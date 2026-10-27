"""Read side: GET /data/{entity} and GET /metrics (docs/api-contract.md, D-04, D-05).

* Entity reads are ordered by the entity's key (code-point order) and paged with an opaque cursor (base64 of the last key), so pages are stable with no
  duplicates or gaps. ``from``/``to`` filter the entity's time field on the half-open window ``[from, to)`` (from inclusive, to exclusive; reversed or
  invalid is 422); other filters are equality on a whitelist of columns per entity (unknown filter: 422 INVALID_FILTER). No actor is needed. Amounts
  are decimal strings (2 places or more), proportions 6 places, instants UTC with Z.
* GET /metrics runs the domain over the tables at ``as_of`` (default: the server's now): the full ``metrics`` tree in the nesting of expected.json, the
  ``ingest`` counts and rejected records, narrowed by ``scenario_id``. ``from``/``to`` (half-open, ISO date or instant) narrow the observations and the
  matured periods of the observed measures; the dated model (cash flow, NPV, paybacks, capacity, risk, roadmap, double count) is not windowed.
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
from changeworks import CONTRACT_VERSION, compute
from changeworks.contract import ENTITIES
from changeworks.timeutil import iso_z

from . import clock, db
from .errors import ApiError, detail

Conn = psycopg.Connection[db.Row]
RESERVED = frozenset({"limit", "cursor", "from", "to"})


@dataclass(frozen=True)
class EntitySpec:
    table: str
    key: tuple[str, ...]
    columns: str
    time_field: str | None = None
    filters: tuple[str, ...] = field(default_factory=tuple)


_TIME = {"initiatives": "created_at", "process_baselines": "measured_at", "assumption_versions": "created_at", "scenario_versions": "created_at",
         "readiness_assessments": "assessed_at", "adoption_observations": "observed_at", "training_completions": "recorded_at",
         "benefit_observations": "observed_at", "forecast_versions": "created_at"}
_FILTERS = {
    "initiatives": ("status", "sponsor_id", "baseline_version"), "process_baselines": ("initiative_id", "baseline_version"),
    "assumption_versions": ("initiative_id", "name", "version_number"), "resources": ("unit",), "scenario_versions": ("status", "baseline_version", "rate_basis"),
    "cost_items": ("initiative_id", "cost_type", "cost_basis"), "benefit_items": ("initiative_id", "benefit_type", "period_index"),
    "dependencies": ("initiative_id", "prerequisite_id", "dependency_type"), "stakeholder_groups": ("impact_level", "owner_id"),
    "impact_mappings": ("initiative_id", "group_id", "impact_level"), "resource_allocations": ("resource_id", "initiative_id", "period_index"),
    "readiness_assessments": ("group_id", "dimension"), "adoption_observations": ("initiative_id",), "training_completions": ("initiative_id",),
    "benefit_observations": ("benefit_id",), "risk_items": ("initiative_id",), "forecast_versions": ("initiative_id", "version_number"),
}
_INT_COLUMNS = frozenset({"version_number", "period_index"})

ENTITY_SPECS: dict[str, EntitySpec] = {}
for _e in ENTITIES:
    _table, _cols, _extra, _key = db.SPECS[_e]
    ENTITY_SPECS[_e] = EntitySpec(_table, _key, _cols + (", " + _extra if _extra else ""), _TIME.get(_e), _FILTERS.get(_e, ()))
ENTITY_SPECS.update({
    "baseline_approvals": EntitySpec("baseline_approvals", ("approval_id",), "approval_id, initiative_id, baseline_version, approved_by, cw_iso(approved_at) AS approved_at, reason",
                                     "approved_at", ("initiative_id",)),
    "opportunity_scores": EntitySpec("opportunity_scores", ("score_id",), "score_id, initiative_id, version_number, criteria, cw_dec(weighted_score) AS weighted_score, weighted_exact, "
                                     "rationale, author_id, cw_iso(created_at) AS created_at", "created_at", ("initiative_id",)),
    "expanded_costs": EntitySpec("expanded_costs", ("scenario_id", "cost_id", "period_index"), "scenario_id, cost_id, initiative_id, period_index, cw_dec(amount) AS amount", None,
                                 ("scenario_id", "initiative_id", "cost_id")),
    "rejected_records": EntitySpec("rejected_records", ("seq",), "seq, batch_id, entity, id, reason_code, details, raw_row, cw_iso(created_at) AS created_at", "created_at",
                                   ("entity", "reason_code")),
    "audit_events": EntitySpec("audit_events", ("event_id",), "event_id, entity_type, entity_id, action, actor_id, actor_role, cw_iso(occurred_at) AS occurred_at, before_version, "
                               "after_version, reason, request_id, details", "occurred_at", ("entity_type", "entity_id", "action", "actor_id")),
    "dataset_versions": EntitySpec("dataset_versions", ("dataset_version",), "dataset_version, dataset_hash, contract_version, cw_iso(as_of) AS as_of, cw_iso(created_at) AS created_at",
                                   "created_at"),
})
_INT_COLUMNS = _INT_COLUMNS | {"seq"}


def parse_instant(value: str, name: str) -> datetime:
    """ISO date or datetime; a missing zone means UTC."""
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "VALIDATION_FAILED", f"{name} is not an ISO-8601 date or datetime", [detail(name, "INVALID_FILTER", f"{name} must be ISO-8601")]) from None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


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
    if not (isinstance(vals, list) and len(vals) == width and all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in vals)):
        raise bad
    return vals


def meta(conn: Conn, applied: dict[str, Any], total: int, next_cursor: str | None, exclusions: dict[str, Any]) -> dict[str, Any]:
    return {"dataset_version": db.current_dataset_version(conn), "code_sha": os.environ.get("CODE_SHA", "dev"), "contract_version": CONTRACT_VERSION,
            "generated_at": iso_z(clock.now()), "applied_filters": applied, "total_count": total, "next_cursor": next_cursor, "exclusions": exclusions}


def _exclusions(conn: Conn) -> dict[str, Any]:
    return {"rejected_records": conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"]}


def read_entity(entity: str, limit: int, cursor: str | None, lo: str | None, hi: str | None, filters: dict[str, str]) -> dict[str, Any]:
    spec = ENTITY_SPECS.get(entity)
    if spec is None:
        raise ApiError(404, "NOT_FOUND", f"unknown entity {entity!r}", [detail("entity", "ENTITY_UNKNOWN", f"known: {', '.join(sorted(ENTITY_SPECS))}")])
    for name in filters:
        if name not in spec.filters:
            raise ApiError(422, "VALIDATION_FAILED", f"{entity} cannot be filtered by {name!r}", [detail(name, "INVALID_FILTER", f"allowed: {', '.join(spec.filters) or 'none'}")])
    window = parse_window(lo, hi)
    if (lo or hi) and spec.time_field is None:
        raise ApiError(422, "VALIDATION_FAILED", f"{entity} has no time field to filter on",
                       [detail("from" if lo else "to", "FILTER_NOT_SUPPORTED", f"{entity} cannot be filtered by time")])
    where: list[str] = []
    params: list[Any] = []       # table and column names come from the constants above, never from the request
    if spec.time_field and window[0] is not None:
        where.append(f"{spec.time_field} >= %s")
        params.append(window[0])
    if spec.time_field and window[1] is not None:
        where.append(f"{spec.time_field} < %s")
        params.append(window[1])
    for name, value in sorted(filters.items()):
        if name in _INT_COLUMNS:
            try:
                params.append(int(value))
            except ValueError:
                raise ApiError(422, "VALIDATION_FAILED", f"{name} must be an integer", [detail(name, "INVALID_FILTER", f"{name} must be an integer")]) from None
        else:
            params.append(value)
        where.append(f"{spec.table}.{name} = %s")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order = ", ".join(f'{spec.table}.{k} COLLATE "C"' if k not in _INT_COLUMNS else f"{spec.table}.{k}" for k in spec.key)
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
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "limit": limit, **filters}
        return {"data": [db.jsonable_row(r) for r in rows], "meta": meta(conn, applied, total, next_cursor, _exclusions(conn)), "warnings": []}


def read_metrics(scenario_id: str | None, lo: str | None, hi: str | None, as_of: str | None) -> dict[str, Any]:
    window = parse_window(lo, hi)
    when = parse_instant(as_of, "as_of") if as_of else clock.now()
    with db.transaction() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")          # one snapshot for the tables, the counts and the rejections
        pop = db.load_population(conn)
        if scenario_id is not None and scenario_id not in {s["scenario_id"] for s in pop.acc["scenario_versions"]}:
            raise ApiError(404, "NOT_FOUND", "scenario not found", [detail("scenario_id", "UNKNOWN_SCENARIO", "scenario not found")])
        metrics, warnings = compute(pop, when, window, [scenario_id] if scenario_id else None)
        rejected = conn.execute("SELECT entity, id, reason_code, details, raw_row FROM rejected_records ORDER BY seq").fetchall()
        records = []
        for r in rejected:
            item: dict[str, Any] = {"entity": r["entity"], "id": r["id"], "status": "rejected", "reason_code": r["reason_code"]}
            if r["details"]:
                item["details"] = r["details"]
            item["raw_row"] = r["raw_row"]
            records.append(item)
        counts = {e: {"accepted": len(pop.acc[e]), "rejected": sum(1 for r in records if r["entity"] == e)} for e in ENTITIES}
        data = {"as_of": iso_z(when), "window": {"from": iso_z(window[0]), "to": iso_z(window[1])}, "scenario_id": scenario_id,
                "period_basis": pop.config["period_basis"], "period_start": pop.config["period_start"], "empty_population": not pop.acc["initiatives"],
                "ingest": {"counts": counts, "rejected_records": records}, "metrics": metrics}
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "as_of": iso_z(when), "scenario_id": scenario_id}
        return {"data": data, "meta": meta(conn, applied, len(metrics["scenarios"]), None, {"rejected_records": len(records)}), "warnings": warnings}
