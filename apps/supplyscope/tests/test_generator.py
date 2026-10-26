"""Synthetic data generator: determinism, shapes, sizes, consistency, injected defects, designed relationships.

The generator (data/generate.py) is stdlib only and shares no code with the domain; these tests run the domain over its
output (ingest, pipeline, group metrics, supplier reliability, forecasts) to show that every designed relationship and
injected defect is detectable. A database test seeds the dataset through data/seed.py (skipped without DATABASE_URL).
"""
from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("ss_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["ss_generate"] = gen
_spec.loader.exec_module(gen)

from supplyscope import run_pipeline  # noqa: E402
from supplyscope.demand import censored_vs_latent, compare_policies  # noqa: E402
from supplyscope.errors import DomainError  # noqa: E402
from supplyscope.forecast import daily_series, forecast_demand, naive, seasonal_naive  # noqa: E402
from supplyscope.ingest import receipt_reason, screen_movements  # noqa: E402
from supplyscope.metrics import compute_metrics, group_metrics  # noqa: E402
from supplyscope.models import parse_row, parse_ts  # noqa: E402
from supplyscope.money import cost_in_force  # noqa: E402
from supplyscope.replenishment import replenish  # noqa: E402
from supplyscope.suppliers import on_time_rate, promised_date  # noqa: E402

SEED = 20261026
VERSION = f"ss-{SEED}-20261026"
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
BUDGET = 5_000_000


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen")
    out, meta = tmp / "out", tmp / "meta"
    manifest = gen.write_all(SEED, out, meta)
    rows = {}
    for name in gen.ENTITIES:
        doc = json.loads((out / f"{name}.json").read_text())
        assert doc["entity"] == name and doc["dataset_version"] == VERSION
        rows[name] = doc["rows"]
    return {"out": out, "meta": meta, "manifest": manifest, "rows": rows,
            "inj": {i["id"]: i for i in json.loads((meta / "injection-manifest.json").read_text())["injections"]},
            "events": {e["event_id"]: e for e in json.loads((meta / "injection-events.json").read_text())["events"]}}


@pytest.fixture(scope="module")
def inputs(built):
    return {"contract_version": 1, "as_of": gen.AS_OF, "window_start": "2025-04-01T00:00:00Z", **built["rows"]}


@pytest.fixture(scope="module")
def result(inputs):
    return run_pipeline(inputs)           # the accepted population in the default state (no fixture state)


def _day(stamp: str) -> str:
    return stamp[:10]


# --- determinism, files, manifest -------------------------------------------------------------------------------
def test_deterministic_across_runs_and_hash_seeds(built, tmp_path):
    again = gen.write_all(SEED, tmp_path / "out", tmp_path / "meta")
    assert again["dataset_hash"] == built["manifest"]["dataset_hash"]
    for name in gen.ENTITIES:
        assert (tmp_path / "out" / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes()
    assert (tmp_path / "meta" / "injection-events.json").read_bytes() == (built["meta"] / "injection-events.json").read_bytes()
    other = gen.write_all(SEED + 1, tmp_path / "o2", tmp_path / "m2")
    assert other["dataset_hash"] != again["dataset_hash"]


def test_manifest_shape_and_hash(built):
    m = built["manifest"]
    assert m["dataset_version"] == VERSION and m["contract_version"] == "v1"
    assert set(m) >= {"dataset_version", "dataset_hash", "generated_at", "contract_version", "generator", "row_counts",
                      "designed_relationships", "injection_manifest"}
    assert m["generator"]["seed"] == SEED and m["generator"]["name"] == "generate.py"
    assert m["generator"]["parameters"]["days"] == 548
    assert m["row_counts"] == {n: len(built["rows"][n]) for n in gen.ENTITIES}
    assert json.loads((built["out"] / "manifest.json").read_text())["dataset_hash"] == m["dataset_hash"]
    h = hashlib.sha256()
    for name in sorted(gen.ENTITIES):
        h.update(json.dumps(built["rows"][name], sort_keys=True, separators=(",", ":")).encode())
    assert h.hexdigest() == m["dataset_hash"]
    assert len(m["designed_relationships"]) == 3
    assert (built["out"] / "injection-manifest.json").read_bytes() == (built["meta"] / "injection-manifest.json").read_bytes()
    assert {e["injection"] for e in built["events"].values()} <= set(built["inj"])


def test_shapes_equal_the_golden_field_names(built):
    columns = _seed_columns()
    for name, g_rows in GOLDEN.items():
        if name not in gen.ENTITIES or not g_rows:
            continue
        want = set(g_rows[0])
        for row in built["rows"][name]:
            assert want <= set(row) <= set(columns[name]), name
    for name in gen.ENTITIES:              # entities that are empty in the golden fixture use the table columns
        for row in built["rows"][name][:50]:
            assert set(row) <= set(columns[name]), name


def _seed_columns() -> dict[str, tuple[str, ...]]:
    from data import seed
    return seed.COLUMNS


# --- spec sizes --------------------------------------------------------------------------------------------------
def test_counts_within_spec(built):
    r = built["rows"]
    assert len(r["products"]) == 60 and len(r["locations"]) == 3 and len(r["suppliers"]) == 4
    assert collections.Counter(p["abc_class"] for p in r["products"]) == {"A": 8, "B": 16, "C": 36}
    assert all(5 <= s["quoted_lead_days"] <= 21 for s in r["suppliers"])
    assert min(s["quoted_lead_days"] for s in r["suppliers"]) == 5 and max(s["quoted_lead_days"] for s in r["suppliers"]) == 21
    days = {_day(s["sold_at"]) for s in r["sales"]}
    assert min(days) >= "2025-04-01" and max(days) <= "2026-09-30" and len(days) >= 540     # 18 months, daily
    assert len(r["inventory_movements"]) >= 10000 and len(r["sales"]) >= 8500
    assert len(built["inj"]["INJ-05"]["record_ids"]) == 12                                    # ~12 intermittent SKUs
    assert len({p["product_id"] for p in r["promotions"]}) == 15                              # promotions on ~15 SKUs
    assert len(r["calendar_closures"]) == 1
    c = r["calendar_closures"][0]
    assert (date.fromisoformat(c["closed_to"]) - date.fromisoformat(c["closed_from"])).days + 1 == 14
    assert {c["calendar_id"]} == {s["calendar_id"] for s in r["suppliers"] if s["supplier_id"] == "sup-02"}
    sc = r["policy_scenarios"]
    assert {(s["service_target"], s["unmet_policy"]) for s in sc} == {(t, u) for t in ("0.95", "0.98")
                                                                       for u in ("lost_sale", "backlog")}
    assert {s["seed"] for s in sc} == {SEED}                                                   # common random numbers
    steps = {c["effective_from"] for c in r["cost_versions"]}
    assert len(steps) == 1 and len({c["product_id"] for c in r["cost_versions"]}) == len(r["cost_versions"])
    assert len(r["replenishment_params"]) == 60
    assert any(l["ordered_quantity"] > sum(x["received_quantity"] for x in r["receipts"] if x["po_line_id"] == l["po_line_id"])
               for l in r["purchase_order_lines"][:300])                                       # partial receipts exist


def test_size_under_five_megabytes_and_aggregated_rows(built):
    total = sum(p.stat().st_size for p in built["out"].glob("*.json"))
    assert total < BUDGET, total
    keys = collections.Counter((s["product_id"], s["location_id"], _day(s["sold_at"])) for s in built["rows"]["sales"])
    assert max(keys.values()) == 1                                    # one sale row per SKU x location x day
    mv = built["rows"]["inventory_movements"]
    kinds = collections.Counter(m["movement_type"] for m in mv)
    assert kinds["sale"] >= len(built["rows"]["sales"]) and kinds["adjustment"] == 60
    assert kinds["receipt"] == len(built["rows"]["receipts"]) - 1 + 1       # every receipt but the injected one, +1 replay
    pairs = {(p["product_id"], p["location_id"]) for p in built["rows"]["replenishment_params"]}
    assert len(pairs) == 60 and {(s["product_id"], s["location_id"]) for s in built["rows"]["sales"]} <= pairs


# --- the pipeline over the dataset --------------------------------------------------------------------------------
def test_pipeline_completes_and_rejects_exactly_the_injected_rows(built, result):
    rej = [r for r in result.rejected if r["entity"] != "latent_demand"]
    inj = built["inj"]
    assert sorted((r["entity"], r["id"], r["reason_code"]) for r in rej) == sorted(
        [("inventory_movements", i, "DUPLICATE_MOVEMENT_ID") for i in inj["INJ-01"]["record_ids"]]
        + [("receipts", i, "RECEIPT_BEFORE_ORDER") for i in inj["INJ-02"]["record_ids"]])
    # the first occurrence of each replayed id is kept
    kept = {m.movement_id for m in result.population.inventory_movements}
    assert set(inj["INJ-01"]["record_ids"]) <= kept
    # latent_demand rows are keyed by product in ingest (row_id), so a second row of a product is DUPLICATE_ID there:
    # a limitation of the domain's ingest (documented in README-generator.md); no other reason may appear
    assert {r["reason_code"] for r in result.rejected if r["entity"] == "latent_demand"} <= {"DUPLICATE_ID"}
    counts = result.counts
    for name in ("products", "sales", "purchase_orders", "purchase_order_lines", "promotions", "forecast_points"):
        assert counts[name] == {"accepted": len(built["rows"][name]), "rejected": 0}, name
    assert counts["inventory_movements"]["rejected"] == 3 and counts["receipts"]["rejected"] == 1
    m = result.metrics
    assert m["negative_stock"] is False and m["running_stock_min"] == 0 and result.flags == []
    assert m["observed_days"] == 548 and not m["empty_population"] and m["working_capital"] is not None
    assert m["on_hand"] > 0 and m["reserved"] > 0 and m["available"] == m["on_hand"] - m["reserved"]


def test_stock_never_exceeds_location_capacity(built):
    cap = {l["location_id"]: l["storage_capacity"] for l in built["rows"]["locations"]}
    seen: set[str] = set()
    per_day: dict[tuple[str, str], int] = collections.defaultdict(int)
    for m in built["rows"]["inventory_movements"]:
        if m["movement_id"] in seen:
            continue
        seen.add(m["movement_id"])
        per_day[(m["location_id"], _day(m["event_at"]))] += m["quantity_delta"]
    for loc in cap:
        run, peak = 0, 0
        for (l, d), delta in sorted(per_day.items()):
            if l == loc:
                run += delta
                assert run >= 0
                peak = max(peak, run)
        assert peak <= cap[loc]


# --- latent vs observed demand -------------------------------------------------------------------------------------
def _observed_latent(rows, product_id):
    loc = next(p["location_id"] for p in rows["replenishment_params"] if p["product_id"] == product_id)
    obs = {_day(s["sold_at"]): s["quantity"] for s in rows["sales"] if s["product_id"] == product_id}
    lat = {l["demand_date"]: l["latent_quantity"] for l in rows["latent_demand"] if l["product_id"] == product_id}
    unmet = {_day(x["occurred_at"]): x["quantity"] for x in rows["lost_sales"] if x["product_id"] == product_id}
    unmet.update({_day(x["opened_at"]): x["quantity"] for x in rows["backorders"] if x["product_id"] == product_id})
    return loc, obs, lat, unmet


def test_latent_differs_from_observed_exactly_on_stockout_days(built):
    rows = built["rows"]
    tracked = sorted({l["product_id"] for l in rows["latent_demand"]})
    assert len(tracked) >= 25
    censored_total = 0
    for pid in tracked:
        _, obs, lat, unmet = _observed_latent(rows, pid)
        days = set(obs) | set(lat)
        differ = {d for d in days if obs.get(d, 0) != lat.get(d, 0)}
        assert differ == set(unmet), pid                         # exactly the days with unmet demand
        for d in differ:
            assert obs.get(d, 0) < lat[d] and lat[d] - obs.get(d, 0) == unmet[d]
        censored_total += len(differ)
    assert censored_total > 100


def test_domain_censored_vs_latent_agrees_with_the_files(built, result):
    rows = built["rows"]
    pop = result.population
    latent = [parse_row("latent_demand", r) for r in rows["latent_demand"]]
    pid = next(p["product_id"] for p in rows["products"] if p["abc_class"] == "A"
               and next(x["location_id"] for x in rows["replenishment_params"] if x["product_id"] == p["product_id"]) == "loc-02")
    loc, obs, lat, unmet = _observed_latent(rows, pid)
    out = censored_vs_latent(pop.sales, pop.backorders, pop.lost_sales, latent, pid, loc, date(2025, 4, 1),
                             date(2026, 9, 30), result.as_of)
    assert out["censored_days"] == sorted(unmet)
    assert out["observed_total"] == sum(obs.values()) and out["latent_total"] == sum(lat.values())
    assert out["latent_total"] - out["observed_total"] == sum(unmet.values())
    assert {d for d, q in out["observed"].items() if q != out["latent"].get(d, 0)} == set(unmet)


def test_unmet_demand_is_a_backorder_or_a_lost_sale_never_both(built):
    rows = built["rows"]
    bo = {(b["product_id"], b["location_id"], _day(b["opened_at"])) for b in rows["backorders"]}
    ls = {(b["product_id"], b["location_id"], _day(b["occurred_at"])) for b in rows["lost_sales"]}
    assert bo and ls and not bo & ls
    assert {b[1] for b in bo} == {gen.BACKLOG_LOCATION} and gen.BACKLOG_LOCATION not in {x[1] for x in ls}


def test_backlog_fills_are_sale_movements_that_close_backorders(built):
    rows = built["rows"]
    sale_qty = collections.Counter()
    for m in rows["inventory_movements"][:-3]:
        if m["movement_type"] == "sale" and m["location_id"] == gen.BACKLOG_LOCATION:
            sale_qty[m["product_id"]] -= m["quantity_delta"]
    sold = collections.Counter()
    for s in rows["sales"]:
        if s["location_id"] == gen.BACKLOG_LOCATION:
            sold[s["product_id"]] += s["quantity"]
    closed = collections.Counter()
    for b in rows["backorders"]:
        if b["closed_at"]:
            closed[b["product_id"]] += b["quantity"]
    for pid in sale_qty:
        assert sale_qty[pid] - sold[pid] == closed[pid]


# --- designed relationships ----------------------------------------------------------------------------------------
def test_supplier_sup03_has_the_lowest_on_time_rate(result):
    pop = result.population
    rates = {}
    for sid in ("sup-01", "sup-02", "sup-03", "sup-04"):
        o = on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, pop.calendar_closures,
                         result.as_of, sid)
        assert o["eligible_receipts"] > 150
        rates[sid] = float(o["on_time_rate"])
    assert min(rates, key=rates.get) == "sup-03"
    assert 0.25 <= 1 - rates["sup-03"] <= 0.40                  # late about 30 %
    assert all(1 - v < 0.22 for k, v in rates.items() if k != "sup-03")
    by_supplier = group_metrics(pop, "supplier", result.as_of, result.window)
    assert set(by_supplier) == {"sup-01", "sup-02", "sup-03", "sup-04"}


def test_class_a_promoted_skus_are_censored_during_stockouts(built, result):
    rows = built["rows"]
    promoted = {p["product_id"] for p in rows["promotions"]}
    a_promoted = [p["product_id"] for p in rows["products"] if p["abc_class"] == "A" and p["product_id"] in promoted]
    assert len(a_promoted) == 8
    by_product = group_metrics(result.population, "product", result.as_of, result.window)
    with_stockouts = [pid for pid in a_promoted if float(by_product[pid]["stockout_days"]) > 0]
    assert len(with_stockouts) >= 6
    # the stockouts concentrate inside promotion windows: more unmet demand per promoted day than per other day
    promo_days = collections.defaultdict(set)
    for p in rows["promotions"]:
        d, end = date.fromisoformat(_day(p["starts_at"])), date.fromisoformat(_day(p["ends_at"]))
        while d <= end:
            promo_days[p["product_id"]].add(d.isoformat())
            d += timedelta(days=1)
    inside = outside = 0
    for pid in with_stockouts:
        _, _, _, unmet = _observed_latent(rows, pid)
        for d, q in unmet.items():
            if d in promo_days[pid]:
                inside += 1
            else:
                outside += 1
    assert inside / (30 * len(with_stockouts)) > outside / ((548 - 30) * len(with_stockouts))
    # promotion outcomes are present but separate: realised_uplift is an outcome, planned_uplift the schedule
    assert all(p["realised_uplift"] is not None and p["announced_at"] < p["starts_at"] for p in rows["promotions"])


def test_loc02_is_the_capacity_bound_location(built, result):
    by_loc = group_metrics(result.population, "location", result.as_of, result.window)
    fill = {k: float(v["fill_rate"]) for k, v in by_loc.items()}
    stock = {k: float(v["stockout_days"]) for k, v in by_loc.items()}
    assert min(fill, key=fill.get) == "loc-02" and max(stock, key=stock.get) == "loc-02"
    assert fill["loc-02"] < 0.92 < min(fill["loc-01"], fill["loc-03"])
    caps = {l["location_id"]: l["storage_capacity"] for l in built["rows"]["locations"]}
    demand = collections.Counter()
    for p in built["rows"]["replenishment_params"]:
        demand[p["location_id"]] += p["target_position"]
    assert caps["loc-02"] < 0.7 * demand["loc-02"] and caps["loc-01"] > 1.5 * demand["loc-01"]
    assert "loc-02" in built["manifest"]["designed_relationships"][2]


# --- injected defects ----------------------------------------------------------------------------------------------
def test_partial_receipt_flagged_complete_stays_open(built, result):
    pop = result.population
    inj = built["inj"]["INJ-03"]
    o = on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, pop.calendar_closures,
                     result.as_of, "sup-03")
    orders = {x["purchase_order_id"]: x for x in built["rows"]["purchase_orders"]}
    lines = {x["po_line_id"]: x for x in built["rows"]["purchase_order_lines"]}
    assert len(inj["record_ids"]) == 2
    for lid in inj["record_ids"]:
        assert orders[lines[lid]["purchase_order_id"]]["status"] == "closed"
        assert lid in o["partially_received_open_lines"] and lid in o["open_lines"]
    for d in inj["detail"]:
        assert 0 < d["received"] < d["ordered"]


def test_lead_time_spanning_the_closure_is_on_time_on_the_supplier_calendar(built, result):
    pop = result.population
    spans = built["inj"]["INJ-04"]["detail"]
    assert spans
    orders = {o.purchase_order_id: o for o in pop.purchase_orders}
    sup = {s.supplier_id: s for s in pop.suppliers}["sup-02"]
    for s in spans:
        o = orders[s["purchase_order_id"]]
        promised = promised_date(o, sup, pop.calendar_closures)
        assert promised.isoformat() == s["promised"]
        assert s["calendar_days"] > sup.quoted_lead_days + 5          # a calendar count would call this very late
        assert date.fromisoformat(s["received"]) >= promised          # but it is not earlier than the open-day count


def test_zero_demand_folds_of_intermittent_skus_are_disclosed(built, result):
    ids = built["inj"]["INJ-05"]["record_ids"]
    share = built["inj"]["INJ-05"]["detail"]["zero_demand_day_share"]
    assert all(0.85 <= share[i] <= 0.97 for i in ids)
    pop = result.population
    loc = {p.product_id: p.location_id for p in pop.replenishment_params}
    notes = 0
    for pid in ids[:4]:
        f = forecast_demand(pop.sales, pop.promotions, pid, loc[pid], parse_ts("2026-09-16T23:59:59Z"), 7)
        notes += "ZERO_DEMAND_FOLDS_DISCLOSED" in f.notes
    assert notes == 4


def test_unit_cost_step_inside_a_valuation_period(built, result):
    pop = result.population
    versions = [v for v in pop.cost_versions]
    assert len(versions) == 15 and {v.effective_from for v in versions} == {parse_ts("2026-02-01T00:00:00Z")}
    prods = {p.product_id: p for p in pop.products}
    v = versions[0]
    base = prods[v.product_id].unit_cost
    mine = [x for x in versions if x.product_id == v.product_id]
    assert cost_in_force(base, mine, date(2026, 1, 31)) == base
    assert cost_in_force(base, mine, date(2026, 2, 1)) == v.unit_cost > base
    first_after = next(l for l in pop.purchase_order_lines if l.product_id == v.product_id
                       and {o.purchase_order_id: o for o in pop.purchase_orders}[l.purchase_order_id].ordered_at
                       >= parse_ts("2026-02-01T00:00:00Z"))
    assert first_after.unit_cost == v.unit_cost                     # orders carry the cost in force at order time


def test_reserved_stock_is_not_subtracted_twice_from_the_position(built, result):
    pop = result.population
    ev = built["events"]["EV-04"]
    pid, loc = ev["input"]["product_id"], ev["input"]["location_id"]
    m = compute_metrics(pop, result.as_of, result.window, None, products=[pid], locations=[loc])
    exp = ev["expected"]
    assert m["reserved"] == exp["reserved"] > 0 and m["on_hand"] == exp["on_hand"]
    assert m["on_order"] == exp["on_order"] and m["backorders"] == exp["backorders"]
    assert m["available"] == exp["available"]
    assert m["inventory_position"] == exp["inventory_position"] != ev["forbidden"]["inventory_position"]
    assert m["inventory_position"] == m["on_hand"] + m["on_order"] - m["backorders"]


# --- the replay-only events ------------------------------------------------------------------------------------------
def test_events_replay_against_the_domain(built, result):
    ev = built["events"]
    assert sorted(ev) == [f"EV-0{i}" for i in range(1, 8)]
    rows = ev["EV-01"]["input"]["input"]["movements"]
    prods = [p.product_id for p in result.population.products]
    locs = [l.location_id for l in result.population.locations]
    acc, rej = screen_movements(rows, prods, locs)
    assert not acc and [r.reason_code for r in rej] == ["DUPLICATE_MOVEMENT_CONFLICT"] * 2
    # EV-02 / EV-06: the arrival dates are before the order / before the quoted lead time
    pop = result.population
    lines = {l.po_line_id: l for l in pop.purchase_order_lines}
    orders = {o.purchase_order_id: o for o in pop.purchase_orders}
    e2 = ev["EV-02"]["input"]["input"]
    line = lines[e2["po_line_id"]]
    fake = parse_row("receipts", {"receipt_id": "x", "po_line_id": line.po_line_id, "location_id": e2["location_id"],
                                  "received_quantity": e2["quantity"], "received_at": e2["at"]})
    assert receipt_reason(fake, line, orders[line.purchase_order_id], 0) == "RECEIPT_BEFORE_ORDER"
    e6 = ev["EV-06"]["input"]["input"]
    l6 = lines[e6["po_line_id"]]
    o6 = orders[l6.purchase_order_id]
    sup = {s.supplier_id: s for s in pop.suppliers}[o6.supplier_id]
    assert parse_ts(e6["at"]).date() < promised_date(o6, sup, pop.calendar_closures)
    assert parse_ts(e6["at"]) >= o6.ordered_at                           # not before the order: a lead-time defect only
    # EV-03: the closed status does not complete the line (see the partial receipt test); EV-05: seeds differ
    setup = [parse_row("policy_scenarios", s) for s in ev["EV-05"]["setup"]["policy_scenarios"]]
    with pytest.raises(DomainError) as err:
        compare_policies(setup, 30, 5.0, 3, 7, 40, 100, 24, 12, 50)
    assert err.value.code == ev["EV-05"]["expected_reason"] == "POLICY_SEED_MISMATCH"
    e7 = ev["EV-07"]
    r = replenish(e7["input"]["position"], 0, 0, e7["input"]["reorder_point"], e7["input"]["target_position"],
                  e7["input"]["moq"], e7["input"]["pack_size"])
    assert {"raw_order": r.raw_order, "order_after_moq": r.order_after_moq, "order_quantity": r.order_quantity} == e7["expected"]


def test_published_forecast_baselines_match_the_domain_at_the_cutoff(built, result):
    pop = result.population
    rows = built["rows"]
    run = next(r for r in rows["forecast_runs"] if r["product_id"] == "prod-002" and r["cutoff"].startswith("2026-08-31"))
    first, series = daily_series(pop.sales, run["product_id"], run["location_id"], parse_ts(run["cutoff"]))
    pts = {(p["model"], p["target_date"]): float(p["forecast_value"]) for p in rows["forecast_points"]
           if p["forecast_run_id"] == run["forecast_run_id"]}
    assert len(pts) == 3 * run["horizon_days"] and run["selected_model"] in {"naive", "seasonal_naive", "ewma"}
    nv, sn = naive(series, 14), seasonal_naive(series, 14)
    for h in range(14):
        d = (date.fromisoformat(run["cutoff"][:10]) + timedelta(days=1 + h)).isoformat()
        assert pts[("naive", d)] == pytest.approx(float(nv[h]), abs=0.005)
        assert pts[("seasonal_naive", d)] == pytest.approx(float(sn[h]), abs=0.005)


# --- the database ----------------------------------------------------------------------------------------------------
from support_db import conn, db_url  # noqa: E402,F401  (fixtures; they skip without DATABASE_URL)


def test_seed_into_postgres_and_row_counts(conn, inputs, result):
    from data import seed
    out = seed.seed(conn, inputs)
    rejected = collections.Counter(r["entity"] for r in result.rejected)
    assert out["skipped"] == len(result.rejected)
    for name in gen.ENTITIES:
        accepted = len(inputs[name]) - rejected.get(name, 0)
        assert out["inserted"][name] == accepted, name
        n = conn.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"]
        assert n == accepted, name
    # the rejected rows are kept raw: the replayed movement ids and the pre-order receipt
    assert conn.execute("SELECT count(*) AS n FROM rejected_records WHERE reason_code = 'DUPLICATE_MOVEMENT_ID'").fetchone()["n"] == 3
    assert conn.execute("SELECT count(*) AS n FROM rejected_records WHERE reason_code = 'RECEIPT_BEFORE_ORDER'").fetchone()["n"] == 1
