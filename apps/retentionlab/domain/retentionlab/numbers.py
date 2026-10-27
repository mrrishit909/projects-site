"""Published number formats (docs/contracts.md D-04): proportions and scores are 6-place decimal strings, percentage points 2 places,
money 2 places, hours integers; ROUND_HALF_UP; null means unknown, censored or a zero denominator, never 0.

No float appears in a published figure: ratios are ``Fraction``, money is ``Decimal``.
"""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any


def rnd(x: Fraction | int, dp: int) -> str:
    """ROUND_HALF_UP of an exact rational to ``dp`` places, as a string (sign kept, no negative zero)."""
    x = Fraction(x)
    neg = x < 0
    scaled = abs(x) * 10 ** dp
    n = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    whole, frac = divmod(n, 10 ** dp)
    s = f"{whole}.{frac:0{dp}d}" if dp else str(whole)
    return ("-" if neg and n else "") + s


def p6(x: Fraction | None) -> str | None:
    return None if x is None else rnd(x, 6)


def pp2(diff: Fraction | None) -> str | None:
    """A difference of proportions, in percentage points with 2 places."""
    return None if diff is None else rnd(Fraction(diff) * 100, 2)


def money(d: Decimal | str) -> str:
    return str(Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ratio(num: int, den: int) -> Fraction | None:
    """num/den, or None when the denominator is zero (unknown, never 0)."""
    return None if den == 0 else Fraction(num, den)


def frac_of_float(x: float) -> Fraction:
    """The exact rational value of a float (used only to freeze a fitted number as a decimal string)."""
    return Fraction(x)


def freeze(x: float) -> str:
    """A fitted float, frozen as a 6-place decimal string (the only way a float leaves the fitting code)."""
    return rnd(Fraction(x), 6)


def canon(payload: Any) -> str:
    """Canonical JSON: sorted keys, no spaces, ASCII. Every hash in the project is taken over this form."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def config_hash(config: dict[str, Any]) -> str:
    """D-P10-17: the SHA-256 of the canonical JSON of a training run's ``config``."""
    return sha256_hex(canon(config))
