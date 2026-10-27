"""Ownership coverage, versioned definitions and definition coverage, lineage coverage (D-02, D-06)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .measure import is_missing
from .models import Population
from .numbers import p6, ratio
from .timeutil import iso_z

Row = dict[str, Any]


def owner_covers(owner: Any, as_of: datetime) -> bool:
    """An owner is accountable at ``as_of`` when active; one deactivated at or before ``as_of`` leaves its datasets uncovered."""
    if owner is None:
        return False
    if owner.deactivated_at is not None:
        return as_of < owner.deactivated_at
    return owner.active


def ownership_block(pop: Population, as_of: datetime) -> Row:
    owners = {o.owner_id: o for o in pop.owners}
    cov = [d.dataset_id for d in pop.datasets if owner_covers(owners.get(d.owner_id), as_of)]
    return {"datasets": len(pop.datasets), "covered": len(cov), "value": p6(ratio(len(cov), len(pop.datasets))),
            "uncovered": sorted(d.dataset_id for d in pop.datasets if d.dataset_id not in set(cov))}


def effective_version(pop: Population, metric_id: str, t: datetime) -> Any | None:
    """The version of a metric in force at ``t``: published or superseded, valid_from not after ``t``, the latest valid_from. A
    published definition is never rewritten: a change adds a version row and the older one stays readable."""
    c = [m for m in pop.metric_versions if m.metric_id == metric_id and m.status in ("published", "superseded") and m.valid_from <= t]
    return max(c, key=lambda m: (m.valid_from, m.version_number)) if c else None


def checklist_gaps(pop: Population, m: Any, items: list[str], owners: set[str]) -> list[str]:
    """The checklist items a metric version fails (definition, grain, source_fields, owner, refresh)."""
    def ok(it: str) -> bool:
        if it == "source_fields":
            return bool(m.source_fields) and all(not is_missing(x, pop.trim) for x in m.source_fields)
        if it == "owner":
            return m.owner_id in owners
        return not is_missing(getattr(m, it, None), pop.trim)
    return [it for it in items if not ok(it)]


def definitions_blocks(pop: Population, as_of: datetime) -> tuple[Row, Row]:
    """(definition_coverage, definitions): coverage under the named checklist version, then the version history facts."""
    cl = next((c for c in pop.checklist_versions if c["checklist_version"] == pop.checklist_version), None)
    items = list(cl["items"]) if cl else []
    owners = {o.owner_id for o in pop.owners}
    by_metric: dict[str, list] = {}
    for m in pop.metric_versions:
        by_metric.setdefault(m.metric_id, []).append(m)
    published, complete, incomplete = 0, 0, {}
    for mid in sorted(by_metric):
        e = effective_version(pop, mid, as_of)
        if e is None or e.status != "published":
            continue
        published += 1
        gaps = checklist_gaps(pop, e, items, owners)
        if gaps:
            incomplete[mid] = gaps
        else:
            complete += 1
    cov = {"checklist_version": pop.checklist_version, "published_metrics": published, "complete_metrics": complete,
           "value": p6(ratio(complete, published)), "incomplete": incomplete}
    probe = pop.probe_definition_at
    chg = {c.metric_version_id: c for c in pop.definition_changes}
    defs = {
        "version_counts": {mid: len(v) for mid, v in sorted(by_metric.items())},
        "change_records": len(pop.definition_changes),
        "versions_without_change_record": sorted(m.metric_version_id for m in pop.metric_versions
                                                 if m.version_number > 1 and m.metric_version_id not in chg),
        "changes_with_mismatched_valid_from": sorted(m.metric_version_id for m in pop.metric_versions
                                                     if m.metric_version_id in chg and chg[m.metric_version_id].changed_at != m.valid_from),
        "effective_at_as_of": {mid: getattr(effective_version(pop, mid, as_of), "metric_version_id", None) for mid in sorted(by_metric)},
        "probe_at": iso_z(probe),
        "effective_at_probe": {mid: (getattr(effective_version(pop, mid, probe), "metric_version_id", None) if probe else None)
                               for mid in sorted(by_metric)}}
    return cov, defs


def lineage_block(pop: Population) -> Row:
    """Declared, observed and inferred edges are kept apart. Coverage = distinct observed pairs that match a declared edge / declared
    edges; repeat observations add nothing; an inferred edge is never part of the observed numerator."""
    pairs = lambda ev: {(e.source_dataset_id, e.target_dataset_id) for e in pop.lineage_edges if e.evidence_type == ev}  # noqa: E731
    fmt = lambda s: [{"source_dataset_id": a, "target_dataset_id": b} for a, b in sorted(s)]  # noqa: E731
    dec, obs, inf = pairs("declared"), pairs("observed"), pairs("inferred")
    return {"declared_edges": len(dec), "observed_rows": sum(1 for e in pop.lineage_edges if e.evidence_type == "observed"),
            "observed_distinct": len(obs), "observed_matching_declared": len(dec & obs), "value": p6(ratio(len(dec & obs), len(dec))),
            "undeclared_observed": fmt(obs - dec), "declared_not_observed": fmt(dec - obs), "inferred_edges": fmt(inf)}
