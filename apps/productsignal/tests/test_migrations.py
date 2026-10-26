"""Migrations are idempotent and the database enforces the append-only, uniqueness and ordering rules."""
import json
from decimal import Decimal

import psycopg
import pytest

from data import migrate, seed
from productsignal.models import canonical_json, plan_hash

from support_db import PLAN_BODY, conn, count, db_url, golden_inputs, load  # noqa: F401

TABLES = ["accounts", "users", "identity_links", "sessions", "events", "event_properties", "subscriptions", "experiment_versions",
          "analysis_plans", "assignments", "exposures", "metric_observations", "analysis_runs", "funnel_definitions", "metric_config",
          "guardrail_reviews", "decisions", "rejected_records", "audit_events", "command_results", "dataset_versions", "t_critical_975", "ps_timezones"]
FILES = ["0001_schema.sql", "0002_constraints.sql"]


@pytest.fixture
def golden(conn):
    load(conn, golden_inputs())
    return conn


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
        funcs = c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                          "WHERE n.nspname = 'public' AND p.proname LIKE 'ps\\_%'").fetchone()[0]
    assert (left, funcs) == (0, 0)


def test_every_table_exists_and_instants_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at' OR column_name IN ('window_end', 'window_from', 'window_to')) "
                       "AND data_type <> 'timestamp with time zone'").fetchall()
    assert bad == []


def test_amounts_are_exact_numeric_never_float(conn):
    rows = conn.execute("SELECT table_name, column_name, data_type, numeric_scale FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND data_type IN ('numeric', 'double precision', 'real')").fetchall()
    assert rows and not [r for r in rows if r["data_type"] != "numeric"]
    assert {(r["table_name"], r["column_name"]): r["numeric_scale"] for r in rows}[("subscriptions", "amount_usd")] == 2


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate.apply_migrations(c)


def test_seed_is_idempotent_and_records_rejected_rows(conn):
    first = load(conn, golden_inputs("variant-rejected"))
    assert first["skipped"] == 4 and first["inserted"]["assignments"] == 20 and first["inserted"]["exposures"] == 17
    again = load(conn, golden_inputs("variant-rejected"))
    assert sum(again["inserted"].values()) == 0 and again["dataset_version"] == first["dataset_version"]
    assert count(conn, "assignments") == 20 and count(conn, "rejected_records") == 4 and count(conn, "dataset_versions") == 1
    assert count(conn, "rejected_records", "reason_code = 'DEPENDENT_REJECTED'") == 2
    assert count(conn, "rejected_records", "reason_code = 'ASSIGNMENT_CONFLICT'") == 1
    assert count(conn, "rejected_records", "reason_code = 'EXPOSURE_BEFORE_ASSIGNMENT'") == 1
    raw = conn.execute("SELECT raw_row FROM rejected_records WHERE id = 'as-c-003-b'").fetchone()["raw_row"]
    assert raw["variant"] == "treatment"                                  # the raw row is kept


def test_golden_seed_stores_the_log_the_plan_the_funnel_and_the_windows(golden):
    assert count(golden, "accounts") == 235 and count(golden, "users") == 236 and count(golden, "events") == 529   # the log keeps every row
    assert count(golden, "event_properties") == 379 and count(golden, "identity_links") == 11 and count(golden, "sessions") == 30
    assert count(golden, "assignments") == 200 and count(golden, "exposures") == 180 and count(golden, "metric_observations") == 200
    assert count(golden, "analysis_runs") == 2 and count(golden, "analysis_plans") == 1 and count(golden, "funnel_definitions") == 1
    plan = golden.execute("SELECT * FROM analysis_plans").fetchone()
    assert plan["config_hash"] == "b3e7466e10b2c0d3fd1adfed5155c60a18447dac1af3d9ebde02be35ec77d659"
    assert "config_hash" not in plan["plan"] and plan_hash(plan["plan"]) == plan["config_hash"]
    assert golden.execute("SELECT windows FROM metric_config").fetchone()["windows"]["retention"] == {"signup_from": "2026-09-14", "signup_to": "2026-09-21"}
    assert count(golden, "t_critical_975") == 2000
    assert golden.execute("SELECT amount_usd FROM subscriptions WHERE subscription_id = 'sub-001'").fetchone()["amount_usd"] == Decimal("49.00")


def test_seed_loads_a_directory_of_entity_files(conn, tmp_path):
    inputs = golden_inputs("variant-rejected")
    config = {k: inputs[k] for k in ("contract_version", "cutoff", "as_of", "analysis_plan", "metric_windows")}
    (tmp_path / "config.json").write_text(json.dumps(config))
    for ent in seed.ENTITIES:
        (tmp_path / f"{ent}.json").write_text(json.dumps(inputs[ent]))
    loaded = seed.load_inputs(tmp_path)
    assert loaded["accounts"] == inputs["accounts"] and loaded["cutoff"] == inputs["cutoff"]
    assert load(conn, loaded)["inserted"]["assignments"] == 20


def test_ps_canonical_json_equals_pythons_compact_sorted_form(conn):
    for value in (PLAN_BODY, {"b": [1, {"z": None, "a": True}], "a": "é\"\\\n", "10": 1.5 if False else 2, "": []}, [], {}, "x", 7):
        got = conn.execute("SELECT ps_canonical_json(%s::jsonb) AS t", (json.dumps(value),)).fetchone()["t"]
        assert got == canonical_json(value)
    assert conn.execute("SELECT encode(sha256(convert_to(ps_canonical_json(%s::jsonb), 'UTF8')), 'hex') AS h", (json.dumps(PLAN_BODY),)).fetchone()["h"] == plan_hash(PLAN_BODY)


def test_the_student_t_table_is_the_textbook_one(golden):
    t = {r["df"]: r["t"] for r in golden.execute("SELECT df, t FROM t_critical_975 WHERE df IN (1, 2, 7, 9, 11, 99, 2000)").fetchall()}
    assert {k: str(v.quantize(Decimal("1e-6"))) for k, v in t.items()} == {1: "12.706205", 2: "4.302653", 7: "2.364624", 9: "2.262157",
                                                                          11: "2.200985", 99: "1.984217", 2000: "1.961151"}


# --- the database refuses what the domain refuses --------------------------------------------------------------

@pytest.mark.parametrize("sql,kind", [
    ("UPDATE events SET event_name = 'visit' WHERE event_id = 'ev-s-c-001'", psycopg.errors.IntegrityError),                     # the log is append-only
    ("DELETE FROM events WHERE event_id = 'ev-s-c-001'", psycopg.errors.IntegrityError),
    ("TRUNCATE identity_links", psycopg.errors.IntegrityError),
    ("UPDATE event_properties SET property_value = 'x'", psycopg.errors.IntegrityError),
    ("DELETE FROM identity_links", psycopg.errors.IntegrityError),
    ("UPDATE assignments SET variant = 'treatment' WHERE assignment_id = 'as-c-001'", psycopg.errors.IntegrityError),           # the variant is fixed
    ("DELETE FROM assignments WHERE assignment_id = 'as-c-001'", psycopg.errors.IntegrityError),
    ("UPDATE exposures SET exposed_at = now()", psycopg.errors.IntegrityError),
    ("UPDATE metric_observations SET value = '0'", psycopg.errors.IntegrityError),
    ("UPDATE analysis_plans SET config_hash = repeat('a', 64)", psycopg.errors.IntegrityError),                                  # a frozen plan is frozen
    ("DELETE FROM analysis_plans", psycopg.errors.IntegrityError),
    ("UPDATE analysis_runs SET cutoff_at = now()", psycopg.errors.IntegrityError),
    ("DELETE FROM analysis_runs", psycopg.errors.IntegrityError),
    ("UPDATE funnel_definitions SET max_gap_hours = 1", psycopg.errors.IntegrityError),
    ("INSERT INTO assignments (assignment_id, experiment_version_id, unit_id, variant, assigned_at) "
     "VALUES ('as-dup', 'xv-001', 'acc-c-001', 'treatment', now())", psycopg.errors.UniqueViolation),                           # one assignment per unit
    ("INSERT INTO exposures (exposure_id, assignment_id, exposed_at, surface) VALUES ('ex-dup', 'as-c-001', now(), 's')", psycopg.errors.UniqueViolation),
    ("INSERT INTO exposures (exposure_id, assignment_id, exposed_at, surface) VALUES ('ex-early', 'as-c-091', '2026-10-01T00:00:00Z', 's')",
     psycopg.errors.IntegrityError),                                                                                             # exposure before assignment
    ("INSERT INTO assignments (assignment_id, experiment_version_id, unit_id, variant, assigned_at) "
     "VALUES ('as-int', 'xv-001', 'acc-int-1', 'control', now())", psycopg.errors.IntegrityError),                              # internal accounts are not randomised
    ("INSERT INTO assignments (assignment_id, experiment_version_id, unit_id, variant, assigned_at) "
     "VALUES ('as-x', 'xv-nope', 'acc-m-01', 'control', now())", psycopg.errors.ForeignKeyViolation),
    ("INSERT INTO metric_observations VALUES ('ob-x', 'as-c-001', 'activation_7d', '2', now())", psycopg.errors.CheckViolation),
    ("INSERT INTO metric_observations VALUES ('ob-y', 'as-c-001', 'activation_7d', '1', now())", psycopg.errors.UniqueViolation),
    ("INSERT INTO accounts VALUES ('acc-tz', 'team', 'smb', now(), false, 'Mars/Olympus')", psycopg.errors.CheckViolation),
    ("INSERT INTO events (event_id, event_name, event_at, received_at) VALUES ('e-bad', 'Bad Name', now(), now())", psycopg.errors.CheckViolation),
    ("INSERT INTO event_properties VALUES ('pr-dup', 'ev-x-c-001', 'variant', 'x', 'string')", psycopg.errors.UniqueViolation),
    ("INSERT INTO identity_links (identity_link_id, anonymous_id, user_id, linked_at, rule_version) VALUES ('il-x', 'a-f01', 'u-f02', now(), 'v1')",
     psycopg.errors.UniqueViolation),                                                                                            # one user per anonymous_id
    ("INSERT INTO subscriptions VALUES ('sub-x', 'acc-c-001', now(), NULL, 'active', -1)", psycopg.errors.CheckViolation),
    ("INSERT INTO analysis_runs (analysis_id, experiment_version_id, cutoff_at, config_hash) VALUES ('an-x', 'xv-001', now(), 'short')", psycopg.errors.CheckViolation),
    ("INSERT INTO funnel_definitions (definition_id, version, steps, max_gap_hours, window_from, window_to) "
     "VALUES ('f', 1, ARRAY['visit'], 48, now(), now() + interval '1 day')", psycopg.errors.CheckViolation),
    ("INSERT INTO metric_config VALUES (2, '{}')", psycopg.errors.CheckViolation),
    ("INSERT INTO experiment_versions VALUES ('xv-user', 'n', 'user', 'activation_7d', now())", psycopg.errors.CheckViolation),    # the unit is the account
])
def test_the_database_refuses(golden, sql, kind):
    golden.execute("INSERT INTO accounts VALUES ('acc-int-1', 'business', 'mid', now(), true, 'UTC') ON CONFLICT DO NOTHING")
    with pytest.raises(kind):
        golden.execute(sql)


def test_decisions_and_reviews_are_constrained_and_append_only(golden):
    golden.execute("INSERT INTO guardrail_reviews (review_id, analysis_id, experiment_version_id, verdict, result, reviewed_by) "
                   "VALUES ('gr-1', 'an-002', 'xv-001', 'OK', '{}', 'u')")
    with pytest.raises(psycopg.errors.UniqueViolation):                                   # one review per run
        golden.execute("INSERT INTO guardrail_reviews (review_id, analysis_id, experiment_version_id, verdict, result, reviewed_by) "
                       "VALUES ('gr-2', 'an-002', 'xv-001', 'OK', '{}', 'u')")
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("INSERT INTO guardrail_reviews (review_id, analysis_id, experiment_version_id, verdict, result, reviewed_by) "
                       "VALUES ('gr-3', 'an-001', 'xv-001', 'FINE', '{}', 'u')")
    ins = ("INSERT INTO decisions (decision_id, experiment_version_id, analysis_id, review_id, decision, rationale, decided_by, decided_role, decided_at) "
           "VALUES (%s, 'xv-001', 'an-002', 'gr-1', %s, %s, 'u', %s, now())")
    for args, kind in ((("d-1", "maybe", "r", "admin"), psycopg.errors.CheckViolation), (("d-1", "ship", "  ", "admin"), psycopg.errors.CheckViolation),
                       (("d-1", "ship", "r", "analyst"), psycopg.errors.CheckViolation)):
        with pytest.raises(kind):
            golden.execute(ins, args)
    golden.execute(ins, ("d-1", "inconclusive", "r", "admin"))
    with pytest.raises(psycopg.errors.UniqueViolation):                                   # one decision per analysis run
        golden.execute(ins, ("d-2", "stop", "r", "admin"))
    with pytest.raises(psycopg.errors.IntegrityError):
        golden.execute("UPDATE decisions SET decision = 'ship'")
    with pytest.raises(psycopg.errors.IntegrityError):
        golden.execute("DELETE FROM decisions")


def test_reference_rows_may_change_but_only_through_their_own_columns(golden):
    golden.execute("UPDATE accounts SET plan = 'business' WHERE account_id = 'acc-c-001'")
    assert golden.execute("SELECT plan FROM accounts WHERE account_id = 'acc-c-001'").fetchone()["plan"] == "business"
