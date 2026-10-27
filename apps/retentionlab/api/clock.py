"""The API's clock: the real UTC time, or (in tests) a fixed, stepping clock so no test depends on the date it runs on.

Everything that stamps a time (default cutoffs, ``frozen_at``, ``created_at`` of a run, "in the future" checks, ``generated_at``)
reads ``now()``. ``freeze(at, step)`` makes each call return ``at``, ``at + step``, ... (strictly increasing, so two runs never
share a ``created_at``); ``freeze(None)`` restores the real clock.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

_lock = threading.Lock()
_next: datetime | None = None
_step = timedelta(milliseconds=1)


def now() -> datetime:
    global _next
    with _lock:
        if _next is None:
            return datetime.now(timezone.utc)
        t, _next = _next, _next + _step
        return t


def freeze(at: datetime | None, step: timedelta = timedelta(milliseconds=1)) -> None:
    global _next, _step
    with _lock:
        _next, _step = at, step
