"""Warnings the domain raises beside a result without changing it (D-09: R4-03, R4-18).

* ``calendar_warnings``: calendars are ignored (D-07: SLA targets are wall clock). The only calendar the domain knows
  is ``cal-001``, the 24x7 one; a policy that names another calendar is computed as 24x7 anyway and says so.
* ``cutoff_warnings``: the window is half-open ``[from, to)`` but a backlog cutoff is an instant that INCLUDES events at
  that instant. A cutoff at or after the window end therefore counts events the window itself excludes.
* ``break_flags``: a service interval that opens inside a recorded break. Breaks are not an ingest entity (the D-05
  break rule belongs to the staffed-time metric), so this is a flag, never a rejection; the API refuses it in C03.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .events import History
from .models import Population
from .timeutil import iso_z, parse_ts

CALENDAR_24X7 = "cal-001"


def warning(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path}


def calendar_warnings(pop: Population) -> list[dict[str, Any]]:
    return [warning("SLA_CALENDAR_IGNORED",
                    f"SLA policy {p.sla_policy_id} names calendar {p.calendar_id!r}; calendars are ignored (D-07), "
                    f"targets are measured on the wall clock as if the calendar were {CALENDAR_24X7} (24x7)",
                    f"sla_policies[{p.sla_policy_id}].calendar_id")
            for p in sorted(pop.sla_policies, key=lambda p: p.sla_policy_id) if p.calendar_id != CALENDAR_24X7]


def cutoff_warnings(pop: Population, window: tuple[datetime, datetime],
                    cutoffs: Iterable[datetime]) -> list[dict[str, Any]]:
    """A cutoff not before the window end that really counts an arrival, resolution, reopen or abandonment at or after
    the end (inclusive) is flagged; a cutoff at the end with nothing there (the usual case) is silent."""
    closers = ("resolved", "reopened", "abandoned")
    out = []
    for c in cutoffs:
        if c < window[1]:
            continue
        beyond = sum(1 for t in pop.tickets if window[1] <= t.created_at <= c) + sum(
            1 for e in pop.ticket_events if e.event_type in closers and window[1] <= e.occurred_at <= c)
        if beyond:
            out.append(warning("CUTOFF_AT_OR_AFTER_WINDOW_END",
                               f"backlog cutoff {iso_z(c)} is not before the window end {iso_z(window[1])} and counts "
                               f"{beyond} arrival or closing event(s) the half-open window excludes: a cutoff includes "
                               "events at its own instant (D-09)", "cutoff"))
    return out


def break_flags(hist: dict[str, History], breaks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Service intervals that open inside a recorded break: ``{ticket_id, agent_id, at, break_id}``, sorted."""
    spans: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for b in breaks:
        spans.setdefault(b["agent_id"], []).append((parse_ts(b["starts_at"]), parse_ts(b["ends_at"]), b.get("break_id", "")))
    out = []
    for h in hist.values():
        for iv in h.intervals:
            for a, z, bid in spans.get(iv.agent_id or "", []):
                if a <= iv.start < z:
                    out.append({"ticket_id": iv.ticket_id, "agent_id": iv.agent_id, "at": iso_z(iv.start), "break_id": bid})
    return sorted(out, key=lambda f: (f["at"], f["ticket_id"]))


def break_warnings(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [warning("SERVICE_DURING_BREAK",
                    f"ticket {f['ticket_id']}: agent {f['agent_id']} started service at {f['at']} inside break "
                    f"{f['break_id']}", f"tickets[{f['ticket_id']}]") for f in flags]
