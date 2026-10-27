"""data/sql/reference_metrics.sql recomputes the headline metrics from the facts, independently of the Python domain and of any stored
classification, and equals expected.json on the fixtures and the domain on any loaded population (P08-GOLD-06)."""
from pathlib import Path

import psycopg
import pytest
from pipeline_observatory import run_pipeline
from pipeline_observatory.contract import METRIC_KEYS

from support_db import CUTOFF, VARIANTS, conn, db_url, diff, flat, golden_expected, golden_inputs, load, load_world  # noqa: F401

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
COLUMNS = (*METRIC_KEYS, "empty_population")


def reference(conn, cutoff=CUTOFF):
    return conn.execute(SQL, {"cutoff": cutoff}).fetchone()


@pytest.mark.parametrize("variant", VARIANTS)
def test_sql_equals_expected_for_every_fixture_leaf_for_leaf(conn, variant):
    inputs = golden_inputs(variant)
    load(conn, inputs)
    row = reference(conn, inputs["cutoff"])
    want = golden_expected(variant)
    assert set(row) == set(COLUMNS)
    for k in METRIC_KEYS:
        assert row[k] == want["metrics"][k], k
    assert row["empty_population"] is want["empty_population"]
    assert diff({k: row[k] for k in METRIC_KEYS}, want["metrics"]) == []


def test_sql_headline_values_typed_from_the_hand_worked_calculation(conn):
    inputs = golden_inputs()
    load(conn, inputs)
    r = reference(conn)
    b1 = r["ingestion"]["sources"]["src-orders"]["batches"]["b-001"]
    assert (b1["received"], b1["accepted_unique"], b1["duplicate"], b1["quarantined"], b1["rejection_rate"], b1["duplicate_rate"]) == (10, 8, 1, 1, "0.100000", "0.100000")
    assert r["ingestion"]["sources"]["src-orders"]["accepted_unique"] == 8 and r["ingestion"]["sources"]["src-orders"]["checkpoint"]["committed_version"] == 2
    assert (r["freshness"]["src-orders"]["freshness_seconds"], r["freshness"]["src-orders"]["ingestion_age_seconds"]) == (52200, 42900)
    assert r["completeness"]["src-orders"]["2026-10-04"]["value"] == "0.888889"
    assert (r["runs"]["runs"]["run-001"]["task_success_rate"], r["runs"]["runs"]["run-001"]["attempt_success_rate"]) == ("1.000000", "0.800000")
    assert [(h["gate_decision"], h["pointer_after"]) for h in r["publications"]["pointer_history"]] == [("allowed", "pub-001"), ("blocked", "pub-001"), ("allowed", "pub-003")]
    assert r["publications"]["publications"]["pub-001"]["lag_seconds"] == 3600 and r["late_events"]["count"] == 1
    assert r["reconciliation"]["pub-001"]["residual"] == "0.00" and r["reconciliation"]["pub-001"]["source_total"] == "289.94"
    assert r["incidents"]["incidents"]["inc-001"]["recovery_seconds"] == 28500 and r["backfills"]["requests"]["bf-001"]["coverage"] == "0.666667"
    assert r["processing_rate"]["records_per_second"] == "0.666667"


def test_sql_does_not_read_the_stored_classification(conn):
    """Scramble the stored dispositions and delete accepted_records: the SQL reference does not move (it classifies from the raw rows)."""
    inputs = golden_inputs()
    load(conn, inputs)
    before = reference(conn)
    conn.execute("ALTER TABLE raw_records DISABLE TRIGGER raw_records_guard")
    conn.execute("UPDATE raw_records SET disposition = 'duplicate', reason_code = 'LIES'")
    conn.execute("ALTER TABLE accepted_records DISABLE TRIGGER accepted_guard")
    conn.execute("DELETE FROM accepted_records")
    assert reference(conn) == before


def test_sql_equals_the_domain_on_a_changed_population(conn):
    """A population the fixtures do not cover: a changed payload under a known key, a missing field, a late record, an unknown-order replay."""
    inputs = golden_inputs()
    extra = {"payload_json": {"record_id": "ORD-1001", "quantity": 7, "unit_price": "1.00", "amount": "7.00", "event_ts": "2026-10-04T13:00:00Z"}}
    from pipeline_observatory.hashing import payload_hash
    inputs["raw_records"] += [{"raw_record_id": "rr-b-002-11", "batch_id": "b-002", "source_key": "ORD-1001", "payload_hash": payload_hash(extra["payload_json"]), **extra},
                              {"raw_record_id": "rr-b-002-12", "batch_id": "b-002", "source_key": "ORD-7000", "payload_hash": payload_hash({"record_id": "ORD-7000", "quantity": 1}),
                               "payload_json": {"record_id": "ORD-7000", "quantity": 1}},
                              {"raw_record_id": "rr-b-002-13", "batch_id": "b-002", "source_key": "ORD-7001", "payload_hash": payload_hash({"record_id": "ORD-7001", "quantity": 1, "unit_price": "2.00", "amount": "2.00", "event_ts": "2026-10-04T11:50:00Z"}),
                               "payload_json": {"record_id": "ORD-7001", "quantity": 1, "unit_price": "2.00", "amount": "2.00", "event_ts": "2026-10-04T11:50:00Z"}}]
    inputs["quarantine_records"].append({"quarantine_id": "q-b-002-02", "batch_id": "b-002", "source_key": "ORD-7000", "reason_code": "MISSING_FIELD",
                                         "payload_hash": payload_hash({"record_id": "ORD-7000", "quantity": 1})})
    load(conn, inputs)
    got = run_pipeline(inputs).metrics
    row = reference(conn)
    assert diff({k: row[k] for k in METRIC_KEYS}, got) == []
    assert row["ingestion"]["sources"]["src-orders"]["batches"]["b-002"]["accepted_unique"] == 1                    # ORD-7001 is new; ORD-1001 changed is a duplicate
    assert row["ingestion"]["sources"]["src-orders"]["quarantine_by_reason"] == {"MISSING_FIELD": 1, "NEGATIVE_QUANTITY": 2}


def test_sql_returns_null_not_zero_on_an_empty_world(conn):
    load_world(conn)
    r = reference(conn)
    assert r["empty_population"] is True and r["ingestion"]["overall"]["rejection_rate"] is None and r["completeness"]["src-orders"]["2026-10-04"]["value"] == "0.000000"      # 0 of 9 expected is 0; 0 of 0 would be null
    assert r["freshness"]["src-orders"]["freshness_seconds"] is None and r["publications"]["current_publication_id"] is None and r["processing_rate"]["records_per_second"] is None
