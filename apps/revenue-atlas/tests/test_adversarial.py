"""Adversarial cases P01-TEST-01, -03, -06, -09, -10 against the app and PostgreSQL (D-03, D-04, D-06)."""
from __future__ import annotations

import psycopg
import pytest
from support_db import HEADERS, PREFIX, client, command, conn, count, db_url, golden_inputs, seed_db  # noqa: F401

RET = {"shipment_line_id": "sl-001", "returned_quantity": 1, "credit_amount": "90.00",
       "credit_date": "2026-03-20", "expected_version": 1}


def test_P01_TEST_01_double_allocation_is_detected_by_key_and_recovered_by_idempotent_rerun(client, conn, monkeypatch):
    seed_db(conn, golden_inputs())
    first = command(client, "allocate-freight", {"shipment_id": "shp-001"}, key="alloc-1")
    assert first.status_code == 200
    stored = conn.execute("SELECT shipment_line_id, amount::text FROM freight_allocations "
                          "ORDER BY shipment_line_id").fetchall()
    assert [(r["shipment_line_id"], r["amount"]) for r in stored] == [("sl-001", "12.000000"), ("sl-002", "3.000000")]

    # (a) the database itself refuses a second row for the same shipment line.
    with pytest.raises(psycopg.errors.UniqueViolation) as exc:
        conn.execute("INSERT INTO freight_allocations (shipment_line_id, shipment_id, amount) "
                     "VALUES ('sl-001', 'shp-001', 12)")
    assert exc.value.diag.constraint_name == "freight_allocations_pkey"

    # (b) a second command with a DIFFERENT key is a 409 with no partial write.
    audits = count(conn, "audit_events")
    second = command(client, "allocate-freight", {"shipment_id": "shp-001"}, key="alloc-2")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "FREIGHT_ALREADY_ALLOCATED"
    assert second.json()["error"]["details"][0]["rule_id"] == "FREIGHT_ALREADY_ALLOCATED"
    assert count(conn, "freight_allocations") == 2 and count(conn, "audit_events") == audits
    assert count(conn, "command_results") == 1                     # the failed key is not recorded

    # (c) even when the application pre-check is bypassed, the PRIMARY KEY stops it and the
    #     409 is returned with the whole transaction rolled back (no discount_allocations either).
    from api import commands
    conn.execute("DELETE FROM discount_allocations")
    monkeypatch.setattr(commands, "_already_allocated", lambda c, ids: [])
    third = command(client, "allocate-freight", {"shipment_id": "shp-001"}, key="alloc-3")
    assert third.status_code == 409 and third.json()["error"]["code"] == "FREIGHT_ALREADY_ALLOCATED"
    assert count(conn, "freight_allocations") == 2 and count(conn, "discount_allocations") == 0
    monkeypatch.undo()

    # (d) recovery: re-running the ORIGINAL request (same key) returns the same allocations.
    rerun = command(client, "allocate-freight", {"shipment_id": "shp-001"}, key="alloc-1")
    assert rerun.status_code == 200 and rerun.headers["Idempotent-Replay"] == "true"
    assert rerun.json() == first.json()
    assert rerun.json()["result"]["allocations"] == {"sl-001": "12.00", "sl-002": "3.00"}
    assert count(conn, "freight_allocations") == 2


def test_P01_TEST_03_overlapping_cost_versions_quarantine_then_fixing_valid_to_recovers(client, conn):
    data = golden_inputs()
    data["cost_versions"].append({"cost_version_id": "cv-003", "product_id": "prod-001", "unit_cost": "65.00",
                                  "valid_from": "2026-02-01", "valid_to": None})   # overlaps cv-001
    seed_db(conn, data)
    r = command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    assert r.status_code == 200 and r.json()["status"] == "partial"
    outcomes = {o["shipment_line_id"]: o for o in r.json()["result"]["lines"]}
    assert outcomes["sl-001"]["outcome"] == "quarantined"
    assert outcomes["sl-001"]["reason_code"] == "COST_VERSION_AMBIGUOUS"
    assert outcomes["sl-002"]["cost_version_id"] == "cv-002"
    assert [w["code"] for w in r.json()["warnings"]] == ["COST_VERSION_AMBIGUOUS"]
    q = conn.execute("SELECT id, reason_code, raw_row FROM quarantined_records").fetchall()
    assert [(x["id"], x["reason_code"]) for x in q] == [("sl-001", "COST_VERSION_AMBIGUOUS")]
    assert q[0]["raw_row"]["details"]["cost_version_ids"] == ["cv-001", "cv-003"]
    assert conn.execute("SELECT cost_version_id FROM shipment_lines WHERE shipment_line_id='sl-001'"
                        ).fetchone()["cost_version_id"] is None
    # The metrics read drops the quarantined line and says so.
    m = client.get(f"{PREFIX}/metrics").json()
    assert m["data"]["metrics"]["gross_sales"] == "50.00"
    assert m["meta"]["exclusions"]["quarantined"] == {"shipment_lines": 1}
    assert [w["code"] for w in m["warnings"]] == ["QUARANTINED_RECORDS_EXCLUDED"]

    # Fix the data (close cv-001 where cv-003 begins) and run C02 again.
    conn.execute("UPDATE cost_versions SET valid_to = '2026-02-01' WHERE cost_version_id = 'cv-001'")
    fixed = command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    assert fixed.status_code == 200 and fixed.json()["status"] == "completed"
    assert fixed.json()["result"]["counts"] == {"resolved": 1, "unchanged": 1, "quarantined": 0}
    assert conn.execute("SELECT cost_version_id FROM shipment_lines WHERE shipment_line_id='sl-001'"
                        ).fetchone()["cost_version_id"] == "cv-003"
    assert count(conn, "quarantined_records") == 0
    m = client.get(f"{PREFIX}/metrics").json()
    assert m["data"]["metrics"]["gross_sales"] == "250.00" and m["warnings"] == []


def test_P01_TEST_03_missing_cost_version_is_quarantined_as_missing(client, conn):
    data = golden_inputs()
    data["cost_versions"][0]["valid_from"] = "2026-04-01"            # nothing covers 2026-03-10
    seed_db(conn, data)
    r = command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    assert r.json()["status"] == "partial"
    assert r.json()["warnings"][0]["code"] == "COST_VERSION_MISSING"
    repeat = command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    assert repeat.json()["status"] == "partial" and count(conn, "quarantined_records") == 1


def test_P01_TEST_06_negative_credit_is_rejected(client, conn):
    seed_db(conn, golden_inputs())
    r = command(client, "post-a-partial-return", {**RET, "credit_amount": "-90.00"})
    assert r.status_code == 422
    d = r.json()["error"]["details"][0]
    assert (d["path"], d["rule_id"]) == ("input.credit_amount", "CREDIT_SIGN_REVERSED")
    assert count(conn, "returns") == 0 and count(conn, "audit_events") == 0
    assert conn.execute("SELECT version FROM shipment_lines WHERE shipment_line_id='sl-001'").fetchone()["version"] == 1
    # The database constraint backs the rule up if anything bypasses the API.
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO returns VALUES ('ret-x', 'sl-001', 1, -1, '2026-03-20')")
    # Garbage amounts are 422 as well, never a 500.
    for bad in ("abc", "NaN", "Infinity", ""):
        assert command(client, "post-a-partial-return", {**RET, "credit_amount": bad}).status_code == 422, bad
    assert command(client, "post-a-partial-return", {**RET, "credit_amount": 90}).status_code == 422


def test_P01_TEST_09_cancelled_order_has_no_facts(client, conn):
    data = golden_inputs()
    data["orders"].append({"order_id": "ord-009", "customer_id": "cust-001", "order_date": "2026-03-09",
                           "currency": "USD", "status": "cancelled"})
    data["order_lines"].append({"line_id": "line-009", "order_id": "ord-009", "product_id": "prod-001",
                                "quantity": 5, "unit_price": "100.00"})
    data["shipments"].append({"shipment_id": "shp-009", "order_id": "ord-009",
                              "shipped_at": "2026-03-10T09:00:00Z", "shipping_cost": "9.00", "currency": "USD"})
    data["shipment_lines"].append({"shipment_line_id": "sl-009", "shipment_id": "shp-009",
                                   "line_id": "line-009", "shipped_quantity": 5})
    seed_db(conn, data)
    m = client.get(f"{PREFIX}/metrics").json()
    assert m["data"]["metrics"]["gross_sales"] == "250.00"          # the cancelled order adds nothing
    assert m["data"]["metrics"]["eligible_orders"] == 1 and m["data"]["metrics"]["shipping_cost"] == "15.00"
    assert m["meta"]["exclusions"]["excluded_shipment_lines"] == 1
    by_customer = client.get(f"{PREFIX}/metrics", params={"group_by": "product"}).json()["data"]["groups"]
    assert set(by_customer) == {"prod-001", "prod-002"} and by_customer["prod-001"]["shipped_units"] == 2


def test_P01_TEST_10_return_exceeding_remaining_rejected_and_smaller_one_accepted(client, conn):
    seed_db(conn, golden_inputs())
    over = command(client, "post-a-partial-return", {**RET, "returned_quantity": 3})
    assert over.status_code == 422
    d = over.json()["error"]["details"][0]
    assert (d["path"], d["rule_id"]) == ("input.returned_quantity", "RETURN_EXCEEDS_REMAINING")
    assert count(conn, "returns") == 0
    ok = command(client, "post-a-partial-return", {**RET, "returned_quantity": 1})
    assert ok.status_code == 200 and ok.json()["result"]["remaining_quantity"] == 1
    # One unit left: asking for 2 fails, asking for the last 1 works, then nothing remains.
    more = command(client, "post-a-partial-return", {**RET, "returned_quantity": 2, "expected_version": 2})
    assert more.status_code == 422 and more.json()["error"]["details"][0]["rule_id"] == "RETURN_EXCEEDS_REMAINING"
    last = command(client, "post-a-partial-return", {**RET, "returned_quantity": 1, "expected_version": 2})
    assert last.status_code == 200 and last.json()["result"]["remaining_quantity"] == 0
    none_left = command(client, "post-a-partial-return", {**RET, "returned_quantity": 1, "expected_version": 3})
    assert none_left.status_code == 422
    assert count(conn, "returns") == 2
    assert command(client, "post-a-partial-return", {**RET, "returned_quantity": 0}).status_code == 422


def test_P01_TEST_10_responses_never_leak_internals(client, conn):
    seed_db(conn, golden_inputs())
    r = command(client, "allocate-freight", {"shipment_id": "x'; DROP TABLE orders; --"})
    assert r.status_code == 404 and count(conn, "orders") == 1
    for resp in (r, client.get(f"{PREFIX}/data/orders", params={"cursor": "%"})):
        assert "Traceback" not in resp.text and "lab:lab" not in resp.text and "postgresql://" not in resp.text


def test_P01_TEST_06_hostile_ingest_payloads_are_422_never_500_and_write_nothing(client, conn):
    """NaN, NUL, out-of-range numbers and non-object rows are refused before any write (D-06 C01)."""
    def post(raw_input: str):
        body = ('{"request_id":"r","dataset_version":"d","idempotency_key":"k-%d","input":%s}'
                % (count(conn, "command_results") + hash(raw_input) % 10000, raw_input))
        return client.post(f"{PREFIX}/commands/ingest-sales", content=body,
                           headers={**HEADERS, "Content-Type": "application/json"})
    order = ('{"order_id":"o","customer_id":"c","order_date":"2026-01-01","currency":"USD",'
             '"status":"shipped"%s}')
    cases = [
        '{"batch":{"orders":[' + order % ',"x":NaN' + ']}}',
        '{"batch":{"orders":[' + (order % "").replace('"o"', '"a\\u0000b"') + ']}}',
        '{"batch":{"orders":[5,null]}}',
        '{"batch":{"products":[{"product_id":"a","sku":"s","category_id":"c","unit_of_measure":"e",'
        '"active":true}],"orders":[' + order % "" + '],"order_lines":[{"line_id":"l","order_id":"o",'
        '"product_id":"a","quantity":99999999999999999999,"unit_price":"1"}]}}',
        '{"batch":{"products":[{"product_id":"a","sku":"s","category_id":"c","unit_of_measure":"e",'
        '"active":true}],"orders":[' + order % "" + '],"order_lines":[{"line_id":"l","order_id":"o",'
        '"product_id":"a","quantity":1,"unit_price":"99999999999999999999"}]}}',
    ]
    for raw in cases:
        r = post(raw)
        assert r.status_code == 422, (raw[:60], r.status_code, r.text)
        assert r.json()["error"]["details"][0]["rule_id"] in {
            "JSON_NON_FINITE", "NUL_CHARACTER", "MALFORMED_RECORD", "VALUE_OUT_OF_RANGE"}
    for table in ("orders", "products", "order_lines", "raw_batches", "audit_events", "command_results"):
        assert count(conn, table) == 0, table
