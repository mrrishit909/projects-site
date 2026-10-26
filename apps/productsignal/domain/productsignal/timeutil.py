"""Instants (UTC, one accepted form, seconds required) and the account's local calendar (zoneinfo)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TS_FORM = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")
DATE_FORM = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UTC = timezone.utc


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
    return d.astimezone(UTC)


def parse_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not DATE_FORM.match(value):
        raise ValueError("date must be YYYY-MM-DD")
    return date.fromisoformat(value)


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"


@lru_cache(maxsize=256)
def zone(name: str) -> ZoneInfo:
    """An IANA zone from the system tz database; ``ValueError`` when it does not exist."""
    if not isinstance(name, str) or not name or name.startswith("/") or ".." in name:
        raise ValueError("timezone must be an IANA name")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"unknown IANA timezone {name!r}") from None


def local_date(t: datetime, tz: str) -> date:
    """The calendar date of the instant ``t`` in the IANA zone ``tz`` (D-02: day indices are local calendar days)."""
    return t.astimezone(zone(tz)).date()


def days(n: int) -> timedelta:
    return timedelta(days=n)
