"""Instants (UTC, one accepted form) and the dataset's local refresh schedule (zoneinfo, IANA names, system tzdata)."""
from __future__ import annotations

import re
from fractions import Fraction
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TS_FORM = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
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


def parse_hhmm(value: str) -> time:
    m = HHMM.match(value) if isinstance(value, str) else None
    if not m:
        raise ValueError("local time must be HH:MM")
    return time(int(m.group(1)), int(m.group(2)))


def local_to_utc(day: date, at: time, tz: str) -> datetime:
    """The UTC instant of ``day`` ``at`` in the IANA zone. A time that occurs twice (clocks going back) is the LATER one, the
    standard-time instant; a time that does not exist (clocks going forward) uses the offset before the change. Both are what
    PostgreSQL's ``timestamp AT TIME ZONE`` does, so the SQL reference and the domain agree on those days."""
    z = zone(tz)
    d0 = datetime.combine(day, at, tzinfo=z)
    d1 = d0.replace(fold=1)
    chosen = d1 if d0.utcoffset() > d1.utcoffset() else d0
    return chosen.astimezone(UTC)


def scheduled_occurrence(tz: str, local_time: str, grace_minutes: int, as_of: datetime) -> tuple[datetime, datetime]:
    """The latest daily occurrence (local ``local_time`` in ``tz``) whose grace window has closed by ``as_of`` (s + grace <= as_of),
    and its deadline. The window is half-open [s, s + grace) (D-05)."""
    at = parse_hhmm(local_time)
    grace = timedelta(minutes=grace_minutes)
    d0 = as_of.astimezone(zone(tz)).date()
    for back in range(-1, 5):
        s = local_to_utc(d0 - timedelta(days=back), at, tz)
        if s + grace <= as_of:
            return s, s + grace
    raise ValueError("no occurrence found")


def latest_occurrence(tz: str, local_time: str, grace_minutes: int, as_of: datetime) -> tuple[datetime, datetime]:
    """The latest daily occurrence (local ``local_time`` in ``tz``) that has STARTED by ``as_of`` (s <= as_of), and its deadline
    s + grace. Its window [s, s + grace) may still be open (D-10, R7-01)."""
    at = parse_hhmm(local_time)
    d0 = as_of.astimezone(zone(tz)).date()
    for back in range(-1, 5):
        s = local_to_utc(d0 - timedelta(days=back), at, tz)
        if s <= as_of:
            return s, s + timedelta(minutes=grace_minutes)
    raise ValueError("no occurrence found")


ON_TIME, LATE, PENDING = "on_time", "late", "pending"


def timeliness_state(tz: str, local_time: str, grace_minutes: int, last_refresh: datetime | None, as_of: datetime) -> tuple[str, datetime, datetime]:
    """(state, occurrence, deadline) of a monitored dataset at ``as_of`` (D-10, R7-01).

    on_time  a refresh (not after ``as_of``) exists in [latest occurrence <= as_of, its deadline);
    pending  otherwise, when that occurrence's deadline has not passed: neither on time nor late, outside the denominator;
    late     otherwise (the deadline has passed with no refresh in the window; a refresh at the deadline is late)."""
    s, dl = latest_occurrence(tz, local_time, grace_minutes, as_of)
    if last_refresh is not None and last_refresh <= as_of and s <= last_refresh < dl:
        return ON_TIME, s, dl
    return (PENDING if dl > as_of else LATE), s, dl


def hours_between(a: datetime, b: datetime) -> Fraction:
    """Exact hours from ``a`` to ``b`` (integer microseconds, no float)."""
    td = b - a
    micro = (td.days * 86400 + td.seconds) * 1_000_000 + td.microseconds
    return Fraction(micro, 3_600_000_000)
