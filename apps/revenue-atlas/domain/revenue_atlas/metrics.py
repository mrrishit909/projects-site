"""Metric aggregation (D-01, D-05). Ratios come from aggregated sums."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from .contract import UNALLOCATED_GROUP, UNASSIGNED_REGION
from .errors import INVALID_WINDOW, DomainError
from .models import ReturnEvent, ShipmentLineFact
from .money import ZERO, money_str, rate_str

Window = tuple[datetime | None, datetime | None]


def check_window(window: Window) -> None:
    lo, hi = window
    if lo is not None and hi is not None and lo >= hi:
        raise DomainError(INVALID_WINDOW, "window start must be before end",
                          details={"from": lo.isoformat(), "to": hi.isoformat()})


def in_window(shipped_at: datetime, window: Window) -> bool:
    """Half-open [from, to) on shipped_at (D-01)."""
    lo, hi = window
    return (lo is None or shipped_at >= lo) and (hi is None or shipped_at < hi)


def credit_in_window(credit_date: str, window: Window) -> bool:
    """Half-open [from, to) on credit_date, read as 00:00 UTC of that date (D-01a)."""
    at = datetime.fromisoformat(credit_date).replace(tzinfo=timezone.utc)
    return in_window(at, window)


def _ratio(num: Decimal, den: Decimal) -> str | None:
    return None if den == 0 else rate_str(num / den)


def compute_metrics(facts: list[ShipmentLineFact], window: Window = (None, None), *,
                    unallocated_freight: Decimal = ZERO,
                    declared_shipping_cost: Decimal | None = None,
                    returns: list[ReturnEvent] | None = None) -> dict:
    """Contract D-05 metrics over facts in the window.

    D-01a: shipment lines are selected by ``shipped_at``; return credits by ``credit_date``
    (``returns``, restricted to lines present in ``facts``). With ``returns=None`` the facts'
    own aggregated return columns are used, which is exact only for an unwindowed call.

    ``unallocated_freight`` still counts in shipping cost (D-04).
    ``declared_shipping_cost`` (sum of shipment costs) makes the residual a real
    check; if omitted the residual is 0.00 by construction.
    """
    check_window(window)
    fs = [f for f in facts if in_window(f.shipped_at, window)]
    gross = sum((f.gross_sales for f in fs), ZERO)
    disc = sum((f.allocated_discount for f in fs), ZERO)
    if returns is None:
        credits = sum((f.merchandise_credit for f in fs), ZERO)
        recov = sum((f.recoverable_return_cost for f in fs), ZERO)
        returned = sum(f.returned_quantity for f in fs)
    else:
        known = {f.shipment_line_id for f in facts}
        rs = [r for r in returns if r.shipment_line_id in known and credit_in_window(r.credit_date, window)]
        credits = sum((r.merchandise_credit for r in rs), ZERO)
        recov = sum((r.recoverable_return_cost for r in rs), ZERO)
        returned = sum(r.returned_quantity for r in rs)
    cogs = sum((f.cogs for f in fs), ZERO) - recov
    freight = sum((f.freight for f in fs), ZERO)
    ship_cost = freight + unallocated_freight
    ship_rev = ZERO
    other = ZERO
    net = gross - disc - credits
    gp = net - cogs
    cm = gp + ship_rev - ship_cost - other
    elig_rev = net + ship_rev
    units = sum(f.shipped_quantity for f in fs)
    orders = len({f.order_id for f in fs})
    residual = ZERO if declared_shipping_cost is None else declared_shipping_cost - ship_cost
    return {
        "gross_sales": money_str(gross),
        "allocated_discounts": money_str(disc),
        "merchandise_credits": money_str(credits),
        "net_merchandise_sales": money_str(net),
        "cogs": money_str(cogs),
        "recoverable_return_cost": money_str(recov),
        "gross_profit": money_str(gp),
        "shipping_revenue": money_str(ship_rev),
        "shipping_cost": money_str(ship_cost),
        "other_variable_costs": money_str(other),
        "contribution_margin": money_str(cm),
        "eligible_net_revenue": money_str(elig_rev),
        "contribution_margin_rate": _ratio(cm, elig_rev),
        "discount_rate": _ratio(disc, gross),
        "return_rate": _ratio(Decimal(returned), Decimal(units)),
        "average_order_value": None if orders == 0 else money_str(net / orders),
        "allocation_residual": money_str(residual),
        "eligible_orders": orders,
        "eligible_shipment_lines": len(fs),
        "shipped_units": units,
        "returned_units": returned,
    }


def region_key(fact: ShipmentLineFact) -> str:
    """Region key; a missing region is the explicit UNASSIGNED row (D-06)."""
    return fact.region_id or UNASSIGNED_REGION


def group_metrics(facts: list[ShipmentLineFact],
                  key: Callable[[ShipmentLineFact], str | None],
                  window: Window = (None, None),
                  returns: list[ReturnEvent] | None = None,
                  unallocated_freight: Decimal = ZERO) -> dict[str, dict]:
    """Metrics per group, sorted by key; ``None`` keys become UNASSIGNED.

    D-08 (R-03): freight that no shipment line could carry (``unallocated_freight``, already
    restricted to the window by the caller) still counts in shipping cost (D-04). It is emitted as
    an explicit ``UNALLOCATED`` group with shipping cost equal to it and contribution minus it, for
    every grouping key, so the groups add up to the overall metrics. Nothing is emitted when it is 0.
    """
    check_window(window)
    groups: dict[str, list[ShipmentLineFact]] = {}
    for f in facts:
        groups.setdefault(key(f) or UNASSIGNED_REGION, []).append(f)
    out = {k: compute_metrics(groups[k], window, returns=returns) for k in groups}
    if unallocated_freight != 0:
        out[UNALLOCATED_GROUP] = compute_metrics([], window, unallocated_freight=unallocated_freight)
    return {k: out[k] for k in sorted(out)}


def month_of(shipped_at: datetime) -> str:
    """UTC calendar month "YYYY-MM" of a shipment instant."""
    return shipped_at.astimezone(timezone.utc).strftime("%Y-%m")


def monthly_metrics(facts: list[ShipmentLineFact], returns: list[ReturnEvent],
                    window: Window = (None, None), *,
                    unallocated_by_shipment: dict[str, Decimal] | None = None) -> dict[str, dict]:
    """Month by month metrics under D-01a/D-09: month M selects shipment lines shipped in M and credits
    dated in M (whatever month their line shipped), intersected with ``window``. Months with only
    credits appear (gross 0.00). Unallocated freight of a shipment belongs to its shipped month."""
    check_window(window)
    ship_at = {f.shipment_id: f.shipped_at for f in facts}
    months: set[str] = {month_of(f.shipped_at) for f in facts if in_window(f.shipped_at, window)}
    known = {f.shipment_line_id for f in facts}
    for r in returns:
        if r.shipment_line_id in known and credit_in_window(r.credit_date, window):
            months.add(r.credit_date[:7])
    out: dict[str, dict] = {}
    for m in sorted(months):
        y, mo = int(m[:4]), int(m[5:])
        lo = datetime(y, mo, 1, tzinfo=timezone.utc)
        hi = datetime(y + (mo == 12), mo % 12 + 1, 1, tzinfo=timezone.utc)
        if window[0] is not None:
            lo = max(lo, window[0])
        if window[1] is not None:
            hi = min(hi, window[1])
        unalloc = sum((v for sid, v in (unallocated_by_shipment or {}).items()
                       if sid in ship_at and in_window(ship_at[sid], (lo, hi))), ZERO)
        out[m] = compute_metrics(facts, (lo, hi), returns=returns, unallocated_freight=unalloc)
    return out
