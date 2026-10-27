"""Migrations are idempotent and the database enforces the append-only, ordering, pairing and pointer rules (defence in depth)."""
import psycopg
import pytest

from data import migrate, seed

from support_db import conn, count, db_url, golden_inputs, load  # noqa: F401

FILES = ["0001_schema.sql", "0002_constraints.sql", "0003_review_fixes.sql"]
TABLES = ["source_contracts", "source_expectations", "ingestion_batches", "raw_records", "accepted_records", "quarantine_records", "checkpoints", "model_definitions",
          "backfill_requests", "pipeline_runs", "task_runs", "quality_results", "publications", "publication_pointer", "incidents", "model_outputs",
          "processing_measurements", "fetch_log", "fault_injections", "evidence_archives", "rejected_records", "audit_events", "command_results", "dataset_versions"]


@pytest.fixture
def golden(conn):
    load(conn, golden_inputs())
    return conn


def fails(conn, sql, match):
    with pytest.raises(psycopg.errors.IntegrityError, match=match):
        with conn.transaction():
            conn.execute(sql)


def test_migrations_are_idempotent(db_url):
    with psycopg.connect(db_url) as c:
        assert migrate.apply_migrations(c) == []                      # the fixture already applied them
        migrate.reset(c)
        assert migrate.apply_migrations(c) == FILES
        assert migrate.apply_migrations(c) == []
    for name in FILES:                                                # each file also re-runs cleanly
        with psycopg.connect(db_url) as c:
            c.execute((migrate.MIGRATIONS_DIR / name).read_text())


def test_reset_drops_everything_the_migrations_create(db_url):
    with psycopg.connect(db_url) as c:
        migrate.reset(c)
        left = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'").fetchone()[0]
        funcs = c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname LIKE 'po\\_%'").fetchone()[0]
    assert (left, funcs) == (0, 0)


def test_every_table_exists_and_instants_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at' OR column_name IN ('watermark')) AND data_type <> 'timestamp with time zone'").fetchall()
    assert bad == []


def test_the_section_03_entity_names_and_the_d_p8_12_fields_are_the_schema(conn):
    cols = {(r["table_name"], r["column_name"]) for r in conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'").fetchall()}
    for t, c in [("source_contracts", "expected_frequency"), ("ingestion_batches", "source_cursor"), ("checkpoints", "batch_id"), ("publications", "watermark"),
                 ("publications", "source_ids"), ("publications", "included_batch_ids"), ("quality_results", "severity"), ("pipeline_runs", "backfill_id"),
                 ("incidents", "closed_at"), ("incidents", "recovery_run_id"), ("backfill_requests", "partitions"), ("model_definitions", "definition")]:
        assert (t, c) in cols, (t, c)


def test_no_float_column_anywhere(conn):
    rows = conn.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' "
                        "AND data_type IN ('double precision', 'real')").fetchall()
    assert rows == []


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate.apply_migrations(c)


def test_seed_is_idempotent_and_names_its_dataset_version(conn):
    first = load(conn, golden_inputs(), dataset_version="ds-golden-1")
    assert first["dataset_version"] == "ds-golden-1" and first["inserted"]["raw_records"] == 32 and first["inserted"]["accepted_records"] == 9 and first["skipped"] == 0
    again = load(conn, golden_inputs(), dataset_version="ds-golden-1")
    assert sum(again["inserted"].values()) == 0 and count(conn, "dataset_versions") == 1 and count(conn, "raw_records") == 32
    assert count(conn, "accepted_records", "source_id = 'src-orders'") == 8                                        # eight accepted orders, never nine


def test_a_source_key_is_accepted_once_per_source_at_the_database(golden):
    """The idempotency boundary is a primary key: a second accepted record for an accepted key is refused whatever the application does."""
    golden.execute("INSERT INTO raw_records (raw_record_id, batch_id, source_key, payload_hash, payload_json) VALUES ('rr-x', 'b-003', 'ORD-1001', %s, '{}')", ("0" * 64,))
    with pytest.raises(psycopg.errors.UniqueViolation, match="accepted_records_pkey"):
        golden.execute("INSERT INTO accepted_records (source_id, source_key, raw_record_id, batch_id, accepted_at) VALUES ('src-orders', 'ORD-1001', 'rr-x', 'b-003', now())")
    assert count(golden, "accepted_records", "source_id = 'src-orders'") == 8


def test_checkpoints_commit_previous_plus_one_and_never_change(golden):
    golden.execute("INSERT INTO ingestion_batches (batch_id, source_id, source_cursor, started_at, status) VALUES ('b-9', 'src-orders', 'c', now(), 'staged')")
    for version, code in ((2, "CHECKPOINT_REGRESSION"), (1, "CHECKPOINT_REGRESSION"), (4, "CHECKPOINT_GAP")):
        fails(golden, f"INSERT INTO checkpoints VALUES ('cp-9', 'src-orders', 'b-9', 'c', now(), {version})", code)
    for sql in ("UPDATE checkpoints SET version_number = 9 WHERE checkpoint_id = 'cp-001'", "DELETE FROM checkpoints WHERE checkpoint_id = 'cp-001'", "TRUNCATE checkpoints"):
        fails(golden, sql, "APPEND_ONLY")


def test_a_batch_commits_atomically_with_its_checkpoint_in_either_direction(golden):
    golden.execute("INSERT INTO ingestion_batches (batch_id, source_id, source_cursor, started_at, status) VALUES ('b-9', 'src-orders', 'c', now(), 'staged')")
    with pytest.raises(psycopg.errors.IntegrityError, match="COMMIT_WITHOUT_CHECKPOINT"):          # the batch says committed, the checkpoint is missing
        with golden.transaction():
            golden.execute("UPDATE ingestion_batches SET status = 'committed' WHERE batch_id = 'b-9'")
    with pytest.raises(psycopg.errors.IntegrityError, match="CHECKPOINT_WITHOUT_COMMIT"):          # the checkpoint is written, the batch is not committed
        with golden.transaction():
            golden.execute("INSERT INTO checkpoints VALUES ('cp-9', 'src-orders', 'b-9', 'c', now(), 3)")
    assert count(golden, "checkpoints", "source_id = 'src-orders'") == 2 and count(golden, "ingestion_batches", "batch_id = 'b-9' AND status = 'staged'") == 1
    with golden.transaction():                                                                      # both together: fine
        golden.execute("INSERT INTO checkpoints VALUES ('cp-9', 'src-orders', 'b-9', 'c', now(), 3)")
        golden.execute("UPDATE ingestion_batches SET status = 'committed' WHERE batch_id = 'b-9'")
    assert count(golden, "checkpoints", "source_id = 'src-orders'") == 3


def test_committed_batches_and_their_rows_are_final_raw_payloads_are_evidence(golden):
    fails(golden, "UPDATE ingestion_batches SET status = 'aborted' WHERE batch_id = 'b-001'", "APPEND_ONLY")
    fails(golden, "UPDATE raw_records SET payload_json = '{}' WHERE raw_record_id = 'rr-b-001-01'", "APPEND_ONLY")
    fails(golden, "UPDATE raw_records SET disposition = 'duplicate' WHERE raw_record_id = 'rr-b-001-01'", "APPEND_ONLY")
    fails(golden, "DELETE FROM raw_records WHERE raw_record_id = 'rr-b-003-01'", "APPEND_ONLY")
    fails(golden, "DELETE FROM accepted_records WHERE source_key = 'ORD-1001'", "APPEND_ONLY")
    fails(golden, "UPDATE accepted_records SET batch_id = 'b-002' WHERE source_key = 'ORD-1001'", "APPEND_ONLY")


def test_evidence_tables_are_append_only(golden):
    for t, where in (("quarantine_records", "quarantine_id = 'q-b-001-01'"), ("publications", "publication_id = 'pub-001'"), ("quality_results", "quality_result_id = 'qr-001-1'"),
                     ("model_definitions", "model_id = 'm-stg-orders'")):
        fails(golden, f"DELETE FROM {t} WHERE {where}", "APPEND_ONLY")
    fails(golden, "UPDATE publications SET watermark = now() WHERE publication_id = 'pub-001'", "APPEND_ONLY")
    golden.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id) VALUES ('e1', 'x', 'y', 'z', 'a')")
    fails(golden, "UPDATE audit_events SET action = 'q' WHERE event_id = 'e1'", "APPEND_ONLY")
    fails(golden, "DELETE FROM audit_events WHERE event_id = 'e1'", "APPEND_ONLY")


def test_the_pointer_refuses_a_failed_run_and_a_blocked_gate(golden):
    golden.execute("INSERT INTO pipeline_runs (run_id, started_at, finished_at, status, code_sha) VALUES ('run-9', now(), now(), 'failed', 'x')")
    fails(golden, "INSERT INTO publications VALUES ('pub-9', 'run-9', 'sales_daily', now(), now(), '{src-orders}', '{b-001}', repeat('a', 64))", "PUBLICATION_REQUIRES_SUCCESS")
    fails(golden, "INSERT INTO publications VALUES ('pub-002', 'run-002', 'sales_daily', now(), now(), '{src-orders}', '{b-001}', repeat('a', 64))", "PUBLICATION_REQUIRES_SUCCESS")
    golden.execute("INSERT INTO pipeline_runs (run_id, started_at, finished_at, status, code_sha) VALUES ('run-8', now(), now(), 'success', 'x')")
    fails(golden, "INSERT INTO publications VALUES ('pub-8', 'run-8', 'sales_daily', now(), now(), '{src-orders}', '{b-001}', repeat('a', 64))", "PUBLICATION_REQUIRES_GATE")   # no gate at all: fail closed
    assert golden.execute("SELECT publication_id FROM publication_pointer").fetchone()["publication_id"] == "pub-003"
    golden.execute("DELETE FROM publication_pointer")
    fails(golden, "INSERT INTO publication_pointer VALUES (1, 'pub-001', now()), (2, 'pub-003', now())", "publication_pointer_id_check")
    golden.execute("INSERT INTO publication_pointer VALUES (1, 'pub-001', now())")                  # a passed candidate: fine


def test_incident_closure_needs_a_recovery_and_a_closed_incident_is_final(golden):
    fails(golden, "UPDATE incidents SET status = 'open', closed_at = NULL WHERE incident_id = 'inc-001'", "APPEND_ONLY")
    golden.execute("INSERT INTO incidents (incident_id, run_id, severity, status, opened_at) VALUES ('inc-9', 'run-002', 'low', 'open', now())")
    fails(golden, "UPDATE incidents SET status = 'closed', closed_at = now() WHERE incident_id = 'inc-9'", "incidents_check1|violates check")      # no recovery run named
    golden.execute("UPDATE incidents SET status = 'closed', closed_at = now(), recovery_run_id = 'run-003' WHERE incident_id = 'inc-9'")


def test_definition_hash_is_checked_by_the_database_and_half_open_ranges_must_be_ordered(golden):
    fails(golden, "INSERT INTO model_definitions VALUES ('m-x', 'x', 'g', 1, 'select 1', repeat('0', 64))", "model_definitions_check")
    fails(golden, "INSERT INTO backfill_requests VALUES ('bf-x', 'src-orders', '2026-09-04T00:00:00Z', '2026-09-04T00:00:00Z', 'requested', '[]', 'x')", "backfill_requests_check")


def test_task_attempts_are_unique_per_run_and_task(golden):
    fails(golden, "INSERT INTO task_runs VALUES ('tr-dup', 'run-001', 'transform', 'success', 2)", "task_runs_attempt_uq")
    fails(golden, "INSERT INTO task_runs VALUES ('tr-dup', 'run-001', 'transform', 'success', 0)", "task_runs_attempt_check|attempt")


def test_quality_failures_cannot_exceed_the_eligible_count(golden):
    fails(golden, "INSERT INTO quality_results VALUES ('qr-x', 'tr-001-4', 'r', 'warning', 3, 4)", "quality_results_check")
