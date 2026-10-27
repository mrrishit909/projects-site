"""The Python side of the reconciliation of docs/sql-analysis.md (P05-ART-04): every result set of the eight investigations, recomputed
from the published snapshot ``web/public/data`` WITHOUT PostgreSQL, so that run_all.py (and tests/test_artifacts.py, which runs it again
without a database) can compare it cell by cell with what the SQL returns.

Independence: the SQL derives the book from facts in one recursive query (00_book.sql, a copy of data/sql/reference_metrics.sql); this
file derives it with the Python domain (``invoicebridge.book.derive``, a different implementation of the same contract) and aggregates with
exact arithmetic (Decimal and Fraction, never float; half-up rounding as PostgreSQL's ``round``), sharing no query text and no helper
with the SQL. The two stored sources that are not facts (the exception history and its assignments) are read from the published JSON
rows exactly as ``prepare_snapshot.py`` loads them into the database.

Every block function returns a list of dicts whose keys are the SQL column names, in the SQL ``ORDER BY`` order; ``norm`` renders a
value the way ``run_all.py`` renders a database value (None -> '', datetimes in UTC with a Z, Decimals with their scale).
"""
from __future__ import annotations

import json
import re
import sys
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from invoicebridge.amounts import normalise_number  # noqa: E402
from invoicebridge.book import derive, effective_policy, role_may_approve  # noqa: E402
from invoicebridge.ingest import validate_batch  # noqa: E402
from invoicebridge.match import quantities  # noqa: E402,F401
from invoicebridge.models import Assignment, ExceptionRecord  # noqa: E402
from invoicebridge.money import frac_str  # noqa: E402
from invoicebridge.pipeline import validate_population  # noqa: E402
from invoicebridge.timeutil import parse_ts  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
C1, C2, ASOF = "2026-03-31T23:59:59Z", "2026-06-30T23:59:59Z", "2026-10-01T02:00:00Z"
CUTOFFS = (C1, C2, ASOF)
ENTITIES = ["vendors", "purchase_orders", "po_lines", "receipts", "invoices", "invoice_lines", "credit_notes", "approval_policies",
            "approvals", "export_requests", "exceptions", "exception_assignments"]
REASONS = ("QUANTITY_BLOCKED", "PRICE_VARIANCE", "NO_PO_LINE", "ROUNDING_EXCEPTION", "CURRENCY_MISMATCH")
BLOCKS: dict[str, Callable[["Ctx"], list[dict[str, Any]]]] = {}
KEYS: list[str] = []


def norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


def rnd(x: Fraction | Decimal | int, places: int) -> Decimal:
    """Half-up (away from zero) rounding to ``places`` decimals, exact, as a Decimal that carries its scale."""
    f = Fraction(x)
    return Decimal(frac_str(f, places))


def block(key: str):
    def deco(fn):
        BLOCKS[key] = fn
        KEYS.append(key)
        return fn
    return deco


class Ctx:
    """The snapshot, its population (with the stored exception history) and the book at each cutoff."""


def load() -> Ctx:
    c = Ctx()
    c.manifest = json.loads((DATA / "manifest.json").read_text())
    c.rows = {e: json.loads((DATA / f"{e}.json").read_text())["rows"] for e in ENTITIES + ["export_batches"]}
    c.inputs = {"contract_version": 1, "as_of": c.manifest["as_of"], "snapshot_cutoffs": c.manifest["snapshot_cutoffs"],
                "tolerances": c.manifest["tolerances"],
                **{e: c.rows[e] for e in ENTITIES if e not in ("exceptions", "exception_assignments")}}
    c.ingest = validate_batch(c.inputs)
    c.pop = validate_population(c.ingest.population())
    c.pop.exceptions = [ExceptionRecord(r["exception_id"], r["invoice_id"], r["exception_type"]) for r in c.rows["exceptions"]]
    c.pop.assignments = [Assignment(r["exception_id"], r["owner_id"], parse_ts(r["assigned_at"])) for r in c.rows["exception_assignments"]]
    c.books = {k: derive(c.pop, parse_ts(k)) for k in CUTOFFS}
    c.book = c.books[ASOF]
    c.asof = parse_ts(ASOF)
    c.inv = {i.invoice_id: i for i in c.pop.invoices}
    c.vendor = {v.vendor_id: v for v in c.pop.vendors}
    c.po_vendor = {p.po_id: p.vendor_id for p in c.pop.purchase_orders}
    c.po_cur = {p.po_id: p.currency for p in c.pop.purchase_orders}
    c.pol = {l.po_line_id: l for l in c.pop.po_lines}
    c.exc = [{**r, "created": parse_ts(r["created_at"]), "resolved": parse_ts(r["resolved_at"]) if r["resolved_at"] else None}
             for r in c.rows["exceptions"]]
    c.asg = [{**r, "at": parse_ts(r["assigned_at"])} for r in c.rows["exception_assignments"]]
    return c


def group_of(vendor_id: str) -> str:
    if "ven-020" <= vendor_id <= "ven-029":
        return "ven-02x"
    return "ven-007" if vendor_id == "ven-007" else "other vendors"


def iso(c: str) -> datetime:
    return parse_ts(c)


def run_of(x: Ctx, cutoff: str):
    return x.books[cutoff].run


def is_open(e: dict, c: datetime) -> bool:
    return e["created"] <= c and (e["resolved"] is None or e["resolved"] > c)


# ===================================================== 01 =============================================================
F01 = "01_match_outcomes_by_vendor_and_reason__"


@block(F01 + "reason_open_vs_ever")
def b01a(x: Ctx):
    open_n = {r: 0 for r in REASONS}
    for e in x.book.exceptions:
        open_n[e["exception_type"]] += 1
    out = []
    tot_raised = tot_resolved = 0
    for r in REASONS:
        rows = [e for e in x.rows["exceptions"] if e["exception_type"] == r]
        raised, resolved = len(rows), sum(1 for e in rows if e["status"] == "resolved")
        tot_raised += raised
        tot_resolved += resolved
        out.append({"reason": r, "open_at_cutoff": open_n[r], "ever_raised": raised, "ever_resolved": resolved,
                    "ever_invoices": len({e["invoice_id"] for e in rows}),
                    "open_share_of_ever": None if raised == 0 else rnd(Fraction(open_n[r], raised), 6)})
    out.append({"reason": "ALL", "open_at_cutoff": sum(open_n.values()), "ever_raised": tot_raised, "ever_resolved": tot_resolved,
                "ever_invoices": len({e["invoice_id"] for e in x.rows["exceptions"]}),
                "open_share_of_ever": rnd(Fraction(sum(open_n.values()), tot_raised), 6)})
    return out


@block(F01 + "vendor_group_open_vs_ever")
def b01b(x: Ctx):
    run = run_of(x, ASOF)
    hist = {(e["invoice_id"], e["exception_type"]) for e in x.rows["exceptions"]}
    g: dict[str, list] = {}
    for iid in x.book.in_book:
        r = run.invoices[iid]
        qb_o, pv_o = "QUANTITY_BLOCKED" in r.reasons, "PRICE_VARIANCE" in r.reasons
        g.setdefault(group_of(x.inv[iid].vendor_id), []).append(
            (qb_o, pv_o, qb_o or (iid, "QUANTITY_BLOCKED") in hist, pv_o or (iid, "PRICE_VARIANCE") in hist))
    out = []
    for name in sorted(g):
        v = g[name]
        n = len(v)
        qo, qe = sum(1 for t in v if t[0]), sum(1 for t in v if t[2])
        out.append({"vendor_group": name, "invoices_in_book": n, "quantity_blocked_open": qo,
                    "quantity_blocked_open_rate": rnd(Fraction(qo, n), 6), "quantity_blocked_ever": qe,
                    "quantity_blocked_ever_rate": rnd(Fraction(qe, n), 6), "price_variance_open": sum(1 for t in v if t[1]),
                    "price_variance_ever": sum(1 for t in v if t[3])})
    return out


@block(F01 + "by_vendor")
def b01c(x: Ctx):
    run = run_of(x, ASOF)
    hist_inv = {e["invoice_id"] for e in x.rows["exceptions"]}
    out = []
    for v in sorted(x.pop.vendors, key=lambda v: v.vendor_id):
        mine = [i for i in x.book.in_book if x.inv[i].vendor_id == v.vendor_id]
        m = [i for i in mine if run.invoices[i].matched]
        out.append({"vendor_id": v.vendor_id, "currency": v.currency, "vendor_group": group_of(v.vendor_id), "invoices_in_book": len(mine),
                    "matched_at_cutoff": len(m), "with_open_exception": len(mine) - len(m),
                    "matched_after_an_exception": sum(1 for i in m if i in hist_inv)})
    return out


@block(F01 + "by_currency")
def b01d(x: Ctx):
    run = run_of(x, ASOF)
    out = []
    for cur in sorted({x.inv[i].currency for i in x.book.in_book}):
        mine = [i for i in x.book.in_book if x.inv[i].currency == cur]
        m = [i for i in mine if run.invoices[i].matched]
        out.append({"currency": cur, "invoices_in_book": len(mine), "matched_at_cutoff": len(m),
                    "matched_total": rnd(sum((run.invoices[i].total for i in m), Decimal(0)), 2) if m else None,
                    "with_open_exception": len(mine) - len(m)})
    return out


@block(F01 + "history_by_vendor_group")
def b01e(x: Ctx):
    run = run_of(x, ASOF)
    out = []
    for reason in ("PRICE_VARIANCE", "QUANTITY_BLOCKED"):
        raised: dict[str, list] = {}
        for e in x.rows["exceptions"]:
            if e["exception_type"] == reason:
                raised.setdefault(group_of(x.inv[e["invoice_id"]].vendor_id), []).append(e["invoice_id"])
        open_n: dict[str, int] = {}
        for iid in x.book.in_book:
            if reason in run.invoices[iid].reasons:
                g = group_of(x.inv[iid].vendor_id)
                open_n[g] = open_n.get(g, 0) + 1
        for g in sorted(raised):
            out.append({"vendor_group": g, "reason": reason, "ever_raised_rows": len(raised[g]), "ever_raised_invoices": len(set(raised[g])),
                        "open_at_cutoff": open_n.get(g, 0)})
    return out


@block(F01 + "rates_by_currency")
def b01f(x: Ctx):
    run = run_of(x, ASOF)
    hist = {e["invoice_id"] for e in x.rows["exceptions"]}
    out = []
    for cur in sorted({x.inv[i].currency for i in x.book.in_book}):
        mine = [i for i in x.book.in_book if x.inv[i].currency == cur]
        n = len(mine)
        blocked = sum(1 for i in mine if run.invoices[i].reasons)
        ever = sum(1 for i in mine if run.invoices[i].reasons or i in hist)
        out.append({"currency": cur, "invoices_in_book": n, "blocked_at_cutoff": blocked, "ever_excepted": ever,
                    "straight_through_rate": rnd(Fraction(n - blocked, n), 6), "never_excepted_rate": rnd(Fraction(n - ever, n), 6)})
    return out


# ===================================================== 02 =============================================================
F02 = "02_cumulative_consumption_by_po_line__"
STATES = ("nothing_received", "received_none_invoiced", "partly_invoiced", "fully_invoiced", "over_consumed")


def _q4(d: Decimal | Fraction) -> Decimal:
    return rnd(d, 4)


@block(F02 + "totals_by_cutoff")
def b02a(x: Ctx):
    out = []
    for cut in CUTOFFS:
        run = run_of(x, cut)
        per: dict[str, list] = {}
        for k, l in run.po_lines.items():
            per.setdefault(x.po_cur[l.po_id], []).append(k)

        def agg(keys: list[str], money: bool):
            P = run.po_lines
            sq = lambda f: sum((f(k) for k in keys), Decimal(0))  # noqa: E731
            row = {"cutoff": parse_ts(cut), "po_lines": len(keys),
                   "ordered_quantity": _q4(sq(lambda k: P[k].quantity)), "net_received_quantity": _q4(sq(lambda k: run.net[k])),
                   "accepted_invoiced_quantity": _q4(sq(lambda k: run.consumed[k])),
                   "open_to_receive_quantity": _q4(sq(lambda k: max(P[k].quantity - run.net[k], Decimal(0)))),
                   "open_to_invoice_quantity": _q4(sq(lambda k: max(P[k].quantity - run.consumed[k], Decimal(0)))),
                   "received_not_invoiced_quantity": _q4(sq(lambda k: max(run.net[k] - run.consumed[k], Decimal(0))))}
            row["received_not_invoiced_value"] = rnd(sq(lambda k: max(run.net[k] - run.consumed[k], Decimal(0)) * P[k].unit_price), 2) if money else None
            return row
        for cur in sorted(per):
            out.append({"cutoff": parse_ts(cut), "currency": cur, **{k: v for k, v in agg(per[cur], True).items() if k != "cutoff"}})
        out.append({"cutoff": parse_ts(cut), "currency": "ALL", **{k: v for k, v in agg(list(run.po_lines), False).items() if k != "cutoff"}})
    # ORDER BY cutoff, currency ('ALL' sorts before 'EUR')
    out.sort(key=lambda r: (r["cutoff"], r["currency"]))
    return out


@block(F02 + "line_state_by_cutoff")
def b02b(x: Ctx):
    out = []
    for cut in CUTOFFS:
        run = run_of(x, cut)
        cnt = {s: 0 for s in STATES}
        for k in run.po_lines:
            net, used = run.net[k], run.consumed[k]
            s = ("over_consumed" if used > net else "nothing_received" if net == 0 else "received_none_invoiced" if used == 0
                 else "partly_invoiced" if used < net else "fully_invoiced")
            cnt[s] += 1
        out += [{"cutoff": parse_ts(cut), "state": s, "po_lines": cnt[s]} for s in STATES]
    return out


@block(F02 + "ladder_top_lines")
def b02c(x: Ctx):
    r1, r2, r3 = (run_of(x, c) for c in CUTOFFS)
    top = sorted((k for k in r3.po_lines if r3.consumed[k] > 0), key=lambda k: (-r3.consumed[k], k))[:10]
    g = lambda r, d, k: d[k] if k in r.po_lines else Decimal(0)  # noqa: E731
    out = []
    for k in top:
        l = x.pol[k]
        out.append({"po_line_id": k, "vendor_id": x.po_vendor[l.po_id], "currency": x.po_cur[l.po_id], "ordered_quantity": _q4(l.quantity),
                    "net_at_march": _q4(g(r1, r1.net, k)), "invoiced_at_march": _q4(g(r1, r1.consumed, k)),
                    "net_at_june": _q4(g(r2, r2.net, k)), "invoiced_at_june": _q4(g(r2, r2.consumed, k)),
                    "net_at_asof": _q4(g(r3, r3.net, k)), "invoiced_at_asof": _q4(r3.consumed[k])})
    return out


# ===================================================== 03 =============================================================
F03 = "03_duplicates_identity_vs_bytes_and_month_end__"


def month_end(d: datetime) -> bool:
    d = d.astimezone(timezone.utc)
    return monthrange(d.year, d.month)[1] - d.day <= 2


@block(F03 + "merges_by_reason_and_cutoff")
def b03a(x: Ctx):
    out = []
    for cut in CUTOFFS:
        by: dict[str, list] = {}
        for rec in x.books[cut].merged_records:
            by.setdefault(rec["reason_code"], []).append(rec["merged_into"])
        out += [{"cutoff": parse_ts(cut), "reason_code": r, "rows_merged": len(v), "canonical_invoices": len(set(v))} for r, v in sorted(by.items())]
    return out


@block(F03 + "identity_vs_bytes")
def b03b(x: Ctx):
    by: dict[str, list] = {}
    for rec in x.book.merged_records:
        by.setdefault(rec["reason_code"], []).append((x.inv[rec["id"]], x.inv[rec["merged_into"]]))
    out = []
    for r, pairs in sorted(by.items()):
        days = [Fraction((d.imported_at - k.imported_at).days * 86400 + (d.imported_at - k.imported_at).seconds, 86400) for d, k in pairs]
        out.append({"reason_code": r, "rows_merged": len(pairs), "same_source_bytes": sum(1 for d, k in pairs if d.source_sha256 == k.source_sha256),
                    "same_file_name": sum(1 for d, k in pairs if d.source_filename == k.source_filename),
                    "same_vendor": sum(1 for d, k in pairs if d.vendor_id == k.vendor_id),
                    "mean_days_after_canonical": rnd(sum(days, Fraction(0)) / len(days), 4)})
    return out


def _identity_ids(x: Ctx) -> set[str]:
    return {rec["id"] for rec in x.book.merged_records if rec["reason_code"] == "DUPLICATE_IDENTITY"}


@block(F03 + "month_end_clustering")
def b03c(x: Ctx):
    ident = _identity_ids(x)

    def row(name, ids):
        n = len(ids)
        k = sum(1 for i in ids if month_end(x.inv[i].imported_at))
        return {"population": name, "invoices": n, "imported_in_last_three_days": k, "share": rnd(Fraction(k, n), 4)}
    allids = [i.invoice_id for i in x.pop.invoices]
    return [row("merged by identity (re-sent PDFs)", sorted(ident)), row("all invoices", allids),
            row("invoices that are not re-sent copies", [i for i in allids if i not in ident])]


@block(F03 + "merged_by_import_month")
def b03d(x: Ctx):
    by: dict[str, list] = {}
    for i in _identity_ids(x):
        d = x.inv[i].imported_at.astimezone(timezone.utc)
        by.setdefault(d.strftime("%Y-%m"), []).append(d)
    return [{"import_month": m, "rows_merged_by_identity": len(v), "in_last_three_days": sum(1 for d in v if month_end(d))} for m, v in sorted(by.items())]


@block(F03 + "same_number_other_vendor")
def b03e(x: Ctx):
    g: dict[str, list] = {}
    for i in x.pop.invoices:
        g.setdefault(normalise_number(i.invoice_number), []).append(i)
    merged = {rec["id"] for rec in x.book.merged_records}
    return [{"number_norm": n, "invoices": len(v), "vendors": len({i.vendor_id for i in v}), "merged_rows": sum(1 for i in v if i.invoice_id in merged)}
            for n, v in sorted(g.items()) if len({i.vendor_id for i in v}) > 1]


@block(F03 + "lineage_append_only")
def b03f(x: Ctx):
    merged: dict[str, int] = {}
    for rec in x.book.merged_records:
        merged[rec["reason_code"]] = merged.get(rec["reason_code"], 0) + 1
    acc = len(x.pop.invoices) - sum(merged.values())
    rows = [("accepted", "", acc)] + [("merged", r, n) for r, n in merged.items()]
    return [{"import_status": s, "reason_code": r, "lineage_rows": n, "invoices": n} for s, r, n in sorted(rows)]


# ===================================================== 04 =============================================================
F04 = "04_approvals_under_policy_versions__"


def _pol(x: Ctx, at: datetime):
    return effective_policy(x.pop.approval_policies, at)


def _valid_rejects(x: Ctx) -> set[str]:
    bad = {r["approval_id"] for r in x.book.invalid_decisions}
    return {a.approval_id for a in x.pop.approvals if a.decision == "reject" and a.decided_at <= x.asof and a.approval_id not in bad}


@block(F04 + "decisions_by_policy_version")
def b04a(x: Ctx):
    valid_ap = {a.approval_id for a in x.book.first_valid.values()}
    valid_rj = _valid_rejects(x)
    out = []
    for p in sorted(x.pop.approval_policies, key=lambda p: p.version_number):
        mine = [a for a in x.pop.approvals if _pol(x, a.decided_at) == p]
        if not mine:
            continue
        out.append({"policy_id": p.policy_id, "version_number": p.version_number, "amount_limit": p.amount_limit,
                    "approve_decisions": sum(1 for a in mine if a.decision == "approve"),
                    "valid_approvals": sum(1 for a in mine if a.approval_id in valid_ap),
                    "reject_decisions": sum(1 for a in mine if a.decision == "reject"),
                    "valid_rejections": sum(1 for a in mine if a.approval_id in valid_rj)})
    return out


def _committed(x: Ctx):
    run = run_of(x, ASOF)
    for iid, a in x.book.first_valid.items():
        yield iid, a, x.inv[iid], run.invoices[iid].total, _pol(x, a.decided_at)


@block(F04 + "approvals_by_policy_and_currency")
def b04b(x: Ctx):
    g: dict[tuple, list] = {}
    for iid, a, inv, total, p in _committed(x):
        g.setdefault((p.policy_id, inv.currency), []).append((total, a.decided_at - inv.imported_at))
    out = []
    for (pid, cur), v in sorted(g.items()):
        mins = [Fraction(d.days * 86400 + d.seconds, 60) for _, d in v]
        out.append({"policy_id": pid, "currency": cur, "valid_approvals": len(v), "approved_total": rnd(sum((t for t, _ in v), Decimal(0)), 2),
                    "largest_invoice": rnd(max(t for t, _ in v), 2), "mean_minutes_to_approval": rnd(sum(mins, Fraction(0)) / len(mins), 4)})
    return out


@block(F04 + "approval_time_by_currency")
def b04g(x: Ctx):
    g: dict[str, list] = {}
    for iid, a, inv, total, p in _committed(x):
        d = a.decided_at - inv.imported_at
        g.setdefault(inv.currency, []).append(Fraction(d.days * 86400 + d.seconds, 60))
    return [{"currency": c, "valid_approvals": len(v), "mean_minutes_to_approval": rnd(sum(v, Fraction(0)) / len(v), 4), "longest_minutes": rnd(max(v), 4)}
            for c, v in sorted(g.items())]


@block(F04 + "limit_bands")
def b04c(x: Ctx):
    g: dict[tuple, int] = {}
    for iid, a, inv, total, p in _committed(x):
        band = "total up to 5000.00" if total <= 5000 else "total above 5000.00 up to 8000.00"
        g[(p.policy_id, band, inv.currency)] = g.get((p.policy_id, band, inv.currency), 0) + 1
    return [{"policy_id": p, "band": b, "currency": c, "valid_approvals": n} for (p, b, c), n in sorted(g.items())]


@block(F04 + "matched_not_approved_over_limit")
def b04d(x: Ctx):
    run = run_of(x, ASOF)
    limit = _pol(x, x.asof).amount_limit
    g: dict[str, list] = {}
    for iid in x.book.in_book:
        r = run.invoices[iid]
        if r.matched and iid not in x.book.first_valid:
            g.setdefault(x.inv[iid].currency, []).append(r.total)
    return [{"currency": c, "matched_not_approved": len(v), "above_the_limit": sum(1 for t in v if t > limit),
             "above_the_limit_total": rnd(sum((t for t in v if t > limit), Decimal(0)), 2) if any(t > limit for t in v) else None}
            for c, v in sorted(g.items())]


@block(F04 + "v1_counterfactual")
def b04e(x: Ctx):
    g: dict[str, int] = {}
    cut = parse_ts("2026-04-01T00:00:00Z")
    for iid, a, inv, total, p in _committed(x):
        if a.decided_at >= cut and total > 5000:
            g[inv.currency] = g.get(inv.currency, 0) + 1
    return [{"statement": "HYPOTHETICAL: approvals under pol-v2 above the pol-v1 limit", "currency": c, "approvals": n} for c, n in sorted(g.items())]


@block(F04 + "separation_of_duties")
def b04f(x: Ctx):
    run = run_of(x, ASOF)
    creators = {i.created_by for i in x.pop.invoices}
    ap = [a for a in x.pop.approvals if a.decision == "approve"]
    rj = [a for a in x.pop.approvals if a.decision == "reject"]

    def role_or_limit(a) -> bool:
        r = run.invoices.get(a.invoice_id)
        return r is not None and not role_may_approve(_pol(x, a.decided_at), a.actor_role, r.total)
    deciders = {a.actor_id for a in x.pop.approvals}
    rows = [("approve decisions recorded", len(ap)),
            ("approve decisions that are policy-valid (the committed invoices)", len(x.book.first_valid)),
            ("SELF_APPROVAL: approver is the invoice creator", sum(1 for a in ap if a.actor_id == x.inv[a.invoice_id].created_by)),
            ("ROLE_OR_LIMIT: role not allowed, or total above the limit in force", sum(1 for a in ap if role_or_limit(a))),
            ("BEFORE_IMPORT: decided before the invoice was imported", sum(1 for a in ap if a.decided_at < x.inv[a.invoice_id].imported_at)),
            ("reject decisions recorded", len(rj)),
            ("reject decisions that are valid", len(_valid_rejects(x))),
            ("SELF_DECISION: rejecter is the invoice creator", sum(1 for a in rj if a.actor_id == x.inv[a.invoice_id].created_by)),
            ("deciding actors who also created other invoices (allowed: the rule is per invoice)", len(deciders & creators)),
            ("distinct deciding actors", len(deciders)),
            ("distinct invoice creators", len(creators))]
    return [{"check_name": n, "n": v} for n, v in rows]


# ===================================================== 05 =============================================================
F05 = "05_exception_backlog_and_assignment_history__"


def _owned(x: Ctx, e: dict, c: datetime) -> bool:
    return any(a["exception_id"] == e["exception_id"] and a["at"] <= c for a in x.asg)


@block(F05 + "backlog_at_cutoffs")
def b05a(x: Ctx):
    out = []
    first_by_exc: dict[str, list[datetime]] = {}
    for a in x.asg:
        first_by_exc.setdefault(a["exception_id"], []).append(a["at"])
    for cut in CUTOFFS:
        c = parse_ts(cut)
        h = [e for e in x.exc if is_open(e, c)]
        owned = sum(1 for e in h if any(t <= c for t in first_by_exc.get(e["exception_id"], [])))
        facts = sum(len(r.reasons) for r in x.books[cut].run.invoices.values())
        out.append({"cutoff": c, "open_from_history": len(h), "open_from_facts": facts, "difference": facts - len(h),
                    "owned_from_history": owned, "unowned_from_history": len(h) - owned})
    return out


@block(F05 + "open_by_reason_and_age")
def b05b(x: Ctx):
    g: dict[str, list[int]] = {}
    for e in x.exc:
        if is_open(e, x.asof):
            delta = x.asof - e["created"]
            g.setdefault(e["exception_type"], []).append((delta.days * 86400 + delta.seconds) // 86400)
    return [{"reason": r, "open_exceptions": len(a), "age_0_to_6_days": sum(1 for d in a if d < 7), "age_7_to_13_days": sum(1 for d in a if 7 <= d <= 13),
             "age_14_to_29_days": sum(1 for d in a if 14 <= d <= 29), "age_30_days_or_more": sum(1 for d in a if d >= 30), "oldest_days": max(a)}
            for r, a in sorted(g.items())]


@block(F05 + "assignments_per_exception")
def b05c(x: Ctx):
    n_by: dict[str, int] = {}
    for a in x.asg:
        n_by[a["exception_id"]] = n_by.get(a["exception_id"], 0) + 1
    g: dict[int, list[bool]] = {}
    for e in x.exc:
        g.setdefault(n_by.get(e["exception_id"], 0), []).append(is_open(e, x.asof))
    return [{"assignments": n, "exceptions": len(v), "open_at_cutoff": sum(1 for o in v if o), "resolved": sum(1 for o in v if not o)} for n, v in sorted(g.items())]


@block(F05 + "first_assignment_and_resolution")
def b05d(x: Ctx):
    first: dict[str, datetime] = {}
    for a in x.asg:
        if a["exception_id"] not in first or a["at"] < first[a["exception_id"]]:
            first[a["exception_id"]] = a["at"]
    g: dict[str, list] = {}
    for e in x.exc:
        g.setdefault(e["exception_type"], []).append(e)
    out = []
    for r, v in sorted(g.items()):
        hrs = [Fraction(((first[e["exception_id"]] - e["created"]).days * 86400 + (first[e["exception_id"]] - e["created"]).seconds), 3600)
               for e in v if e["exception_id"] in first]
        days = [Fraction(((e["resolved"] - e["created"]).days * 86400 + (e["resolved"] - e["created"]).seconds), 86400) for e in v if e["resolved"]]
        out.append({"reason": r, "exceptions": len(v), "with_an_assignment": len(hrs),
                    "mean_hours_to_first_assignment": rnd(sum(hrs, Fraction(0)) / len(hrs), 4) if hrs else None,
                    "resolved": len(days), "mean_days_to_resolution": rnd(sum(days, Fraction(0)) / len(days), 4) if days else None})
    return out


@block(F05 + "owner_workload_at_cutoff")
def b05e(x: Ctx):
    latest: dict[str, tuple] = {}
    for a in x.asg:
        if a["at"] <= x.asof:
            k = (a["at"], a["assignment_id"])
            if a["exception_id"] not in latest or k > latest[a["exception_id"]][0]:
                latest[a["exception_id"]] = (k, a["owner_id"])
    g: dict[str, int] = {}
    for e in x.exc:
        if is_open(e, x.asof):
            o = latest[e["exception_id"]][1] if e["exception_id"] in latest else "unowned"
            g[o] = g.get(o, 0) + 1
    return [{"owner": o, "open_exceptions": n} for o, n in sorted(g.items(), key=lambda t: (-t[1], t[0]))]


# ===================================================== 06 =============================================================
F06 = "06_export_batches_and_reconciliation__"


def _lag_days(a: datetime, b: datetime) -> Fraction:
    d = b - a
    return Fraction(d.days * 86400 + d.seconds, 86400)


@block(F06 + "batch_summary")
def b06a(x: Ctx):
    b = x.book
    named = {i for r in x.pop.export_requests if r.exported_at <= x.asof for i in r.invoice_ids}
    rows = [("requests received", b.export_stats["requests_received"]), ("batches created (non-repeat requests)", b.export_stats["batches_created"]),
            ("repeat requests answered with the prior batch", b.export_stats["repeat_requests_returned_prior"]),
            ("export rows (invoices exported)", len(b.export_rows)), ("distinct invoices named by any request", len(named)),
            ("stored export_batches rows (cross-check)", len(x.rows["export_batches"])),
            ("stored export_rows rows (cross-check)", len(b.export_rows))]
    return [{"measure": m, "n": n} for m, n in rows]


@block(F06 + "reconciliation_by_currency")
def b06b(x: Ctx):
    run = run_of(x, ASOF)
    ex: dict[str, list[Decimal]] = {}
    for r in x.book.export_rows:
        ex.setdefault(r["currency"], []).append(Decimal(r["amount"]))
    ob: dict[str, list[Decimal]] = {}
    for iid in x.book.approved:
        ob.setdefault(x.inv[iid].currency, []).append(run.invoices[iid].total)
    out = []
    for cur in sorted(set(ex) | set(ob)):
        e, o = ex.get(cur, []), ob.get(cur, [])
        out.append({"currency": cur, "exported_invoices": len(e), "accepted_export_total": rnd(sum(e, Decimal(0)), 2), "approved_invoices": len(o),
                    "eligible_approved_total": rnd(sum(o, Decimal(0)), 2), "difference": rnd(sum(e, Decimal(0)) - sum(o, Decimal(0)), 2)})
    return out


@block(F06 + "exclusions_by_reason_and_currency")
def b06c(x: Ctx):
    run = run_of(x, ASOF)
    exported = set(x.book.exported)
    late = set(x.book.export_late)
    g: dict[tuple, list] = {}
    for iid in x.book.in_book:
        if iid in exported:
            continue
        approved = iid in x.book.first_valid
        r = run.invoices[iid]
        if not approved and not r.matched:
            code = "EXCEPTION_OPEN"
        elif not approved:
            code = "NOT_APPROVED"
        elif iid in late:
            code = "EXPORT_BEFORE_APPROVAL"
        else:
            code = "APPROVED_NOT_EXPORTED"
        g.setdefault((code, x.inv[iid].currency), []).append(r.total)
    return [{"reason_code": c, "currency": cur, "invoices": len(v), "invoice_total": rnd(sum(v, Decimal(0)), 2)} for (c, cur), v in sorted(g.items())]


@block(F06 + "batch_cadence")
def b06d(x: Ctx):
    g: dict[str, list[int]] = {}
    for r, rep in x.book.export_log:
        if not rep:
            g.setdefault(r.exported_at.astimezone(timezone.utc).strftime("%a %H:%M"), []).append(len(r.invoice_ids))
    return [{"weekday_and_time": k, "batches": len(v), "fewest_invoices": min(v), "most_invoices": max(v), "mean_invoices": rnd(Fraction(sum(v), len(v)), 4)}
            for k, v in sorted(g.items())]


@block(F06 + "repeat_requests")
def b06e(x: Ctx):
    out = []
    for r, rep in x.book.export_log:
        if rep:
            first = next(q for q in x.pop.export_requests if q.batch_id == r.batch_id)
            out.append({"batch_id": r.batch_id, "idempotency_key": r.idempotency_key, "invoices_named": len(r.invoice_ids),
                        "seconds_after_first_request": int((r.exported_at - first.exported_at).total_seconds())})
    return sorted(out, key=lambda r: r["batch_id"])


@block(F06 + "approval_to_export_lag")
def b06f(x: Ctx):
    g: dict[str, list] = {}
    for r in x.book.export_rows:
        iid = r["invoice_id"]
        g.setdefault(x.inv[iid].currency, []).append(_lag_days(x.book.first_valid[iid].decided_at, parse_ts(r["exported_at"])))
    return [{"currency": c, "exported_invoices": len(v), "mean_days_approval_to_export": rnd(sum(v, Fraction(0)) / len(v), 4), "longest_days": rnd(max(v), 4)}
            for c, v in sorted(g.items())]


# ===================================================== 07 =============================================================
F07 = "07_credits_and_payable_by_currency__"


def _applied_credits(x: Ctx):
    return [cn for cn in x.pop.credit_notes if (cn.credited_at is None or cn.credited_at <= x.asof) and cn.invoice_id in x.book.first_valid]


@block(F07 + "payable_by_currency")
def b07a(x: Ctx):
    run = run_of(x, ASOF)
    ob: dict[str, list] = {}
    for iid in x.book.first_valid:
        ob.setdefault(x.inv[iid].currency, []).append(run.invoices[iid].total)
    cr: dict[str, list] = {}
    for cn in _applied_credits(x):
        cr.setdefault(x.inv[cn.invoice_id].currency, []).append(cn)
    out = []
    for cur in sorted(ob):
        tot = sum(ob[cur], Decimal(0))
        c = cr.get(cur, [])
        ctot = sum((cn.credit_amount for cn in c), Decimal(0))
        out.append({"currency": cur, "obligations": len(ob[cur]), "approved_total": rnd(tot, 2), "credit_notes": len(c),
                    "invoices_credited": len({cn.invoice_id for cn in c}), "credit_total": rnd(ctot, 2), "approved_payable": rnd(tot - ctot, 2),
                    "credit_share_of_approved_total": rnd(Fraction(ctot) / Fraction(tot), 6)})
    return out


@block(F07 + "credit_share_of_invoices")
def b07b(x: Ctx):
    rows = [("invoices carrying at least one credit note", len({cn.invoice_id for cn in x.pop.credit_notes})), ("credit notes", len(x.pop.credit_notes)),
            ("invoices imported (denominator of the 4.0 % claim)", len(x.pop.invoices)),
            ("obligations at the as-of (denominator of the 4.9 % reading)", len(x.book.first_valid)),
            ("credit notes against an invoice that is not an obligation", sum(1 for cn in x.pop.credit_notes if cn.invoice_id not in x.book.first_valid))]
    return [{"measure": m, "n": n} for m, n in rows]


@block(F07 + "credits_per_invoice")
def b07c(x: Ctx):
    n: dict[str, int] = {}
    for cn in x.pop.credit_notes:
        n[cn.invoice_id] = n.get(cn.invoice_id, 0) + 1
    g: dict[int, int] = {}
    for v in n.values():
        g[v] = g.get(v, 0) + 1
    return [{"credit_notes_on_the_invoice": k, "invoices": v} for k, v in sorted(g.items())]


@block(F07 + "credit_size_by_currency")
def b07d(x: Ctx):
    run = run_of(x, ASOF)
    cum: dict[str, Decimal] = {}
    for cn in x.pop.credit_notes:
        if cn.invoice_id in run.invoices:
            cum[cn.invoice_id] = cum.get(cn.invoice_id, Decimal(0)) + cn.credit_amount
    g: dict[str, list] = {}
    for iid, cr in cum.items():
        g.setdefault(x.inv[iid].currency, []).append((Fraction(cr) / Fraction(run.invoices[iid].total), cr > run.invoices[iid].total))
    return [{"currency": c, "invoices_credited": len(v), "smallest_share": rnd(min(s for s, _ in v), 6),
             "mean_share": rnd(sum((s for s, _ in v), Fraction(0)) / len(v), 6), "largest_share": rnd(max(s for s, _ in v), 6),
             "credited_above_the_invoice_total": sum(1 for _, o in v if o)} for c, v in sorted(g.items())]


# ===================================================== 08 =============================================================
F08 = "08_rejections_and_injected_defects_by_reason__"


@block(F08 + "ingest_outcomes")
def b08a(x: Ctx):
    merged: dict[str, int] = {}
    for rec in x.book.merged_records:
        merged[rec["reason_code"]] = merged.get(rec["reason_code"], 0) + 1
    rj = [a for a in x.pop.approvals if a.decision == "reject"]
    valid = len(_valid_rejects(x))
    rows = [("import lineage: accepted", len(x.pop.invoices) - sum(merged.values())), ("import lineage: merged (DUPLICATE_IDENTITY)", merged.get("DUPLICATE_IDENTITY", 0)),
            ("import lineage: merged (DUPLICATE_SOURCE_BYTES)", merged.get("DUPLICATE_SOURCE_BYTES", 0)),
            ("rejected_records kept (ingest rejections)", len(x.ingest.rejected)), ("reject decisions (C08) recorded", len(rj)),
            ("reject decisions that are valid", valid), ("reject decisions refused (invalid)", len(rj) - valid)]
    return [{"outcome": o, "n": n} for o, n in rows]


@block(F08 + "reject_decisions_by_reason")
def b08b(x: Ctx):
    run = run_of(x, ASOF)
    valid = _valid_rejects(x)
    et: dict[str, list[str]] = {}
    resolved: set[str] = set()
    for e in x.rows["exceptions"]:
        et.setdefault(e["invoice_id"], []).append(e["exception_type"])
        if e["resolved_at"]:
            resolved.add(e["invoice_id"])
    g: dict[tuple, list] = {}
    for a in x.pop.approvals:
        if a.decision != "reject":
            continue
        k = (a.reason, min(et[a.invoice_id]) if a.invoice_id in et else "none")
        g.setdefault(k, []).append((a.approval_id in valid, a.invoice_id in run.invoices, a.invoice_id in resolved))
    return [{"reviewer_reason": r, "exception_type_in_history": t, "reject_decisions": len(v), "valid": sum(1 for s in v if s[0]),
             "still_in_the_book": sum(1 for s in v if s[1]), "with_a_resolved_exception": sum(1 for s in v if s[2])} for (r, t), v in sorted(g.items())]


def _outside_02x_open_qb(x: Ctx) -> list[str]:
    run = run_of(x, ASOF)
    return sorted(i for i in x.book.in_book if "QUANTITY_BLOCKED" in run.invoices[i].reasons and not ("ven-020" <= x.inv[i].vendor_id <= "ven-029"))


def _cumulative_candidates(x: Ctx) -> list[str]:
    run = run_of(x, ASOF)
    net_to_date = {}
    for r in x.pop.receipts:
        if not r.reversed and r.received_at <= x.asof:
            net_to_date[r.po_line_id] = net_to_date.get(r.po_line_id, Decimal(0)) + r.received_quantity
    inv_line = {l.invoice_line_id: l for i in x.pop.invoices for l in i.lines}
    out = set()
    for lr in run.lines:
        if lr.reason_code == "QUANTITY_BLOCKED":
            iid = lr.invoice_id
            if "ven-020" <= x.inv[iid].vendor_id <= "ven-029":
                continue
            if inv_line[lr.invoice_line_id].quantity <= net_to_date.get(lr.po_line_id, Decimal(0)):
                out.add(iid)
    return sorted(out)


@block(F08 + "injected_defect_signatures")
def b08c(x: Ctx):
    run = run_of(x, ASOF)
    by_sha: dict[str, int] = {}
    for i in x.pop.invoices:
        by_sha[i.source_sha256] = by_sha.get(i.source_sha256, 0) + 1
    num: dict[str, set] = {}
    for i in x.pop.invoices:
        num.setdefault(normalise_number(i.invoice_number), set()).add(i.vendor_id)
    ap = [a for a in x.pop.approvals if a.decision == "approve"]
    per_inv: dict[str, int] = {}
    for a in ap:
        per_inv[a.invoice_id] = per_inv.get(a.invoice_id, 0) + 1
    cred_ids: dict[str, int] = {}
    for cn in x.pop.credit_notes:
        cred_ids[cn.credit_id] = cred_ids.get(cn.credit_id, 0) + 1
    cur_mismatch = {i.invoice_id for i in x.pop.invoices for l in i.lines
                    if l.po_line_id in x.pol and x.po_cur[x.pol[l.po_line_id].po_id] != i.currency}
    declared = sum(1 for iid in x.book.in_book if abs(x.inv[iid].declared_total - run.invoices[iid].total) > Decimal("0.02"))
    seen_k, seen_b, rep = set(), set(), 0
    for r in x.pop.export_requests:
        if r.idempotency_key in seen_k or r.batch_id in seen_b:
            rep += 1
        seen_k.add(r.idempotency_key)
        seen_b.add(r.batch_id)
    lineage = {}
    for i in x.pop.invoices:
        lineage[i.invoice_id] = lineage.get(i.invoice_id, 0) + 1
    migrations = " ".join(p.read_text().lower() for p in sorted((ROOT / "data" / "migrations").glob("*.sql")))
    paid_cols = len(re.findall(r"\b(is_paid|paid_at|paid)\s+(boolean|timestamptz|text|bool)", migrations))
    rows = [
        ("INJ-01", "groups of invoices that share source bytes under different ids", sum(1 for n in by_sha.values() if n > 1), False),
        ("INJ-02", "normalised invoice numbers shared by invoices of different vendors", sum(1 for v in num.values() if len(v) > 1), False),
        ("INJ-03", "invoices with an open QUANTITY_BLOCKED outside vendors ven-020 .. ven-029 (a superset: the receipt is short, nothing follows)",
         len(_outside_02x_open_qb(x)), False),
        ("INJ-04", "invoices outside ven-020 .. ven-029 with an open QUANTITY_BLOCKED line whose own quantity is within what was received "
                   "(blocked by earlier consumption; a superset)", len(_cumulative_candidates(x)), False),
        ("INJ-05", "invoices whose declared total differs from the computed total by more than 0.02", declared, False),
        ("INJ-06", "approvals by the invoice creator (self-approval attempt)", sum(1 for a in ap if a.actor_id == x.inv[a.invoice_id].created_by), True),
        ("INJ-07", "invoices with more than one approve decision (racing approvals)", sum(1 for n in per_inv.values() if n > 1), True),
        ("INJ-08", "credit notes beyond the first for one credit id (a credit applied twice)", sum(1 for n in cred_ids.values() if n > 1), True),
        ("INJ-09", "invoices with a line in a currency other than its purchase order's", len(cur_mismatch), False),
        ("INJ-10", "invoice ids with more than one stored version (a correction overwriting the original)", sum(1 for n in lineage.values() if n > 1), True),
        ("INJ-11", "export requests repeated after a timeout (same batch id and key, later exported_at)", rep, False),
        ("INJ-12", "export batches carrying a paid flag (the schema has no such column)", paid_cols, True)]
    return [{"inj": a, "signature": b, "found": c, "replay_only": d} for a, b, c, d in rows]


@block(F08 + "open_quantity_blocked_outside_02x")
def b08d(x: Ctx):
    return [{"invoice_id": i, "vendor_id": x.inv[i].vendor_id} for i in _outside_02x_open_qb(x)]


@block(F08 + "cumulative_blocked_candidates")
def b08e(x: Ctx):
    return [{"invoice_id": i, "vendor_id": x.inv[i].vendor_id} for i in _cumulative_candidates(x)]


def compute(x: Ctx) -> dict[str, list[dict[str, Any]]]:
    return {k: BLOCKS[k](x) for k in KEYS}


def normalised(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{k: norm(v) for k, v in r.items()} for r in rows]
