"""Metrics over an accepted population (D-02, D-03, D-05), exact rationals, 4 dp minutes and 6 dp rates.

``compute_metrics`` returns EXACTLY the keys of expected.json ``metrics``. Choices the contract leaves open:

* Window ``[start, end)`` is half-open. An arrival is a ticket whose ``created_at`` is inside; a completion is a ticket
  whose final resolution is inside. A ticket reopened and resolved again is ONE arrival and ONE completion (the last
  resolution); a reopened ticket that is not yet resolved again is open.
* First response = first human reply (typed replied_human, actor not a bot) minus arrival; a ticket with no human
  reply is outside the first-response population (D-05) and counted in ``disclosures``. Wait = first service start
  minus arrival. Resolution = final resolution minus the ORIGINAL arrival (a transfer never moves the arrival).
* Handling = service intervals clipped to the window (open ones run to the window end); waiting_customer is excluded.
* Staffed minutes: shift overlap with the window; the shift's break is deducted only when the window covers the whole
  shift (D-05). Occupancy = handling / staffed, null when staffed is 0.
* Backlog at a cutoff: arrived, not resolved and not abandoned at that instant (a ticket in service is unresolved).
  Open overdue is counted at the window end: open and older than the resolution target.
* CSAT, invitation and response rates are over the surveys of the tickets completed in the window.
"""
from __future__ import annotations

from datetime import datetime
from fractions import Fraction
from typing import Any, Iterable

from .contract import DEFAULT_ABANDONABLE, GROUP_KEYS, METRIC_KEYS
from .errors import INVALID_WINDOW, DomainError
from .events import History, Interval, is_bot, replay
from .models import Population, Shift, Survey
from .timeutil import d4, d6, iso_z, mean, minutes_between, nearest_rank, overlap_minutes, ratio

Window = tuple[datetime, datetime]
P90 = Fraction(9, 10)


def check_window(window: Window) -> None:
    if window[0] >= window[1]:
        raise DomainError(INVALID_WINDOW, "the window must start before it ends", "from")


def histories(pop: Population) -> dict[str, History]:
    by_t = pop.events_by_ticket()
    return {t.ticket_id: replay(t, by_t.get(t.ticket_id, [])) for t in pop.tickets}


def staffed_minutes(shifts: Iterable[Shift], window: Window) -> tuple[Fraction, Fraction]:
    """(available inside the window, whole-shift total). A break is deducted only for a shift the window covers whole."""
    w0, w1 = window
    avail, whole = Fraction(0), Fraction(0)
    for s in shifts:
        length = minutes_between(s.starts_at, s.ends_at)
        whole += length - s.break_minutes
        ov = overlap_minutes(s.starts_at, s.ends_at, w0, w1)
        if ov > 0:
            avail += ov - (s.break_minutes if w0 <= s.starts_at and s.ends_at <= w1 else 0)
    return avail, whole


def _compute(pop: Population, hist: dict[str, History], ticket_ids: set[str], intervals: list[Interval],
             shifts: list[Shift] | None, window: Window, cutoffs: list[datetime],
             abandonable: Iterable[str]) -> dict[str, Any]:
    w0, w1 = window
    check_window(window)
    hours = minutes_between(w0, w1) / 60
    tickets = [t for t in pop.tickets if t.ticket_id in ticket_ids]
    policy = {p.priority: p for p in pop.sla_policies}
    by_id = {t.ticket_id: t for t in tickets}
    inside = lambda x: x is not None and w0 <= x < w1  # noqa: E731

    arrivals = sorted((t for t in tickets if inside(t.created_at)), key=lambda t: t.ticket_id)
    completions = sorted((t for t in tickets if inside(hist[t.ticket_id].final_resolution)),
                         key=lambda t: t.ticket_id)
    first_resp = {t.ticket_id: minutes_between(t.created_at, hist[t.ticket_id].first_human_reply_at)
                  for t in arrivals if hist[t.ticket_id].first_human_reply_at is not None}
    wait = {t.ticket_id: minutes_between(t.created_at, hist[t.ticket_id].first_service_at)
            for t in arrivals if hist[t.ticket_id].first_service_at is not None}
    resolution = {t.ticket_id: minutes_between(t.created_at, hist[t.ticket_id].final_resolution)  # type: ignore[arg-type]
                  for t in completions}

    fr_ok = sum(1 for tid, m in first_resp.items()
                if by_id[tid].priority in policy and m <= policy[by_id[tid].priority].first_response_minutes)
    fr_elig = sum(1 for tid in first_resp if by_id[tid].priority in policy)
    rs_ok = sum(1 for tid, m in resolution.items()
                if by_id[tid].priority in policy and m <= policy[by_id[tid].priority].resolution_minutes)
    rs_elig = sum(1 for tid in resolution if by_id[tid].priority in policy)
    overdue = sum(1 for t in tickets if t.created_at <= w1 and hist[t.ticket_id].open_at(w1) and t.priority in policy
                  and minutes_between(t.created_at, w1) > policy[t.priority].resolution_minutes)

    handling = sum((iv.minutes_within(w0, w1) for iv in intervals), Fraction(0))
    if shifts is None:
        staff = whole = occ = None
    else:
        staff, whole = staffed_minutes(shifts, window)
        occ = ratio(handling, staff)

    ab_set = set(abandonable)
    ab_arr = [t for t in arrivals if t.channel in ab_set]
    ab_n = sum(1 for t in ab_arr if hist[t.ticket_id].abandoned_at is not None)

    done = {t.ticket_id for t in completions}
    surveys: list[Survey] = [s for s in pop.surveys if s.ticket_id in done]
    invited = [s for s in surveys if s.invited_at is not None]
    responded = [s for s in invited if s.score is not None and s.response_at is not None]
    positive = sum(1 for s in responded if s.score >= 4)  # type: ignore[operator]

    out: dict[str, Any] = {
        "arrival_count": len(arrivals), "completion_count": len(completions),
        "arrival_rate_per_hour": d6(Fraction(len(arrivals)) / hours),
        "completion_rate_per_hour": d6(Fraction(len(completions)) / hours),
        "backlog": {iso_z(c): sum(1 for t in tickets if hist[t.ticket_id].open_at(c)) for c in cutoffs},
        "first_response_minutes": {k: d4(v) for k, v in sorted(first_resp.items())},
        "mean_first_response_minutes": d4(mean(list(first_resp.values()))),
        "p90_first_response_minutes": d4(nearest_rank(list(first_resp.values()), P90)),
        "wait_minutes": {k: d4(v) for k, v in sorted(wait.items())},
        "mean_wait_minutes": d4(mean(list(wait.values()))),
        "resolution_minutes": {k: d4(v) for k, v in sorted(resolution.items())},
        "mean_resolution_minutes": d4(mean(list(resolution.values()))),
        "handling_minutes_total": d4(handling),
        "sla_first_response_compliance": d6(ratio(fr_ok, fr_elig)),
        "sla_first_response_within": fr_ok, "sla_first_response_eligible": fr_elig,
        "sla_resolution_compliance": d6(ratio(rs_ok, rs_elig)),
        "sla_resolution_within": rs_ok, "sla_resolution_eligible": rs_elig,
        "open_overdue_at_cutoff": overdue,
        "staffed_available_minutes": d4(staff), "staffed_shift_minutes_whole": d4(whole),
        "agent_occupancy": d6(occ),
        "abandonment_rate": d6(ratio(ab_n, len(ab_arr))),
        "csat": d6(ratio(positive, len(responded))),
        "survey_invitation_rate": d6(ratio(len(invited), len(completions))),
        "survey_response_rate": d6(ratio(len(responded), len(invited))),
        "empty_population": len(tickets) == 0,
    }
    assert tuple(out) == METRIC_KEYS
    return out


def compute_metrics(pop: Population, window: Window, cutoffs: list[datetime] | None = None,
                    abandonable_channels: Iterable[str] | None = None) -> dict[str, Any]:
    """All metrics of ``pop`` for the half-open ``window``; ``cutoffs`` are the backlog instants."""
    hist = histories(pop)
    intervals = [iv for h in hist.values() for iv in h.intervals]
    return _compute(pop, hist, {t.ticket_id for t in pop.tickets}, intervals, list(pop.shifts), window,
                    list(cutoffs if cutoffs is not None else [window[1]]),
                    DEFAULT_ABANDONABLE if abandonable_channels is None else abandonable_channels)


def group_values(pop: Population, group_by: str, hist: dict[str, History]) -> dict[str, set[str]]:
    """Ticket ids per group. ``agent``: the tickets each agent carried to their end (never-served tickets belong to
    no agent). ``queue`` is the ticket's current queue."""
    if group_by not in GROUP_KEYS:
        raise DomainError("INVALID_GROUP_BY", f"group_by must be one of {', '.join(GROUP_KEYS)}", "group_by")
    out: dict[str, set[str]] = {}
    for t in pop.tickets:
        key = {"queue": t.queue_id, "priority": t.priority, "channel": t.channel,
               "agent": hist[t.ticket_id].owner_agent}[group_by]
        if key is not None:
            out.setdefault(key, set()).add(t.ticket_id)
    return out


def group_metrics(pop: Population, group_by: str, window: Window, cutoffs: list[datetime] | None = None,
                  abandonable_channels: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    """Metrics per queue, priority, agent or channel (keys sorted). Staffing figures exist only for ``agent``
    (shifts are the agent's; a queue or a priority has no staffed time of its own): they are null otherwise."""
    hist = histories(pop)
    cuts = list(cutoffs if cutoffs is not None else [window[1]])
    ab = DEFAULT_ABANDONABLE if abandonable_channels is None else abandonable_channels
    out: dict[str, dict[str, Any]] = {}
    for key, ids in sorted(group_values(pop, group_by, hist).items()):
        if group_by == "agent":
            ivs = [iv for h in hist.values() for iv in h.intervals if iv.agent_id == key]
            shifts: list[Shift] | None = [s for s in pop.shifts if s.agent_id == key]
        else:
            ivs, shifts = [iv for tid in ids for iv in hist[tid].intervals], None
        out[key] = _compute(pop, hist, ids, ivs, shifts, window, cuts, ab)
    return out


def disclosures(pop: Population, window: Window) -> dict[str, Any]:
    """What a reader must see beside the numbers (P04-TEST-02/06/10/11): reopens, bot replies, transfers, the P90
    rule, open overdue and the survey nonresponse that skews CSAT."""
    hist = histories(pop)
    w0, w1 = window
    inside = lambda x: x is not None and w0 <= x < w1  # noqa: E731
    arr = [t for t in pop.tickets if inside(t.created_at)]
    done = {t.ticket_id for t in pop.tickets if inside(hist[t.ticket_id].final_resolution)}
    surveys = [s for s in pop.surveys if s.ticket_id in done]
    invited = [s for s in surveys if s.invited_at is not None]
    responded = [s for s in invited if s.score is not None and s.response_at is not None]
    return {
        "reopened_tickets": sum(1 for t in arr if hist[t.ticket_id].reopen_count > 0),
        "reopen_events": sum(hist[t.ticket_id].reopen_count for t in arr),
        "transferred_tickets": sum(1 for t in arr if hist[t.ticket_id].transfers),
        "arrivals_without_human_reply": sum(1 for t in arr if hist[t.ticket_id].first_human_reply_at is None),
        "bot_events_ignored_for_first_response": sum(
            1 for e in pop.ticket_events if e.event_type == "acknowledged_bot" or (
                e.event_type == "replied_human" and is_bot(e.actor_id))),
        "open_overdue_at_window_end": _compute(pop, hist, {t.ticket_id for t in pop.tickets}, [], None, window, [],
                                               DEFAULT_ABANDONABLE)["open_overdue_at_cutoff"],
        "p90_method": "nearest rank: sort ascending, take index ceil(0.9 n); n is the first-response population",
        "csat": {"completed_tickets": len(done), "invited": len(invited), "valid_responses": len(responded),
                 "nonresponse": len(invited) - len(responded),
                 "note": "CSAT is over valid responses only; nonresponse is not random, read it beside the response rate"},
        "staffed_break_rule": "a shift's break is deducted only when the window covers the whole shift (D-05)",
    }
