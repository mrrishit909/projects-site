"""Business rules of the pure domain, one test per rule (D-01..D-06). Test ids P03-TEST-nn are in the names."""
from datetime import date, datetime, timezone
from fractions import Fraction

import pytest

from supplyscope import DomainError, ledger, replenishment
from supplyscope import demand as dem
from supplyscope import forecast as fc
from supplyscope import metrics as dm
from supplyscope import suppliers as sup
from supplyscope.ingest import validate_batch
from supplyscope.models import Population, parse_row, parse_ts
from supplyscope.money import d2, d6

AS_OF = parse_ts("2026-03-31T23:59:59Z")


def base(**extra):
    rows = {"products": [{"product_id": "p1", "sku": "S1", "unit_cost": "10.00", "pack_size": 24, "minimum_order_quantity": 50}],
            "locations": [{"location_id": "l1", "location_name": "DC", "timezone": "UTC", "storage_capacity": 100, "active": True}],
            "suppliers": [{"supplier_id": "s1", "supplier_name": "S", "calendar_id": "c1", "quoted_lead_days": 7, "active": True}]}
    rows.update(extra)
    return rows


def mv(i, delta, at, kind=None):
    kind = kind or ("receipt" if delta > 0 else "sale")
    return {"movement_id": f"mv-{i}", "product_id": "p1", "location_id": "l1", "quantity_delta": delta, "event_at": at,
            "movement_type": kind}


def sale(i, qty, at):
    return {"sale_id": f"s-{i}", "product_id": "p1", "location_id": "l1", "sold_at": at, "quantity": qty}


def movements(rows):
    return [parse_row("inventory_movements", r) for r in rows]


# --- D-01 ledger ------------------------------------------------------------------------------------------------

def test_day_order_receipts_then_sales_then_review():
    rows = [mv(1, -35, "2026-03-12T09:00:00Z"), mv(2, 35, "2026-03-12T15:00:00Z"),
            mv(3, -5, "2026-03-12T01:00:00Z", "review")]
    st = ledger.reconstruct(movements(rows), AS_OF)[("p1", "l1")]
    assert st.on_hand_raw == -5 and st.running_min == -5       # 0 -> +35 -> 0 -> -5 (the review comes last)
    assert st.timestamp_order_min == -40                        # by timestamp: review -5, sale -40, receipt -5
    assert ledger.day_key(movements(rows)[0]) < ledger.day_key(movements(rows)[2])  # sale before review
    only = ledger.reconstruct(movements(rows[:2]), AS_OF)[("p1", "l1")]
    assert (only.on_hand, only.running_min, only.timestamp_order_min, only.negative) == (0, 0, -35, False)


def test_movement_after_as_of_is_excluded():
    rows = [mv(1, 60, "2026-03-01T08:00:00Z"), mv(2, -10, "2026-04-02T10:00:00Z")]
    assert ledger.reconstruct(movements(rows), AS_OF)[("p1", "l1")].on_hand == 60
    assert ledger.reconstruct(movements(rows), parse_ts("2026-04-02T10:00:00Z"))[("p1", "l1")].on_hand == 50  # inclusive instant


def test_negative_stock_is_flagged_and_never_valued():
    pop = Population.from_rows(base(inventory_movements=[mv(1, 10, "2026-03-01T08:00:00Z"), mv(2, -25, "2026-03-02T08:00:00Z")]))
    st = ledger.reconstruct(pop.inventory_movements, AS_OF)[("p1", "l1")]
    assert st.on_hand_raw == -15 and st.on_hand == 0 and st.flags == ["NEGATIVE_STOCK"]
    m = dm.compute_metrics(pop, AS_OF, (parse_ts("2026-03-01T00:00:00Z"), None))
    assert m["negative_stock"] is True and m["on_hand"] == 0 and m["working_capital"] == "0.00"
    assert dm.negative_stock_flags(pop, AS_OF)[0]["flag"] == "NEGATIVE_STOCK"


# --- D-02 replenishment ------------------------------------------------------------------------------------------

def test_pack_rounding_below_moq():
    """P03-TEST-03: raw 20, MOQ 50, pack 24 -> 72 (the MOQ lifts 20 to 50, the pack rounds 50 up to 3 packs)."""
    r = replenishment.replenish(on_hand=100, on_order=0, backorders=0, reorder_point=150, target_position=120, moq=50, pack_size=24)
    assert (r.raw_order, r.order_after_moq, r.order_quantity, r.triggered) == (20, 50, 72, True)


@pytest.mark.parametrize("raw,moq,pack,want", [(50, 50, 25, 50), (50, 50, 24, 72), (48, 48, 24, 48), (1, 1, 1, 1), (0, 50, 24, 72)])
def test_moq_exactly_met_and_rounding(raw, moq, pack, want):
    assert replenishment.pack_round_up(replenishment.apply_moq(raw, moq), pack) == want


def test_not_triggered_zeroes_every_quantity():
    r = replenishment.replenish(on_hand=40, on_order=50, backorders=10, reorder_point=70, target_position=120, moq=50, pack_size=24)
    assert (r.position, r.triggered, r.raw_order, r.order_after_moq, r.order_quantity) == (80, False, 0, 0, 0)
    assert replenishment.replenish(70, 0, 0, 70, 120, 50, 24).triggered is False   # position == ROP is not below it


def test_p03_test_10_reserved_is_not_subtracted_from_position():
    rows = base(inventory_movements=[mv(1, 40, "2026-03-01T08:00:00Z")],
                reservations=[{"reservation_id": "r1", "product_id": "p1", "location_id": "l1", "quantity": 15,
                               "reserved_at": "2026-03-10T00:00:00Z"}])
    m = dm.compute_metrics(Population.from_rows(rows), AS_OF, (parse_ts("2026-03-01T00:00:00Z"), None))
    assert (m["on_hand"], m["reserved"], m["available"], m["inventory_position"]) == (40, 15, 25, 40)


def test_p03_test_05_supplier_closure_extends_lead_time():
    from supplyscope.models import Closure
    start = date(2026, 3, 1)
    none = replenishment.effective_lead_days(start, 7, [], "c1")
    closure = [Closure("k1", "c1", date(2026, 3, 3), date(2026, 3, 9))]
    assert none == 7 and replenishment.effective_lead_days(start, 7, closure, "c1") == 14
    assert replenishment.effective_lead_days(start, 7, closure, "other-calendar") == 7   # another calendar is unaffected
    assert replenishment.arrival_date(start, 7, closure, "c1") == date(2026, 3, 15)
    daily = [Fraction(3)] * 30                                                            # demand keeps running through the closure
    assert replenishment.lead_time_demand(daily, 14) - replenishment.lead_time_demand(daily, 7) == 21


def test_safety_stock_from_residual_variance_and_z_table():
    z = replenishment.z_value("0.95")
    assert str(z) == "1.644854"
    assert replenishment.safety_stock(z, Fraction(4), 9) == 10            # ceil(1.644854 * sqrt(36)) = ceil(9.87)
    assert replenishment.safety_stock(z, None, 9) == 0 and replenishment.safety_stock(z, Fraction(0), 9) == 0
    for target in ("0.90", "0.98", "0.99"):
        replenishment.z_value(target)
    with pytest.raises(DomainError) as e:
        replenishment.z_value("0.5")
    assert e.value.code == "UNSUPPORTED_SERVICE_TARGET"


# --- D-04 receipts, suppliers, unmet demand ----------------------------------------------------------------------

def _po_rows(received):
    return base(purchase_orders=[{"purchase_order_id": "po1", "supplier_id": "s1", "ordered_at": "2026-03-01T09:00:00Z",
                                  "status": "confirmed", "currency": "USD"}],
                purchase_order_lines=[{"po_line_id": "pl1", "purchase_order_id": "po1", "product_id": "p1",
                                       "ordered_quantity": 100, "unit_cost": "10.00"}],
                receipts=[{"receipt_id": f"r{i}", "po_line_id": "pl1", "location_id": "l1", "received_quantity": q,
                           "received_at": at} for i, (q, at) in enumerate(received)])


def test_p03_test_07_partial_receipt_stays_open():
    pop = Population.from_rows(_po_rows([(60, "2026-03-09T09:00:00Z")]))
    line = pop.purchase_order_lines[0]
    assert sup.open_quantity(line, pop.receipts, AS_OF) == 40 and sup.line_status(line, pop.receipts, AS_OF) == "open"
    assert dm.on_order_by_product(pop, AS_OF) == {"p1": 40}
    done = Population.from_rows(_po_rows([(60, "2026-03-09T09:00:00Z"), (40, "2026-03-10T09:00:00Z")]))
    assert sup.line_status(done.purchase_order_lines[0], done.receipts, AS_OF) == "complete"
    assert dm.on_order_by_product(done, AS_OF) == {"p1": 0}
    review = sup.on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, [], AS_OF)
    assert review["partially_received_open_lines"] == ["pl1"] and review["open_lines"] == ["pl1"]


def test_supplier_on_time_rate_uses_only_receipts_up_to_the_cutoff():
    pop = Population.from_rows(_po_rows([(50, "2026-03-08T09:00:00Z"), (50, "2026-03-20T09:00:00Z")]))
    cut = parse_ts("2026-03-10T00:00:00Z")
    early = sup.on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, [], cut)
    assert (early["eligible_receipts"], early["on_time_receipts"], early["on_time_rate"]) == (1, 1, "1.000000")
    later = sup.on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, [], AS_OF)
    assert (later["eligible_receipts"], later["on_time_rate"], later["late_receipts"]) == (2, "0.500000", ["r1"])
    none = sup.on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, [],
                            parse_ts("2026-03-02T00:00:00Z"))
    assert none["eligible_receipts"] == 0 and none["on_time_rate"] is None


def test_p03_test_08_lost_sale_xor_backlog():
    assert dem.apply_unmet_policy("backlog", 5) == {"backorder": 5, "lost_sale": 0}
    assert dem.apply_unmet_policy("lost_sale", 5) == {"backorder": 0, "lost_sale": 5}
    for policy in ("backlog", "lost_sale"):
        got = dem.apply_unmet_policy(policy, 7)
        assert sorted(got.values()) == [0, 7]
    with pytest.raises(DomainError):
        dem.apply_unmet_policy("both", 1)


def test_fill_rate_and_stockout_days_from_aggregated_units():
    rows = base(sales=[sale(1, 95, "2026-03-05T10:00:00Z")], inventory_movements=[mv(1, 95, "2026-03-01T00:00:00Z")],
                backorders=[{"backorder_id": "b1", "product_id": "p1", "location_id": "l1", "quantity": 5,
                             "opened_at": "2026-03-12T09:00:00Z", "closed_at": None}],
                lost_sales=[{"lost_sale_id": "ls1", "product_id": "p1", "location_id": "l1", "quantity": 5,
                             "occurred_at": "2026-03-12T10:00:00Z"}])
    m = dm.compute_metrics(Population.from_rows(rows), AS_OF, (parse_ts("2026-03-01T00:00:00Z"), None))
    assert (m["requested_units"], m["unmet_units"], m["fill_rate"]) == (105, 10, "0.904762")
    assert (m["stockout_day_count"], m["stockout_days"]) == (1, "0.032258")     # two events, one day


def test_half_open_window_excludes_its_end():
    rows = base(sales=[sale(1, 10, "2026-03-05T00:00:00Z"), sale(2, 10, "2026-03-10T00:00:00Z")],
                inventory_movements=[mv(1, 50, "2026-03-01T00:00:00Z")])
    pop = Population.from_rows(rows)
    m = dm.compute_metrics(pop, AS_OF, (parse_ts("2026-03-05T00:00:00Z"), parse_ts("2026-03-10T00:00:00Z")))
    assert m["fulfilled_units"] == 10 and m["observed_days"] == 5          # [03-05, 03-10): the sale at 03-10 00:00 is out
    with pytest.raises(DomainError) as e:
        dm.compute_metrics(pop, AS_OF, (parse_ts("2026-03-10T00:00:00Z"), parse_ts("2026-03-05T00:00:00Z")))
    assert e.value.code == "INVALID_WINDOW"


def test_p03_test_01_censored_sales_and_latent_demand_are_reported_separately():
    rows = base(sales=[sale(1, 10, "2026-03-01T10:00:00Z"), sale(2, 4, "2026-03-02T10:00:00Z")],
                backorders=[{"backorder_id": "b1", "product_id": "p1", "location_id": "l1", "quantity": 6,
                             "opened_at": "2026-03-02T12:00:00Z", "closed_at": None}],
                latent_demand=[{"product_id": "p1", "location_id": "l1", "demand_date": "2026-03-01", "latent_quantity": 10},
                               {"product_id": "p1", "location_id": "l1", "demand_date": "2026-03-02", "latent_quantity": 10}])
    pop = Population.from_rows(rows)
    out = dem.censored_vs_latent(pop.sales, pop.backorders, pop.lost_sales, pop.latent_demand, "p1", "l1",
                                 date(2026, 3, 1), date(2026, 3, 2), AS_OF)
    assert out["observed"] == {"2026-03-01": 10, "2026-03-02": 4} and out["latent"] == {"2026-03-01": 10, "2026-03-02": 10}
    assert out["censored_days"] == ["2026-03-02"] and out["observed_total"] == 14 and out["latent_total"] == 20
    assert "censored" in out["shown"]


# --- D-03 forecasts ---------------------------------------------------------------------------------------------

def daily_sales(values, start=date(2026, 1, 1)):
    from datetime import timedelta
    return [parse_row("sales", sale(i, v, f"{(start + timedelta(days=i)).isoformat()}T12:00:00Z"))
            for i, v in enumerate(values) if v]


def test_baselines_naive_and_seasonal_naive():
    hist = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert fc.naive(hist, 3) == [9, 9, 9]
    assert fc.seasonal_naive(hist, 9) == [3, 4, 5, 6, 7, 8, 9, 3, 4]       # the last 7 days repeat
    assert fc.seasonal_naive([4, 5], 2) == [5, 5]                          # under a week of history: falls back to naive


def test_forecast_always_reports_both_baselines_and_never_claims_an_unearned_win():
    weekly = [10, 12, 9, 11, 30, 8, 7] * 8                                  # seasonal-naive is perfect
    sales = daily_sales(weekly)
    cut = parse_ts("2026-02-25T23:59:59Z")
    res = fc.forecast_demand(sales, [], "p1", "l1", cut, 7)
    assert set(res.evals) == {"naive", "seasonal_naive", "ewma"} and res.evals["seasonal_naive"].mae == 0
    assert res.beats_baseline == {"ewma": False} and res.selected_model == "seasonal_naive"
    noisy = [10, 40, 3, 25, 8, 31, 2, 18, 35, 4, 22, 9, 28, 5] * 4         # period-14 noise: seasonal-naive (7) is wrong
    res2 = fc.forecast_demand(daily_sales(noisy), [], "p1", "l1", parse_ts("2026-02-25T23:59:59Z"), 7)
    e = res2.evals
    assert e["ewma"].folds == e["seasonal_naive"].folds > 0                 # compared on the same folds
    assert res2.beats_baseline["ewma"] is (e["ewma"].mae < e["seasonal_naive"].mae)
    assert res2.selected_model == ("ewma" if res2.beats_baseline["ewma"] else "seasonal_naive")


def test_p03_test_02_forecast_at_cutoff_ignores_later_promotion_outcomes_and_sales():
    from datetime import timedelta
    values = [5, 6, 4, 5, 7, 5, 6] * 6
    cut = parse_ts("2026-02-11T23:59:59Z")                                  # 42 days of history: 01-01..02-11
    promo = lambda realised, announced: parse_row("promotions", {   # noqa: E731
        "promotion_id": "pr", "product_id": "p1", "starts_at": "2026-02-13T00:00:00Z", "ends_at": "2026-02-15T00:00:00Z",
        "planned_uplift": "2", "announced_at": announced, "realised_uplift": realised})
    known = fc.forecast_demand(daily_sales(values), [promo("3", "2026-02-01T00:00:00Z")], "p1", "l1", cut, 7)
    other_outcome = fc.forecast_demand(daily_sales(values), [promo("0.1", "2026-02-01T00:00:00Z")], "p1", "l1", cut, 7)
    assert known.points == other_outcome.points                              # the outcome is never a feature
    late = fc.forecast_demand(daily_sales(values), [promo("3", "2026-03-01T00:00:00Z")], "p1", "l1", cut, 7)
    none = fc.forecast_demand(daily_sales(values), [], "p1", "l1", cut, 7)
    assert late.points == none.points                                        # announced after the cutoff: unknown
    assert known.points["ewma"] != none.points["ewma"]                      # a schedule known at the cutoff IS used
    future_sales = daily_sales(values + [500] * 10)                          # sales after the cutoff are never read
    assert fc.forecast_demand(future_sales, [], "p1", "l1", cut, 7).points == none.points
    with pytest.raises(DomainError) as e:
        fc.forecast_demand(daily_sales(values), [], "p1", "l1", parse_ts("2026-06-01T00:00:00Z"), 7,
                           fc.dataset_end(daily_sales(values), [], []))
    assert e.value.code == "FORECAST_CUTOFF_IN_FUTURE"


def test_p03_test_06_intermittent_sku_wape_is_null_and_zero_folds_are_disclosed():
    values = [3, 0, 0, 2] + [0] * 56
    res = fc.forecast_demand(daily_sales(values), [], "p1", "l1", parse_ts("2026-03-01T23:59:59Z"), 7)
    for ev in res.evals.values():
        assert ev.wape is None and ev.actual == 0 and ev.zero_demand_folds >= 1
    assert res.beats_baseline["ewma"] is None                                 # cannot be judged: no win is reported
    assert "ZERO_DEMAND_FOLDS_DISCLOSED" in res.notes and res.model_report()["naive"]["wape"] is None
    assert res.model_report()["naive"]["mae"] is not None


def test_mae_and_wape_arithmetic():
    ev = fc.ModelEval("x", points=4, abs_error=Fraction(6), actual=Fraction(24))
    assert d6(ev.mae) == "1.500000" and d6(ev.wape) == "0.250000"


# --- D-05 money, simulation -------------------------------------------------------------------------------------

def test_p03_test_12_cost_change_inside_the_valuation_period():
    rows = base(inventory_movements=[mv(1, 10, "2026-02-28T08:00:00Z")],
                cost_versions=[{"cost_version_id": "cv1", "product_id": "p1", "unit_cost": "12.00",
                                "effective_from": "2026-03-03T00:00:00Z"}])
    pop = Population.from_rows(rows)
    window = (parse_ts("2026-03-01T00:00:00Z"), None)
    assert dm.compute_metrics(pop, parse_ts("2026-03-02T23:59:59Z"), window)["working_capital"] == "100.00"
    assert dm.compute_metrics(pop, parse_ts("2026-03-04T23:59:59Z"), window)["working_capital"] == "120.00"
    sup4 = dm.supplementary(pop, parse_ts("2026-03-04T23:59:59Z"), window)      # days 100, 100, 120, 120
    assert sup4["average_inventory_value"] == "110.00"                           # not 4 x the last cost (120.00)
    assert sup4["inventory_turnover"] is None or float(sup4["inventory_turnover"]) >= 0


def test_turnover_is_annualised_cogs_over_average_inventory():
    rows = base(inventory_movements=[mv(1, 100, "2026-03-01T00:00:00Z"), mv(2, -10, "2026-03-02T12:00:00Z")],
                sales=[sale(1, 10, "2026-03-02T12:00:00Z")])
    s = dm.supplementary(Population.from_rows(rows), parse_ts("2026-03-04T23:59:59Z"), (parse_ts("2026-03-01T00:00:00Z"), None))
    assert s["annualised_cogs"] == "9125.00" and s["average_inventory_value"] == "925.00"   # (1000 + 900 x 3) / 4 days; COGS 10 x 10.00 x 365 / 4
    assert s["inventory_turnover"] == d6(Fraction(9125) / Fraction(925))


def test_p03_test_09_policies_share_the_same_random_sample():
    from supplyscope.models import Scenario
    from decimal import Decimal
    a = Scenario("a", "A", Decimal("0.90"), "backlog", 11, 3, 2)
    b = Scenario("b", "B", Decimal("0.95"), "lost_sale", 11, 3, 2)
    out = dem.compare_policies([a, b], 60, 6.0, 2, 5, 40, 90, 20, 10, 30)
    assert out["seed"] == 11 and len(out["sample_hashes"]) == 2
    assert out == dem.compare_policies([a, b], 60, 6.0, 2, 5, 40, 90, 20, 10, 30)          # repeatable
    s1, s2 = dem.common_sample(11, 60, 6.0, 2, 5), dem.common_sample(11, 60, 6.0, 2, 5)
    assert s1 == s2 and dem.common_sample(12, 60, 6.0, 2, 5) != s1
    ra, rb = out["results"]["a"][0], out["results"]["b"][0]
    assert ra["requested"] == rb["requested"]                                                 # the same demand was offered
    c = Scenario("c", "C", Decimal("0.95"), "backlog", 12, 3, 2)
    with pytest.raises(DomainError) as e:
        dem.compare_policies([a, c], 60, 6.0, 2, 5, 40, 90, 20, 10, 30)
    assert e.value.code == "POLICY_SEED_MISMATCH"


def test_rate_rounding_is_half_up_from_exact_fractions():
    assert d6(Fraction(1, 128)) == "0.007813" and d2(Fraction(1, 8)) == "0.13" and d6(Fraction(1, 3)) == "0.333333"
    assert d6(None) is None and d2(Fraction(5, 1)) == "5.00"


# --- ingest ------------------------------------------------------------------------------------------------------

def test_ingest_conflicting_duplicate_rejects_both_and_exact_replay_keeps_first():
    inp = base(inventory_movements=[mv(1, 10, "2026-03-01T00:00:00Z"), mv(1, 12, "2026-03-01T00:00:00Z"),
                                    mv(2, 5, "2026-03-02T00:00:00Z"), mv(2, 5, "2026-03-02T00:00:00Z")])
    res = validate_batch(inp)
    reasons = [(r.id, r.reason_code) for r in res.rejected]
    assert reasons == [("mv-1", "DUPLICATE_MOVEMENT_CONFLICT"), ("mv-1", "DUPLICATE_MOVEMENT_CONFLICT"),
                       ("mv-2", "DUPLICATE_MOVEMENT_ID")]
    assert [m.movement_id for m in res.accepted["inventory_movements"]] == ["mv-2"]
    assert res.counts["inventory_movements"] == {"accepted": 1, "rejected": 3}


def test_ingest_references_malformed_and_receipt_rules():
    po = {"purchase_order_id": "po1", "supplier_id": "s1", "ordered_at": "2026-03-10T09:00:00Z", "status": "confirmed", "currency": "USD"}
    line = {"po_line_id": "pl1", "purchase_order_id": "po1", "product_id": "p1", "ordered_quantity": 10, "unit_cost": "10.00"}
    rc = lambda i, q, at: {"receipt_id": i, "po_line_id": "pl1", "location_id": "l1", "received_quantity": q, "received_at": at}  # noqa: E731
    inp = base(purchase_orders=[po, dict(po, purchase_order_id="po2", supplier_id="nope")],
               purchase_order_lines=[line, dict(line, po_line_id="pl2", purchase_order_id="po2")],
               receipts=[rc("r1", 6, "2026-03-12T00:00:00Z"), rc("r2", 6, "2026-03-13T00:00:00Z"),
                         rc("r0", 1, "2026-03-01T00:00:00Z"), rc("r3", 0, "2026-03-14T00:00:00Z")],
               inventory_movements=[mv(1, 10, "2026-03-01T00:00:00Z"), dict(mv(2, 5, "2026-03-01T00:00:00Z"), product_id="ghost"),
                                    dict(mv(3, 5, "2026-03-01T00:00:00Z"), quantity_delta=2.5),
                                    dict(mv(4, 5, "2026-03-01T00:00:00Z"), event_at="2026-03-01T00:00:00"),
                                    dict(mv(5, 5, "2026-03-01T00:00:00Z"), quantity_delta=True),
                                    dict(mv(6, 5, "2026-03-01T00:00:00Z"), quantity_delta=-5, movement_type="receipt")],
               sales=[sale(1, 1, "2026-03-01T00:00:00Z"), sale(1, 1, "2026-03-01T00:00:00Z")])
    got = {(r.entity, r.id): r.reason_code for r in validate_batch(inp).rejected}
    assert got[("purchase_orders", "po2")] == "UNKNOWN_REFERENCE" and got[("purchase_order_lines", "pl2")] == "UNKNOWN_REFERENCE"
    assert got[("receipts", "r0")] == "RECEIPT_BEFORE_ORDER" and got[("receipts", "r2")] == "RECEIPT_EXCEEDS_ORDERED"
    assert got[("receipts", "r3")] == "MALFORMED_RECORD" and ("receipts", "r1") not in got
    assert got[("inventory_movements", "mv-2")] == "UNKNOWN_REFERENCE"
    for i in (3, 4, 5, 6):
        assert got[("inventory_movements", f"mv-{i}")] == "MALFORMED_RECORD", i
    assert got[("sales", "s-1")] == "DUPLICATE_ID"


def test_contract_version_mismatch_is_refused():
    with pytest.raises(DomainError) as e:
        validate_batch({"contract_version": 99})
    assert e.value.code == "CONTRACT_MISMATCH"


# --- groups ------------------------------------------------------------------------------------------------------

def test_group_metrics_by_product_location_supplier_and_abc_class():
    rows = base(products=[{"product_id": "p1", "sku": "S1", "unit_cost": "10.00", "pack_size": 1, "minimum_order_quantity": 1,
                           "abc_class": "A", "supplier_id": "s1"},
                          {"product_id": "p2", "sku": "S2", "unit_cost": "5.00", "pack_size": 1, "minimum_order_quantity": 1}],
                inventory_movements=[mv(1, 10, "2026-03-01T00:00:00Z"),
                                     dict(mv(2, 20, "2026-03-01T00:00:00Z"), product_id="p2")])
    pop = Population.from_rows(rows)
    window = (parse_ts("2026-03-01T00:00:00Z"), None)
    by = lambda key: {g: (m["on_hand"], m["working_capital"]) for g, m in dm.group_metrics(pop, key, AS_OF, window).items()}  # noqa: E731
    assert by("product") == {"p1": (10, "100.00"), "p2": (20, "100.00")}
    assert by("location") == {"l1": (30, "200.00")}
    assert by("supplier") == {"s1": (10, "100.00"), "unassigned": (20, "100.00")}
    assert by("abc_class") == {"A": (10, "100.00"), "unclassified": (20, "100.00")}
    assert sum(v[0] for v in by("product").values()) == dm.compute_metrics(pop, AS_OF, window)["on_hand"]
    with pytest.raises(ValueError):
        dm.group_values(pop, "colour")
