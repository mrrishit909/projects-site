"""Exact decimal helpers (D-02, D-05): no float anywhere.

Money rounds ROUND_HALF_UP to 2 dp, quantities and unit-price variances to 4 dp, rates to 6 dp, minutes to 4 dp.
Arithmetic runs under a 60-digit context (``exact``), so the product of a 12-digit quantity and a 12-digit price is
never rounded by the default 28-digit context.
"""
from __future__ import annotations

import functools
import re
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from fractions import Fraction
from typing import Any, Callable, TypeVar

from .contract import MAX_ABS
from .errors import MALFORMED_RECORD, DomainError

CTX = Context(prec=60, rounding=ROUND_HALF_UP)
D0 = Decimal(0)
#: ASCII-only decimal spelling (D-09): no underscores, exponents, signs other than one leading +/-, no non-ASCII digits.
DECIMAL_TEXT = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)$", re.ASCII)
C2, C4, C6 = Decimal("0.01"), Decimal("0.0001"), Decimal("0.000001")
F = TypeVar("F", bound=Callable[..., Any])


def exact(fn: F) -> F:
    """Run ``fn`` under the 60-digit ROUND_HALF_UP context (decimal contexts are per thread)."""
    @functools.wraps(fn)
    def wrapper(*a: Any, **k: Any) -> Any:
        with localcontext(CTX):
            return fn(*a, **k)
    return wrapper  # type: ignore[return-value]


def dec(value: object, name: str, max_dp: int | None = None, bound: bool = True) -> Decimal:
    """A JSON string or integer to a finite Decimal. Floats, booleans, NaN and over-long fractions are refused
    (MALFORMED_RECORD): a float has already lost the digits the rule is about."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise DomainError(MALFORMED_RECORD, f"{name} must be a decimal string", name)
    if isinstance(value, str) and not DECIMAL_TEXT.match(value.strip()):
        raise DomainError(MALFORMED_RECORD, f"{name} is not a decimal number", name)
    try:
        d = Decimal(value.strip() if isinstance(value, str) else value)
    except InvalidOperation:
        raise DomainError(MALFORMED_RECORD, f"{name} is not a decimal number", name) from None
    if not d.is_finite():
        raise DomainError(MALFORMED_RECORD, f"{name} must be finite", name)
    if bound and abs(d) >= MAX_ABS:
        raise DomainError(MALFORMED_RECORD, f"{name} is out of range", name)
    if max_dp is not None and -d.as_tuple().exponent > max_dp and d != d.quantize(Decimal(1).scaleb(-max_dp)):
        raise DomainError(MALFORMED_RECORD, f"{name} carries more than {max_dp} decimals", name)
    return d


@exact
def q2(x: Decimal) -> Decimal:
    return x.quantize(C2, rounding=ROUND_HALF_UP)


@exact
def q4(x: Decimal) -> Decimal:
    return x.quantize(C4, rounding=ROUND_HALF_UP)


@exact
def q6(x: Decimal) -> Decimal:
    return x.quantize(C6, rounding=ROUND_HALF_UP)


def s2(x: Decimal) -> str:
    return str(q2(x))


def s4(x: Decimal) -> str:
    return str(q4(x))


def frac_str(x: Fraction, places: int) -> str:
    """``x`` rounded half up (away from zero on a tie) to ``places`` decimals, as a string; exact (integers only)."""
    scale = 10 ** places
    num, den = abs(x.numerator) * scale, x.denominator
    q, r = divmod(num, den)
    if 2 * r >= den:
        q += 1
    sign = "-" if x < 0 and q else ""
    whole, frac = divmod(q, scale)
    return f"{sign}{whole}.{frac:0{places}d}"
