"""The two variants through the domain, the loader and the database: rejection is atomic, dependent and never silent; absence is null (P08-GOLD-08/09)."""
from pipeline_observatory import run_pipeline

from support_db import conn, count, db_url, golden_expected, golden_inputs, load  # noqa: F401


def test_variant_rejected_lists_every_rejection_with_reason_and_the_raw_row():
    res = run_pipeline(golden_inputs("variant-rejected"))
    got = [(r["entity"], r["id"], r["reason_code"]) for r in res.rejected]
    assert got == [("ingestion_batches", "b-003", "DEPENDENT_REJECTED"), ("raw_records", "rr-b-003-01", "DEPENDENT_REJECTED"),
                   ("raw_records", "rr-b-003-02", "DEPENDENT_REJECTED"), ("checkpoints", "cp-003", "CHECKPOINT_REGRESSION"),
                   ("pipeline_runs", "run-bf-2", "DEPENDENT_REJECTED"), ("task_runs", "tr-001-2", "DUPLICATE_ID"), ("task_runs", "tr-bf2-1", "DEPENDENT_REJECTED"),
                   ("quality_results", "qr-001-2", "DEPENDENT_REJECTED"), ("quality_results", "qr-bf2-1", "DEPENDENT_REJECTED"),
                   ("backfill_requests", "bf-002", "BACKFILL_OVERLAP")]
    assert got == [(r["entity"], r["id"], r["reason_code"]) for r in golden_expected("variant-rejected")["ingest"]["rejected_records"]]      # the reference's list, in order
    assert {r["reason_code"] for r in res.rejected} == {"DEPENDENT_REJECTED", "CHECKPOINT_REGRESSION", "DUPLICATE_ID", "BACKFILL_OVERLAP"}
    raw = {(r["entity"], r["id"]): r["raw_row"] for r in res.rejected}
    assert raw[("checkpoints", "cp-003")]["version_number"] == 1 and raw[("raw_records", "rr-b-003-01")]["source_key"] == "ORD-5"      # rows kept exactly as sent
    c = res.counts
    assert c["checkpoints"] == {"accepted": 2, "rejected": 1} and c["raw_records"] == {"accepted": 4, "rejected": 2} and c["backfill_requests"] == {"accepted": 2, "rejected": 1}


def test_variant_rejected_never_counts_the_rows_of_the_rejected_commit():
    s = run_pipeline(golden_inputs("variant-rejected")).metrics["ingestion"]["sources"]["src-orders"]
    assert (s["received"], s["accepted_unique"], s["quarantined"]) == (4, 3, 1) and s["checkpoint"]["committed_version"] == 2     # ORD-5 and ORD-6 are never counted
    b = run_pipeline(golden_inputs("variant-rejected")).metrics["backfills"]
    assert b["refused"] == ["bf-002"] and sorted(b["requests"]) == ["bf-001", "bf-003"] and b["requests"]["bf-003"]["coverage"] == "0.000000" and b["overall"]["coverage"] == "0.500000"


def test_variant_empty_is_all_zero_counts_and_null_ratios_never_zero_ratios():
    res = run_pipeline(golden_inputs("variant-empty"))
    m = res.metrics
    assert res.empty_population is True
    assert m["ingestion"]["overall"] == {"received": 0, "accepted_unique": 0, "duplicate": 0, "quarantined": 0, "rejection_rate": None, "duplicate_rate": None}
    assert m["completeness"]["src-orders"]["2026-10-04"] == {"expected_records": 0, "accepted_records": 0, "value": None}
    assert m["freshness"]["src-orders"]["freshness_seconds"] is None and m["freshness"]["src-orders"]["ingestion_age_seconds"] is None
    assert m["runs"]["overall"]["task_success_rate"] is None and m["runs"]["overall"]["attempt_success_rate"] is None and m["runs"]["durations"]["successful"]["mean_minutes"] is None
    assert m["backfills"]["overall"]["coverage"] is None and m["processing_rate"]["records_per_second"] is None and m["incidents"]["mean_recovery_minutes"] is None
    assert m["publications"]["current_publication_id"] is None
    assert "0.000000" not in str(m)


def test_db_loader_keeps_rejected_rows_raw_and_does_not_load_them(conn):
    first = load(conn, golden_inputs("variant-rejected"))
    assert first["skipped"] == 10 and first["inserted"]["checkpoints"] == 2 and first["inserted"]["raw_records"] == 4
    assert count(conn, "rejected_records") == 10 and count(conn, "rejected_records", "reason_code = 'DEPENDENT_REJECTED'") == 7
    raw = conn.execute("SELECT raw_row FROM rejected_records WHERE id = 'cp-003'").fetchone()["raw_row"]
    assert raw["version_number"] == 1 and raw["committed_cursor"] == "cur-009"
    assert count(conn, "ingestion_batches", "batch_id = 'b-003'") == 0 and count(conn, "raw_records", "batch_id = 'b-003'") == 0
    again = load(conn, golden_inputs("variant-rejected"))
    assert sum(again["inserted"].values()) == 0 and again["dataset_version"] == first["dataset_version"]
    assert count(conn, "rejected_records") == 10 and count(conn, "dataset_versions") == 1


def test_db_variant_empty_has_nothing_but_the_source_and_its_expectation(conn):
    load(conn, golden_inputs("variant-empty"))
    assert sum(count(conn, t) for t in ("ingestion_batches", "raw_records", "accepted_records", "checkpoints", "pipeline_runs", "publications", "incidents", "backfill_requests")) == 0
    assert count(conn, "source_contracts") == 1 and count(conn, "source_expectations") == 1 and count(conn, "publication_pointer") == 0
