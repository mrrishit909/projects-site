"""data/sql/reference_metrics.sql recomputes the golden metrics independently of the Python domain."""
from pathlib import Path

import pytest

from data import seed
from supplyscope import run_pipeline

from support_db import AS_OF, conn, db_url, golden_expected, golden_inputs, seeded  # noqa: F401

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
START = "2026-03-01T00:00:00Z"


def reference(conn, as_of=AS_OF, start=START, end=None):
    return conn.execute(SQL, {"as_of": as_of, "window_start": start, "window_end": end}).fetchone()


def test_sql_equals_golden_key_by_key(seeded):
    want = golden_expected()["states"]["golden"]["metrics"]
    row = reference(seeded)
    assert set(row) == set(want)
    for k, v in want.items():
        assert row[k] == v and type(row[k]) is type(v), k


def test_sql_equals_golden_position_80(seeded):
    line = golden_inputs()["states"]["position_80"]["add_purchase_order_lines"][0]
    seeded.execute("INSERT INTO purchase_order_lines VALUES (%s, %s, %s, %s, %s)", tuple(line.values()))
    want = golden_expected()["states"]["position_80"]["metrics"]
    row = reference(seeded)
    for k, v in want.items():
        assert row[k] == v, k


def test_sql_empty_variant_has_nulls_for_the_unevaluated_fields(conn):
    seed.seed(conn, golden_inputs("variant-empty"))
    want = golden_expected("variant-empty")["states"]["empty"]["metrics"]
    row = reference(conn)
    for k, v in want.items():
        assert row[k] == v, k


def test_sql_agrees_with_the_domain_on_the_variants(conn):
    seed.seed(conn, golden_inputs("variant-rejected"))
    row = reference(conn)
    dom = run_pipeline(golden_inputs("variant-rejected"), "golden").metrics
    assert dict(row) == dom


def test_sql_day_order_and_cutoff(seeded):
    row = reference(seeded)
    assert (row["running_stock_min"], row["timestamp_order_stock_min"], row["negative_stock"]) == (0, -35, False)
    later = reference(seeded, as_of="2026-04-03T00:00:00Z")      # the sale of 10 on 04-02 is now inside the cutoff
    assert later["on_hand"] == 30 and later["working_capital"] == "375.00"
    before = reference(seeded, as_of="2026-03-12T10:00:00Z")      # the receipt of 15:00 is not yet posted
    assert before["on_hand"] == 0 and before["negative_stock"] is True and before["running_stock_min"] == -35


def test_sql_agrees_with_the_domain_on_moq_and_pack_rounding(seeded):
    """raw 20, MOQ 50, pack 24 -> 72, as SQL expressions."""
    seeded.execute("UPDATE replenishment_params SET reorder_point = 150, target_position = 80")
    row = reference(seeded)
    assert (row["inventory_position"], row["raw_order"], row["order_after_moq"], row["order_quantity"]) == (60, 20, 50, 72)
    seeded.execute("UPDATE products SET minimum_order_quantity = 0")
    assert reference(seeded)["order_after_moq"] == 20 and reference(seeded)["order_quantity"] == 24


def test_sql_values_each_day_at_the_cost_in_force(seeded):
    seeded.execute("INSERT INTO cost_versions VALUES ('cv1', 'prod-001', 20.00, '2026-03-20T00:00:00Z')")
    assert reference(seeded, as_of="2026-03-19T23:59:59Z")["working_capital"] == "500.00"
    assert reference(seeded)["working_capital"] == "800.00"
