"""Half-open backfill ranges [start, end) over daily UTC partitions (D-03, D-P8-11)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable

from . import errors as E
from .errors import DomainError
from .timeutil import day_partitions, parse_ts

Row = dict[str, Any]


def ranges_overlap(a_start: Any, a_end: Any, b_start: Any, b_end: Any) -> bool:
    """Half-open ranges overlap iff each starts before the other ends: touching ranges ([a, b) and [b, c)) do not overlap."""
    return parse_ts(a_start) < parse_ts(b_end) and parse_ts(b_start) < parse_ts(a_end)


def find_overlap(accepted: Iterable[Row], request: Row) -> Row | None:
    """The first earlier accepted request of the same source whose range overlaps the request's."""
    for other in accepted:
        if other["source_id"] == request["source_id"] and ranges_overlap(request["start_at"], request["end_at"], other["start_at"], other["end_at"]):
            return other
    return None


def check_range(start: Any, end: Any) -> list[str]:
    """The partitions of a request: both bounds at UTC midnight, start before end; else DomainError."""
    s, e = parse_ts(start), parse_ts(end)
    if not s < e:
        raise DomainError(E.INVALID_RANGE, "start_at must be before end_at (the range is half-open)", "input.end_at")
    for name, v in (("start_at", s), ("end_at", e)):
        if (v.hour, v.minute, v.second, v.microsecond) != (0, 0, 0, 0):
            raise DomainError(E.PARTITION_ALIGNMENT, f"{name} must be a UTC midnight (partitions are daily)", f"input.{name}")
    if (e - s) > timedelta(days=3660):
        raise DomainError(E.INVALID_RANGE, "a backfill covers at most 3660 daily partitions", "input.end_at")
    return day_partitions(s, e)
