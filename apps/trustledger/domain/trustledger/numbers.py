"""Published number formats (D-05): proportions are 6-place decimal strings, hours 4 places, ROUND_HALF_UP, null = unknown."""
from __future__ import annotations

from fractions import Fraction


def rnd(x: Fraction | int, dp: int) -> str:
    """ROUND_HALF_UP of an exact rational to ``dp`` places, as a string (no float anywhere)."""
    x = Fraction(x)
    neg = x < 0
    scaled = abs(x) * 10 ** dp
    n = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    whole, frac = divmod(n, 10 ** dp)
    s = f"{whole}.{frac:0{dp}d}" if dp else str(whole)
    return ("-" if neg and n else "") + s


def p6(x: Fraction | None) -> str | None:
    return None if x is None else rnd(x, 6)


def h4(x: Fraction | None) -> str | None:
    return None if x is None else rnd(x, 4)


def ratio(num: int, den: int) -> Fraction | None:
    """num/den, or None when the denominator is zero (unknown, never 0)."""
    return None if den == 0 else Fraction(num, den)
