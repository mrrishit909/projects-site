"""The golden fixture and both variants through the pure domain: every figure equals expected.json LEAF FOR LEAF (P10-GOLD-01..11),
including the ``consistency`` block; the spec's sentence figures; no float anywhere."""
import json

import pytest

from retentionlab import evaluate
from retentionlab.contract import ENTITIES

from support_db import JAN, FEB, VARIANTS, flat, golden_expected, golden_inputs, has_float

LEAVES = {"": 912, "variant-rejected": 480, "variant-empty": 334}        # the number of leaves of each expected.json


@pytest.fixture(scope="module")
def golden():
    return evaluate(golden_inputs())


@pytest.mark.parametrize("variant", VARIANTS)
def test_whole_shape_equals_expected_json_leaf_for_leaf(variant):
    exp, got = flat(golden_expected(variant)), flat(evaluate(golden_inputs(variant)))
    assert set(exp) == set(got)
    assert [k for k in exp if exp[k] != got[k] or type(exp[k]) is not type(got[k])] == []
    assert len(exp) == LEAVES[variant]


@pytest.mark.parametrize("variant", VARIANTS)
def test_consistency_block_is_present_and_empty_for_every_fixture(variant):
    got = evaluate(golden_inputs(variant))["consistency"]
    assert set(got) == {"cutoff_windows_mismatched", "feature_rows_mismatched", "labels_mismatched", "split_assignments_mismatched",
                        "scoring_publications_mismatched", "config_hash_mismatched", "outreach_queue_mismatched", "predictions_citation_mismatched"}
    assert all(v == [] for v in got.values())
    assert got == golden_expected(variant)["consistency"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_no_float_in_any_output_or_serialisation(variant):
    out = evaluate(golden_inputs(variant))
    assert not has_float(out)
    text = json.dumps(out)
    assert json.loads(text, parse_float=lambda s: pytest.fail(f"float {s} in the JSON")) == out


def test_the_spec_sentence_figures_P10_GOLD_01(golden):
    """Risks .8 .6 .4 .1 with outcomes 1 0 1 0: precision@2 .5, recall@2 .5, Brier .1925, AP 5/6, lift 1; no treatment effect estimate."""
    s = golden["cutoff_sets"][JAN]
    assert [(r["account_id"], r["probability"], r["outcome"]) for r in s["ranking"]] == [(1, "0.800000", 1), (2, "0.600000", 0), (3, "0.400000", 1), (4, "0.100000", 0)]
    assert s["precision_at_k"] == {"value": "0.500000", "hits": 1, "k": 2}
    assert s["recall_at_k"] == {"value": "0.500000", "hits": 1, "positives": 2}
    assert s["brier_score"]["value"] == "0.192500" and s["average_precision"]["value"] == "0.833333"
    assert s["risk_lift_at_k"]["value"] == "1.000000" and s["churn_rate"]["value"] == "0.500000"
    assert s["economics"]["treatment_effect_estimate"] is None and s["economics"]["label"] == "hypothetical"
    assert s["economics"]["expected_value"] == "8.45"                      # 8.445 rounded ONCE, half up (half-even would say 8.44)


def test_censored_cohort_has_null_ratios_not_zero(golden):
    f = golden["cutoff_sets"][FEB]
    assert (f["population"]["eligible"], f["population"]["mature"], f["population"]["censored"]) == (4, 0, 4)
    assert f["churn_rate"]["value"] is None and f["average_precision"]["value"] is None and f["brier_score"]["value"] is None
    assert f["empty_evaluation"] is True and f["empty_population"] is False
    assert all(r["churned"] is None for r in golden["point_in_time"]["rows"] if r["prediction_at"] == FEB)


def test_psi_and_freshness_figures(golden):
    assert golden["cutoff_sets"][JAN]["population_drift"]["psi"] == "0.074266"
    assert golden["cutoff_sets"][FEB]["population_drift"]["psi"] == "2.381316"
    assert golden["cutoff_sets"][FEB]["population_drift"]["exceeds_threshold"] is True and golden["cutoff_sets"][FEB]["population_drift"]["diagnostic_only"] is True
    assert (golden["freshness"]["scoring_hours"], golden["freshness"]["data_hours"]) == (2878, 264)
    assert [p["status"] for p in golden["scoring_publications"]] == ["completed", "incomplete"]


def test_ingest_counts_per_entity_and_the_import_order(golden):
    assert list(golden["ingest"]["counts"]) == list(ENTITIES)
    assert golden["ingest"]["counts"] == golden_expected()["ingest"]["counts"] and golden["ingest"]["rejected_records"] == []


def test_a_stored_derived_row_that_differs_from_the_rebuild_is_reported():
    d = golden_inputs()
    d["feature_rows"][0]["features_json"]["usage_events_30d"] += 1
    d["labels"][8]["churned"] = not d["labels"][8]["churned"]
    d["training_runs"][0]["config_hash"] = "0" * 64
    d["predictions"][0]["feature_version"] = "fv-9"
    d["scoring_publications"][1]["status"] = "completed"
    d["split_assignments"][0]["status"] = "retained"
    d["split_assignments"][0]["drop_reason"] = None
    d["outreach_events"].pop()
    d["prediction_cutoffs"][0]["horizon_end"] = "2025-05-31T00:00:00Z"
    c = evaluate(d)["consistency"]
    assert c["feature_rows_mismatched"] == [d["feature_rows"][0]["feature_row_id"]] and set(c["labels_mismatched"]) == {d["labels"][8]["label_id"], "lb-co-01-20250301"}      # the second: its cutoff's window moved
    assert c["config_hash_mismatched"] == ["tr-001"] and len(c["predictions_citation_mismatched"]) == 7      # a wrong run hash: every prediction cites a hash the run no longer has
    assert c["scoring_publications_mismatched"] == ["sp-002"] and c["split_assignments_mismatched"] == ["sa-tr-001-co-01-20250301"]
    assert c["outreach_queue_mismatched"] == ["sc-001"] and c["cutoff_windows_mismatched"] == ["co-01-20250301"]
