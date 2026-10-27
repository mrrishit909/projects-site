"""The golden fixtures through the pure domain: every figure equals expected.json key by key (P08-GOLD-01..06)."""
import json

import pytest
from pipeline_observatory import run_pipeline
from pipeline_observatory.contract import ENTITIES, METRIC_KEYS

from support_db import VARIANTS, diff, flat, golden_expected, golden_inputs


@pytest.fixture(scope="module")
def result():
    return run_pipeline(golden_inputs())


@pytest.mark.parametrize("variant", VARIANTS)
def test_whole_shape_equals_expected_json_leaf_for_leaf(variant):
    exp, got = flat(golden_expected(variant)), flat(run_pipeline(golden_inputs(variant)).golden)
    assert set(exp) == set(got)
    assert [k for k in exp if exp[k] != got[k]] == []
    assert len(exp) == {"": 295, "variant-rejected": 265, "variant-empty": 95}[variant]       # the number of leaves of each expected.json


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("key", METRIC_KEYS)
def test_metric_family_equals_expected(variant, key):
    assert run_pipeline(golden_inputs(variant)).metrics[key] == golden_expected(variant)["metrics"][key]


def test_metric_names_are_exactly_the_expected_keys_in_the_expected_nesting(result):
    assert set(result.metrics) == set(golden_expected()["metrics"])
    assert tuple(result.metrics) == METRIC_KEYS
    assert set(result.metrics["ingestion"]) == {"sources", "overall"} and set(result.metrics["publications"]) == {"current_publication_id", "pointer_history", "publications"}
    assert set(result.metrics["backfills"]) == {"requests", "refused", "overall"}


@pytest.mark.parametrize("entity", ENTITIES)
def test_ingest_counts_per_entity(result, entity):
    assert result.counts[entity] == golden_expected()["ingest"]["counts"][entity]


def test_spec_sentence_p08_gold_01(result):
    """10 received, 8 accepted unique, 1 duplicate, 1 quarantined; the replay leaves 8; the crash never makes a ninth record."""
    s = result.metrics["ingestion"]["sources"]["src-orders"]
    b1, b2, b3 = (s["batches"][b] for b in ("b-001", "b-002", "b-003"))
    assert (b1["received"], b1["accepted_unique"], b1["duplicate"], b1["quarantined"]) == (10, 8, 1, 1)
    assert b1["received"] == b1["accepted_unique"] + b1["duplicate"] + b1["quarantined"]            # nothing is dropped
    assert (b1["rejection_rate"], b1["duplicate_rate"]) == ("0.100000", "0.100000")
    assert (b2["accepted_unique"], b2["duplicate"], b2["quarantined"]) == (0, 9, 1)                  # the replay adds no accepted record
    assert s["accepted_unique"] == 8 and s["duplicate"] == 10 and s["quarantined"] == 2 and s["quarantined_distinct_keys"] == 1
    assert (b3["status"], b3["counted"], b3["written_rows"], b3["accepted_unique"]) == ("aborted", False, 10, 0)     # the crashed batch counts for nothing
    assert s["checkpoint"] == {"committed_version": 2, "committed_cursor": "cur-010", "committed_batch_id": "b-002", "uncommitted_batches": ["b-003"],
                               "uncommitted_batches_with_checkpoint": 0}
    assert s["accepted_unique"] != 9


def test_freshness_differs_from_ingestion_age_and_completeness_uses_the_declaration(result):
    f = result.metrics["freshness"]["src-orders"]
    assert (f["freshness_seconds"], f["ingestion_age_seconds"]) == (52200, 42900)
    c = result.metrics["completeness"]["src-orders"]["2026-10-04"]
    assert (c["expected_records"], c["accepted_records"], c["value"]) == (9, 8, "0.888889")


def test_task_success_is_not_attempt_success_and_durations_are_kept_apart(result):
    r = result.metrics["runs"]["runs"]["run-001"]
    assert (r["task_success_rate"], r["attempt_success_rate"], r["duration_seconds"]) == ("1.000000", "0.800000", 1200)
    o = result.metrics["runs"]["overall"]
    assert (o["task_success_rate"], o["attempt_success_rate"]) == ("0.909091", "0.833333")
    d = result.metrics["runs"]["durations"]
    assert d["successful"]["mean_minutes"] == "17.5000" and d["failed"]["mean_minutes"] == "10.0000" and d["failed"]["durations_seconds"] == [600]


def test_gate_pointer_lag_late_event_residual_recovery_backfill_rate(result):
    m = result.metrics
    assert [(h["run_id"], h["gate_decision"], h["pointer_after"]) for h in m["publications"]["pointer_history"]] == [
        ("run-001", "allowed", "pub-001"), ("run-002", "blocked", "pub-001"), ("run-003", "allowed", "pub-003")]
    assert m["publications"]["publications"]["pub-001"]["lag_seconds"] == 3600
    assert m["late_events"]["count"] == 1 and m["late_events"]["events"][0]["included_in_publication_id"] == "pub-003" and m["late_events"]["lost"] == 0
    rc = m["reconciliation"]["pub-001"]
    assert (rc["source_total"], rc["published_total"], rc["exclusions"]["quarantined"], rc["exclusions"]["duplicates"], rc["residual"]) == ("289.94", "289.97", "-30.00", "29.97", "0.00")
    inc = m["incidents"]["incidents"]["inc-001"]
    assert (inc["recovery_seconds"], inc["recovery_minutes"], inc["closure_consistent"]) == (28500, "475.0000", True)
    assert m["backfills"]["requests"]["bf-001"]["coverage"] == "0.666667" and m["processing_rate"]["records_per_second"] == "0.666667"


def test_no_float_anywhere_in_the_inputs_or_the_published_result(result):
    def walk(x):
        assert not isinstance(x, float), x
        if isinstance(x, dict):
            [walk(v) for v in x.values()]
        if isinstance(x, list):
            [walk(v) for v in x]
    walk(result.golden)
    walk(golden_inputs())
    json.dumps(result.golden, allow_nan=False)


def test_the_result_does_not_depend_on_row_order_in_the_inputs():
    inputs = golden_inputs()
    for e in ("raw_records", "task_runs", "quality_results", "ingestion_batches", "checkpoints"):
        inputs[e].reverse()
    assert diff(run_pipeline(inputs).golden, golden_expected()) == []
