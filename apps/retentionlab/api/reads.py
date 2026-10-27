"""Read side: GET /data/{entity} and GET /metrics (docs/api-contract.md, docs/contracts.md D-03..D-05).

* Entity reads are ordered by the entity's key (code-point order; numeric for integer keys) and paged with an opaque cursor (base64 of
  the last key), so pages are stable with no duplicates or gaps. ``from``/``to`` filter the entity's time field on the half-open window
  ``[from, to)``; other filters are equality on a whitelist of columns per entity (unknown filter: 422 INVALID_FILTER). No actor is
  needed. Decimals are returned as strings exactly as stored (NUMERIC(20,6)); no float is ever serialised.
* GET /metrics computes the twelve metrics over the tables AS KNOWN at ``as_of`` (default: the server's now; later-arriving events,
  predictions and publications are invisible), for a ``training_run_id`` and the cutoff sets selected by ``prediction_at`` /
  ``cutoff_id`` (a cutoff row names its set) or by the half-open window ``[from, to)`` on ``prediction_at`` (default: every set), with an
  optional ``scenario_id`` (K, contact budget, expected value, the draft queue) and ``model``. A scenario whose K exceeds the evaluated
  population of a set that HAS labels is refused 422 CAPACITY_EXCEEDS_POPULATION; with an empty evaluated population the K metrics are
  null (D-P10-04). ``reference_prediction_at`` adds the PSI of usage_events_30d against that cohort (a diagnostic).
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
from retentionlab import errors as E
from retentionlab.contract import CONTRACT_VERSION, DEFAULT_DRIFT, MODELS
from retentionlab.ingest import Ingest
from retentionlab.metrics import freshness, publications, set_metrics
from retentionlab.pipeline import consistency
from retentionlab.rules import check_as_of
from retentionlab.split import split_run
from retentionlab.timeutil import iso_z, parse_ts
from retentionlab.world import World

from . import clock, db
from .errors import ApiError, detail, from_domain

Conn = psycopg.Connection[db.Row]
RESERVED = frozenset({"limit", "cursor", "from", "to"})


@dataclass(frozen=True)
class EntitySpec:
    table: str
    key: tuple[str, ...]
    time_field: str | None = None
    filters: tuple[str, ...] = field(default_factory=tuple)
    columns: str = "*"


ENTITIES: dict[str, EntitySpec] = {s.table: s for s in (
    EntitySpec("accounts", ("account_id",), "created_at", ("segment", "region", "synthetic")),
    EntitySpec("subscription_events", ("subscription_event_id",), "event_at", ("account_id", "event_type")),
    EntitySpec("billing_events", ("billing_event_id",), "event_at", ("account_id",)),
    EntitySpec("usage_events", ("usage_event_id",), "event_at", ("account_id", "event_name")),
    EntitySpec("support_events", ("support_event_id",), "event_at", ("account_id", "severity")),
    EntitySpec("prediction_cutoffs", ("cutoff_id",), "prediction_at", ("account_id",)),
    EntitySpec("feature_rows", ("feature_row_id",), "max_available_at", ("cutoff_id", "feature_version")),
    EntitySpec("labels", ("label_id",), "label_end", ("cutoff_id", "churned", "mature")),
    EntitySpec("training_runs", ("training_run_id",), "created_at", ("training_run_id", "created_by")),
    EntitySpec("predictions", ("prediction_id",), "scored_at", ("training_run_id", "cutoff_id", "model_name")),
    EntitySpec("intervention_scenarios", ("scenario_id",), "created_at", ("scenario_id", "created_by")),
    EntitySpec("outreach_events", ("outreach_event_id",), "created_at", ("account_id", "scenario_id", "status", "training_run_id")),
    EntitySpec("feature_registry", ("feature_version", "feature_name"), None, ("feature_version", "post_outcome", "latent", "id_derived")),
    EntitySpec("split_assignments", ("assignment_id",), None, ("training_run_id", "split", "status", "drop_reason")),
    EntitySpec("scoring_publications", ("publication_id",), "published_at", ("training_run_id", "status", "model_name")),
    EntitySpec("rejected_records", ("batch_id", "entity", "id", "reason_code", "ordinal"), "created_at", ("entity", "reason_code")),
    EntitySpec("audit_events", ("event_id",), "occurred_at", ("entity_type", "entity_id", "action", "actor_id")),
    EntitySpec("dataset_versions", ("dataset_version",), "created_at"),
)}

_BOOL_COLUMNS = frozenset({"synthetic", "churned", "mature", "post_outcome", "latent", "id_derived"})
_INT_COLUMNS = frozenset({"account_id", "ordinal"})


def parse_instant(value: str, name: str) -> datetime:
    """ISO date or datetime; a missing zone means UTC."""
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "VALIDATION_FAILED", f"{name} is not an ISO-8601 date or datetime",
                       [detail(name, "INVALID_FILTER", f"{name} must be ISO-8601")]) from None
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


def _filter_value(name: str, value: str) -> Any:
    if name in _BOOL_COLUMNS:
        if value not in ("true", "false"):
            raise ApiError(422, "VALIDATION_FAILED", f"{name} must be true or false", [detail(name, "INVALID_FILTER", f"{name} must be true or false")])
        return value == "true"
    if name in _INT_COLUMNS:
        try:
            return int(value)
        except ValueError:
            raise ApiError(422, "VALIDATION_FAILED", f"{name} must be an integer", [detail(name, "INVALID_FILTER", f"{name} must be an integer")]) from None
    return value


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
        where.append(f"{name} = %s")
        params.append(_filter_value(name, value))
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
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "limit": limit, **filters}
        return {"data": [db.jsonable_row(r) for r in rows], "meta": meta(conn, applied, total, next_cursor, _counts(conn)), "warnings": []}


def _names(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def read_metrics(training_run_id: str | None, cutoff_id: str | None, prediction_at: str | None, lo: str | None, hi: str | None, as_of: str | None,
                 scenario_id: str | None, model: str, reference_prediction_at: str | None) -> dict[str, Any]:
    if model not in MODELS:
        raise ApiError(422, "VALIDATION_FAILED", f"unknown model {model!r}", [detail("model", E.UNKNOWN_MODEL, f"use one of {', '.join(MODELS)}")])
    window = parse_window(lo, hi)
    when = parse_instant(as_of, "as_of") if as_of else clock.now()
    try:
        check_as_of(when, clock.now())                                  # D-09 (R10-01): the future is not known, so nothing is mature in it
    except E.DomainError as err:
        raise from_domain(err, "as_of") from None
    wanted = [iso_z(parse_instant(p, "prediction_at")) for p in _names(prediction_at)]
    with db.transaction() as conn:
        data = db.load_data(conn, when, model)
        world = World(data, data)
        runs = sorted(world.runs)
        if training_run_id is not None:
            if training_run_id not in world.runs:
                raise ApiError(404, "NOT_FOUND", "training run not found", [detail("training_run_id", E.UNKNOWN_TRAINING_RUN, "training run not found")])
            run_id = training_run_id
        elif len(runs) > 1:
            raise ApiError(422, "VALIDATION_FAILED", "several training runs exist: name one",
                           [detail("training_run_id", "TRAINING_RUN_REQUIRED", "name a training_run_id from /data/training_runs")])
        else:
            run_id = runs[0] if runs else ""
        if scenario_id is not None and scenario_id not in world.scenarios:
            raise ApiError(404, "NOT_FOUND", "scenario not found", [detail("scenario_id", E.UNKNOWN_SCENARIO, "scenario not found")])
        by_cutoff = {c["cutoff_id"]: iso_z(parse_ts(c["prediction_at"])) for c in data["prediction_cutoffs"]}
        for c in _names(cutoff_id):
            if c not in by_cutoff:
                raise ApiError(404, "NOT_FOUND", f"cutoff {c!r} not found", [detail("cutoff_id", E.UNKNOWN_CUTOFF, "cutoff not found")])
            wanted.append(by_cutoff[c])
        known = world.prediction_ats()
        for p in wanted:
            if p not in known:
                raise ApiError(404, "NOT_FOUND", f"cutoff set {p!r} not found", [detail("prediction_at", E.UNKNOWN_CUTOFF, "no cutoff row has this prediction_at")])
        sets = sorted(set(wanted)) if wanted else known
        sets = [p for p in sets if (window[0] is None or parse_ts(p) >= window[0]) and (window[1] is None or parse_ts(p) < window[1])]
        drift = None
        if reference_prediction_at is not None:
            ref = iso_z(parse_instant(reference_prediction_at, "reference_prediction_at"))
            if ref not in known:
                raise ApiError(404, "NOT_FOUND", "reference cohort not found", [detail("reference_prediction_at", E.UNKNOWN_CUTOFF, "no cutoff row has this prediction_at")])
            drift = {**DEFAULT_DRIFT, "reference_prediction_at": ref}
        blocks: dict[str, Any] = {}
        queues: dict[str, list[int]] = {}
        warnings: list[dict[str, Any]] = []
        for p in sets:
            m = set_metrics(world, run_id, p, scenario_id, drift)
            cap = m["capacity"]
            if cap and cap["refusal"]:
                raise ApiError(422, "VALIDATION_FAILED", f"capacity {cap['k']} exceeds the evaluated population {cap['population']} of {p}",
                               [{**detail("scenario_id", E.CAPACITY_EXCEEDS_POPULATION, "K may not exceed the evaluated population"),
                                 "context": {"offending": [{"item": scenario_id, "code": f"CAPACITY_{cap['k']}_GT_{cap['population']}"}], "prediction_at": p}}])
            blocks[p] = m
            if m["outreach_queue"] is not None:
                queues[scenario_id or ""] = m["outreach_queue"]["account_ids"]
            if m["population"]["censored"]:
                warnings.append({"code": "LABELS_PENDING", "path": f"cutoff_sets.{p}.population.censored",
                                 "message": f"{m['population']['censored']} eligible row(s) are censored (immature label window) and excluded from outcome metrics"})
        if scenario_id is not None:
            warnings.append({"code": "HYPOTHETICAL", "path": "cutoff_sets.economics", "message": "economics are hypothetical and assumption-based; no treatment effect is estimated"})
        splits = {rid: split_run(world, run) for rid, run in world.runs.items()}
        pubs = publications(world)
        out = {"as_of": iso_z(when), "training_run_id": run_id or None, "model": model, "scenario_id": scenario_id,
               "window": {"from": iso_z(window[0]), "to": iso_z(window[1])}, "cutoff_sets": blocks,
               "freshness": freshness(world, pubs), "scoring_publications": pubs,
               "consistency": consistency(world, Ingest(data, []), splits, pubs, {k: v for k, v in queues.items() if k}),
               "empty_population": all(b["empty_population"] for b in blocks.values()) if blocks else True}
        applied = {"training_run_id": run_id or None, "prediction_at": sets, "from": iso_z(window[0]), "to": iso_z(window[1]), "as_of": iso_z(when),
                   "scenario_id": scenario_id, "model": model, "reference_prediction_at": reference_prediction_at}
        return {"data": out, "meta": meta(conn, applied, len(sets), None, _counts(conn)), "warnings": warnings}
