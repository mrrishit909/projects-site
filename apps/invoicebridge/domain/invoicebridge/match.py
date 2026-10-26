"""Three-way match (D-03) with cumulative consumption, rounding tolerances and exceptions (D-02).

``match_run`` evaluates the invoices of the book at one cutoff in CONSUMPTION order (D-09): invoices with a committed
approval first, by their commit instant, then the others in (invoice_date, imported_at, invoice_id) order, so a later
fact cannot displace a committed one.
A line matches when quantity variance <= 0 and |price variance| <= the price tolerance; otherwise it carries the specific
reason (QUANTITY_BLOCKED, PRICE_VARIANCE, NO_PO_LINE, CURRENCY_MISMATCH). An invoice matches when no line has a reason and
its rounding differences are within tolerance (ROUNDING_EXCEPTION otherwise). Only a MATCHED invoice consumes received
quantity, so an exception, rejected or merged invoice consumes nothing. Matching never confers approval (D-03).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Mapping, Sequence

from .amounts import invoice_amounts, line_extended
from .contract import RULE_VERSION
from .money import D0, exact, q2, s2, s4
from .models import Invoice, Population, PoLine


@dataclass
class LineResult:
    invoice_line_id: str
    invoice_id: str
    po_line_id: str
    status: str                          # matched | exception
    reason_code: str | None
    available: Decimal | None
    quantity_variance: Decimal | None
    price_variance: Decimal | None
    invoice_price: Decimal
    explanation: str

    def as_row(self) -> dict[str, object]:
        return {"invoice_line_id": self.invoice_line_id, "invoice_id": self.invoice_id, "rule_version": RULE_VERSION,
                "status": self.status, "reason_code": self.reason_code,
                "available_quantity": None if self.available is None else s4(self.available),
                "quantity_variance": None if self.quantity_variance is None else s4(self.quantity_variance),
                "price_variance": None if self.price_variance is None else s4(self.price_variance)}


@dataclass
class InvoiceResult:
    invoice_id: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    rounding_difference: Decimal
    reasons: list[str]                   # sorted, distinct
    matched: bool
    line_rounding: list[tuple[str, Decimal]] = field(default_factory=list)   # (line id, |stated - computed|) when > 0


@dataclass
class MatchRun:
    cutoff: datetime
    po_lines: dict[str, PoLine]
    net: dict[str, Decimal]
    consumed: dict[str, Decimal]
    lines: list[LineResult]
    invoices: dict[str, InvoiceResult]


def book_order(inv: Invoice) -> tuple:
    return (inv.invoice_date, inv.imported_at, inv.invoice_id)


@exact
def match_run(pop: Population, candidates: Sequence[Invoice], cutoff: datetime,
              committed: Mapping[str, tuple] | None = None) -> MatchRun:
    """D-03 at ``cutoff``: PO lines whose PO was ordered by then, non-reversed receipts received by then, the given
    candidate invoices (already filtered to the book) in consumption order: ``committed`` (invoice id -> commit instant
    key) first, then book order."""
    committed = committed or {}
    tol_price = pop.tolerances.price_per_unit
    tol_line = pop.tolerances.rounding_per_line
    tol_inv = pop.tolerances.rounding_per_invoice
    po_cur = {p.po_id: p.currency for p in pop.purchase_orders}
    po_vendor = {p.po_id: p.vendor_id for p in pop.purchase_orders}
    ordered = {p.po_id for p in pop.purchase_orders if p.ordered_at <= cutoff}
    pol = {l.po_line_id: l for l in pop.po_lines if l.po_id in ordered}
    net = {k: D0 for k in pol}
    for r in pop.receipts:
        if not r.reversed and r.received_at <= cutoff and r.po_line_id in net:
            net[r.po_line_id] += r.received_quantity
    consumed = {k: D0 for k in pol}
    results: list[LineResult] = []
    invs: dict[str, InvoiceResult] = {}
    for inv in sorted(candidates, key=lambda i: (0, committed[i.invoice_id], i.invoice_id) if i.invoice_id in committed
                      else (1, book_order(i), i.invoice_id)):
        sub, tax, total = invoice_amounts(inv)
        reasons: set[str] = set()
        local: dict[str, Decimal] = {}
        rows: list[LineResult] = []
        line_round: list[tuple[str, Decimal]] = []
        for l in sorted(inv.lines, key=lambda x: x.invoice_line_id):
            p = pol.get(l.po_line_id)
            row = LineResult(l.invoice_line_id, inv.invoice_id, l.po_line_id, "matched", None, None, None, None,
                             l.unit_price, "")
            if p is None:
                row.status, row.reason_code = "exception", "NO_PO_LINE"
                row.explanation = f"no purchase-order line {l.po_line_id} exists at the cutoff"
            elif po_vendor[p.po_id] != inv.vendor_id:
                row.status, row.reason_code = "exception", "NO_PO_LINE"      # D-09: another vendor's PO line is no PO line of this invoice
                row.explanation = (f"purchase-order line {l.po_line_id} belongs to a purchase order of vendor "
                                   f"{po_vendor[p.po_id]}, not of {inv.vendor_id}")
            elif po_cur[p.po_id] != inv.currency:
                row.status, row.reason_code = "exception", "CURRENCY_MISMATCH"
                row.explanation = (f"invoice currency {inv.currency} differs from the PO currency {po_cur[p.po_id]} and "
                                   "no dated conversion rate exists")
            else:
                avail = net[p.po_line_id] - consumed[p.po_line_id] - local.get(p.po_line_id, D0)
                qv, pv = l.quantity - avail, l.unit_price - p.unit_price
                row.available, row.quantity_variance, row.price_variance = avail, qv, pv
                if qv > 0:
                    row.status, row.reason_code = "exception", "QUANTITY_BLOCKED"
                    row.explanation = f"invoiced {s4(l.quantity)} exceeds the {s4(avail)} available to invoice"
                elif abs(pv) > tol_price:
                    row.status, row.reason_code = "exception", "PRICE_VARIANCE"
                    row.explanation = (f"invoice price {l.unit_price} differs from the PO price {p.unit_price} by "
                                       f"{s4(pv)} (tolerance {tol_price})")
                else:
                    row.explanation = f"{s4(l.quantity)} of {s4(avail)} available, price within tolerance"
                local[p.po_line_id] = local.get(p.po_line_id, D0) + l.quantity
            if row.reason_code:
                reasons.add(row.reason_code)
            if l.line_amount is not None:
                ldiff = abs(l.line_amount - q2(line_extended(l)))
                if ldiff > 0:
                    line_round.append((l.invoice_line_id, ldiff))
                if ldiff > tol_line:
                    reasons.add("ROUNDING_EXCEPTION")
            rows.append(row)
        diff = abs(inv.declared_total - total)
        if diff > tol_inv:
            reasons.add("ROUNDING_EXCEPTION")
        ok = not reasons
        if ok:
            for k, v in local.items():
                consumed[k] += v
        results.extend(rows)
        invs[inv.invoice_id] = InvoiceResult(inv.invoice_id, sub, tax, total, diff, sorted(reasons), ok, line_round)
    return MatchRun(cutoff, pol, net, consumed, results, invs)


@exact
def quantities(run: MatchRun, po_filter: set[str] | None = None) -> dict[str, str]:
    """D-P5-14 open quantities at the run's cutoff, over all PO lines (or those in ``po_filter``)."""
    pol = {k: v for k, v in run.po_lines.items() if po_filter is None or k in po_filter}
    net, cons = run.net, run.consumed
    rni = sum((max(net[k] - cons[k], D0) for k in pol), D0)
    rni_val = sum((max(net[k] - cons[k], D0) * pol[k].unit_price for k in pol), D0)
    blocked = [r for r in run.lines if r.reason_code == "QUANTITY_BLOCKED" and (po_filter is None or r.po_line_id in po_filter)]
    b_q = sum((r.quantity_variance for r in blocked), D0)          # type: ignore[misc]
    b_v = sum((r.quantity_variance * r.invoice_price for r in blocked), D0)   # type: ignore[operator]
    return {
        "ordered_quantity": s4(sum((p.quantity for p in pol.values()), D0)),
        "net_received_quantity": s4(sum((net[k] for k in pol), D0)),
        "accepted_invoiced_quantity": s4(sum((cons[k] for k in pol), D0)),
        "open_to_receive_quantity": s4(sum((max(pol[k].quantity - net[k], D0) for k in pol), D0)),
        "open_to_invoice_quantity": s4(sum((max(pol[k].quantity - cons[k], D0) for k in pol), D0)),
        "received_not_invoiced_quantity": s4(rni),
        "received_not_invoiced_value": s2(rni_val),
        "invoiced_not_received_quantity": s4(b_q),
        "invoiced_not_received_value": s2(b_v),
    }
