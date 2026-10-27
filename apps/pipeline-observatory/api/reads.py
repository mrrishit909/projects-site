"""Read side: GET /data/{entity} and GET /metrics (docs/api-contract.md, D-04, D-05).

* Entity reads are ordered by the entity's key (code-point order) and paged with an opaque cursor (base64 of the last key), so pages are stable
  with no duplicates or gaps. ``from``/``to`` filter the entity's time field on the half-open window ``[from, to)``; other filters are equality
  on a whitelist of columns per entity (unknown filter: 422 INVALID_FILTER). No actor is needed.
* GET /metrics runs the domain over the tables: the eleven metric families of D-P8-07 under ``metrics`` in the nesting of expected.json, with the
  import counts and the rejected records under ``ingest``. ``from``/``to`` (half-open) narrow the facts on the primary instant of each entity
  (batches and runs: started_at; publications: published_at; incidents: opened_at; backfills: start_at; expectations: the partition day);
  ``cutoff`` (default: the server's now) is the instant freshness and ingestion age are measured at and drops facts not yet known at it;
  ``source_id`` narrows to one source; ``group_by`` is none or source (each source's ingestion, freshness and completeness side by side).
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
from pipeline_observatory import CONTRACT_VERSION, DomainError
from pipeline_observatory.classify import money_amount
from pipeline_observatory.metrics import compute
from pipeline_observatory.scope import restrict, restrict_expectations
from pipeline_observatory.timeutil import iso_z

from . import clock, db
from .errors import ApiError, detail, from_domain

Conn = db.Conn
RESERVED = frozenset({"limit", "cursor", "from", "to"})
GROUPS = ("none", "source")


@dataclass(frozen=True)
class EntitySpec:
    table: str
    key: tuple[str, ...]
    time_field: str | None = None
    filters: tuple[str, ...] = field(default_factory=tuple)
    columns: str = "*"


ENTITIES: dict[str, EntitySpec] = {s.table: s for s in (
    EntitySpec("source_contracts", ("source_id",), None, ("owner_id", "expected_frequency")),
    EntitySpec("source_expectations", ("source_id", "partition"), None, ("source_id",)),
    EntitySpec("ingestion_batches", ("batch_id",), "started_at", ("source_id", "status")),
    EntitySpec("raw_records", ("raw_record_id",), None, ("batch_id", "source_key", "disposition")),
    EntitySpec("accepted_records", ("source_id", "source_key"), "accepted_at", ("source_id", "batch_id")),
    EntitySpec("quarantine_records", ("quarantine_id",), None, ("batch_id", "reason_code", "source_key")),
    EntitySpec("checkpoints", ("checkpoint_id",), "committed_at", ("source_id", "batch_id")),
    EntitySpec("model_definitions", ("model_id",), None, ("model_name",)),
    EntitySpec("pipeline_runs", ("run_id",), "started_at", ("status", "backfill_id")),
    EntitySpec("task_runs", ("task_run_id",), None, ("run_id", "task_name", "status")),
    EntitySpec("quality_results", ("quality_result_id",), None, ("task_run_id", "rule_name", "severity")),
    EntitySpec("publications", ("publication_id",), "published_at", ("run_id", "dataset_name")),
    EntitySpec("publication_pointer", ("id",), "updated_at", ()),
    EntitySpec("incidents", ("incident_id",), "opened_at", ("status", "run_id", "severity")),
    EntitySpec("backfill_requests", ("backfill_id",), "start_at", ("source_id", "status")),
    EntitySpec("model_outputs", ("output_id",), None, ("run_id", "source_id", "record_key")),
    EntitySpec("processing_measurements", ("measurement_id",), "recorded_at", ("source_id", "batch_id")),
    EntitySpec("fetch_log", ("fetch_id",), "fetched_at", ("source_id", "status", "session_id")),
    EntitySpec("fault_injections", ("fault_id",), "injected_at", ("fault_type", "target_id")),
    EntitySpec("evidence_archives", ("archive_id",), "created_at", ("run_id",)),
    EntitySpec("rejected_records", ("batch_id", "entity", "id", "reason_code", "ordinal"), "created_at", ("entity", "reason_code")),
    EntitySpec("audit_events", ("event_id",), "occurred_at", ("entity_type", "entity_id", "action", "actor_id")),
    EntitySpec("dataset_versions", ("dataset_version",), "created_at"),
)}
_INT_COLUMNS = frozenset({"ordinal", "output_id", "fetch_id", "measurement_id", "id"})


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


def _counts(conn: Conn) -> dict[str, int]:
    return {"rejected_records": conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"]}


def read_entity(entity: str, limit: int, cursor: str | None, lo: str | None, hi: str | None, filters: dict[str, str]) -> dict[str, Any]:
    spec = ENTITIES.get(entity)
    if spec is None:
        raise ApiError(404, "NOT_FOUND", f"unknown entity {entity!r}", [detail("entity", "ENTITY_UNKNOWN", f"known: {', '.join(sorted(ENTITIES))}")])
    for name in filters:
        if name not in spec.filters:
            raise ApiError(422, "VALIDATION_FAILED", f"{entity} cannot be filtered by {name!r}", [detail(name, "INVALID_FILTER", f"allowed: {', '.join(spec.filters) or 'none'}")])
    window = parse_window(lo, hi)
    if (lo or hi) and spec.time_field is None:
        raise ApiError(422, "VALIDATION_FAILED", f"{entity} has no time field to filter on", [detail("from" if lo else "to", "FILTER_NOT_SUPPORTED", f"{entity} cannot be filtered by time")])
    where: list[str] = []
    params: list[Any] = []       # table and column names come from the ENTITIES constants, never from the request
    if spec.time_field and window[0] is not None:
        where.append(f"{spec.time_field} >= %s")
        params.append(window[0])
    if spec.time_field and window[1] is not None:
        where.append(f"{spec.time_field} < %s")
        params.append(window[1])
    for name, value in sorted(filters.items()):
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
            raise ApiError(422, "VALIDATION_FAILED", "a filter or the cursor is not valid for this entity", [detail("cursor", "INVALID_CURSOR", "the value does not match this entity")]) from None
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor([rows[-1][k] for k in spec.key]) if more else None
        data = [db.jsonable_row(r) for r in rows]
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "limit": limit, **filters}
        return {"data": data, "meta": meta(conn, applied, total, next_cursor, _counts(conn)), "warnings": []}


def read_metrics(lo: str | None, hi: str | None, cutoff: str | None, source_id: str | None, group_by: str) -> dict[str, Any]:
    if group_by not in GROUPS:
        raise ApiError(422, "VALIDATION_FAILED", "unsupported group_by", [detail("group_by", "INVALID_GROUP_BY", f"use one of {', '.join(GROUPS)}")])
    window = parse_window(lo, hi)
    when = parse_instant(cutoff, "cutoff") if cutoff else clock.now()
    with db.transaction() as conn:
        acc = db.load_rows(conn)
        if source_id is not None and source_id not in {s["source_id"] for s in acc["source_contracts"]}:
            raise ApiError(404, "NOT_FOUND", "source not found", [detail("source_id", "UNKNOWN_SOURCE", "source not found")])
        params = db.load_params(conn, iso_z(when))
        scoped = restrict(acc, source_id, window[0], window[1], when)
        params["source_expectations"] = restrict_expectations(params["source_expectations"], source_id, window[0], window[1], when)
        pm = params["processing_measurement"]
        if pm is not None and pm["batch_id"] not in {b["batch_id"] for b in scoped["ingestion_batches"]}:
            params["processing_measurement"] = None
        try:
            golden = compute(scoped, db.load_rejected(conn), params)
        except DomainError as err:
            raise from_domain(err, "cutoff") from None
        data: dict[str, Any] = {"as_of": golden["as_of"], "cutoff": golden["cutoff"], "window": {"from": iso_z(window[0]), "to": iso_z(window[1])},
                                "source_id": source_id, "group_by": group_by, "empty_population": golden["empty_population"], "ingest": golden["ingest"],
                                "metrics": golden["metrics"]}
        deleted = conn.execute("SELECT a.source_id, a.source_key, a.batch_id, a.deleted_in_batch, r.payload_json FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id "
                               "WHERE a.deleted_in_batch IS NOT NULL ORDER BY a.source_id COLLATE \"C\", a.source_key COLLATE \"C\"").fetchall()
        data["deleted_records"] = [{"source_id": d["source_id"], "source_key": d["source_key"], "accepted_in_batch": d["batch_id"], "deleted_in_batch": d["deleted_in_batch"],
                                    "excluded_amount": format(money_amount(d["payload_json"]), "f"), "reason": "DELETE_EVENT"} for d in deleted]
        if group_by == "source":
            m = golden["metrics"]
            data["groups"] = {sid: {"ingestion": m["ingestion"]["sources"][sid], "freshness": m["freshness"].get(sid), "completeness": m["completeness"].get(sid, {})}
                              for sid in sorted(m["ingestion"]["sources"])}
        warnings = [{"code": "PROCESSING_RATE_OBSERVED", "message": "the processing rate is an observed value with its hardware and cache state, not a benchmark", "path": "metrics.processing_rate"}] \
            if golden["metrics"]["processing_rate"]["records_per_second"] is not None else []
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "cutoff": iso_z(when), "source_id": source_id, "group_by": group_by}
        return {"data": data, "meta": meta(conn, applied, len(scoped["source_contracts"]), None, _counts(conn)), "warnings": warnings}
