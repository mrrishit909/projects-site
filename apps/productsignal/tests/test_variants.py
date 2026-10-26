"""Variants: rejected rows leave every figure at the right value; the empty dataset is honest (null, not zero)."""
import pytest

from productsignal import run_pipeline
from productsignal.contract import ENTITIES, METRIC_KEYS

from support_db import golden_expected, golden_inputs


@pytest.mark.parametrize("variant", ["variant-rejected", "variant-empty"])
def test_whole_variant_equals_expected_json(variant):
    assert run_pipeline(golden_inputs(variant)).golden() == golden_expected(variant)


@pytest.mark.parametrize("variant", ["variant-rejected", "variant-empty"])
@pytest.mark.parametrize("key", METRIC_KEYS)
def test_variant_metric_equals_expected(variant, key):
    assert run_pipeline(golden_inputs(variant)).metrics[key] == golden_expected(variant)["metrics"][key]


@pytest.mark.parametrize("entity", ENTITIES)
def test_rejected_variant_counts(entity):
    got = run_pipeline(golden_inputs("variant-rejected")).counts[entity]
    assert got == golden_expected("variant-rejected")["ingest"]["counts"][entity]


def test_rejected_variant_reasons_and_dependents():
    res = run_pipeline(golden_inputs("variant-rejected"))
    reasons = {(r["entity"], r["id"]): r["reason_code"] for r in res.rejected}
    assert reasons == {("assignments", "as-c-003-b"): "ASSIGNMENT_CONFLICT", ("exposures", "ex-c-003-b"): "DEPENDENT_REJECTED",
                       ("exposures", "ex-t-004"): "EXPOSURE_BEFORE_ASSIGNMENT", ("metric_observations", "ob-c-003-b"): "DEPENDENT_REJECTED"}
    assert all(r["status"] == "rejected" and "raw_row" in r for r in res.rejected)


def test_rejected_variant_the_first_assignment_fixes_the_variant_and_the_unit_is_counted_once():
    """Accepting the second assignment would have put one account in both arms (21 assignments for 20 accounts)."""
    e = run_pipeline(golden_inputs("variant-rejected")).metrics["experiment"]
    assert e["assigned_units"] == 20 and e["srm"]["observed"] == {"control": 12, "treatment": 8}
    assert e["exposure"]["by_variant"]["treatment"] == {"exposed": 7, "units": 8, "rate": "0.875000"}     # ex-t-004 is not an exposure
    assert e["primary"]["relative_lift"] is None and e["primary"]["absolute_lift_pp"] == "37.50"       # zero control conversions: null
    assert e["primary"]["conclusive"] is True


def test_empty_variant_is_honest_not_zero_filled():
    res = run_pipeline(golden_inputs("variant-empty"))
    m = res.metrics
    assert res.empty_population is True
    assert m["signup_conversion"]["rate"] is None and m["activation"]["rate"] is None and m["feature_adoption"]["rate"] is None
    assert m["retention"]["day7"]["rate"] is None and m["retention"]["week4"]["rate"] is None
    assert all(s["units"] == 0 and s["conversion_from_first"] is None for s in m["funnel"]["steps"]) and m["funnel"]["overall_conversion"] is None
    e = m["experiment"]
    assert e["srm"] == {"observed": {"control": 0, "treatment": 0}, "expected": None, "statistic": None, "p_value": None, "verdict": "INSUFFICIENT"}
    assert e["primary"]["relative_lift"] is None and e["primary"]["interval"] is None and e["primary"]["conclusive"] is False
    assert e["revenue_per_assigned_account"]["by_variant"]["control"] == {"units": 0, "total": "0.00", "mean": None, "interval": None}
    assert e["run"]["analysis_id"] is None and e["run"]["plan_frozen"] is False
