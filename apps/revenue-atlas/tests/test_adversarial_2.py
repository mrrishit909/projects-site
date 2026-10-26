"""Adversarial cases P01-TEST-02, -04, -05, -07, -08, -11, -12 through the API and pipeline.

Every test is named with its P01-TEST id and the phase it verifies (DETECT or RECOVER).
Key totals are checked against a reference calculation written in this file from the raw input
rows (plain Decimal arithmetic, no domain code), and each test also asserts that unrelated
records and earlier results stay intact. Contract: docs/contracts.md D-01..D-07.
The replay of data/injection-events.json runs on the seeded generated snapshot.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from support_db import (GOLDEN, HEADERS, PREFIX, client, command, conn, count,  # noqa: F401
                        db_url, expected, golden_inputs, seed_db)

from revenue_atlas import run_pipeline
from revenue_atlas.metrics import compute_metrics

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "web" / "public" / "data"
EVENTS = ROOT / "data" / "injection-events.json"

# --- helpers -----------------------------------------------------------------------


def metrics(client, **params) -> dict[str, Any]:
    r = client.get(f"{PREFIX}/metrics", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def totals(client, **params) -> dict[str, Any]:
    return metrics(client, **params)["data"]["metrics"]


def groups(client, group_by: str, **params) -> dict[str, dict[str, Any]]:
    return metrics(client, group_by=group_by, **params)["data"]["groups"]


def entity(client, name: str, **params) -> dict[str, Any]:
    r = client.get(f"{PREFIX}/data/{name}", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()


def ingest(client, batch: dict[str, Any], key: str | None = None):
    return command(client, "ingest-sales", {"batch": {"contract": "v1", **batch}}, key=key)


def settle(client, shipment_id: str) -> None:
    """C02 then C04 for one shipment, as an operator would."""
    assert command(client, "resolve-historical-cost", {"shipment_id": shipment_id}).status_code == 200
    assert command(client, "allocate-freight", {"shipment_id": shipment_id}).status_code == 200


def customer(cid: str, region: str, effective_from: str, segment: str = "SMB") -> dict[str, Any]:
    return {"customer_id": cid, "customer_name": f"Test {cid}", "region_id": region,
            "segment": segment, "effective_from": effective_from}


def order_bundle(n: str, cust: str, shipped_at: str, lines: list[tuple[str, int, str]],
                 shipping: str, currency: str = "USD") -> dict[str, list[dict[str, Any]]]:
    """One order, one shipment, every line shipped in full. lines: (product, qty, unit_price)."""
    out: dict[str, list[dict[str, Any]]] = {
        "orders": [{"order_id": f"ord-{n}", "customer_id": cust, "order_date": shipped_at[:10],
                    "currency": currency, "status": "shipped"}],
        "order_lines": [], "shipments": [{"shipment_id": f"shp-{n}", "order_id": f"ord-{n}",
                                          "shipped_at": shipped_at, "shipping_cost": shipping,
                                          "currency": currency}],
        "shipment_lines": []}
    for i, (prod, qty, price) in enumerate(lines, 1):
        out["order_lines"].append({"line_id": f"line-{n}-{i}", "order_id": f"ord-{n}",
                                   "product_id": prod, "quantity": qty, "unit_price": price})
        out["shipment_lines"].append({"shipment_line_id": f"sl-{n}-{i}", "shipment_id": f"shp-{n}",
                                      "line_id": f"line-{n}-{i}", "shipped_quantity": qty})
    return out


def merge(inputs: dict[str, Any], extra: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    for k, rows in extra.items():
        inputs[k] = list(inputs.get(k, [])) + copy.deepcopy(rows)
    return inputs


def golden_baseline() -> dict[str, Any]:
    return expected()["states"]["baseline"]["metrics"]


# Hand reference (not domain code): golden = 2x100 + 1x50, discounts 20+5, freight 15 split 12/3 by
# gross weight, costs 60 and 20 per unit.  gross 250, net 225, cogs 140, gross profit 85, CM 70.
REF_GOLDEN = {"gross_sales": "250.00", "net_merchandise_sales": "225.00", "cogs": "140.00",
              "shipping_cost": "15.00", "contribution_margin": "70.00"}


def sum_money(rows: dict[str, dict[str, Any]], field: str) -> D:
    return sum((D(g[field]) for g in rows.values()), D(0))


def snapshot_counts(conn) -> dict[str, int]:
    return {t: count(conn, t) for t in ("customers", "products", "orders", "order_lines", "discounts",
                                        "shipments", "shipment_lines", "returns", "cost_versions",
                                        "exchange_rates", "freight_allocations")}


# === P01-TEST-02 partial return posted after period close =============================

def _golden_window() -> tuple[str, str, str]:
    """Window of the golden shipment's month, and a credit date in the next month."""
    shipped = datetime.fromisoformat(golden_inputs()["shipments"][0]["shipped_at"].replace("Z", "+00:00"))
    lo = shipped.date().replace(day=1)
    hi = (lo + timedelta(days=32)).replace(day=1)
    return lo.isoformat(), hi.isoformat(), (hi + timedelta(days=14)).isoformat()


def _seed_period_close(client, conn):
    seed_db(conn, golden_inputs())
    settle(client, "shp-001")
    lo, hi, credit_date = _golden_window()
    base = totals(client, **{"from": lo, "to": hi})
    assert base["net_merchandise_sales"] == REF_GOLDEN["net_merchandise_sales"]   # reference, not self-referential
    assert base == golden_baseline()
    return lo, hi, credit_date, base


def _post_late_return(client, credit_date: str):
    return command(client, "post-a-partial-return",
                   {"shipment_line_id": "sl-001", "returned_quantity": 1, "credit_amount": "90.00",
                    "credit_date": credit_date, "expected_version": 1,
                    "reason": "customer return after period close"}, key="ret-late-1")


@pytest.mark.xfail(strict=True, reason="DEFECT G-01: credits windowed by shipped_at, "
                   "contract D-01 requires credit_date")
def test_P01_TEST_02_DETECT_late_return_does_not_change_closed_window_net_sales(client, conn):
    lo, hi, credit_date, base = _seed_period_close(client, conn)
    before_rows = snapshot_counts(conn)
    resp = _post_late_return(client, credit_date)
    assert resp.status_code == 200 and resp.json()["status"] == "posted"
    # unrelated records intact: only the returns table grew
    after_rows = snapshot_counts(conn)
    assert after_rows == {**before_rows, "returns": before_rows["returns"] + 1}
    after = totals(client, **{"from": lo, "to": hi})
    # sales side is unaffected either way
    assert after["gross_sales"] == base["gross_sales"] == REF_GOLDEN["gross_sales"]
    assert after["allocated_discounts"] == base["allocated_discounts"] == "25.00"
    assert after["shipping_cost"] == base["shipping_cost"] == REF_GOLDEN["shipping_cost"]
    # D-01: the credit is dated next month, so the closed window must not move
    assert after["net_merchandise_sales"] == REF_GOLDEN["net_merchandise_sales"]
    assert after == base


def test_P01_TEST_02_DETECT_observed_behaviour_credit_follows_shipped_at(client, conn):
    """Characterises G-01: today the credit lands in the shipment's window (March), not its credit month."""
    lo, hi, credit_date, base = _seed_period_close(client, conn)
    assert _post_late_return(client, credit_date).status_code == 200
    march = totals(client, **{"from": lo, "to": hi})
    assert march["merchandise_credits"] == "90.00"            # reference: 1 unit credited at 90.00
    assert march["net_merchandise_sales"] == "135.00"         # 225.00 - 90.00
    next_month = totals(client, **{"from": hi, "to": (date.fromisoformat(hi) + timedelta(days=31)).isoformat()})
    assert next_month["merchandise_credits"] == "0.00"        # ...and the credit month sees nothing
    assert next_month["eligible_shipment_lines"] == 0
    # the all-time view matches the golden hand-derived after-return state
    assert totals(client) == expected()["states"]["after_return"]["metrics"]


def test_P01_TEST_02_RECOVER_audit_event_and_returns_read_carry_the_late_credit(client, conn):
    lo, hi, credit_date, _ = _seed_period_close(client, conn)
    audits_before = count(conn, "audit_events")
    resp = _post_late_return(client, credit_date)
    body = resp.json()
    assert body["result"]["remaining_quantity"] == 1 and body["version"] == 2
    ev = conn.execute("SELECT * FROM audit_events WHERE action = 'post-a-partial-return'").fetchall()
    assert len(ev) == 1 and count(conn, "audit_events") == audits_before + 1
    assert ev[0]["entity_id"] == "sl-001" and ev[0]["actor_id"] == HEADERS["X-Actor-Id"]
    assert ev[0]["reason"] == "customer return after period close"
    assert ev[0]["occurred_at"] is not None
    assert (ev[0]["before_version"], ev[0]["after_version"]) == (1, 2)
    # the returns read, windowed by credit date, finds exactly this credit in the later month
    later = entity(client, "returns", **{"from": hi, "to": (date.fromisoformat(hi) + timedelta(days=31)).isoformat()})
    assert [(r["shipment_line_id"], r["credit_amount"], r["credit_date"]) for r in later["data"]] \
        == [("sl-001", "90.00", credit_date)]
    assert entity(client, "returns", **{"from": lo, "to": hi})["data"] == []


@pytest.mark.xfail(strict=True, reason="DEFECT G-01: credits windowed by shipped_at, "
                   "contract D-01 requires credit_date")
def test_P01_TEST_02_RECOVER_metrics_over_the_later_window_include_the_credit(client, conn):
    lo, hi, credit_date, _ = _seed_period_close(client, conn)
    assert _post_late_return(client, credit_date).status_code == 200
    nxt = (date.fromisoformat(hi) + timedelta(days=31)).isoformat()
    later = totals(client, **{"from": hi, "to": nxt})
    assert later["merchandise_credits"] == "90.00"             # D-01: recognised on credit_date
    assert later["net_merchandise_sales"] == "-90.00"          # no sales in that month, one credit


# === P01-TEST-04 missing exchange rate ==================================================

EUR_DAY = "2026-03-12"


def _eur_inputs(rate_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    inputs = golden_inputs()
    inputs["exchange_rates"] += [{"rate_id": "fx-eur-0311", "currency": "EUR",
                                  "reporting_currency": "USD", "rate_date": "2026-03-11", "rate": "1.05"}]
    inputs["exchange_rates"] += rate_rows or []
    return merge(inputs, order_bundle("eur", "cust-001", f"{EUR_DAY}T10:00:00Z",
                                      [("prod-001", 1, "80.00")], "4.00", currency="EUR"))


def test_P01_TEST_04_DETECT_missing_rate_quarantines_line_and_totals_stay_golden(client, conn):
    seed_db(conn, _eur_inputs())
    settle(client, "shp-001")
    assert command(client, "resolve-historical-cost", {"shipment_id": "shp-eur"}).status_code == 200  # cost is fine
    assert command(client, "allocate-freight", {"shipment_id": "shp-eur"}).status_code == 200
    body = metrics(client)
    m = body["data"]["metrics"]
    # not zero-filled, not rate 1.0: the EUR line is simply absent, golden totals stand
    assert m == golden_baseline()
    assert m["gross_sales"] == REF_GOLDEN["gross_sales"] and m["contribution_margin"] == REF_GOLDEN["contribution_margin"]
    assert m["eligible_shipment_lines"] == 2 and m["eligible_orders"] == 1
    assert body["meta"]["exclusions"]["quarantined"] == {"shipment_lines": 1}
    assert [w["code"] for w in body["warnings"]] == ["QUARANTINED_RECORDS_EXCLUDED"]
    # prior results intact: the golden shipment's allocation is unchanged
    alloc = {r["shipment_line_id"]: r["amount"] for r in entity(client, "freight_allocations")["data"]
             if r["shipment_id"] == "shp-001"}
    assert alloc == {"sl-001": "12.00", "sl-002": "3.00"}


@pytest.mark.xfail(strict=True, reason="DEFECT-1: FX_RATE_MISSING is quarantined only inside the pipeline "
                   "run; C02 persists COST_* quarantines only, so GET /data/quarantined_records "
                   "does not list the line")
def test_P01_TEST_04_DETECT_quarantined_records_read_lists_fx_rate_missing(client, conn):
    seed_db(conn, _eur_inputs())
    settle(client, "shp-001")
    command(client, "resolve-historical-cost", {"shipment_id": "shp-eur"})
    command(client, "allocate-freight", {"shipment_id": "shp-eur"})
    rows = entity(client, "quarantined_records")["data"]
    assert [(r["entity"], r["id"], r["reason_code"]) for r in rows] == \
        [("shipment_lines", "sl-eur-1", "FX_RATE_MISSING")]


def test_P01_TEST_04_RECOVER_ingesting_the_rate_via_c01_admits_the_line(client, conn):
    seed_db(conn, _eur_inputs())
    settle(client, "shp-001")
    command(client, "resolve-historical-cost", {"shipment_id": "shp-eur"})
    command(client, "allocate-freight", {"shipment_id": "shp-eur"})
    assert totals(client) == golden_baseline()
    rows_before = snapshot_counts(conn)
    # a batch holding only exchange_rates is accepted (rates have no parents)
    r = ingest(client, {"exchange_rates": [{"rate_id": "fx-eur-0312", "currency": "EUR",
                                            "reporting_currency": "USD", "rate_date": EUR_DAY, "rate": "1.10"}]})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert r.json()["result"]["counts"]["exchange_rates"]["inserted"] == 1
    assert snapshot_counts(conn) == {**rows_before, "exchange_rates": rows_before["exchange_rates"] + 1}
    body = metrics(client)
    m = body["data"]["metrics"]
    # independent reference: EUR line 1 x 80.00 x 1.10 = 88.00; shipping 4.00 x 1.10 = 4.40 (all on that
    # line); cost is stored in USD, 60.00 for prod-001; the golden lines are unchanged.
    gross = D("250.00") + D("80.00") * D("1.10")
    net = gross - D("25.00")
    cogs = D("140.00") + D("60.00")
    freight = D("15.00") + D("4.00") * D("1.10")
    assert (D(m["gross_sales"]), D(m["net_merchandise_sales"]), D(m["cogs"]), D(m["shipping_cost"])) \
        == (gross, net, cogs, freight) == (D("338.00"), D("313.00"), D("200.00"), D("19.40"))
    assert D(m["contribution_margin"]) == net - cogs - freight == D("93.60")
    assert m["eligible_shipment_lines"] == 3 and m["eligible_orders"] == 2
    assert body["meta"]["exclusions"]["quarantined"] == {} and body["warnings"] == []
    # the original rate row (2026-03-11) was never used for the 03-12 shipment
    assert D(m["gross_sales"]) != D("250.00") + D("80.00") * D("1.05")


# === P01-TEST-05 zero revenue with non-zero costs =======================================

def _zero_inputs() -> dict[str, Any]:
    inputs = golden_inputs()
    inputs["customers"].append(customer("cust-z", "reg-z", "2025-01-01"))
    # one shipment, two lines at price 0.00 (3 x prod-001 @ cost 60, 1 x prod-002 @ cost 20), freight 7.00
    return merge(inputs, order_bundle("z", "cust-z", "2026-03-15T09:00:00Z",
                                      [("prod-001", 3, "0.00"), ("prod-002", 1, "0.00")], "7.00"))


def test_P01_TEST_05_DETECT_zero_revenue_gives_negative_contribution_and_null_rates(client, conn):
    seed_db(conn, _zero_inputs())
    settle(client, "shp-001")
    alloc = command(client, "allocate-freight", {"shipment_id": "shp-z"})
    assert alloc.status_code == 200
    # freight is allocated by quantity (zero gross weight): 7.00 over 3:1 -> 5.25 / 1.75
    assert alloc.json()["result"]["allocations"] == {"sl-z-1": "5.25", "sl-z-2": "1.75"}
    assert alloc.json()["result"]["allocation_residual"] == "0.00"
    g = groups(client, "region")
    z = g["reg-z"]
    # reference: gross 0, net 0, cogs 3x60 + 1x20 = 200, freight 7 -> CM = 0 - 200 - 7 = -207
    assert (z["gross_sales"], z["net_merchandise_sales"], z["cogs"], z["shipping_cost"]) \
        == ("0.00", "0.00", "200.00", "7.00")
    assert z["contribution_margin"] == "-207.00" and D(z["contribution_margin"]) < 0
    assert z["contribution_margin_rate"] is None          # not 0, not an error
    assert z["discount_rate"] is None
    assert z["average_order_value"] == "0.00" and z["eligible_orders"] == 1
    assert z["allocation_residual"] == "0.00"
    # unrelated region (golden) is untouched
    assert g["reg-001"] == golden_baseline()
    assert sum_money(g, "contribution_margin") == D("70.00") + D("-207.00") \
        == D(totals(client)["contribution_margin"])
    # persisted allocation equals the response
    stored = {r["shipment_line_id"]: r["amount"] for r in entity(client, "freight_allocations")["data"]
              if r["shipment_id"] == "shp-z"}
    assert stored == {"sl-z-1": "5.25", "sl-z-2": "1.75"}


def test_P01_TEST_05_RECOVER_corrected_price_via_new_batch_yields_a_rate(client, conn):
    seed_db(conn, _zero_inputs())
    settle(client, "shp-001")
    command(client, "allocate-freight", {"shipment_id": "shp-z"})
    # (a) re-ingesting the SAME line id with a price is a no-op: rows are insert-only (ON CONFLICT DO NOTHING)
    fix = order_bundle("z", "cust-z", "2026-03-15T09:00:00Z", [("prod-001", 3, "25.00"), ("prod-002", 1, "10.00")], "7.00")
    r = ingest(client, fix)
    assert r.status_code == 200 and r.json()["result"]["counts"]["order_lines"]["inserted"] == 0
    assert conn.execute("SELECT unit_price::text AS p FROM order_lines WHERE line_id = 'line-z-1'").fetchone()["p"] \
        == "0.000000"
    assert groups(client, "region")["reg-z"]["contribution_margin_rate"] is None
    # (b) a NEW priced order for the same customer (2 x prod-002 @ 50.00, freight 6.00) gives a rate
    new = order_bundle("z2", "cust-z", "2026-03-20T09:00:00Z", [("prod-002", 2, "50.00")], "6.00")
    r = ingest(client, new)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    settle(client, "shp-z2")
    g = groups(client, "region")
    z = g["reg-z"]
    # reference: reg-z net 0 + 100 = 100; CM = -207 + (100 - 2x20 - 6 = 54) = -153 -> rate -1.53
    assert z["net_merchandise_sales"] == "100.00" and z["contribution_margin"] == "-153.00"
    assert D(z["contribution_margin_rate"]) == D("-1.53")
    assert D(z["discount_rate"]) == 0 and z["discount_rate"] is not None   # gross > 0 now: defined, zero
    assert g["reg-001"] == golden_baseline()


# === P01-TEST-07 customer changes territory ===========================================

def _territory_inputs() -> dict[str, Any]:
    inputs = golden_inputs()
    inputs["customers"].append(customer("cust-001", "reg-002", "2026-04-01"))   # moves on 2026-04-01
    return inputs


def test_P01_TEST_07_DETECT_shipment_takes_the_version_effective_at_shipped_at(client, conn):
    seed_db(conn, _territory_inputs())
    settle(client, "shp-001")
    assert [(r["region_id"], r["effective_from"]) for r in entity(client, "customers")["data"]] \
        == [("reg-001", "2025-01-01"), ("reg-002", "2026-04-01")]
    g = groups(client, "region")
    # shipped 2026-03-10 -> the 2025-01-01 version (reg-001), though a newer version exists
    assert list(g) == ["reg-001"]
    assert g["reg-001"] == golden_baseline()
    assert g["reg-001"]["net_merchandise_sales"] == REF_GOLDEN["net_merchandise_sales"]


def test_P01_TEST_07_RECOVER_later_shipment_lands_in_new_region_and_regions_sum_to_total(client, conn):
    seed_db(conn, _territory_inputs())
    settle(client, "shp-001")
    # shipped exactly at the version boundary (2026-04-01T00:00Z): effective_from <= shipped date -> reg-002
    late = order_bundle("late", "cust-001", "2026-04-01T00:00:00Z", [("prod-001", 1, "100.00")], "5.00")
    assert ingest(client, late).status_code == 200
    settle(client, "shp-late")
    g = groups(client, "region")
    assert sorted(g) == ["reg-001", "reg-002"]
    assert g["reg-001"] == golden_baseline()                   # earlier shipment did not move
    # reference: 1 x 100.00, no discount, cost 60, freight 5 -> net 100, CM 35
    assert (g["reg-002"]["net_merchandise_sales"], g["reg-002"]["cogs"], g["reg-002"]["contribution_margin"]) \
        == ("100.00", "60.00", "35.00")
    total = totals(client)
    assert D(total["net_merchandise_sales"]) == sum_money(g, "net_merchandise_sales") == D("325.00")
    assert D(total["contribution_margin"]) == sum_money(g, "contribution_margin") == D("105.00")
    assert total["eligible_shipment_lines"] == sum(x["eligible_shipment_lines"] for x in g.values()) == 3


# === P01-TEST-08 quota joined to daily transactions ===================================

def test_P01_TEST_08_DETECT_quota_is_period_grain_and_no_api_path_joins_it_to_transactions(client, conn):
    seed_db(conn, golden_inputs())
    # (1) the generated snapshot carries quotas at (rep, period) grain, one row each, no transaction keys
    rows = json.loads((SNAPSHOT / "quotas.json").read_text())["rows"]
    assert len(rows) == 64
    assert len({(q["rep_id"], q["period"]) for q in rows}) == len(rows)
    assert all(not ({"order_id", "shipment_id", "shipment_line_id", "shipped_at"} & set(q)) for q in rows)
    # (2) the backend does not expose quotas: no table, no entity read, no quota path, no quota metric
    assert conn.execute("SELECT count(*) AS n FROM information_schema.tables "
                        "WHERE table_schema = current_schema() AND table_name ILIKE '%quota%'").fetchone()["n"] == 0
    r = client.get(f"{PREFIX}/data/quotas")
    assert r.status_code == 404 and r.json()["error"]["details"][0]["rule_id"] == "ENTITY_UNKNOWN"
    paths = client.get(f"{PREFIX}/openapi.json").json()["paths"]
    assert not [p for p in paths if "quota" in p.lower() or "attainment" in p.lower()]
    m = totals(client)
    assert not [k for k in m if "quota" in k or "attainment" in k]
    # (3) the golden totals are exactly one pass over shipment lines (a quota-by-row multiply would change them)
    assert m == golden_baseline()


@pytest.mark.skip(reason="BLOCKED: no quota attainment calculation in the slice (D-05 quota attainment "
                  "needs a quotas table, a read and a (rep, period) join; none exists)")
def test_P01_TEST_08_RECOVER_quota_attainment_equals_eligible_sales_over_quota_at_period_grain():
    raise AssertionError("unreachable: blocked")


# === P01-TEST-11 filter excludes unassigned region ====================================

def _unassigned_inputs() -> dict[str, Any]:
    inputs = golden_inputs()
    # cust-u's only version starts after its shipment, so shipped_at has no effective version
    inputs["customers"].append(customer("cust-u", "reg-u", "2026-03-20"))
    return merge(inputs, order_bundle("u", "cust-u", "2026-03-10T09:00:00Z", [("prod-002", 2, "40.00")], "6.00"))


def test_P01_TEST_11_DETECT_unassigned_group_exists_and_groups_sum_to_the_ungrouped_total(client, conn):
    seed_db(conn, _unassigned_inputs())
    settle(client, "shp-001")
    settle(client, "shp-u")
    window = {"from": "2026-03-01", "to": "2026-04-01"}
    for params in ({}, window):
        g = groups(client, "region", **params)
        assert sorted(g) == ["UNASSIGNED", "reg-001"], params
        total = totals(client, **params)
        # reference from raw facts: UNASSIGNED = 2 x 40 gross, cost 2 x 20, freight 6 -> net 80, CM 34
        assert g["UNASSIGNED"]["net_merchandise_sales"] == "80.00"
        assert g["UNASSIGNED"]["contribution_margin"] == "34.00"
        assert g["reg-001"] == golden_baseline()
        for field, want in (("gross_sales", "330.00"), ("net_merchandise_sales", "305.00"), ("cogs", "180.00"),
                            ("shipping_cost", "21.00"), ("contribution_margin", "104.00")):
            assert D(total[field]) == sum_money(g, field) == D(want), (params, field)
        assert total["eligible_shipment_lines"] == sum(x["eligible_shipment_lines"] for x in g.values()) == 3
    # a window that contains only the unassigned shipment's day still shows the row
    only = groups(client, "region", **{"from": "2026-03-10", "to": "2026-03-11"})
    assert sorted(only) == ["UNASSIGNED", "reg-001"]


def test_P01_TEST_11_RECOVER_adding_a_customer_version_via_c01_moves_the_line_out_of_unassigned(client, conn):
    seed_db(conn, _unassigned_inputs())
    settle(client, "shp-001")
    settle(client, "shp-u")
    before = snapshot_counts(conn)
    r = ingest(client, {"customers": [customer("cust-u", "reg-u", "2026-01-01")]})
    assert r.status_code == 200 and r.json()["result"]["counts"]["customers"]["inserted"] == 1
    assert snapshot_counts(conn) == {**before, "customers": before["customers"] + 1}
    g = groups(client, "region")
    assert sorted(g) == ["reg-001", "reg-u"] and "UNASSIGNED" not in g
    assert g["reg-u"]["net_merchandise_sales"] == "80.00" and g["reg-001"] == golden_baseline()
    assert D(totals(client)["net_merchandise_sales"]) == sum_money(g, "net_merchandise_sales") == D("305.00")


# === P01-TEST-12 scenario overwrites published actuals ================================

def _entity_hash() -> str:
    """sha256 over canonical rows of every entity file, in sorted entity-name order (generator rule)."""
    h = hashlib.sha256()
    for f in sorted(SNAPSHOT.glob("*.json"), key=lambda p: p.stem):
        if f.stem in ("manifest", "injection-manifest"):
            continue
        rows = json.loads(f.read_text())["rows"]
        h.update(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
    return h.hexdigest()


def _file_digests() -> dict[str, str]:
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(SNAPSHOT.glob("*.json"))}


def test_P01_TEST_12_DETECT_scenario_delta_on_a_copy_leaves_the_published_baseline_unchanged():
    inputs = json.loads((GOLDEN / "inputs.json").read_text())
    pinned = copy.deepcopy(inputs)
    digests = _file_digests()
    res = run_pipeline(inputs, include_returns=True)
    actual = copy.deepcopy(res.metrics)
    assert actual == expected()["states"]["after_return"]["metrics"]
    facts_before = list(res.facts)

    # D-07 scenario on a deep copy: discounts +10 %, shipping -20 %
    copy_facts = copy.deepcopy(res.facts)
    scen = [dataclasses.replace(f, allocated_discount=f.allocated_discount * D("1.10"),
                                freight=f.freight * D("0.80")) for f in copy_facts]
    est = compute_metrics(scen)
    # reference: gross 250; discounts 25 x 1.10 = 27.50; credit 90 -> net 132.50; cogs 140 - 60 = 80;
    # shipping 15 x 0.80 = 12.00; CM = 132.50 - 80 - 12 = 40.50 (baseline CM is 70 - 90 + 60 = 40.00)
    assert (est["allocated_discounts"], est["net_merchandise_sales"], est["shipping_cost"],
            est["contribution_margin"]) == ("27.50", "132.50", "12.00", "40.50")
    assert actual["contribution_margin"] == "40.00"
    # the baseline object, its facts and the inputs are untouched
    assert res.metrics == actual and list(res.facts) == facts_before
    assert [f.allocated_discount for f in res.facts] == [f.allocated_discount for f in facts_before]
    assert inputs == pinned
    assert run_pipeline(copy.deepcopy(pinned), include_returns=True).metrics == actual
    assert _file_digests() == digests                            # no published file was written


def test_P01_TEST_12_RECOVER_published_manifest_hash_equals_the_hash_of_the_entity_files():
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text())
    assert _entity_hash() == manifest["dataset_hash"]
    golden_manifest = json.loads((SNAPSHOT / "golden" / "manifest.json").read_text())
    assert hashlib.sha256((GOLDEN / "inputs.json").read_bytes()).hexdigest() == golden_manifest["dataset_hash"]


def test_P01_TEST_12_DETECT_backend_has_no_scenario_endpoint_so_actuals_cannot_be_written_by_one(client):
    paths = client.get(f"{PREFIX}/openapi.json").json()["paths"]
    assert not [p for p in paths if "scenario" in p.lower()]
    assert sorted(p for p, v in paths.items() if "post" in v) == sorted(
        f"{PREFIX}/commands/{c}" for c in ("ingest-sales", "resolve-historical-cost",
                                           "post-a-partial-return", "allocate-freight"))


@pytest.mark.skip(reason="BLOCKED: backend C07/C08 (scenario commands) are extensions and not implemented; "
                  "covered at the domain/snapshot level by the two P01-TEST-12 tests above")
def test_P01_TEST_12_RECOVER_backend_scenario_commands_never_write_historical_rows():
    raise AssertionError("unreachable: blocked")


# === Replay of data/injection-events.json on the seeded generated snapshot ============

def _snapshot_inputs() -> dict[str, Any]:
    data: dict[str, Any] = {"contract": "v1", "reporting_currency": "USD"}
    for f in SNAPSHOT.glob("*.json"):
        if f.stem in ("manifest", "injection-manifest", "quotas"):
            continue
        data[f.stem] = json.loads(f.read_text())["rows"]
    return data


def _data_of(resp) -> dict[str, Any]:
    return resp.json()["data"]


def test_P01_TEST_injection_events_replay_on_the_seeded_generated_snapshot(client, conn):
    inputs = _snapshot_inputs()
    out = seed_db(conn, inputs)
    assert out["skipped"] > 0                                    # INJ-01: malformed-currency orders were refused at seed
    events = json.loads(EVENTS.read_text())["events"]
    base_metrics = _data_of(client.get(f"{PREFIX}/metrics"))
    base_counts = snapshot_counts(conn)
    audits = count(conn, "audit_events")

    # --- INJ-05 duplicate shipment-line row through C01 --------------------------------
    dup = next(e for e in events if e["command"] == "ingest-sales")
    sl_id = dup["input"]["batch"]["shipment_lines"][0]["shipment_line_id"]
    first = command(client, "ingest-sales", dup["input"], key="inj05-dup")
    assert first.status_code == 200 and first.json()["status"] == "partial"
    # the API rejects it as ORPHAN_REFERENCE (a batch must carry its own parents), keeping the raw row
    assert first.json()["result"]["rejected_records"] == [
        {"entity": "shipment_lines", "id": sl_id, "reason_code": "ORPHAN_REFERENCE"}]
    assert first.json()["result"]["counts"]["shipment_lines"]["inserted"] == 0
    assert snapshot_counts(conn) == base_counts
    again = command(client, "ingest-sales", dup["input"], key="inj05-dup")      # same key, same payload
    assert again.status_code == 200 and again.headers["Idempotent-Replay"] == "true"
    assert again.json() == first.json()                           # stored result is returned, not a 409
    # self-contained replay (order, line, shipment, and the duplicated shipment line): inserts nothing
    sl = next(r for r in inputs["shipment_lines"] if r["shipment_line_id"] == sl_id)
    ln = next(r for r in inputs["order_lines"] if r["line_id"] == sl["line_id"])
    shp = next(r for r in inputs["shipments"] if r["shipment_id"] == sl["shipment_id"])
    od = next(r for r in inputs["orders"] if r["order_id"] == ln["order_id"])
    full = command(client, "ingest-sales", {"batch": {"contract": "v1", "orders": [od], "order_lines": [ln],
                                                      "shipments": [shp], "shipment_lines": [sl]}},
                   key="inj05-dup-full")
    assert full.status_code == 200 and full.json()["status"] == "accepted"
    assert all(c["inserted"] == 0 for c in full.json()["result"]["counts"].values())
    assert snapshot_counts(conn) == base_counts
    assert conn.execute("SELECT count(*) AS n FROM shipment_lines WHERE shipment_line_id = %s",
                        (sl_id,)).fetchone()["n"] == 1

    # --- INJ-05 double C04 -------------------------------------------------------------
    c04 = [e for e in events if e["command"] == "allocate-freight"]
    assert len(c04) == 1 and c04[0]["repeat"] == 2
    shp_id = c04[0]["input"]["shipment_id"]
    ok = command(client, "allocate-freight", c04[0]["input"], key="inj05-c04-a")
    assert ok.status_code == 200
    shipping = conn.execute("SELECT shipping_cost FROM shipments WHERE shipment_id = %s", (shp_id,)).fetchone()
    alloc_rows = conn.execute("SELECT shipment_line_id, amount FROM freight_allocations WHERE shipment_id = %s "
                              "ORDER BY shipment_line_id", (shp_id,)).fetchall()
    assert alloc_rows and sum(r["amount"] for r in alloc_rows) == shipping["shipping_cost"]   # residual 0.00
    n_alloc, audits_ok = count(conn, "freight_allocations"), count(conn, "audit_events")
    second = command(client, "allocate-freight", c04[0]["input"], key="inj05-c04-b")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "FREIGHT_ALREADY_ALLOCATED"
    assert count(conn, "freight_allocations") == n_alloc and count(conn, "audit_events") == audits_ok
    assert conn.execute("SELECT shipment_line_id, amount FROM freight_allocations WHERE shipment_id = %s "
                        "ORDER BY shipment_line_id", (shp_id,)).fetchall() == alloc_rows
    replay = command(client, "allocate-freight", c04[0]["input"], key="inj05-c04-a")    # same key as the first
    assert replay.status_code == 200 and replay.headers["Idempotent-Replay"] == "true"

    # --- INJ-06 four returns exceeding the remaining quantity, INJ-07 negative credit ----
    rets = [e for e in events if e["command"] == "post-a-partial-return"]
    assert [e["expected_error_code"] for e in rets] == ["RETURN_EXCEEDS_REMAINING"] * 4 + ["CREDIT_SIGN_REVERSED"]
    top_codes = []
    for i, e in enumerate(rets):
        rows_before = (count(conn, "returns"), count(conn, "audit_events"))
        v_before = conn.execute("SELECT version FROM shipment_lines WHERE shipment_line_id = %s",
                                (e["input"]["shipment_line_id"],)).fetchone()["version"]
        r = command(client, "post-a-partial-return", e["input"], key=f"inj06-{i}")
        assert r.status_code == 422, (e["injection"], r.text)
        err = r.json()["error"]
        assert err["details"][0]["rule_id"] == e["expected_error_code"]
        top_codes.append(err["code"])
        assert (count(conn, "returns"), count(conn, "audit_events")) == rows_before     # nothing written
        assert conn.execute("SELECT version FROM shipment_lines WHERE shipment_line_id = %s",
                            (e["input"]["shipment_line_id"],)).fetchone()["version"] == v_before
    # the code carried at the top level of the envelope (the specific one is in details[0].rule_id)
    assert set(top_codes) == {"VALIDATION_FAILED"}

    # --- the rejected events changed nothing else ---------------------------------------
    after_counts = snapshot_counts(conn)
    assert after_counts == {**base_counts, "freight_allocations": base_counts["freight_allocations"] + len(alloc_rows)}
    # audit rows: the two C01 replays (each logs its own ingest event) + the one successful C04; the five
    # rejected C03 commands and the 409 C04 wrote none
    assert count(conn, "audit_events") == audits + 3
    assert conn.execute("SELECT action, count(*) AS n FROM audit_events GROUP BY action ORDER BY action").fetchall() \
        == [{"action": "allocate-freight", "n": 1}, {"action": "ingest-sales", "n": 2}]
    assert _data_of(client.get(f"{PREFIX}/metrics")) == base_metrics       # metrics do not depend on allocation rows
