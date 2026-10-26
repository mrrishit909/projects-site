"""The rejected and empty variants equal their expected.json (ingest counts, rejected rows, metrics)."""
import pytest

from onboard_studio import run_pipeline
from onboard_studio.contract import METRIC_KEYS

from support_db import golden_expected, golden_inputs

VARIANTS = ["variant-rejected", "variant-empty"]
STATES = ["pause_eligible", "pause_not_eligible"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_ingest_counts_equal_expected(variant):
    assert run_pipeline(golden_inputs(variant), "pause_eligible").counts == golden_expected(variant)["ingest"]["counts"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_rejected_records_equal_expected(variant):
    res = run_pipeline(golden_inputs(variant), "pause_eligible")
    assert res.rejected == golden_expected(variant)["ingest"]["rejected_records"]


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("key", METRIC_KEYS)
@pytest.mark.parametrize("variant", VARIANTS)
def test_metric_equals_expected(variant, state, key):
    exp = golden_expected(variant)["states"][state]["metrics"]
    assert run_pipeline(golden_inputs(variant), state).metrics[key] == exp[key]


@pytest.mark.parametrize("state", STATES)
def test_rejected_variant_equals_golden_totals(state):
    assert run_pipeline(golden_inputs("variant-rejected"), state).metrics == \
        run_pipeline(golden_inputs(), state).metrics


def test_rejected_variant_rejects_every_row_of_the_case_with_self_approval():
    res = run_pipeline(golden_inputs("variant-rejected"), "pause_eligible")
    assert {r["reason_code"] for r in res.rejected} == {"SELF_APPROVAL"}
    assert len(res.rejected) == 10
    assert {r["entity"] for r in res.rejected if r["id"] == "case-002"} == {"cases"}


@pytest.mark.parametrize("state", STATES)
def test_empty_variant_is_an_empty_population_with_null_rates(state):
    m = run_pipeline(golden_inputs("variant-empty"), state).metrics
    assert m["empty_population"] is True
    assert m["sla_attainment"] is None and m["calendar_cycle_time_hours"] is None
    assert m["step_waiting_time_hours"] == {"sd-001": None, "sd-002": None}
    assert m["completed_eligible_cases"] == 0 and m["handoff_count"] == 0
