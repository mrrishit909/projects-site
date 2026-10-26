"""Instants, minutes and decimal rounding (D-02): UTC instants, minutes at 4 dp, rates at 6 dp, all exact."""
from __future__ import annotations

import math
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from zoneinfo import ZoneInfo

_FOUR = Decimal("0.0001")
_SIX = Decimal("0.000001")
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


def minutes_between(start: datetime, end: datetime) -> Fraction:
    """Exact minutes from start to end as a rational, never negative (a late-arriving reply clamps to 0)."""
    delta = end - start
    secs = Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1_000_000)
    return secs / 60 if secs > 0 else Fraction(0)


def overlap_minutes(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> Fraction:
    """Minutes of the intersection of [a0, a1) and [b0, b1)."""
    lo, hi = max(a0, b0), min(a1, b1)
    return minutes_between(lo, hi) if hi > lo else Fraction(0)


def local_to_utc(day: date, at: time, zone: str) -> datetime:
    """A wall-clock time in an IANA zone to the UTC instant it names (D-02: shifts are stored as UTC instants,
    so a daylight-saving day never stretches or shrinks a shift measured between two instants)."""
    return datetime.combine(day, at, tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)


def _to_decimal(x: Fraction | Decimal | int) -> Decimal:
    if isinstance(x, Fraction):
        # Exact when the rational terminates (every tie does); 60 digits otherwise.
        from decimal import localcontext
        with localcontext() as ctx:
            ctx.prec = 60
            return Decimal(x.numerator) / Decimal(x.denominator)
    return Decimal(x)


def d4(x: Fraction | Decimal | int | None) -> str | None:
    """Minutes as a decimal string with 4 decimals (ROUND_HALF_UP) from an exact rational."""
    return None if x is None else format(_to_decimal(x).quantize(_FOUR, rounding=ROUND_HALF_UP), "f")


def d6(x: Fraction | Decimal | int | None) -> str | None:
    """Rate as a decimal string with 6 decimals (ROUND_HALF_UP) from an exact rational."""
    return None if x is None else format(_to_decimal(x).quantize(_SIX, rounding=ROUND_HALF_UP), "f")


def ratio(num: int | Fraction, den: int | Fraction) -> Fraction | None:
    return None if den == 0 else Fraction(num) / Fraction(den)


def mean(values: list[Fraction]) -> Fraction | None:
    return None if not values else sum(values, Fraction(0)) / len(values)


def nearest_rank(values: list[Fraction], p: Fraction) -> Fraction | None:
    """D-02: sort ascending, take the value at 1-based index ceil(p * n) (nearest rank). Exact: no interpolation."""
    if not values:
        return None
    s = sorted(values)
    idx = math.ceil(Fraction(p) * len(s))
    return s[max(idx, 1) - 1]
