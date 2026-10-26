"""Discount and freight allocation (D-04)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .models import Discount, OrderLine, Shipment, ShipmentLine
from .money import ZERO, cents, largest_remainder


@dataclass(frozen=True)
class FreightAllocation:
    allocations: dict[str, Decimal] = field(default_factory=dict)
    residual: Decimal = ZERO
    unallocated: bool = False


def allocate_discounts(order_lines: list[OrderLine], discounts: list[Discount],
                       shipment_lines: list[ShipmentLine]) -> dict[str, Decimal]:
    """Discount * shipped / ordered per shipment line, exact cents (D-04).

    Each order line's discounts are summed, then split over its shipment lines by
    shipped quantity with largest remainder (tie-break: lowest shipment_line_id).
    """
    out: dict[str, Decimal] = {}
    for ol in sorted(order_lines, key=lambda x: x.line_id):
        sls = sorted((s for s in shipment_lines if s.line_id == ol.line_id),
                     key=lambda s: s.shipment_line_id)
        if not sls:
            continue
        disc = sum((d.discount_amount for d in discounts if d.line_id == ol.line_id), ZERO)
        shipped = sum(s.shipped_quantity for s in sls)
        if shipped == 0 or disc == 0:
            out.update({s.shipment_line_id: ZERO.quantize(Decimal("0.01")) for s in sls})
            continue
        total = cents(disc * shipped / ol.quantity)
        out.update(largest_remainder(total, [(s.shipment_line_id, Decimal(s.shipped_quantity))
                                             for s in sls]))
    return out


def allocate_freight(shipment: Shipment, shipment_lines: list[ShipmentLine],
                     gross_by_line: dict[str, Decimal]) -> FreightAllocation:
    """Allocate shipping_cost by gross-sales weight, else quantity, else leave unallocated (D-04)."""
    cost = cents(shipment.shipping_cost)
    lines = sorted(shipment_lines, key=lambda s: s.shipment_line_id)
    weights = [(s.shipment_line_id, gross_by_line.get(s.shipment_line_id, ZERO)) for s in lines]
    if sum(w for _, w in weights) == 0:
        weights = [(s.shipment_line_id, Decimal(s.shipped_quantity)) for s in lines]
    if sum(w for _, w in weights) == 0:
        return FreightAllocation({}, cost, True)
    alloc = largest_remainder(cost, weights)
    return FreightAllocation(alloc, cost - sum(alloc.values(), ZERO), False)
