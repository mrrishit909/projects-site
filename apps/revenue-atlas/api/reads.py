"""Read side: GET /data/{entity} and GET /metrics (docs/api-contract.md, D-01, D-05).

* Entity reads are ordered by the entity's key, paged with an opaque cursor (base64 of the
  last key) so pages are stable with no duplicates or gaps; ``from``/``to`` filter the
  entity's time field on the half-open window ``[from, to)``.
* Metrics run the domain pipeline over facts assembled from the tables.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

import psycopg
from revenue_atlas import CONTRACT_VERSION, DomainError, group_metrics, run_pipeline
from revenue_atlas.metrics import check_window
from revenue_atlas.models import ShipmentLineFact

from . import db
from .errors import ApiError, detail, from_domain

Conn = psycopg.Connection[db.Row]


@dataclass(frozen=True)
class EntitySpec:
    table: str
    key: tuple[str, ...]
    time_field: str | None = None


ENTITIES: dict[str, EntitySpec] = {s.table: s for s in (
    EntitySpec("customers", ("customer_id", "effective_from"), "effective_from"),
    EntitySpec("products", ("product_id",)),
    EntitySpec("orders", ("order_id",), "order_date"),
    EntitySpec("order_lines", ("line_id",)),
    EntitySpec("discounts", ("discount_id",)),
    EntitySpec("shipments", ("shipment_id",), "shipped_at"),
    EntitySpec("shipment_lines", ("shipment_line_id",)),
    EntitySpec("returns", ("return_id",), "credit_date"),
    EntitySpec("cost_versions", ("cost_version_id",), "valid_from"),
    EntitySpec("exchange_rates", ("rate_id",), "rate_date"),
    EntitySpec("rejected_records", ("batch_id", "entity", "id")),
    EntitySpec("quarantined_records", ("entity", "id")),
    EntitySpec("freight_allocations", ("shipment_line_id",), "allocated_at"),
    EntitySpec("audit_events", ("event_id",), "occurred_at"),
)}

GROUP_BY: dict[str, Callable[[ShipmentLineFact], str]] = {
    "region": lambda f: f.region_id,
    "customer": lambda f: f.customer_id,
    "product": lambda f: f.product_id,
    "month": lambda f: f.shipped_at.astimezone(timezone.utc).strftime("%Y-%m"),
}


def parse_instant(value: str, name: str) -> datetime:
    """ISO date or datetime; a missing zone means UTC (D-01)."""
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "VALIDATION_FAILED", f"{name} is not an ISO-8601 date or datetime",
                       [detail(name, "INVALID_FILTER", f"{name} must be ISO-8601")]) from None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def parse_window(lo: str | None, hi: str | None) -> tuple[datetime | None, datetime | None]:
    """Half-open window; from >= to is INVALID_WINDOW (D-01)."""
    window = (parse_instant(lo, "from") if lo else None, parse_instant(hi, "to") if hi else None)
    try:
        check_window(window)
    except DomainError as err:
        raise from_domain(err, "from") from None
    return window


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps([db.jsonable(v) for v in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, width: int) -> list[str]:
    bad = ApiError(422, "VALIDATION_FAILED", "cursor is not valid",
                   [detail("cursor", "INVALID_CURSOR", "cursor must come from a previous next_cursor")])
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        vals = json.loads(raw)
    except (binascii.Error, ValueError):
        raise bad from None
    if not (isinstance(vals, list) and len(vals) == width and all(isinstance(v, str) for v in vals)):
        raise bad
    return vals


def meta(conn: Conn, applied: dict[str, Any], total: int, next_cursor: str | None,
         exclusions: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT dataset_version FROM dataset_versions "
                       "ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return {"dataset_version": row["dataset_version"] if row else "unversioned",
            "code_sha": os.environ.get("CODE_SHA", "dev"), "contract_version": CONTRACT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "applied_filters": applied, "total_count": total, "next_cursor": next_cursor,
            "exclusions": exclusions}


def _counts(conn: Conn) -> dict[str, int]:
    return {"rejected_records": conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"],
            "quarantined_records": conn.execute("SELECT count(*) AS n FROM quarantined_records").fetchone()["n"]}


def read_entity(entity: str, limit: int, cursor: str | None, lo: str | None,
                hi: str | None) -> dict[str, Any]:
    spec = ENTITIES.get(entity)
    if spec is None:
        raise ApiError(404, "NOT_FOUND", f"unknown entity {entity!r}",
                       [detail("entity", "ENTITY_UNKNOWN", f"known: {', '.join(sorted(ENTITIES))}")])
    window = parse_window(lo, hi)
    if (lo or hi) and spec.time_field is None:
        raise ApiError(422, "VALIDATION_FAILED", f"{entity} has no time field to filter on",
                       [detail("from" if lo else "to", "FILTER_NOT_SUPPORTED",
                               f"{entity} cannot be filtered by time")])
    # Table and column names below come from the ENTITIES constants, never from the request.
    where: list[str] = []
    params: list[Any] = []
    if spec.time_field and window[0] is not None:
        where.append(f"{spec.time_field} >= %s")
        params.append(window[0])
    if spec.time_field and window[1] is not None:
        where.append(f"{spec.time_field} < %s")
        params.append(window[1])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order = ", ".join(spec.key)
    page_where, page_params = where_sql, list(params)
    if cursor:
        after = decode_cursor(cursor, len(spec.key))
        keys = ", ".join(spec.key)
        marks = ", ".join(["%s"] * len(spec.key))
        page_where += (" AND " if where else " WHERE ") + f"({keys}) > ({marks})"
        page_params += after
    with db.transaction() as conn:
        total = conn.execute(f"SELECT count(*) AS n FROM {spec.table}{where_sql}", params).fetchone()["n"]
        try:
            rows = conn.execute(f"SELECT * FROM {spec.table}{page_where} ORDER BY {order} LIMIT %s",
                                page_params + [limit + 1]).fetchall()
        except psycopg.errors.DataError:
            raise ApiError(422, "VALIDATION_FAILED", "cursor is not valid",
                           [detail("cursor", "INVALID_CURSOR", "cursor does not match this entity")]) from None
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor([rows[-1][k] for k in spec.key]) if more else None
        applied = {"from": window[0].isoformat() if window[0] else None,
                   "to": window[1].isoformat() if window[1] else None, "limit": limit}
        return {"data": [db.jsonable_row(r) for r in rows],
                "meta": meta(conn, applied, total, next_cursor, _counts(conn)), "warnings": []}


def read_metrics(lo: str | None, hi: str | None, group_by: str) -> dict[str, Any]:
    if group_by != "none" and group_by not in GROUP_BY:
        raise ApiError(422, "VALIDATION_FAILED", "unsupported group_by",
                       [detail("group_by", "INVALID_GROUP_BY", "use none, region, customer, product or month")])
    window = parse_window(lo, hi)
    with db.transaction() as conn:
        res = run_pipeline(db.load_batch(conn), include_returns=True, window=window)
        if group_by == "none":
            data: dict[str, Any] = {"group_by": "none", "metrics": res.metrics}
        else:
            data = {"group_by": group_by,
                    "groups": group_metrics(res.facts, GROUP_BY[group_by], window, res.returns)}
        quarantined: dict[str, int] = {}
        for q in res.quarantined:
            quarantined[q.entity] = quarantined.get(q.entity, 0) + 1
        exclusions = {"excluded_shipment_lines": len(res.excluded_shipment_lines),
                      "quarantined": quarantined, **_counts(conn)}
        warnings = [{"code": "QUARANTINED_RECORDS_EXCLUDED",
                     "message": f"{sum(quarantined.values())} record(s) quarantined and excluded",
                     "path": None}] if quarantined else []
        applied = {"from": window[0].isoformat() if window[0] else None,
                   "to": window[1].isoformat() if window[1] else None, "group_by": group_by}
        return {"data": data, "meta": meta(conn, applied, len(res.facts), None, exclusions),
                "warnings": warnings}
