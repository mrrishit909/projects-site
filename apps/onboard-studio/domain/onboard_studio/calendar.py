"""Working calendars as sets of half-open intervals [starts_at, ends_at) (D-01).

A holiday is an interval subtracted from the working set. A holiday that lies on a weekend
(where there is no working interval) subtracts nothing (P02-TEST-08).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .timeutil import ZERO, seconds_between

Interval = tuple[datetime, datetime]


def merge(intervals: list[Interval]) -> list[Interval]:
    """Union of intervals as sorted, disjoint, non-empty half-open intervals (touching ones join)."""
    out: list[Interval] = []
    for s, e in sorted(i for i in intervals if i[1] > i[0]):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def subtract(working: list[Interval], holidays: list[Interval]) -> list[Interval]:
    """Working set minus holidays, as disjoint intervals."""
    result = merge(working)
    for hs, he in merge(holidays):
        nxt: list[Interval] = []
        for s, e in result:
            if he <= s or hs >= e:  # no overlap (half-open: touching does not subtract)
                nxt.append((s, e))
                continue
            if s < hs:
                nxt.append((s, hs))
            if he < e:
                nxt.append((he, e))
        result = nxt
    return result


def effective_intervals(working: list[Interval], holidays: list[Interval] | None = None) -> list[Interval]:
    return subtract(working, holidays or [])


def overlap_seconds(start: datetime, end: datetime, intervals: list[Interval]) -> Decimal:
    """Seconds of [start, end) inside the intervals; 0 when end <= start. Intervals must be disjoint."""
    total = ZERO
    if end <= start:
        return total
    for s, e in intervals:
        lo, hi = max(start, s), min(end, e)
        if hi > lo:
            total += seconds_between(lo, hi)
    return total


def in_working_time(at: datetime, intervals: list[Interval]) -> bool:
    return any(s <= at < e for s, e in intervals)
