"""Commands C01..C04 through the FastAPI app against PostgreSQL (docs/api-contract.md, D-03..D-06)."""
from __future__ import annotations

import copy

from support_db import (HEADERS, PREFIX, client, command, conn, count, db_url, expected,  # noqa: F401
                        golden_inputs, seed_db)

RET = {"shipment_line_id": "sl-001", "returned_quantity": 1, "credit_amount": "90.00",
       "credit_date": "2026-03-20", "expected_version": 1}


def test_c01_ingest_golden_counts_match_expected(client, conn):
    r = command(client, "ingest-sales", {"batch": golden_inputs(returns=True, costs=True)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"command_id", "status", "result", "warnings", "version"}
    assert body["status"] == "accepted" and body["warnings"] == []
    for ent, want in expected()["ingest"]["counts"].items():
        got = body["result"]["counts"][ent]
        assert {k: got[k] for k in want} == want, ent
    assert count(conn, "order_lines") == 2 and count(conn, "raw_batches") == 1
    assert count(conn, "audit_events") == 1


def test_c01_to_c04_happy_path_on_golden(client, conn):
    assert command(client, "ingest-sales", {"batch": golden_inputs()}).status_code == 200
    c2 = command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    assert c2.status_code == 200 and c2.json()["status"] == "completed"
    assert {o["shipment_line_id"]: o["cost_version_id"] for o in c2.json()["result"]["lines"]} == \
        {"sl-001": "cv-001", "sl-002": "cv-002"}
    c4 = command(client, "allocate-freight", {"shipment_id": "shp-001"})
    assert c4.status_code == 200
    assert c4.json()["result"]["allocations"] == expected()["states"]["baseline"]["freight_by_shipment_line"]
    assert c4.json()["result"]["discount_allocations"] == \
        expected()["states"]["baseline"]["discount_by_shipment_line"]
    assert c4.json()["result"]["allocation_residual"] == "0.00"
    c3 = command(client, "post-a-partial-return", RET)
    assert c3.status_code == 200, c3.text
    assert c3.json()["version"] == 2 and c3.json()["warnings"] == []
    assert c3.json()["result"]["remaining_quantity"] == 1
    row = conn.execute("SELECT version FROM shipment_lines WHERE shipment_line_id = 'sl-001'").fetchone()
    assert row["version"] == 2
    audit = conn.execute("SELECT action, actor_id, before_version, after_version, request_id "
                         "FROM audit_events WHERE action = 'post-a-partial-return'").fetchone()
    assert audit == {"action": "post-a-partial-return", "actor_id": "analyst-1", "before_version": 1,
                     "after_version": 2, "request_id": "req-test"}
    assert conn.execute("SELECT status FROM orders").fetchone()["status"] == "partially_returned"


def test_c01_malformed_currency_is_rejected_and_raw_row_preserved(client, conn):
    batch = golden_inputs()
    batch["orders"].append({"order_id": "ord-002", "customer_id": "cust-001", "order_date": "2026-03-09",
                            "currency": "US$", "status": "shipped"})
    r = command(client, "ingest-sales", {"batch": batch})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "partial"
    assert {w["code"] for w in body["warnings"]} == {"CURRENCY_NOT_ISO4217"}
    assert body["result"]["counts"]["orders"]["rejected"] == 1
    rej = conn.execute("SELECT entity, id, reason_code, raw_row FROM rejected_records").fetchall()
    assert rej == [{"entity": "orders", "id": "ord-002", "reason_code": "CURRENCY_NOT_ISO4217",
                    "raw_row": batch["orders"][1]}]
    assert count(conn, "orders") == 1                       # the bad order never reached the table
    raw = conn.execute("SELECT payload, status FROM raw_batches").fetchone()
    assert raw["status"] == "partial" and raw["payload"]["orders"][1]["currency"] == "US$"


def test_c01_structurally_invalid_batch_is_422_and_writes_nothing(client, conn):
    r = command(client, "ingest-sales", {"batch": {"orders": "nope", "contract": "v1"}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert err["details"][0]["path"] == "input.batch.orders" and err["details"][0]["rule_id"] == "MALFORMED_RECORD"
    assert r.json()["request_id"] == "req-test"
    r = command(client, "ingest-sales", {"batch": {"contract": "v9"}})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["rule_id"] == "CONTRACT_MISMATCH"
    assert count(conn, "raw_batches") == 0 and count(conn, "audit_events") == 0


def test_unknown_shipment_is_404_for_c02_and_c04(client, conn):
    seed_db(conn, golden_inputs())
    for name in ("resolve-historical-cost", "allocate-freight"):
        r = command(client, name, {"shipment_id": "shp-nope"})
        assert r.status_code == 404, name
        assert r.json()["error"]["code"] == "NOT_FOUND"
        assert r.json()["error"]["details"][0]["rule_id"] == "SHIPMENT_UNKNOWN"
    r = command(client, "post-a-partial-return", {**RET, "shipment_line_id": "sl-nope"})
    assert r.status_code == 404 and r.json()["error"]["details"][0]["rule_id"] == "SHIPMENT_LINE_UNKNOWN"
    assert count(conn, "audit_events") == 0 and count(conn, "command_results") == 0


def test_c03_stale_expected_version_is_409_and_writes_nothing(client, conn):
    seed_db(conn, golden_inputs())
    command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    assert command(client, "post-a-partial-return", RET).status_code == 200      # version 1 -> 2
    r = command(client, "post-a-partial-return", {**RET, "returned_quantity": 1})  # still says version 1
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "STALE_VERSION"
    assert r.json()["error"]["details"][0]["path"] == "input.expected_version"
    assert count(conn, "returns") == 1
    assert conn.execute("SELECT version FROM shipment_lines WHERE shipment_line_id='sl-001'").fetchone()["version"] == 2


def test_same_key_same_payload_replays_without_side_effects(client, conn):
    seed_db(conn, golden_inputs())
    first = command(client, "post-a-partial-return", RET, key="k-replay")
    again = command(client, "post-a-partial-return", RET, key="k-replay", request_id="req-other")
    assert first.status_code == again.status_code == 200
    assert again.headers["Idempotent-Replay"] == "true" and "Idempotent-Replay" not in first.headers
    assert first.json() == again.json()
    assert first.json()["command_id"] == again.json()["command_id"]
    assert count(conn, "returns") == 1 and count(conn, "audit_events") == 1
    assert conn.execute("SELECT version FROM shipment_lines WHERE shipment_line_id='sl-001'").fetchone()["version"] == 2
    assert count(conn, "command_results") == 1


def test_same_key_different_payload_is_409(client, conn):
    seed_db(conn, golden_inputs())
    assert command(client, "post-a-partial-return", RET, key="k-reuse").status_code == 200
    r = command(client, "post-a-partial-return", {**RET, "credit_amount": "45.00"}, key="k-reuse")
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    r = command(client, "allocate-freight", {"shipment_id": "shp-001"}, key="k-reuse")  # other command, same key
    assert r.status_code == 409
    assert count(conn, "returns") == 1 and count(conn, "freight_allocations") == 0


def test_missing_actor_is_401_and_viewer_role_is_403(client, conn):
    seed_db(conn, golden_inputs())
    r = command(client, "allocate-freight", {"shipment_id": "shp-001"}, headers={"X-Actor-Role": "analyst"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert r.json()["request_id"]
    r = command(client, "allocate-freight", {"shipment_id": "shp-001"},
                headers={"X-Actor-Id": "u1", "X-Actor-Role": "viewer"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    r = command(client, "allocate-freight", {"shipment_id": "shp-001"}, headers={"X-Actor-Id": "u1"})
    assert r.status_code == 403
    # identity is checked before the body: an invalid body without identity is still 401.
    r = client.post(f"{PREFIX}/commands/allocate-freight", json={"nonsense": 1})
    assert r.status_code == 401
    r = command(client, "allocate-freight", {"shipment_id": "shp-001"},
                headers={"X-Actor-Id": "s1", "X-Actor-Role": "steward"})
    assert r.status_code == 200
    assert count(conn, "freight_allocations") == 2


def test_unsupported_action_path_is_404_envelope(client):
    r = client.post(f"{PREFIX}/commands/delete-everything", json={}, headers=HEADERS)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND" and r.json()["request_id"]
    assert client.get(f"{PREFIX}/commands/ingest-sales").status_code == 405


def test_envelope_validation_422_has_path_and_rule_id(client, conn):
    body = {"request_id": "r1", "dataset_version": "ds", "idempotency_key": "bad key!",
            "input": {"shipment_id": "shp-001", "extra": 1}}
    r = client.post(f"{PREFIX}/commands/allocate-freight", json=body, headers=HEADERS)
    assert r.status_code == 422
    details = {(d["path"], d["rule_id"]) for d in r.json()["error"]["details"]}
    assert ("idempotency_key", "IDEMPOTENCY_KEY_INVALID") in details
    assert ("input.extra", "FIELD_UNEXPECTED") in details
    assert r.json()["request_id"] == "r1"
    r = client.post(f"{PREFIX}/commands/allocate-freight", content=b"{not json",
                    headers={**HEADERS, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["details"][0] == {
        "path": "body", "rule_id": "BODY_INVALID_JSON", "message": "JSON decode error"}
    assert count(conn, "audit_events") == 0


def test_c02_repeat_with_new_key_is_a_noop(client, conn):
    seed_db(conn, golden_inputs())
    first = command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    assert first.json()["result"]["counts"] == {"resolved": 2, "unchanged": 0, "quarantined": 0}
    audits = count(conn, "audit_events")
    again = command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    assert again.status_code == 200 and again.json()["status"] == "completed"
    assert again.json()["result"]["counts"] == {"resolved": 0, "unchanged": 2, "quarantined": 0}
    assert count(conn, "audit_events") == audits
    assert again.json()["command_id"] != first.json()["command_id"]


def test_failed_command_rolls_back_effects_and_audit_together(client, conn, monkeypatch):
    """Command effects and the audit row share one transaction (D-06)."""
    seed_db(conn, golden_inputs())
    from api import commands

    def boom(*a, **k):
        raise RuntimeError("postgresql://lab:lab@127.0.0.1/secret")
    monkeypatch.setattr(commands, "_credit_warning", boom)
    r = command(client, "post-a-partial-return", RET)
    assert r.status_code == 500
    assert "lab:lab" not in r.text and "Traceback" not in r.text and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert count(conn, "returns") == 0 and count(conn, "audit_events") == 0 and count(conn, "command_results") == 0
    assert conn.execute("SELECT version FROM shipment_lines WHERE shipment_line_id='sl-001'").fetchone()["version"] == 1


def test_c03_warns_when_credit_differs_from_expected(client, conn):
    seed_db(conn, golden_inputs())
    command(client, "resolve-historical-cost", {"shipment_id": "shp-001"})
    r = command(client, "post-a-partial-return", {**RET, "credit_amount": "95.00"})
    assert r.status_code == 200
    assert [w["code"] for w in r.json()["warnings"]] == ["CREDIT_DIFFERS_FROM_EXPECTED"]
