"""Migrations and seed: empty database, second run, idempotent seed (docs/contracts.md D-02, D-04)."""
from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import dict_row
from support_db import GOLDEN, conn, count, db_url, golden_inputs, migrate, seed  # noqa: F401


def _tables(c) -> set[str]:
    return {r["table_name"] for r in c.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}


def test_migrate_from_empty_then_twice_gives_same_tables(db_url):
    with psycopg.connect(db_url, row_factory=dict_row) as c:
        migrate.reset(c)
        assert _tables(c) == set()
        first = migrate.apply_migrations(c)
        c.commit()
        tables = _tables(c)
        assert first == ["0001_schema.sql", "0002_constraints.sql", "0003_shipment_invariants.sql"]
        second = migrate.apply_migrations(c)
        c.commit()
        assert second == []
        assert _tables(c) == tables
        assert {"customers", "shipment_lines", "returns", "freight_allocations", "discount_allocations",
                "raw_batches", "rejected_records", "quarantined_records", "audit_events",
                "command_results", "dataset_versions", "schema_migrations"} <= tables
        versions = [r["version"] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == ["0001_schema.sql", "0002_constraints.sql", "0003_shipment_invariants.sql"]


def test_money_columns_are_numeric_20_6_and_versions_default(conn):
    row = conn.execute("SELECT numeric_precision, numeric_scale FROM information_schema.columns "
                       "WHERE table_name = 'order_lines' AND column_name = 'unit_price'").fetchone()
    assert (row["numeric_precision"], row["numeric_scale"]) == (20, 6)
    row = conn.execute("SELECT column_default, is_nullable FROM information_schema.columns "
                       "WHERE table_name = 'shipment_lines' AND column_name = 'version'").fetchone()
    assert row["column_default"] == "1" and row["is_nullable"] == "NO"
    row = conn.execute("SELECT is_nullable FROM information_schema.columns "
                       "WHERE table_name = 'shipment_lines' AND column_name = 'cost_version_id'").fetchone()
    assert row["is_nullable"] == "YES"


def test_seed_twice_keeps_same_counts_and_records_dataset_version(conn):
    data = golden_inputs(returns=True, costs=True)
    first = seed.seed(conn, data)
    counts = {t: count(conn, t) for t in ("customers", "products", "orders", "order_lines", "discounts",
                                          "shipments", "shipment_lines", "returns", "cost_versions",
                                          "exchange_rates", "dataset_versions")}
    assert counts["order_lines"] == 2 and counts["returns"] == 1 and counts["dataset_versions"] == 1
    second = seed.seed(conn, data)
    assert second["inserted"] == {k: 0 for k in second["inserted"]}
    assert first["dataset_hash"] == second["dataset_hash"]
    assert counts == {t: count(conn, t) for t in counts}
    row = conn.execute("SELECT * FROM dataset_versions").fetchone()
    assert len(row["dataset_hash"]) == 64 and row["contract_version"] == "v1.1"
    assert row["dataset_version"] == first["dataset_version"]


def test_returns_and_audit_events_are_append_only(conn):
    seed.seed(conn, golden_inputs(returns=True, costs=True))
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        conn.execute("UPDATE returns SET returned_quantity = 2")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        conn.execute("DELETE FROM returns")
