"""data/sql/reference_totals.sql (plain SQL, no Python domain) against the golden expectations.

Contract: docs/contracts.md D-01..D-05. The SQL carries its own largest-remainder logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from revenue_atlas import run_pipeline
from support_db import (ROOT, client, command, conn, count, db_url, expected, golden_inputs,  # noqa: F401
                        seed_db)

SQL = (ROOT / "data" / "sql" / "reference_totals.sql").read_text()
KEYS = ("gross_sales", "allocated_discounts", "merchandise_credits", "net_merchandise_sales", "cogs",
        "recoverable_return_cost", "gross_profit", "shipping_cost", "contribution_margin",
        "allocation_residual")


def sql_totals(conn, lo: datetime | None = None, hi: datetime | None = None) -> dict[str, Any]:
    return dict(conn.execute(SQL, {"lo": lo, "hi": hi}).fetchone())


def _prepare_shp001(client) -> None:
    assert command(client, "resolve-historical-cost", {"shipment_id": "shp-001"}).status_code == 200
    assert command(client, "allocate-freight", {"shipment_id": "shp-001"}).status_code == 200


def test_sql_reference_matches_golden_baseline_and_after_return(client, conn):
    seed_db(conn, golden_inputs())
    _prepare_shp001(client)

    base = expected()["states"]["baseline"]["metrics"]
    got = sql_totals(conn)
    assert set(got) == set(KEYS)
    for key in KEYS:
        assert got[key] == base[key], key

    seq = command(client, "post-a-partial-return",
                  {"shipment_line_id": "sl-001", "returned_quantity": 1, "credit_amount": "90.00",
                   "credit_date": "2026-03-20", "expected_version": 1})
    assert seq.status_code == 200, seq.text
    after = expected()["states"]["after_return"]["metrics"]
    got = sql_totals(conn)
    for key in KEYS:
        assert got[key] == after[key], key
    # Spot-check the headline numbers from CALCULATION.md.
    assert (got["net_merchandise_sales"], got["cogs"], got["contribution_margin"]) == \
        ("135.00", "80.00", "40.00")


def test_sql_reference_window_is_half_open_on_shipped_at(client, conn):
    seed_db(conn, golden_inputs())
    _prepare_shp001(client)
    shipped = datetime(2026, 3, 10, 14, 30, tzinfo=timezone.utc)
    assert sql_totals(conn, lo=shipped)["gross_sales"] == "250.00"          # from is inclusive
    assert sql_totals(conn, hi=shipped)["gross_sales"] == "0.00"            # to is exclusive
    empty = sql_totals(conn, lo=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert all(v == "0.00" for v in empty.values())


def test_sql_reference_excludes_lines_without_a_cost_version(client, conn):
    seed_db(conn, golden_inputs())  # C02 not run: every line is still uncosted (quarantine-equivalent)
    assert sql_totals(conn)["gross_sales"] == "0.00"


def test_sql_reference_largest_remainder_matches_domain_on_split_amounts(client, conn):
    """Thirds force remainder cents: SQL and the Python domain must agree to the cent."""
    batch = golden_inputs()
    batch["order_lines"] = [{"line_id": "line-001", "order_id": "ord-001", "product_id": "prod-001",
                             "quantity": 3, "unit_price": "33.33"},
                            {"line_id": "line-002", "order_id": "ord-001", "product_id": "prod-002",
                             "quantity": 1, "unit_price": "7.77"}]
    batch["discounts"] = [{"discount_id": "d1", "line_id": "line-001", "discount_amount": "10.00",
                           "reason_code": "VOLUME", "approved_by": "m"}]
    batch["shipments"] = [{"shipment_id": "shp-a", "order_id": "ord-001", "shipped_at": "2026-03-10T10:00:00Z",
                           "shipping_cost": "10.00", "currency": "USD"},
                          {"shipment_id": "shp-b", "order_id": "ord-001", "shipped_at": "2026-03-11T10:00:00Z",
                           "shipping_cost": "0.07", "currency": "USD"}]
    batch["shipment_lines"] = [
        {"shipment_line_id": "s-a1", "shipment_id": "shp-a", "line_id": "line-001", "shipped_quantity": 1},
        {"shipment_line_id": "s-a2", "shipment_id": "shp-a", "line_id": "line-002", "shipped_quantity": 1},
        {"shipment_line_id": "s-b1", "shipment_id": "shp-b", "line_id": "line-001", "shipped_quantity": 2}]
    seed_db(conn, batch)
    for shp in ("shp-a", "shp-b"):
        assert command(client, "resolve-historical-cost", {"shipment_id": shp}).status_code == 200
    got = sql_totals(conn)
    want = run_pipeline(batch, include_returns=False).metrics
    for key in KEYS:
        assert got[key] == want[key], key
    assert got["allocated_discounts"] == "10.00" and got["allocation_residual"] == "0.00"
