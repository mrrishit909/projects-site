"""The twelve metrics of expected.json (D-01..D-06), computed from a ``Population`` at ``as_of``.

Facts timestamped after ``as_of`` do not exist yet: datasets registered later, runs later, issues detected later, versions valid
later, observed edges, candidates and decisions later are left out. A disabled rule was still active before ``disabled_at``. The
optional half-open ``window`` [from, to) narrows the time-stamped facts a metric counts: issues by ``detected_at``, observed lineage
by ``observed_at``, candidates by ``proposed_at`` and merge decisions by ``decided_at``. Current-state measures (the rules over the
dataset rows, timeliness, ownership, definitions) are snapshots at ``as_of`` and are not windowed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Mapping

from .contract import METRIC_KEYS
from .errors import INVALID_WINDOW, DomainError
from .issues import IssueView, classify, resolution_block
from .matching import matching_block
from .measure import Measure, measure_rule, timeliness_of
from .models import Population, weight_in_force
from .numbers import p6, ratio
from .scoring import carried_failures, dimension_scores, weighted_block
from .structure import definitions_blocks, lineage_block, ownership_block
from .timeutil import ON_TIME, PENDING, iso_z, timeliness_state
from .verification import precision_block

Row = dict[str, Any]
Window = tuple[datetime | None, datetime | None]


@dataclass
class Computation:
    metrics: Row
    rules: Row
    definitions: Row
    matching: Row
    weight_version: str | None
    empty_population: bool
    warnings: list[Row] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    views: list[IssueView] = field(default_factory=list)
    timeliness_probes: Row = field(default_factory=dict)


def in_window(t: datetime, window: Window | None) -> bool:
    return window is None or ((window[0] is None or t >= window[0]) and (window[1] is None or t < window[1]))


def check_window(window: Window | None) -> None:
    if window and window[0] is not None and window[1] is not None and window[0] >= window[1]:
        raise DomainError(INVALID_WINDOW, "from must be before to (the window is half-open)", path="from")


def at(pop: Population, as_of: datetime, window: Window | None = None) -> Population:
    """The population as it stood at ``as_of`` (and inside ``window`` for the time-stamped facts)."""
    ds = [d for d in pop.datasets if d.registered_at <= as_of]
    ds_ids = {d.dataset_id for d in ds}
    rules = [r for r in pop.quality_rules if r.dataset_id in ds_ids]
    rule_ids = {r.rule_id for r in rules}
    runs = [r for r in pop.rule_runs if r.run_at <= as_of and r.rule_id in rule_ids]
    run_ids = {r.rule_run_id for r in runs}
    cands = [c for c in pop.match_candidates if c.proposed_at <= as_of and in_window(c.proposed_at, window)]
    return replace(
        pop, datasets=ds, fields=[f for f in pop.fields if f.dataset_id in ds_ids],
        quality_rules=rules, rule_runs=runs,
        issues=[i for i in pop.issues if i.detected_at <= as_of and in_window(i.detected_at, window) and i.rule_run_id in run_ids],
        lineage_edges=[e for e in pop.lineage_edges if e.observed_at is None or (e.observed_at <= as_of and in_window(e.observed_at, window))],
        metric_versions=[m for m in pop.metric_versions if m.valid_from <= as_of],
        definition_changes=[c for c in pop.definition_changes if c.changed_at <= as_of],
        match_candidates=cands,
        merge_decisions=[m for m in pop.merge_decisions if m.decided_at <= as_of and in_window(m.decided_at, window)])


def compare_runs(prev: Any, cur: Any) -> Row:
    """Two runs of one rule are comparable only when their rule version (the eligibility definition) is the same; otherwise no rate
    is compared and the reason is RULE_VERSION_DIFFERS (D-01, P07-TEST-12). ``prev``/``cur`` carry rule_version and counts."""
    same = prev.rule_version == cur.rule_version
    rate = lambda r: p6(ratio(r.failure_count, r.eligible_count))  # noqa: E731
    return {"previous_run_id": prev.rule_run_id, "previous_rule_version": prev.rule_version, "current_rule_version": cur.rule_version,
            "comparable": same, "reason": None if same else "RULE_VERSION_DIFFERS",
            "previous_eligible_count": prev.eligible_count, "current_eligible_count": cur.eligible_count,
            "failure_rate_previous": rate(prev) if same else None, "failure_rate_current": rate(cur) if same else None}


@dataclass(frozen=True)
class _Cur:
    """The current run of a rule, shaped like a stored run for ``compare_runs``."""
    rule_run_id: str | None
    rule_version: int
    eligible_count: int
    failure_count: int


def restrict(pop: Population, dataset_ids: set[str] | None = None, severities: set[str] | None = None) -> Population:
    """The part of the population one dataset group or severity sees: its datasets, their active and disabled rules (of the given
    severities), those rules' runs and issues, and the lineage edges that touch the datasets. Dataset rows stay whole because a
    relationship rule reads its parent dataset's rows. Owners, definitions and matching are global and are not narrowed."""
    ds = [d for d in pop.datasets if dataset_ids is None or d.dataset_id in dataset_ids]
    ids = {d.dataset_id for d in ds}
    rules = [r for r in pop.quality_rules if r.dataset_id in ids and (severities is None or r.severity in severities)]
    rule_ids = {r.rule_id for r in rules}
    runs = [r for r in pop.rule_runs if r.rule_id in rule_ids]
    run_ids = {r.rule_run_id for r in runs}
    return replace(pop, datasets=ds, fields=[f for f in pop.fields if f.dataset_id in ids], quality_rules=rules, rule_runs=runs,
                   issues=[i for i in pop.issues if i.rule_run_id in run_ids],
                   lineage_edges=[e for e in pop.lineage_edges if e.source_dataset_id in ids or e.target_dataset_id in ids])


def compute(pop: Population, as_of: datetime, weight_version: str | None = None, window: Window | None = None,
            truth: Mapping[str, str] | None = None, empty: bool | None = None) -> Computation:
    """All metrics at ``as_of`` under ``weight_version`` (default: the version in force at ``as_of``). ``empty`` overrides the
    empty-population test (a restricted view is not an empty population)."""
    check_window(window)
    empty = pop.total() == 0 if empty is None else empty
    wv = weight_version or weight_in_force(pop, as_of) or pop.weight_version
    p = at(pop, as_of, window)
    warnings: list[Row] = []

    live = [r for r in sorted(p.quality_rules, key=lambda r: r.rule_id) if r.active_at(as_of)]
    for r in live:
        if r.rule_type == "validity" and not r.definition.get("pattern"):          # a rule with nothing to test is not measured
            warnings.append({"code": "RULE_NOT_MEASURABLE", "path": f"rules.runs.{r.rule_id}", "message": f"validity rule {r.rule_id} has no pattern"})
    measures = [measure_rule(r, p, as_of) for r in live if not (r.rule_type == "validity" and not r.definition.get("pattern"))]
    runs: Row = {m.rule.rule_id: m.run(wv, as_of) for m in measures}
    by_type = lambda t: {m.rule.rule_id: m.block for m in measures if m.rule.rule_type == t}  # noqa: E731

    comparisons: Row = {}
    for m in measures:
        prev = [r for r in p.rule_runs if r.rule_id == m.rule.rule_id and r.kind == "scheduled" and r.run_at < as_of]
        if prev:
            last = max(prev, key=lambda r: (r.run_at, r.rule_run_id))
            comparisons[m.rule.rule_id] = compare_runs(last, _Cur(None, m.rule.version_number, m.eligible, m.failures))
    disabled: Row = {}
    for r in p.quality_rules:
        if not r.active_at(as_of):
            disabled[r.rule_id] = {"disabled_at": iso_z(r.disabled_at), "disabled_reason": r.disabled_reason,
                                   "runs_retained": sum(1 for x in p.rule_runs if x.rule_id == r.rule_id),
                                   "issues_retained": sum(1 for i in p.issues if next(x for x in p.rule_runs if x.rule_run_id == i.rule_run_id).rule_id == r.rule_id)}

    tl = {}
    for d in sorted(p.datasets, key=lambda d: d.dataset_id):
        t = timeliness_of(d, as_of)
        if t is not None:
            tl[d.dataset_id] = t
    on = sum(1 for v in tl.values() if v["state"] == ON_TIME)
    pending = sum(1 for v in tl.values() if v["state"] == PENDING)
    evaluated = len(tl) - pending                                              # a pending occurrence is neither on time nor late (D-10 R7-01)
    timeliness = {"monitored_datasets": len(tl), "evaluated_datasets": evaluated, "pending_count": pending, "on_time_count": on,
                  "value": p6(ratio(on, evaluated)), "datasets": tl}

    views = classify(p, as_of)
    carried = carried_failures(p, as_of)
    weighted, critical = weighted_block(p, dimension_scores(measures), measures, views, wv, carried)
    cov, defs = definitions_blocks(p, as_of)
    matching, approved, reviewed = matching_block(p)
    metrics = {
        "completeness": by_type("completeness"), "validity": by_type("validity"), "uniqueness": by_type("uniqueness"),
        "relationship_integrity": by_type("relationship"), "timeliness": timeliness, "weighted_score": weighted,
        "critical_failures": critical, "resolution_time": resolution_block(views), "ownership_coverage": ownership_block(p, as_of),
        "definition_coverage": cov, "match_precision": precision_block(truth, approved, reviewed),
        "lineage_coverage": lineage_block(p)}
    assert tuple(metrics) == METRIC_KEYS
    if metrics["match_precision"]["precision"] is None and approved:
        warnings.append({"code": "MATCH_TRUTH_UNAVAILABLE", "path": "metrics.match_precision",
                         "message": "no synthetic truth names every decided record: precision is unknown (null), not 0"})
    if any(v.get("critical_override") for v in weighted["datasets"].values()):
        warnings.append({"code": "CRITICAL_OVERRIDE", "path": "metrics.weighted_score",
                         "message": "a score hides an open critical failure or issue: read critical_failures beside it"})
    if not pop.weight_versions:
        warnings.append({"code": "NO_WEIGHT_VERSION", "path": "weight_version", "message": "no rule weight version is defined: scores are null"})
    probes: Row = {}
    for c in pop.probe_timeliness:                  # stated cases: the rule alone, no dataset, no population
        state, s, dl = timeliness_state(c["timezone"], c["local_time"], c["grace_minutes"], c["last_refreshed_at"], c["as_of"])
        probes[c["probe_id"]] = {"as_of": iso_z(c["as_of"]), "last_refreshed_at": iso_z(c["last_refreshed_at"]), "evaluated_occurrence_utc": iso_z(s),
                                 "deadline_utc": iso_z(dl), "state": state}
    return Computation(metrics, {"active_count": len(runs), "runs": runs, "comparisons": comparisons, "disabled": disabled},
                       defs, matching, wv, empty, warnings, measures, views, probes)
