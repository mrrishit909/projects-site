"""Migrations are idempotent and the database enforces the append-only, uniqueness, ordering and verification rules."""
import psycopg
import pytest

from data import migrate, seed

from support_db import conn, count, db_url, golden_inputs, load  # noqa: F401

FILES = ["0001_schema.sql", "0002_constraints.sql"]
TABLES = ["owners", "datasets", "fields", "dataset_rows", "quality_rules", "rule_weight_versions", "checklist_versions", "ledger_config", "rule_runs", "issues",
          "issue_events", "lineage_edges", "metric_versions", "definition_changes", "customer_records", "match_candidates", "merge_decisions", "rejected_records",
          "audit_events", "command_results", "dataset_versions", "tl_timezones"]
APPEND_ONLY = {"dataset_rows": "dataset_id = 'ds-orders'", "rule_runs": "rule_run_id = 'rr-001'", "rule_weight_versions": "weight_version = 'w1'",
               "checklist_versions": "true", "metric_versions": "metric_version_id = 'mv-rev-1'", "definition_changes": "true", "customer_records": "record_id = 'rec-001'",
               "match_candidates": "candidate_id = 'cand-001'", "merge_decisions": "merge_id = 'md-1'", "lineage_edges": "edge_id = 'ed-1'",
               "issue_events": "event_id = 'ie-iss-001-0'"}


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
        funcs = c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname LIKE 'tl\\_%'").fetchone()[0]
    assert (left, funcs) == (0, 0)


def test_every_table_exists_and_instants_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at' OR column_name = 'valid_from') AND data_type NOT IN ('timestamp with time zone', 'ARRAY')").fetchall()
    assert bad == []


def test_no_float_column_anywhere_and_scores_are_exact_numeric(conn):
    rows = conn.execute("SELECT table_name, column_name, data_type, numeric_scale FROM information_schema.columns WHERE table_schema = 'public' "
                        "AND data_type IN ('numeric', 'double precision', 'real')").fetchall()
    assert {(r["table_name"], r["column_name"]): (r["data_type"], r["numeric_scale"]) for r in rows} == {("match_candidates", "score"): ("numeric", 6)}


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate.apply_migrations(c)


def test_seed_is_idempotent_and_names_its_dataset_version(conn):
    first = load(conn, golden_inputs(), dataset_version="ds-golden-1")
    assert first["dataset_version"] == "ds-golden-1" and first["inserted"]["dataset_rows"] == 140 and first["skipped"] == 0
    again = load(conn, golden_inputs(), dataset_version="ds-golden-1")
    assert sum(again["inserted"].values()) == 0 and count(conn, "dataset_versions") == 1 and count(conn, "rule_runs") == 13 and count(conn, "issue_events") == 16
    default = seed.seed(conn, golden_inputs())
    assert default["dataset_version"] == f"ds-{default['dataset_hash'][:12]}" and count(conn, "dataset_versions") == 2
    assert conn.execute("SELECT as_of FROM dataset_versions WHERE dataset_version = 'ds-golden-1'").fetchone()["as_of"].isoformat() == "2026-10-05T00:00:00+00:00"


def test_the_seed_never_loads_the_synthetic_truth(conn):
    load(conn, golden_inputs(), truth=False)
    tables = [r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()]
    assert "verification_truth" in tables and count(conn, "verification_truth") == 0                 # the table exists for tests; the seeder left it empty
    cols = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND (column_name LIKE '%truth%' OR column_name LIKE '%true_entity%') "
                        "AND table_name <> 'verification_truth'").fetchall()
    assert cols == []                                                                                # no entity table carries truth


def test_the_directory_loader_reads_one_file_per_entity(conn, tmp_path):
    import json
    inputs = golden_inputs()
    for e in ("owners", "datasets", "fields", "quality_rules", "rule_runs", "issues", "lineage_edges", "metric_versions", "definition_changes", "customer_records",
              "match_candidates", "merge_decisions"):
        (tmp_path / f"{e}.json").write_text(json.dumps(inputs[e]))
    (tmp_path / "dataset_rows.json").write_text(json.dumps(inputs["dataset_rows"]))
    (tmp_path / "config.json").write_text(json.dumps({k: inputs[k] for k in ("contract_version", "as_of", "whitespace_policy", "weight_version", "weight_versions",
                                                                           "checklist_version", "checklist_versions", "probes")}))
    out = load(conn, seed.load_inputs(tmp_path), truth=False)
    assert out["inserted"]["owners"] == 5 and out["inserted"]["dataset_rows"] == 140 and "synthetic_truth" not in seed.load_inputs(tmp_path)


@pytest.mark.parametrize("table,where", sorted(APPEND_ONLY.items()))
def test_append_only_tables_refuse_update_delete_and_truncate(golden, table, where):
    for sql in (f"UPDATE {table} SET {'weights' if table == 'rule_weight_versions' else {'checklist_versions': 'items', 'definition_changes': 'reason', 'issue_events': 'event_type', 'dataset_rows': 'row_id'}.get(table, list(golden.execute(f'SELECT * FROM {table} LIMIT 1').fetchone())[0])} = {table}.{'weights' if table == 'rule_weight_versions' else {'checklist_versions': 'items', 'definition_changes': 'reason', 'issue_events': 'event_type', 'dataset_rows': 'row_id'}.get(table, list(golden.execute(f'SELECT * FROM {table} LIMIT 1').fetchone())[0])} WHERE {where}",
                f"DELETE FROM {table} WHERE {where}", f"TRUNCATE {table} CASCADE"):
        with pytest.raises(psycopg.errors.IntegrityError, match="append-only"):
            golden.execute(sql)                                                                      # table and where are test constants


def test_audit_results_and_rejections_are_append_only_too(conn):
    conn.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id) VALUES ('e1', 't', 'i', 'a', 'x')")
    conn.execute("INSERT INTO command_results VALUES ('k', 'h', 'a', 'admin', 'c', 's', '{}')")
    for sql in ("UPDATE audit_events SET action = 'b'", "DELETE FROM audit_events", "UPDATE command_results SET status = 'x'", "DELETE FROM command_results"):
        with pytest.raises(psycopg.errors.IntegrityError):
            conn.execute(sql)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO command_results VALUES ('k2', 'h', 'a', 'root', 'c', 's', '{}')")


def test_rules_never_change_in_place_and_a_disabled_rule_stays_disabled(golden):
    for sql in ("UPDATE quality_rules SET severity = 'low' WHERE rule_id = 'r-cust-key-unique'", "UPDATE quality_rules SET definition = '{}'::jsonb WHERE rule_id = 'r-cust-key-unique'",
                "UPDATE quality_rules SET version_number = 9 WHERE rule_id = 'r-cust-key-unique'", "DELETE FROM quality_rules WHERE rule_id = 'r-cust-key-unique'",
                "UPDATE quality_rules SET status = 'active', disabled_at = NULL, disabled_reason = NULL WHERE rule_id = 'r-ord-amount-range'",
                "UPDATE quality_rules SET disabled_reason = 'changed' WHERE rule_id = 'r-ord-amount-range'"):
        with pytest.raises(psycopg.errors.IntegrityError):
            golden.execute(sql)
    with pytest.raises(psycopg.errors.CheckViolation):                                              # disabling needs a reason and a date, and only then
        golden.execute("UPDATE quality_rules SET status = 'disabled', disabled_at = now(), disabled_reason = ' ' WHERE rule_id = 'r-cust-fresh'")
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("UPDATE quality_rules SET status = 'disabled' WHERE rule_id = 'r-cust-fresh'")
    golden.execute("UPDATE quality_rules SET status = 'disabled', disabled_at = now(), disabled_reason = 'ok' WHERE rule_id = 'r-cust-fresh'")


def test_datasets_need_an_owner_a_classification_and_a_valid_schedule(golden):
    base = ("ds-t", "T", "s", "own-01", "internal", "2026-10-01T00:00:00Z", False, None, None, None, None, "x")
    ins = "INSERT INTO datasets VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    golden.execute(ins, base)
    for patch, exc in (({3: None}, psycopg.errors.NotNullViolation), ({3: "ghost"}, psycopg.errors.ForeignKeyViolation), ({4: "  "}, psycopg.errors.CheckViolation),
                       ({6: True}, psycopg.errors.CheckViolation), ({6: True, 7: "Mars/Base", 8: "06:00", 9: 5}, psycopg.errors.CheckViolation),
                       ({6: True, 7: "UTC", 8: "24:00", 9: 5}, psycopg.errors.CheckViolation), ({6: True, 7: "UTC", 8: "06:00", 9: 1440}, psycopg.errors.CheckViolation)):
        row = list(base)
        row[0] = f"ds-{len(patch)}-{list(patch)[0]}"
        for k, v in patch.items():
            row[k] = v
        with pytest.raises(exc):
            golden.execute(ins, row)
    row = list(base)
    row[0], row[6], row[7], row[8], row[9] = "ds-ok", True, "Asia/Kolkata", "05:30", 45
    golden.execute(ins, row)


def test_candidates_need_canonical_order_a_unique_pair_a_score_features_and_an_explanation(golden):
    ins = "INSERT INTO match_candidates VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())"
    ok = ("c-new", "rec-003", "rec-005", "0.5", '{"f": "1"}', "x", None, "p")
    for patch, exc in (({1: "rec-005", 2: "rec-003"}, psycopg.errors.CheckViolation), ({1: "rec-003", 2: "rec-003"}, psycopg.errors.CheckViolation),
                       ({3: "1.5"}, psycopg.errors.CheckViolation), ({3: "-0.1"}, psycopg.errors.CheckViolation), ({4: "{}"}, psycopg.errors.CheckViolation),
                       ({5: " "}, psycopg.errors.CheckViolation), ({2: "rec-99"}, psycopg.errors.ForeignKeyViolation), ({1: "rec-001", 2: "rec-002"}, psycopg.errors.UniqueViolation)):
        row = list(ok)
        row[0] = f"c-{list(patch)[0]}-{len(patch)}"
        for k, v in patch.items():
            row[k] = v
        with pytest.raises(exc):
            golden.execute(ins, row)
    golden.execute(ins, ok)


def test_the_canonical_order_is_code_point_order_not_the_locale(golden):
    golden.execute("INSERT INTO customer_records VALUES ('B1', 's', '1', 'n', 'a'), ('a1', 's', '2', 'n', 'a')")
    golden.execute("INSERT INTO match_candidates VALUES ('c-case', 'B1', 'a1', 0.5, '{\"f\": 1}', 'x', NULL, 'p', now())")        # 'B' < 'a' in code-point order
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("INSERT INTO match_candidates VALUES ('c-case2', 'a1', 'B1', 0.5, '{\"f\": 1}', 'x', NULL, 'p', now())")


def test_merge_decisions_reviewer_reversal_and_uniqueness_rules(golden):
    ins = "INSERT INTO merge_decisions VALUES (%s,%s,%s,%s,now(),%s,%s)"
    with pytest.raises(psycopg.errors.IntegrityError, match="REVIEWER_IS_PROPOSER"):
        golden.execute(ins, ("m-x", "cand-005", "own-01", "approve", None, None))                   # own-01 proposed it
    with pytest.raises(psycopg.errors.UniqueViolation):
        golden.execute(ins, ("m-y", "cand-001", "own-03", "reject", None, None))                    # cand-001 already has md-1
    with pytest.raises(psycopg.errors.IntegrityError):
        golden.execute(ins, ("m-z", "cand-005", "own-02", "reverse", None, "r"))                    # a reversal names its approval
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute(ins, ("m-z", "cand-001", "own-02", "reverse", "md-1", " "))                  # ... and gives a reason
    with pytest.raises(psycopg.errors.IntegrityError, match="INVALID_REVERSAL"):
        golden.execute(ins, ("m-z", "cand-005", "own-02", "reverse", "md-1", "r"))                  # md-1 is another candidate's approval
    with pytest.raises(psycopg.errors.IntegrityError, match="INVALID_REVERSAL"):
        golden.execute(ins, ("m-z", "cand-004", "own-02", "reverse", "md-4", "r"))                  # md-4 is a rejection
    with pytest.raises(psycopg.errors.UniqueViolation):
        golden.execute(ins, ("m-z", "cand-003", "own-02", "reverse", "md-3", "again"))              # md-3 is already reversed by md-5
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute(ins, ("m-w", "cand-005", "own-02", "maybe", None, None))
    golden.execute(ins, ("m-ok", "cand-005", "own-02", "approve", None, None))


def test_the_database_refuses_resolved_without_a_successful_rerun_of_the_same_rule_version(golden):
    golden.execute("INSERT INTO rule_runs (rule_run_id, rule_id, rule_version, weight_version, kind, run_at, eligible_count, failure_count, rerun_for_issue) VALUES "
                   "('rr-bad-fail', 'r-cust-key-unique', 1, 'w2', 'rerun', '2026-10-06T00:00:00Z', 2, 1, 'iss-006'), "
                   "('rr-bad-ver', 'r-cust-key-unique', 2, 'w2', 'rerun', '2026-10-06T00:00:00Z', 2, 0, 'iss-006'), "
                   "('rr-bad-iss', 'r-cust-key-unique', 1, 'w2', 'rerun', '2026-10-06T00:00:00Z', 2, 0, 'iss-001'), "
                   "('rr-bad-early', 'r-cust-key-unique', 1, 'w2', 'rerun', '2026-09-29T00:00:00Z', 2, 0, 'iss-006'), "
                   "('rr-good', 'r-cust-key-unique', 1, 'w2', 'rerun', '2026-10-06T00:00:00Z', 2, 0, 'iss-006')")
    for run in ("rr-bad-fail", "rr-bad-ver", "rr-bad-iss", "rr-bad-early", "rr-003"):
        with pytest.raises(psycopg.errors.IntegrityError, match="VERIFICATION_RUN_INVALID"):
            golden.execute("UPDATE issues SET verification_run_id = %s WHERE issue_id = 'iss-006'", (run,))
    golden.execute("UPDATE issues SET verification_run_id = 'rr-good', status = 'closed', closed_at = now() WHERE issue_id = 'iss-006'")
    with pytest.raises(psycopg.errors.IntegrityError, match="VERIFICATION_IMMUTABLE"):             # a verification is not swapped without a reopen
        golden.execute("UPDATE issues SET verification_run_id = NULL WHERE issue_id = 'iss-006'")


def test_issues_keep_their_first_detection_and_only_ever_add_reopen_cycles(golden):
    for sql in ("UPDATE issues SET detected_at = now() WHERE issue_id = 'iss-005'", "UPDATE issues SET rule_run_id = 'rr-001' WHERE issue_id = 'iss-005'",
                "UPDATE issues SET severity = 'low' WHERE issue_id = 'iss-005'", "UPDATE issues SET reopened_at = '{}' WHERE issue_id = 'iss-005'"):
        with pytest.raises(psycopg.errors.IntegrityError):
            golden.execute(sql)
    golden.execute("UPDATE issues SET reopened_at = array_append(reopened_at, now()) WHERE issue_id = 'iss-005'")
    assert golden.execute("SELECT cardinality(reopened_at) AS n FROM issues WHERE issue_id = 'iss-005'").fetchone()["n"] == 2
    with pytest.raises(psycopg.errors.CheckViolation):
        golden.execute("UPDATE issues SET status = 'closed', closed_at = NULL WHERE issue_id = 'iss-006'")
    with pytest.raises(psycopg.errors.UniqueViolation):                                             # one issue per run
        golden.execute("INSERT INTO issues (issue_id, rule_run_id, severity, owner_id, status, detected_at) VALUES ('dup', 'rr-003', 'critical', 'own-01', 'open', now())")


def test_runs_have_consistent_counts_kinds_and_known_weight_versions(golden):
    ins = "INSERT INTO rule_runs (rule_run_id, rule_id, rule_version, weight_version, kind, run_at, eligible_count, failure_count, rerun_for_issue) VALUES (%s,%s,%s,%s,%s,now(),%s,%s,%s)"
    for row, exc in ((("x1", "r-cust-fresh", 1, "w2", "scheduled", 1, 2, None), psycopg.errors.CheckViolation),
                     (("x2", "r-cust-fresh", 1, "w2", "scheduled", 1, 0, "iss-001"), psycopg.errors.CheckViolation),
                     (("x3", "r-cust-fresh", 1, "w2", "rerun", 1, 0, None), psycopg.errors.CheckViolation),
                     (("x4", "r-cust-fresh", 1, "w2", "other", 1, 0, None), psycopg.errors.CheckViolation),
                     (("x5", "r-cust-fresh", 1, "w9", "scheduled", 1, 0, None), psycopg.errors.ForeignKeyViolation),
                     (("x6", "r-nope", 1, "w2", "scheduled", 1, 0, None), psycopg.errors.ForeignKeyViolation),
                     (("x7", "r-cust-fresh", 1, "w2", "scheduled", -1, 0, None), psycopg.errors.CheckViolation)):
        with pytest.raises(exc):
            golden.execute(ins, row)


def test_helper_functions(conn):
    r = conn.execute("SELECT tl_iso('2026-10-04T10:20:00+00'::timestamptz) AS a, tl_iso('2026-10-04T10:20:00.5+02'::timestamptz) AS b, tl_iso(NULL) AS c, "
                     "tl_cell('\"x\"'::jsonb) AS d, tl_cell('null'::jsonb) AS e, tl_cell(NULL) AS f, tl_cell('42'::jsonb) AS g, tl_cell('true'::jsonb) AS h, "
                     "tl_valid_tz('Europe/London') AS i, tl_valid_tz('Mars/Base') AS j").fetchone()
    assert (r["a"], r["b"], r["c"], r["d"], r["e"], r["f"], r["g"], r["h"], r["i"], r["j"]) == (
        "2026-10-04T10:20:00Z", "2026-10-04T08:20:00.500000Z", None, "x", None, None, "42", "true", True, False)
