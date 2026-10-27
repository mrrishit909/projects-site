"""Instants: UTC, ``Z``, one accepted form (seconds, optional fraction, a zone). Naive values are refused."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
_FORM = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def parse_ts(value: object) -> datetime:
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        if not _FORM.match(value):
            raise ValueError("timestamp must be YYYY-MM-DDTHH:MM:SS with a zone")
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp must be an ISO-8601 string")
    if d.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return d.astimezone(UTC)


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"


def days(n: int) -> timedelta:
    return timedelta(days=n)


def hours_between(later: datetime, earlier: datetime) -> int:
    """Whole hours, floored."""
    return int((later - earlier).total_seconds() // 3600)
