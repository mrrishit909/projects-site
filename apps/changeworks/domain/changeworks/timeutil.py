"""Calendar (D-04): integer periods from 0 with a ``period_basis`` and a ``period_start`` date; ranges half-open; instants UTC."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from .errors import DomainError

_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")


def is_ts(s: Any) -> bool:
    if not isinstance(s, str) or not _TS.match(s):
        return False
    try:
        parse_ts(s)
    except ValueError:
        return False
    return True


def parse_ts(s: str) -> datetime:
    if not isinstance(s, str) or not _TS.match(s):
        raise ValueError(f"not a UTC instant with Z: {s!r}")
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in s else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)


def iso_z(d: datetime | None) -> str | None:
    if d is None:
        return None
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + (f".{d.microsecond:06d}".rstrip("0") if d.microsecond else "") + "Z"


def check_period_start(s: Any) -> date:
    """R9-14: a period start is a real calendar date whose day is at most 28, so the same day exists in every month and every year (PERIOD_START_INVALID)."""
    try:
        if not isinstance(s, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            raise ValueError(s)
        d = date.fromisoformat(s)
    except ValueError:
        raise DomainError("PERIOD_START_INVALID", f"period_start must be a calendar date YYYY-MM-DD, got {s!r}", "period_start") from None
    if d.day > 28:
        raise DomainError("PERIOD_START_INVALID", f"period_start day must be at most 28 so that every month has it, got {s}", "period_start", {"day": d.day})
    return d


def period_date(config: dict[str, Any], t: int) -> date:
    """``period_start`` of period ``t`` (the start of the half-open period [t, t+1))."""
    s = config["period_start"]
    s = date.fromisoformat(s) if isinstance(s, str) else s
    if config["period_basis"] == "annual":
        return date(s.year + t, s.month, s.day)
    m = s.month - 1 + t
    return date(s.year + m // 12, m % 12 + 1, s.day)


def period_end_instant(config: dict[str, Any], t: int) -> datetime:
    d = period_date(config, t + 1)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def period_start_instant(config: dict[str, Any], t: int) -> datetime:
    d = period_date(config, t)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def matured(config: dict[str, Any], t: int, as_of: datetime) -> bool:
    """A period is matured when its end (the start of period t+1) is <= as_of (D-P9-22)."""
    try:
        return period_end_instant(config, t) <= as_of
    except (ValueError, OverflowError):
        return False


def matured_count(config: dict[str, Any], as_of: datetime, cap: int) -> int:
    """How many leading periods are matured, looking at no more than ``cap`` periods."""
    n = 0
    while n < cap and matured(config, n, as_of):
        n += 1
    return n
