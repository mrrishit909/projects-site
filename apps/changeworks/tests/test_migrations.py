"""Migrations succeed from an empty database and on a second run; the database enforces the append-only, ordering, uniqueness and approval rules."""
import psycopg
import pytest

from data import migrate

from support_db import conn, count, db_url, golden_inputs, load, table_digest  # noqa: F401

FILES = ["0001_schema.sql", "0002_constraints.sql", "0003_review9.sql"]
TABLES = ["dataset_config", "initiatives", "process_baselines", "baseline_approvals", "assumption_versions", "opportunity_scores", "resources", "scenario_versions",
          "scenario_initiatives", "scenario_pins", "cost_items", "expanded_costs", "benefit_items", "dependencies", "stakeholder_groups", "impact_mappings",
          "resource_allocations", "readiness_assessments", "adoption_observations", "training_completions", "benefit_observations", "risk_items", "forecast_versions",
          "rejected_records", "audit_events", "command_results", "dataset_versions"]
APPEND_ONLY = {"process_baselines": "baseline_id = 'pb-101'", "baseline_approvals": "true", "assumption_versions": "assumption_id = 'a-101-t1'", "resources": "true",
               "scenario_initiatives": "true", "scenario_pins": "true", "cost_items": "cost_id = 'c-101'", "benefit_items": "benefit_id = 'b-101'",
               "dependencies": "dependency_id = 'd-1'", "stakeholder_groups": "group_id = 'grp-001'", "impact_mappings": "mapping_id = 'im-1'",
               "resource_allocations": "allocation_id = 'al-1'", "readiness_assessments": "assessment_id = 'ra-1'", "adoption_observations": "observation_id = 'ad-1'",
               "training_completions": "training_id = 'tc-1'", "benefit_observations": "benefit_observation_id = 'bo-1'", "risk_items": "risk_id = 'r-101a'",
               "forecast_versions": "forecast_id = 'f-101-1-1'", "dataset_versions": "true"}


@pytest.fixture
def golden(conn):
    load(conn, golden_inputs())
    return conn


def fails(conn, sql, *params, contains=""):
    """The statement is refused by the database (an integrity or check violation); the message names the rule."""
    with pytest.raises(psycopg.errors.IntegrityError) as e:
        with conn.transaction():
            conn.execute(sql, params)
    assert contains in str(e.value), str(e.value)


def test_migrations_from_an_empty_database_and_idempotent_on_a_second_run(db_url):
    with psycopg.connect(db_url) as c:
        migrate.reset(c)
    with psycopg.connect(db_url) as c:
        left = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'").fetchone()[0]
        assert left == 0                                              # empty
        assert migrate.apply_migrations(c) == FILES
    with psycopg.connect(db_url) as c:
        assert migrate.apply_migrations(c) == []                      # the second run applies nothing
    for name in FILES:                                                # each file also re-runs cleanly (IF NOT EXISTS everywhere)
        with psycopg.connect(db_url) as c:
            c.execute((migrate.MIGRATIONS_DIR / name).read_text())


def test_reset_drops_everything_the_migrations_create(db_url):
    with psycopg.connect(db_url) as c:
        migrate.reset(c)
        left = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'").fetchone()[0]
        funcs = c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname LIKE 'cw\\_%'").fetchone()[0]
    assert (left, funcs) == (0, 0)


def test_every_table_exists_and_instants_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at' OR column_name = 'valid_from') AND data_type <> 'timestamp with time zone'").fetchall()
    assert bad == []


def test_money_is_numeric_20_6_proportions_numeric_7_6_and_no_float_column_anywhere(conn):
    rows = conn.execute("SELECT table_name, column_name, data_type, numeric_precision, numeric_scale FROM information_schema.columns WHERE table_schema = 'public' "
                        "AND data_type IN ('numeric', 'double precision', 'real')").fetchall()
    assert not [r for r in rows if r["data_type"] != "numeric"]
    got = {(r["table_name"], r["column_name"]): (r["numeric_precision"], r["numeric_scale"]) for r in rows}
    for key in [("cost_items", "amount"), ("benefit_items", "amount"), ("forecast_versions", "amount"), ("risk_items", "impact"), ("benefit_observations", "measured_value"),
                ("benefit_items", "baseline_trend_per_period"), ("resources", "capacity_per_period"), ("resource_allocations", "amount"), ("expanded_costs", "amount")]:
        assert got[key] == (20, 6), key
    for key in [("process_baselines", "error_rate"), ("scenario_versions", "discount_rate"), ("risk_items", "probability")]:
        assert got[key] == (7, 6), key


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c:
        with pytest.raises(RuntimeError, match="changed after it was applied"):
            migrate.apply_migrations(c)


def test_seed_is_idempotent_and_names_its_dataset_version(conn):
    first = load(conn, golden_inputs(), dataset_version="ds-golden-1")
    assert first["dataset_version"] == "ds-golden-1" and sum(first["inserted"].values()) == 71 and first["skipped"] == 0 and first["warnings"] == []
    n = {t: count(conn, t) for t in TABLES}
    again = load(conn, golden_inputs(), dataset_version="ds-golden-1")
    assert sum(again["inserted"].values()) == 0 and {t: count(conn, t) for t in TABLES} == n
    assert count(conn, "dataset_versions") == 1 and count(conn, "baseline_approvals") == 2
    third = load(conn, golden_inputs())
    assert third["dataset_version"].startswith("ds-") and count(conn, "dataset_versions") == 2


def test_seed_keeps_rejected_records_with_raw_rows_and_does_not_load_them(conn):
    out = load(conn, golden_inputs("variant-rejected"))
    assert out["skipped"] == 30 and count(conn, "rejected_records") == 30
    row = conn.execute("SELECT * FROM rejected_records WHERE id = 'rd-3'").fetchone()
    assert row["entity"] == "dependencies" and row["reason_code"] == "DEPENDENCY_CYCLE" and row["details"]["cycle"] == ["rj-i1", "rj-i3", "rj-i2", "rj-i1"]
    assert row["raw_row"]["prerequisite_id"] == "rj-i3"
    assert count(conn, "dependencies") == 2 and count(conn, "initiatives") == 10          # four of the original six, and the six probe initiatives
    assert conn.execute("SELECT status FROM initiatives WHERE initiative_id = 'rj-i1'").fetchone()["status"] == "in_delivery"      # the first of the two repeats is kept
    seqs = [r["seq"] for r in conn.execute("SELECT seq FROM rejected_records ORDER BY seq").fetchall()]
    assert seqs == sorted(seqs)


def test_the_rejected_record_echo_keeps_the_original_number_text(conn):
    """R9-22: a fractional or exponent number in a rejected row is echoed as written (1.50, 1e3, 0.0), not as the float it parses to."""
    import json as _json
    from data import seed
    d = _json.loads(_json.dumps(golden_inputs()))
    text = _json.dumps(d).replace('"cost_items": [', '"cost_items": [{"cost_id": "raw-1", "initiative_id": "i-1", "amount": 1.50, "extra": [1e3, 0.0]}, ', 1)
    assert '"raw-1"' in text
    load(conn, seed.load_json(text))
    raw = conn.execute("SELECT raw_row::text AS t FROM rejected_records WHERE id = 'raw-1'").fetchone()["t"]
    assert "1.50" in raw and "0.0" in raw and "1000" in raw.replace("1e3", "1000")


def test_an_initiative_naming_a_baseline_that_was_not_loaded_is_loaded_without_an_approved_baseline(conn):
    d = golden_inputs()
    d["process_baselines"] = [b for b in d["process_baselines"] if b["baseline_id"] != "pb-101"]
    out = load(conn, d)
    assert [w["code"] for w in out["warnings"]] == ["BASELINE_NOT_LOADED"]
    assert conn.execute("SELECT baseline_version FROM initiatives WHERE initiative_id = 'init-001'").fetchone()["baseline_version"] is None


@pytest.mark.parametrize("table,where", sorted(APPEND_ONLY.items()))
def test_append_only_tables_refuse_update_delete_and_truncate(golden, table, where):
    col = golden.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position LIMIT 1").fetchone()["column_name"]
    before = table_digest(golden, [table])
    fails(golden, f"UPDATE {table} SET {col} = {col} WHERE {where}", contains="append-only")
    fails(golden, f"DELETE FROM {table} WHERE {where}", contains="append-only")
    fails(golden, f"TRUNCATE {table} CASCADE", contains="append-only")
    assert table_digest(golden, [table]) == before


def test_audit_results_and_rejections_are_append_only_too(conn):
    conn.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id) VALUES ('e', 't', 'i', 'a', 'x')")
    conn.execute("INSERT INTO command_results VALUES ('k', 'h', 'a', 'admin', 'c', 's', '{}')")
    conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row) VALUES ('b', 'e', 'i', 'C', '{}')")
    for t in ("audit_events", "command_results", "rejected_records"):
        fails(conn, f"DELETE FROM {t}", contains="append-only")
    fails(conn, "UPDATE audit_events SET action = 'x'", contains="append-only")
    fails(conn, "INSERT INTO command_results VALUES ('k2', 'h', 'a', 'root', 'c', 's', '{}')", contains="command_results_role_ck")


def test_the_forecast_overwrite_is_refused_by_the_database_with_its_rule(golden):
    fails(golden, "UPDATE forecast_versions SET amount = 1 WHERE forecast_id = 'f-101-1-1'", contains="FORECAST_OVERWRITE")
    fails(golden, "INSERT INTO forecast_versions (forecast_id, initiative_id, version_number, period_index, amount, reason, created_at) "
                  "VALUES ('f-x', 'init-001', 1, 1, 1, 'again', now())", contains="forecast_versions_uq")


def test_an_approved_baseline_is_frozen_and_only_approvals_name_it(golden):
    fails(golden, "UPDATE process_baselines SET volume = 1 WHERE baseline_id = 'pb-101'", contains="BASELINE_FROZEN")
    fails(golden, "INSERT INTO process_baselines (baseline_id, initiative_id, baseline_version, volume, minutes_per_case, error_rate, evidence_ref, measured_at) "
                  "VALUES ('pb-x', 'init-001', 'v1', 1, 1, 0, 'e', now())", contains="process_baselines_version_uq")
    fails(golden, "UPDATE initiatives SET baseline_version = 'v2', version = version + 1 WHERE initiative_id = 'init-002'", contains="initiatives_approved_baseline_fk")   # v2 exists, but was never approved
    fails(golden, "UPDATE initiatives SET baseline_version = NULL, version = version + 1 WHERE initiative_id = 'init-001'", contains="BASELINE_FROZEN")
    with golden.transaction():                 # approve v2 properly: an approval row and the pointer, in one transaction
        golden.execute("INSERT INTO baseline_approvals VALUES ('appr-x', 'init-002', 'v2', 'sponsor', now(), 'restated')")
        golden.execute("UPDATE initiatives SET baseline_version = 'v2', version = version + 1 WHERE initiative_id = 'init-002'")
    assert count(golden, "baseline_approvals") == 3 and golden.execute("SELECT baseline_version, version FROM initiatives WHERE initiative_id = 'init-002'").fetchone() == {"baseline_version": "v2", "version": 2}
    fails(golden, "INSERT INTO baseline_approvals VALUES ('appr-y', 'init-003', 'v9', 'sponsor', now(), NULL)", contains="baseline_approvals_baseline_fk")        # no such baseline row


def test_initiatives_keep_identity_bump_version_by_one_and_are_never_deleted(golden):
    fails(golden, "UPDATE initiatives SET title = 'renamed', version = version + 1 WHERE initiative_id = 'init-001'", contains="INITIATIVE_IMMUTABLE")
    fails(golden, "UPDATE initiatives SET deployment_period = 0, version = version + 1 WHERE initiative_id = 'init-001'", contains="INITIATIVE_IMMUTABLE")
    fails(golden, "UPDATE initiatives SET status = 'closed' WHERE initiative_id = 'init-001'", contains="STALE_VERSION")
    fails(golden, "UPDATE initiatives SET status = 'funded', version = version + 1 WHERE initiative_id = 'init-001'", contains="initiatives_status_ck")
    fails(golden, "DELETE FROM initiatives WHERE initiative_id = 'init-003'", contains="INITIATIVE_IMMUTABLE")
    golden.execute("UPDATE initiatives SET status = 'adopted', requested_start_period = 1, version = version + 1 WHERE initiative_id = 'init-001'")
    assert golden.execute("SELECT status, version FROM initiatives WHERE initiative_id = 'init-001'").fetchone() == {"status": "adopted", "version": 2}


def test_a_scenario_never_changes_except_draft_to_proposed_once_and_never_to_funded(golden):
    fails(golden, "UPDATE scenario_versions SET discount_rate = 0.05", contains="SCENARIO_IMMUTABLE")
    fails(golden, "UPDATE scenario_versions SET horizon_periods = 5", contains="SCENARIO_IMMUTABLE")
    fails(golden, "UPDATE scenario_versions SET status = 'funded'", contains="scenarios_ck")
    fails(golden, "UPDATE scenario_versions SET status = 'proposed'", contains="scenarios_ck")            # a proposal records when
    fails(golden, "DELETE FROM scenario_versions", contains="SCENARIO_IMMUTABLE")
    golden.execute("UPDATE scenario_versions SET status = 'proposed', proposed_at = now(), proposed_by = 'sponsor', comparison = '{}'::jsonb")
    fails(golden, "UPDATE scenario_versions SET residual_explanation = 'edited later'", contains="SCENARIO_IMMUTABLE")
    fails(golden, "UPDATE scenario_versions SET status = 'draft', proposed_at = NULL", contains="SCENARIO_IMMUTABLE")


def test_row_checks_money_proportions_periods_units_and_one_time_costs(golden):
    def cost(cid, **kw):
        base = dict(cost_id=cid, cost_key="k-" + cid, cost_type="one_time", cost_basis="planned", amount="1.00", period_index=0, start_period=None, end_period=None)
        base.update(kw)
        return ("INSERT INTO cost_items (cost_id, initiative_id, cost_key, cost_type, cost_basis, amount, period_index, start_period, end_period) "
                "VALUES (%s, 'init-001', %s, %s, %s, %s, %s, %s, %s)", (base["cost_id"], base["cost_key"], base["cost_type"], base["cost_basis"], base["amount"], base["period_index"],
                                                                      base["start_period"], base["end_period"]))
    for kw, rule in [({"amount": "-1"}, "cost_items_ck"), ({"period_index": None}, "cost_items_ck"), ({"start_period": 1, "end_period": 2}, "cost_items_ck"),
                     ({"cost_type": "recurring", "period_index": 0, "start_period": 1, "end_period": 3}, "cost_items_ck"),
                     ({"cost_type": "recurring", "period_index": None, "start_period": 3, "end_period": 3}, "cost_items_ck"), ({"cost_type": "weekly"}, "cost_items_ck"),
                     ({"cost_key": "ck-101-licence"}, "cost_items_one_time_uq")]:
        sql, p = cost("c-new", **kw)
        fails(golden, sql, *p, contains=rule)
    fails(golden, "INSERT INTO risk_items VALUES ('r-x', 'init-001', 1.5, 1, 'm')", contains="risk_ck")
    fails(golden, "INSERT INTO benefit_items (benefit_id, initiative_id, benefit_type, amount, period_index, starts_period, unit) VALUES ('b-x', 'init-001', 'capacity', 1, 1, 1, 'USD')",
          contains="benefit_items_ck")
    fails(golden, "INSERT INTO benefit_items (benefit_id, initiative_id, benefit_type, amount, period_index, starts_period, unit) VALUES ('b-y', 'init-001', 'cash', 1, 0, 1, 'USD')",
          contains="benefit_items_ck")
    fails(golden, "INSERT INTO adoption_observations (observation_id, initiative_id, eligible_count, adopted_count, observed_at, eligibility_rule_version) "
                  "VALUES ('o', 'init-001', 5, 6, now(), 'elig-v1')", contains="adoption_ck")
    fails(golden, "INSERT INTO readiness_assessments (assessment_id, group_id, dimension, score, weight, assessed_at) VALUES ('r', 'grp-001', 'awareness', 6, 1, now())", contains="readiness_ck")
    fails(golden, "INSERT INTO readiness_assessments (assessment_id, group_id, dimension, score, weight, assessed_at) VALUES ('r', 'grp-001', 'mood', 3, 1, now())", contains="readiness_ck")
    fails(golden, "INSERT INTO dependencies VALUES ('d-self', 'init-001', 'init-001', 'finish_to_start', 0)", contains="dependencies_self_ck")
    fails(golden, "INSERT INTO dependencies VALUES ('d-dup', 'init-002', 'init-001', 'finish_to_start', 5)", contains="dependencies_pair_uq")
    with pytest.raises(psycopg.errors.DataError):                       # more than 20 digits does not fit NUMERIC(20,6)
        with golden.transaction():
            golden.execute("INSERT INTO resources VALUES ('res-big', 'x', 123456789012345678901, 'FTE')")


def test_assumption_versions_are_unique_per_initiative_name_and_number_even_without_an_initiative(golden):
    fails(golden, "INSERT INTO assumption_versions (assumption_id, initiative_id, name, version_number, value, rationale, author_id, created_at) "
                  "VALUES ('a-x', 'init-001', 'target_minutes_per_case', 1, '6', 'r', 'u', now())", contains="assumption_versions_version_uq")
    golden.execute("INSERT INTO assumption_versions (assumption_id, initiative_id, name, version_number, value, rationale, author_id, created_at) "
                   "VALUES ('c1', NULL, 'monthly_rate_conversion', 1, '0.007974', 'r', 'u', now())")
    fails(golden, "INSERT INTO assumption_versions (assumption_id, initiative_id, name, version_number, value, rationale, author_id, created_at) "
                  "VALUES ('c2', NULL, 'monthly_rate_conversion', 1, '0.008', 'r', 'u', now())", contains="assumption_versions_version_uq")
    fails(golden, "INSERT INTO assumption_versions (assumption_id, initiative_id, name, version_number, value, rationale, author_id, created_at) "
                  "VALUES ('c3', NULL, 'x', 1, 'abc', 'r', 'u', now())", contains="assumptions_ck")


def test_helper_functions(conn):
    row = conn.execute("SELECT cw_dec(600::numeric(20,6)) AS a, cw_dec(0.125000::numeric(20,6)) AS b, cw_dec(-3::numeric) AS c, cw_iso('2028-03-31 00:00:00+00'::timestamptz) AS d, "
                       "cw_iso('2028-03-31 00:00:00.5+00'::timestamptz) AS e, cw_dec(NULL) AS f").fetchone()
    assert row == {"a": "600.00", "b": "0.125", "c": "-3.00", "d": "2028-03-31T00:00:00Z", "e": "2028-03-31T00:00:00.5Z", "f": None}


# ------------------------------------------------------------------------------------------------------------------------------ review 9
def test_the_database_refuses_a_period_start_over_the_28th_blank_evidence_and_a_draft_with_a_snapshot(golden):
    fails(golden, "UPDATE dataset_config SET period_start = '2026-01-31'", contains="dataset_config_day_ck")
    fails(golden, "INSERT INTO benefit_items (benefit_id, initiative_id, benefit_type, amount, period_index, starts_period, unit, evidence_ref) "
                  "VALUES ('b-x', 'init-001', 'avoided_cost', 1, 2, 1, 'USD', E'  \\t ')", contains="benefit_items_evidence_ck")
    fails(golden, "INSERT INTO assumption_versions (assumption_id, initiative_id, name, version_number, value, rationale, author_id, staffing_change_evidence_ref, created_at) "
                  "VALUES ('a-x', 'init-001', 'capacity_hourly_rate', 9, '1', 'r', 'a', '   ', now())", contains="assumptions_evidence_ck")
    fails(golden, "INSERT INTO benefit_observations (benefit_observation_id, benefit_id, measured_value, evidence_ref, observed_at) VALUES ('bo-x', 'b-101', 1, '  ', now())",
          contains="benefit_obs_evidence_ck")
    fails(golden, "UPDATE scenario_versions SET snapshot_hash = repeat('a', 64) WHERE scenario_id = 'scn-001'", contains="scenarios_snapshot_ck")


def test_the_seeder_refuses_a_dataset_whose_period_start_has_a_day_over_28(conn):
    from changeworks import DomainError
    d = golden_inputs()
    d["period_start"] = "2026-01-31"
    with pytest.raises(DomainError) as e:
        load(conn, d)
    assert e.value.code == "PERIOD_START_INVALID" and count(conn, "initiatives") == 0


def test_migration_0003_seals_scenarios_that_exist_already(db_url):
    """An upgrade from the schema of 0001 and 0002: the scenarios already stored are sealed at the size they have, and the new rules are in force afterwards."""
    with psycopg.connect(db_url) as c:
        migrate.reset(c)
        for name in FILES[:2]:
            c.execute((migrate.MIGRATIONS_DIR / name).read_text())
        c.execute("INSERT INTO dataset_config VALUES (1, 'annual', '2026-01-01', NULL)")
        c.execute("INSERT INTO initiatives (initiative_id, title, sponsor_id, status, requested_start_period, duration_periods, deployment_period, eligibility_rule_version) "
                  "VALUES ('i-1', 't', 's', 'candidate', 0, 1, 1, 'elig-v1')")
        c.execute("INSERT INTO scenario_versions (scenario_id, baseline_version, discount_rate, rate_basis, horizon_periods, status, created_at) VALUES ('s-1', 'v1', 0.1, 'annual', 3, 'draft', now())")
        c.execute("INSERT INTO scenario_initiatives VALUES ('s-1', 'i-1')")
    with psycopg.connect(db_url) as c:
        c.execute((migrate.MIGRATIONS_DIR / FILES[2]).read_text())
        assert c.execute("SELECT initiatives_expected, pins_expected FROM scenario_versions").fetchone() == (1, 0)
        with pytest.raises(psycopg.errors.IntegrityError, match="SCENARIO_IMMUTABLE"):
            c.execute("INSERT INTO scenario_pins SELECT 's-1', 'nope'")
