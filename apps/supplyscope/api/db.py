"""psycopg helpers: one connection and one transaction per request.

``transaction()`` commits when the block exits normally and rolls back on any exception, so a command's effects and its
audit event are atomic.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from supplyscope.models import Population, iso_z

Row = dict[str, Any]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect() -> psycopg.Connection[Row]:
    # UTC session so TIMESTAMPTZ comparisons never depend on the server's zone.
    return psycopg.connect(database_url(), row_factory=dict_row, options="-c timezone=UTC")


@contextmanager
def transaction() -> Iterator[psycopg.Connection[Row]]:
    """One transaction: commit on success, rollback on error, always close."""
    with _connect() as conn:
        yield conn


def jsonable(value: Any) -> Any:
    """Row value to JSON: Decimal as a plain string, timestamps as UTC ISO-8601 with Z."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def jsonable_row(row: Row) -> Row:
    return {k: jsonable(v) for k, v in row.items()}


_ROWS = {
    "products": "SELECT * FROM products ORDER BY product_id",
    "locations": "SELECT * FROM locations ORDER BY location_id",
    "sales": "SELECT * FROM sales ORDER BY sale_id",
    "inventory_movements": "SELECT * FROM inventory_movements ORDER BY movement_id",
    "purchase_orders": "SELECT * FROM purchase_orders ORDER BY purchase_order_id",
    "purchase_order_lines": "SELECT * FROM purchase_order_lines ORDER BY po_line_id",
    "receipts": "SELECT * FROM receipts ORDER BY receipt_id",
    "suppliers": "SELECT * FROM suppliers ORDER BY supplier_id",
    "promotions": "SELECT * FROM promotions ORDER BY promotion_id",
    "policy_scenarios": "SELECT * FROM policy_scenarios ORDER BY scenario_id",
    "backorders": "SELECT * FROM backorders ORDER BY backorder_id",
    "reservations": "SELECT * FROM reservations ORDER BY reservation_id",
    "replenishment_params": "SELECT * FROM replenishment_params ORDER BY product_id, location_id",
    "cost_versions": "SELECT * FROM cost_versions ORDER BY cost_version_id",
    "lost_sales": "SELECT * FROM lost_sales ORDER BY lost_sale_id",
    "calendar_closures": "SELECT * FROM calendar_closures ORDER BY closure_id",
    "latent_demand": "SELECT * FROM latent_demand ORDER BY product_id, location_id, demand_date",
}


def load_population(conn: psycopg.Connection[Row]) -> Population:
    """Assemble the domain's population from the tables (rows are trusted: the database enforced the rules)."""
    return Population.from_rows({ent: [dict(r) for r in conn.execute(sql).fetchall()] for ent, sql in _ROWS.items()})


def dataset_version(conn: psycopg.Connection[Row]) -> str:
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC "
                       "LIMIT 1").fetchone()
    return row["dataset_version"] if row else "unversioned"
