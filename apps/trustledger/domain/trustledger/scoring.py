"""The weighted quality score and the critical override (D-01, D-06).

score = sum(dimension score x weight) / sum(weights of the measured dimensions), under the NAMED weight version. A dimension with no
measured score (no active rule, or a zero denominator) is dropped from both sums; a dataset that measures nothing has a null score.
Several active rules of one dimension on one dataset contribute the plain mean of their scores. Critical failures (failure counts of
active critical rules on the current run) and open critical issues are counted separately and NEVER hidden by the score:
``critical_override`` is true if either is above 0, however high the score.
"""
from __future__ import annotations

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
                   version: str | None) -> tuple[Row, Row]:
    """(weighted_score block, critical_failures block)."""
    w = weights_of(pop, version) if pop.weight_versions else {}
    ds_out: Row = {}
    by_version: dict[str, Row] = {w_.weight_version: {} for w_ in sorted(pop.weight_versions, key=lambda x: x.weight_version)}
    cf_total = ci_total = over = 0
    for ds in sorted(d.dataset_id for d in pop.datasets):
        sc = dim_scores.get(ds, {})
        measured, wsum, val = score(sc, w) if w else ([d for d in DIMENSIONS if d in sc], Fraction(0), None)
        cf = sum(m.failures for m in measures if m.rule.dataset_id == ds and m.rule.severity == "critical")
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
            {"failures": cf_total, "open_issues": ci_total, "datasets_overridden": over})
