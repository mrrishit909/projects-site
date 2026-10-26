"""Instants, hours and decimal rounding (D-01): UTC instants, hours at 4 dp, rates at 6 dp."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

_FOUR = Decimal("0.0001")
_SIX = Decimal("0.000001")
_SECONDS_PER_HOUR = Decimal(3600)
ZERO = Decimal(0)


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


def seconds_between(start: datetime, end: datetime) -> Decimal:
    """Exact seconds from start to end, never negative."""
    delta = end - start
    secs = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(1_000_000)
    return secs if secs > 0 else ZERO


def hours(seconds: Decimal) -> Decimal:
    """Seconds to hours (unrounded, never negative)."""
    return seconds / _SECONDS_PER_HOUR if seconds > 0 else ZERO


def d4(x: Decimal | None) -> str | None:
    """Hours as a decimal string with 4 decimals (ROUND_HALF_UP)."""
    return None if x is None else format(x.quantize(_FOUR, rounding=ROUND_HALF_UP), "f")


def d6(x: Decimal | None) -> str | None:
    """Rate as a decimal string with 6 decimals (ROUND_HALF_UP)."""
    return None if x is None else format(x.quantize(_SIX, rounding=ROUND_HALF_UP), "f")


def ratio(num: int | Decimal, den: int | Decimal) -> Decimal | None:
    return None if den == 0 else Decimal(num) / Decimal(den)


def mean(values: list[Decimal]) -> Decimal | None:
    return None if not values else sum(values, ZERO) / len(values)
