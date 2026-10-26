"""Regression tests for the master-18 reviewer findings (verification ledger, 2026-10-26T15:22:44Z) and the worker findings
S-02 / S-03. Each test is named after its finding: R3-01 .. R3-07. They run through the pure domain, the SQL reference and
the API (Mode A); the TypeScript mirror is checked by web/scripts/review-check.ts with the same cases."""
import copy
from decimal import Decimal
from fractions import Fraction

import pytest

from data import seed
from supplyscope import run_pipeline
from supplyscope import metrics as dm
from supplyscope.contract import EXTRA_METRIC_KEYS, METRIC_KEYS
from supplyscope.forecast import promo_factor
from supplyscope.models import iso_z, parse_row, parse_ts

from support_db import (AS_OF, add_scenario, client, command, conn, count, db_url, get, golden_inputs, rule_ids,  # noqa: F401
                        seeded)

FROM = {"from": "2026-03-01T00:00:00Z"}
from pathlib import Path

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()


def inputs(**kw):
    g = golden_inputs()
    g.pop("states", None)
    g.update(kw)
    return g


def mv(i, d, t="2026-03-02T08:00:00Z", typ="adjustment", p="prod-001", l="loc-001"):
    return {"movement_id": i, "product_id": p, "location_id": l, "quantity_delta": d, "event_at": t, "movement_type": typ}


def two_locations():
    """The golden dataset plus a second location holding 100 units and one sale there; parameters stay at loc-001 only."""
    c = inputs()
    c["locations"].append({"location_id": "loc-002", "location_name": "B", "timezone": "UTC", "storage_capacity": 10,
                           "active": True})
    c["inventory_movements"].append(mv("x1", 100, "2026-03-02T08:00:00Z", "receipt", l="loc-002"))
    return c


def sql_row(conn, as_of=AS_OF, start="2026-03-01T00:00:00Z"):
    return conn.execute(SQL, {"as_of": as_of, "window_start": start, "window_end": None}).fetchone()


# --- R3-01 stockout days are a SKU-day rate; the calendar share is its own key ---------------------------------------

def test_R3_01_stockout_days_is_a_sku_day_rate_and_the_golden_value_holds():
    m = run_pipeline(golden_inputs(), "golden").metrics
    assert (m["stockout_day_count"], m["observed_days"], m["stockout_days"]) == (1, 31, "0.032258")   # one pair: 1 / 31
    assert (m["stockout_calendar_days_share"], m["observed_sku_days"]) == ("0.032258", 31)
    assert list(m) == [*METRIC_KEYS, *EXTRA_METRIC_KEYS]


def test_R3_01_two_pairs_one_stockout_gives_half_the_rate_and_the_calendar_share_stays_whole():
    m = run_pipeline(two_locations()).metrics
    assert (m["stockout_day_count"], m["observed_sku_days"]) == (1, 62)
    assert m["stockout_days"] == "0.016129"                       # 1 SKU-day of 2 pairs x 31 days
    assert m["stockout_calendar_days_share"] == "0.032258"        # 1 of 31 calendar dates had any unmet demand
    assert m["observed_days"] == 31


def test_R3_01_groups_reconcile_to_the_total():
    r = run_pipeline(two_locations())
    total = r.metrics
    for key in ("location", "product", "supplier", "abc_class"):
        groups = dm.group_metrics(r.population, key, r.as_of, r.window)
        assert sum(g["stockout_day_count"] for g in groups.values()) == total["stockout_day_count"], key
        assert sum(g["observed_sku_days"] for g in groups.values()) == total["observed_sku_days"], key
        rate = Fraction(sum(g["stockout_day_count"] for g in groups.values()), sum(g["observed_sku_days"] for g in groups.values()))
        assert abs(Decimal(total["stockout_days"]) - Decimal(rate.numerator) / Decimal(rate.denominator)) <= Decimal("0.0000005")
    by_loc = dm.group_metrics(r.population, "location", r.as_of, r.window)
    assert by_loc["loc-001"]["stockout_days"] == "0.032258" and by_loc["loc-002"]["stockout_days"] == "0.000000"


def test_R3_01_sql_reference_agrees(conn):
    seed.seed(conn, two_locations())
    row = sql_row(conn)
    dom = run_pipeline(two_locations()).metrics
    assert dict(row) == dom and row["stockout_days"] == "0.016129" and row["observed_sku_days"] == 62


# --- R3-02 scenario-scoped unmet demand ------------------------------------------------------------------------------

def _unmet(sc, at="2026-03-26T10:00:00Z", qty=4, **kw):
    return {"scenario_id": sc, "product_id": "prod-001", "location_id": "loc-001", "quantity": qty, "occurred_at": at, **kw}


def test_R3_02_the_same_event_under_two_scenarios_is_a_conflict_not_two_kinds(client, seeded, conn):
    add_scenario(conn, "s-bl", policy="backlog")
    add_scenario(conn, "s-ls", policy="lost_sale")
    add_scenario(conn, "s-bl2", policy="backlog")
    a = command(client, "record-unmet-demand", _unmet("s-bl"))
    assert a.status_code == 200 and a.json()["result"]["demand_ref"].startswith("ud-")
    b = command(client, "record-unmet-demand", _unmet("s-ls", qty=9))                  # same event, other kind
    assert b.status_code == 409 and b.json()["error"]["code"] == "UNMET_POLICY_CONFLICT"
    c = command(client, "record-unmet-demand", _unmet("s-bl2"))                        # same event, same kind
    assert c.status_code == 409 and c.json()["error"]["code"] == "UNMET_ALREADY_RECORDED"
    assert count(conn, "backorders") == 3 and count(conn, "lost_sales") == 0
    other = command(client, "record-unmet-demand", _unmet("s-ls", at="2026-03-27T10:00:00Z"))   # another event is fine
    assert other.status_code == 200 and other.json()["result"]["kind"] == "lost_sale"


def test_R3_02_scenario_backorders_never_change_the_canonical_position(client, seeded, conn):
    add_scenario(conn, "s-bl", policy="backlog")
    add_scenario(conn, "s-ls", policy="lost_sale")
    canon = lambda: get(client, "/metrics", as_of=AS_OF, **FROM).json()["data"]["metrics"]  # noqa: E731
    before = canon()
    assert command(client, "record-unmet-demand", _unmet("s-bl", qty=25)).status_code == 200
    assert command(client, "record-unmet-demand", _unmet("s-ls", at="2026-03-27T10:00:00Z", qty=7)).status_code == 200
    after = canon()
    assert after == before and after["inventory_position"] == 60 and after["backorders"] == 10
    assert after["unmet_units"] == 5 and after["fill_rate"] == "0.950000"
    mine = get(client, "/metrics", as_of=AS_OF, scenario="s-bl", **FROM).json()["data"]["metrics"]
    assert (mine["inventory_position"], mine["backorders"], mine["unmet_units"]) == (35, 35, 30)
    assert get(client, "/metrics", as_of=AS_OF, scenario="nope", **FROM).status_code == 422
    # canonical reads: the entity lists hide scenario rows unless the scenario is asked for
    assert len(get(client, "/data/backorders").json()["data"]) == 2
    assert len(get(client, "/data/backorders", scenario_id="s-bl").json()["data"]) == 1
    # and replenishment is calculated on the canonical position
    r = command(client, "calculate-replenishment", {"as_of": AS_OF})
    assert r.json()["result"]["evaluated"][0]["inventory_position"] == 60


def test_R3_02_occurred_at_is_required(client, seeded, conn):
    add_scenario(conn, "s-bl", policy="backlog")
    body = {"scenario_id": "s-bl", "product_id": "prod-001", "location_id": "loc-001", "quantity": 1}
    r = command(client, "record-unmet-demand", body)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["path"].endswith("occurred_at")
    assert count(conn, "backorders") == 2


# --- R3-03 dataset_version and stale drafts (D-07) --------------------------------------------------------------------

def test_R3_03_a_stale_dataset_version_is_409_and_writes_nothing(client, seeded, conn):
    r = command(client, "reconstruct-stock", {"as_of": AS_OF}, dataset_version="ds-not-current")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_DATASET_VERSION"
    assert r.json()["error"]["details"][0]["context"]["current"].startswith("ds-")
    assert count(conn, "stock_snapshots") == 0 and count(conn, "command_results") == 0
    assert command(client, "reconstruct-stock", {"as_of": AS_OF}).status_code == 200


def test_R3_03_export_marks_a_draft_stale_when_the_ledger_moved_under_it(client, seeded, conn):
    assert command(client, "calculate-replenishment", {"as_of": AS_OF}).json()["result"]["drafts"] == 1
    fresh = command(client, "export-buying-plan", {}).json()["result"]
    assert fresh["stale_count"] == 0 and "# stale_rows: 0" in fresh["csv"]
    late = mv("late-1", 100, "2026-03-05T08:00:00Z")                         # a back-dated receipt: the position is now 160
    assert command(client, "load-movements", {"movements": [late]}).status_code == 200
    res = command(client, "export-buying-plan", {})
    out = res.json()["result"]
    assert out["stale_count"] == 1 and out["stale_draft_order_ids"] == out["draft_order_ids"]
    latest = conn.execute("SELECT max(event_at) AS t FROM inventory_movements").fetchone()["t"]
    assert out["ledger_latest_movement_at"] == iso_z(latest) and latest > parse_ts(AS_OF)      # the header names the ledger it checked
    lines = out["csv"].splitlines()
    assert "# stale_rows: 1" in lines and any(l.startswith("# ledger_latest_movement_at: 2026-") for l in lines)
    header = next(l for l in lines if not l.startswith("#")).split(",")
    row = dict(zip(header, [l for l in lines if not l.startswith("#")][1].split(",")))
    assert row["status"] == "stale" and row["current_inventory_position"] == "160" and row["current_order_quantity"] == "0"
    assert row["order_quantity"] == "72" and [w["code"] for w in res.json()["warnings"]] == ["STALE_DRAFT"]
    assert conn.execute("SELECT status FROM draft_orders").fetchone()["status"] == "draft"      # the table is untouched
    # recalculating withdraws the draft and the next export has no stale rows
    command(client, "calculate-replenishment", {"as_of": AS_OF})
    assert command(client, "export-buying-plan", {}).json()["result"]["row_count"] == 0


# --- R3-04 the product position is the sum over its locations ---------------------------------------------------------

def test_R3_04_position_of_a_product_with_parameters_at_one_of_two_locations_is_the_product_total(conn):
    r = run_pipeline(two_locations())
    assert r.metrics["inventory_position"] == 160 and r.metrics["on_hand"] == 140
    assert (r.metrics["reorder_point"], r.metrics["order_quantity"]) == (70, 72)       # the per-pair figures are per pair
    by_loc = dm.group_metrics(r.population, "location", r.as_of, r.window)
    assert (by_loc["loc-001"]["inventory_position"], by_loc["loc-002"]["inventory_position"]) == (60, 100)
    seed.seed(conn, two_locations())
    assert sql_row(conn)["inventory_position"] == 160


def test_R3_04_position_over_the_api_for_the_multi_location_product(client, conn):
    seed.seed(conn, two_locations())
    m = get(client, "/metrics", as_of=AS_OF, group_by="product", **FROM).json()["data"]["groups"]["prod-001"]
    assert m["inventory_position"] == 160 and m["on_hand"] == 140


# --- R3-05 microsecond instants ---------------------------------------------------------------------------------------

def test_R3_05_sub_millisecond_instants_keep_their_microseconds():
    after = inputs()
    after["inventory_movements"].append(mv("x1", 7, "2026-03-31T23:59:59.0004Z", "receipt"))
    assert run_pipeline(after).metrics["on_hand"] == 40                                 # after the cutoff: excluded
    both = inputs(as_of="2026-03-31T23:59:59.0004Z")
    both["inventory_movements"] += [mv("x1", 7, "2026-03-31T23:59:59.0001Z", "receipt"), mv("x2", -3, "2026-03-31T23:59:59.0009Z", "sale")]
    assert run_pipeline(both).metrics["on_hand"] == 47
    assert iso_z(parse_ts("2026-03-31T23:59:59.0004Z")) == "2026-03-31T23:59:59.000400Z"


def test_R3_05_sql_orders_microseconds_like_the_domain(conn):
    c = inputs()
    c["inventory_movements"].append(mv("x1", 7, "2026-03-31T23:59:59.0004Z", "receipt"))
    seed.seed(conn, c)
    assert sql_row(conn)["on_hand"] == 40 == run_pipeline(c).metrics["on_hand"]


# --- R3-06 target position at least the reorder point ----------------------------------------------------------------

def test_R3_06_ingest_rejects_a_target_below_the_reorder_point():
    c = inputs()
    c["replenishment_params"][0].update(reorder_point=70, target_position=50)
    r = run_pipeline(c)
    assert [(x["entity"], x["reason_code"]) for x in r.rejected] == [("replenishment_params", "REPLENISHMENT_PARAMS_INVALID")]
    assert r.metrics["order_quantity"] is None and r.metrics["reorder_triggered"] is None       # not evaluated, never an order
    ok = inputs()
    ok["replenishment_params"][0].update(reorder_point=70, target_position=70)
    assert run_pipeline(ok).rejected == []


def test_R3_06_calculate_replenishment_refuses_a_row_that_is_below_its_own_reorder_point(client, seeded, conn):
    conn.execute("UPDATE replenishment_params SET target_position = 50")                         # bypasses ingest
    r = command(client, "calculate-replenishment", {"as_of": AS_OF})
    assert r.status_code == 422 and "REPLENISHMENT_PARAMS_INVALID" in rule_ids(r)
    assert count(conn, "draft_orders") == 0


# --- R3-07 negative available, unclamped position, wide sums ----------------------------------------------------------

def test_R3_07_available_below_zero_is_flagged():
    c = inputs()
    c["reservations"] = [{"reservation_id": "r1", "product_id": "prod-001", "location_id": "loc-001", "quantity": 500,
                          "reserved_at": "2026-03-30T00:00:00Z", "released_at": None}]
    r = run_pipeline(c)
    assert r.metrics["available"] == -460 and r.metrics["inventory_position"] == 60          # reserved is not in the position
    assert [f["flag"] for f in r.flags] == ["NEGATIVE_AVAILABLE"] and r.flags[0]["available"] == -460


def test_R3_07_the_position_uses_the_unclamped_ledger_value():
    c = inputs()
    c["inventory_movements"].append(mv("n1", -100, "2026-03-31T10:00:00Z", "sale"))      # on hand reconstructs to -60
    r = run_pipeline(c)
    assert r.metrics["on_hand"] == 0 and r.metrics["negative_stock"] is True               # valued at zero and flagged
    assert r.metrics["inventory_position"] == -60 + 30 - 10 and "NEGATIVE_STOCK" in [f["flag"] for f in r.flags]
    assert r.metrics["order_quantity"] == 168                                                # raw 120 - (-40) = 160 -> 7 packs of 24


def test_R3_07_sql_sums_are_bigint_and_agree(conn):
    c = inputs()
    c["inventory_movements"] += [mv(f"h{i}", 10**9, "2026-03-02T08:00:00Z") for i in range(5)]
    c["inventory_movements"] += [mv(f"g{i}", 10**9, "2026-03-02T08:00:00Z", l="loc-001") for i in range(5, 12)]
    seed.seed(conn, c)
    row = sql_row(conn)
    dom = run_pipeline(c).metrics
    assert row["on_hand"] == dom["on_hand"] == 12 * 10**9 + 40 and row["inventory_position"] == dom["inventory_position"]
    assert dict(row) == dom


# --- S-02 suppliers before products ---------------------------------------------------------------------------------

def test_S_02_a_product_with_a_supplier_id_is_accepted():
    c = inputs()
    c["products"][0]["supplier_id"] = "sup-001"
    r = run_pipeline(c)
    assert r.rejected == [] and r.population.products[0].supplier_id == "sup-001"
    assert dm.supplier_of(r.population, "prod-001") == "sup-001"
    bad = inputs()
    bad["products"][0]["supplier_id"] = "sup-nope"
    assert [x["reason_code"] for x in run_pipeline(bad).rejected][0] == "UNKNOWN_REFERENCE"


# --- S-03 the forecast promotion factor is 1 + planned uplift -------------------------------------------------------

def test_S_03_promo_factor_is_one_plus_the_planned_uplift():
    row = {"promotion_id": "pr-1", "product_id": "prod-001", "location_id": None, "starts_at": "2026-03-02T00:00:00Z",
           "ends_at": "2026-03-04T00:00:00Z", "planned_uplift": "0.50", "announced_at": "2026-02-10T00:00:00Z",
           "realised_uplift": "9.0"}
    promo = parse_row("promotions", row)
    known = parse_ts("2026-02-28T23:59:59Z")
    day = parse_ts("2026-03-03T00:00:00Z").date()
    assert promo_factor([promo], "prod-001", day, known) == Fraction(3, 2)                    # not 0.5
    assert promo_factor([promo, promo], "prod-001", day, known) == Fraction(9, 4)
    assert promo_factor([promo], "prod-001", parse_ts("2026-03-10T00:00:00Z").date(), known) == 1
    assert promo_factor([promo], "prod-001", day, parse_ts("2026-02-01T00:00:00Z")) == 1      # not announced yet
