"""The business rules of the pure domain beyond the golden fixture (the cases CALCULATION.md lists under "Not exercised"), one behaviour per test."""
from datetime import datetime, timezone
from fractions import Fraction as F

import pytest

from changeworks import DomainError, Validator, run_pipeline, validate_batch
from changeworks.numbers import canon
from changeworks.roadmap import feasible_starts

from worlds import (ad, alloc, asm, ben, bo, cost, dataset, dep, fc, grp, ini, pb, ra, resource, risk, sc, tc)

UTC = timezone.utc


def run(d, **kw):
    return run_pipeline(d, **kw)


def codes(d):
    return {(r.entity, r.id): r.reason_code for r in validate_batch(d).rejected}


def one(d, scn="scn-1", i="i-1", **kw):
    return run(d, **kw).metrics["scenarios"][scn]["initiatives"][i]


def flow(d, **kw):
    return [r["net_cash_flow"] for r in one(d, **kw)["cash_flow"]]


# ------------------------------------------------------------------------------------------------------------------ shapes and ingest order
@pytest.mark.parametrize("patch", [{"amount": "100"}, {"amount": 100}, {"amount": None}, {"amount": "1e3"}, {"amount": "1.1234567"}, {"amount": "-"},
                                   {"period_index": True}, {"period_index": "0"}, {"period_index": 1.0}, {"cost_key": ""}, {"cost_key": " k "}])
def test_malformed_rows_are_rejected_with_the_failing_fields(patch):
    row = {**cost("c-1", "i-1", "k", "one_time", "100.00", p=0), **patch}
    if patch.get("amount") == "100":                 # a whole number is a valid decimal string: accepted
        assert codes(dataset(initiatives=[ini()], cost_items=[row])) == {}
        return
    r = validate_batch(dataset(initiatives=[ini()], cost_items=[row])).rejected
    assert [x.reason_code for x in r] == ["MALFORMED_RECORD"] and set(r[0].details["fields"]) <= {"amount", "period_index", "cost_key"}


def test_a_missing_key_a_non_object_and_a_float_are_malformed():
    d = dataset(initiatives=[ini()], cost_items=[{"cost_id": "c-1"}, "nope", {**cost("c-2", "i-1", "k", "one_time", "1.00", p=0), "amount": 1.5}])
    rej = validate_batch(d).rejected
    assert [r.reason_code for r in rej] == ["MALFORMED_RECORD"] * 3 and "missing" in rej[0].details["fields"]["initiative_id"]


def test_ingest_order_duplicate_id_then_keys_then_rules():
    d = dataset(initiatives=[ini(), ini(status="funded")], cost_items=[cost("c-1", "i-9", "k", "bogus", "1.00", p=0), cost("c-2", "i-1", "k", "bogus", "1.00", p=0)])
    assert codes(d) == {("initiatives", "i-1"): "DUPLICATE_ID", ("cost_items", "c-1"): "UNKNOWN_INITIATIVE", ("cost_items", "c-2"): "INVALID_COST_TYPE"}


def test_the_later_of_two_repeats_is_rejected_and_the_first_is_kept():
    d = dataset(initiatives=[ini()], cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0), cost("c-1", "i-1", "other", "one_time", "999.00", p=0)])
    r = validate_batch(d)
    assert [c["amount"] for c in r.population.acc["cost_items"]] == ["100.00"] and [x.reason_code for x in r.rejected] == ["DUPLICATE_ID"]


def test_a_rejected_parent_makes_children_dependent_rejected_not_unknown():
    d = dataset(initiatives=[ini(status="funded")], cost_items=[cost("c-1", "i-1", "k", "one_time", "1.00", p=0)], risk_items=[risk("r-1", "i-1", "0.5", "10.00")])
    assert codes(d) == {("initiatives", "i-1"): "STATUS_NOT_ALLOWED", ("cost_items", "c-1"): "DEPENDENT_REJECTED", ("risk_items", "r-1"): "DEPENDENT_REJECTED"}


@pytest.mark.parametrize("row,code", [
    (ben("b-1", "i-1", "cash", "10.00", 1, starts=0), "BENEFIT_BEFORE_DEPLOYMENT"),
    ({**ben("b-1", "i-1", "cash", "10.00", 2, starts=3)}, "INVALID_PERIOD"),
    (ben("b-1", "i-1", "mystery", "10.00", 1), "INVALID_BENEFIT_TYPE"),
    ({**ben("b-1", "i-1", "capacity", "10.00", 1), "unit": "USD"}, "INVALID_UNIT"),
    (ben("b-1", "i-1", "capacity", "10.00", 1, real=True), "CAPACITY_WITHOUT_CONVERSION"),
    (ben("b-1", "i-1", "cash", "-1.00", 1), "INVALID_AMOUNT"),
])
def test_benefit_rules(row, code):
    assert codes(dataset(initiatives=[ini()], benefit_items=[row])) == {("benefit_items", "b-1"): code}


@pytest.mark.parametrize("row,code", [
    (cost("c-1", "i-1", "k", "one_time", "1.00"), "INVALID_PERIOD"), (cost("c-1", "i-1", "k", "one_time", "1.00", p=0, s=1), "INVALID_PERIOD"),
    (cost("c-1", "i-1", "k", "recurring", "1.00", s=2, e=2), "INVALID_PERIOD"), (cost("c-1", "i-1", "k", "recurring", "1.00", p=1, s=1, e=3), "INVALID_PERIOD"),
    (cost("c-1", "i-1", "k", "recurring", "1.00", s=3, e=1), "INVALID_PERIOD"), (cost("c-1", "i-1", "k", "weekly", "1.00", p=0), "INVALID_COST_TYPE"),
    (cost("c-1", "i-1", "k", "one_time", "1.00", p=0, basis="guess"), "INVALID_AMOUNT"),
])
def test_cost_rules(row, code):
    assert codes(dataset(initiatives=[ini()], cost_items=[row])) == {("cost_items", "c-1"): code}


def test_assumption_rules_versions_ramp_and_rationale():
    ok = asm("a-1", "i-1", "adoption_ramp", values=["0.5", "1"])
    bad = [asm("a-2", "i-1", "adoption_ramp", n=2, values=["0.8", "0.5"]), asm("a-3", "i-1", "adoption_ramp", n=3, values=["0.5", "1.5"]),
           asm("a-4", "i-1", "adoption_ramp", n=1, values=["0.5"]), {**asm("a-5", "i-1", "x"), "rationale": "  "}, asm("a-6", "i-1", "x", value="1", values=["1"]),
           asm("a-7", "i-1", "x", n=0, value="1"), asm("a-8", "i-1", "x")]
    assert codes(dataset(initiatives=[ini()], assumption_versions=[ok] + bad)) == {
        ("assumption_versions", "a-2"): "INVALID_RAMP", ("assumption_versions", "a-3"): "INVALID_RAMP", ("assumption_versions", "a-4"): "VERSION_EXISTS",
        ("assumption_versions", "a-5"): "RATIONALE_REQUIRED", ("assumption_versions", "a-6"): "INVALID_ASSUMPTION", ("assumption_versions", "a-7"): "INVALID_VERSION",
        ("assumption_versions", "a-8"): "INVALID_ASSUMPTION"}


@pytest.mark.parametrize("patch,code", [({"horizon_periods": 0}, "INVALID_HORIZON"), ({"horizon_periods": 601}, "INVALID_HORIZON"), ({"rate_basis": "weekly"}, "INVALID_RATE_BASIS"),
                                         ({"discount_rate": "1.500000"}, "INVALID_RATE"), ({"initiative_ids": []}, "INVALID_SCENARIO"), ({"status": "funded"}, "STATUS_NOT_ALLOWED"),
                                         ({"rate_basis": "monthly"}, "RATE_PERIOD_MISMATCH")])
def test_scenario_rules(patch, code):
    assert codes(dataset(initiatives=[ini()], scenario_versions=[{**sc(), **patch}])) == {("scenario_versions", "scn-1"): code}


def test_a_conversion_must_be_a_monthly_rate_conversion_assumption():
    d = dataset("monthly", initiatives=[ini()], assumption_versions=[asm("a-x", None, "something_else", value="0.007974")], scenario_versions=[sc(h=2, conv="a-x")])
    assert codes(d) == {("scenario_versions", "scn-1"): "INVALID_CONVERSION"}


def test_other_row_rules():
    dup = {**fc("i-1", 1, 1, "6.00"), "forecast_id": "f-dup"}
    d = dataset(initiatives=[ini(), ini("i-2", dur=0), ini("i-3", start=-1)], dependencies=[dep("d-1", "i-1", "i-1"), dep("d-2", "i-1", "i-2", lag=-1), dep("d-3", "i-1", "i-2", "sometimes")],
                stakeholder_groups=[{**grp(), "impact_level": "huge"}], risk_items=[risk("r-1", "i-1", "1.000001", "1.00"), risk("r-2", "i-1", "0.5", "1.00")],
                forecast_versions=[fc("i-1", 1, 1, "5.00"), dup])
    c = codes(d)
    assert c[("dependencies", "d-1")] == "DEPENDENCY_CYCLE"
    assert c[("dependencies", "d-2")] == c[("dependencies", "d-3")] == "DEPENDENT_REJECTED"          # i-2 was rejected, so its dependants are, whatever else is wrong with them
    assert c[("initiatives", "i-2")] == "INVALID_DURATION" and c[("initiatives", "i-3")] == "INVALID_PERIOD"
    assert c[("stakeholder_groups", "g-1")] == "INVALID_IMPACT_LEVEL" and c[("risk_items", "r-1")] == "PROBABILITY_OUT_OF_RANGE" and ("risk_items", "r-2") not in c
    assert c[("forecast_versions", "f-dup")] == "VERSION_EXISTS"


@pytest.mark.parametrize("row,code", [(dep("d-1", "a", "b", "sometimes"), "INVALID_DEPENDENCY_TYPE"), (dep("d-1", "a", "b", lag=-1), "INVALID_LAG"), (dep("d-1", "a", "a"), "DEPENDENCY_CYCLE")])
def test_dependency_rules(row, code):
    assert codes(dataset(initiatives=[ini("a"), ini("b")], dependencies=[row])) == {("dependencies", "d-1"): code}


def test_baseline_rows_one_per_version_and_an_approved_version_is_frozen():
    d = dataset(initiatives=[ini(base="v1")], process_baselines=[pb(v="v1"), pb(v="v1", bid="pb-dup"), pb(v="v2")] + [{**pb(v="v3", bid="pb-3"), "evidence_ref": " "}])
    c = codes(d)
    assert c == {("process_baselines", "pb-dup"): "BASELINE_FROZEN", ("process_baselines", "pb-3"): "EVIDENCE_REQUIRED"}
    d2 = dataset(initiatives=[ini(base=None)], process_baselines=[pb(v="v1"), pb(v="v1", bid="pb-dup")])
    assert codes(d2) == {("process_baselines", "pb-dup"): "VERSION_EXISTS"}                       # not approved yet: a version exists, it is not "frozen"


def test_validator_check_does_not_change_state_and_add_does():
    v = Validator(config={"period_basis": "annual", "period_start": "2026-01-01", "as_of": None})
    assert v.add("initiatives", ini()) is None
    n = len(v.acc["cost_items"])
    assert v.check("cost_items", cost("c-1", "i-1", "k", "one_time", "1.00", p=0)) is None and len(v.acc["cost_items"]) == n
    assert v.add("cost_items", cost("c-1", "i-1", "k", "one_time", "1.00", p=0)) is None
    assert v.check("cost_items", cost("c-1", "i-1", "k2", "one_time", "1.00", p=1)).reason_code == "DUPLICATE_ID"


# ------------------------------------------------------------------------------------------------------------------ cash flow
def test_ramp_is_indexed_from_each_rows_own_starts_period_and_the_last_value_is_held():
    d = dataset(initiatives=[ini()], assumption_versions=[asm("a-r", "i-1", "adoption_ramp", values=["0.250000", "0.500000", "0.750000"])],
                scenario_versions=[sc(h=6, pins=("a-r",))],
                benefit_items=[ben("b-0", "i-1", "cash", "100.00", 1, starts=1), ben("b-1", "i-1", "cash", "100.00", 2, starts=1), ben("b-2", "i-1", "cash", "100.00", 3, starts=1),
                               ben("b-3", "i-1", "cash", "100.00", 4, starts=1), ben("b-4", "i-1", "cash", "100.00", 5, starts=1),
                               ben("b-late", "i-1", "cash", "100.00", 5, starts=5)])
    assert flow(d) == ["0.00", "25.00", "50.00", "75.00", "75.00", "100.00"]                 # idx 0, 1, 2, then held (3 values, 5 periods); b-late starts at 5: idx 0 = 25, 75 + 25 = 100


def test_an_unpinned_ramp_uses_the_latest_version_and_a_pin_selects_an_older_one():
    a1, a2 = asm("a-1", "i-1", "adoption_ramp", 1, values=["0.100000"]), asm("a-2", "i-1", "adoption_ramp", 2, values=["0.900000"])
    base = dict(initiatives=[ini()], assumption_versions=[a1, a2], benefit_items=[ben("b-1", "i-1", "cash", "100.00", 1)])
    assert flow(dataset(**base, scenario_versions=[sc(h=2)])) == ["0.00", "90.00"]
    assert flow(dataset(**base, scenario_versions=[sc(h=2, pins=("a-1",))])) == ["0.00", "10.00"]
    r = one(dataset(**base, scenario_versions=[sc(h=2, pins=("a-1",))]))
    assert r["ramp"]["assumption_id"] == "a-1" and r["unramped_net_cash_flow"] == ["0.00", "100.00"] and r["planned_money_benefits"] == {"ramped": "10.00", "unramped": "100.00"}


def test_no_ramp_means_ramp_null_and_unramped_null():
    r = one(dataset(initiatives=[ini()], scenario_versions=[sc()], benefit_items=[ben("b-1", "i-1", "cash", "100.00", 1)]))
    assert r["ramp"] is None and r["unramped_net_cash_flow"] is None


def test_avoided_cost_enters_only_with_cash_realisation_and_evidence():
    d = dataset(initiatives=[ini()], scenario_versions=[sc(h=4)],
                benefit_items=[ben("b-1", "i-1", "avoided_cost", "10.00", 1, real=True, ev="budget-line:x"), ben("b-2", "i-1", "avoided_cost", "20.00", 2, real=True),
                               ben("b-3", "i-1", "avoided_cost", "40.00", 3, real=False, ev="budget-line:y"), ben("b-4", "i-1", "avoided_cost", "80.00", 3)])
    r = one(d)
    assert [x["net_cash_flow"] for x in r["cash_flow"]] == ["0.00", "10.00", "0.00", "0.00"]
    assert [(x["benefit_id"], x["reason"]) for x in r["excluded_from_cash_flow"]["avoided_cost_beside"]] == [("b-2", "NO_EVIDENCE_REF"), ("b-3", "NOT_CASH_REALISED"), ("b-4", "NOT_CASH_REALISED")]
    assert r["excluded_from_cash_flow"]["avoided_cost_beside_total"] == "140.00"


def test_capacity_conversion_pinned_else_latest_needs_staffing_evidence():
    base = dict(initiatives=[ini()], benefit_items=[ben("b-1", "i-1", "capacity", "10.00", 1)])
    r1, r2 = asm("a-1", "i-1", "capacity_hourly_rate", 1, value="20.00", staff="hr:plan"), asm("a-2", "i-1", "capacity_hourly_rate", 2, value="30.00", staff="hr:plan")
    assert flow(dataset(**base, assumption_versions=[r1, r2], scenario_versions=[sc(h=2)])) == ["0.00", "300.00"]
    assert flow(dataset(**base, assumption_versions=[r1, r2], scenario_versions=[sc(h=2, pins=("a-1",))])) == ["0.00", "200.00"]
    no_evidence = dataset(**base, assumption_versions=[asm("a-1", "i-1", "capacity_hourly_rate", value="20.00")], scenario_versions=[sc(h=2)])
    r = one(no_evidence)
    assert flow(no_evidence) == ["0.00", "0.00"] and r["excluded_from_cash_flow"]["capacity_hours_not_converted"] == "10.00" and r["converted_capacity"] == []
    conv = one(dataset(**base, assumption_versions=[r1], scenario_versions=[sc(h=2)]))["converted_capacity"][0]
    assert (conv["hours"], conv["hourly_rate"], conv["amount"], conv["conversion_assumption_id"], conv["staffing_change_evidence_ref"]) == ("10.00", "20.00", "200.00", "a-1", "hr:plan")


def test_one_time_and_recurring_costs_and_rows_beyond_the_horizon():
    d = dataset(initiatives=[ini()], scenario_versions=[sc(h=3)],
                cost_items=[cost("c-1", "i-1", "k1", "one_time", "100.00", p=0), cost("c-2", "i-1", "k2", "recurring", "10.00", s=1, e=6), cost("c-3", "i-1", "k3", "one_time", "999.00", p=7)],
                benefit_items=[ben("b-1", "i-1", "cash", "50.00", 2), ben("b-far", "i-1", "cash", "70.00", 4)])
    r = one(d)
    assert [x["costs"] for x in r["cash_flow"]] == ["100.00", "10.00", "10.00"] and [x["period_index"] for x in r["expanded_planned_costs"]] == [0, 1, 2]
    assert r["excluded_from_cash_flow"]["beyond_horizon"] == ["b-far"] and r["planned_money_benefits"]["ramped"] == "50.00"


def test_npv_on_monthly_periods_with_a_declared_monthly_rate_is_exact():
    d = dataset("monthly", initiatives=[ini(base=None)], scenario_versions=[sc(rate="0.010000", basis="monthly", h=3)],
                cost_items=[cost("c-1", "i-1", "k", "one_time", "1000.00", p=0)], benefit_items=[ben("b-1", "i-1", "cash", "600.00", 1), ben("b-2", "i-1", "cash", "600.00", 2)])
    r = one(d)
    assert F(r["npv"]["exact"]) == -1000 + F(600) / F(101, 100) + F(600) / F(101, 100) ** 2
    assert [x["period_start"] for x in r["cash_flow"]] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert r["cash_flow"][1]["discount_factor_exact"] == "100/101"


def test_a_zero_rate_is_allowed_and_npv_is_the_plain_sum():
    r = one(dataset(initiatives=[ini(base=None)], scenario_versions=[sc(rate="0.000000")], cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0)],
                    benefit_items=[ben("b-1", "i-1", "cash", "60.00", 1), ben("b-2", "i-1", "cash", "60.00", 2)]))
    assert r["npv"]["exact"] == "20" and r["npv"]["value"] == "20.00" and r["payback"]["simple"] == r["payback"]["discounted"] == {"period": 2, "interpolated": "1.6667", "reason": None}


def test_payback_cumulative_exactly_zero_counts_and_a_flow_with_no_investment_has_no_payback():
    r = one(dataset(initiatives=[ini(base=None)], scenario_versions=[sc(rate="0.000000")], cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0)],
                    benefit_items=[ben("b-1", "i-1", "cash", "50.00", 1), ben("b-2", "i-1", "cash", "50.00", 2)]))
    assert r["payback"]["simple"] == {"period": 2, "interpolated": "2.0000", "reason": None}          # cumulative -100, -50, exactly 0: back
    r0 = one(dataset(initiatives=[ini(base=None, dep=0)], scenario_versions=[sc(h=2)], benefit_items=[ben("b-1", "i-1", "cash", "50.00", 0)]))
    nothing = {"period": None, "interpolated": None, "reason": "NO_INVESTMENT"}                       # R9-12: +50 at t = 0 and no cost: nothing was invested (was 0.0000)
    assert r0["payback"]["simple"] == nothing and r0["payback"]["discounted"] == nothing and r0["npv"]["value"] == "50.00"


def test_payback_is_the_last_crossing_and_a_series_that_ends_negative_has_none():
    """R9-12 on a scenario of its own: cumulative -100, +20, -60, +10 pays back at 3 (not at 1); -100, +20, -60 ends negative."""
    dips = one(dataset(initiatives=[ini(base=None)], scenario_versions=[sc(rate="0.000000", h=4)],
                       cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0), cost("c-2", "i-1", "k2", "one_time", "80.00", p=2)],
                       benefit_items=[ben("b-1", "i-1", "cash", "120.00", 1), ben("b-2", "i-1", "cash", "70.00", 3)]))
    assert [x["cumulative"] for x in dips["cash_flow"]] == ["-100.00", "20.00", "-60.00", "10.00"]
    assert dips["payback"]["simple"] == {"period": 3, "interpolated": "2.8571", "reason": None}          # 2 + 60/70
    ends = one(dataset(initiatives=[ini(base=None)], scenario_versions=[sc(rate="0.000000", h=3)],
                       cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0), cost("c-2", "i-1", "k2", "one_time", "80.00", p=2)],
                       benefit_items=[ben("b-1", "i-1", "cash", "120.00", 1)]))
    assert ends["payback"]["simple"] == {"period": None, "interpolated": None, "reason": "NOT_RECOVERED"}


def test_no_flows_means_null_npv_and_paybacks_not_zero():
    r = one(dataset(initiatives=[ini(base=None)], scenario_versions=[sc()]))
    assert r["npv"]["value"] is None and r["npv"]["exact"] is None and r["payback"]["simple"]["period"] is None and r["payback"]["discounted"]["period"] is None
    assert r["payback"]["simple"]["reason"] == "NO_FLOWS"
    sc_ = run(dataset(initiatives=[ini(base=None)], scenario_versions=[sc()])).metrics["scenarios"]["scn-1"]
    assert sc_["npv_total"] == {"value": None, "exact": None, "basis": "attributable", "sum_of_initiatives": None, "sum_of_initiatives_exact": None}


def test_negative_cash_flow_never_pays_back_and_the_two_paybacks_can_differ():
    d = dataset(initiatives=[ini(base=None)], scenario_versions=[sc(rate="0.200000", h=4)], cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0)],
                benefit_items=[ben("b-1", "i-1", "cash", "60.00", 1), ben("b-2", "i-1", "cash", "60.00", 2), ben("b-3", "i-1", "cash", "60.00", 3)])
    r = one(d)
    assert r["payback"]["simple"]["period"] == 2 and r["payback"]["discounted"]["period"] == 3 and r["payback"]["simple"]["interpolated"] != r["payback"]["discounted"]["interpolated"]


# ------------------------------------------------------------------------------------------------------------------ cost variance, realization
def test_cost_variance_matured_window_and_its_nulls():
    costs = [cost("p-1", "i-1", "k", "one_time", "100.00", p=0, bv="v1"), cost("p-2", "i-1", "r", "recurring", "10.00", s=1, e=4, bv="v1"),
             cost("p-9", "i-1", "x", "one_time", "5000.00", p=0, bv="v0"),
             cost("a-1", "i-1", "k", "one_time", "130.00", p=0, basis="actual"), cost("a-2", "i-1", "r", "recurring", "12.00", s=1, e=4, basis="actual")]
    d = dataset(initiatives=[ini()], process_baselines=[pb()], scenario_versions=[sc(h=4)], cost_items=costs)
    cv = one(d)["cost_variance"]                           # as_of 2028-06-30: periods 0 and 1 are matured
    assert cv == {"window": {"from_period": 0, "to_period": 2}, "baseline_version": "v1", "approved_baseline_cost": "110.00", "actual_cost": "142.00", "variance": "32.00", "reason": None}
    late = one(d, as_of="2029-01-01T00:00:00Z")["cost_variance"]       # period 2 ends exactly at as_of (half-open): matured
    assert late["window"]["to_period"] == 3 and late["variance"] == "34.00"
    early = one(d, as_of="2026-12-31T23:59:59Z")["cost_variance"]
    assert early["reason"] == "NO_MATURED_PERIOD" and early["variance"] is None and early["actual_cost"] is None
    no_act = one(dataset(initiatives=[ini()], process_baselines=[pb()], scenario_versions=[sc(h=4)], cost_items=costs[:3]))["cost_variance"]
    assert no_act["reason"] == "NO_ACTUALS" and no_act["approved_baseline_cost"] == "110.00" and no_act["variance"] is None
    unapproved = one(dataset(initiatives=[ini(base=None)], scenario_versions=[sc(h=4)], cost_items=costs))["cost_variance"]
    assert unapproved["reason"] == "NO_APPROVED_BASELINE" and unapproved["variance"] is None


def test_capacity_released_reasons_and_decimal_targets():
    d = dataset(initiatives=[ini()], process_baselines=[pb(vol=1000, mins=10)], assumption_versions=[asm("a-t", "i-1", "target_minutes_per_case", value="7.5")], scenario_versions=[sc()])
    assert one(d)["capacity_released"]["hours"] == "41.6667"
    assert one(dataset(initiatives=[ini()], process_baselines=[pb()], scenario_versions=[sc()]))["capacity_released"]["reason"] == "NO_TARGET_ASSUMPTION"
    assert one(dataset(initiatives=[ini(base="v9")], process_baselines=[pb()], scenario_versions=[sc()]))["capacity_released"]["reason"] == "NO_APPROVED_BASELINE"


def test_realization_unobserved_rows_are_listed_never_counted_as_zero_and_the_latest_observation_wins():
    d = dataset(initiatives=[ini()], scenario_versions=[sc(h=3)],
                benefit_items=[ben("b-1", "i-1", "cash", "100.00", 1, trend="10.00"), ben("b-2", "i-1", "cash", "100.00", 1), ben("b-3", "i-1", "cash", "100.00", 2)],
                benefit_observations=[bo("o-1", "b-1", "50.00", "2027-06-01T00:00:00Z"), bo("o-2", "b-1", "80.00", "2027-09-01T00:00:00Z"), bo("o-3", "b-3", "99.00", "2028-02-01T00:00:00Z"),
                                      bo("o-4", "b-2", "70.00", "2029-01-01T00:00:00Z")])
    r = one(d)
    c = r["benefit_realization"]["cash"]
    assert (c["comparable_items"], c["observed_comparable"], c["planned_comparable"], c["realization"]) == (["b-1"], "80.00", "100.00", "0.800000")
    assert c["matured_unobserved_items"] == ["b-2"] and c["baseline_trend"] == "10.00" and c["observed_above_trend"] == "70.00"
    assert r["immature_observation_ids"] == ["o-3"]                     # b-3's period 2 has not ended; o-4 is after as_of and does not exist yet


def test_realization_planned_zero_is_null_and_types_are_never_mixed():
    d = dataset(initiatives=[ini()], scenario_versions=[sc()], benefit_items=[ben("b-1", "i-1", "cash", "0.00", 1), ben("b-2", "i-1", "capacity", "10.00", 1)],
                benefit_observations=[bo("o-1", "b-1", "5.00"), bo("o-2", "b-2", "9.00")])
    rz = one(d)["benefit_realization"]
    assert rz["cash"]["realization"] is None and rz["cash"]["observed_comparable"] == "5.00"
    assert rz["capacity"]["unit"] == "hours" and rz["capacity"]["realization"] == "0.900000" and set(rz) == {"cash", "capacity"}


# ------------------------------------------------------------------------------------------------------------------ people, risk, forecast
def test_adoption_and_training_use_the_latest_record_at_or_before_as_of():
    d = dataset(initiatives=[ini()], adoption_observations=[ad("a-1", "i-1", 40, 10, "2027-01-01T00:00:00Z"), ad("a-2", "i-1", 50, 30, "2028-06-30T00:00:00Z"),
                                                            ad("a-3", "i-1", 50, 50, "2028-06-30T00:00:01Z")],
                training_completions=[tc("t-1", "i-1", 50, 25, "2028-01-01T00:00:00Z"), tc("t-2", "i-1", 50, 45, "2029-01-01T00:00:00Z")])
    m = run(d).metrics["initiatives"]["i-1"]
    assert m["adoption"]["adoption_rate"] == "0.600000" and m["adoption"]["eligible_count"] == 50 and m["adoption"]["excluded_after_as_of"] == ["a-3"]
    assert [s["adoption_rate"] for s in m["adoption"]["series"]] == ["0.250000", "0.600000"]
    assert m["training"]["training_completion"] == "0.500000" and m["training"]["differs_from_adoption"] is True and m["training"]["substituted_for_adoption"] is False


def test_zero_eligible_is_null_and_no_records_is_null():
    d = dataset(initiatives=[ini(), ini("i-2")], adoption_observations=[ad("a-1", "i-1", 0, 0, "2027-01-01T00:00:00Z")], training_completions=[tc("t-1", "i-1", 0, 0, "2027-01-01T00:00:00Z")])
    m = run(d).metrics
    assert m["initiatives"]["i-1"]["adoption"]["adoption_rate"] is None and m["initiatives"]["i-1"]["training"]["training_completion"] is None
    assert m["initiatives"]["i-2"]["adoption"]["latest_observation_id"] is None and m["summary"]["adoption_rate"] is None


def test_risk_exposure_probability_zero_and_one_are_inside_and_no_items_is_null():
    d = dataset(initiatives=[ini(), ini("i-2")], risk_items=[risk("r-1", "i-1", "0.000000", "999.00"), risk("r-2", "i-1", "1.000000", "10.00"), risk("r-3", "i-1", "0.333333", "3.00")])
    m = run(d).metrics["initiatives"]
    assert m["i-1"]["risk"]["risk_exposure"] == "11.00" and m["i-1"]["risk"]["label"] == "scenario estimate" and m["i-2"]["risk"]["risk_exposure"] is None


def test_readiness_latest_per_dimension_weights_ties_and_incomplete_sets():
    d = dataset(initiatives=[ini()], stakeholder_groups=[grp(), grp("g-2")],
                readiness_assessments=[ra("r-1", "g-1", "awareness", 1, at="2027-01-01T00:00:00Z"), ra("r-2", "g-1", "awareness", 5, at="2027-06-01T00:00:00Z"),
                                       ra("r-3", "g-1", "desire", 2, weight="3.00"), ra("r-4", "g-1", "desire", 4, weight="1.50"), ra("r-5", "g-1", "ability", 3, at="2029-01-01T00:00:00Z")])
    g = run(d).metrics["groups"]
    # awareness: the later score 5 (weight 1); desire: the two share an instant, the later id (r-4) wins -> 4 (weight 1.5); ability is after as_of
    assert g["g-1"]["readiness_exact"] == str(F(5 * 1 + 4 * F(3, 2)) / F(5, 2)) and g["g-1"]["dimensions_assessed"] == 2 and g["g-1"]["readiness_score"] == "4.4000"
    assert g["g-2"]["readiness_score"] is None and g["g-2"]["dimensions"] == []


def test_forecast_versions_clipped_at_as_of_and_original_preserved():
    d = dataset(initiatives=[ini()], benefit_items=[ben("b-1", "i-1", "cash", "100.00", 1)], benefit_observations=[bo("o-1", "b-1", "70.00")],
                forecast_versions=[fc("i-1", 1, 1, "100.00"), fc("i-1", 2, 1, "70.00", at="2028-02-01T00:00:00Z"), fc("i-1", 3, 1, "10.00", at="2028-12-01T00:00:00Z")])
    f = run(d).metrics["initiatives"]["i-1"]["forecast"]
    assert [v["version_number"] for v in f["versions"]] == [1, 2] and f["original_version"] == 1 and f["original_preserved"] is True and f["latest_minus_original"] == "-30.00"
    assert f["observed"] == [{"benefit_id": "b-1", "period_index": 1, "measured_value": "70.00", "observed_at": "2028-01-31T00:00:00Z", "period_matured": True}]
    assert run(d, as_of="2026-01-01T00:00:00Z").metrics["initiatives"]["i-1"]["forecast"] is None          # nothing existed yet


# ------------------------------------------------------------------------------------------------------------------ roadmap, resources
def test_feasible_start_chain_ss_fs_binding_dependency_and_no_negative_delay():
    inis = {k: ini(k, start=s, dur=du) for k, s, du in (("a", 0, 2), ("b", 0, 1), ("c", 0, 1), ("d", 10, 1))}
    deps = [dep("d-1", "b", "a", lag=1), dep("d-2", "c", "b", "start_to_start", 3), dep("d-3", "c", "a", "start_to_start", 3), dep("d-4", "d", "a")]
    f = feasible_starts(inis, deps)
    assert f == {"a": (0, None), "b": (3, "d-1"), "c": (6, "d-2"), "d": (10, None)}      # c: b starts at 3, +3 = 6 (d-2) beats a's 0 + 3 = 3 (d-3); d starts later than needed: no delay


def test_dependency_delay_in_the_metrics_and_a_tie_binds_the_first_dependency():
    d = dataset(initiatives=[ini("a"), ini("b"), ini("c", start=1)], dependencies=[dep("d-2", "c", "b"), dep("d-1", "c", "a")])
    r = run(d).metrics["initiatives"]["c"]["roadmap"]
    assert (r["dependency_feasible_start"], r["dependency_delay"], r["binding_dependency_id"], r["finish"], r["resource_constrained_start"], r["resource_delay"]) == (1, 0, None, 2, 1, 0)
    d2 = dataset(initiatives=[ini("a"), ini("b"), ini("c")], dependencies=[dep("d-2", "c", "b"), dep("d-1", "c", "a")])
    r2 = run(d2).metrics["initiatives"]["c"]["roadmap"]
    assert (r2["dependency_feasible_start"], r2["dependency_delay"], r2["binding_dependency_id"]) == (1, 1, "d-1")


def test_a_cycle_in_stored_data_is_a_domain_error_with_the_cycle_listed():
    inis = {k: ini(k) for k in "abc"}
    with pytest.raises(DomainError) as e:
        feasible_starts(inis, [dep("d-1", "a", "b"), dep("d-2", "b", "c"), dep("d-3", "c", "a")])
    assert e.value.code == "DEPENDENCY_CYCLE" and e.value.details["cycle"][0] == e.value.details["cycle"][-1] and len(e.value.details["cycle"]) == 4


def test_cycle_report_starts_at_the_initiative_of_the_rejected_edge():
    d = dataset(initiatives=[ini("a"), ini("b")], dependencies=[dep("d-1", "b", "a"), dep("d-2", "a", "b")])
    rej = validate_batch(d).rejected
    assert rej[0].details["cycle"] == ["a", "b", "a"]
    assert validate_batch(dataset(initiatives=[ini("a")], dependencies=[dep("d-1", "a", "a")])).rejected[0].details["cycle"] == ["a", "a"]


def test_allocations_in_id_order_exactly_at_capacity_allowed_and_the_crossing_row_rejected():
    d = dataset(initiatives=[ini("a"), ini("b")], resources=[resource(cap="2.00"), resource("res-2", "1.00")],
                resource_allocations=[alloc("al-1", "res-1", "a", 0, "1.25"), alloc("al-2", "res-1", "b", 0, "0.75"), alloc("al-3", "res-1", "b", 0, "0.01"),
                                      alloc("al-4", "res-2", "a", 0, "1.00"), alloc("al-5", "res-1", "a", 1, "2.00")])
    r = validate_batch(d)
    assert [(x.id, x.reason_code, x.details["periods"]) for x in r.rejected] == [("al-3", "RESOURCE_OVERALLOCATED", [0])]
    res = run(d).metrics["resources"]
    assert res["res-1"]["by_period"] == [{"period_index": 0, "allocated": "2.00", "headroom": "0.00"}, {"period_index": 1, "allocated": "2.00", "headroom": "0.00"}]
    assert res["res-1"]["overallocated_periods"] == [] and res["res-2"]["by_period"][0]["headroom"] == "0.00"


# ------------------------------------------------------------------------------------------------------------------ double count
def claim(bid, i, amt, key="k", p=1, typ="avoided_cost"):
    return ben(bid, i, typ, amt, p, real=True, ev="budget-line:x", key=key)


def dc(*bens, inis=("a", "b", "c"), h=3):
    d = dataset(initiatives=[ini(i, base=None) for i in inis], scenario_versions=[sc(inis=inis, h=h)], benefit_items=list(bens))
    return run(d).metrics["scenarios"]["scn-1"]["double_count"]


def test_double_count_ties_three_claimants_same_initiative_repeats_and_other_periods():
    tie = dc(claim("b-1", "a", "100.00"), claim("b-2", "b", "100.00"))
    assert (tie["planned_benefits"], tie["attributable_benefits"], tie["residual"]) == ("200.00", "100.00", "100.00") and tie["overlaps"][0]["counted_once"] == "100.00"
    three = dc(claim("b-1", "a", "100.00"), claim("b-2", "b", "250.00"), claim("b-3", "c", "40.00"))
    assert (three["attributable_benefits"], three["residual"], three["overlaps"][0]["overlap"]) == ("250.00", "140.00", "140.00")
    same = dc(claim("b-1", "a", "100.00"), claim("b-2", "a", "100.00"))
    assert same["residual"] == "0.00" and same["overlaps"] == [] and same["explanation_required"] is False
    other = dc(claim("b-1", "a", "100.00", p=1), claim("b-2", "b", "100.00", p=2))
    assert other["residual"] == "0.00"
    nokey = dc(claim("b-1", "a", "100.00", key=None), claim("b-2", "b", "100.00", key=None))
    assert nokey["residual"] == "0.00" and nokey["planned_benefits"] == "200.00"


def test_hours_never_count_and_converted_capacity_is_a_money_claim_at_the_largest():
    inis = ("a", "b")
    d = dataset(initiatives=[ini(i, base=None) for i in inis], scenario_versions=[sc(inis=inis, h=3)],
                assumption_versions=[asm("a-ra", "a", "capacity_hourly_rate", value="10.00", staff="hr:p"), asm("a-rb", "b", "capacity_hourly_rate", value="20.00", staff="hr:p")],
                benefit_items=[ben("b-1", "a", "capacity", "100.00", 1, real=True, key="pool"), ben("b-2", "b", "capacity", "100.00", 1, real=True, key="pool"),
                               ben("b-3", "a", "cash", "5.00", 1)])
    x = run(d).metrics["scenarios"]["scn-1"]["double_count"]
    assert (x["planned_benefits"], x["attributable_benefits"], x["residual"]) == ("3005.00", "2005.00", "1000.00")          # 1000 + 2000 + 5; the pool counts once at 2000


# ------------------------------------------------------------------------------------------------------------------ window, scenarios, as_of
def test_window_narrows_observations_and_periods_half_open_and_says_the_model_is_not_windowed():
    d = dataset(initiatives=[ini()], scenario_versions=[sc(h=3)], process_baselines=[pb()],
                cost_items=[cost("p-1", "i-1", "k", "one_time", "100.00", p=0, bv="v1"), cost("p-2", "i-1", "r", "one_time", "10.00", p=1, bv="v1"),
                            cost("a-1", "i-1", "k", "one_time", "100.00", p=0, basis="actual"), cost("a-2", "i-1", "r", "one_time", "15.00", p=1, basis="actual")],
                adoption_observations=[ad("a-1", "i-1", 10, 1, "2027-03-01T00:00:00Z"), ad("a-2", "i-1", 10, 5, "2027-09-01T00:00:00Z"), ad("a-3", "i-1", 10, 9, "2028-03-01T00:00:00Z")])
    lo, hi = datetime(2027, 1, 1, tzinfo=UTC), datetime(2028, 1, 1, tzinfo=UTC)
    r = run(d, window=(lo, hi))
    assert [s["observation_id"] for s in r.metrics["initiatives"]["i-1"]["adoption"]["series"]] == ["a-1", "a-2"]       # [from, to): 2028-01-01 itself would be out
    cv = r.metrics["scenarios"]["scn-1"]["initiatives"]["i-1"]["cost_variance"]
    assert cv["window"] == {"from_period": 1, "to_period": 2} and cv["variance"] == "5.00"
    assert [w["code"] for w in r.warnings] == ["MODEL_NOT_WINDOWED"]
    assert run(d, window=(None, None)).warnings == [] and len(run(d, window=(None, None)).metrics["initiatives"]["i-1"]["adoption"]["series"]) == 3
    assert run(d, window=(None, lo)).metrics["initiatives"]["i-1"]["adoption"]["series"] == []


def test_scenario_ids_narrow_and_the_summary_follows():
    d = dataset(initiatives=[ini(base=None)], scenario_versions=[sc("scn-a"), sc("scn-b", h=2)], cost_items=[cost("c-1", "i-1", "k", "one_time", "10.00", p=0)])
    m = run(d, scenario_ids=["scn-b"]).metrics
    assert list(m["scenarios"]) == ["scn-b"] and m["summary"]["summary_scenario_id"] == "scn-b" and m["summary"]["scenarios"] == 1
    assert run(d, scenario_ids=["nope"]).metrics["scenarios"] == {}


def test_as_of_time_travel_matures_periods_one_at_a_time():
    d = dataset(initiatives=[ini()], process_baselines=[pb()], scenario_versions=[sc(h=3)], cost_items=[cost("p-1", "i-1", "k", "one_time", "1.00", p=0, bv="v1")])
    ends = {"2026-12-31T23:59:59Z": 0, "2027-01-01T00:00:00Z": 1, "2028-01-01T00:00:00Z": 2, "2029-01-01T00:00:00Z": 3, "2040-01-01T00:00:00Z": 3}
    for as_of, n in ends.items():
        assert one(d, as_of=as_of)["cost_variance"]["window"]["to_period"] == n, as_of


def test_canonical_amount_text():
    assert [canon(x) for x in ("1000.000000", "0.5", "7", "0.125000", "-3.10", "12.340000")] == ["1000.00", "0.50", "7.00", "0.125", "-3.10", "12.34"]


# ------------------------------------------------------------------------------------------------------------------ review 9 (contract D-09)
def _with(row, **kw):
    return {**row, **kw}


def test_a_scenario_is_built_on_the_plan_and_assumptions_that_existed_when_it_was_created():
    """R9-01: assumption versions and plan rows that came after the scenario do not enter it; a pinned version always does; a later scenario sees them."""
    base = dict(initiatives=[ini(base=None)],
                assumption_versions=[_with(asm("a-r1", "i-1", "adoption_ramp", 1, values=["0.500000", "1.000000"]), created_at="2026-01-10T00:00:00Z"),
                                     _with(asm("a-r2", "i-1", "adoption_ramp", 2, values=["0.100000", "0.200000"]), created_at="2026-02-10T00:00:00Z")],
                cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0), _with(cost("c-2", "i-1", "k2", "one_time", "50.00", p=1), recorded_at="2026-02-01T00:00:00Z")],
                benefit_items=[ben("b-1", "i-1", "cash", "200.00", 1), _with(ben("b-2", "i-1", "cash", "400.00", 2, starts=1), recorded_at="2026-02-01T00:00:00Z")])
    early = _with(sc("early"), created_at="2026-01-15T00:00:00Z")
    late = _with(sc("late"), created_at="2026-03-01T00:00:00Z")
    pinned = _with(sc("pinned", pins=("a-r2",)), created_at="2026-01-15T00:00:00Z")
    m = run(dataset(scenario_versions=[early, late, pinned], **base)).metrics["scenarios"]
    e, l, p = (m[k]["initiatives"]["i-1"] for k in ("early", "late", "pinned"))
    assert e["ramp"]["assumption_id"] == "a-r1" and l["ramp"]["assumption_id"] == "a-r2" and p["ramp"]["assumption_id"] == "a-r2"      # latest by then; latest later; pinned wins
    assert [r["costs"] for r in e["cash_flow"]] == ["100.00", "0.00", "0.00"] and [r["costs"] for r in l["cash_flow"]] == ["100.00", "50.00", "0.00"]
    assert [r["cash_benefits"] for r in e["cash_flow"]] == ["0.00", "100.00", "0.00"] and [r["cash_benefits"] for r in l["cash_flow"]] == ["0.00", "20.00", "80.00"]
    assert e["excluded_from_cash_flow"]["beyond_horizon"] == [] and len(e["expanded_planned_costs"]) == 1 and len(l["expanded_planned_costs"]) == 2
    nothing = run(dataset(scenario_versions=[_with(sc("before"), created_at="2026-01-01T00:00:00Z")], **base)).metrics["scenarios"]["before"]["initiatives"]["i-1"]
    assert nothing["ramp"] is None                                                       # no version existed yet: no ramp is invented from the future


def test_plan_rows_recorded_later_do_not_move_a_costs_variance_or_a_realization_of_an_earlier_scenario():
    d = dataset(initiatives=[ini(base="v1")], process_baselines=[pb()], scenario_versions=[_with(sc(h=3), created_at="2026-01-15T00:00:00Z")],
                cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0, bv="v1"), cost("c-a", "i-1", "k", "one_time", "100.00", p=0, basis="actual"),
                            _with(cost("c-2", "i-1", "k2", "one_time", "50.00", p=1, bv="v1"), recorded_at="2027-01-01T00:00:00Z")],
                benefit_items=[ben("b-1", "i-1", "cash", "300.00", 1, trend="10.00"), _with(ben("b-2", "i-1", "cash", "300.00", 1, trend="10.00"), recorded_at="2027-01-01T00:00:00Z")],
                benefit_observations=[bo("o-1", "b-1", "250.00"), bo("o-2", "b-2", "100.00")])
    i = one(d)
    assert i["cost_variance"]["approved_baseline_cost"] == "100.00" and i["benefit_realization"]["cash"]["comparable_items"] == ["b-1"]


def test_the_portfolio_npv_counts_a_shared_claim_once_at_the_largest_claim_discounted_in_its_own_period():
    """R9-02: three initiatives claim one source in periods 1 and 2: 100 / 150 / 70 and 40 / 40 / 10. Counted once at the largest."""
    inis = ["i-1", "i-2", "i-3"]
    d = dataset(initiatives=[ini(i) for i in inis], scenario_versions=[sc(inis=inis, rate="0.100000", h=3)],
                cost_items=[cost(f"c-{i}", i, "k", "one_time", "10.00", p=0) for i in inis],
                benefit_items=[ben(f"b-{i}-{p}", i, "cash", str(a), p, starts=1, key="src") for i, p, a in (("i-1", 1, 100), ("i-2", 1, 150), ("i-3", 1, 70), ("i-1", 2, 40), ("i-2", 2, 40), ("i-3", 2, 10))])
    s = run(d).metrics["scenarios"]["scn-1"]
    dc = s["double_count"]
    assert (dc["planned_benefits"], dc["residual"], dc["attributable_benefits"]) == ("410.00", "220.00", "190.00")             # 320 + 90 claimed, kept 150 + 40, removed 170 + 50
    pv = F(100 + 70, 1) / F(11, 10) + F(40 + 10, 1) / F(11, 10) ** 2                                                  # the removed claims: 170 in period 1, 50 in period 2 (the first of the equal 40s is kept)
    assert F(dc["double_counted_pv_exact"]) == pv and dc["double_counted_amount"] == dc["residual"] == "220.00"
    total = sum(F(b["npv"]["exact"]) for b in s["initiatives"].values())
    assert F(s["npv_total"]["exact"]) == total - pv and s["npv_total"]["sum_of_initiatives"] == money_of(total)
    assert dc["double_counted_by_class_exact"]["cash"] == "220"                                                       # 170 + 50 removed, all of it cash
    assert [c["initiative_id"] for c in dc["overlaps"][1]["claims"]] == ["i-1", "i-2", "i-3"] and dc["overlaps"][1]["counted_once"] == "40.00"


def money_of(x):
    from changeworks.numbers import money
    return money(x)


def test_a_claim_that_does_not_enter_the_cash_flow_is_removed_from_the_amount_but_not_from_the_npv():
    """R9-02: avoided cost that no budget line removed is beside the cash flow; if it is the removed claim it counts twice in the amount and never in the NPV."""
    d = dataset(initiatives=[ini("i-1"), ini("i-2")], scenario_versions=[sc(inis=["i-1", "i-2"], rate="0.000000", h=3)],
                benefit_items=[ben("b-1", "i-1", "avoided_cost", "100.00", 1, real=False, key="src"), ben("b-2", "i-2", "cash", "300.00", 1, key="src")])
    s = run(d).metrics["scenarios"]["scn-1"]
    assert s["double_count"]["residual"] == "100.00" and s["double_count"]["double_counted_pv"] == "0.00"                                 # the 100 beside the flow never was in the NPV
    assert s["npv_total"]["value"] == s["npv_total"]["sum_of_initiatives"] == "300.00" and s["double_count"]["double_counted_by_class"]["avoided_cost_beside"] == "100.00"


def test_hours_claimed_twice_are_a_second_residual_and_the_released_hours_total_counts_them_once():
    """R9-03: money and hours are separate rules; either one needs the explanation; the pooled released hours count the shared team once, at the larger figure."""
    d = dataset(initiatives=[ini("i-1"), ini("i-2"), ini("i-3")], process_baselines=[pb("i-1", vol=1200, mins=10), pb("i-2", vol=600, mins=10), pb("i-3", vol=60, mins=10)],
                assumption_versions=[asm(f"a-{k}", f"i-{k}", "target_minutes_per_case", value="8") for k in (1, 2, 3)],
                scenario_versions=[sc(inis=["i-1", "i-2", "i-3"], h=3)],
                benefit_items=[ben("b-1", "i-1", "capacity", "40.00", 1, key="team"), ben("b-2", "i-2", "capacity", "60.00", 1, key="team"), ben("b-3", "i-3", "capacity", "5.00", 1, key="team")])
    r = run(d)
    dc = r.metrics["scenarios"]["scn-1"]["double_count"]
    assert (dc["residual"], dc["planned_hours"], dc["attributable_hours"], dc["hours_residual"], dc["explanation_required"], dc["explanation_required_for"]) == \
        ("0.00", "105.00", "60.00", "45.00", True, ["hours"]) and dc["hours_overlaps"][0]["counted_once"] == "60.00" and len(dc["hours_overlaps"][0]["claims"]) == 3
    s = r.metrics["summary"]                                                                    # released per period: 40 + 20 + 2 hours; the three share a team: counted once, at 40
    assert (s["capacity_released_hours_total"], s["capacity_released_hours_double_counted"], s["hours_residual"]) == ("40.0000", "22.0000", "45.00")
    apart = dataset(initiatives=[ini("i-1"), ini("i-2")], process_baselines=[pb("i-1"), pb("i-2")], assumption_versions=[asm("a-1", "i-1", "target_minutes_per_case", value="8"),
                    asm("a-2", "i-2", "target_minutes_per_case", value="8")], scenario_versions=[sc(inis=["i-1", "i-2"], h=3)],
                    benefit_items=[ben("b-1", "i-1", "capacity", "40.00", 1, key="team"), ben("b-2", "i-2", "capacity", "60.00", 2, key="team")])          # the same team in different periods
    assert run(apart).metrics["scenarios"]["scn-1"]["double_count"]["hours_residual"] == "0.00" and run(apart).metrics["summary"]["capacity_released_hours_double_counted"] == "0.0000"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n", "　", "   "])
def test_blank_evidence_is_refused_everywhere_an_evidence_reference_is_given(blank):
    """R9-04 (Python strip() whitespace, the ideographic space included)."""
    d = dataset(initiatives=[ini()], assumption_versions=[_with(asm("a-1", "i-1", "capacity_hourly_rate", value="30.00"), staffing_change_evidence_ref=blank),
                                                          _with(asm("a-2", "i-1", "target_minutes_per_case", value="8"), evidence_ref=blank)],
                benefit_items=[ben("b-1", "i-1", "avoided_cost", "10.00", 1, real=True, ev=blank)], process_baselines=[_with(pb(), evidence_ref=blank)],
                benefit_observations=[_with(bo("o-1", "b-1", "1.00"), evidence_ref=blank)])
    got = codes(d)
    assert got[("assumption_versions", "a-1")] == got[("assumption_versions", "a-2")] == got[("benefit_items", "b-1")] == got[("process_baselines", "pb-i-1-v1")] == "EVIDENCE_REQUIRED"
    assert got[("benefit_observations", "o-1")] == "DEPENDENT_REJECTED"                         # its benefit was refused; on its own it is refused for the same reason
    assert codes(dataset(initiatives=[ini()], benefit_items=[ben("b-1", "i-1", "cash", "1.00", 1)], benefit_observations=[_with(bo("o-1", "b-1", "1.00"), evidence_ref=blank)])) == \
        {("benefit_observations", "o-1"): "EVIDENCE_REQUIRED"}


def test_the_cash_flow_tests_the_stripped_evidence_even_for_a_population_that_skipped_ingest():
    """Defence in depth: rows that reach the calculation without the validator (an old database) still cannot use '   ' as evidence."""
    d = dataset(initiatives=[ini(base=None)], scenario_versions=[sc(h=3)], assumption_versions=[asm("a-c", "i-1", "capacity_hourly_rate", value="40.00", staff="  ")],
                benefit_items=[ben("b-1", "i-1", "avoided_cost", "999.00", 1, real=True, ev="   "), ben("b-2", "i-1", "capacity", "10.00", 1)])
    pop = validate_batch({**d, "assumption_versions": [], "benefit_items": []}).population
    pop.acc["assumption_versions"], pop.acc["benefit_items"] = d["assumption_versions"], d["benefit_items"]
    from changeworks import compute
    from changeworks.timeutil import parse_ts
    i = compute(pop, parse_ts("2028-06-30T00:00:00Z"))[0]["scenarios"]["scn-1"]["initiatives"]["i-1"]
    assert [x["reason"] for x in i["excluded_from_cash_flow"]["avoided_cost_beside"]] == ["NO_EVIDENCE_REF"] and i["converted_capacity"] == []


def test_a_cost_key_is_one_kind_of_cost_for_an_initiative_and_a_basis():
    """R9-05."""
    d = dataset(initiatives=[ini(), ini("i-2")], cost_items=[cost("c-1", "i-1", "k", "one_time", "100.00", p=0), cost("c-2", "i-1", "k", "recurring", "10.00", s=1, e=3),
                                                             cost("c-3", "i-1", "k", "recurring", "10.00", s=1, e=3, basis="actual"), cost("c-4", "i-2", "k", "recurring", "10.00", s=1, e=3),
                                                             cost("c-5", "i-1", "k", "recurring", "10.00", s=3, e=5, basis="actual")])
    assert codes(d) == {("cost_items", "c-2"): "COST_KEY_BASIS_CONFLICT"}                       # another basis and another initiative are free; recurring tranches of one key are fine
    r = validate_batch(d).rejected[0]
    assert r.details == {"first_cost_id": "c-1", "first_cost_type": "one_time", "this_cost_type": "recurring", "cost_key": "k", "cost_basis": "planned"}


@pytest.mark.parametrize("start", ["2026-01-29", "2026-01-31", "2026-02-30", "2026-13-01", "26-01-01", "2026-1-1", "", "soon", None, 20260101])
def test_a_period_start_with_a_day_over_28_or_not_a_date_is_refused_cleanly(start):
    """R9-14: PERIOD_START_INVALID, not a crash somewhere in the calendar."""
    d = dataset(initiatives=[ini()], scenario_versions=[sc()])
    d["period_start"] = start
    with pytest.raises(DomainError) as e:
        run(d)
    assert e.value.code == "PERIOD_START_INVALID"


def test_a_period_start_of_the_28th_is_fine_in_every_month():
    d = dataset("monthly", initiatives=[ini(base=None)], scenario_versions=[sc(rate="0.010000", basis="monthly", h=14)], cost_items=[cost("c-1", "i-1", "k", "one_time", "1.00", p=0)])
    d["period_start"] = "2026-01-28"
    rows = one(d)["cash_flow"]
    assert [r["period_start"] for r in rows][:3] == ["2026-01-28", "2026-02-28", "2026-03-28"] and rows[13]["period_start"] == "2027-02-28"


def test_an_error_rate_outside_0_1_is_invalid_field_and_a_negative_volume_is_invalid_amount():
    """R9-22."""
    assert codes(dataset(initiatives=[ini()], process_baselines=[_with(pb(), error_rate="1.500000")])) == {("process_baselines", "pb-i-1-v1"): "INVALID_FIELD"}
    r = validate_batch(dataset(initiatives=[ini()], process_baselines=[_with(pb(), error_rate="1.500000")])).rejected[0]
    assert r.details == {"field": "error_rate", "reason": "a proportion in [0, 1]"}
    assert codes(dataset(initiatives=[ini()], process_baselines=[_with(pb(), volume=-1)])) == {("process_baselines", "pb-i-1-v1"): "INVALID_AMOUNT"}


def test_observations_count_when_recorded_and_a_same_day_tie_goes_to_the_later_record():
    """R9-11."""
    d = dataset(initiatives=[ini()], adoption_observations=[ad("a-1", "i-1", 40, 10, "2028-03-31T00:00:00Z"),
                                                          _with(ad("a-2", "i-1", 40, 20, "2028-03-31T00:00:00Z"), recorded_at="2028-04-01T00:00:00Z"),
                                                          _with(ad("a-3", "i-1", 40, 30, "2028-03-31T00:00:00Z"), recorded_at="2028-07-05T00:00:00Z")],
                training_completions=[tc("t-1", "i-1", 40, 38, "2028-03-31T00:00:00Z"), _with(tc("t-2", "i-1", 40, 40, "2028-03-31T00:00:00Z"), entered_at="2028-07-05T00:00:00Z")])
    m = run(d, as_of="2028-06-30T00:00:00Z").metrics["initiatives"]["i-1"]
    assert (m["adoption"]["latest_observation_id"], m["adoption"]["adoption_rate"], m["adoption"]["late_recorded"]) == ("a-2", "0.500000", ["a-3"])
    assert (m["training"]["training_id"], m["training"]["late_recorded"]) == ("t-1", ["t-2"])
    later = run(d, as_of="2028-07-06T00:00:00Z").metrics["initiatives"]["i-1"]
    assert (later["adoption"]["latest_observation_id"], later["adoption"]["late_recorded"], later["training"]["training_id"]) == ("a-3", [], "t-2")
    with_window = run(d, as_of="2028-07-06T00:00:00Z", window=(datetime(2028, 4, 1, tzinfo=UTC), None)).metrics["initiatives"]["i-1"]
    assert with_window["adoption"]["series"] == []                                             # the window still applies to the event time


def test_partial_trend_coverage_withholds_observed_above_trend_and_lists_the_rows():
    """R9-13."""
    d = dataset(initiatives=[ini(base=None)], scenario_versions=[sc(h=3)], benefit_items=[ben("b-1", "i-1", "cash", "100.00", 1, trend="10.00"), ben("b-2", "i-1", "cash", "100.00", 1, trend=None)],
                benefit_observations=[bo("o-1", "b-1", "90.00", "2027-06-30T00:00:00Z"), bo("o-2", "b-2", "80.00", "2027-06-30T00:00:00Z")])
    r = run(d)
    cash = r.metrics["scenarios"]["scn-1"]["initiatives"]["i-1"]["benefit_realization"]["cash"]
    assert (cash["baseline_trend"], cash["observed_above_trend"], cash["trend_coverage"]) == ("10.00", None, {"complete": False, "rows_without_trend": ["b-2"]})
    w = [x for x in r.warnings if x["code"] == "PARTIAL_TREND_COVERAGE"]
    assert len(w) == 1 and w[0]["rows"] == ["b-2"] and w[0]["path"].endswith("benefit_realization.cash")
    full = run({**d, "benefit_items": [_with(b, baseline_trend_per_period="10.00") for b in d["benefit_items"]]})
    cash = full.metrics["scenarios"]["scn-1"]["initiatives"]["i-1"]["benefit_realization"]["cash"]
    assert cash["observed_above_trend"] == "150.00" and cash["trend_coverage"]["complete"] and not [x for x in full.warnings if x["code"] == "PARTIAL_TREND_COVERAGE"]
    none = run({**d, "benefit_items": [_with(b, baseline_trend_per_period=None) for b in d["benefit_items"]]})
    assert none.metrics["scenarios"]["scn-1"]["initiatives"]["i-1"]["benefit_realization"]["cash"]["observed_above_trend"] is None and not none.warnings


def test_aggregates_are_exact_sums_rounded_once():
    """R9-07: three 0.004-hour rows are 0.012 hours, not 0.00; two exposures of 0.005 are 0.010, not 0.02; the forecast difference is of exact totals."""
    d = dataset(initiatives=[ini(base=None), ini("i-2", base=None)], scenario_versions=[sc(inis=["i-1", "i-2"], h=4)],
                benefit_items=[ben(f"b-{k}", "i-1", "capacity", "0.004", k, starts=1) for k in (1, 2, 3)] + [ben(f"a-{k}", "i-2", "avoided_cost", "0.004", k, starts=1, real=False) for k in (1, 2, 3)],
                risk_items=[risk("r-1", "i-1", "0.005000", "1.00"), risk("r-2", "i-2", "0.005000", "1.00")],
                forecast_versions=[fc("i-1", 1, 1, "100.004"), fc("i-1", 1, 2, "100.004"), fc("i-1", 2, 1, "100.002", at="2026-02-01T00:00:00Z"), fc("i-1", 2, 2, "100.002", at="2026-02-01T00:00:00Z")])
    m = run(d).metrics
    blk = m["scenarios"]["scn-1"]["initiatives"]
    assert blk["i-1"]["excluded_from_cash_flow"]["capacity_hours_not_converted"] == "0.01" and blk["i-2"]["excluded_from_cash_flow"]["avoided_cost_beside_total"] == "0.01"
    assert [x["hours"] for x in blk["i-1"]["excluded_from_cash_flow"]["capacity_not_converted"]] == ["0.00"] * 3          # each row shown as it is, the total is not their sum
    assert m["summary"]["risk_exposure_total"] == "0.01" and (m["initiatives"]["i-1"]["risk"]["risk_exposure"], m["initiatives"]["i-2"]["risk"]["risk_exposure"]) == ("0.01", "0.01")
    f = m["initiatives"]["i-1"]["forecast"]
    assert (f["versions"][0]["total"], f["versions"][1]["total"]) == ("200.01", "200.00")
    assert f["latest_minus_original"] == "-0.00"[1:]                      # 200.004 - 200.008 = -0.004: the exact difference rounds to 0.00 (the totals as shown would say -0.01)


def test_a_revision_must_restate_the_original_periods_to_have_a_difference_and_the_preserved_flag_is_read_from_the_rows():
    """R9-10: a partial revision has no difference (null), a missing version 1 is not a preserved original."""
    d = dataset(initiatives=[ini()], forecast_versions=[fc("i-1", 1, 1, "600.00"), fc("i-1", 1, 2, "600.00"), fc("i-1", 2, 2, "550.00", at="2026-02-01T00:00:00Z")])
    f = run(d).metrics["initiatives"]["i-1"]["forecast"]
    assert (f["revisions_cover_original_periods"], f["latest_minus_original"], f["original_preserved"]) == (False, None, True)
    d = dataset(initiatives=[ini()], forecast_versions=[fc("i-1", 2, 1, "600.00")])
    f = run(d).metrics["initiatives"]["i-1"]["forecast"]
    assert (f["original_version"], f["original_preserved"]) == (2, False)


def test_deployment_before_the_feasible_start_is_a_warning_on_the_roadmap_and_in_the_warnings_list():
    """R9-06: i-2 deploys at 1 but its prerequisite finishes at 3."""
    d = dataset(initiatives=[ini("i-1", dur=3), ini("i-2", dep=1)], dependencies=[dep("d-1", "i-2", "i-1")])
    r = run(d)
    assert r.metrics["initiatives"]["i-2"]["roadmap"]["warnings"] == [{"code": "DEPLOYMENT_BEFORE_FEASIBLE_START", "deployment_period": 1, "dependency_feasible_start": 3, "periods_early": 2}]
    assert r.metrics["initiatives"]["i-1"]["roadmap"]["warnings"] == [] and [w["code"] for w in r.warnings] == ["DEPLOYMENT_BEFORE_FEASIBLE_START"]
