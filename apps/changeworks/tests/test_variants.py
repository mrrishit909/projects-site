"""The two variants through the pure domain: the rejected-record variant (P09-GOLD-08) and the empty population (P09-GOLD-09), leaf for leaf."""
import pytest

from changeworks import run_pipeline

from support_db import flat, golden_expected, golden_inputs


@pytest.mark.parametrize("variant,leaves", [("variant-rejected", 2277), ("variant-empty", 57)])
def test_variant_equals_expected_json_leaf_for_leaf(variant, leaves):
    exp, got = flat(golden_expected(variant)), flat(run_pipeline(golden_inputs(variant)).golden())
    assert set(exp) == set(got) and [k for k in exp if exp[k] != got[k]] == []
    assert len(exp) == leaves


def test_rejected_variant_30_records_with_reason_codes_and_cascades():
    r = run_pipeline(golden_inputs("variant-rejected"))
    rej = {x["id"] + "/" + x["entity"]: x for x in r.ingest.rejected_records()}
    assert len(rej) == 30 and sum(v["rejected"] for v in r.counts.values()) == 30
    code = lambda rid, ent: rej[f"{rid}/{ent}"]["reason_code"]
    assert code("rj-i5", "initiatives") == "STATUS_NOT_ALLOWED" and code("rj-i1", "initiatives") == "DUPLICATE_ID"
    assert code("rd-3", "dependencies") == "DEPENDENCY_CYCLE" and rej["rd-3/dependencies"]["details"]["cycle"] == ["rj-i1", "rj-i3", "rj-i2", "rj-i1"]
    assert code("rc-8", "cost_items") == "DEPENDENT_REJECTED" and code("rc-7", "cost_items") == "UNKNOWN_INITIATIVE"      # parent rejected vs parent unknown
    assert code("rbo-2", "benefit_observations") == "DEPENDENT_REJECTED" and code("rbo-3", "benefit_observations") == "UNKNOWN_BENEFIT"
    assert code("al-r2", "resource_allocations") == "RESOURCE_OVERALLOCATED" and rej["al-r2/resource_allocations"]["details"]["periods"] == [0]
    assert code("rs-1", "scenario_versions") == "RATE_PERIOD_MISMATCH" and code("rs-4", "scenario_versions") == "STATUS_NOT_ALLOWED"
    assert code("rc-2", "cost_items") == "ONE_TIME_COST_REPEATED" and code("rb-7", "benefit_items") == "CAPACITY_WITHOUT_CONVERSION"
    assert all(v["raw_row"] for v in rej.values()) and all(v["status"] == "rejected" for v in rej.values())      # nothing is silently dropped


def test_valid_records_around_a_rejection_are_unaffected():
    r = run_pipeline(golden_inputs("variant-rejected"))
    assert r.counts["cost_items"] == {"accepted": 11, "rejected": 3}      # five original rows and six probe rows
    sc = r.metrics["scenarios"]
    assert "rs-1" not in sc and "rs-4" not in sc and "rs-5" not in sc and set(sc) == {"rs-2", "rs-3", "rs-6", "rs-7"}
    assert sc["rs-2"]["initiatives"]["rj-i1"]["npv"]["value"] == "919.31"                    # the first row of ck-a is kept; rc-3 expands to 3 rows
    assert len(sc["rs-2"]["initiatives"]["rj-i1"]["expanded_planned_costs"]) == 4


def test_monthly_periods_use_the_declared_conversion_exactly():
    sc = run_pipeline(golden_inputs("variant-rejected")).metrics["scenarios"]["rs-2"]
    assert (sc["rate_source"], sc["effective_period_rate"], sc["effective_period_rate_exact"]) == ("conversion:ra-conv", "0.007974", "3987/500000")
    assert sc["initiatives"]["rj-i4"]["converted_capacity"][0]["amount"] == "2500.00" and sc["initiatives"]["rj-i4"]["converted_capacity"][0]["conversion_assumption_id"] == "ra-cap"
    assert sc["initiatives"]["rj-i3"]["excluded_from_cash_flow"]["avoided_cost_beside"][0]["reason"] == "NO_EVIDENCE_REF"
    assert [r["period_start"] for r in sc["initiatives"]["rj-i1"]["cash_flow"]] == ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]


def test_empty_population_counts_ratios_and_npv_are_null_not_zero():
    r = run_pipeline(golden_inputs("variant-empty"))
    m = r.metrics
    assert r.empty_population is True and all(v == {"accepted": 0, "rejected": 0} for v in r.counts.values())
    assert m["scenarios"] == {} and m["initiatives"] == {} and m["groups"] == {} and m["resources"] == {}
    assert all(v is None for k, v in m["summary"].items() if k not in ("initiatives", "scenarios")) and m["summary"]["initiatives"] == 0 == m["summary"]["scenarios"]


def test_a_dataset_that_loses_every_initiative_is_an_empty_population():
    d = golden_inputs("variant-rejected")
    d["initiatives"] = [i for i in d["initiatives"] if i["status"] == "funded"]       # the only initiative is rejected: nothing accepted
    r = run_pipeline(d)
    assert r.empty_population and r.metrics["summary"]["npv_total"] is None
    assert r.counts["initiatives"]["accepted"] == 0 and r.counts["cost_items"]["accepted"] == 0         # every child is rejected, none invented


def test_probe_block_pins_the_payback_series_the_first_crossing_rule_got_wrong():
    """R9-12 (hand arithmetic in CALCULATION.md): rate 0, horizon 5."""
    sc = run_pipeline(golden_inputs("variant-rejected")).metrics["scenarios"]
    pb = lambda s, i: sc[s]["initiatives"][i]["payback"]["simple"]
    assert pb("rs-6", "rj-p1") == {"period": None, "interpolated": None, "reason": "NO_INVESTMENT"}        # cumulative 0, 600, 1200: nothing was invested
    assert pb("rs-6", "rj-p2") == {"period": 3, "interpolated": "2.2000", "reason": None}                 # -1000, 200, -100, 400, 400: back for good at 3
    assert pb("rs-6", "rj-p3") == {"period": None, "interpolated": None, "reason": "NOT_RECOVERED"}       # -1000, 500, -200, -200, -200
    assert pb("rs-6", "rj-p4") == {"period": 2, "interpolated": "1.5000", "reason": None}
    assert pb("rs-6", "rj-p5") == {"period": None, "interpolated": None, "reason": "NO_FLOWS"}
    assert sc["rs-6"]["initiatives"]["rj-p5"]["npv"]["value"] is None


def test_probe_block_a_scenario_is_built_on_the_plan_that_existed_when_it_was_created():
    sc = run_pipeline(golden_inputs("variant-rejected")).metrics["scenarios"]
    assert len(sc["rs-6"]["initiatives"]["rj-p2"]["expanded_planned_costs"]) == 2 and sc["rs-6"]["initiatives"]["rj-p2"]["npv"]["value"] == "400.00"
    assert len(sc["rs-7"]["initiatives"]["rj-p2"]["expanded_planned_costs"]) == 3 and sc["rs-7"]["initiatives"]["rj-p2"]["npv"]["value"] == "-100.00"


def test_probe_block_hours_claimed_twice_partial_trend_and_late_records():
    r = run_pipeline(golden_inputs("variant-rejected"))
    dc = r.metrics["scenarios"]["rs-6"]["double_count"]
    assert (dc["planned_hours"], dc["attributable_hours"], dc["hours_residual"], dc["residual"], dc["explanation_required_for"]) == ("100.00", "60.00", "40.00", "0.00", ["hours"])
    cash = r.metrics["scenarios"]["rs-6"]["initiatives"]["rj-p4"]["benefit_realization"]["cash"]
    assert (cash["realization"], cash["baseline_trend"], cash["observed_above_trend"], cash["trend_coverage"]) == \
        ("0.850000", "10.00", None, {"complete": False, "rows_without_trend": ["rb-p4b"]})
    assert [w["code"] for w in r.warnings if "rj-p4" in w["path"]] == ["PARTIAL_TREND_COVERAGE"]
    m = r.metrics["initiatives"]["rj-i1"]
    assert m["adoption"]["late_recorded"] == ["rao-4"] and m["adoption"]["adoption_rate"] == "0.400000" and m["training"]["late_recorded"] == ["rt-3"]
    assert r.metrics["scenarios"]["rs-6"]["initiatives"]["rj-p4"]["late_recorded_observation_ids"] == ["rbo-p4c"]
