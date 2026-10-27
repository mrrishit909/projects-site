"""The weighted quality score and the critical override (D-01, D-06).

score = sum(dimension score x weight) / sum(weights of the measured dimensions), under the NAMED weight version. A dimension with no
measured score (no active rule, or a zero denominator) is dropped from both sums; a dataset that measures nothing has a null score.
Several active rules of one dimension on one dataset contribute the plain mean of their scores. Critical failures (failure counts of
active critical rules on the current run) and open critical issues are counted separately and NEVER hidden by the score:
``critical_override`` is true if either is above 0, however high the score. A critical rule that is disabled while its latest run fails
keeps counting that failure (and the override) until a verified rerun passes: disabling is not repair (D-10, R7-02).
"""
from __future__ import annotations

from datetime import datetime
from fractions import Fraction
from typing import Any

from .contract import DIMENSIONS
from .errors import UNKNOWN_WEIGHT_VERSION, DomainError
from .issues import IssueView
from .measure import Measure
from .models import Population
from .numbers import p6

Row = dict[str, Any]


def dimension_scores(measures: list[Measure]) -> dict[str, dict[str, Fraction]]:
    """dataset -> dimension -> mean score of its measured rules."""
    acc: dict[str, dict[str, list[Fraction]]] = {}
    for m in measures:
        if m.value is not None:
            acc.setdefault(m.rule.dataset_id, {}).setdefault(m.rule.rule_type, []).append(m.value)
    return {ds: {dim: sum(v, Fraction(0)) / len(v) for dim, v in dims.items()} for ds, dims in acc.items()}


def carried_failures(pop: Population, as_of: datetime) -> list[Row]:
    """Failures of disabled critical rules that are still live: the rule's latest run (by ``run_at``, a rerun included) at ``as_of`` has
    failures. A later rerun that passes is the latest run, which is what clears it."""
    latest: dict[str, Any] = {}
    for r in pop.rule_runs:
        cur = latest.get(r.rule_id)
        if cur is None or (r.run_at, r.rule_run_id) > (cur.run_at, cur.rule_run_id):
            latest[r.rule_id] = r
    out = []
    for rule in sorted(pop.quality_rules, key=lambda x: x.rule_id):
        run = latest.get(rule.rule_id)
        if rule.severity == "critical" and not rule.active_at(as_of) and run is not None and run.failure_count > 0:
            out.append({"dataset_id": rule.dataset_id, "rule_id": rule.rule_id, "rule_run_id": run.rule_run_id, "failure_count": run.failure_count})
    return out


def weights_of(pop: Population, version: str | None) -> dict[str, Fraction]:
    for w in pop.weight_versions:
        if w.weight_version == version:
            return w.weights
    raise DomainError(UNKNOWN_WEIGHT_VERSION, f"unknown weight version {version!r}", path="weight_version")


def score(scores: dict[str, Fraction], weights: dict[str, Fraction]) -> tuple[list[str], Fraction, Fraction | None]:
    measured = [d for d in DIMENSIONS if d in scores]
    wsum = sum((weights[d] for d in measured), Fraction(0))
    if not measured or wsum == 0:
        return measured, wsum, None
    return measured, wsum, sum((weights[d] * scores[d] for d in measured), Fraction(0)) / wsum


def weighted_block(pop: Population, dim_scores: dict[str, dict[str, Fraction]], measures: list[Measure], views: list[IssueView],
                   version: str | None, carried: list[Row] | None = None) -> tuple[Row, Row]:
    """(weighted_score block, critical_failures block)."""
    w = weights_of(pop, version) if pop.weight_versions else {}
    ds_out: Row = {}
    by_version: dict[str, Row] = {w_.weight_version: {} for w_ in sorted(pop.weight_versions, key=lambda x: x.weight_version)}
    cf_total = ci_total = over = 0
    for ds in sorted(d.dataset_id for d in pop.datasets):
        sc = dim_scores.get(ds, {})
        measured, wsum, val = score(sc, w) if w else ([d for d in DIMENSIONS if d in sc], Fraction(0), None)
        cf = (sum(m.failures for m in measures if m.rule.dataset_id == ds and m.rule.severity == "critical")
              + sum(c["failure_count"] for c in carried or () if c["dataset_id"] == ds))
        ci = sum(1 for v in views if v.severity == "critical" and v.cls != "resolved" and v.rule.dataset_id == ds)
        ov = cf > 0 or ci > 0
        ds_out[ds] = {"weight_version": version, "dimension_scores": {d: p6(sc[d]) for d in measured}, "measured_dimensions": measured,
                      "weight_sum": p6(wsum), "value": p6(val), "critical_failures": cf, "critical_open_issues": ci,
                      "critical_override": ov}
        cf_total += cf
        ci_total += ci
        over += 1 if ov else 0
        for w_ in pop.weight_versions:
            by_version[w_.weight_version][ds] = p6(score(sc, w_.weights)[2])
    return ({"datasets": ds_out, "by_weight_version": by_version},
            {"failures": cf_total, "open_issues": ci_total, "datasets_overridden": over, "carried": list(carried or [])})
