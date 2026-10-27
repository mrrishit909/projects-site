"""Instants: UTC, one accepted form (``YYYY-MM-DDTHH:MM:SS[.f]`` with ``Z`` or an offset)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

TS_FORM = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")
UTC = timezone.utc


def parse_ts(value: object) -> datetime:
    """Parse an instant to a UTC datetime. Naive values and other forms are refused with ValueError."""
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
    return d.astimezone(UTC)


def iso_z(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_ts(dt)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"


def seconds_between(a: datetime | str, b: datetime | str) -> int:
    """Whole seconds from ``a`` to ``b`` (integer arithmetic on microseconds, no float)."""
    td = parse_ts(b) - parse_ts(a)
    return (td.days * 86400 + td.seconds)


def utc_date(value: datetime | str) -> str:
    """The UTC date (the partition of a timestamp, D-P8-02)."""
    return parse_ts(value).strftime("%Y-%m-%d")


def day_partitions(start: datetime | str, end: datetime | str) -> list[str]:
    """The daily UTC partitions of the half-open range [start, end)."""
    cur, stop, out = parse_ts(start), parse_ts(end), []
    while cur < stop:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def micros_between(a: datetime | str, b: datetime | str) -> int:
    """Exact microseconds from ``a`` to ``b`` (integers only)."""
    td = parse_ts(b) - parse_ts(a)
    return (td.days * 86400 + td.seconds) * 1_000_000 + td.microseconds
