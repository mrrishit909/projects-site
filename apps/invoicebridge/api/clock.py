"""The server clock (D-09). Every instant that decides a result is stamped HERE, never taken from the client: a client that
could choose ``decided_at`` could pick the policy version in force, approve before the import, or back-date past an export.
Tests replace ``now`` (``monkeypatch.setattr(clock, "now", ...)``)."""
from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    """The current instant, UTC, whole seconds (the instants of the data carry no sub-second part)."""
    return datetime.now(timezone.utc).replace(microsecond=0)
