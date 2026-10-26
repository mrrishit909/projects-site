"""Read side: GET /data/{entity} and GET /metrics (docs/api-contract.md, D-02, D-05).

* Entity reads are ordered by the entity's key and paged with an opaque cursor (base64 of the last key), so pages
  are stable with no duplicates or gaps. ``from``/``to`` filter the entity's time field on the half-open window
  ``[from, to)``; other filters are equality on a whitelist of columns per entity (unknown filter: 422 INVALID_FILTER).
* Metrics run the domain over the population assembled from the tables. The window is half-open on the instants the
  metric is about (arrivals on ``created_at``, completions on the final resolution). Without ``from`` the window starts
  at the earliest arrival; without ``to`` it ends one second after the latest recorded instant; without ``cutoff`` the
  backlog is read at the window end. ``group_by`` is none, queue, priority, agent or channel.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from serviceflow import CONTRACT_VERSION, DomainError
from serviceflow.contract import DEFAULT_ABANDONABLE, GROUP_KEYS
from serviceflow.metrics import check_window, compute_metrics, disclosures, group_metrics
from serviceflow.timeutil import iso_z

from . import db
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


_EVENT_COLS = "event_id, ticket_id, event_type, occurred_at, actor_id, queue_id, agent_id"

ENTITIES: dict[str, EntitySpec] = {s.table: s for s in (
    EntitySpec("customers", ("customer_id",), "created_at", ("segment", "timezone", "synthetic")),
    EntitySpec("queues", ("queue_id",), None, ("active", "priority_policy", "calendar_id")),
    EntitySpec("tickets", ("ticket_id",), "created_at", ("customer_id", "queue_id", "priority", "channel")),
    EntitySpec("ticket_events", ("event_id",), "occurred_at", ("ticket_id", "event_type", "agent_id", "queue_id", "actor_id"),
               _EVENT_COLS),
    EntitySpec("agents", ("agent_id",), None, ("active", "employment_type", "timezone")),
    EntitySpec("skills", ("skill_id",), "created_at", ("active",)),
    EntitySpec("agent_skills", ("agent_skill_id",), "effective_from", ("agent_id", "skill_id")),
    EntitySpec("queue_skills", ("queue_id", "skill_id"), None, ("queue_id", "skill_id")),
    EntitySpec("shifts", ("shift_id",), "starts_at", ("agent_id",)),
    EntitySpec("shift_breaks", ("break_id",), "starts_at", ("agent_id", "shift_id")),
    EntitySpec("sla_policies", ("sla_policy_id",), None, ("priority", "calendar_id")),
    EntitySpec("surveys", ("survey_id",), "invited_at", ("ticket_id",)),
    EntitySpec("simulation_runs", ("simulation_id",), "created_at", ("policy_version",)),
    EntitySpec("simulation_events", ("simulation_id", "simulation_event_id"), None,
               ("simulation_id", "ticket_id", "event_type", "warmup")),
    EntitySpec("rejected_records", ("batch_id", "entity", "id", "reason_code", "ordinal"), None, ("entity", "reason_code")),
    EntitySpec("audit_events", ("event_id",), "occurred_at", ("entity_type", "entity_id", "action", "actor_id")),
    EntitySpec("dataset_versions", ("dataset_version",), "created_at"),
)}

#: Columns that are not TEXT, with how a query-string value is converted.
_BOOL_COLUMNS = frozenset({"required", "active", "synthetic", "warmup"})


def parse_instant(value: str, name: str) -> datetime:
    """ISO date or datetime; a missing zone means UTC."""
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "VALIDATION_FAILED", f"{name} is not an ISO-8601 date or datetime",
                       [detail(name, "INVALID_FILTER", f"{name} must be ISO-8601")]) from None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def parse_window(lo: str | None, hi: str | None) -> tuple[datetime | None, datetime | None]:
    """Half-open window; from >= to is INVALID_WINDOW."""
    window = (parse_instant(lo, "from") if lo else None, parse_instant(hi, "to") if hi else None)
    if window[0] is not None and window[1] is not None:
        try:
            check_window((window[0], window[1]))
        except DomainError as err:
            raise from_domain(err, "from") from None
    return window


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps([db.jsonable(v) for v in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, width: int) -> list[Any]:
    bad = ApiError(422, "VALIDATION_FAILED", "cursor is not valid",
                   [detail("cursor", "INVALID_CURSOR", "cursor must come from a previous next_cursor")])
    try:
        vals = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError):
        raise bad from None
    if not (isinstance(vals, list) and len(vals) == width and all(isinstance(v, (str, int)) for v in vals)):
        raise bad
    return vals


def meta(conn: Conn, applied: dict[str, Any], total: int, next_cursor: str | None,
         exclusions: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT dataset_version FROM dataset_versions "
                       "ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return {"dataset_version": row["dataset_version"] if row else "unversioned",
            "code_sha": os.environ.get("CODE_SHA", "dev"), "contract_version": CONTRACT_VERSION,
            "generated_at": iso_z(datetime.now(timezone.utc)), "applied_filters": applied,
            "total_count": total, "next_cursor": next_cursor, "exclusions": exclusions}


def _counts(conn: Conn) -> dict[str, int]:
    return {"rejected_records": conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"]}


def read_entity(entity: str, limit: int, cursor: str | None, lo: str | None, hi: str | None,
                filters: dict[str, str]) -> dict[str, Any]:
    spec = ENTITIES.get(entity)
    if spec is None:
        raise ApiError(404, "NOT_FOUND", f"unknown entity {entity!r}",
                       [detail("entity", "ENTITY_UNKNOWN", f"known: {', '.join(sorted(ENTITIES))}")])
    for name in filters:
        if name not in spec.filters:
            raise ApiError(422, "VALIDATION_FAILED", f"{entity} cannot be filtered by {name!r}",
                           [detail(name, "INVALID_FILTER", f"allowed: {', '.join(spec.filters) or 'none'}")])
    window = parse_window(lo, hi)
    if (lo or hi) and spec.time_field is None:
        raise ApiError(422, "VALIDATION_FAILED", f"{entity} has no time field to filter on",
                       [detail("from" if lo else "to", "FILTER_NOT_SUPPORTED", f"{entity} cannot be filtered by time")])
    # Table and column names below come from the ENTITIES constants, never from the request.
    where: list[str] = []
    params: list[Any] = []
    if spec.time_field and window[0] is not None:
        where.append(f"{spec.time_field} >= %s")
        params.append(window[0])
    if spec.time_field and window[1] is not None:
        where.append(f"{spec.time_field} < %s")
        params.append(window[1])
    for name, value in sorted(filters.items()):
        if name in _BOOL_COLUMNS:
            if value not in ("true", "false"):
                raise ApiError(422, "VALIDATION_FAILED", f"{name} must be true or false",
                               [detail(name, "INVALID_FILTER", f"{name} must be true or false")])
            where.append(f"{name} = %s")
            params.append(value == "true")
        else:
            where.append(f"{name} = %s")
            params.append(value)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order = ", ".join(spec.key)
    page_where, page_params = where_sql, list(params)
    if cursor:
        after = decode_cursor(cursor, len(spec.key))
        marks = ", ".join(["%s"] * len(spec.key))
        page_where += (" AND " if where else " WHERE ") + f"({order}) > ({marks})"
        page_params += after
    with db.transaction() as conn:
        total = conn.execute(f"SELECT count(*) AS n FROM {spec.table}{where_sql}", params).fetchone()["n"]
        try:
            rows = conn.execute(f"SELECT {spec.columns} FROM {spec.table}{page_where} ORDER BY {order} LIMIT %s",
                                page_params + [limit + 1]).fetchall()
        except psycopg.errors.DataError:
            raise ApiError(422, "VALIDATION_FAILED", "cursor is not valid",
                           [detail("cursor", "INVALID_CURSOR", "cursor does not match this entity")]) from None
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor([rows[-1][k] for k in spec.key]) if more else None
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "limit": limit, **filters}
        return {"data": [db.jsonable_row(r) for r in rows],
                "meta": meta(conn, applied, total, next_cursor, _counts(conn)), "warnings": []}


def read_metrics(lo: str | None, hi: str | None, cutoff: str | None, group_by: str,
                 abandonable: str | None = None) -> dict[str, Any]:
    if group_by != "none" and group_by not in GROUP_KEYS:
        raise ApiError(422, "VALIDATION_FAILED", "unsupported group_by",
                       [detail("group_by", "INVALID_GROUP_BY", f"use none, {', '.join(GROUP_KEYS)}")])
    start, end = parse_window(lo, hi)
    channels = tuple(c for c in abandonable.split(",") if c) if abandonable is not None else DEFAULT_ABANDONABLE
    with db.transaction() as conn:
        pop = db.load_population(conn)
        if start is None:
            start = min((t.created_at for t in pop.tickets), default=datetime.now(timezone.utc).replace(microsecond=0))
        if end is None:
            last = max([e.occurred_at for e in pop.ticket_events] + [t.created_at for t in pop.tickets] + [start])
            end = last + timedelta(seconds=1)
        try:
            check_window((start, end))
            cutoffs = [parse_instant(c, "cutoff") for c in cutoff.split(",") if c] if cutoff else [end]
            if group_by == "none":
                data: dict[str, Any] = {"group_by": "none",
                                        "metrics": compute_metrics(pop, (start, end), cutoffs, channels)}
            else:
                data = {"group_by": group_by,
                        "groups": group_metrics(pop, group_by, (start, end), cutoffs, channels)}
            data["window"] = {"from": iso_z(start), "to": iso_z(end)}
            data["disclosures"] = disclosures(pop, (start, end))
        except DomainError as err:
            raise from_domain(err, "from") from None
        total = sum(1 for t in pop.tickets if start <= t.created_at < end)
        applied = {"from": iso_z(start), "to": iso_z(end), "cutoff": [iso_z(c) for c in cutoffs],
                   "group_by": group_by, "abandonable_channels": list(channels)}
        return {"data": data, "meta": meta(conn, applied, total, None, _counts(conn)), "warnings": []}
