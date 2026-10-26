"""Metrics (P05-MET-01..12) from a derived book: exactly the keys of ``expected.json["metrics"]``.

``compute_metrics(pop, as_of, cutoffs)`` is the whole population at one instant. A window ``[from, to)`` restricts the
cohort to invoices imported in it (matching still runs on the whole book so consumption is right); ``group_by`` splits
the cohort by vendor or currency. ``snapshots`` re-run the open quantities as of each cutoff (D-P5-15).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any, Callable, Sequence

from .book import Book, derive
from .contract import EXCEPTION_CODES, METRIC_KEYS, RULE_VERSION
from .errors import (APPROVED_NOT_EXPORTED, EXCEPTION_OPEN, EXPORT_BEFORE_APPROVAL, INVALID_GROUP, INVALID_WINDOW,
                     NOT_APPROVED, DomainError)
from .match import quantities
from .money import D0, exact, frac_str, s2
from .models import ExportRequest, Population
from .timeutil import iso_z, minutes_between

GROUPS = ("none", "vendor", "currency")


def check_window(lo: datetime | None, hi: datetime | None) -> None:
    if lo is not None and hi is not None and lo >= hi:
        raise DomainError(INVALID_WINDOW, "from must be before to (the window is half-open)", "from")


@exact
def metrics_from_book(pop: Population, book: Book, cutoffs: Sequence[datetime] = (),
                      cohort: set[str] | None = None, po_filter: set[str] | None = None,
                      requests: list[tuple[ExportRequest, bool]] | None = None) -> dict[str, Any]:
    """The eleven metrics. ``cohort`` limits the invoice-level metrics to those invoice ids (None: all);
    ``po_filter`` limits the quantity metrics to those PO lines; ``requests`` is the (request, repeat) log the export
    counts are taken from (default: every request at the cutoff, or those naming a cohort invoice)."""
    run = book.run

    def inc(iid: str) -> bool:
        return cohort is None or iid in cohort

    cur = {i: book.invoices[i].currency for i in book.in_book}
    good = [i for i in book.in_book if inc(i) and book.status[i] in ("matched", "approved", "exported", "adjusted")]
    sub_t = sum((run.invoices[i].subtotal for i in good), D0)
    tax_t = sum((run.invoices[i].tax for i in good), D0)
    tot_t = sum((run.invoices[i].total for i in good), D0)
    oblig = [i for i in good if book.status[i] in ("approved", "exported", "adjusted")]
    oblig_t = sum((run.invoices[i].total for i in oblig), D0)

    by_reason = {c: 0 for c in EXCEPTION_CODES}
    records = [e for e in book.exceptions if inc(e["invoice_id"])]
    for e in records:
        by_reason[e["exception_type"]] += 1
    eligible = [i for i in book.in_book if inc(i)]
    flagged_ids = {i for i in eligible if run.invoices[i].reasons}
    flagged = len(flagged_ids)
    n = len(eligible)
    approved = [i for i in sorted(book.approved) if inc(i)]
    minutes = [minutes_between(book.invoices[i].imported_at, book.approved[i]) for i in approved]
    mean = None if not minutes else frac_str(sum(minutes, Fraction(0)) / len(minutes), 4)
    credits = sum((v for k, v in book.credits.items() if inc(k)), D0)

    rows = [r for r in book.export_rows if inc(r["invoice_id"])]
    exp_total = sum((Decimal(r["amount"]) for r in rows), D0)
    log = requests
    if log is None:
        log = book.export_log if cohort is None else [(r, rep) for r, rep in book.export_log
                                                      if any(i in cohort for i in r.invoice_ids)]
    stats = {"requests_received": len(log), "batches_created": sum(1 for _, rep in log if not rep),
             "repeat_requests_returned_prior": sum(1 for _, rep in log if rep)}

    snaps: dict[str, Any] = {}
    for cut in cutoffs:
        snap = derive(pop, cut)
        snaps[iso_z(cut)] = quantities(snap.run, po_filter)

    merged_in = [r for r in book.merged_records if cohort is None or r["id"] in cohort]
    # exclusions (D-09): every in-book invoice the export did not take, with the reason, so the difference is explained
    exclusions = []
    for i in eligible:
        st = book.status[i]
        if i in book.exported:
            continue
        if st == "exception":
            code = EXCEPTION_OPEN
        elif st == "matched":
            code = NOT_APPROVED
        else:                                      # approved (or adjusted) and not exported
            code = EXPORT_BEFORE_APPROVAL if i in book.export_late else APPROVED_NOT_EXPORTED
        exclusions.append({"invoice_id": i, "reason_code": code})

    rates: dict[str, Any] = {"eligible_invoices": n,
                             "straight_through_rate": None if n == 0 else frac_str(Fraction(n - flagged, n), 6),
                             "exception_rate": None if n == 0 else frac_str(Fraction(flagged, n), 6)}
    if pop.exceptions and n:        # D-09: the history pair is published only where the stored exception history adds invoices
        in_cohort = set(eligible)
        ever = flagged_ids | {e.invoice_id for e in pop.exceptions if e.invoice_id in in_cohort}
        if len(ever) > flagged:
            rates["straight_through_never_excepted_rate"] = frac_str(Fraction(n - len(ever), n), 6)
            rates["ever_excepted_rate"] = frac_str(Fraction(len(ever), n), 6)

    out: dict[str, Any] = {
        "matched": {"invoice_count": len(good), "amount_before_tax": s2(sub_t), "tax": s2(tax_t), "total": s2(tot_t)},
        "obligations": {"count": len(oblig), "total": s2(oblig_t)},
        "exceptions": {"open_count": len(records), "unowned_count": sum(1 for e in records if e["owner_id"] is None),
                       "by_reason": by_reason, "records": records},
        "duplicates": {"groups_detected": len({r["merged_into"] for r in merged_in}), "rows_merged": len(merged_in),
                       "unresolved_groups": len({canon for i, canon in book.review.items() if inc(i)})},
        "quantities": quantities(run, po_filter),
        "snapshots": snaps,
        "rates": rates,
        "processing": {"approved_count": len(approved), "mean_minutes": mean,
                       "pending_count": sum(1 for i in eligible if i not in book.approved)},
        "approvals": {"valid_count": len(approved),
                      "invalid_records": [r for r in book.invalid_decisions
                                          if cohort is None or _decision_invoice(pop, r["approval_id"]) in cohort]},
        "payable": {"approved_total": s2(oblig_t), "credit_total": s2(credits), "approved_payable": s2(oblig_t - credits)},
        "export": {**stats, "rows": rows, "exclusions": exclusions,
                   "accepted_export_total": s2(exp_total), "eligible_approved_total": s2(oblig_t),
                   "difference": s2(exp_total - oblig_t)},
    }
    # D-09: a total across currencies is meaningless, so a metric that spans more than one currency also carries its
    # figures per currency (the sums stay, as "sum across currencies, not converted"); single-currency data is unchanged.
    def per(items: list[str], field: Callable[[str], Decimal]) -> dict[str, Decimal]:
        acc: dict[str, Decimal] = {}
        for i in items:
            acc[cur[i]] = acc.get(cur[i], D0) + field(i)
        return acc

    if len({cur[i] for i in good}) > 1:
        ks = sorted({cur[i] for i in good})
        sub, tax, tot = (per(good, lambda i, f=f: getattr(run.invoices[i], f)) for f in ("subtotal", "tax", "total"))
        cnt = {k: sum(1 for i in good if cur[i] == k) for k in ks}
        out["matched"]["by_currency"] = {k: {"invoice_count": cnt[k], "amount_before_tax": s2(sub[k]), "tax": s2(tax[k]),
                                             "total": s2(tot[k])} for k in ks}
    ob = per(oblig, lambda i: run.invoices[i].total)
    cr = per([i for i in book.credits if inc(i)], lambda i: book.credits[i])
    ex: dict[str, Decimal] = {}
    for r in rows:
        ex[r["currency"]] = ex.get(r["currency"], D0) + Decimal(r["amount"])
    if len(set(ob) | set(cr)) > 1:
        ks = sorted(set(ob) | set(cr))
        out["obligations"]["by_currency"] = {k: {"count": sum(1 for i in oblig if cur[i] == k), "total": s2(ob.get(k, D0))}
                                             for k in ks}
        out["payable"]["by_currency"] = {k: {"approved_total": s2(ob.get(k, D0)), "credit_total": s2(cr.get(k, D0)),
                                             "approved_payable": s2(ob.get(k, D0) - cr.get(k, D0))} for k in ks}
    if len(set(ex) | set(ob)) > 1:
        ks = sorted(set(ex) | set(ob))
        out["export"]["by_currency"] = {k: {"accepted_export_total": s2(ex.get(k, D0)),
                                            "eligible_approved_total": s2(ob.get(k, D0)),
                                            "difference": s2(ex.get(k, D0) - ob.get(k, D0))} for k in ks}
    return out


def _decision_invoice(pop: Population, approval_id: str) -> str:
    return next(a.invoice_id for a in pop.approvals if a.approval_id == approval_id)


def compute_metrics(pop: Population, as_of: datetime | None = None, cutoffs: Sequence[datetime] = ()) -> dict[str, Any]:
    """The eleven metrics of the whole population at ``as_of`` (inclusive; None: every recorded fact)."""
    book = derive(pop, as_of)
    out = metrics_from_book(pop, book, cutoffs)
    assert tuple(out) == METRIC_KEYS
    return out


def window_metrics(pop: Population, window: tuple[datetime | None, datetime | None], cutoffs: Sequence[datetime] = (),
                   group_by: str = "none") -> dict[str, Any]:
    """Metrics over a half-open window ``[from, to)`` of invoice import instants, optionally grouped.
    Returns ``{"metrics": {...}}`` or ``{"groups": [{"key", "metrics"}...]}``."""
    lo, hi = window
    check_window(lo, hi)
    if group_by not in GROUPS:
        raise DomainError(INVALID_GROUP, f"group_by must be one of {', '.join(GROUPS)}", "group_by")
    cut = None if hi is None else hi - timedelta(microseconds=1)      # the window is half-open: nothing AT ``to``
    book = derive(pop, cut)
    cohort_all = {i.invoice_id for i in pop.invoices if (lo is None or i.imported_at >= lo)
                  and (hi is None or i.imported_at < hi)}
    snaps = [c for c in cutoffs]
    if group_by == "none":
        return {"metrics": metrics_from_book(pop, book, snaps, None if lo is None else cohort_all)}
    po_vendor = {p.po_id: p.vendor_id for p in pop.purchase_orders}
    po_cur = {p.po_id: p.currency for p in pop.purchase_orders}
    inv_by_id = {i.invoice_id: i for i in pop.invoices}
    gkey = lambda i: inv_by_id[i].vendor_id if group_by == "vendor" else inv_by_id[i].currency      # noqa: E731
    keys = sorted({gkey(i) for i in cohort_all})
    # D-09: a request is counted ONCE, in the group of the first (code-point order) invoice it names that is in the window;
    # a batch naming invoices of two groups is not counted in both, so the groups add up to the whole.
    by_group: dict[str, list[tuple[ExportRequest, bool]]] = {k: [] for k in keys}
    for r, rep in book.export_log:
        first = next((i for i in sorted(set(r.invoice_ids)) if i in cohort_all), None)
        if first is not None:
            by_group[gkey(first)].append((r, rep))
    groups = []
    for k in keys:
        members = {i.invoice_id for i in pop.invoices if i.invoice_id in cohort_all
                   and (i.vendor_id if group_by == "vendor" else i.currency) == k}
        lines = {l.po_line_id for l in pop.po_lines
                 if (po_vendor[l.po_id] if group_by == "vendor" else po_cur[l.po_id]) == k}
        groups.append({"key": k, "metrics": metrics_from_book(pop, book, snaps, members, lines, by_group[k])})
    return {"groups": groups}


def disclosures(pop: Population, book: Book) -> dict[str, Any]:
    """What must sit beside the numbers: tolerances applied, roundings tolerated, merges by reason, the mode."""
    tol = pop.tolerances
    tolerated = [{"invoice_id": i, "rounding_difference": s2(r.rounding_difference)}
                 for i, r in sorted(book.run.invoices.items()) if 0 < r.rounding_difference <= tol.rounding_per_invoice]
    line_tolerated = [{"invoice_id": i, "invoice_line_id": lid, "rounding_difference": s2(d)}
                      for i, r in sorted(book.run.invoices.items()) for lid, d in r.line_rounding
                      if 0 < d <= tol.rounding_per_line]
    by_reason: dict[str, int] = {}
    for rec in book.merged_records:
        by_reason[rec["reason_code"]] = by_reason.get(rec["reason_code"], 0) + 1
    return {
        "rule_version": RULE_VERSION,
        "tolerances": {"price_per_unit": str(tol.price_per_unit), "rounding_per_line": str(tol.rounding_per_line),
                       "rounding_per_invoice": str(tol.rounding_per_invoice)},
        "rounding_tolerated_invoices": tolerated, "rounding_tolerated_lines": line_tolerated,
        "merged_by_reason": by_reason,
        "tax_basis": "tax is computed once per invoice on the unrounded subtotal, ROUND_HALF_UP to 2 dp (D-05)",
        "obligation": "an obligation is an approved, exported or adjusted invoice; nothing here is paid and nothing "
                      "marks an invoice paid",
        "matching": "matching never confers approval; only a matched invoice consumes received quantity",
    }
