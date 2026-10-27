"""Number formats (D-04): exact rationals inside, ROUND_HALF_UP at the declared presentation step. No float anywhere."""
from __future__ import annotations

import re
from decimal import Decimal
from fractions import Fraction as F
from typing import Any

DECIMAL_RE = re.compile(r"^-?\d{1,14}(\.\d{1,6})?$")


def rnd(x: Any, dp: int) -> str:
    """ROUND_HALF_UP (half away from zero) of a Fraction to ``dp`` places, as a string, by integer arithmetic."""
    x = F(x)
    neg = x < 0
    scaled = abs(x) * 10 ** dp
    n = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    whole, frac = divmod(n, 10 ** dp)
    s = f"{whole}.{frac:0{dp}d}" if dp else str(whole)
    return ("-" if neg and n else "") + s


def money(x: Any) -> str:
    return rnd(x, 2)


def p6(x: Any) -> str | None:
    return None if x is None else rnd(x, 6)


def m4(x: Any) -> str | None:
    return None if x is None else rnd(x, 4)


def mn(x: Any) -> str | None:
    return None if x is None else money(x)


def ex(x: Any) -> str | None:
    """The exact rational as ``n/d`` (``n`` for an integer)."""
    return None if x is None else str(F(x))


def dec(s: Any) -> F:
    """A decimal string / Decimal / int to an exact Fraction (never through a float)."""
    if isinstance(s, float):
        raise TypeError("float is not allowed")
    return F(Decimal(s)) if not isinstance(s, F) else s


def canon(v: Any) -> str:
    """Canonical text of a stored amount: at least 2 places, no trailing zeros beyond them (``1000.000000`` -> ``1000.00``)."""
    s = format(Decimal(v), "f")
    if "." not in s:
        return s + ".00"
    whole, frac = s.split(".")
    return f"{whole}.{frac.rstrip('0').ljust(2, '0')}"


def is_decimal(s: Any) -> bool:
    return isinstance(s, str) and bool(DECIMAL_RE.match(s))
