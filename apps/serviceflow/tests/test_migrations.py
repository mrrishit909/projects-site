"""Migrations are idempotent and the database enforces the append-only, arrival and shift rules."""
import psycopg
import pytest

from data import migrate, seed

from support_db import World, conn, count, db_url, golden_inputs, load, seeded  # noqa: F401

TABLES = ["customers", "queues", "agents", "skills", "agent_skills", "queue_skills", "shifts", "shift_breaks",
          "sla_policies", "tickets", "ticket_events", "surveys", "simulation_runs", "simulation_events", "raw_batches",
          "rejected_records", "audit_events", "command_results", "dataset_versions"]


def test_migrations_are_idempotent(db_url):
    with psycopg.connect(db_url) as c:
        assert migrate.apply_migrations(c) == []                      # the fixture already applied them
        migrate.reset(c)
        assert migrate.apply_migrations(c) == ["0001_schema.sql", "0002_constraints.sql"]
        assert migrate.apply_migrations(c) == []
    for name in ("0001_schema.sql", "0002_constraints.sql"):          # each file also re-runs cleanly
        with psycopg.connect(db_url) as c:
            c.execute((migrate.MIGRATIONS_DIR / name).read_text())


def test_every_table_exists_and_instants_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at' OR column_name = 'occurred_at') "
                       "AND table_name <> 'simulation_events' AND data_type <> 'timestamp with time zone'").fetchall()   # simulation_events.event_at is minutes
    assert bad == []


def test_entity_columns_are_exactly_the_contract_fields(conn):
    want = {"customers": ["customer_id", "segment", "timezone", "created_at", "synthetic"],
            "queues": ["queue_id", "queue_name", "priority_policy", "calendar_id", "active"],
            "tickets": ["ticket_id", "customer_id", "queue_id", "priority", "created_at", "channel"],
            "agents": ["agent_id", "agent_name", "timezone", "employment_type", "active", "max_concurrent"],
            "skills": ["skill_id", "skill_name", "description", "active", "created_at"],
            "agent_skills": ["agent_skill_id", "agent_id", "skill_id", "proficiency", "effective_from"],
            "queue_skills": ["queue_id", "skill_id"],
            "shifts": ["shift_id", "agent_id", "starts_at", "ends_at", "break_minutes"],
            "sla_policies": ["sla_policy_id", "priority", "first_response_minutes", "resolution_minutes", "calendar_id"],
            "surveys": ["survey_id", "ticket_id", "response_at", "score", "invited_at"]}
    for table, cols in want.items():
        got = [r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
            (table,)).fetchall()]
        assert got == cols, table
    ev = [r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'ticket_events' ORDER BY ordinal_position").fetchall()]
    assert ev == ["event_seq", "event_id", "ticket_id", "event_type", "occurred_at", "actor_id", "queue_id", "agent_id"]


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate.apply_migrations(c)


def test_seed_is_idempotent_and_records_rejected_rows(conn):
    first = seed.seed(conn, golden_inputs("variant-rejected"))
    assert first["skipped"] == 9 and first["inserted"]["tickets"] == 3 and first["inserted"]["ticket_events"] == 18
    again = seed.seed(conn, golden_inputs("variant-rejected"))
    assert sum(again["inserted"].values()) == 0 and again["dataset_version"] == first["dataset_version"]
    assert count(conn, "tickets") == 3 and count(conn, "rejected_records") == 9 and count(conn, "raw_batches") == 1
    assert count(conn, "dataset_versions") == 1 and count(conn, "simulation_events") == 6
    assert conn.execute("SELECT count(*) AS n FROM rejected_records WHERE reason_code = 'TICKET_REJECTED'").fetchone()["n"] == 7


def test_golden_simulation_events_are_stored(seeded):
    rows = seeded.execute("SELECT simulation_event_id, ticket_id, event_type, event_at::text AS at FROM simulation_events "
                          "ORDER BY simulation_event_id").fetchall()
    assert [(r["simulation_event_id"], r["ticket_id"], r["event_type"], r["at"]) for r in rows] == [
        ("se-001", "t-001", "service_started", "0.0000"), ("se-002", "t-002", "service_started", "10.0000"),
        ("se-003", "t-003", "service_started", "20.0000"), ("se-004", "t-001", "resolved", "10.0000"),
        ("se-005", "t-002", "resolved", "20.0000"), ("se-006", "t-003", "resolved", "30.0000")]


# --- immutable event log ----------------------------------------------------------------------------------------

def test_ticket_events_are_immutable(seeded):
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("UPDATE ticket_events SET occurred_at = now() WHERE event_id = 'e-001'")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("DELETE FROM ticket_events WHERE event_id = 'e-001'")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("TRUNCATE ticket_events")
    assert count(seeded, "ticket_events") == 18


def test_event_id_is_unique(seeded):
    with pytest.raises(psycopg.errors.UniqueViolation):
        seeded.execute("INSERT INTO ticket_events (event_id, ticket_id, event_type, occurred_at, actor_id, queue_id) "
                       "VALUES ('e-001', 't-001', 'queued', now(), NULL, 'q-001')")
    idx = seeded.execute("SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conname = 'ticket_events_event_id_key'").fetchone()
    assert idx["d"] == "UNIQUE (event_id)"


def test_audit_events_are_append_only(seeded):
    seeded.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id) VALUES ('a1', 't', '1', 'x', 'me')")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        seeded.execute("UPDATE audit_events SET action = 'y'")


def test_a_bot_cannot_author_a_human_reply_even_directly(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO ticket_events (event_id, ticket_id, event_type, occurred_at, actor_id, queue_id) "
                       "VALUES ('e-bot', 't-001', 'replied_human', now(), 'bot-001', 'q-001')")


def test_service_started_needs_an_agent(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO ticket_events (event_id, ticket_id, event_type, occurred_at, actor_id, queue_id) "
                       "VALUES ('e-na', 't-001', 'service_started', now(), 'x', 'q-001')")


def test_event_type_is_constrained(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO ticket_events (event_id, ticket_id, event_type, occurred_at) "
                       "VALUES ('e-bad', 't-001', 'teleported', now())")


# --- arrival and shifts -----------------------------------------------------------------------------------------

def test_a_ticket_keeps_its_arrival_but_may_change_queue(seeded):
    seeded.execute("INSERT INTO queues VALUES ('q-002', 'Other', 'fifo', 'cal-001', true)")
    seeded.execute("UPDATE tickets SET queue_id = 'q-002' WHERE ticket_id = 't-001'")            # a transfer: allowed
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="ARRIVAL_IMMUTABLE"):
        seeded.execute("UPDATE tickets SET created_at = created_at + interval '1 hour' WHERE ticket_id = 't-001'")


def test_shift_must_end_after_it_starts(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO shifts VALUES ('sh-x', 'agt-001', '2026-07-07T10:00Z', '2026-07-07T10:00Z', 0)")
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO shifts VALUES ('sh-y', 'agt-001', '2026-07-07T10:00Z', '2026-07-07T09:00Z', 0)")


def test_break_minutes_cannot_be_negative_or_exceed_the_shift(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO shifts VALUES ('sh-n', 'agt-001', '2026-07-07T09:00Z', '2026-07-07T17:00Z', -1)")
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO shifts VALUES ('sh-n', 'agt-001', '2026-07-07T09:00Z', '2026-07-07T10:00Z', 61)")
    seeded.execute("INSERT INTO shifts VALUES ('sh-ok', 'agt-001', '2026-07-07T09:00Z', '2026-07-07T10:00Z', 60)")


def test_agent_concurrency_defaults_to_one_and_is_at_least_one(conn):
    conn.execute("INSERT INTO agents (agent_id, agent_name, timezone, employment_type, active) VALUES ('a', 'A', 'UTC', 'full_time', true)")
    assert conn.execute("SELECT max_concurrent FROM agents").fetchone()["max_concurrent"] == 1
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE agents SET max_concurrent = 0")


def test_foreign_keys_hold(seeded):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        seeded.execute("INSERT INTO tickets VALUES ('t-9', 'c-nobody', 'q-001', 'P2', now(), 'email')")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        seeded.execute("INSERT INTO ticket_events (event_id, ticket_id, event_type, occurred_at) VALUES ('e-z', 't-nobody', 'queued', now())")


def test_survey_score_and_response_go_together(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO surveys VALUES ('sv-9', 't-002', NULL, 5, now())")
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute("INSERT INTO surveys VALUES ('sv-9', 't-002', now(), 6, now())")


def test_concurrency_is_an_application_rule_not_a_trigger(conn):
    """Intervals are derived from a log that accepts late arrivals, so overlap is checked by the domain and the commands
    (tests/test_adversarial.py P04-TEST-04); the schema deliberately has no overlap trigger."""
    triggers = {r["tgname"] for r in conn.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal").fetchall()}
    assert triggers == {"ticket_events_immutable", "ticket_events_no_truncate", "audit_events_append_only",
                        "simulation_events_append_only", "tickets_arrival_fixed"}
