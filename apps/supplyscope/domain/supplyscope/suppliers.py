"""Supplier reliability and open lines (D-04). Computed only from receipts dated at or before the cutoff; a partial
receipt never completes its line."""
from __future__ import annotations

from datetime import date, datetime, timezone
from fractions import Fraction
from typing import Any

from .models import Closure, PoLine, PurchaseOrder, Receipt, Supplier
from .money import d6, ratio
from .replenishment import arrival_date


def received_quantity(line_id: str, receipts: list[Receipt], cutoff: datetime | None = None) -> int:
    return sum(r.received_quantity for r in receipts if r.po_line_id == line_id and (cutoff is None or r.received_at <= cutoff))


def open_quantity(line: PoLine, receipts: list[Receipt], cutoff: datetime | None = None) -> int:
    """ordered - received (receipts at or before the cutoff), never below 0. > 0 means the line is open."""
    return max(line.ordered_quantity - received_quantity(line.po_line_id, receipts, cutoff), 0)


def line_status(line: PoLine, receipts: list[Receipt], cutoff: datetime | None = None) -> str:
    got = received_quantity(line.po_line_id, receipts, cutoff)
    return "open" if got < line.ordered_quantity else "complete"  # partial (0 < got < ordered) stays open


def promised_date(order: PurchaseOrder, supplier: Supplier, closures: list[Closure]) -> date:
    """The deadline promised at order time: the quoted lead days counted on the supplier calendar."""
    return arrival_date(order.ordered_at.astimezone(timezone.utc).date(), supplier.quoted_lead_days, closures,
                        supplier.calendar_id)


def on_time_rate(orders: list[PurchaseOrder], lines: list[PoLine], receipts: list[Receipt],
                 suppliers: list[Supplier], closures: list[Closure], cutoff: datetime,
                 supplier_id: str | None = None) -> dict[str, Any]:
    """Receipts within the promised deadline / eligible receipts, from receipts dated <= cutoff (no future leakage)."""
    sup = {s.supplier_id: s for s in suppliers}
    ord_ = {o.purchase_order_id: o for o in orders}
    line = {l.po_line_id: l for l in lines}
    eligible = on_time = 0
    late: list[str] = []
    seen_lines: set[str] = set()
    for r in sorted(receipts, key=lambda r: (r.received_at, r.receipt_id)):
        if r.received_at > cutoff or r.po_line_id not in line:
            continue
        o = ord_.get(line[r.po_line_id].purchase_order_id)
        s = sup.get(o.supplier_id) if o else None
        if o is None or s is None or (supplier_id is not None and s.supplier_id != supplier_id):
            continue
        eligible += 1
        seen_lines.add(r.po_line_id)
        if r.received_at.astimezone(timezone.utc).date() <= promised_date(o, s, closures):
            on_time += 1
        else:
            late.append(r.receipt_id)
    rate = ratio(on_time, eligible)
    open_lines = sorted(l.po_line_id for l in lines if (ord_.get(l.purchase_order_id) is not None
                        and (supplier_id is None or ord_[l.purchase_order_id].supplier_id == supplier_id)
                        and ord_[l.purchase_order_id].ordered_at <= cutoff
                        and line_status(l, receipts, cutoff) == "open"))
    return {"eligible_receipts": eligible, "on_time_receipts": on_time, "late_receipts": late,
            "on_time_rate": d6(rate), "partially_received_open_lines": sorted(
                l for l in open_lines if received_quantity(l, receipts, cutoff) > 0),
            "open_lines": open_lines}
