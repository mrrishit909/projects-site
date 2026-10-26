"""Variants: rejected tickets leave every metric and the simulation at the golden values; the empty dataset is honest."""
import pytest

from serviceflow import run_pipeline
from serviceflow.contract import ENTITIES, METRIC_KEYS

from support_db import golden_expected, golden_inputs


@pytest.mark.parametrize("variant", ["variant-rejected", "variant-empty"])
def test_whole_variant_equals_expected_json(variant):
    assert run_pipeline(golden_inputs(variant)).golden() == golden_expected(variant)


@pytest.mark.parametrize("variant", ["variant-rejected", "variant-empty"])
@pytest.mark.parametrize("key", METRIC_KEYS)
def test_variant_metric_equals_expected(variant, key):
    got = run_pipeline(golden_inputs(variant)).metrics
    assert got[key] == golden_expected(variant)["metrics"][key]


@pytest.mark.parametrize("entity", ENTITIES)
def test_rejected_variant_counts(entity):
    got = run_pipeline(golden_inputs("variant-rejected")).counts[entity]
    assert got == golden_expected("variant-rejected")["ingest"]["counts"][entity]


def test_rejected_variant_reasons_and_dependents():
    res = run_pipeline(golden_inputs("variant-rejected"))
    reasons = {(r["entity"], r["id"]): r["reason_code"] for r in res.rejected}
    assert reasons[("tickets", "t-004")] == "AGENT_NOT_QUALIFIED"
    assert reasons[("tickets", "t-005")] == "CONCURRENCY_EXCEEDED"
    deps = [k for k, v in reasons.items() if k[0] != "tickets"]
    assert len(deps) == 7 and all(reasons[k] == "TICKET_REJECTED" for k in deps)   # D-05: 6 events and 1 survey
    assert all(r["status"] == "rejected" and "raw_row" in r for r in res.rejected)


def test_rejected_variant_totals_equal_golden():
    gold = golden_expected()
    res = run_pipeline(golden_inputs("variant-rejected"))
    assert res.metrics == gold["metrics"] and res.simulations[0].golden() == gold["simulation"]


def test_empty_variant_is_honest_not_zero_filled():
    res = run_pipeline(golden_inputs("variant-empty"))
    m = res.metrics
    assert m["empty_population"] is True and res.simulations == []
    for k in ("mean_first_response_minutes", "p90_first_response_minutes", "mean_wait_minutes", "mean_resolution_minutes",
              "sla_first_response_compliance", "sla_resolution_compliance", "csat", "survey_invitation_rate",
              "survey_response_rate", "abandonment_rate"):
        assert m[k] is None, k
    assert m["agent_occupancy"] == "0.000000" and m["staffed_available_minutes"] == "60.0000"
    assert res.golden()["simulation"] is None
