"""Instants: UTC, one accepted form (seconds required), ISO output with Z."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from fractions import Fraction

TS_FORM = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")
DATE_FORM = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: "No cutoff": every recorded fact counts.
FAR_FUTURE = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def parse_ts(value: object) -> datetime:
    """``YYYY-MM-DDTHH:MM:SS[.f]`` with ``Z`` or an offset, to a UTC datetime. Naive values are refused."""
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        if not TS_FORM.match(value):
            raise ValueError("timestamp must be YYYY-MM-DDTHH:MM:SS with a zone")
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp must be an ISO-8601 string")
    if d.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return d.astimezone(timezone.utc)


def parse_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not DATE_FORM.match(value):
        raise ValueError("date must be YYYY-MM-DD")
    return date.fromisoformat(value)


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"


def minutes_between(start: datetime, end: datetime) -> Fraction:
    """Exact minutes from ``start`` to ``end`` (may be negative)."""
    delta = end - start
    secs = Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1_000_000)
    return secs / 60
