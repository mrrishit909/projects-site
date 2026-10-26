"""Regression tests named after the master-18 reviewer findings R-01..R-08 (docs/contracts.md D-08, D-09).

Python domain, PostgreSQL and API halves; the TypeScript half is web/scripts/review-check.ts, which uses the same
fixtures (tests/fixtures/review/) and the same expected values.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import psycopg
import pytest
from api import db
from revenue_atlas.contract import UNALLOCATED_GROUP
from revenue_atlas.ingest import validate_batch
from revenue_atlas.metrics import group_metrics, monthly_metrics, region_key
from revenue_atlas.models import Return, ShipmentLine
from revenue_atlas.pipeline import run_pipeline
from revenue_atlas.returns import validate_return
from support_db import client, command, conn, count, db_url, golden_inputs, seed_db  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "review"
RECON = (ROOT / "data" / "sql" / "discount_reconciliation.sql").read_text()


def fixture(name: str) -> dict:
    return json.loads((FIX / f"in_{name}.json").read_text())


def tiny(qty: int = 2) -> dict:
    """One USD order line (qty x 10.00, 0.03 discount), no shipments yet."""
    return {
        "contract": "v1",
        "customers": [{"customer_id": "c1", "customer_name": "C", "region_id": "r1", "segment": "SMB",
                       "effective_from": "2025-01-01"}],
        "products": [{"product_id": "p1", "sku": "S1", "category_id": "k", "unit_of_measure": "each", "active": True},
                     {"product_id": "p2", "sku": "S2", "category_id": "k", "unit_of_measure": "each", "active": True}],
        "orders": [{"order_id": "o1", "customer_id": "c1", "order_date": "2026-03-08", "currency": "USD",
                    "status": "shipped"},
                   {"order_id": "o2", "customer_id": "c1", "order_date": "2026-03-08", "currency": "USD",
                    "status": "shipped"}],
        "order_lines": [{"line_id": "l1", "order_id": "o1", "product_id": "p1", "quantity": qty, "unit_price": "10.00"}],
        "discounts": [{"discount_id": "d1", "line_id": "l1", "discount_amount": "0.03", "reason_code": "X",
                       "approved_by": "m"}],
        "shipments": [], "shipment_lines": [], "returns": [],
        "cost_versions": [{"cost_version_id": "cv1", "product_id": "p1", "unit_cost": "4.00",
                           "valid_from": "2026-01-01", "valid_to": None}],
        "exchange_rates": [{"rate_id": "fx1", "currency": "USD", "reporting_currency": "USD",
                            "rate_date": "2026-01-01", "rate": "1.0"}],
    }


def ship(batch: dict, shipment_id: str, line_id: str, sl_id: str, qty: int, cost: str = "3.00",
         at: str = "2026-03-10T12:00:00Z", order_id: str = "o1") -> None:
    if not any(s["shipment_id"] == shipment_id for s in batch["shipments"]):
        batch["shipments"].append({"shipment_id": shipment_id, "order_id": order_id, "shipped_at": at,
                                   "shipping_cost": cost, "currency": "USD"})
    batch["shipment_lines"].append({"shipment_line_id": sl_id, "shipment_id": shipment_id, "line_id": line_id,
                                    "shipped_quantity": qty})


def rejected(batch: dict) -> list[tuple[str, str, str]]:
    return [(r.entity, r.id, r.reason_code) for r in validate_batch(batch).rejected]


# ---- R-01 ------------------------------------------------------------------------------------------------
def test_R01_domain_rejects_order_line_shipped_above_ordered_with_its_dependents():
    batch = fixture("over")  # L5: ordered 2, sl7 ships 3
    assert rejected(batch) == [("discounts", "d5", "SHIPPED_EXCEEDS_ORDERED"),
                               ("order_lines", "L5", "SHIPPED_EXCEEDS_ORDERED"),
                               ("shipment_lines", "sl7", "SHIPPED_EXCEEDS_ORDERED")]
    # a return of the rejected shipment line follows it
    batch["returns"].append({"return_id": "rX", "shipment_line_id": "sl7", "returned_quantity": 1,
                             "credit_amount": "1.00", "credit_date": "2026-03-12"})
    assert ("returns", "rX", "SHIPPED_EXCEEDS_ORDERED") in rejected(batch)
    # the metrics are exactly those of the same batch without the over-shipped line (no phantom discount)
    clean = fixture("over")
    for ent, key in (("order_lines", "L5"), ("discounts", "d5"), ("shipment_lines", "sl7")):
        clean[ent] = [r for r in clean[ent] if key not in r.values()]
    assert run_pipeline(fixture("over"), True).metrics == run_pipeline(clean, True).metrics


def test_R01_total_across_several_shipment_lines_counts_and_the_ordered_quantity_itself_is_fine():
    ok = tiny(2)
    ship(ok, "s1", "l1", "sl1", 1)
    ship(ok, "s2", "l1", "sl2", 1)
    assert rejected(ok) == []                       # 1 + 1 == ordered 2
    over = tiny(2)
    ship(over, "s1", "l1", "sl1", 1)
    ship(over, "s2", "l1", "sl2", 2)                # 1 + 2 > 2
    assert rejected(over) == [("discounts", "d1", "SHIPPED_EXCEEDS_ORDERED"),
                              ("order_lines", "l1", "SHIPPED_EXCEEDS_ORDERED"),
                              ("shipment_lines", "sl1", "SHIPPED_EXCEEDS_ORDERED"),
                              ("shipment_lines", "sl2", "SHIPPED_EXCEEDS_ORDERED")]


def test_R01_c01_rejects_over_shipment_and_database_trigger_guards_a_later_batch(client, conn):
    base = tiny(2)
    ship(base, "s1", "l1", "sl1", 2)
    first = command(client, "ingest-sales", {"batch": base})
    assert first.status_code == 200 and first.json()["status"] == "accepted"
    # batch 2 alone is valid for the domain (1 <= 2) but the database already holds 2 of 2: trigger -> 422
    later = {k: base[k] for k in ("customers", "products", "orders", "order_lines")}
    later.update(contract="v1", shipments=[], shipment_lines=[])
    ship(later, "s2", "l1", "sl2", 1)
    r = command(client, "ingest-sales", {"batch": later})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["details"][0]["rule_id"] == "SHIPPED_EXCEEDS_ORDERED"
    assert count(conn, "shipment_lines") == 1 and count(conn, "shipments") == 1   # whole transaction rolled back


def test_R01_c01_over_shipment_is_a_partial_ingest_with_the_raw_rows_kept(client, conn):
    batch = fixture("over")
    r = command(client, "ingest-sales", {"batch": batch})
    assert r.status_code == 200 and r.json()["status"] == "partial"
    assert {(x["entity"], x["id"], x["reason_code"]) for x in r.json()["result"]["rejected_records"]} == {
        ("discounts", "d5", "SHIPPED_EXCEEDS_ORDERED"), ("order_lines", "L5", "SHIPPED_EXCEEDS_ORDERED"),
        ("shipment_lines", "sl7", "SHIPPED_EXCEEDS_ORDERED")}
    assert conn.execute("SELECT count(*) AS n FROM shipment_lines WHERE shipment_line_id = 'sl7'").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM rejected_records WHERE reason_code = 'SHIPPED_EXCEEDS_ORDERED'"
                        ).fetchone()["n"] == 3


def test_R01_database_check_refuses_a_direct_over_shipment_and_a_quantity_cut_below_shipped(conn):
    base = tiny(2)
    ship(base, "s1", "l1", "sl1", 2)
    seed_db(conn, base)
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        conn.execute("INSERT INTO shipment_lines (shipment_line_id, shipment_id, line_id, shipped_quantity) "
                     "VALUES ('sl2', 's1', 'l1', 1)")
    assert exc.value.diag.constraint_name == "shipment_lines_shipped_le_ordered"
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE shipment_lines SET shipped_quantity = 3 WHERE shipment_line_id = 'sl1'")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE order_lines SET quantity = 1 WHERE line_id = 'l1'")
    # re-inserting the same row (seed is idempotent, ON CONFLICT DO NOTHING) must not count it twice
    seed_db(conn, base)
    assert count(conn, "shipment_lines") == 1


def test_R01_c03_cannot_return_more_than_shipped_or_ordered(client, conn):
    base = tiny(2)
    ship(base, "s1", "l1", "sl1", 2)
    assert command(client, "ingest-sales", {"batch": base}).status_code == 200
    ret = {"shipment_line_id": "sl1", "returned_quantity": 3, "credit_amount": "10.00",
           "credit_date": "2026-03-20", "expected_version": 1}
    r = command(client, "post-a-partial-return", ret)        # 3 > ordered 2 = shipped 2
    assert r.status_code == 422 and r.json()["error"]["details"][0]["rule_id"] == "RETURN_EXCEEDS_REMAINING"
    assert count(conn, "returns") == 0
    over = fixture("over")                                     # the rejected line's shipment line never exists to return against
    command(client, "ingest-sales", {"batch": over})
    r = command(client, "post-a-partial-return", {**ret, "shipment_line_id": "sl7", "returned_quantity": 1})
    assert r.status_code == 404


# ---- R-02 ------------------------------------------------------------------------------------------------
def test_R02_discount_allocations_equal_the_contract_split_across_two_c04_calls(client, conn):
    first_batch = tiny(2)                # 0.03 over quantity 2; the SECOND shipment's line has the LOWER id
    ship(first_batch, "s1", "l1", "sl-z", 1)
    assert command(client, "ingest-sales", {"batch": first_batch}).status_code == 200
    assert command(client, "resolve-historical-cost", {"shipment_id": "s1"}).status_code == 200
    first = command(client, "allocate-freight", {"shipment_id": "s1"})
    assert first.json()["result"]["discount_allocations"] == {"sl-z": "0.02"}     # round(0.03 x 1/2) while one line exists
    second_batch = {k: first_batch[k] for k in ("customers", "products", "orders", "order_lines")}
    second_batch.update(contract="v1", shipments=[], shipment_lines=[])
    ship(second_batch, "s2", "l1", "sl-a", 1, at="2026-03-11T12:00:00Z")
    assert command(client, "ingest-sales", {"batch": second_batch}).status_code == 200
    assert command(client, "resolve-historical-cost", {"shipment_id": "s2"}).status_code == 200
    second = command(client, "allocate-freight", {"shipment_id": "s2"})
    assert second.status_code == 200, second.text
    rows = {r["shipment_line_id"]: r["amount"] for r in conn.execute(
        "SELECT shipment_line_id, amount FROM discount_allocations").fetchall()}
    assert rows == {"sl-a": D("0.02"), "sl-z": D("0.01")}                          # before the fix: 0.02 + 0.02 = 0.04
    assert sum(rows.values()) == D("0.03")
    assert second.json()["result"]["discount_resplit_on_other_shipments"] == {"sl-z": "0.01"}
    contract = run_pipeline(db.load_batch(conn), True).discount_by_line
    assert {k: v for k, v in contract.items()} == rows
    assert conn.execute(RECON).fetchall() == []                                    # reconciliation query: no drift


def test_R02_reconciliation_query_flags_a_drifting_line(client, conn):
    batch = tiny(2)
    ship(batch, "s1", "l1", "sl-z", 1)
    ship(batch, "s2", "l1", "sl-a", 1, at="2026-03-11T12:00:00Z")
    assert command(client, "ingest-sales", {"batch": batch}).status_code == 200
    conn.execute("INSERT INTO discount_allocations (shipment_line_id, line_id, amount) VALUES ('sl-z', 'l1', 0.02), "
                 "('sl-a', 'l1', 0.02)")                    # the pre-fix state
    drift = conn.execute(RECON).fetchall()
    assert [(r["line_id"], r["expected_allocated"], r["stored_allocated"], r["drift"]) for r in drift] == [
        ("l1", D("0.03"), D("0.04"), D("0.01"))]


# ---- R-08 ------------------------------------------------------------------------------------------------
def _two_line_shipment() -> dict:
    batch = tiny(2)
    batch["order_lines"].append({"line_id": "l2", "order_id": "o1", "product_id": "p2", "quantity": 3,
                                 "unit_price": "10.00"})  # p2 has no cost version: COST_VERSION_MISSING
    batch["discounts"] = []
    ship(batch, "s1", "l1", "sl1", 2, cost="9.00")
    ship(batch, "s1", "l2", "sl2", 3, cost="9.00")
    return batch


def test_R08_c04_allocates_freight_only_over_lines_not_quarantined_and_respreads_after_unquarantine(client, conn):
    assert command(client, "ingest-sales", {"batch": _two_line_shipment()}).status_code == 200
    c02 = command(client, "resolve-historical-cost", {"shipment_id": "s1"}).json()
    assert {o["shipment_line_id"]: o.get("reason_code") for o in c02["result"]["lines"]}["sl2"] == "COST_VERSION_MISSING"
    first = command(client, "allocate-freight", {"shipment_id": "s1"})
    assert first.status_code == 200 and first.json()["status"] == "allocated"
    assert first.json()["result"]["allocations"] == {"sl1": "9.00"}               # before the fix: 3.60 + 5.40
    assert first.json()["result"]["skipped_lines"] == {"sl2": "COST_VERSION_MISSING"}
    pipeline = run_pipeline(db.load_batch(conn), True)
    assert {k: str(v) for k, v in pipeline.freight_by_line.items()} == {"sl1": "9.00"}
    assert str(sum(pipeline.freight_by_line.values())) == "9.00" and pipeline.metrics["shipping_cost"] == "9.00"
    stored = {r["shipment_line_id"]: r["amount"] for r in conn.execute("SELECT * FROM freight_allocations").fetchall()}
    assert stored == {"sl1": D("9.00")}
    # an identical re-run is still the double allocation guard (P01-TEST-01)
    again = command(client, "allocate-freight", {"shipment_id": "s1"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "FREIGHT_ALREADY_ALLOCATED"
    # the missing cost version arrives: C02 un-quarantines sl2, C04 re-spreads (upsert) over both lines
    fix = {"contract": "v1", "cost_versions": [{"cost_version_id": "cv2", "product_id": "p2", "unit_cost": "5.00",
                                                "valid_from": "2026-01-01", "valid_to": None}]}
    assert command(client, "ingest-sales", {"batch": fix}).status_code == 200
    assert command(client, "resolve-historical-cost", {"shipment_id": "s1"}).status_code == 200
    spread = command(client, "allocate-freight", {"shipment_id": "s1"})
    assert spread.status_code == 200 and spread.json()["status"] == "reallocated", spread.text
    assert [w["code"] for w in spread.json()["warnings"]] == ["FREIGHT_RESPREAD"]
    pipeline = run_pipeline(db.load_batch(conn), True)
    stored = {r["shipment_line_id"]: r["amount"] for r in conn.execute("SELECT * FROM freight_allocations").fetchall()}
    assert stored == {k: v for k, v in pipeline.freight_by_line.items()} == {"sl1": D("3.60"), "sl2": D("5.40")}
    assert sum(stored.values()) == D("9.00")


def test_R08_stale_row_of_a_line_that_became_quarantined_is_removed_on_respread(client, conn):
    batch = _two_line_shipment()
    batch["cost_versions"].append({"cost_version_id": "cv2", "product_id": "p2", "unit_cost": "5.00",
                                   "valid_from": "2026-01-01", "valid_to": None})
    assert command(client, "ingest-sales", {"batch": batch}).status_code == 200
    assert command(client, "allocate-freight", {"shipment_id": "s1"}).status_code == 200
    assert count(conn, "freight_allocations") == 2
    conn.execute("INSERT INTO cost_versions (cost_version_id, product_id, unit_cost, valid_from) "
                 "VALUES ('cv3', 'p2', 6, '2026-02-01')")       # overlaps cv2: sl2 is now COST_VERSION_AMBIGUOUS
    res = command(client, "allocate-freight", {"shipment_id": "s1"})
    assert res.status_code == 200 and res.json()["status"] == "reallocated"
    assert {r["shipment_line_id"]: r["amount"] for r in conn.execute("SELECT * FROM freight_allocations").fetchall()} \
        == {"sl1": D("9.00")}


# ---- R-06 ------------------------------------------------------------------------------------------------
def test_R06_domain_rejects_a_shipment_line_whose_order_line_belongs_to_another_order():
    batch = fixture("cross")             # sl9 sits on shipment S1 (order o1) but points at line L4 (order o2)
    assert rejected(batch) == [("shipment_lines", "sl9", "SHIPMENT_LINE_ORDER_MISMATCH")]
    batch["returns"].append({"return_id": "rY", "shipment_line_id": "sl9", "returned_quantity": 1,
                             "credit_amount": "1.00", "credit_date": "2026-03-12"})
    assert ("returns", "rY", "SHIPMENT_LINE_ORDER_MISMATCH") in rejected(batch)
    # the mismatched line is not counted against the quantity of the line it points at (L4 ordered 2, sl5 ships 2)
    assert not any(code == "SHIPPED_EXCEEDS_ORDERED" for _, _, code in rejected(batch))
    # metrics: exactly the batch without that line
    clean = fixture("cross")
    clean["shipment_lines"] = [r for r in clean["shipment_lines"] if r["shipment_line_id"] != "sl9"]
    assert run_pipeline(fixture("cross"), True).metrics == run_pipeline(clean, True).metrics


def test_R06_c01_and_database_trigger_refuse_the_cross_order_line(client, conn):
    r = command(client, "ingest-sales", {"batch": fixture("cross")})
    assert r.status_code == 200 and r.json()["status"] == "partial"
    assert [(x["id"], x["reason_code"]) for x in r.json()["result"]["rejected_records"]] == [
        ("sl9", "SHIPMENT_LINE_ORDER_MISMATCH")]
    assert conn.execute("SELECT count(*) AS n FROM shipment_lines WHERE shipment_line_id = 'sl9'").fetchone()["n"] == 0
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        conn.execute("INSERT INTO shipment_lines (shipment_line_id, shipment_id, line_id, shipped_quantity) "
                     "VALUES ('sl9', 'S1', 'L4', 0)")
    assert exc.value.diag.constraint_name == "shipment_lines_order_match"


# ---- R-07 ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("zero", ["-0.00", "-0", "-0.0000"])
def test_R07_negative_zero_credit_is_credit_sign_reversed(zero):
    line = ShipmentLine("sl", "s", "l", 2)
    with pytest.raises(Exception) as exc:
        validate_return(line, [], 1, D(zero))
    assert getattr(exc.value, "code", None) == "CREDIT_SIGN_REVERSED"
    validate_return(line, [], 1, D("0.00"))          # a plain zero credit stays acceptable
    batch = golden_inputs(returns=True)
    batch["returns"][0]["credit_amount"] = zero
    assert rejected(batch) == [("returns", "ret-001", "CREDIT_SIGN_REVERSED")]
    assert run_pipeline(batch, True).metrics["merchandise_credits"] == "0.00"


def test_R07_c03_refuses_negative_zero_credit(client, conn):
    seed_db(conn, golden_inputs())
    ret = {"shipment_line_id": "sl-001", "returned_quantity": 1, "credit_amount": "-0.00",
           "credit_date": "2026-03-20", "expected_version": 1}
    r = command(client, "post-a-partial-return", ret)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["rule_id"] == "CREDIT_SIGN_REVERSED"
    assert count(conn, "returns") == 0
    ok = command(client, "post-a-partial-return", {**ret, "credit_amount": "0.00"})
    assert ok.status_code == 200


# ---- R-03 ------------------------------------------------------------------------------------------------
def test_R03_grouped_shipping_cost_includes_the_unallocated_group():
    res = run_pipeline(fixture("unalloc"), True)
    overall = res.metrics
    assert overall["shipping_cost"] == "36.25" and res.unallocated_freight == D("5.00")
    keys = {"region": region_key, "customer": lambda f: f.customer_id, "product": lambda f: f.product_id,
            "month": lambda f: f.shipped_at.strftime("%Y-%m")}
    for name, key in keys.items():
        groups = group_metrics(res.facts, key, returns=res.returns, unallocated_freight=res.unallocated_freight)
        assert UNALLOCATED_GROUP in groups, name
        u = groups[UNALLOCATED_GROUP]
        assert (u["shipping_cost"], u["contribution_margin"], u["gross_sales"]) == ("5.00", "-5.00", "0.00"), name
        assert sum(D(g["shipping_cost"]) for g in groups.values()) == D(overall["shipping_cost"]), name
        # contribution adds up to the overall one up to the R-05 cent drift of per-group rounding after FX
        assert abs(sum(D(g["contribution_margin"]) for g in groups.values()) - D(overall["contribution_margin"])) <= D("0.02")
        assert list(groups) == sorted(groups)
    without = group_metrics(res.facts, region_key, returns=res.returns)
    assert UNALLOCATED_GROUP not in without and sum(D(g["shipping_cost"]) for g in without.values()) == D("31.25")


# ---- R-04 (the monthly rule; the views are checked in web/scripts/review-check.ts and the e2e) -------------
def test_R04_monthly_metrics_put_a_credit_in_its_credit_month():
    batch = golden_inputs(returns=True)
    batch["returns"][0]["credit_date"] = "2026-04-05"       # shipped 2026-03-10, credited a month later
    res = run_pipeline(batch, True)
    months = monthly_metrics(res.facts, res.returns)
    assert list(months) == ["2026-03", "2026-04"]
    assert (months["2026-03"]["gross_sales"], months["2026-03"]["merchandise_credits"]) == ("250.00", "0.00")
    assert (months["2026-04"]["gross_sales"], months["2026-04"]["merchandise_credits"],
            months["2026-04"]["net_merchandise_sales"]) == ("0.00", "90.00", "-90.00")
    for key in ("merchandise_credits", "net_merchandise_sales", "contribution_margin", "cogs"):
        assert sum(D(m[key]) for m in months.values()) == D(res.metrics[key]), key
    # grouping facts by shipment month with the returns (the pre-fix views) books the credit in March
    by_ship = group_metrics(res.facts, lambda f: f.shipped_at.strftime("%Y-%m"), returns=res.returns)
    assert by_ship["2026-03"]["merchandise_credits"] == "90.00"
    # a window narrower than the months applies to both selections
    w = (datetime(2026, 4, 1, tzinfo=timezone.utc), datetime(2026, 4, 10, tzinfo=timezone.utc))
    assert list(monthly_metrics(res.facts, res.returns, w)) == ["2026-04"]
