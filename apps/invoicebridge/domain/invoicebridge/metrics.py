"""Metrics (P05-MET-01..12) from a derived book: exactly the keys of ``expected.json["metrics"]``.

``compute_metrics(pop, as_of, cutoffs)`` is the whole population at one instant. A window ``[from, to)`` restricts the
cohort to invoices imported in it (matching still runs on the whole book so consumption is right); ``group_by`` splits
the cohort by vendor or currency. ``snapshots`` re-run the open quantities as of each cutoff (D-P5-15).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any, Sequence

from .book import Book, derive
from .contract import EXCEPTION_CODES, METRIC_KEYS, RULE_VERSION
from .errors import EXCEPTION_OPEN, INVALID_GROUP, INVALID_WINDOW, NOT_APPROVED, DomainError
from .match import quantities
from .money import D0, exact, frac_str, s2
from .models import Population
from .timeutil import iso_z, minutes_between

GROUPS = ("none", "vendor", "currency")


def check_window(lo: datetime | None, hi: datetime | None) -> None:
    if lo is not None and hi is not None and lo >= hi:
        raise DomainError(INVALID_WINDOW, "from must be before to (the window is half-open)", "from")


@exact
def metrics_from_book(pop: Population, book: Book, cutoffs: Sequence[datetime] = (),
                      cohort: set[str] | None = None, po_filter: set[str] | None = None,
                      all_requests: bool = True) -> dict[str, Any]:
    """The eleven metrics. ``cohort`` limits the invoice-level metrics to those invoice ids (None: all);
    ``po_filter`` limits the quantity metrics to those PO lines."""
    run = book.run

    def inc(iid: str) -> bool:
        return cohort is None or iid in cohort

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
    flagged = sum(1 for i in eligible if run.invoices[i].reasons)
    n = len(eligible)
    approved = [i for i in sorted(book.approved) if inc(i)]
    minutes = [minutes_between(book.invoices[i].imported_at, book.approved[i]) for i in approved]
    mean = None if not minutes else frac_str(sum(minutes, Fraction(0)) / len(minutes), 4)
    credits = sum((v for k, v in book.credits.items() if inc(k)), D0)

    rows = [r for r in book.export_rows if inc(r["invoice_id"])]
    exp_total = sum((Decimal(r["amount"]) for r in rows), D0)
    stats = book.export_stats
    if cohort is not None:                      # a cohort counts the requests that name one of its invoices
        reqs = [r for r in pop.export_requests if r.exported_at <= book.cutoff and any(i in cohort for i in r.invoice_ids)]
        seen_k: set[str] = set()
        seen_b: set[str] = set()
        batches = repeats = 0
        for r in reqs:
            repeat = r.idempotency_key in seen_k or r.batch_id in seen_b
            seen_k.add(r.idempotency_key)
            seen_b.add(r.batch_id)
            if repeat:
                repeats += 1
            else:
                batches += 1
        stats = {"requests_received": len(reqs), "batches_created": batches, "repeat_requests_returned_prior": repeats}

    snaps: dict[str, Any] = {}
    for cut in cutoffs:
        snap = derive(pop, cut)
        snaps[iso_z(cut)] = quantities(snap.run, po_filter)

    group_ids = None if cohort is None else cohort
    merged_in = [r for r in book.merged_records if group_ids is None or r["id"] in group_ids]
    return {
        "matched": {"invoice_count": len(good), "amount_before_tax": s2(sub_t), "tax": s2(tax_t), "total": s2(tot_t)},
        "obligations": {"count": len(oblig), "total": s2(oblig_t)},
        "exceptions": {"open_count": len(records), "unowned_count": sum(1 for e in records if e["owner_id"] is None),
                       "by_reason": by_reason, "records": records},
        "duplicates": {"groups_detected": len({r["merged_into"] for r in merged_in}), "rows_merged": len(merged_in),
                       "unresolved_groups": 0},
        "quantities": quantities(run, po_filter),
        "snapshots": snaps,
        "rates": {"eligible_invoices": n,
                  "straight_through_rate": None if n == 0 else frac_str(Fraction(n - flagged, n), 6),
                  "exception_rate": None if n == 0 else frac_str(Fraction(flagged, n), 6)},
        "processing": {"approved_count": len(approved), "mean_minutes": mean,
                       "pending_count": sum(1 for i in eligible if i not in book.approved)},
        "approvals": {"valid_count": len(approved),
                      "invalid_records": [r for r in book.invalid_decisions
                                          if cohort is None or _decision_invoice(pop, r["approval_id"]) in cohort]},
        "payable": {"approved_total": s2(oblig_t), "credit_total": s2(credits), "approved_payable": s2(oblig_t - credits)},
        "export": {**stats, "rows": rows,
                   "exclusions": [{"invoice_id": i, "reason_code": EXCEPTION_OPEN if book.status[i] == "exception" else NOT_APPROVED}
                                  for i in eligible if book.status[i] in ("exception", "matched")],
                   "accepted_export_total": s2(exp_total), "eligible_approved_total": s2(oblig_t),
                   "difference": s2(exp_total - oblig_t)},
    }


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
    keys = sorted({(i.vendor_id if group_by == "vendor" else i.currency) for i in pop.invoices if i.invoice_id in cohort_all})
    groups = []
    for k in keys:
        members = {i.invoice_id for i in pop.invoices if i.invoice_id in cohort_all
                   and (i.vendor_id if group_by == "vendor" else i.currency) == k}
        lines = {l.po_line_id for l in pop.po_lines
                 if (po_vendor[l.po_id] if group_by == "vendor" else po_cur[l.po_id]) == k}
        groups.append({"key": k, "metrics": metrics_from_book(pop, book, snaps, members, lines)})
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
