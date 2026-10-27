"""Migrations are idempotent from an empty database, and the database enforces the append-only, ordering, citation and maturity rules."""
import psycopg
import pytest

from data import migrate

from support_db import conn, count, db_url, golden_inputs, load  # noqa: F401

FILES = ["0001_schema.sql", "0002_constraints.sql"]
TABLES = ["label_versions", "feature_versions", "feature_registry", "accounts", "subscription_events", "billing_events", "usage_events", "support_events",
          "prediction_cutoffs", "feature_rows", "labels", "training_runs", "model_preprocessing", "model_coefficients", "calibration_maps", "split_assignments",
          "predictions", "scoring_publications", "intervention_scenarios", "outreach_events", "rejected_records", "audit_events", "command_results", "dataset_versions"]
#: table -> (a column to "update", a WHERE that selects a golden row). Every one refuses UPDATE, DELETE and TRUNCATE.
APPEND_ONLY = {"accounts": ("segment", "account_id = 1"), "subscription_events": ("event_type", "subscription_event_id = 'se-001'"),
               "billing_events": ("amount", "billing_event_id = 'bil-001'"), "usage_events": ("event_name", "usage_event_id = 'ue-001'"),
               "support_events": ("severity", "support_event_id = 'sup-001'"), "prediction_cutoffs": ("horizon_end", "cutoff_id = 'co-01-20260101'"),
               "feature_rows": ("max_available_at", "feature_row_id = 'fr-co-01-20260101'"), "predictions": ("probability", "prediction_id = 'pr-co-01-20260101'"),
               "split_assignments": ("split", "assignment_id = 'sa-tr-001-co-01-20250301'"), "scoring_publications": ("status", "publication_id = 'sp-001'"),
               "intervention_scenarios": ("capacity", "scenario_id = 'sc-001'"), "outreach_events": ("action", "outreach_event_id = 'oe-001'"),
               "feature_registry": ("lineage", "feature_name = 'usage_events_30d'"), "label_versions": ("grace_days", "label_version_id = 'lv-1'"),
               "feature_versions": ("observation_days", "feature_version = 'fv-1'")}


@pytest.fixture
def golden(conn):
    load(conn, golden_inputs())
    return conn


def test_migrations_apply_from_empty_and_are_idempotent(db_url):
    with psycopg.connect(db_url) as c:
        assert migrate.apply_migrations(c) == []                      # the fixture already applied them
        migrate.reset(c)
        left = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'").fetchone()[0]
        funcs = c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname LIKE 'rl\\_%'").fetchone()[0]
        assert (left, funcs) == (0, 0)                                # an empty database
        assert migrate.apply_migrations(c) == FILES                   # from empty
        assert migrate.apply_migrations(c) == []                      # a second run applies nothing
    for name in FILES:                                                # each file also re-runs cleanly on a populated schema
        with psycopg.connect(db_url) as c:
            c.execute((migrate.MIGRATIONS_DIR / name).read_text())


def test_the_command_line_entry_point_is_idempotent_too(db_url, capsys):
    assert migrate.main(["--reset"]) == 0 and "applied: 0001_schema.sql, 0002_constraints.sql" in capsys.readouterr().out
    assert migrate.main([]) == 0 and "nothing (up to date)" in capsys.readouterr().out


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate.apply_migrations(c)


def test_every_table_exists_and_instants_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at' OR column_name LIKE '%\\_end' OR column_name IN ('observation_start')) AND data_type <> 'timestamp with time zone'").fetchall()
    assert bad == []


def test_no_float_column_anywhere_and_money_and_probabilities_are_numeric_20_6(conn):
    rows = conn.execute("SELECT table_name, column_name, data_type, numeric_precision, numeric_scale FROM information_schema.columns WHERE table_schema = 'public' "
                        "AND data_type IN ('numeric', 'double precision', 'real')").fetchall()
    got = {(r["table_name"], r["column_name"]): (r["data_type"], r["numeric_precision"], r["numeric_scale"]) for r in rows}
    assert {v[0] for v in got.values()} == {"numeric"} and {v[1:] for v in got.values()} == {(20, 6)}
    assert {("billing_events", "amount"), ("predictions", "probability"), ("intervention_scenarios", "contact_cost"), ("intervention_scenarios", "assumed_effect"),
            ("intervention_scenarios", "margin_value"), ("model_coefficients", "value"), ("calibration_maps", "a"), ("calibration_maps", "b"),
            ("model_preprocessing", "median"), ("model_preprocessing", "mean"), ("model_preprocessing", "std")} == set(got)


def test_the_golden_fixture_loads_with_nothing_rejected_and_seed_is_idempotent(conn):
    first = load(conn, golden_inputs(), dataset_version="ds-golden-1")
    assert first["skipped"] == 0 and first["inserted"]["usage_events"] == 26 and first["inserted"]["predictions"] == 7 and first["inserted"]["training_runs"] == 1
    again = load(conn, golden_inputs(), dataset_version="ds-golden-1")
    assert sum(again["inserted"].values()) == 0 and count(conn, "dataset_versions") == 1 and count(conn, "model_coefficients") == 3 and count(conn, "calibration_maps") == 1
    default = load(conn, golden_inputs())
    assert default["dataset_version"] == f"ds-{default['dataset_hash'][:12]}" and count(conn, "dataset_versions") == 2
    assert conn.execute("SELECT as_of FROM dataset_versions WHERE dataset_version = 'ds-golden-1'").fetchone()["as_of"].isoformat() == "2026-05-01T00:00:00+00:00"


def test_scope_and_requests_of_a_fixture_are_never_loaded(conn):
    load(conn, golden_inputs("variant-rejected"))
    assert count(conn, "audit_events") == 0 and count(conn, "command_results") == 0       # the fixture's `requests` are test inputs, not commands that ran


@pytest.mark.parametrize("table,spec", sorted(APPEND_ONLY.items()))
def test_append_only_tables_refuse_update_delete_and_truncate(golden, table, spec):
    column, where = spec
    for sql in (f"UPDATE {table} SET {column} = {column} WHERE {where}", f"DELETE FROM {table} WHERE {where}", f"TRUNCATE {table} CASCADE"):
        with pytest.raises(psycopg.errors.IntegrityError, match="append-only"):
            golden.execute(sql)                                                          # table, column and where are test constants


def test_audit_results_and_rejections_are_append_only_too(conn):
    conn.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id) VALUES ('e1', 't', 'i', 'a', 'x')")
    conn.execute("INSERT INTO command_results VALUES ('k', 'h', 'a', 'admin', 'c', 's', '{}')")
    conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row) VALUES ('b', 'accounts', '1', 'X', '{}')")
    for sql in ("UPDATE audit_events SET action = 'b'", "DELETE FROM audit_events", "UPDATE command_results SET status = 'x'", "DELETE FROM command_results",
                "UPDATE rejected_records SET reason_code = 'Y'", "TRUNCATE rejected_records"):
        with pytest.raises(psycopg.errors.IntegrityError):
            conn.execute(sql)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO command_results VALUES ('k2', 'h', 'a', 'root', 'c', 's', '{}')")


def test_accounts_are_synthetic_and_events_cannot_be_known_before_they_happen(golden):
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("INSERT INTO accounts VALUES (500, now(), 'mid', 'amer', false)")
    for table, cols in (("usage_events", "('ue-x', 1, 'login', '2026-01-02T00:00:00Z', '2026-01-01T00:00:00Z')"),
                        ("subscription_events", "('se-x', 1, 'renew', '2026-01-02T00:00:00Z', '2026-01-01T00:00:00Z')"),
                        ("billing_events", "('b-x', 1, 5, '2026-01-02T00:00:00Z', '2026-01-01T00:00:00Z')"),
                        ("support_events", "('s-x', 1, 'low', '2026-01-02T00:00:00Z', '2026-01-01T00:00:00Z')")):
        with pytest.raises(psycopg.errors.CheckViolation):
            golden.execute(f"INSERT INTO {table} VALUES {cols}")                         # constants
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("INSERT INTO subscription_events VALUES ('se-y', 1, 'pause', now(), now())")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        golden.execute("INSERT INTO usage_events VALUES ('ue-y', 4040, 'login', now(), now())")


def test_cutoffs_are_ordered_and_unique_per_account_and_instant(golden):
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("INSERT INTO prediction_cutoffs VALUES ('c-bad', 1, '2026-01-01T00:00:00Z', '2025-12-01T00:00:00Z', '2025-10-03T00:00:00Z')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        golden.execute("INSERT INTO prediction_cutoffs VALUES ('c-dup', 1, '2026-01-01T00:00:00Z', '2026-04-01T00:00:00Z', '2025-10-03T00:00:00Z')")


def test_a_feature_row_cannot_use_data_that_arrived_at_or_after_the_cutoff(golden):
    ins = "INSERT INTO feature_rows VALUES ('fr-new', 'co-05-20260101', 'fv-1', '{}', %s)"
    for bad in ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"):
        with pytest.raises(psycopg.errors.IntegrityError, match="AVAILABILITY_AFTER_CUTOFF"):
            golden.execute(ins, (bad,))
    golden.execute(ins, ("2025-12-31T23:59:59Z",))
    golden.execute("INSERT INTO feature_rows VALUES ('fr-null', 'co-06-20260101', 'fv-1', '{}', NULL)")


def test_labels_are_never_false_while_censored_and_mature_exactly_once(golden):
    with pytest.raises(psycopg.errors.CheckViolation):                               # censored and false
        golden.execute("INSERT INTO labels VALUES ('lb-x', 'co-05-20260101', false, '2026-04-15T00:00:00Z', false)")
    with pytest.raises(psycopg.errors.CheckViolation):                               # mature and unknown
        golden.execute("INSERT INTO labels VALUES ('lb-x', 'co-05-20260101', NULL, '2026-04-15T00:00:00Z', true)")
    with pytest.raises(psycopg.errors.IntegrityError, match="LABEL_WINDOW_INVALID"):
        golden.execute("INSERT INTO labels VALUES ('lb-x', 'co-05-20260101', NULL, '2026-03-01T00:00:00Z', false)")
    with pytest.raises(psycopg.errors.IntegrityError, match="LABEL_IMMUTABLE"):      # a mature label never changes
        golden.execute("UPDATE labels SET churned = NOT churned WHERE label_id = 'lb-co-01-20260101'")
    with pytest.raises(psycopg.errors.IntegrityError, match="LABEL_IMMUTABLE"):      # a censored label may only become mature with a known outcome
        golden.execute("UPDATE labels SET mature = true WHERE label_id = 'lb-co-01-20260201'")
    golden.execute("UPDATE labels SET mature = true, churned = true WHERE label_id = 'lb-co-01-20260201'")
    with pytest.raises(psycopg.errors.IntegrityError, match="LABEL_IMMUTABLE"):
        golden.execute("UPDATE labels SET churned = false WHERE label_id = 'lb-co-01-20260201'")
    with pytest.raises(psycopg.errors.IntegrityError, match="append-only"):
        golden.execute("DELETE FROM labels WHERE label_id = 'lb-co-02-20260201'")


def test_a_prediction_cites_its_runs_hash_feature_version_and_label_version_and_a_probability_is_in_range(golden):
    run = golden.execute("SELECT config_hash FROM training_runs").fetchone()["config_hash"]
    ins = "INSERT INTO predictions (prediction_id, training_run_id, cutoff_id, probability, scored_at, config_hash, feature_version, label_version) VALUES (%s,'tr-001','co-05-20260101',%s,now(),%s,%s,%s)"
    for args in (("p1", "0.5", "0" * 64, "fv-1", "lv-1"), ("p2", "0.5", run, "fv-9", "lv-1"), ("p3", "0.5", run, "fv-1", "lv-9")):
        with pytest.raises((psycopg.errors.IntegrityError)):
            golden.execute(ins, args)
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute(ins, ("p4", "1.2", run, "fv-1", "lv-1"))
    golden.execute(ins, ("p5", "0.25", run, "fv-1", "lv-1"))
    with pytest.raises(psycopg.errors.UniqueViolation):                              # one prediction per run, cutoff and model
        golden.execute(ins, ("p6", "0.25", run, "fv-1", "lv-1"))


def test_a_training_run_is_frozen_once_it_has_a_prediction(golden, conn):
    with pytest.raises(psycopg.errors.IntegrityError, match="RUN_FROZEN"):
        golden.execute("UPDATE training_runs SET config = '{}'::jsonb, config_hash = repeat('a', 64) WHERE training_run_id = 'tr-001'")
    with pytest.raises(psycopg.errors.IntegrityError, match="RUN_FROZEN"):
        golden.execute("DELETE FROM calibration_maps WHERE training_run_id = 'tr-001'")
    with pytest.raises(psycopg.errors.IntegrityError, match="RUN_IMMUTABLE"):
        golden.execute("UPDATE training_runs SET train_end = train_end + interval '1 day' WHERE training_run_id = 'tr-001'")
    with pytest.raises(psycopg.errors.IntegrityError, match="append-only"):
        golden.execute("DELETE FROM training_runs WHERE training_run_id = 'tr-001'")
    golden.execute("INSERT INTO training_runs VALUES ('tr-new', '2025-06-01T00:00:00Z', '2025-10-01T00:00:00Z', '2026-06-01T00:00:00Z', '{}', repeat('b', 64), now(), 'x')")
    golden.execute("UPDATE training_runs SET config = '{\"a\": 1}'::jsonb, config_hash = repeat('c', 64) WHERE training_run_id = 'tr-new'")       # not scored yet: may change
    golden.execute("INSERT INTO calibration_maps VALUES ('tr-new', 'platt', 1.5, -0.25, 3)")
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("INSERT INTO training_runs VALUES ('tr-bad', '2025-10-01T00:00:00Z', '2025-06-01T00:00:00Z', '2026-06-01T00:00:00Z', '{}', repeat('b', 64), now(), 'x')")
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("INSERT INTO training_runs VALUES ('tr-bad', '2025-06-01T00:00:00Z', '2025-10-01T00:00:00Z', '2026-06-01T00:00:00Z', '{}', 'not-a-hash', now(), 'x')")


def test_scenarios_and_the_outreach_queue_are_drafts_with_assumptions_in_range(golden):
    ins = "INSERT INTO intervention_scenarios (scenario_id, capacity, contact_cost, assumed_effect, margin_value, selected_on) VALUES (%s,%s,%s,%s,%s,%s)"
    for args in (("s1", 0, "1", "0.1", "1", "validation"), ("s2", 1, "-1", "0.1", "1", "validation"), ("s3", 1, "1", "1.5", "1", "validation"),
                 ("s4", 1, "1", "-0.1", "1", "validation"), ("s5", 1, "1", "0.1", "-5", "validation"), ("s6", 1, "1", "0.1", "1", "test")):
        with pytest.raises(psycopg.errors.CheckViolation):
            golden.execute(ins, args)
    golden.execute(ins, ("s7", 2, "1.25", "1", "10", "validation"))
    for status in ("sent", "queued", "scheduled"):
        with pytest.raises(psycopg.errors.CheckViolation):                           # nothing is ever sent
            golden.execute("INSERT INTO outreach_events (outreach_event_id, account_id, scenario_id, action, status) VALUES ('oe-s', 3, 'sc-001', 'propose_contact', %s)", (status,))
    with pytest.raises(psycopg.errors.UniqueViolation):                              # one queue row per scenario and account
        golden.execute("INSERT INTO outreach_events (outreach_event_id, account_id, scenario_id, action, status) VALUES ('oe-dup', 1, 'sc-001', 'propose_contact', 'draft')")


def test_split_assignments_carry_a_reason_exactly_when_dropped(golden):
    ins = "INSERT INTO split_assignments VALUES (%s, 'tr-001', %s, %s, %s, %s)"
    for args in (("sa-1", "co-05-20260101", "test", "dropped", None), ("sa-2", "co-05-20260101", "test", "retained", "GROUP_TEST"),
                 ("sa-3", "co-05-20260101", "elsewhere", "retained", None), ("sa-4", "co-05-20260101", "train", "dropped", "BECAUSE")):
        with pytest.raises(psycopg.errors.CheckViolation):
            golden.execute(ins, args)
