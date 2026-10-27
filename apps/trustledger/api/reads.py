"""Read side: GET /data/{entity}, GET /data/comparable_runs, GET /data/identity_map and GET /metrics (docs/api-contract.md, D-05, D-06).

* Entity reads are ordered by the entity's key (code-point order) and paged with an opaque cursor (base64 of the last key), so pages
  are stable with no duplicates or gaps. ``from``/``to`` filter the entity's time field on the half-open window ``[from, to)``; other
  filters are equality on a whitelist of columns per entity (unknown filter: 422 INVALID_FILTER). No actor is needed. Rows of issues also
  carry the derived ``class`` (open | claimed | resolved), ``resolved_at`` and ``reopen_cycles``; lineage edges carry ``evidence_type``
  (an inferred edge is never presented as observed).
* GET /metrics runs the domain over the tables at ``as_of`` (default: the server's now): the twelve metrics under ``metrics`` for the
  ``weight_version`` named (default: the one in force at ``as_of``), narrowed by ``dataset_id``. ``from``/``to`` (half-open) narrow the
  time-stamped facts (issues by detected_at, observed lineage, candidates, merge decisions). ``group_by`` is none, dataset, owner,
  source_system or severity; each group carries the metrics computed over its own part of the portfolio (definition coverage and match
  precision are portfolio-wide and appear only at the top).
* GET /data/comparable_runs lists, per rule, its runs and the comparison of each scheduled run with the one before it: comparable only
  under the same rule version, otherwise RULE_VERSION_DIFFERS and no rate is compared.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import psycopg
from trustledger import CONTRACT_VERSION, DomainError
from trustledger.contract import GROUPS, SEVERITIES
from trustledger.issues import classify
from trustledger.matching import matching_block
from trustledger.metrics import at, compare_runs, compute, restrict
from trustledger.models import parse
from trustledger.numbers import p6, ratio
from trustledger.timeutil import iso_z, parse_ts

from . import clock, db
from .errors import ApiError, detail, from_domain

Conn = psycopg.Connection[db.Row]
RESERVED = frozenset({"limit", "cursor", "from", "to"})
GROUP_METRICS = ("completeness", "validity", "uniqueness", "relationship_integrity", "timeliness", "weighted_score", "critical_failures",
                 "resolution_time", "ownership_coverage", "lineage_coverage")


@dataclass(frozen=True)
class EntitySpec:
    table: str
    key: tuple[str, ...]
    time_field: str | None = None
    filters: tuple[str, ...] = field(default_factory=tuple)
    columns: str = "*"


ENTITIES: dict[str, EntitySpec] = {s.table: s for s in (
    EntitySpec("owners", ("owner_id",), "deactivated_at", ("role", "active", "team")),
    EntitySpec("datasets", ("dataset_id",), "registered_at", ("owner_id", "source_system", "classification", "monitored")),
    EntitySpec("fields", ("field_id",), None, ("dataset_id",)),
    EntitySpec("dataset_rows", ("dataset_id", "ordinal"), "recorded_at", ("dataset_id", "row_id", "row_version", "corrected_by")),
    EntitySpec("dataset_refreshes", ("dataset_id", "refreshed_at"), "refreshed_at", ("dataset_id", "recorded_by")),
    EntitySpec("quality_rule_versions", ("rule_id", "version_number"), "valid_from", ("rule_id", "rule_type", "severity", "version_number")),
    EntitySpec("quality_rules", ("rule_id",), "disabled_at", ("dataset_id", "rule_type", "severity", "status")),
    EntitySpec("rule_weight_versions", ("weight_version",), "valid_from"),
    EntitySpec("checklist_versions", ("checklist_version",), None),
    EntitySpec("rule_runs", ("rule_run_id",), "run_at", ("rule_id", "kind", "weight_version", "rule_version", "rerun_for_issue")),
    EntitySpec("issues", ("issue_id",), "detected_at", ("status", "severity", "owner_id", "rule_run_id")),
    EntitySpec("issue_events", ("event_id",), "occurred_at", ("issue_id", "event_type")),
    EntitySpec("lineage_edges", ("edge_id",), "observed_at", ("evidence_type", "source_dataset_id", "target_dataset_id")),
    EntitySpec("metric_versions", ("metric_version_id",), "valid_from", ("metric_id", "status", "owner_id")),
    EntitySpec("definition_changes", ("change_id",), "changed_at", ("metric_version_id", "approved_by")),
    EntitySpec("customer_records", ("record_id",), None, ("source_system",)),
    EntitySpec("match_candidates", ("candidate_id",), "proposed_at", ("proposed_by", "left_record_id", "right_record_id")),
    EntitySpec("merge_decisions", ("merge_id",), "decided_at", ("candidate_id", "decision", "reviewer_id")),
    EntitySpec("rejected_records", ("batch_id", "entity", "id", "reason_code", "ordinal"), "created_at", ("entity", "reason_code")),
    EntitySpec("audit_events", ("event_id",), "occurred_at", ("entity_type", "entity_id", "action", "actor_id")),
    EntitySpec("dataset_versions", ("dataset_version",), "created_at"),
)}

_BOOL_COLUMNS = frozenset({"active", "monitored"})
_INT_COLUMNS = frozenset({"rule_version", "ordinal", "version_number", "row_version", "refreshed_at"})      # ordered as they are (no text collation)


def parse_instant(value: str, name: str) -> datetime:
    """``YYYY-MM-DDTHH:MM:SS[.f]`` with ``Z`` or an offset, as the commands require. A value with no zone (a date, or a time without ``Z`` or an
    offset) is refused, not read as UTC (D-10 R7-14)."""
    try:
        return parse_ts(value)
    except ValueError:
        raise ApiError(422, "VALIDATION_FAILED", f"{name} must be an ISO-8601 timestamp with seconds and a zone (Z or +hh:mm)",
                       [detail(name, "TIMESTAMP_INVALID", f"{name} must be YYYY-MM-DDTHH:MM:SSZ or carry an offset; a value with no zone is refused")]) from None


def parse_window(lo: str | None, hi: str | None) -> tuple[datetime | None, datetime | None]:
    window = (parse_instant(lo, "from") if lo else None, parse_instant(hi, "to") if hi else None)
    if window[0] is not None and window[1] is not None and window[0] >= window[1]:
        raise ApiError(422, "VALIDATION_FAILED", "from must be before to (the window is half-open)", [detail("from", "INVALID_WINDOW", "from must be before to")])
    return window


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps([db.jsonable(v) for v in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, width: int) -> list[Any]:
    bad = ApiError(422, "VALIDATION_FAILED", "cursor is not valid", [detail("cursor", "INVALID_CURSOR", "cursor must come from a previous next_cursor")])
    try:
        vals = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError):
        raise bad from None
    if not (isinstance(vals, list) and len(vals) == width and all(isinstance(v, (str, int)) for v in vals)):
        raise bad
    return vals


def meta(conn: Conn, applied: dict[str, Any], total: int, next_cursor: str | None, exclusions: dict[str, Any]) -> dict[str, Any]:
    return {"dataset_version": db.current_dataset_version(conn), "code_sha": os.environ.get("CODE_SHA", "dev"), "contract_version": CONTRACT_VERSION,
            "generated_at": iso_z(clock.now()), "applied_filters": applied, "total_count": total, "next_cursor": next_cursor, "exclusions": exclusions}


def _counts(conn: Conn) -> dict[str, int]:
    return {"rejected_records": conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"]}


def read_entity(entity: str, limit: int, cursor: str | None, lo: str | None, hi: str | None, filters: dict[str, str]) -> dict[str, Any]:
    spec = ENTITIES.get(entity)
    if spec is None:
        raise ApiError(404, "NOT_FOUND", f"unknown entity {entity!r}", [detail("entity", "ENTITY_UNKNOWN", f"known: {', '.join(sorted(ENTITIES))}")])
    for name in filters:
        if name not in spec.filters:
            raise ApiError(422, "VALIDATION_FAILED", f"{entity} cannot be filtered by {name!r}",
                           [detail(name, "INVALID_FILTER", f"allowed: {', '.join(spec.filters) or 'none'}")])
    window = parse_window(lo, hi)
    if (lo or hi) and spec.time_field is None:
        raise ApiError(422, "VALIDATION_FAILED", f"{entity} has no time field to filter on",
                       [detail("from" if lo else "to", "FILTER_NOT_SUPPORTED", f"{entity} cannot be filtered by time")])
    where: list[str] = []
    params: list[Any] = []       # table and column names come from the ENTITIES constants, never from the request
    if spec.time_field and window[0] is not None:
        where.append(f"{spec.time_field} >= %s")
        params.append(window[0])
    if spec.time_field and window[1] is not None:
        where.append(f"{spec.time_field} < %s")
        params.append(window[1])
    for name, value in sorted(filters.items()):
        if name in _BOOL_COLUMNS:
            if value not in ("true", "false"):
                raise ApiError(422, "VALIDATION_FAILED", f"{name} must be true or false", [detail(name, "INVALID_FILTER", f"{name} must be true or false")])
            where.append(f"{name} = %s")
            params.append(value == "true")
        else:
            where.append(f"{name} = %s")
            params.append(value)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order = ", ".join(f'{k} COLLATE "C"' if k not in _INT_COLUMNS else k for k in spec.key)
    page_where, page_params = where_sql, list(params)
    if cursor:
        after = decode_cursor(cursor, len(spec.key))
        marks = ", ".join(["%s"] * len(spec.key))
        page_where += (" AND " if where else " WHERE ") + f"({order}) > ({marks})"
        page_params += after
    with db.transaction() as conn:
        try:
            total = conn.execute(f"SELECT count(*) AS n FROM {spec.table}{where_sql}", params).fetchone()["n"]
            rows = conn.execute(f"SELECT {spec.columns} FROM {spec.table}{page_where} ORDER BY {order} LIMIT %s", page_params + [limit + 1]).fetchall()
        except psycopg.errors.DataError:
            raise ApiError(422, "VALIDATION_FAILED", "a filter or the cursor is not valid for this entity",
                           [detail("cursor", "INVALID_CURSOR", "the value does not match this entity")]) from None
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor([rows[-1][k] for k in spec.key]) if more else None
        data = [db.jsonable_row(r) for r in rows]
        if entity == "issues" and rows:
            now = clock.now()
            views = {v.issue.issue_id: v for v in classify(at(db.load_population(conn), now), now)}
            for r, d in zip(rows, data):
                v = views.get(r["issue_id"])
                d.update({"class": v.cls if v else None, "resolved_at": iso_z(v.resolved_at) if v else None, "reopen_cycles": v.cycles if v else 0})
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "limit": limit, **filters}
        return {"data": data, "meta": meta(conn, applied, total, next_cursor, _counts(conn)), "warnings": []}


def read_comparable_runs(rule_id: str | None) -> dict[str, Any]:
    """Per rule: its runs and, for each scheduled run, the comparison with the scheduled run before it (D-01, P07-TEST-12)."""
    with db.transaction() as conn:
        rules = conn.execute("SELECT rule_id, version_number, status FROM quality_rules WHERE (%s::text IS NULL OR rule_id = %s) ORDER BY rule_id COLLATE \"C\"",
                             (rule_id, rule_id)).fetchall()
        if rule_id and not rules:
            raise ApiError(404, "NOT_FOUND", "rule not found", [detail("rule_id", "RULE_UNKNOWN", "rule not found")])
        data = []
        for r in rules:
            runs = [parse("rule_runs", x) for x in conn.execute(
                "SELECT rule_run_id, rule_id, rule_version, weight_version, kind, run_at, eligible_count, failure_count, rerun_for_issue FROM rule_runs "
                "WHERE rule_id = %s ORDER BY run_at, rule_run_id", (r["rule_id"],)).fetchall()]
            sched = [x for x in runs if x.kind == "scheduled"]
            comps = [{**compare_runs(a, b), "current_run_id": b.rule_run_id, "previous_run_at": iso_z(a.run_at), "current_run_at": iso_z(b.run_at)}
                     for a, b in zip(sched, sched[1:])]
            data.append({"rule_id": r["rule_id"], "status": r["status"], "current_rule_version": r["version_number"],
                         "runs": [{"rule_run_id": x.rule_run_id, "kind": x.kind, "run_at": iso_z(x.run_at), "rule_version": x.rule_version,
                                   "weight_version": x.weight_version, "eligible_count": x.eligible_count, "failure_count": x.failure_count,
                                   "failure_rate": p6(ratio(x.failure_count, x.eligible_count))} for x in runs],
                         "comparisons": comps, "comparable_pairs": sum(1 for c in comps if c["comparable"]),
                         "not_comparable_pairs": sum(1 for c in comps if not c["comparable"])})
        return {"data": data, "meta": meta(conn, {"rule_id": rule_id}, len(data), None, _counts(conn)), "warnings": []}


def read_identity_map(as_of: str | None) -> dict[str, Any]:
    """Which record each source record maps to now, with the mapping history (a reversal restores both identities, the history stays)."""
    when = parse_instant(as_of, "as_of") if as_of else clock.now()
    with db.transaction() as conn:
        block, _, _ = matching_block(at(db.load_population(conn, when), when))
        return {"data": block, "meta": meta(conn, {"as_of": iso_z(when)}, block["candidates"], None, _counts(conn)), "warnings": []}


def read_metrics(lo: str | None, hi: str | None, as_of: str | None, dataset_id: str | None, weight_version: str | None, group_by: str) -> dict[str, Any]:
    if group_by not in GROUPS:
        raise ApiError(422, "VALIDATION_FAILED", "unsupported group_by", [detail("group_by", "INVALID_GROUP_BY", f"use one of {', '.join(GROUPS)}")])
    window = parse_window(lo, hi)
    when = parse_instant(as_of, "as_of") if as_of else clock.now()
    with db.transaction() as conn:
        pop = db.load_population(conn, when)
        truth = db.load_truth(conn)
        if dataset_id is not None and dataset_id not in {d.dataset_id for d in pop.datasets}:
            raise ApiError(404, "NOT_FOUND", "dataset not found", [detail("dataset_id", "DATASET_UNKNOWN", "dataset not found")])
        if weight_version is not None and weight_version not in {w.weight_version for w in pop.weight_versions}:
            raise ApiError(422, "VALIDATION_FAILED", f"unknown weight version {weight_version!r}",
                           [detail("weight_version", "UNKNOWN_WEIGHT_VERSION", "name a weight version from /data/rule_weight_versions")])
        empty = pop.total() == 0
        scope = restrict(pop, {dataset_id}) if dataset_id else pop
        try:
            comp = compute(scope, when, weight_version, window, truth, empty)
        except DomainError as err:
            raise from_domain(err, "from") from None
        warnings = list(comp.warnings)
        data: dict[str, Any] = {"as_of": iso_z(when), "weight_version": comp.weight_version, "window": {"from": iso_z(window[0]), "to": iso_z(window[1])},
                                "group_by": group_by, "dataset_id": dataset_id, "metrics": comp.metrics, "rules": comp.rules,
                                "definitions": comp.definitions, "matching": comp.matching, "empty_population": comp.empty_population}
        if dataset_id:
            warnings.append({"code": "PORTFOLIO_WIDE_METRICS", "path": "metrics.definition_coverage",
                             "message": "definition coverage and match precision are portfolio-wide and are not narrowed by dataset_id"})
        if group_by != "none":
            ds = scope.datasets
            members: dict[str, tuple[set[str] | None, set[str] | None]] = {}
            if group_by == "dataset":
                members = {d.dataset_id: ({d.dataset_id}, None) for d in ds}
            elif group_by == "owner":
                for d in ds:
                    members.setdefault(d.owner_id or "", (set(), None))[0].add(d.dataset_id)      # type: ignore[union-attr]
            elif group_by == "source_system":
                for d in ds:
                    members.setdefault(d.source_system, (set(), None))[0].add(d.dataset_id)        # type: ignore[union-attr]
            else:
                present = {r.severity for r in scope.quality_rules}
                members = {s: ({d.dataset_id for d in ds}, {s}) for s in SEVERITIES if s in present}
            groups = {}
            for value in sorted(members):
                ids, sev = members[value]
                sub = restrict(scope, ids, sev)
                try:
                    c = compute(sub, when, weight_version, window, truth, empty)
                except DomainError as err:
                    raise from_domain(err, "from") from None
                groups[value] = {"datasets": len(sub.datasets), "rules": c.rules["active_count"], "metrics": {k: c.metrics[k] for k in GROUP_METRICS}}
            data["groups"] = groups
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "as_of": iso_z(when), "dataset_id": dataset_id,
                   "weight_version": comp.weight_version, "group_by": group_by}
        return {"data": data, "meta": meta(conn, applied, len(scope.datasets), None, _counts(conn)), "warnings": warnings}
