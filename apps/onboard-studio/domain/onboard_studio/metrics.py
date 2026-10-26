"""Metric aggregation (D-01, D-04, D-05). Rates come from aggregated numerators and denominators.

``compute_metrics`` returns exactly the keys of ``expected.json``. Paused intervals that contribute no
business hours are reported separately by ``compute_with_flags`` (P02-TEST-03).
"""
from __future__ import annotations

from datetime import datetime
from fractions import Fraction
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping

from . import calendar as cal
from .errors import INVALID_WINDOW, DomainError
from .models import Case, Population
from .workflow import accepted_types_latest
from .timeutil import ZERO, d4, d6, hours, iso_z, mean, parse_ts, ratio, seconds_between

Window = tuple[datetime | None, datetime | None]
PausePolicy = "list[str] | tuple[str, ...] | Mapping[str, list[str]] | None"

FLAG_PAUSE_OUTSIDE_WORKING = "PAUSE_OUTSIDE_WORKING_INTERVAL"
#: D-09: a completed case whose SLA calendar has no working interval cannot be evaluated against the SLA.
FLAG_SLA_UNEVALUATED = "SLA_UNEVALUATED_NO_WORKING_TIME"
GROUP_KEYS = ("organization", "segment", "region", "workflow_version")


def check_window(window: Window) -> None:
    lo, hi = window
    if lo is not None and hi is not None and lo >= hi:
        raise DomainError(INVALID_WINDOW, "window start must be before end",
                          details={"from": iso_z(lo), "to": iso_z(hi)})


def in_window(at: datetime, window: Window) -> bool:
    """Half-open [from, to) on opened_at (the metrics contract)."""
    lo, hi = window
    return (lo is None or at >= lo) and (hi is None or at < hi)


def _policy_for(rule: Any, override: Any) -> tuple[str, ...]:
    if override is None:
        return tuple(rule.pause_policy)
    if isinstance(override, Mapping):
        return tuple(override.get(rule.sla_rule_id, rule.pause_policy))
    return tuple(override)


def _calendars(pop: Population) -> dict[str, list[cal.Interval]]:
    """Effective working intervals per calendar. A calendar with no ``working`` interval is absent (D-09)."""
    working: dict[str, list[cal.Interval]] = {}
    holidays: dict[str, list[cal.Interval]] = {}
    for ci in pop.calendar_intervals:
        (holidays if ci.kind == "holiday" else working).setdefault(ci.calendar_id, []).append(
            (ci.starts_at, ci.ends_at))
    return {cid: cal.effective_intervals(w, holidays.get(cid)) for cid, w in working.items()}


def sla_unevaluated_cases(flags: Iterable[Mapping[str, str]]) -> int:
    """D-09: completed cases left out of the SLA denominator because their calendar has no working interval."""
    return sum(1 for f in flags if f.get("flag") == FLAG_SLA_UNEVALUATED)


def compute_with_flags(pop: Population, pause_policy: Any = None, cutoffs: Iterable[Any] = (),
                       window: Window = (None, None)) -> tuple[dict[str, Any], list[dict[str, str]]]:
    check_window(window)
    cases = [c for c in pop.cases if in_window(c.opened_at, window)]
    if len(cases) != len(pop.cases):
        pop = pop.subset({c.case_id for c in cases})
    calendars = _calendars(pop)
    sla = {r.workflow_version_id: r for r in pop.sla_rules}
    flags: list[dict[str, str]] = []

    done_with_rule = [c for c in cases if c.completed_at is not None and c.workflow_version_id in sla]
    completed = [c for c in done_with_rule if sla[c.workflow_version_id].calendar_id in calendars]
    for c in done_with_rule:  # D-09: unevaluated, excluded from every mean and from the SLA denominator
        if sla[c.workflow_version_id].calendar_id not in calendars:
            flags.append({"case_id": c.case_id, "flag": FLAG_SLA_UNEVALUATED})
    waits_by_case: dict[str, list[Any]] = {}
    for w in pop.waiting_intervals:
        waits_by_case.setdefault(w.case_id, []).append(w)

    cal_h, bus_h, paused_h, pov_h, act_h = [], [], [], [], []
    within = 0
    for c in completed:
        rule = sla[c.workflow_version_id]
        working = calendars[rule.calendar_id]
        opened, done = c.opened_at, c.completed_at
        assert done is not None
        eligible = set(_policy_for(rule, pause_policy))
        business = hours(cal.overlap_seconds(opened, done, working))
        clipped: list[cal.Interval] = []
        for w in sorted(waits_by_case.get(c.case_id, []), key=lambda w: (w.starts_at, w.waiting_interval_id)):
            if w.reason_code not in eligible:
                continue  # customer waiting that is not pause-eligible is neither deducted nor hidden
            lo, hi = max(w.starts_at, opened), min(w.ends_at or done, done)
            if hi <= lo:
                continue
            if cal.overlap_seconds(lo, hi, working) == 0:
                flags.append({"waiting_interval_id": w.waiting_interval_id, "case_id": c.case_id,
                              "flag": FLAG_PAUSE_OUTSIDE_WORKING})
            clipped.append((lo, hi))
        union = cal.merge(clipped)
        paused = sum((hours(seconds_between(s, e)) for s, e in union), ZERO)
        pov = sum((hours(cal.overlap_seconds(s, e, working)) for s, e in union), ZERO)
        active = business - pov if business > pov else ZERO
        cal_h.append(hours(seconds_between(opened, done)))
        bus_h.append(business)
        paused_h.append(paused)
        pov_h.append(pov)
        act_h.append(active)
        if active * 60 <= rule.business_minutes:
            within += 1

    backlog: dict[str, int] = {}
    for cut in cutoffs:
        t = parse_ts(cut)
        backlog[iso_z(t)] = sum(1 for c in cases if c.opened_at <= t and (c.completed_at is None or c.completed_at > t))

    docs_by_case: dict[str, list[Any]] = {}
    for d in pop.document_versions:
        docs_by_case.setdefault(d.case_id, []).append(d)
    submitted = [c for c in cases if docs_by_case.get(c.case_id)]
    reworked = [c for c in submitted if any(d.review_status == "rejected" for d in docs_by_case[c.case_id])]

    firsts: dict[tuple[str, str], Any] = {}
    for d in pop.document_versions:
        k = (d.case_id, d.document_type)
        if k not in firsts or d.version_number < firsts[k].version_number:
            firsts[k] = d
    reviewed = [d for d in firsts.values() if d.review_status in ("accepted", "rejected")]
    first_ok = [d for d in reviewed if d.review_status == "accepted"]

    req_total = req_ok = 0
    for c in cases:
        required = pop.requirements.get(c.workflow_version_id, ())
        accepted = accepted_types_latest(docs_by_case.get(c.case_id, []))  # D-06: the latest version decides
        req_total += len(required)
        req_ok += sum(1 for t in required if t in accepted)

    per_step: dict[str, set[tuple[str, datetime]]] = {}
    for a in pop.assignments:  # exact replays (same step, assignee and start) count once
        per_step.setdefault(a.step_instance_id, set()).add((a.assignee_id, a.assigned_at))
    handoffs = sum(len(v) - 1 for v in per_step.values())

    case_wv = {c.case_id: c.workflow_version_id for c in cases}
    step_waits: dict[str, list[Fraction]] = {s.step_definition_id: [] for s in pop.step_definitions}
    for si in pop.step_instances:
        rule = sla.get(case_wv.get(si.case_id, ""))
        if si.started_at is None or si.ready_at is None or rule is None or rule.calendar_id not in calendars:
            continue
        step_waits.setdefault(si.step_definition_id, []).append(
            hours(cal.overlap_seconds(si.ready_at, si.started_at, calendars[rule.calendar_id])))

    metrics = {
        "calendar_cycle_time_hours": d4(mean(cal_h)),
        "business_cycle_time_hours": d4(mean(bus_h)),
        "paused_time_hours": d4(mean(paused_h)),
        "paused_business_overlap_hours": d4(mean(pov_h)),
        "active_elapsed_hours": d4(mean(act_h)),
        "sla_attainment": d6(ratio(within, len(completed))),
        "completed_eligible_cases": len(completed),
        "within_sla_cases": within,
        "open_backlog_at_cutoff": backlog,
        "rework_rate": d6(ratio(len(reworked), len(submitted))),
        "handoff_count": handoffs,
        "step_waiting_time_hours": {k: d4(mean(v)) for k, v in sorted(step_waits.items())},
        "first_pass_approval": d6(ratio(len(first_ok), len(reviewed))),
        "document_completeness": d6(ratio(req_ok, req_total)),
        "empty_population": len(cases) == 0,
    }
    return metrics, flags


def compute_metrics(pop: Population, pause_policy: Any = None, cutoffs: Iterable[Any] = (),
                    window: Window = (None, None)) -> dict[str, Any]:
    """The D-04 metrics. ``pause_policy`` overrides the SLA rules' pause policy (a list for every rule, or
    ``{sla_rule_id: list}``); ``None`` keeps each rule's configured policy."""
    return compute_with_flags(pop, pause_policy, cutoffs, window)[0]


def _group_key(pop: Population, by: str) -> Callable[[Case], str]:
    orgs = {o.organization_id: o for o in pop.organizations}
    if by == "organization":
        return lambda c: c.organization_id
    if by == "segment":
        return lambda c: orgs[c.organization_id].segment if c.organization_id in orgs else "UNKNOWN"
    if by == "region":
        return lambda c: orgs[c.organization_id].region if c.organization_id in orgs else "UNKNOWN"
    if by == "workflow_version":
        return lambda c: c.workflow_version_id
    raise ValueError(f"group_by must be one of {GROUP_KEYS}")


def group_metrics(pop: Population, by: str, pause_policy: Any = None, cutoffs: Iterable[Any] = (),
                  window: Window = (None, None)) -> dict[str, dict[str, Any]]:
    """Metrics per group of cases, keyed by the group value in sorted order."""
    check_window(window)
    key = _group_key(pop, by)
    members: dict[str, set[str]] = {}
    for c in pop.cases:
        if in_window(c.opened_at, window):
            members.setdefault(key(c), set()).add(c.case_id)
    cuts = list(cutoffs)
    return {g: compute_metrics(pop.subset(ids), pause_policy, cuts) for g, ids in sorted(members.items())}
