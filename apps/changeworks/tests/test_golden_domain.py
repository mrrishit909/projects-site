"""The golden fixture through the pure domain: every figure equals expected.json leaf for leaf (P09-GOLD-01..07, P09-MET-01..12)."""
from fractions import Fraction as F

import pytest

from changeworks import run_pipeline
from changeworks.numbers import rnd

from support_db import flat, golden_expected, golden_inputs

LEAVES = 572


@pytest.fixture(scope="module")
def result():
    return run_pipeline(golden_inputs())


def test_whole_shape_equals_expected_json_leaf_for_leaf(result):
    exp, got = flat(golden_expected()), flat(result.golden())
    assert set(exp) == set(got)
    assert [k for k in exp if exp[k] != got[k]] == []
    assert len(exp) == LEAVES                                     # the number of leaves of expected.json


def test_the_metrics_tree_has_the_key_nesting_of_expected_json(result):
    want = golden_expected()["metrics"]
    assert list(result.metrics) == list(want) == ["summary", "scenarios", "initiatives", "groups", "resources"]
    sc = result.metrics["scenarios"]["scn-001"]
    assert set(sc) == set(want["scenarios"]["scn-001"])
    assert set(sc["initiatives"]["init-001"]) == set(want["scenarios"]["scn-001"]["initiatives"]["init-001"])
    assert set(result.metrics["initiatives"]["init-001"]) == {"roadmap", "adoption", "training", "risk", "forecast"}


@pytest.mark.parametrize("entity", list(golden_expected()["ingest"]["counts"]))
def test_ingest_counts_per_entity(result, entity):
    assert result.counts[entity] == golden_expected()["ingest"]["counts"][entity]
    assert result.ingest.rejected_records() == []


def test_spec_sentence_p09_gold_01(result):
    """cost 1000 at period 0, 600 and 600 net inflows, 10% annual: NPV = 5000/121 = 41.32; paybacks labelled separately; the 800 capacity hours are excluded."""
    i1 = result.metrics["scenarios"]["scn-001"]["initiatives"]["init-001"]
    assert [r["net_cash_flow"] for r in i1["cash_flow"]] == ["-1000.00", "600.00", "600.00"]
    assert i1["npv"] == {"value": "41.32", "exact": "5000/121", "unit": "USD", "label": "estimate"}
    assert F(i1["npv"]["exact"]) == -1000 + F(600) / F(11, 10) + F(600) / F(11, 10) ** 2
    assert i1["payback"]["simple"] == {"period": 2, "interpolated": "1.6667"}
    assert i1["payback"]["discounted"] == {"period": 2, "interpolated": "1.9167"}                # two different numbers, two labels
    assert i1["excluded_from_cash_flow"]["capacity_hours_not_converted"] == "800.00"
    assert all(r["cash_benefits"] in ("0.00", "600.00") for r in i1["cash_flow"])               # hours are never added to dollars
    assert i1["capacity_released"]["hours"] == "400.0000"


def test_ramp_lag_and_benefit_classes_of_init_002(result):
    i2 = result.metrics["scenarios"]["scn-001"]["initiatives"]["init-002"]
    assert [r["net_cash_flow"] for r in i2["cash_flow"]] == ["-500.00", "100.00", "425.00"]
    assert i2["unramped_net_cash_flow"] == ["-500.00", "300.00", "550.00"]                      # the unramped plan stays visible beside the ramped one
    assert i2["cash_flow"][2]["benefits_by_class"] == {"cash": "400.00", "revenue": "50.00", "avoided_cost_realised": "75.00", "capacity_converted": "0.00"}
    assert i2["excluded_from_cash_flow"]["avoided_cost_beside_total"] == "120.00"
    assert [r["amount"] for r in i2["expanded_planned_costs"]] == ["500.00", "100.00", "100.00"]  # the recurring cost, expanded explicitly
    assert i2["payback"]["discounted"] == {"period": None, "interpolated": None}


def test_null_is_unknown_never_zero(result):
    i3 = result.metrics["scenarios"]["scn-001"]["initiatives"]["init-003"]
    assert i3["capacity_released"]["hours"] is None and i3["cost_variance"]["variance"] is None
    assert i3["payback"]["simple"]["period"] is None
    m = result.metrics
    assert m["initiatives"]["init-003"]["adoption"]["adoption_rate"] is None and m["initiatives"]["init-003"]["risk"]["risk_exposure"] is None
    assert m["groups"]["grp-003"]["readiness_score"] is None
    assert m["scenarios"]["scn-001"]["initiatives"]["init-001"]["cost_variance"]["variance"] == "0.00"       # a real zero is not null


def test_double_count_residual_at_the_largest_claim(result):
    dc = result.metrics["scenarios"]["scn-001"]["double_count"]
    assert (dc["planned_benefits"], dc["attributable_benefits"], dc["residual"], dc["explanation_required"]) == ("2195.00", "2120.00", "75.00", True)
    assert dc["overlaps"][0]["counted_once"] == "150.00" and [c["amount"] for c in dc["overlaps"][0]["claims"]] == ["75.00", "150.00"]


def test_summary_pools_only_what_can_be_pooled(result):
    s = result.metrics["summary"]
    assert s["adoption_rate"] == "0.555556" and s["training_completion"] == "0.950000" and s["npv_total"] == "-692.56"
    assert s["risk_exposure_total"] == "2500.00" and s["capacity_released_hours_total"] == "1000.0000"
    assert set(s) == {"summary_scenario_id", "initiatives", "scenarios", "npv_total", "double_count_residual", "adoption_rate", "training_completion",
                      "risk_exposure_total", "capacity_released_hours_total"}                    # no pooled payback, realization, readiness, variance or delay


def test_no_float_anywhere_in_inputs_or_outputs(result):
    def walk(x):
        if isinstance(x, float):
            raise AssertionError(x)
        if isinstance(x, dict):
            [walk(v) for v in x.values()]
        if isinstance(x, list):
            [walk(v) for v in x]
    walk(golden_inputs())
    walk(result.golden())


def test_rounding_is_half_up_away_from_zero():
    assert rnd(F(1, 2), 0) == "1" and rnd(F(-1, 2), 0) == "-1" and rnd(F(5, 1000), 2) == "0.01" and rnd(F(-5, 1000), 2) == "-0.01"
    assert rnd(F(-7000, 121), 2) == "-57.85" and rnd(F(-81800, 121), 2) == "-676.03" and rnd(F(-1, 1000), 2) == "0.00"
    assert rnd(F(20, 6), 4) == "3.3333" and rnd(F(55, 60) + 1, 4) == "1.9167"


def test_the_domain_is_deterministic_and_does_not_mutate_its_input():
    a, b = golden_inputs(), golden_inputs()
    r1, r2 = run_pipeline(a).golden(), run_pipeline(b).golden()
    assert r1 == r2 and a == b == golden_inputs()
