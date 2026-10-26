"""Read side: GET /data/{entity}, GET /data/invoices/{id}/audit and GET /metrics (docs/api-contract.md, D-02, D-05).

* Entity reads are ordered by the entity's key and paged with an opaque cursor (base64 of the last key), so pages are
  stable with no duplicates or gaps. ``from``/``to`` filter the entity's time field on the half-open window ``[from, to)``;
  other filters are equality on a whitelist of columns per entity (unknown filter: 422 INVALID_FILTER).
* Metrics run the domain's derivation over the facts in the tables. ``from``/``to`` is the half-open window of invoice import
  instants (``to`` is also the as-of instant of every other fact: nothing stamped at or after it counts); ``cutoff`` is a
  comma-separated list of snapshot instants for the open quantities; ``group_by`` is none, vendor or currency.
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
from invoicebridge import CONTRACT_VERSION, DomainError
from invoicebridge.book import derive
from invoicebridge.metrics import GROUPS, disclosures, window_metrics
from invoicebridge.timeutil import iso_z

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


ENTITIES: dict[str, EntitySpec] = {s.table: s for s in (
    EntitySpec("vendors", ("vendor_id",), None, ("currency", "active")),
    EntitySpec("purchase_orders", ("po_id",), "ordered_at", ("vendor_id", "status", "currency")),
    EntitySpec("po_lines", ("po_line_id",), None, ("po_id", "product_code")),
    EntitySpec("receipts", ("receipt_id",), "received_at", ("po_line_id", "reversed")),
    EntitySpec("invoices", ("invoice_id",), "imported_at",
               ("vendor_id", "status", "currency", "created_by", "invoice_number_norm", "source_sha256", "merged_into")),
    EntitySpec("invoice_lines", ("invoice_line_id",), None, ("invoice_id", "po_line_id")),
    EntitySpec("match_results", ("invoice_line_id",), "matched_at", ("invoice_id", "status", "reason_code")),
    EntitySpec("exceptions", ("exception_id",), "created_at", ("invoice_id", "exception_type", "status", "owner_id")),
    EntitySpec("exception_assignments", ("assignment_id",), "assigned_at", ("exception_id", "owner_id")),
    EntitySpec("approvals", ("approval_id",), "decided_at", ("invoice_id", "actor_id", "decision")),
    EntitySpec("approval_policies", ("policy_id",), "effective_from", ("reviewer_role",)),
    EntitySpec("credit_notes", ("credit_id",), "credited_at", ("invoice_id",)),
    EntitySpec("export_batches", ("batch_id",), "exported_at", ("requested_by",)),
    EntitySpec("export_rows", ("export_id",), "exported_at", ("batch_id", "invoice_id", "vendor_id")),
    EntitySpec("export_requests", ("request_seq",), "exported_at", ("batch_id", "outcome")),
    EntitySpec("import_lineage", ("lineage_id",), "imported_at", ("invoice_id", "source_sha256", "import_status")),
    EntitySpec("rejected_records", ("batch_id", "entity", "id", "reason_code", "ordinal"), None, ("entity", "reason_code")),
    EntitySpec("audit_events", ("event_id",), "occurred_at", ("entity_type", "entity_id", "invoice_id", "action", "actor_id")),
    EntitySpec("dataset_versions", ("dataset_version",), "created_at"),
)}

_BOOL_COLUMNS = frozenset({"active", "reversed"})
_INT_COLUMNS = frozenset({"assignment_id", "lineage_id", "request_seq"})


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
        raise ApiError(422, "VALIDATION_FAILED", "from must be before to (the window is half-open)",
                       [detail("from", "INVALID_WINDOW", "from must be before to")])
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


def meta(conn: Conn, applied: dict[str, Any], total: int, next_cursor: str | None, exclusions: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
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
                raise ApiError(422, "VALIDATION_FAILED", f"{name} must be true or false",
                               [detail(name, "INVALID_FILTER", f"{name} must be true or false")])
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
        keyexpr = ", ".join(f'{k} COLLATE "C"' if k not in _INT_COLUMNS else k for k in spec.key)
        page_where += (" AND " if where else " WHERE ") + f"({keyexpr}) > ({marks})"
        page_params += after
    with db.transaction() as conn:
        try:
            total = conn.execute(f"SELECT count(*) AS n FROM {spec.table}{where_sql}", params).fetchone()["n"]
            rows = conn.execute(f"SELECT {spec.columns} FROM {spec.table}{page_where} ORDER BY {order} LIMIT %s",
                                page_params + [limit + 1]).fetchall()
        except psycopg.errors.DataError:
            raise ApiError(422, "VALIDATION_FAILED", "a filter or the cursor is not valid for this entity",
                           [detail("cursor", "INVALID_CURSOR", "the value does not match this entity")]) from None
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor([rows[-1][k] for k in spec.key]) if more else None
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "limit": limit, **filters}
        return {"data": [db.jsonable_row(r) for r in rows],
                "meta": meta(conn, applied, total, next_cursor, _counts(conn)), "warnings": []}


def read_invoice_audit(invoice_id: str) -> dict[str, Any]:
    """Everything recorded about one invoice: the invoice, its lines, import lineage (source bytes), match results,
    exceptions with assignment history, decisions, credits, export rows and the audit trail."""
    with db.transaction() as conn:
        inv = conn.execute("SELECT * FROM invoices WHERE invoice_id = %s", (invoice_id,)).fetchone()
        if inv is None:
            raise ApiError(404, "NOT_FOUND", "invoice not found", [detail("invoice_id", "INVOICE_UNKNOWN", "invoice not found")])

        def rows(sql: str, *args: Any) -> list[dict[str, Any]]:
            return [db.jsonable_row(r) for r in conn.execute(sql, args).fetchall()]

        data = {
            "invoice": db.jsonable_row(inv),
            "lines": rows("SELECT * FROM invoice_lines WHERE invoice_id = %s ORDER BY invoice_line_id", invoice_id),
            "lineage": rows("SELECT * FROM import_lineage WHERE invoice_id = %s OR merged_into = %s ORDER BY lineage_id", invoice_id, invoice_id),
            "match_results": rows("SELECT * FROM match_results WHERE invoice_id = %s ORDER BY invoice_line_id", invoice_id),
            "exceptions": rows("SELECT * FROM exceptions WHERE invoice_id = %s ORDER BY exception_id", invoice_id),
            "assignments": rows("SELECT a.* FROM exception_assignments a JOIN exceptions e USING (exception_id) "
                                "WHERE e.invoice_id = %s ORDER BY a.assignment_id", invoice_id),
            "approvals": rows("SELECT * FROM approvals WHERE invoice_id = %s ORDER BY decided_at, approval_id", invoice_id),
            "credit_notes": rows("SELECT * FROM credit_notes WHERE invoice_id = %s ORDER BY credit_id", invoice_id),
            "export_rows": rows("SELECT * FROM export_rows WHERE invoice_id = %s ORDER BY export_id", invoice_id),
            "audit": rows("SELECT * FROM audit_events WHERE invoice_id = %s ORDER BY occurred_at, event_id", invoice_id),
        }
        return {"data": data, "meta": meta(conn, {"invoice_id": invoice_id}, 1, None, _counts(conn)), "warnings": []}


def read_metrics(lo: str | None, hi: str | None, cutoff: str | None, group_by: str) -> dict[str, Any]:
    if group_by not in GROUPS:
        raise ApiError(422, "VALIDATION_FAILED", "unsupported group_by",
                       [detail("group_by", "INVALID_GROUP_BY", f"use one of {', '.join(GROUPS)}")])
    start, end = parse_window(lo, hi)
    with db.transaction() as conn:
        pop = db.load_population(conn)
        cutoffs = [parse_instant(c, "cutoff") for c in cutoff.split(",") if c] if cutoff else []
        try:
            out = window_metrics(pop, (start, end), cutoffs, group_by)
        except DomainError as err:
            raise from_domain(err, "from") from None
        cut = None if end is None else end - timedelta(microseconds=1)
        book = derive(pop, cut)
        data: dict[str, Any] = {"group_by": group_by, **out, "snapshot_cutoffs": [iso_z(c) for c in cutoffs],
                                "window": {"from": iso_z(start), "to": iso_z(end)}, "disclosures": disclosures(pop, book)}
        # the workflow state is stored by the commands; the metrics are derived from the facts: say where they differ
        warns = [{"code": "WORKFLOW_STATE_DIFFERS", "message": f"{r['invoice_id']} is stored as {r['status']} but the facts derive "
                  f"{book.status[r['invoice_id']]}", "path": f"invoices[{r['invoice_id']}]"}
                 for r in conn.execute("SELECT invoice_id, status FROM invoices WHERE validity IS NOT NULL OR status = 'merged' "
                                       "ORDER BY invoice_id").fetchall()
                 if r["status"] != book.status.get(r["invoice_id"]) and r["status"] not in ("valid", "invalid")][:50]
        applied = {"from": iso_z(start), "to": iso_z(end), "cutoff": [iso_z(c) for c in cutoffs], "group_by": group_by}
        total = sum(1 for i in pop.invoices if (start is None or i.imported_at >= start) and (end is None or i.imported_at < end))
        return {"data": data, "meta": meta(conn, applied, total, None, _counts(conn)), "warnings": warns}
