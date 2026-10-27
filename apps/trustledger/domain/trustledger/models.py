"""Typed records of the twelve entities and the population the metrics are computed over.

``parse`` turns a raw row (a dict, as in inputs.json or a table row) into a frozen record or raises ``DomainError``
(MALFORMED_RECORD). Field kinds: ``id`` non-blank text; ``text`` any text; ``ts`` an instant with a zone; a trailing ``?`` allows
null; ``enum:a|b`` one of the listed values. Unknown keys are ignored (the raw row is kept by ingest for rejections).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any

from .contract import (DECISIONS, EVIDENCE_TYPES, ID_KEYS, ISSUE_STATUSES, METRIC_STATUSES, NON_PORTABLE_ESCAPES, ROLES, RULE_STATUSES,
                       RULE_TYPES, RUN_KINDS, SEVERITIES)
from .errors import MALFORMED_RECORD, PATTERN_NOT_PORTABLE, SCHEDULE_REQUIRED, DomainError
from .timeutil import parse_hhmm, parse_ts, zone

Row = dict[str, Any]
_DEC = re.compile(r"^\d+(\.\d+)?$")


def _malformed(entity: str, name: str, why: str) -> DomainError:
    return DomainError(MALFORMED_RECORD, f"{entity}.{name}: {why}", path=name)


def _conv(entity: str, name: str, kind: str, v: Any) -> Any:
    opt = kind.endswith("?")
    base = kind.rstrip("?")
    if v is None:
        if opt:
            return None
        raise _malformed(entity, name, "is required")
    if base == "id":
        if not isinstance(v, str) or not v.strip() or len(v) > 128:
            raise _malformed(entity, name, "must be a non-blank text of at most 128 characters")
        return v
    if base == "text":
        if not isinstance(v, str):
            raise _malformed(entity, name, "must be text")
        return v
    if base == "bool":
        if not isinstance(v, bool):
            raise _malformed(entity, name, "must be true or false")
        return v
    if base == "int":
        if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 2 ** 31 - 1:
            raise _malformed(entity, name, "must be a non-negative integer")
        return v
    if base == "ts":
        try:
            return parse_ts(v)
        except ValueError as e:
            raise _malformed(entity, name, str(e)) from None
    if base == "ts_list":
        if not isinstance(v, list):
            raise _malformed(entity, name, "must be a list of instants")
        try:
            return tuple(parse_ts(x) for x in v)
        except ValueError as e:
            raise _malformed(entity, name, str(e)) from None
    if base == "strs":
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise _malformed(entity, name, "must be a list of text")
        return tuple(v)
    if base == "dict":
        if not isinstance(v, dict):
            raise _malformed(entity, name, "must be an object")
        return v
    if base == "dec":
        if not isinstance(v, str) or not _DEC.match(v):
            raise _malformed(entity, name, "must be a decimal string")
        return Fraction(v)
    if base.startswith("enum:"):
        if v not in base[5:].split("|"):
            raise _malformed(entity, name, f"must be one of {base[5:].replace('|', ', ')}")
        return v
    raise AssertionError(kind)


def _parse(entity: str, cls: type, spec: tuple[tuple[str, str], ...], row: Any, optional: tuple[str, ...] = ()) -> Any:
    if not isinstance(row, dict):
        raise DomainError(MALFORMED_RECORD, f"{entity} row must be an object")
    kw = {}
    for name, kind in spec:
        if name not in row and name not in optional:
            raise _malformed(entity, name, "is missing")
        if name not in row:                       # an optional key that is absent
            kw[name] = () if kind == "ts_list" else None
            continue
        kw[name] = _conv(entity, name, kind, row[name])
    return cls(**kw)


@dataclass(frozen=True)
class Owner:
    owner_id: str
    owner_name: str
    team: str
    role: str
    active: bool
    deactivated_at: datetime | None


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    dataset_name: str
    source_system: str
    owner_id: str | None
    classification: str | None
    registered_at: datetime
    monitored: bool
    refresh_timezone: str | None
    refresh_local_time: str | None
    refresh_grace_minutes: int | None
    last_refreshed_at: datetime | None


@dataclass(frozen=True)
class Field:
    field_id: str
    dataset_id: str
    field_name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True)
class Rule:
    rule_id: str
    dataset_id: str
    field_id: str | None
    rule_type: str
    severity: str
    version_number: int
    status: str
    disabled_at: datetime | None
    disabled_reason: str | None
    definition: Row = field(compare=False)

    def active_at(self, t: datetime) -> bool:
        """A rule disabled after ``t`` was still active at ``t``; disabling keeps its history (D-01)."""
        return self.status == "active" or (self.disabled_at is not None and self.disabled_at > t)


@dataclass(frozen=True)
class RuleRun:
    rule_run_id: str
    rule_id: str
    rule_version: int
    weight_version: str
    kind: str
    run_at: datetime
    eligible_count: int
    failure_count: int
    rerun_for_issue: str | None


@dataclass(frozen=True)
class Issue:
    issue_id: str
    rule_run_id: str
    owner_id: str
    status: str
    detected_at: datetime
    due_at: datetime | None
    closed_at: datetime | None
    verification_run_id: str | None
    reopened_at: tuple[datetime, ...]


@dataclass(frozen=True)
class Edge:
    edge_id: str
    source_dataset_id: str
    target_dataset_id: str
    evidence_type: str
    observed_at: datetime | None


@dataclass(frozen=True)
class MetricVersion:
    metric_version_id: str
    metric_id: str
    metric_name: str
    version_number: int
    definition: str | None
    grain: str | None
    source_fields: tuple[str, ...] | None
    owner_id: str | None
    refresh: str | None
    valid_from: datetime
    status: str


@dataclass(frozen=True)
class DefinitionChange:
    change_id: str
    metric_version_id: str
    previous_metric_version_id: str | None
    reason: str
    approved_by: str
    changed_at: datetime


@dataclass(frozen=True)
class CustomerRecord:
    record_id: str
    source_system: str
    source_customer_id: str
    normalized_name: str
    address_key: str


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    left_record_id: str
    right_record_id: str
    score: Fraction
    features: Row = field(compare=False)
    explanation: str
    uncertainty: str | None
    proposed_by: str
    proposed_at: datetime


@dataclass(frozen=True)
class Decision:
    merge_id: str
    candidate_id: str
    reviewer_id: str
    decision: str
    decided_at: datetime
    reverses_merge_id: str | None
    reason: str | None


SPECS: dict[str, tuple[type, tuple[tuple[str, str], ...], tuple[str, ...]]] = {
    "owners": (Owner, (("owner_id", "id"), ("owner_name", "text"), ("team", "text"), ("role", "enum:" + "|".join(ROLES)),
                       ("active", "bool"), ("deactivated_at", "ts?")), ()),
    "datasets": (Dataset, (("dataset_id", "id"), ("dataset_name", "text"), ("source_system", "text"), ("owner_id", "text?"),
                           ("classification", "text?"), ("registered_at", "ts"), ("monitored", "bool"),
                           ("refresh_timezone", "text?"), ("refresh_local_time", "text?"), ("refresh_grace_minutes", "int?"),
                           ("last_refreshed_at", "ts?")), ()),
    "fields": (Field, (("field_id", "id"), ("dataset_id", "id"), ("field_name", "id"), ("data_type", "text"), ("nullable", "bool")), ()),
    "quality_rules": (Rule, (("rule_id", "id"), ("dataset_id", "id"), ("field_id", "text?"), ("rule_type", "enum:" + "|".join(RULE_TYPES)),
                             ("severity", "enum:" + "|".join(SEVERITIES)), ("version_number", "int"),
                             ("status", "enum:" + "|".join(RULE_STATUSES)), ("disabled_at", "ts?"), ("disabled_reason", "text?"),
                             ("definition", "dict")), ()),
    "rule_runs": (RuleRun, (("rule_run_id", "id"), ("rule_id", "id"), ("rule_version", "int"), ("weight_version", "id"),
                            ("kind", "enum:" + "|".join(RUN_KINDS)), ("run_at", "ts"), ("eligible_count", "int"),
                            ("failure_count", "int"), ("rerun_for_issue", "text?")), ("rerun_for_issue",)),
    "issues": (Issue, (("issue_id", "id"), ("rule_run_id", "id"), ("owner_id", "id"),
                       ("status", "enum:" + "|".join(ISSUE_STATUSES)), ("detected_at", "ts"), ("due_at", "ts?"),
                       ("closed_at", "ts?"), ("verification_run_id", "text?"), ("reopened_at", "ts_list")),
               ("due_at", "closed_at", "verification_run_id", "reopened_at")),
    "lineage_edges": (Edge, (("edge_id", "id"), ("source_dataset_id", "id"), ("target_dataset_id", "id"),
                             ("evidence_type", "enum:" + "|".join(EVIDENCE_TYPES)), ("observed_at", "ts?")), ("observed_at",)),
    "metric_versions": (MetricVersion, (("metric_version_id", "id"), ("metric_id", "id"), ("metric_name", "text"),
                                        ("version_number", "int"), ("definition", "text?"), ("grain", "text?"),
                                        ("source_fields", "strs?"), ("owner_id", "text?"), ("refresh", "text?"),
                                        ("valid_from", "ts"), ("status", "enum:" + "|".join(METRIC_STATUSES))), ()),
    "definition_changes": (DefinitionChange, (("change_id", "id"), ("metric_version_id", "id"), ("previous_metric_version_id", "text?"),
                                              ("reason", "text"), ("approved_by", "id"), ("changed_at", "ts")), ()),
    "customer_records": (CustomerRecord, (("record_id", "id"), ("source_system", "text"), ("source_customer_id", "text"),
                                          ("normalized_name", "text"), ("address_key", "text")), ()),
    "match_candidates": (Candidate, (("candidate_id", "id"), ("left_record_id", "id"), ("right_record_id", "id"), ("score", "dec"),
                                     ("features", "dict"), ("explanation", "text"), ("uncertainty", "text?"), ("proposed_by", "id"),
                                     ("proposed_at", "ts")), ("uncertainty",)),
    "merge_decisions": (Decision, (("merge_id", "id"), ("candidate_id", "id"), ("reviewer_id", "id"),
                                   ("decision", "enum:" + "|".join(DECISIONS)), ("decided_at", "ts"),
                                   ("reverses_merge_id", "text?"), ("reason", "text?")), ("reverses_merge_id", "reason")),
}


def parse(entity: str, row: Any) -> Any:
    """A raw row to its typed record; DomainError(MALFORMED_RECORD) when it is not well formed."""
    cls, spec, optional = SPECS[entity]
    rec = _parse(entity, cls, spec, row, optional)
    if entity == "issues" and rec.status == "closed" and rec.closed_at is None:
        raise _malformed(entity, "closed_at", "is required when the issue is closed")
    if entity == "datasets":
        _check_schedule(rec)
    if entity == "quality_rules":
        _check_rule(rec)
    if entity == "rule_runs" and rec.failure_count > rec.eligible_count:
        raise _malformed(entity, "failure_count", "cannot exceed eligible_count")
    if entity == "quality_rules" and rec.status == "disabled" and (rec.disabled_at is None or not (rec.disabled_reason or "").strip()):
        raise _malformed(entity, "disabled_reason", "a disabled rule needs disabled_at and a reason")
    if entity == "merge_decisions" and (rec.decision == "reverse") != (rec.reverses_merge_id is not None):
        raise _malformed(entity, "reverses_merge_id", "is required for, and only for, a reversal")
    if entity == "match_candidates":
        if not rec.features:
            raise _malformed(entity, "features", "must name at least one feature")
    return rec


def _check_schedule(d: Dataset) -> None:
    if d.refresh_timezone is not None or d.refresh_local_time is not None or d.refresh_grace_minutes is not None or d.monitored:
        ok = d.refresh_timezone is not None and d.refresh_local_time is not None and d.refresh_grace_minutes is not None
        if d.monitored and not ok:
            raise DomainError(SCHEDULE_REQUIRED, "a monitored dataset needs refresh_timezone, refresh_local_time and refresh_grace_minutes",
                              path="refresh_timezone")
        if ok:
            try:
                zone(d.refresh_timezone)  # type: ignore[arg-type]
                parse_hhmm(d.refresh_local_time)  # type: ignore[arg-type]
            except ValueError as e:
                raise _malformed("datasets", "refresh_timezone", str(e)) from None
            if not 0 <= d.refresh_grace_minutes <= 1439:  # type: ignore[operator]
                raise _malformed("datasets", "refresh_grace_minutes", "must be 0..1439")


def pattern_portable(pattern: str) -> bool:
    """A pattern is portable only if it avoids ``\\s \\d \\w \\b`` (and their negations): Python ``re``, JavaScript and PostgreSQL disagree on
    what they match (Unicode or ASCII classes, a boundary or a backspace). Use explicit classes: ``[ \\t\\r\\n\\f\\v]``, ``[0-9]``. An escaped
    backslash followed by a letter (``\\\\s``) is a literal backslash and a letter, and passes (D-10, R7-04)."""
    i = 0
    while i < len(pattern):
        if pattern[i] == "\\":
            if i + 1 < len(pattern) and pattern[i + 1] in NON_PORTABLE_ESCAPES:
                return False
            i += 2
        else:
            i += 1
    return True


def _check_rule(r: Rule) -> None:
    d = r.definition
    t = r.rule_type
    if t != "timeliness" and not (isinstance(d.get("field"), str) and d["field"]):
        raise _malformed("quality_rules", "definition.field", "is required")
    if t == "validity" and (r.status == "active" or "pattern" in d):      # a disabled rule keeps its history even without a pattern
        if isinstance(d.get("pattern"), str) and not pattern_portable(d["pattern"]):
            raise DomainError(PATTERN_NOT_PORTABLE, "a pattern may not use \\s, \\d, \\w or \\b (they differ between Python, JavaScript and PostgreSQL): "
                              "use explicit classes such as [ \\t\\r\\n\\f\\v] and [0-9]", path="definition.pattern")
        try:
            re.compile(d.get("pattern", ""))
        except (re.error, TypeError):
            raise _malformed("quality_rules", "definition.pattern", "must be a valid regular expression") from None
        if not isinstance(d.get("pattern"), str) or not d["pattern"]:
            raise _malformed("quality_rules", "definition.pattern", "is required")
    f = d.get("filter")
    if f is not None and not (isinstance(f, dict) and isinstance(f.get("field"), str) and f["field"] and isinstance(f.get("equals"), str)):
        raise _malformed("quality_rules", "definition.filter", "must be {field, equals} with text values")
    if t == "relationship" and not all(isinstance(d.get(k), str) and d[k] for k in ("parent_dataset_id", "parent_field")):
        raise _malformed("quality_rules", "definition.parent_dataset_id", "parent_dataset_id and parent_field are required")


@dataclass(frozen=True)
class WeightVersion:
    weight_version: str
    valid_from: datetime
    weights: dict[str, Fraction]


@dataclass
class Population:
    """Everything the metrics read: the accepted records, the dataset rows and the configuration."""
    owners: list[Owner] = field(default_factory=list)
    datasets: list[Dataset] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    quality_rules: list[Rule] = field(default_factory=list)
    rule_runs: list[RuleRun] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    lineage_edges: list[Edge] = field(default_factory=list)
    metric_versions: list[MetricVersion] = field(default_factory=list)
    definition_changes: list[DefinitionChange] = field(default_factory=list)
    customer_records: list[CustomerRecord] = field(default_factory=list)
    match_candidates: list[Candidate] = field(default_factory=list)
    merge_decisions: list[Decision] = field(default_factory=list)
    dataset_rows: dict[str, list[Row]] = field(default_factory=dict)
    weight_versions: list[WeightVersion] = field(default_factory=list)
    checklist_versions: list[dict[str, Any]] = field(default_factory=list)
    checklist_version: str = "cl-1"
    trim: str = " \t\r\n"
    probe_definition_at: datetime | None = None
    probe_timeliness: list[dict[str, Any]] = field(default_factory=list)   # D-10 R7-01: stated cases, judged by the timeliness rule alone
    weight_version: str | None = None

    def total(self) -> int:
        from .contract import ENTITIES
        return sum(len(getattr(self, e)) for e in ENTITIES) + sum(len(v) for v in self.dataset_rows.values())


def weight_in_force(pop: Population, as_of: datetime) -> str | None:
    """The weight version in force at ``as_of``: the latest ``valid_from`` not after it (D-01)."""
    live = [w for w in pop.weight_versions if w.valid_from <= as_of]
    return max(live, key=lambda w: (w.valid_from, w.weight_version)).weight_version if live else None


def id_of(entity: str, rec: Any) -> str:
    return getattr(rec, ID_KEYS[entity])
