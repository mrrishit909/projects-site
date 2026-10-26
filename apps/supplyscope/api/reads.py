"""Read side: GET /data/{entity} and GET /metrics (docs/api-contract.md, D-01, D-04).

* Entity reads are ordered by the entity's key and paged with an opaque cursor (base64 of the last key), so pages are
  stable with no duplicates or gaps. ``from``/``to`` filter the entity's time field on the half-open window
  ``[from, to)``; other filters are equality on a whitelist of columns (unknown filter: 422 INVALID_FILTER).
* Metrics run the domain over the population assembled from the tables at ``as_of`` over the half-open window
  ``[from, to)``; ``state`` names a stored fixture state; ``group_by`` is product, location, supplier or abc_class.
* Canonical reads (R3-02): unmet-demand rows recorded under a scenario (C07) are excluded from the metrics and from
  ``/data/backorders`` and ``/data/lost_sales``, unless that scenario is asked for (``/metrics?scenario=<id>`` adds its
  rows to the canonical ones; ``/data/backorders?scenario_id=<id>`` lists them).
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
from supplyscope import CONTRACT_VERSION, DomainError
from supplyscope.contract import GROUP_KEYS
from supplyscope.metrics import (availability_flags, check_window, compute_metrics, group_metrics,
                                 negative_stock_flags, supplementary)
from supplyscope.models import iso_z

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
    canonical: bool = False     # rows with a scenario_id are hidden unless a scenario_id filter is given (R3-02)


ENTITIES: dict[str, EntitySpec] = {s.table: s for s in (
    EntitySpec("products", ("product_id",), None, ("abc_class", "supplier_id")),
    EntitySpec("locations", ("location_id",), None, ("active",)),
    EntitySpec("suppliers", ("supplier_id",), None, ("active", "calendar_id")),
    EntitySpec("calendar_closures", ("closure_id",), None, ("calendar_id",)),
    EntitySpec("cost_versions", ("cost_version_id",), "effective_from", ("product_id",)),
    EntitySpec("policy_scenarios", ("scenario_id",), None, ("unmet_policy",)),
    EntitySpec("purchase_orders", ("purchase_order_id",), "ordered_at", ("supplier_id", "status")),
    EntitySpec("purchase_order_lines", ("po_line_id",), None, ("purchase_order_id", "product_id")),
    EntitySpec("receipts", ("receipt_id",), "received_at", ("po_line_id", "location_id")),
    EntitySpec("inventory_movements", ("movement_id",), "event_at", ("product_id", "location_id", "movement_type")),
    EntitySpec("sales", ("sale_id",), "sold_at", ("product_id", "location_id")),
    EntitySpec("promotions", ("promotion_id",), "starts_at", ("product_id",)),
    EntitySpec("latent_demand", ("product_id", "location_id", "demand_date"), None, ("product_id", "location_id")),
    EntitySpec("forecast_runs", ("forecast_run_id",), "cutoff", ("product_id", "location_id", "selected_model")),
    EntitySpec("forecast_points", ("forecast_point_id",), None, ("forecast_run_id", "model")),
    EntitySpec("backorders", ("backorder_id",), "opened_at", ("product_id", "location_id", "scenario_id"), True),
    EntitySpec("lost_sales", ("lost_sale_id",), "occurred_at", ("product_id", "location_id", "scenario_id"), True),
    EntitySpec("reservations", ("reservation_id",), "reserved_at", ("product_id", "location_id")),
    EntitySpec("replenishment_params", ("product_id", "location_id"), None, ("product_id", "location_id")),
    EntitySpec("stock_snapshots", ("as_of", "product_id", "location_id"), "as_of", ("product_id", "location_id")),
    EntitySpec("draft_orders", ("draft_order_id",), "as_of", ("product_id", "location_id", "supplier_id", "scenario_id",
                                                              "status")),
    EntitySpec("fixture_states", ("state_name",), None, ()),
    EntitySpec("rejected_records", ("batch_id", "entity", "id", "reason_code", "ordinal"), None, ("entity", "reason_code")),
    EntitySpec("quarantined_records", ("entity", "id"), None, ("entity", "reason_code")),
    EntitySpec("audit_events", ("event_id",), "occurred_at", ("entity_type", "entity_id", "action", "actor_id")),
    EntitySpec("dataset_versions", ("dataset_version",), "created_at"),
)}

_BOOL_COLUMNS = frozenset({"active"})
#: Cursor values are strings; key columns that are not text are cast back for the comparison.
_CAST = {"as_of": "timestamptz", "ordinal": "int", "demand_date": "date"}


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
    try:
        check_window(window)
    except DomainError as err:
        raise from_domain(err, "from") from None
    return window


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps([str(db.jsonable(v)) for v in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, width: int) -> list[str]:
    bad = ApiError(422, "VALIDATION_FAILED", "cursor is not valid",
                   [detail("cursor", "INVALID_CURSOR", "cursor must come from a previous next_cursor")])
    try:
        vals = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError):
        raise bad from None
    if not (isinstance(vals, list) and len(vals) == width and all(isinstance(v, str) for v in vals)):
        raise bad
    return vals


def meta(conn: Conn, applied: dict[str, Any], total: int, next_cursor: str | None,
         exclusions: dict[str, Any]) -> dict[str, Any]:
    return {"dataset_version": db.dataset_version(conn), "code_sha": os.environ.get("CODE_SHA", "dev"),
            "contract_version": CONTRACT_VERSION, "generated_at": iso_z(datetime.now(timezone.utc)),
            "applied_filters": applied, "total_count": total, "next_cursor": next_cursor, "exclusions": exclusions}


def _counts(conn: Conn) -> dict[str, int]:
    return {"rejected_records": conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"],
            "quarantined_records": conn.execute("SELECT count(*) AS n FROM quarantined_records").fetchone()["n"]}


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
    if spec.canonical and "scenario_id" not in filters:
        where.append("scenario_id IS NULL")
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
        marks = ", ".join(f"%s::{_CAST.get(k, 'text')}" for k in spec.key)
        page_where += (" AND " if where else " WHERE ") + f"({order}) > ({marks})"
        page_params += after
    with db.transaction() as conn:
        total = conn.execute(f"SELECT count(*) AS n FROM {spec.table}{where_sql}", params).fetchone()["n"]
        try:
            rows = conn.execute(f"SELECT * FROM {spec.table}{page_where} ORDER BY {order} LIMIT %s",
                                page_params + [limit + 1]).fetchall()
        except (psycopg.errors.DataError, psycopg.errors.UndefinedFunction, psycopg.errors.DatatypeMismatch):
            raise ApiError(422, "VALIDATION_FAILED", "cursor is not valid",
                           [detail("cursor", "INVALID_CURSOR", "cursor does not match this entity")]) from None
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor([rows[-1][k] for k in spec.key]) if more else None
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "limit": limit, **filters}
        return {"data": [db.jsonable_row(r) for r in rows],
                "meta": meta(conn, applied, total, next_cursor, _counts(conn)), "warnings": []}


def read_metrics(as_of: str | None, lo: str | None, hi: str | None, state: str | None, group_by: str,
                 scenario: str | None = None) -> dict[str, Any]:
    if group_by != "none" and group_by not in GROUP_KEYS:
        raise ApiError(422, "VALIDATION_FAILED", "unsupported group_by",
                       [detail("group_by", "INVALID_GROUP_BY", f"use none, {', '.join(GROUP_KEYS)}")])
    window = parse_window(lo, hi)
    cut = parse_instant(as_of, "as_of") if as_of else datetime.now(timezone.utc).replace(microsecond=0)
    with db.transaction() as conn:
        spec = None
        if state is not None:
            row = conn.execute("SELECT payload FROM fixture_states WHERE state_name = %s", (state,)).fetchone()
            if row is None:
                known = [r["state_name"] for r in conn.execute("SELECT state_name FROM fixture_states ORDER BY 1").fetchall()]
                raise ApiError(422, "VALIDATION_FAILED", "unsupported state",
                               [detail("state", "INVALID_STATE", f"known: {', '.join(known) or 'none'}")])
            spec = row["payload"]
        if scenario is not None and conn.execute("SELECT 1 FROM policy_scenarios WHERE scenario_id = %s",
                                                 (scenario,)).fetchone() is None:
            raise ApiError(422, "VALIDATION_FAILED", "unknown scenario",
                           [detail("scenario", "INVALID_SCENARIO", f"scenario {scenario!r} does not exist")])
        pop = db.load_population(conn)
        try:
            if group_by == "none":
                data: dict[str, Any] = {"group_by": "none", "state": state, "scenario": scenario, "as_of": iso_z(cut),
                                        "metrics": compute_metrics(pop, cut, window, spec, scenario_id=scenario),
                                        "supplementary": supplementary(pop, cut, window)}
            else:
                data = {"group_by": group_by, "state": state, "scenario": scenario, "as_of": iso_z(cut),
                        "groups": group_metrics(pop, group_by, cut, window, spec, scenario_id=scenario)}
        except DomainError as err:
            raise from_domain(err, "state") from None
        warnings = [{"code": f["flag"], "message": "the reconstruction is negative: flagged, valued at zero "
                                                   "(the position uses the unclamped value)",
                     "path": f"stock[{f['product_id']}:{f['location_id']}]"} for f in negative_stock_flags(pop, cut)]
        warnings += [{"code": f["flag"], "message": "reserved exceeds the on-hand stock: available is below zero",
                      "path": f"stock[{f['product_id']}:{f['location_id']}]"} for f in availability_flags(pop, cut)]
        applied = {"as_of": iso_z(cut), "from": iso_z(window[0]), "to": iso_z(window[1]), "state": state,
                   "group_by": group_by, "scenario": scenario}
        return {"data": data, "meta": meta(conn, applied, len(pop.products), None, _counts(conn)), "warnings": warnings}
