"""Money and rate formatting (D-05): money is a Decimal with 2 dp, rates have 6 dp from exact Fractions."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction

_TWO = Decimal("0.01")
_SIX = Decimal("0.000001")


def to_decimal(x: Fraction | Decimal | int) -> Decimal:
    if isinstance(x, Fraction):
        return Decimal(x.numerator) / Decimal(x.denominator)  # exact whenever the rational terminates
    return Decimal(x)


def d2(x: Fraction | Decimal | int | None) -> str | None:
    return None if x is None else format(to_decimal(x).quantize(_TWO, rounding=ROUND_HALF_UP), "f")


def d6(x: Fraction | Decimal | int | None) -> str | None:
    return None if x is None else format(to_decimal(x).quantize(_SIX, rounding=ROUND_HALF_UP), "f")


def ratio(num: int | Fraction, den: int | Fraction) -> Fraction | None:
    return None if den == 0 else Fraction(num) / Fraction(den)


def parse_money(value: object) -> Decimal:
    """A non-negative amount with at most 2 decimals, from a string, int or Decimal (never a float)."""
    if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("money must be a decimal string")
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise ValueError("money is not a number") from None
    if not d.is_finite() or d < 0 or d != d.quantize(_TWO):
        raise ValueError("money must be finite, not negative, with at most 2 decimals")
    return d.quantize(_TWO)


def cost_in_force(base_cost: Decimal, versions: list, on_date: date) -> Decimal:
    """The unit cost on ``on_date``: the latest cost version effective on or before that date, else the product's
    base cost (``products.unit_cost`` is the cost before any cost version, D-05)."""
    best = None
    for v in versions:
        if v.effective_from.astimezone(timezone.utc).date() <= on_date and (
                best is None or (v.effective_from, v.cost_version_id) > (best.effective_from, best.cost_version_id)):
            best = v
    return best.unit_cost if best is not None else base_cost


def on_hand_value(on_hand: int, unit_cost: Decimal) -> Decimal:
    """Negative stock is never valued: it counts as zero."""
    return Decimal(max(on_hand, 0)) * unit_cost


def utc_date(dt: datetime) -> date:
    return dt.astimezone(timezone.utc).date()
