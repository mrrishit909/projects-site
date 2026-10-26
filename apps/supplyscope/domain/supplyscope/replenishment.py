"""Replenishment (D-02, D-06). position = on hand + on order - backorders (reserved is NOT subtracted);
quantity = pack_round_up(max(target - position, MOQ)) when position < reorder point, else 0."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Iterable

from .contract import Z_TABLE
from .errors import UNSUPPORTED_SERVICE_TARGET, DomainError
from .models import Closure


def inventory_position(on_hand: int, on_order: int, backorders: int) -> int:
    return on_hand + on_order - backorders


def is_triggered(position: int, reorder_point: int) -> bool:
    return position < reorder_point


def raw_order(target_position: int, position: int) -> int:
    return max(target_position - position, 0)


def apply_moq(raw: int, moq: int) -> int:
    return max(raw, moq)


def pack_round_up(quantity: int, pack_size: int) -> int:
    """Round up to a whole number of packs (pure integer arithmetic)."""
    if pack_size < 1:
        raise ValueError("pack_size must be at least 1")
    return -(-quantity // pack_size) * pack_size


@dataclass(frozen=True)
class Replenishment:
    position: int
    reorder_point: int
    target_position: int
    triggered: bool
    raw_order: int
    order_after_moq: int
    order_quantity: int


def replenish(on_hand: int, on_order: int, backorders: int, reorder_point: int, target_position: int,
              moq: int, pack_size: int) -> Replenishment:
    """The golden arithmetic. Not triggered: raw, MOQ and pack quantities are all 0 (D-06)."""
    pos = inventory_position(on_hand, on_order, backorders)
    if not is_triggered(pos, reorder_point):
        return Replenishment(pos, reorder_point, target_position, False, 0, 0, 0)
    raw = raw_order(target_position, pos)
    after = apply_moq(raw, moq)
    return Replenishment(pos, reorder_point, target_position, True, raw, after, pack_round_up(after, pack_size))


# --- supplier calendar and lead time -----------------------------------------------------------------------------

def _closed_days(closures: Iterable[Closure], calendar_id: str) -> set[date]:
    days: set[date] = set()
    for c in closures:
        if c.calendar_id == calendar_id:
            d = c.closed_from
            while d <= c.closed_to:
                days.add(d)
                d += timedelta(days=1)
    return days


def arrival_date(start: date, lead_days: int, closures: Iterable[Closure], calendar_id: str) -> date:
    """The date ``lead_days`` open supplier-calendar days after ``start`` (closure days do not count, P03-TEST-05)."""
    closed = _closed_days(closures, calendar_id)
    d, counted = start, 0
    while counted < lead_days:
        d += timedelta(days=1)
        if d not in closed:
            counted += 1
    return d


def effective_lead_days(start: date, lead_days: int, closures: Iterable[Closure], calendar_id: str) -> int:
    """Calendar days from ``start`` until the quoted lead days have elapsed on the supplier calendar."""
    return (arrival_date(start, lead_days, closures, calendar_id) - start).days


# --- safety stock ------------------------------------------------------------------------------------------------

def z_value(service_target: Decimal | str) -> Decimal:
    key = format(Decimal(service_target).quantize(Decimal("0.01")), "f")
    if key not in Z_TABLE or Decimal(service_target) != Decimal(key):
        raise DomainError(UNSUPPORTED_SERVICE_TARGET, f"service target {service_target} is not one of "
                          f"{', '.join(sorted(Z_TABLE))}", details={"supported": sorted(Z_TABLE)})
    return Decimal(Z_TABLE[key])


def safety_stock(z: Decimal, daily_variance: Fraction | None, lead_days: int) -> int:
    """ceil(z * sqrt(daily residual variance * lead days)): z times the deviation of lead-time demand, from the
    rolling-origin residuals (errors assumed uncorrelated across days)."""
    if daily_variance is None or lead_days <= 0 or daily_variance == 0:
        return 0
    with localcontext() as ctx:
        ctx.prec = 40
        var = Decimal(daily_variance.numerator) / Decimal(daily_variance.denominator)
        value = z * (var * Decimal(lead_days)).sqrt()
    return math.ceil(value)


def lead_time_demand(daily_forecast: list[Fraction], lead_days: int) -> Fraction:
    """Expected demand over the lead window (the first ``lead_days`` forecast days, closure days included)."""
    return sum(daily_forecast[:lead_days], Fraction(0))


def derived_parameters(ltd: Fraction, safety: int, review_demand: Fraction) -> tuple[int, int]:
    """(reorder point, target position) when no replenishment_params row exists: ROP = ceil(LTD + SS),
    target = ROP + ceil(demand of one review period)."""
    rop = math.ceil(ltd + safety)
    return rop, rop + math.ceil(review_demand)
