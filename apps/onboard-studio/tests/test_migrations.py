"""Migrations are idempotent and the database enforces the append-only and immutability rules."""
import hashlib

import psycopg
import pytest

from data import migrate, seed

from support_db import conn, count, db_url, golden_inputs, seeded  # noqa: F401

TABLES = ["organizations", "workflow_versions", "step_definitions", "dependencies", "workflow_requirements",
          "sla_rules", "calendar_intervals", "cases", "step_instances", "assignments", "document_versions",
          "document_reviews", "approvals", "waiting_intervals", "case_events", "raw_batches", "rejected_records",
          "quarantined_records", "audit_events", "command_results", "dataset_versions"]


def test_migrations_are_idempotent(db_url):
    with psycopg.connect(db_url) as c:
        assert migrate.apply_migrations(c) == []                      # fixture already applied them
        migrate.reset(c)
        assert migrate.apply_migrations(c) == ["0001_schema.sql", "0002_constraints.sql", "0003_review_findings.sql"]
        assert migrate.apply_migrations(c) == []
    for name in ("0001_schema.sql", "0002_constraints.sql", "0003_review_findings.sql"):          # each file also re-runs cleanly
        with psycopg.connect(db_url) as c:
            c.execute((migrate.MIGRATIONS_DIR / name).read_text())


def test_every_table_exists_and_timestamps_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at' OR column_name IN ('occurred_at')) "
                       "AND data_type <> 'timestamp with time zone'").fetchall()
    assert bad == []
    assert conn.execute("SELECT data_type FROM information_schema.columns WHERE table_name = 'sla_rules' "
                        "AND column_name = 'business_minutes'").fetchone()["data_type"] == "numeric"


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate.apply_migrations(c)


def test_seed_is_idempotent_and_records_rejected_rows(conn):
    first = seed.seed(conn, golden_inputs("variant-rejected"))
    assert first["skipped"] == 10 and first["inserted"]["cases"] == 1
    again = seed.seed(conn, golden_inputs("variant-rejected"))
    assert sum(again["inserted"].values()) == 0 and again["dataset_version"] == first["dataset_version"]
    assert count(conn, "cases") == 1 and count(conn, "rejected_records") == 10 and count(conn, "raw_batches") == 1
    assert count(conn, "dataset_versions") == 1
    assert conn.execute("SELECT definition_hash FROM workflow_versions").fetchone()["definition_hash"] == \
        golden_inputs()["workflow_versions"][0]["definition_hash"]


def test_document_versions_are_append_only(seeded):
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("UPDATE document_versions SET review_status = 'rejected'")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("DELETE FROM document_versions")
    seeded.execute("INSERT INTO document_versions VALUES ('doc-002', 'case-001', 'identity_proof', 2, "
                   "'sha256:x', 'submitted', now(), NULL)")           # a new version is fine
    assert count(seeded, "document_versions") == 2


def test_audit_events_are_append_only(seeded):
    seeded.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id) "
                   "VALUES ('e1', 'case', 'case-001', 'x', 'a')")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        seeded.execute("UPDATE audit_events SET action = 'y'")


def test_published_workflow_version_is_immutable(seeded):
    for sql in ("UPDATE workflow_versions SET template_id = 'other'", "DELETE FROM workflow_versions",
                "UPDATE step_definitions SET role_key = 'x'", "DELETE FROM dependencies",
                "INSERT INTO step_definitions VALUES ('sd-9', 'wfv-001', 'n', true, 'ops', 9)",
                "INSERT INTO workflow_requirements VALUES ('wfv-001', 'tax_form')"):
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="immutable"):
            seeded.execute(sql)


def test_draft_workflow_version_can_change_until_published(conn):
    conn.execute("INSERT INTO workflow_versions (workflow_version_id, template_id, version_number) VALUES ('d', 't', 1)")
    conn.execute("INSERT INTO step_definitions VALUES ('d1', 'd', 'n', true, 'ops', 1)")
    conn.execute("UPDATE step_definitions SET role_key = 'reviewer' WHERE step_definition_id = 'd1'")
    with pytest.raises(psycopg.errors.CheckViolation):                # a published row needs its hash
        conn.execute("UPDATE workflow_versions SET published_at = now() WHERE workflow_version_id = 'd'")
    conn.execute("UPDATE workflow_versions SET published_at = now(), definition_hash = 'h' WHERE workflow_version_id = 'd'")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        conn.execute("UPDATE step_definitions SET role_key = 'ops'")


def test_one_decision_per_step_version_and_open_assignments(seeded):
    with pytest.raises(psycopg.errors.UniqueViolation):
        seeded.execute("INSERT INTO approvals VALUES ('apr-9', 'si-001', 'rev-9', 'approved', now(), NULL, 1)")
    seeded.execute("INSERT INTO approvals VALUES ('apr-9', 'si-001', 'rev-9', 'approved', now(), NULL, 2)")
    seeded.execute("INSERT INTO assignments VALUES ('asg-9', 'si-001', 'ops-9', now(), NULL)")    # NULL = open
    assert seeded.execute("SELECT count(*) AS n FROM assignments WHERE ended_at IS NULL").fetchone()["n"] == 1


def test_completed_case_cannot_be_reopened_in_the_database(seeded):  # P02-TEST-11
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="reopened"):
        seeded.execute("UPDATE cases SET status = 'open', completed_at = NULL")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        seeded.execute("UPDATE cases SET completed_at = completed_at + interval '1 hour'")
    with pytest.raises(psycopg.errors.CheckViolation):                # status and completed_at must agree
        seeded.execute("INSERT INTO cases (case_id, organization_id, workflow_version_id, status, opened_at) "
                       "VALUES ('c-x', 'org-001', 'wfv-001', 'completed', now())")


def test_check_constraints(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO calendar_intervals VALUES ('c', 'cal', now(), now() - interval '1 hour', 'UTC', 'working')")
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("UPDATE step_instances SET status = 'done'")
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("UPDATE sla_rules SET business_minutes = 0")
