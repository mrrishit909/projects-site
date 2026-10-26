"""Decimal money helpers (D-02 rounding, D-04 largest-remainder)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction

D = Decimal
ZERO = D("0")
_CENT = D("0.01")
_RATE = D("0.000001")


def parse_money(value: object) -> Decimal:
    """Parse a decimal string. Floats, bools and None are refused (never coerced)."""
    if not isinstance(value, (str, Decimal)):
        raise ValueError(f"money must be a decimal string, got {type(value).__name__}")
    try:
        d = D(value)
    except InvalidOperation as exc:
        raise ValueError(f"not a decimal: {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"not finite: {value!r}")
    return d


def cents(x: Decimal) -> Decimal:
    """Quantize to 0.01, ROUND_HALF_UP."""
    return x.quantize(_CENT, rounding=ROUND_HALF_UP)


def rate6(x: Decimal) -> Decimal:
    """Quantize to six decimals, ROUND_HALF_UP."""
    return x.quantize(_RATE, rounding=ROUND_HALF_UP)


def money_str(x: Decimal) -> str:
    """Presentation string with exactly two decimals."""
    return format(cents(x), "f")


def rate_str(x: Decimal | None) -> str | None:
    """Presentation string with six decimals, or None."""
    return None if x is None else format(rate6(x), "f")


def largest_remainder(total: Decimal, weights: list[tuple[str, Decimal]]) -> dict[str, Decimal]:
    """Split ``total`` over ``weights`` so the cents sum exactly (D-04).

    Shares are floored to cents; leftover cents go one at a time to the largest
    fractional remainders, ties broken by lowest key. Exact rational arithmetic.
    """
    keys = [k for k, _ in weights]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate allocation keys")
    if any(w < 0 for _, w in weights):
        raise ValueError("negative weight")
    wsum = sum((Fraction(w) for _, w in weights), Fraction(0))
    if wsum == 0:
        raise ValueError("sum of weights is zero")
    total_c = int(cents(total) * 100)
    exact = {k: Fraction(total_c) * Fraction(w) / wsum for k, w in weights}
    floors = {k: v.__floor__() for k, v in exact.items()}
    leftover = total_c - sum(floors.values())
    order = sorted(exact, key=lambda k: (-(exact[k] - floors[k]), k))
    for k in order[:leftover]:
        floors[k] += 1
    return {k: D(floors[k]).scaleb(-2).quantize(_CENT) for k in sorted(floors)}
