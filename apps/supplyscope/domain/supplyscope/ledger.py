"""Ledger reconstruction (D-01). Stock is the sum of posted deltas up to the cutoff instant per (product, location).
Within a date the order is receipts, then sales, then everything else (review): the sort key is
(date, movement type rank, event_at, movement_id). The same order is used by the simulation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from .errors import NEGATIVE_STOCK
from .models import Movement

RANK = {"receipt": 0, "sale": 1}
FLAG_NEGATIVE_STOCK = NEGATIVE_STOCK


def day_key(m: Movement) -> tuple:
    return (m.event_at.astimezone(timezone.utc).date(), RANK.get(m.movement_type, 2), m.event_at, m.movement_id)


def time_key(m: Movement) -> tuple:
    return (m.event_at, m.movement_id)


@dataclass(frozen=True)
class Stock:
    product_id: str
    location_id: str
    on_hand_raw: int          # the reconstructed sum, possibly negative
    on_hand: int              # never negative: a negative reconstruction is valued and offered at zero
    running_min: int          # lowest running stock (day order), including the opening 0
    timestamp_order_min: int  # the same by timestamp only, to show what day order prevents
    negative: bool
    movement_count: int

    @property
    def flags(self) -> list[str]:
        return [FLAG_NEGATIVE_STOCK] if self.negative else []


def _run(ordered: Iterable[Movement]) -> tuple[int, int]:
    run = low = 0
    for m in ordered:
        run += m.quantity_delta
        low = min(low, run)
    return run, low


def reconstruct(movements: Iterable[Movement], as_of: datetime) -> dict[tuple[str, str], Stock]:
    """Stock per (product, location) from the movements posted at or before ``as_of`` (a later movement is excluded)."""
    groups: dict[tuple[str, str], list[Movement]] = {}
    for m in movements:
        if m.event_at <= as_of:
            groups.setdefault((m.product_id, m.location_id), []).append(m)
    out: dict[tuple[str, str], Stock] = {}
    for (p, l), items in sorted(groups.items()):
        raw, low = _run(sorted(items, key=day_key))
        _, naive_low = _run(sorted(items, key=time_key))
        out[(p, l)] = Stock(p, l, raw, max(raw, 0), low, naive_low, raw < 0 or low < 0, len(items))
    return out


def end_of_day_on_hand(movements: Iterable[Movement], first: date, last: date) -> dict[tuple[str, str], dict[date, int]]:
    """Raw end-of-day stock per pair for each day first..last (order within a day does not change the day's close)."""
    by_pair: dict[tuple[str, str], list[Movement]] = {}
    for m in movements:
        by_pair.setdefault((m.product_id, m.location_id), []).append(m)
    out: dict[tuple[str, str], dict[date, int]] = {}
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    for pair, items in sorted(by_pair.items()):
        deltas: dict[date, int] = {}
        opening = 0
        for m in items:
            d = m.event_at.astimezone(timezone.utc).date()
            if d < first:
                opening += m.quantity_delta
            elif d <= last:
                deltas[d] = deltas.get(d, 0) + m.quantity_delta
        run, series = opening, {}
        for d in days:
            run += deltas.get(d, 0)
            series[d] = run
        out[pair] = series
    return out
