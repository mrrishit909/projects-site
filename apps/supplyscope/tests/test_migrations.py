"""Migrations are idempotent and the database enforces the immutability, receipt and status rules."""
import psycopg
import pytest

from data import migrate, seed

from support_db import conn, count, db_url, golden_inputs, seeded  # noqa: F401

FILES = ["0001_schema.sql", "0002_constraints.sql"]
TABLES = ["products", "locations", "suppliers", "calendar_closures", "cost_versions", "policy_scenarios", "purchase_orders",
          "purchase_order_lines", "receipts", "inventory_movements", "sales", "promotions", "latent_demand", "forecast_runs",
          "forecast_points", "backorders", "lost_sales", "reservations", "replenishment_params", "stock_snapshots",
          "draft_orders", "fixture_states", "raw_batches", "rejected_records", "quarantined_records", "audit_events",
          "command_results", "dataset_versions"]


def test_migrations_are_idempotent(db_url):
    with psycopg.connect(db_url) as c:
        assert migrate.apply_migrations(c) == []                      # the fixture already applied them
        migrate.reset(c)
        assert migrate.apply_migrations(c) == FILES
        assert migrate.apply_migrations(c) == []
    for name in FILES:                                                # each file also re-runs cleanly on its own
        with psycopg.connect(db_url) as c:
            c.execute((migrate.MIGRATIONS_DIR / name).read_text())


def test_every_table_exists_and_timestamps_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables "
                                                   "WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at' OR column_name IN ('as_of', 'cutoff')) "
                       "AND data_type <> 'timestamp with time zone'").fetchall()
    assert bad == []
    assert conn.execute("SELECT data_type FROM information_schema.columns WHERE table_name = 'products' "
                        "AND column_name = 'unit_cost'").fetchone()["data_type"] == "numeric"


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate.apply_migrations(c)


def test_seed_is_idempotent_and_keeps_rejected_rows(conn):
    first = seed.seed(conn, golden_inputs("variant-rejected"))
    assert first["skipped"] == 2 and first["inserted"]["inventory_movements"] == 7 and first["inserted"]["receipts"] == 0
    again = seed.seed(conn, golden_inputs("variant-rejected"))
    assert sum(again["inserted"].values()) == 0 and again["dataset_version"] == first["dataset_version"]
    assert count(conn, "inventory_movements") == 7 and count(conn, "rejected_records") == 2
    assert count(conn, "raw_batches") == 1 and count(conn, "dataset_versions") == 1 and count(conn, "fixture_states") == 2
    raw = conn.execute("SELECT raw_row FROM rejected_records WHERE id = 'mv-002'").fetchone()["raw_row"]
    assert raw["quantity_delta"] == -25


def test_p03_test_04_inventory_movements_are_immutable_and_unique(seeded):
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("UPDATE inventory_movements SET quantity_delta = 1")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("DELETE FROM inventory_movements")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("TRUNCATE inventory_movements")
    with pytest.raises(psycopg.errors.UniqueViolation):
        seeded.execute("INSERT INTO inventory_movements VALUES ('mv-001', 'prod-001', 'loc-001', 5, now(), 'receipt')")
    assert count(seeded, "inventory_movements") == 7
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO inventory_movements VALUES ('mv-x', 'prod-001', 'loc-001', 0, now(), 'receipt')")


def test_p03_test_11_receipt_rules_in_the_database(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO receipts VALUES ('r-0', 'pol-001', 'loc-001', 0, '2026-03-25T00:00:00Z')")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="RECEIPT_BEFORE_ORDER"):
        seeded.execute("INSERT INTO receipts VALUES ('r-1', 'pol-001', 'loc-001', 10, '2026-03-18T10:00:00Z')")
    seeded.execute("INSERT INTO receipts VALUES ('r-2', 'pol-001', 'loc-001', 10, '2026-03-25T10:00:00Z')")   # partial: fine
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="RECEIPT_EXCEEDS_ORDERED"):
        seeded.execute("INSERT INTO receipts VALUES ('r-3', 'pol-001', 'loc-001', 21, '2026-03-26T10:00:00Z')")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="its date cannot change"):
        seeded.execute("UPDATE purchase_orders SET ordered_at = '2026-03-30T00:00:00Z'")


def test_draft_orders_can_only_be_drafts_and_whole_packs(seeded):
    cols = ("INSERT INTO draft_orders (draft_order_id, as_of, product_id, location_id, inventory_position, reorder_point, "
            "target_position, raw_order, minimum_order_quantity, order_after_moq, pack_size, order_quantity, "
            "parameter_source, status) VALUES ('d1', now(), 'prod-001', 'loc-001', 60, 70, 120, 60, 50, 60, 24, %s, 'params', %s)")
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute(cols, (72, "ordered"))                       # never anything but a draft
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute(cols, (70, "draft"))                         # not a whole number of packs
    seeded.execute(cols, (72, "draft"))


def test_unmet_demand_is_a_backorder_xor_a_lost_sale(seeded):
    seeded.execute("INSERT INTO backorders (backorder_id, product_id, location_id, quantity, opened_at, demand_ref) "
                   "VALUES ('b1', 'prod-001', 'loc-001', 3, now(), 'ref-1')")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="UNMET_POLICY_CONFLICT"):
        seeded.execute("INSERT INTO lost_sales (lost_sale_id, product_id, location_id, quantity, occurred_at, demand_ref) "
                       "VALUES ('l1', 'prod-001', 'loc-001', 3, now(), 'ref-1')")


def test_scenario_policy_and_target_checks(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO policy_scenarios VALUES ('x', 'x', 0.95, 'both', 1, 0, 1)")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO policy_scenarios VALUES ('x', 'x', 1.5, 'backlog', 1, 0, 1)")
