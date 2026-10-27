"""The evaluation context of one metrics computation: the population, ``as_of``, the optional window and the lookups every metric shares."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .ingest import Population, Row
from .numbers import dec
from .timeutil import matured_count, parse_ts, period_start_instant

Window = tuple[datetime | None, datetime | None]


class Ctx:
    def __init__(self, pop: Population, as_of: datetime, window: Window | None = None, scenario_ids: list[str] | None = None) -> None:
        self.pop = pop
        self.acc = pop.acc
        self.cfg = pop.config
        self.as_of = as_of
        self.window = window if window and (window[0] or window[1]) else None
        self.ini: dict[str, Row] = {i["initiative_id"]: i for i in self.acc["initiatives"]}
        self.scenarios = sorted((s for s in self.acc["scenario_versions"] if scenario_ids is None or s["scenario_id"] in scenario_ids),
                                key=lambda s: s["scenario_id"])
        cap = max((s["horizon_periods"] for s in self.acc["scenario_versions"]), default=0)
        self.M = matured_count(self.cfg, as_of, cap)          # leading matured periods, never more than the longest horizon

    # -- time
    def ts_visible(self, ts: str) -> bool:
        """An instant that exists at as_of and lies in the window (half-open [from, to))."""
        t = parse_ts(ts)
        if t > self.as_of:
            return False
        return self.ts_in_window(t)

    def ts_in_window(self, t: datetime) -> bool:
        if self.window is None:
            return True
        lo, hi = self.window
        return (lo is None or t >= lo) and (hi is None or t < hi)

    def period_in_window(self, p: int) -> bool:
        return self.ts_in_window(period_start_instant(self.cfg, p))

    def window_periods(self, end: int) -> tuple[int, int]:
        """The periods [a, b) of [0, end) whose start lies in the window."""
        if self.window is None:
            return 0, end
        ps = [p for p in range(end) if self.period_in_window(p)]
        return (ps[0], ps[-1] + 1) if ps else (0, 0)

    def observation_visible(self, observed_at: str, stamp: str | None) -> bool:
        """R9-11: an observation exists at as_of when it happened by then AND was recorded by then (``stamp`` is its server-recorded instant; absent: the event
        time), and its event time lies in the window."""
        t = parse_ts(observed_at)
        if t > self.as_of or (stamp is not None and parse_ts(stamp) > self.as_of):
            return False
        return self.ts_in_window(t)

    @staticmethod
    def stamp_of(row: Row, field: str = "recorded_at") -> str | None:
        return row.get(field)

    # -- the plan as it was when a scenario was built (R9-01)
    def created(self, sc: Row) -> datetime:
        return parse_ts(sc["created_at"])

    def costs(self, sc: Row) -> list[Row]:
        """The cost rows that existed at the scenario's ``created_at`` (rows with no ``recorded_at`` are part of the loaded world and always do)."""
        t = self.created(sc)
        return [c for c in self.acc["cost_items"] if c.get("recorded_at") is None or parse_ts(c["recorded_at"]) <= t]

    def benefits(self, sc: Row) -> list[Row]:
        t = self.created(sc)
        return [b for b in self.acc["benefit_items"] if b.get("recorded_at") is None or parse_ts(b["recorded_at"]) <= t]

    # -- assumptions (D-P9-14, R9-01): the version the scenario pins, otherwise the latest that existed when the scenario was created
    def versions(self, iid: str | None, name: str) -> list[Row]:
        return sorted((a for a in self.acc["assumption_versions"] if a["initiative_id"] == iid and a["name"] == name), key=lambda a: a["version_number"])

    def pick(self, iid: str, name: str, sc: Row) -> Row | None:
        vs = self.versions(iid, name)
        pinned = [a for a in vs if a["assumption_id"] in sc["pinned_assumption_ids"]]
        if pinned:
            return pinned[-1]
        t = self.created(sc)
        known = [a for a in vs if parse_ts(a["created_at"]) <= t]
        return known[-1] if known else None

    def assumption(self, aid: str) -> Row:
        return next(a for a in self.acc["assumption_versions"] if a["assumption_id"] == aid)

    def rate(self, sc: Row) -> tuple[Any, str]:
        """The effective per-period rate and where it comes from (D-01, D-P9-06)."""
        if sc["rate_basis"] == self.cfg["period_basis"]:
            return dec(sc["discount_rate"]), "declared"
        conv = self.assumption(sc["rate_conversion_assumption_id"])
        return dec(conv["value"]), "conversion:" + conv["assumption_id"]
