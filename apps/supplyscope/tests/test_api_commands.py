"""Commands C01..C10 through the HTTP API: envelopes, validation, effects, idempotency, identity."""
import pytest

from api.app import PREFIX

from support_db import (ADMIN, AS_OF, BUYER, PLANNER, add_scenario, client, command, conn, count, db_url, get,  # noqa: F401
                        golden_inputs, rule_ids, seeded)

M = lambda i, delta, at, kind=None, p="prod-001", l="loc-001": {  # noqa: E731
    "movement_id": f"mv-new-{i}", "product_id": p, "location_id": l, "quantity_delta": delta, "event_at": at,
    "movement_type": kind or ("receipt" if delta > 0 else "sale")}


# --- identity and envelope -------------------------------------------------------------------------------------

def test_identity_and_envelope(client, seeded):
    body = {"request_id": "r1", "dataset_version": "d", "idempotency_key": "k1", "input": {"as_of": AS_OF}}
    assert client.post(f"{PREFIX}/commands/reconstruct-stock", json=body).status_code == 401
    r = client.post(f"{PREFIX}/commands/reconstruct-stock", json=body, headers={"X-Actor-Id": "x", "X-Actor-Role": "viewer"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    for role in ("planner", "buyer", "admin"):
        ok = command(client, "reconstruct-stock", {"as_of": AS_OF}, headers={"X-Actor-Id": f"{role}-1", "X-Actor-Role": role})
        assert ok.status_code == 200, role
    r = command(client, "reconstruct-stock", {"as_of": AS_OF, "nope": 1})
    assert r.status_code == 422 and rule_ids(r) == ["FIELD_UNEXPECTED"]
    r = command(client, "reconstruct-stock", {"as_of": "2026-03-31"})
    assert r.status_code == 422 and rule_ids(r) == ["TIMESTAMP_INVALID"]
    assert command(client, "reconstruct-stock", {}).status_code == 422
    r = command(client, "no-such-command", {})
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNSUPPORTED_ACTION"
    body = command(client, "reconstruct-stock", {"as_of": AS_OF}).json()
    assert set(body) == {"command_id", "status", "result", "warnings", "version"}


def test_idempotency_replay_is_actor_bound_and_instant_normalised(client, seeded):
    first = command(client, "reconstruct-stock", {"as_of": AS_OF}, key="k-same")
    again = command(client, "reconstruct-stock", {"as_of": "2026-04-01T00:59:59+01:00"}, key="k-same")   # the same instant
    assert first.status_code == again.status_code == 200 and again.headers["Idempotent-Replay"] == "true"
    assert again.json() == first.json()
    other = command(client, "reconstruct-stock", {"as_of": AS_OF}, key="k-same", headers=BUYER)
    assert other.status_code == 409 and rule_ids(other) == ["IDEMPOTENCY_ACTOR_MISMATCH"]
    diff = command(client, "reconstruct-stock", {"as_of": "2026-03-30T00:00:00Z"}, key="k-same")
    assert diff.status_code == 409 and rule_ids(diff) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]
    assert command(client, "reconstruct-stock", {"as_of": AS_OF}, key="bad key!").status_code == 422


# --- C01 load-movements ----------------------------------------------------------------------------------------

def test_c01_load_validates_keeps_raw_rows_and_rejects_replays(client, seeded, conn):
    rows = [M(1, 10, "2026-03-20T08:00:00Z"), M(2, -4, "2026-03-21T08:00:00Z"), M(1, 10, "2026-03-20T08:00:00Z"),
            dict(M(3, 5, "2026-03-22T08:00:00Z"), product_id="ghost"), dict(M(4, 1, "2026-03-22T08:00:00Z"), quantity_delta=1.5)]
    r = command(client, "load-movements", {"movements": rows})
    assert r.status_code == 200
    res = r.json()["result"]
    assert (res["received"], res["accepted"], res["rejected"]) == (5, 2, 3) and r.json()["status"] == "partial"
    assert {(x["id"], x["reason_code"]) for x in res["rejected_records"]} == {
        ("mv-new-1", "DUPLICATE_MOVEMENT_ID"), ("mv-new-3", "UNKNOWN_REFERENCE"), ("mv-new-4", "MALFORMED_RECORD")}
    assert count(conn, "inventory_movements") == 9 and count(conn, "rejected_records") == 3
    raw = conn.execute("SELECT payload FROM raw_batches").fetchone()["payload"]
    assert len(raw["movements"]) == 5                                                     # the raw rows are kept
    again = command(client, "load-movements", {"movements": [M(1, 10, "2026-03-20T08:00:00+00:00")]})   # replay of a stored id
    assert again.json()["status"] == "rejected" and again.json()["result"]["rejected_records"][0]["reason_code"] == "DUPLICATE_MOVEMENT_ID"
    conflict = command(client, "load-movements", {"movements": [M(1, 99, "2026-03-20T08:00:00Z")]})
    assert conflict.json()["result"]["rejected_records"][0]["reason_code"] == "DUPLICATE_MOVEMENT_CONFLICT"
    assert conn.execute("SELECT quantity_delta FROM inventory_movements WHERE movement_id = 'mv-new-1'").fetchone()["quantity_delta"] == 10


def test_c01_limits_and_empty_batches(client, seeded):
    assert command(client, "load-movements", {"movements": []}).status_code == 422
    assert command(client, "load-movements", {}).status_code == 422
    assert command(client, "load-movements", {"movements": [M(i, 1, "2026-03-20T08:00:00Z") for i in range(5001)]}).status_code == 422


# --- C02 reconstruct-stock -------------------------------------------------------------------------------------

def test_c02_reconstruct_persists_one_snapshot_idempotently(client, seeded, conn):
    for _ in range(2):
        r = command(client, "reconstruct-stock", {"as_of": AS_OF})
        assert r.status_code == 200
    snap = r.json()["result"]["snapshots"][0]
    assert (snap["on_hand"], snap["reserved"], snap["available"], snap["running_stock_min"], snap["negative_stock"]) == (40, 0, 40, 0, False)
    assert count(conn, "stock_snapshots") == 1
    early = command(client, "reconstruct-stock", {"as_of": "2026-03-12T10:00:00Z", "product_id": "prod-001"}).json()
    assert early["result"]["snapshots"][0]["on_hand_raw"] == -35 and early["result"]["snapshots"][0]["on_hand"] == 0
    assert early["warnings"][0]["code"] == "NEGATIVE_STOCK" and count(conn, "stock_snapshots") == 2
    assert command(client, "reconstruct-stock", {"as_of": AS_OF, "product_id": "zzz"}).status_code == 404


# --- C03 forecast-demand ---------------------------------------------------------------------------------------

def history(conn):
    conn.execute("INSERT INTO sales SELECT 'fs-' || g, 'prod-001', 'loc-001', timestamptz '2026-01-01 12:00+00' + g * interval '1 day', "
                 "5 + (g * 7 % 5) FROM generate_series(0, 58) g")


def test_c03_forecast_has_baselines_and_is_deterministic(client, seeded, conn):
    history(conn)
    r = command(client, "forecast-demand", {"cutoff": "2026-02-28T23:59:59Z", "horizon_days": 7})
    assert r.status_code == 200
    run = r.json()["result"]["runs"][0]
    assert run["baselines"] == ["naive", "seasonal_naive"] and set(run["model_report"]) == {"naive", "seasonal_naive", "ewma"}
    assert run["first_target_date"] == "2026-03-01"
    pts = conn.execute("SELECT model, count(*) AS n FROM forecast_points GROUP BY model ORDER BY model").fetchall()
    assert [(p["model"], p["n"]) for p in pts] == [("ewma", 7), ("naive", 7), ("seasonal_naive", 7)]
    again = command(client, "forecast-demand", {"cutoff": "2026-02-28T23:59:59Z", "horizon_days": 7})
    assert again.json()["result"]["runs"][0]["forecast_run_id"] == run["forecast_run_id"] and count(conn, "forecast_runs") == 1
    conn.execute("INSERT INTO sales VALUES ('later', 'prod-001', 'loc-001', '2026-03-05T10:00:00Z', 500)")   # after the cutoff
    third = command(client, "forecast-demand", {"cutoff": "2026-02-28T23:59:59Z", "horizon_days": 7})
    assert third.json()["result"]["runs"][0]["forecast_run_id"] == run["forecast_run_id"]


def test_c03_cutoff_after_the_dataset_end_is_422(client, seeded):
    r = command(client, "forecast-demand", {"cutoff": "2026-06-01T00:00:00Z", "horizon_days": 7})
    assert r.status_code == 422 and rule_ids(r) == ["FORECAST_CUTOFF_IN_FUTURE"]
    assert command(client, "forecast-demand", {"cutoff": "2026-03-01T00:00:00Z", "horizon_days": 0}).status_code == 422
    assert command(client, "forecast-demand", {"cutoff": "2026-03-01T00:00:00Z", "horizon_days": 91}).status_code == 422


# --- C05 calculate-replenishment -------------------------------------------------------------------------------

def test_c05_golden_draft_carries_the_arithmetic(client, seeded, conn):
    add_scenario(conn)
    r = command(client, "calculate-replenishment", {"as_of": AS_OF, "scenario_id": "sc-1"})
    assert r.status_code == 200 and r.json()["result"]["drafts"] == 1
    row = conn.execute("SELECT * FROM draft_orders").fetchone()
    assert (row["inventory_position"], row["reorder_point"], row["target_position"], row["raw_order"],
            row["minimum_order_quantity"], row["order_after_moq"], row["pack_size"], row["order_quantity"]) == \
        (60, 70, 120, 60, 50, 60, 24, 72)
    assert row["status"] == "draft" and row["parameter_source"] == "params" and row["supplier_id"] == "sup-001"
    ev = r.json()["result"]["evaluated"][0]
    assert ev["order_quantity"] == 72 and ev["draft_order_id"] == row["draft_order_id"]
    command(client, "calculate-replenishment", {"as_of": AS_OF, "scenario_id": "sc-1"})
    assert count(conn, "draft_orders") == 1                                     # the same as-of: the same draft


def test_c05_not_triggered_creates_no_draft_and_withdraws_a_stale_one(client, seeded, conn):
    command(client, "calculate-replenishment", {"as_of": AS_OF})
    assert count(conn, "draft_orders") == 1
    conn.execute("INSERT INTO purchase_order_lines VALUES ('pol-002', 'po-001', 'prod-001', 20, 12.50)")   # position 80
    r = command(client, "calculate-replenishment", {"as_of": AS_OF})
    assert r.json()["result"]["drafts"] == 0 and r.json()["result"]["evaluated"][0]["triggered"] is False
    assert count(conn, "draft_orders") == 0


def test_c05_validation(client, seeded):
    assert command(client, "calculate-replenishment", {"as_of": AS_OF, "scenario_id": "nope"}).status_code == 404
    assert command(client, "calculate-replenishment", {"as_of": AS_OF, "product_id": "nope"}).status_code == 404
    assert command(client, "calculate-replenishment", {}).status_code == 422


def test_c05_without_parameters_the_forecast_sizes_the_order(client, seeded, conn):
    history(conn)
    conn.execute("DELETE FROM replenishment_params")
    add_scenario(conn, target="0.95")
    r = command(client, "calculate-replenishment", {"as_of": "2026-02-28T23:59:59Z", "scenario_id": "sc-1"})
    assert r.status_code == 200
    ev = r.json()["result"]["evaluated"][0]
    assert ev["parameter_source"] == "forecast" and ev["reorder_point"] > 0 and ev["target_position"] > ev["reorder_point"]
    add_scenario(conn, "sc-bad", target="0.50")
    assert command(client, "calculate-replenishment", {"as_of": "2026-02-28T23:59:59Z", "scenario_id": "sc-bad"}).status_code == 422


# --- C06 simulate-arrival --------------------------------------------------------------------------------------

def test_c06_partial_arrival_keeps_the_line_open_and_posts_stock(client, seeded, conn):
    r = command(client, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001", "at": "2026-03-28T09:00:00Z", "quantity": 10})
    assert r.status_code == 200
    res = r.json()["result"]
    assert (res["received_quantity"], res["remaining"], res["line_status"]) == (10, 20, "open")
    assert conn.execute("SELECT quantity_delta, movement_type FROM inventory_movements WHERE movement_id = %s",
                        (res["movement_id"],)).fetchone() == {"quantity_delta": 10, "movement_type": "receipt"}
    m = get(client, "/metrics", as_of="2026-03-31T23:59:59Z", **{"from": "2026-03-01T00:00:00Z"}).json()["data"]["metrics"]
    assert (m["on_hand"], m["on_order"], m["inventory_position"]) == (50, 20, 60)         # still open: 20 on order
    r = command(client, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001", "at": "2026-03-29T09:00:00Z"})
    assert r.json()["result"]["received_quantity"] == 20 and r.json()["result"]["line_status"] == "complete"


def test_c06_receipt_rules(client, seeded, conn):
    base = {"po_line_id": "pol-001", "location_id": "loc-001"}
    r = command(client, "simulate-arrival", {**base, "at": "2026-03-18T10:00:00Z"})
    assert r.status_code == 422 and rule_ids(r) == ["RECEIPT_BEFORE_ORDER"]
    r = command(client, "simulate-arrival", {**base, "at": "2026-03-25T10:00:00Z"})            # ordered 03-20 + 7 lead days = 03-27
    assert r.status_code == 422 and rule_ids(r) == ["RECEIPT_BEFORE_LEAD_TIME"]
    assert r.json()["error"]["details"][0]["context"]["earliest"] == "2026-03-27T09:00:00Z"
    r = command(client, "simulate-arrival", {**base, "at": "2026-03-27T09:00:00Z", "quantity": 31})
    assert r.status_code == 422 and rule_ids(r) == ["RECEIPT_EXCEEDS_ORDERED"]
    assert command(client, "simulate-arrival", {**base, "at": "2026-03-27T09:00:00Z", "quantity": 0}).status_code == 422
    assert command(client, "simulate-arrival", {**base, "at": "2026-03-27T09:00:00Z", "location_id": "zz"}).status_code == 404
    assert command(client, "simulate-arrival", {"po_line_id": "zz", "location_id": "loc-001", "at": AS_OF}).status_code == 404
    assert count(conn, "receipts") == 0 and count(conn, "inventory_movements") == 7
    conn.execute("UPDATE purchase_orders SET status = 'cancelled'")
    r = command(client, "simulate-arrival", {**base, "at": "2026-03-27T09:00:00Z"})
    assert r.status_code == 422 and rule_ids(r) == ["ORDER_NOT_RECEIVABLE"]


def test_c06_a_supplier_closure_pushes_the_earliest_receipt(client, seeded, conn):
    conn.execute("INSERT INTO calendar_closures VALUES ('k1', 'cal-001', '2026-03-22', '2026-03-28')")   # 7 closed days
    r = command(client, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001", "at": "2026-03-27T09:00:00Z"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["context"]["effective_lead_days"] == 14


# --- C07 record-unmet-demand -----------------------------------------------------------------------------------

def test_c07_the_scenario_policy_chooses_exactly_one_kind(client, seeded, conn):
    add_scenario(conn, "sc-backlog", policy="backlog")
    add_scenario(conn, "sc-lost", policy="lost_sale")
    base = {"product_id": "prod-001", "location_id": "loc-001", "quantity": 4, "occurred_at": "2026-03-15T10:00:00Z"}
    a = command(client, "record-unmet-demand", {**base, "scenario_id": "sc-backlog"})
    b = command(client, "record-unmet-demand", {**base, "scenario_id": "sc-lost", "quantity": 6,
                                                "occurred_at": "2026-03-16T10:00:00Z"})      # another event (R3-02)
    assert a.json()["result"]["kind"] == "backorder" and b.json()["result"]["kind"] == "lost_sale"
    assert count(conn, "backorders") == 3 and count(conn, "lost_sales") == 1
    m = get(client, "/metrics", as_of=AS_OF, **{"from": "2026-03-01T00:00:00Z"}).json()["data"]["metrics"]
    assert m["unmet_units"] == 5 and m["backorders"] == 10 and m["inventory_position"] == 60   # scenario rows are not canonical
    ms = get(client, "/metrics", as_of=AS_OF, scenario="sc-backlog", **{"from": "2026-03-01T00:00:00Z"}).json()["data"]["metrics"]
    assert ms["unmet_units"] == 9 and ms["requested_units"] == 104 and ms["backorders"] == 14   # 5 + 4 backorder
    ml = get(client, "/metrics", as_of=AS_OF, scenario="sc-lost", **{"from": "2026-03-01T00:00:00Z"}).json()["data"]["metrics"]
    assert ml["unmet_units"] == 11 and ml["backorders"] == 10                                    # 5 + 6 lost; not a backorder
    r = command(client, "record-unmet-demand", {**base, "scenario_id": "sc-lost", "policy": "backlog"})
    assert r.status_code == 422 and rule_ids(r) == ["POLICY_MISMATCH"]
    assert command(client, "record-unmet-demand", {**base, "scenario_id": "nope"}).status_code == 404
    assert command(client, "record-unmet-demand", {**base, "scenario_id": "sc-lost", "quantity": 0}).status_code == 422


# --- C08 compare-policies and C09 review-supplier -------------------------------------------------------------

def test_c08_policies_are_compared_on_the_same_sample(client, seeded, conn):
    add_scenario(conn, "a", "0.90", "backlog", 5)
    add_scenario(conn, "b", "0.95", "lost_sale", 5)
    add_scenario(conn, "c", "0.95", "lost_sale", 6)
    body = {"scenario_ids": ["a", "b"], "product_id": "prod-001", "location_id": "loc-001", "days": 60, "mean_demand": 6, "initial_stock": 30}
    r = command(client, "compare-policies", body)
    assert r.status_code == 200 and r.json()["result"]["common_random_numbers"] is True and r.json()["result"]["seed"] == 5
    ra, rb = r.json()["result"]["results"]["a"], r.json()["result"]["results"]["b"]
    assert [x["requested"] for x in ra] == [x["requested"] for x in rb]
    assert command(client, "compare-policies", body | {"scenario_ids": ["a", "c"]}).status_code == 422
    assert command(client, "compare-policies", body | {"scenario_ids": ["a"]}).status_code == 422
    assert command(client, "compare-policies", body | {"scenario_ids": ["a", "zz"]}).status_code == 404


def test_c09_review_supplier_uses_only_receipts_up_to_the_cutoff(client, seeded, conn):
    for rid, at in (("r1", "2026-03-27T09:00:00Z"), ("r2", "2026-04-20T09:00:00Z")):
        conn.execute("INSERT INTO receipts VALUES (%s, 'pol-001', 'loc-001', 10, %s)", (rid, at))
    r = command(client, "review-supplier", {"supplier_id": "sup-001", "as_of": AS_OF})
    res = r.json()["result"]
    assert (res["eligible_receipts"], res["on_time_receipts"], res["on_time_rate"]) == (1, 1, "1.000000")
    assert res["open_lines"] == ["pol-001"] and res["partially_received_open_lines"] == ["pol-001"]
    later = command(client, "review-supplier", {"supplier_id": "sup-001", "as_of": "2026-05-01T00:00:00Z"}).json()["result"]
    assert later["eligible_receipts"] == 2 and later["on_time_rate"] == "0.500000" and later["late_receipts"] == ["r2"]
    assert command(client, "review-supplier", {"supplier_id": "zz", "as_of": AS_OF}).status_code == 404


# --- C10 export-buying-plan ------------------------------------------------------------------------------------

def test_c10_export_carries_the_header_rows_and_never_a_real_po(client, seeded, conn):
    add_scenario(conn)
    command(client, "calculate-replenishment", {"as_of": AS_OF, "scenario_id": "sc-1"})
    r = command(client, "export-buying-plan", {"scenario_id": "sc-1", "as_of": AS_OF})
    assert r.status_code == 200
    csv_text = r.json()["result"]["csv"]
    lines = csv_text.splitlines()
    assert lines[0] == "# contract_version: v1" and lines[1].startswith("# dataset_version: ds-")
    assert lines[2] == f"# as_of: {AS_OF}" and lines[3] == "# scenario: sc-1"
    assert lines[4] == '# filters: {"as_of":"2026-03-31T23:59:59Z","scenario_id":"sc-1"}' and lines[5] == "# rows: 1"
    assert lines[6] == "# stale_rows: 0" and lines[7].startswith("# ledger_latest_movement_at: 2026-")
    assert "not purchase orders" in lines[8]
    header = lines[9].split(",")
    row = dict(zip(header, lines[10].split(",")))
    assert row["order_quantity"] == "72" and row["status"] == "draft" and row["raw_order"] == "60" and row["pack_size"] == "24"
    assert r.json()["result"]["row_count"] == 1 and r.json()["result"]["contract_version"] == "v1"
    assert count(conn, "draft_orders") == 1                       # exporting changes nothing
    empty = command(client, "export-buying-plan", {"product_id": "nope"})
    assert empty.json()["result"]["row_count"] == 0 and empty.json()["warnings"][0]["code"] == "NO_DRAFTS"


def test_c10_formula_injection_is_neutralised(client, conn):
    from data import seed
    data = golden_inputs()
    evil = "=HYPERLINK(\"http://x\",\"y\")"
    data["products"][0]["product_id"] = evil
    for ent in ("sales", "inventory_movements", "backorders", "replenishment_params", "purchase_order_lines"):
        for row in data[ent]:
            row["product_id"] = evil
    seed.seed(conn, data)
    command(client, "calculate-replenishment", {"as_of": AS_OF})
    csv_text = command(client, "export-buying-plan", {}).json()["result"]["csv"]
    body = [l for l in csv_text.splitlines() if not l.startswith("#")][1]
    assert "'=HYPERLINK" in body and "\n=" not in csv_text and not body.startswith("=")
    import csv, io
    cells = next(csv.reader(io.StringIO("\n".join(l for l in csv_text.splitlines() if not l.startswith("#"))), strict=True))
    assert not any(c.startswith(("=", "+", "-", "@")) for c in cells)


def test_c04_is_not_implemented_and_says_so(client, seeded):
    r = command(client, "classify-skus", {"anything": 1})
    assert r.status_code == 501 and r.json()["error"]["code"] == "NOT_IMPLEMENTED"
