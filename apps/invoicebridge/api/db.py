"""psycopg helpers: one connection and one transaction per request.

``transaction()`` commits when the block exits normally and rolls back on any exception, so a command's
effects and its audit event are atomic.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from invoicebridge.models import Population
from invoicebridge.timeutil import iso_z
from psycopg.rows import dict_row

Row = dict[str, Any]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect(autocommit: bool = False) -> psycopg.Connection[Row]:
    # UTC session so TIMESTAMPTZ comparisons never depend on the server's zone.
    return psycopg.connect(database_url(), row_factory=dict_row, options="-c timezone=UTC", autocommit=autocommit)


@contextmanager
def transaction() -> Iterator[psycopg.Connection[Row]]:
    """One transaction: commit on success, rollback on error, always close."""
    with _connect() as conn:
        yield conn


@contextmanager
def autocommit() -> Iterator[psycopg.Connection[Row]]:
    """A separate connection whose statements commit at once: used to keep a refusal or a rejected record when the
    command's own transaction is about to be rolled back."""
    with _connect(True) as conn:
        yield conn


def jsonable(value: Any) -> Any:
    """Row value to JSON: Decimal exactly as stored (money keeps 2 dp, quantities 4), timestamps as UTC ISO-8601 with Z."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def jsonable_row(row: Row) -> Row:
    return {k: jsonable(v) for k, v in row.items()}


_ROWS = {
    "vendors": "SELECT * FROM vendors ORDER BY vendor_id",
    "purchase_orders": "SELECT * FROM purchase_orders ORDER BY po_id",
    "po_lines": "SELECT * FROM po_lines ORDER BY po_line_id",
    "receipts": "SELECT * FROM receipts ORDER BY receipt_id",
    "invoices": "SELECT * FROM invoices ORDER BY invoice_id",
    "invoice_lines": "SELECT * FROM invoice_lines ORDER BY invoice_line_id",
    "credit_notes": "SELECT * FROM credit_notes ORDER BY credit_id",
    "approval_policies": "SELECT * FROM approval_policies ORDER BY policy_id",
    "approvals": "SELECT * FROM approvals ORDER BY approval_id",
    "export_requests": "SELECT * FROM export_requests ORDER BY request_seq",
    # resolved rows first, so the current (open or assigned) record of a pair is the one the domain keeps
    "exceptions": "SELECT * FROM exceptions ORDER BY (status <> 'resolved'), created_at, exception_id",
    "exception_assignments": "SELECT * FROM exception_assignments ORDER BY assignment_id",
}


def load_population(conn: psycopg.Connection[Row]) -> Population:
    """Assemble the domain's population from the tables (rows are trusted; the same parsers as ingest run over them)."""
    rows = {ent: [dict(r) for r in conn.execute(sql).fetchall()] for ent, sql in _ROWS.items()}
    for r in rows["invoices"]:
        r["invoice_date"] = r["invoice_date"].isoformat()
    t = conn.execute("SELECT price_per_unit, rounding_per_line, rounding_per_invoice FROM tolerances WHERE id = 1").fetchone()
    return Population.from_rows(rows, None if t is None else {k: format(v, "f") for k, v in t.items()})
