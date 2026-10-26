"""psycopg helpers: one connection and one transaction per request (D-06).

``transaction()`` commits when the block exits normally and rolls back on any exception,
so a command's effects and its audit event are atomic.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from revenue_atlas import CONTRACT_VERSION

Row = dict[str, Any]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect() -> psycopg.Connection[Row]:
    # UTC session so DATE/TIMESTAMPTZ comparisons never depend on the server's zone.
    return psycopg.connect(database_url(), row_factory=dict_row, options="-c timezone=UTC")


@contextmanager
def transaction() -> Iterator[psycopg.Connection[Row]]:
    """One transaction: commit on success, rollback on error, always close."""
    with _connect() as conn:
        yield conn


def money(value: Decimal) -> str:
    """Decimal string with at least two decimals and no padding zeros past them (D-02)."""
    text = format(value, "f")
    if "." not in text:
        return text + ".00"
    whole, frac = text.split(".")
    frac = frac.rstrip("0").ljust(2, "0")
    return f"{whole}.{frac}"


def jsonable(value: Any) -> Any:
    """Row value to JSON: Decimal as string, timestamps as UTC ISO-8601."""
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def jsonable_row(row: Row) -> Row:
    return {k: jsonable(v) for k, v in row.items()}


def load_batch(conn: psycopg.Connection[Row]) -> dict[str, Any]:
    """Assemble the domain's ``inputs.json`` shape from the tables (acceptable for the slice)."""
    def rows(sql: str) -> list[Row]:
        return [_plain(r) for r in conn.execute(sql).fetchall()]

    return {
        "contract": CONTRACT_VERSION,
        "customers": rows("SELECT customer_id, customer_name, region_id, segment, effective_from "
                          "FROM customers ORDER BY customer_id, effective_from"),
        "products": rows("SELECT product_id, sku, category_id, unit_of_measure, active "
                         "FROM products ORDER BY product_id"),
        "orders": rows("SELECT order_id, customer_id, order_date, currency, status "
                       "FROM orders ORDER BY order_id"),
        "order_lines": rows("SELECT line_id, order_id, product_id, quantity, unit_price "
                            "FROM order_lines ORDER BY line_id"),
        "discounts": rows("SELECT discount_id, line_id, discount_amount, reason_code, approved_by "
                          "FROM discounts ORDER BY discount_id"),
        "shipments": rows("SELECT shipment_id, order_id, shipped_at, shipping_cost, currency "
                          "FROM shipments ORDER BY shipment_id"),
        "shipment_lines": rows("SELECT shipment_line_id, shipment_id, line_id, shipped_quantity, "
                               "cost_version_id FROM shipment_lines ORDER BY shipment_line_id"),
        "returns": rows("SELECT return_id, shipment_line_id, returned_quantity, credit_amount, "
                        "credit_date FROM returns ORDER BY return_id"),
        "cost_versions": rows("SELECT cost_version_id, product_id, unit_cost, valid_from, valid_to "
                              "FROM cost_versions ORDER BY cost_version_id"),
        "exchange_rates": rows("SELECT rate_id, currency, reporting_currency, rate_date, rate "
                               "FROM exchange_rates ORDER BY rate_id"),
    }


def _plain(row: Row) -> Row:
    """Row for the domain parsers: money as plain decimal strings, dates as ISO strings."""
    out: Row = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = format(v, "f")
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
