"""Adversarial tests named by their P03-TEST id (01, 02, 04..12; 03 pack rounding is in test_rules): each attacks a rule
through the API and, where the rule is also a data rule, through the database or the pure domain. The tail attacks the
protocol: idempotency races, deadlocks, atomicity, odd inputs."""
import concurrent.futures as cf
import threading

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import commands
from api.app import PREFIX, create_app
from supplyscope import DomainError, run_pipeline
from supplyscope.forecast import forecast_demand
from supplyscope.models import parse_row, parse_ts

from support_db import (ADMIN, AS_OF, BUYER, PLANNER, add_scenario, client, command, conn, count, db_url, get,  # noqa: F401
                        golden_inputs, rule_ids, seeded)

FROM = {"from": "2026-03-01T00:00:00Z"}


def history(conn, days=59, pid="prod-001"):
    conn.execute("INSERT INTO sales SELECT 'fs-' || g, %s, 'loc-001', timestamptz '2026-01-01 12:00+00' + g * interval '1 day', "
                 "5 + mod(g * 7, 5) FROM generate_series(0, %s) g", (pid, days - 1))


@pytest.fixture
def api(client, seeded):
    return client


def test_p03_test_01_censored_sales_are_not_latent_demand(api, conn):
    """Sales observed during a stockout are a floor on demand: the API keeps latent demand in its own entity and never
    folds it into the observed series or the fill rate."""
    conn.execute("INSERT INTO latent_demand VALUES ('prod-001', 'loc-001', '2026-03-12', 70), ('prod-001', 'loc-001', '2026-03-11', 35)")
    latent = get(api, "/data/latent_demand").json()["data"]
    assert [(r["demand_date"], r["latent_quantity"]) for r in latent] == [("2026-03-11", 35), ("2026-03-12", 70)]
    sales = get(api, "/data/sales", **{"from": "2026-03-12", "to": "2026-03-13"}).json()["data"]
    assert sum(s["quantity"] for s in sales) == 35                                       # observed 35 vs latent 70, kept apart
    m = get(api, "/metrics", as_of=AS_OF, **FROM).json()["data"]["metrics"]
    assert m["fulfilled_units"] == 95 and m["unmet_units"] == 5 and m["fill_rate"] == "0.950000"   # latent never enters requested
    from supplyscope import demand
    from supplyscope.models import Population
    from data import seed
    pop = run_pipeline(golden_inputs() | {"latent_demand": [{"product_id": "prod-001", "location_id": "loc-001",
                                                              "demand_date": "2026-03-12", "latent_quantity": 70}]}, "golden").population
    out = demand.censored_vs_latent(pop.sales, pop.backorders, pop.lost_sales, pop.latent_demand, "prod-001", "loc-001",
                                    parse_ts("2026-03-11T00:00:00Z").date(), parse_ts("2026-03-12T00:00:00Z").date(), parse_ts(AS_OF))
    assert out["observed"]["2026-03-12"] == 35 and out["latent"]["2026-03-12"] == 70 and "2026-03-12" in out["censored_days"]


def test_p03_test_02_forecast_at_cutoff_ignores_later_promotion_outcomes(api, conn):
    history(conn)
    conn.execute("INSERT INTO promotions VALUES ('pr-1', 'prod-001', NULL, '2026-03-02T00:00:00Z', '2026-03-04T00:00:00Z', 2, "
                 "'2026-02-10T00:00:00Z', 1.5)")
    body = {"cutoff": "2026-02-28T23:59:59Z", "horizon_days": 7}
    first = command(api, "forecast-demand", body).json()["result"]["runs"][0]
    pts = lambda rid: conn.execute("SELECT model, target_date, forecast_value FROM forecast_points WHERE forecast_run_id = %s "  # noqa: E731
                                   "ORDER BY 1, 2", (rid,)).fetchall()
    base_points = pts(first["forecast_run_id"])
    conn.execute("UPDATE promotions SET realised_uplift = 9.0")                      # the outcome changes after the cutoff
    conn.execute("INSERT INTO promotions VALUES ('pr-2', 'prod-001', NULL, '2026-03-02T00:00:00Z', '2026-03-04T00:00:00Z', 5, "
                 "'2026-03-01T00:00:00Z', 4)")                                          # announced after the cutoff
    conn.execute("INSERT INTO sales VALUES ('after', 'prod-001', 'loc-001', '2026-03-01T09:00:00Z', 900)")
    second = command(api, "forecast-demand", body).json()["result"]["runs"][0]
    assert second["forecast_run_id"] == first["forecast_run_id"] and pts(second["forecast_run_id"]) == base_points
    ewma = {str(r["target_date"]): r["forecast_value"] for r in base_points if r["model"] == "ewma"}
    plain = {str(r["target_date"]): r["forecast_value"] for r in base_points if r["model"] == "naive"}
    assert ewma["2026-03-02"] != ewma["2026-03-05"]                                        # the known schedule is used (x2)


def test_p03_test_04_duplicate_movement_cannot_drive_stock_negative(api, conn):
    """Replaying the sale of 35 would take stock from 0 to -35 (valued at zero, flagged): the replay is rejected."""
    load = lambda rows: command(api, "load-movements", {"movements": rows})  # noqa: E731
    sale = {"movement_id": "mv-009", "product_id": "prod-001", "location_id": "loc-001", "quantity_delta": -40,
            "event_at": "2026-03-20T08:00:00Z", "movement_type": "sale"}
    assert load([sale]).json()["status"] == "loaded"                                        # on hand 40 -> 0
    r = load([sale, sale])                                                                  # replays of a stored id
    assert r.json()["status"] == "rejected" and [x["reason_code"] for x in r.json()["result"]["rejected_records"]] == [
        "DUPLICATE_MOVEMENT_ID"] * 2
    r = load([dict(sale, quantity_delta=-1)])                                               # same id, another payload
    assert [x["reason_code"] for x in r.json()["result"]["rejected_records"]] == ["DUPLICATE_MOVEMENT_CONFLICT"]
    assert count(conn, "inventory_movements") == 8
    m = get(api, "/metrics", as_of=AS_OF, **FROM).json()
    assert m["data"]["metrics"]["on_hand"] == 0 and m["data"]["metrics"]["negative_stock"] is False and m["warnings"] == []
    with pytest.raises(psycopg.errors.UniqueViolation):                                      # and the table refuses it too
        conn.execute("INSERT INTO inventory_movements VALUES ('mv-009', 'prod-001', 'loc-001', -40, '2026-03-21T00:00:00Z', 'sale')")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        conn.execute("DELETE FROM inventory_movements WHERE movement_id = 'mv-009'")          # nor can it be erased and re-posted


def test_p03_test_05_supplier_closure_lengthens_the_lead_time_and_the_reorder_point(api, conn):
    history(conn)
    conn.execute("DELETE FROM replenishment_params")
    add_scenario(conn, target="0.90")
    body = {"as_of": "2026-02-28T23:59:59Z", "scenario_id": "sc-1"}
    plain = command(api, "calculate-replenishment", body).json()["result"]["evaluated"][0]
    conn.execute("INSERT INTO calendar_closures VALUES ('k1', 'cal-001', '2026-03-02', '2026-03-08')")      # a week closed
    closed = command(api, "calculate-replenishment", body).json()["result"]["evaluated"][0]
    assert closed["reorder_point"] > plain["reorder_point"] and closed["target_position"] > plain["target_position"]
    r = command(api, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001", "at": "2026-03-27T09:00:00Z"})
    assert r.status_code == 200                                                          # a closure on another dates does not block this one


def test_p03_test_06_intermittent_sku_has_null_wape_over_the_api(api, conn):
    conn.execute("INSERT INTO sales SELECT 'is-' || g, 'prod-001', 'loc-001', timestamptz '2025-12-01 12:00+00' + g * interval '1 day', 3 "
                 "FROM generate_series(0, 2) g")                                          # three sales days, then silence until March
    conn.execute("DELETE FROM sales WHERE sale_id LIKE 'sale-%'")
    conn.execute("INSERT INTO sales VALUES ('end', 'prod-001', 'loc-001', '2026-03-31T10:00:00Z', 1)")
    r = command(api, "forecast-demand", {"cutoff": "2026-03-30T23:59:59Z", "horizon_days": 7})
    run = r.json()["result"]["runs"][0]
    assert all(v["wape"] is None for v in run["model_report"].values())
    assert run["model_report"]["naive"]["mae"] is not None and run["model_report"]["naive"]["zero_demand_folds"] > 0
    assert run["beats_baseline"] == {"ewma": None} and run["selected_model"] == "seasonal_naive"
    assert {n["code"] for n in r.json()["warnings"]} == {"ZERO_DEMAND_FOLDS_DISCLOSED"}


def test_p03_test_07_partial_receipt_never_completes_the_line(api, conn):
    base = {"po_line_id": "pol-001", "location_id": "loc-001"}
    r = command(api, "simulate-arrival", {**base, "at": "2026-03-28T09:00:00Z", "quantity": 29})
    assert r.json()["result"]["line_status"] == "open" and r.json()["result"]["remaining"] == 1
    m = get(api, "/metrics", as_of=AS_OF, **FROM).json()["data"]["metrics"]
    assert m["on_order"] == 1                                                             # 29 of 30 received: one unit still due
    review = command(api, "review-supplier", {"supplier_id": "sup-001", "as_of": AS_OF}).json()["result"]
    assert review["open_lines"] == ["pol-001"] and review["partially_received_open_lines"] == ["pol-001"]
    assert command(api, "simulate-arrival", {**base, "at": "2026-03-29T09:00:00Z", "quantity": 2}).status_code == 422
    done = command(api, "simulate-arrival", {**base, "at": "2026-03-29T09:00:00Z", "quantity": 1}).json()["result"]
    assert done["line_status"] == "complete"
    assert command(api, "review-supplier", {"supplier_id": "sup-001", "as_of": AS_OF}).json()["result"]["open_lines"] == []
    assert command(api, "simulate-arrival", {**base, "at": "2026-03-30T09:00:00Z", "quantity": 1}).status_code == 422


def test_p03_test_08_lost_sale_xor_backlog_even_when_forced(api, conn):
    add_scenario(conn, "sc-b", policy="backlog")
    add_scenario(conn, "sc-l", policy="lost_sale")
    body = {"product_id": "prod-001", "location_id": "loc-001", "quantity": 3, "occurred_at": "2026-03-15T10:00:00Z", "demand_ref": "ud-1"}
    assert command(api, "record-unmet-demand", {**body, "scenario_id": "sc-b"}).status_code == 200
    r = command(api, "record-unmet-demand", {**body, "scenario_id": "sc-l"})              # the same demand, the other kind
    assert r.status_code == 409 and r.json()["error"]["code"] == "UNMET_POLICY_CONFLICT"
    dup = command(api, "record-unmet-demand", {**body, "scenario_id": "sc-b"})            # the same kind twice
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "UNMET_ALREADY_RECORDED"
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="UNMET_POLICY_CONFLICT"):
        conn.execute("INSERT INTO lost_sales (lost_sale_id, product_id, location_id, quantity, occurred_at, demand_ref) "
                     "VALUES ('x', 'prod-001', 'loc-001', 3, now(), 'ud-1')")
    assert count(conn, "lost_sales") == 0 and count(conn, "backorders") == 3
    # raced: two threads record the same demand under opposite policies; exactly one wins
    barrier = threading.Barrier(2)

    def go(scenario):
        barrier.wait()
        with TestClient(create_app(), raise_server_exceptions=False) as c:
            return command(c, "record-unmet-demand", {**body, "demand_ref": "ud-race", "scenario_id": scenario}).status_code
    with cf.ThreadPoolExecutor(2) as ex:
        codes = sorted(f.result() for f in [ex.submit(go, "sc-b"), ex.submit(go, "sc-l")])
    assert codes == [200, 409]
    assert count(conn, "lost_sales") + count(conn, "backorders") == 3 + 1


def test_p03_test_09_policies_with_different_seeds_are_refused(api, conn):
    add_scenario(conn, "s1", "0.90", "backlog", 100)
    add_scenario(conn, "s2", "0.95", "backlog", 101)
    add_scenario(conn, "s3", "0.95", "lost_sale", 100)
    body = {"scenario_ids": ["s1", "s2"], "product_id": "prod-001", "location_id": "loc-001", "initial_stock": 20}
    r = command(api, "compare-policies", body)
    assert r.status_code == 422 and rule_ids(r) == ["POLICY_SEED_MISMATCH"]
    assert r.json()["error"]["details"][0]["context"]["seeds"] == [100, 101]
    ok = command(api, "compare-policies", body | {"scenario_ids": ["s1", "s3"]})
    again = command(api, "compare-policies", body | {"scenario_ids": ["s1", "s3"]})
    assert ok.status_code == 200 and ok.json()["result"]["results"] == again.json()["result"]["results"]


def test_p03_test_10_reserved_stock_is_never_subtracted_twice(api, conn):
    conn.execute("INSERT INTO reservations VALUES ('res-1', 'prod-001', 'loc-001', 15, '2026-03-10T00:00:00Z', NULL), "
                 "('res-2', 'prod-001', 'loc-001', 5, '2026-03-11T00:00:00Z', NULL)")
    m = get(api, "/metrics", as_of=AS_OF, state="golden", **FROM).json()["data"]["metrics"]
    assert (m["on_hand"], m["reserved"], m["available"], m["inventory_position"]) == (40, 20, 20, 60)
    assert (m["raw_order"], m["order_quantity"]) == (60, 72)                              # the golden order is unchanged
    snap = command(api, "reconstruct-stock", {"as_of": AS_OF}).json()["result"]["snapshots"][0]
    assert (snap["on_hand"], snap["reserved"], snap["available"]) == (40, 20, 20)
    r = command(api, "calculate-replenishment", {"as_of": AS_OF}).json()["result"]["evaluated"][0]
    assert r["inventory_position"] == 60 and r["order_quantity"] == 72
    conn.execute("UPDATE reservations SET released_at = '2026-03-20T00:00:00Z'")
    assert get(api, "/metrics", as_of=AS_OF, **FROM).json()["data"]["metrics"]["reserved"] == 0


def test_p03_test_11_receipt_before_the_order_is_refused_everywhere(api, conn):
    r = command(api, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001", "at": "2026-03-19T23:59:59Z"})
    assert r.status_code == 422 and rule_ids(r) == ["RECEIPT_BEFORE_ORDER"]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="RECEIPT_BEFORE_ORDER"):
        conn.execute("INSERT INTO receipts VALUES ('rx', 'pol-001', 'loc-001', 5, '2026-03-19T23:59:59Z')")
    res = run_pipeline(golden_inputs("variant-rejected"), "golden")
    assert [(x["id"], x["reason_code"]) for x in res.rejected if x["entity"] == "receipts"] == [("rcpt-001", "RECEIPT_BEFORE_ORDER")]
    assert count(conn, "receipts") == 0 and count(conn, "inventory_movements") == 7


def test_p03_test_12_cost_change_inside_the_valuation_period(api, conn):
    conn.execute("INSERT INTO cost_versions VALUES ('cv-1', 'prod-001', 20.00, '2026-03-16T00:00:00Z')")
    m = lambda as_of: get(api, "/metrics", as_of=as_of, **FROM).json()["data"]  # noqa: E731
    assert m("2026-03-16T08:00:00Z")["metrics"]["working_capital"] == "800.00"              # 40 x the new 20.00
    assert m("2026-03-15T23:59:59Z")["metrics"]["on_hand"] == 0                              # day order: 0 -> 35 -> 0 on 03-12
    data = m(AS_OF)
    sup = data["supplementary"]
    assert data["metrics"]["working_capital"] == "800.00"
    # 31 days: 03-01 60x12.5, 03-02..04 60, 03-05..10 35, 03-11..15 0 (+03-12 closes 0), 03-16.. 40 at 20.00 from the 16th
    expected_total = 12.5 * (60 * 4 + 35 * 6) + 0 * 5 + 20.0 * 40 * 16
    assert float(sup["average_inventory_value"]) == pytest.approx(expected_total / 31, abs=0.01)
    old = conn.execute("SELECT unit_cost FROM products").fetchone()["unit_cost"]
    assert str(old) == "12.50"                                                              # the product keeps its base cost


# --- protocol attacks -------------------------------------------------------------------------------------------

def test_a_deadlock_is_retried_then_409_never_500(api, monkeypatch):
    calls = {"n": 0}
    real = commands._execute_once

    def always(*a, **k):
        calls["n"] += 1
        raise psycopg.errors.DeadlockDetected("deadlock detected")
    monkeypatch.setattr(commands, "_execute_once", always)
    monkeypatch.setattr(commands.time, "sleep", lambda s: None)
    r = command(api, "reconstruct-stock", {"as_of": AS_OF})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONCURRENT_UPDATE" and calls["n"] == 3

    def once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.errors.SerializationFailure("could not serialize access")
        return real(*a, **k)
    calls["n"] = 0
    monkeypatch.setattr(commands, "_execute_once", once)
    assert command(api, "reconstruct-stock", {"as_of": AS_OF}).status_code == 200 and calls["n"] == 2


def test_pairs_are_locked_in_sorted_order(api, monkeypatch):
    seen = []
    real = commands._lock_pairs
    monkeypatch.setattr(commands, "_lock_pairs", lambda conn, pairs: (seen.append(list(pairs)), real(conn, pairs))[1])
    command(api, "reconstruct-stock", {"as_of": AS_OF})
    command(api, "calculate-replenishment", {"as_of": AS_OF})
    assert seen and all(isinstance(p, tuple) for batch in seen for p in batch)
    import inspect
    assert "sorted(set(pairs))" in inspect.getsource(real)


def test_the_same_key_raced_runs_the_command_once(api, conn):
    barrier = threading.Barrier(4)

    def go():
        barrier.wait()
        with TestClient(create_app(), raise_server_exceptions=False) as c:
            return command(c, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001",
                                                   "at": "2026-03-28T09:00:00Z", "quantity": 10}, key="race-key")
    with cf.ThreadPoolExecutor(4) as ex:
        rs = [f.result() for f in [ex.submit(go) for _ in range(4)]]
    assert [r.status_code for r in rs] == [200] * 4 and len({r.json()["command_id"] for r in rs}) == 1
    assert count(conn, "receipts") == 1 and count(conn, "inventory_movements") == 8


def test_concurrent_receipts_cannot_over_receive_a_line(api, conn):
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        with TestClient(create_app(), raise_server_exceptions=False) as c:
            return command(c, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001",
                                                   "at": "2026-03-28T09:00:00Z", "quantity": 20}).status_code
    with cf.ThreadPoolExecutor(2) as ex:
        codes = sorted(f.result() for f in [ex.submit(go), ex.submit(go)])
    assert codes == [200, 422]
    assert conn.execute("SELECT sum(received_quantity) AS n FROM receipts").fetchone()["n"] == 20


def test_two_batches_loading_the_same_ids_never_500_and_never_duplicate(api, conn):
    rows = [{"movement_id": f"mv-c{i}", "product_id": "prod-001", "location_id": "loc-001", "quantity_delta": 1,
             "event_at": "2026-03-20T08:00:00Z", "movement_type": "receipt"} for i in range(30)]
    barrier = threading.Barrier(2)

    def go(order):
        barrier.wait()
        with TestClient(create_app(), raise_server_exceptions=False) as c:
            return command(c, "load-movements", {"movements": order}).status_code
    with cf.ThreadPoolExecutor(2) as ex:
        codes = [f.result() for f in [ex.submit(go, rows), ex.submit(go, list(reversed(rows)))]]
    assert all(c < 500 for c in codes), codes
    assert count(conn, "inventory_movements") == 37


def test_a_failed_command_leaves_no_trace(api, conn):
    snap = {t: count(conn, t) for t in ("receipts", "inventory_movements", "audit_events", "command_results", "raw_batches")}
    r = command(api, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001", "at": "2026-03-10T09:00:00Z"})
    assert r.status_code == 422
    assert snap == {t: count(conn, t) for t in snap}
    ok = command(api, "simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001", "at": "2026-03-28T09:00:00Z"})
    assert ok.status_code == 200 and count(conn, "audit_events") == 1 and count(conn, "command_results") == 1


def test_odd_inputs_are_422_not_500(api):
    for name, body in (("load-movements", {"movements": ["x"]}), ("load-movements", {"movements": [None]}),
                       ("forecast-demand", {"cutoff": "2026-03-01T00:00:00Z", "horizon_days": "7"}),
                       ("simulate-arrival", {"po_line_id": "pol-001", "location_id": "loc-001", "at": AS_OF, "quantity": 1.5}),
                       ("record-unmet-demand", {"scenario_id": "s", "product_id": "p", "location_id": "l", "quantity": "5"}),
                       ("compare-policies", {"scenario_ids": ["a", "b"], "product_id": "p", "location_id": "l", "mean_demand": float("nan")})):
        r = api.post(f"{PREFIX}/commands/{name}", content=__import__("json").dumps(
            {"request_id": "r", "dataset_version": "d", "idempotency_key": "k", "input": body}, allow_nan=True),
            headers=PLANNER | {"content-type": "application/json"})
        assert r.status_code in (200, 422), (name, r.status_code, r.text[:200])
        assert r.status_code != 500
    r = api.post(f"{PREFIX}/commands/reconstruct-stock", content="{not json", headers=PLANNER | {"content-type": "application/json"})
    assert r.status_code == 422 and rule_ids(r) == ["BODY_INVALID_JSON"]
    nul = command(api, "load-movements", {"movements": [{"movement_id": "a\u0000b"}]})
    assert nul.status_code == 422 and rule_ids(nul) == ["NUL_CHARACTER"]


def test_commands_never_create_a_purchase_order_or_a_non_draft(api, conn):
    command(api, "calculate-replenishment", {"as_of": AS_OF})
    assert count(conn, "purchase_orders") == 1 and count(conn, "purchase_order_lines") == 1
    assert {r["status"] for r in conn.execute("SELECT status FROM draft_orders").fetchall()} == {"draft"}
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE draft_orders SET status = 'ordered'")
