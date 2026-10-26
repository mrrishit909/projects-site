"""Instants, hours and decimal rounding (D-01): UTC instants, hours at 4 dp, rates at 6 dp."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

_FOUR = Decimal("0.0001")
_SIX = Decimal("0.000001")
_SECONDS_PER_HOUR = Decimal(3600)
ZERO = Fraction(0)


def parse_ts(value: object) -> datetime:
    """ISO-8601 string with a zone (``Z`` or an offset) to a UTC datetime. Naive values are refused."""
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp must be an ISO-8601 string")
    if d.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return d.astimezone(timezone.utc)


def parse_ts_opt(value: object) -> datetime | None:
    return None if value is None else parse_ts(value)


def iso_z(dt: datetime | None) -> str | None:
    """UTC ISO-8601 with a ``Z`` suffix (microseconds only when present)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"


def seconds_between(start: datetime, end: datetime) -> Fraction:
    """Exact seconds from start to end as a rational, never negative."""
    delta = end - start
    secs = Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1_000_000)
    return secs if secs > 0 else Fraction(0)


def hours(seconds: Fraction | Decimal | int) -> Fraction:
    """Seconds to hours as an exact rational (never negative). Rounding happens only in d4/d6,
    so a mean that lands exactly on a half-up tie (e.g. 1.31125) rounds correctly."""
    f = Fraction(seconds)
    return f / 3600 if f > 0 else Fraction(0)


def _to_decimal(x: Fraction | Decimal | int) -> Decimal:
    if isinstance(x, Fraction):
        # Exact when the rational terminates (every tie does); 28 digits otherwise.
        return Decimal(x.numerator) / Decimal(x.denominator)
    return Decimal(x)


def d4(x: Fraction | Decimal | int | None) -> str | None:
    """Hours as a decimal string with 4 decimals (ROUND_HALF_UP) from an exact rational."""
    return None if x is None else format(_to_decimal(x).quantize(_FOUR, rounding=ROUND_HALF_UP), "f")


def d6(x: Fraction | Decimal | int | None) -> str | None:
    """Rate as a decimal string with 6 decimals (ROUND_HALF_UP) from an exact rational."""
    return None if x is None else format(_to_decimal(x).quantize(_SIX, rounding=ROUND_HALF_UP), "f")


def ratio(num: int | Fraction | Decimal, den: int | Fraction | Decimal) -> Fraction | None:
    return None if den == 0 else Fraction(num) / Fraction(den)


def mean(values: list[Fraction]) -> Fraction | None:
    return None if not values else sum(values, Fraction(0)) / len(values)
