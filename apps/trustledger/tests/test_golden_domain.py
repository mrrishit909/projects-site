"""The golden fixtures through the pure domain: every figure equals expected.json key by key (P07-GOLD-01..)."""
import json
from copy import deepcopy

import pytest

from trustledger import run_pipeline
from trustledger.contract import ENTITIES, METRIC_KEYS

from support_db import VARIANTS, flat, golden_expected, golden_inputs


@pytest.fixture(scope="module")
def result():
    return run_pipeline(golden_inputs())


@pytest.mark.parametrize("variant", VARIANTS)
def test_whole_shape_equals_expected_json_key_by_key(variant):
    exp, got = flat(golden_expected(variant)), flat(run_pipeline(golden_inputs(variant)).golden())
    assert set(exp) == set(got)
    assert [k for k in exp if exp[k] != got[k]] == []
    assert len(exp) == {"": 391, "variant-rejected": 231, "variant-empty": 96}[variant]       # the number of leaves of each expected.json


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("key", METRIC_KEYS)
def test_metric_equals_expected(variant, key):
    assert run_pipeline(golden_inputs(variant)).metrics[key] == golden_expected(variant)["metrics"][key]


def test_metric_names_are_exactly_the_expected_keys(result):
    assert set(result.metrics) == set(golden_expected()["metrics"])
    assert tuple(result.metrics) == METRIC_KEYS


@pytest.mark.parametrize("entity", [*ENTITIES, "dataset_rows"])
def test_ingest_counts_per_entity(result, entity):
    assert result.counts[entity] == golden_expected()["ingest"]["counts"][entity]


def test_spec_sentence_figures(result):
    """P07-GOLD-01: 100 eligible rows, 5 missing e-mails -> 0.950000; populated-only validity 90/95, never 90/100; a critical key failure stays visible."""
    c, v = result.metrics["completeness"]["r-cust-complete-email"], result.metrics["validity"]["r-cust-valid-email"]
    assert (c["eligible_count"], c["missing_count"], c["populated_count"], c["value"]) == (100, 5, 95, "0.950000")
    assert c["whitespace_only_count"] == 2                                  # the whitespace policy: 2 of the 5 look populated
    assert v["populated_only"] == {"label": "validity_populated_only", "value": "0.947368"}       # 90 / 95
    assert v["all_eligible"] == {"label": "validity_all_eligible", "value": "0.900000"}           # 90 / 100
    ws = result.metrics["weighted_score"]["datasets"]["ds-customers"]
    assert ws["value"] == "0.963932" and ws["critical_override"] is True and ws["critical_failures"] == 2 and ws["critical_open_issues"] == 1
    assert result.metrics["weighted_score"]["by_weight_version"]["w1"]["ds-customers"] == "0.958116"


def test_uniqueness_both_shares_relationship_nulls_timeliness_and_the_rest(result):
    u = result.metrics["uniqueness"]["r-cust-key-unique"]
    assert (u["group_share"]["value"], u["row_share"]["value"], u["distinct_keys"]) == ("0.010204", "0.020000", 98)
    r = result.metrics["relationship_integrity"]["r-ord-cust-fk"]
    assert (r["total_fk_count"], r["null_fk_count"], r["eligible_count"], r["matched_count"], r["value"]) == (40, 2, 38, 36, "0.947368")
    t = result.metrics["timeliness"]
    assert (t["on_time_count"], t["monitored_datasets"], t["value"]) == (3, 4, "0.750000")
    assert t["datasets"]["ds-shipments"]["on_time"] is False and t["datasets"]["ds-payments"]["on_time"] is True      # 05:00 is not < 05:00
    m = result.metrics
    assert m["ownership_coverage"]["value"] == "0.800000" and m["ownership_coverage"]["uncovered"] == ["ds-shipments"]
    assert m["definition_coverage"]["value"] == "0.750000" and m["definition_coverage"]["incomplete"] == {"m-ltv": ["grain", "refresh"]}
    assert m["lineage_coverage"]["value"] == "0.833333" and m["lineage_coverage"]["undeclared_observed"] == [
        {"source_dataset_id": "ds-payments", "target_dataset_id": "ds-shipments"}]
    assert m["match_precision"]["precision"] == "0.666667" and m["match_precision"]["reviewed_correct_share"] == "0.500000"
    assert m["resolution_time"]["mean_hours"] == "38.4444" and m["critical_failures"] == {"failures": 2, "open_issues": 1, "datasets_overridden": 1}


def test_the_synthetic_truth_is_a_separate_block_and_only_the_verification_layer_reads_it():
    inputs = golden_inputs()
    assert "synthetic_truth" in inputs and not any("truth" in k for e in ENTITIES for row in inputs[e] for k in row)
    base = run_pipeline(inputs)
    flipped = deepcopy(inputs)
    flipped["synthetic_truth"]["true_entity"] = {k: "E" for k in flipped["synthetic_truth"]["true_entity"]}          # everyone is one person
    other = run_pipeline(flipped)
    assert other.metrics["match_precision"]["precision"] == "1.000000" != base.metrics["match_precision"]["precision"]
    same = lambda r: {k: v for k, v in r.golden().items() if k != "metrics"} | {"metrics": {k: v for k, v in r.metrics.items() if k != "match_precision"}}  # noqa: E731
    assert same(base) == same(other)                       # candidates, decisions, identity map, mapping history: unchanged by the truth


def test_pipeline_without_a_truth_block_reports_null_precision_not_zero():
    inputs = golden_inputs()
    del inputs["synthetic_truth"]
    p = run_pipeline(inputs).metrics["match_precision"]
    assert p == {"approved_decisions": 3, "approved_correct": None, "precision": None, "reviewed": 4, "reviewed_correct": None, "reviewed_correct_share": None}
    assert run_pipeline(inputs).warnings and run_pipeline(inputs).warnings[0]["code"] == "MATCH_TRUTH_UNAVAILABLE"
    given = run_pipeline(inputs, truth=golden_inputs()["synthetic_truth"]["true_entity"]).metrics["match_precision"]
    assert given["precision"] == "0.666667"                # the optional truth argument feeds the verification layer only


def test_no_float_anywhere_in_the_published_result(result):
    def walk(x):
        if isinstance(x, float):
            raise AssertionError(x)
        if isinstance(x, dict):
            [walk(v) for v in x.values()]
        if isinstance(x, list):
            [walk(v) for v in x]
    walk(result.golden())
    json.dumps(result.golden(), allow_nan=False)
