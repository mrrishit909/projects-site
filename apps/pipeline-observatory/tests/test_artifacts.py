"""Artifact package checks (P08-ART-01..10): the SQL analysis results, the analyst workbook, the BI exports, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that every result cell of the formula sheets is a live formula, (2) reads
the values LibreOffice cached in the delivered file and compares them with the Python domain RECOMPUTED HERE (not with the pasted reference column), (3) recalculates
copies with LibreOffice headless (as delivered, and with the switches flipped) and compares them with the domain, (4) checks that the stored analysis results equal the
plain-Python recomputation over web/public/data (no database), through data/sql/analysis/python_side.py, which shares no code with the SQL or the domain, (5) recomputes the
BI measures from the CSV exports, (6) checks that each document quotes the stored results, the ledgers and the public case study, and (7) checks CHECKSUMS.txt and the
release-package table. With ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts08_*; the test prepares them with prepare_snapshot.py) it
also re-runs the SQL files and compares their rows with the stored results; without them that test is skipped with a printed reason. The tests that need LibreOffice are skipped,
with a reason, where `soffice` is missing (the CI workflow installs LibreOffice Calc and the scratch databases, so none skips there). Excel and Power BI are never run. This file
never touches the shared pipeline_observatory database.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "data" / "sql" / "analysis"
DOCS = ROOT / "docs"
ART = ROOT / "artifacts"
for _p in (ROOT / "domain", ROOT, SQL_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

openpyxl = pytest.importorskip("openpyxl")

XLSX = ART / "pipeline-observatory-analyst-workbook.xlsx"
RES = json.loads((ART / "analysis-results.json").read_text()) if (ART / "analysis-results.json").exists() else {}
CODE_REVISION = "ed7eb5a"
CODE_REVISION_FULL = "ed7eb5a8b403db8dcb158c6a3399ee126dc29450"
DATASET_HASH = "0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab"
SCRATCH = "artifacts08_"


def _case_study_text() -> str | None:
    for p in (ROOT.parents[1] / "pipeline-observatory" / "project.json", ROOT.parents[3] / "pipeline-observatory" / "project.json"):
        if p.exists() and p.read_text().strip():
            return p.read_text()
    return None


_CASE = _case_study_text()
PROJECT = json.loads(_CASE) if _CASE else None            # the public case study lives on unified-portfolio: a copy at the repo root (CI) or the main checkout

pytestmark = pytest.mark.skipif(not XLSX.exists() or not RES, reason="artifacts not built (data/sql/analysis/run_all.py, artifacts/build_workbook.py)")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ps():
    import python_side
    return python_side


@pytest.fixture(scope="module")
def P(ps):
    return ps.results()


@pytest.fixture(scope="module")
def wb():
    return openpyxl.load_workbook(XLSX)


@pytest.fixture(scope="module")
def wbv():
    return openpyxl.load_workbook(XLSX, data_only=True)


@pytest.fixture(scope="module")
def bw():
    return _load("po_build_workbook", ART / "build_workbook.py")


@pytest.fixture(scope="module")
def ra():
    return _load("po_run_all", SQL_DIR / "run_all.py")


@pytest.fixture(scope="module")
def prep():
    return _load("po_prepare", SQL_DIR / "prepare_snapshot.py")


@pytest.fixture(scope="module")
def world(prep):
    """The Python domain over the published files, run here (it takes about twenty seconds)."""
    from pipeline_observatory import run_pipeline
    inputs, manifest = prep.snapshot_inputs()
    return {"inputs": inputs, "manifest": manifest, "dom": run_pipeline(inputs).metrics}


def row_of(key: str, **where) -> dict:
    return next(r for r in RES[key] if all(str(r[k]) == str(v) for k, v in where.items()))


def read(name: str) -> str:
    return (DOCS / name).read_text()


def sha_of(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


NUMBERED = ["01", "02", "03", "04", "05", "06", "07", "08", "10"]
DOC_NAMES = ["business-case.md", "requirements.md", "data-dictionary.md", "erd.md", "sql-analysis.md", "workbook.md", "bi-package.md", "executive-memo.md", "uat-evidence.md",
             "technical-case-study.md", "release-package.md", "resume-bullets.md"]


# ---- stored analysis results ---------------------------------------------------------------------------------------------------------------

def test_analysis_results_reconcile_and_cover_every_investigation(P):
    assert RES["reconciliation"] and all(r["equal"] is True for r in RES["reconciliation"])
    assert len(RES["reconciliation"]) >= 150
    meta = RES["meta"][0]
    assert meta["dataset_hash"] == DATASET_HASH and meta["code_revision"] == CODE_REVISION
    assert meta["reconciliation_rows"] == len(RES["reconciliation"]) == meta["reconciliation_equal"]
    for key in P:
        assert RES[key], key
    numbered = sorted(p.name for p in SQL_DIR.glob("[01][0-9]_*.sql") if not p.name.startswith(("00_", "09_")))
    assert len(numbered) == 9 and [n[:2] for n in numbered] == NUMBERED                       # nine numbered investigations on the snapshot plus the golden one: ten, at least the eight required
    assert {k.split("__")[0][:2] for k in P} == set(NUMBERED)
    golden = [k for k in RES if k.startswith("09_golden_known_answer__")]
    assert len(golden) == 13 and all(RES[k] for k in golden)
    assert {r["check"].split(" ")[0] for r in RES["reconciliation"]} == {"A", "B", "C", "D", "E"}
    assert meta["result_sets"] == len(P) + len(golden)
    assert RES["bi_measures"] and RES["bi_measures_headline"]


def test_golden_known_answer_in_sql_equals_expected_json_and_the_hand_figures():
    exp = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())["metrics"]
    b = {r["batch_id"]: r for r in RES["09_golden_known_answer__batches"]}
    assert [b["b-001"][k] for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")] == ["10", "8", "1", "1", "0.100000", "0.100000"]
    assert b["b-002"]["accepted_unique"] == "0" and b["b-003"]["status"] == "aborted" and b["b-003"]["received"] == "0" and b["b-003"]["written_rows"] == "10"
    rc = RES["09_golden_known_answer__replay_and_crash"][0]
    assert (rc["accepted_keys"], rc["accepted_by_the_replay"], rc["checkpoints_of_the_crashed_batch"], rc["new_keys_in_the_crashed_batch"], rc["checkpoint_version"]) == ("8", "0", "0", "0", "2")
    fr = {r["source_id"]: r for r in RES["09_golden_known_answer__freshness"]}
    assert (fr["src-orders"]["freshness_seconds"], fr["src-orders"]["ingestion_age_seconds"]) == ("52200", "42900")
    assert exp["freshness"]["src-orders"]["freshness_seconds"] == 52200 and exp["freshness"]["src-orders"]["ingestion_age_seconds"] == 42900
    cm = RES["09_golden_known_answer__completeness"][0]
    assert (cm["expected_records"], cm["accepted_records"], cm["completeness"]) == ("9", "8", "0.888889") and exp["completeness"]["src-orders"]["2026-10-04"]["value"] == "0.888889"
    runs = {r["run_id"]: r for r in RES["09_golden_known_answer__runs"]}
    assert (runs["run-001"]["task_success_rate"], runs["run-001"]["attempt_success_rate"]) == ("1.000000", "0.800000")
    assert [(r["gate_decision"], r["pointer_after"]) for r in RES["09_golden_known_answer__gate_pointer"]] == [("allowed", "pub-001"), ("blocked", "pub-001"), ("allowed", "pub-003")]
    rec = {r["publication_id"]: r for r in RES["09_golden_known_answer__reconciliation"]}
    assert (rec["pub-001"]["source_total"], rec["pub-001"]["published_total"], rec["pub-001"]["quarantined"], rec["pub-001"]["duplicates"], rec["pub-001"]["residual"]) == ("289.94", "289.97", "-30.00", "29.97", "0.00")
    assert RES["09_golden_known_answer__recovery"][0]["recovery_minutes"] == "475.0000" and RES["09_golden_known_answer__recovery"][0]["recovery_seconds"] == "28500"
    bp = RES["09_golden_known_answer__backfill_processing"][0]
    assert (bp["coverage"], bp["records_per_second"]) == ("0.666667", "0.666667")
    assert len(RES["09_golden_known_answer__late_event"]) == 1 and RES["09_golden_known_answer__late_event"][0]["source_key"] == "REF-2001"
    for r in RES["reconciliation"]:
        if r["check"].startswith("A "):
            assert r["equal"] is True


def test_stored_results_equal_the_python_side_recomputation_over_the_snapshot_files(ps, P):
    assert sorted(P) == sorted(k for k in RES if k[:2] in NUMBERED)
    for key, rows in P.items():
        assert RES[key] == ps.normalised(rows), key
    assert ps.dataset_hash() == DATASET_HASH


def test_stored_reference_figures_equal_the_domain(world):
    d, man = world["dom"], world["manifest"]
    fn = row_of("02_run_funnel_by_failure_kind__funnel")
    gates = d["quality_gate"]
    reached = [v for v in gates.values() if v["results"]]
    assert (int(fn["runs"]), int(fn["reached_gate"]), int(fn["allowed"]), int(fn["blocked_at_gate"]), int(fn["failed_before_gate"])) == (
        len(gates), len(reached), sum(v["decision"] == "allowed" for v in reached), sum(v["decision"] == "blocked" for v in reached), len(gates) - len(reached)) == (1343, 1328, 1318, 10, 15)
    ov = row_of("03_task_vs_attempt_success__overall")
    assert (ov["task_success_rate"], ov["attempt_success_rate"]) == (d["runs"]["overall"]["task_success_rate"], d["runs"]["overall"]["attempt_success_rate"]) == ("0.995311", "0.971622")
    sm = row_of("06_incidents_and_verified_recovery__summary")
    assert sm["mean_recovery_minutes"] == d["incidents"]["mean_recovery_minutes"] == man["stats"]["incidents"]["mean_recovery_minutes"] == "60.6827" and sm["verified"] == str(d["incidents"]["verified"])
    cs = row_of("07_backfill_coverage_and_refused_overlaps__coverage_summary")
    assert cs["coverage"] == d["backfills"]["overall"]["coverage"] == "0.733333" and [r["refused_request"] for r in RES["07_backfill_coverage_and_refused_overlaps__refused_overlaps"]] == d["backfills"]["refused"]
    for r in RES["04_freshness_vs_ingestion_age__ingestion_age"]:
        assert str(d["freshness"][r["source_id"]]["ingestion_age_seconds"]) == r["ingestion_age_seconds"]
    ing = row_of("01_ingestion_by_source__overall")
    mo = man["stats"]["ingestion"]["overall"]
    assert [ing[k] for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")] == [str(mo[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")]
    s3 = RES["10_sample_scope_reconciliation__rates_by_scope"][2]
    dov = d["ingestion"]["overall"]                        # the domain over the sample
    assert [s3[k] for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")] == [str(dov[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")]
    assert d["late_events"]["count"] == 141 and man["stats"]["late_events"]["count"] == 757                      # the sample and the record are different statements
    assert sum(1 for p in d["publications"]["publications"].values() if p["content_hash_ok"]) == 0 and man["stats"]["publications"]["content_hash_ok"] == 1318
    assert d["publications"]["current_publication_id"] == "pub-1343" == man["stats"]["publications"]["current_publication_id"]


def test_headline_numbers_of_the_documents_are_the_stored_ones():
    sql = read("sql-analysis.md")
    ing, o = RES["01_ingestion_by_source__by_source"], row_of("01_ingestion_by_source__overall")
    assert [o[k] for k in ("received", "accepted_unique", "duplicate", "quarantined", "deleted", "rejection_rate", "duplicate_rate")] == ["39901", "37248", "2101", "429", "123", "0.010752", "0.052655"]
    for tok in ("39,901", "37,248", "2,101", "429", "123", "0.010752", "0.052655", "446", "b-0847", "273 rows", "255 accepted, 12 duplicates, 6 quarantined"):
        assert tok in sql, tok
    assert max(ing, key=lambda r: float(r["duplicate_rate"]))["source_id"] == "src-refunds" and "0.108964" in sql
    fn = row_of("02_run_funnel_by_failure_kind__funnel")
    assert [fn[k] for k in ("runs", "reached_gate", "allowed", "blocked_at_gate", "failed_before_gate")] == ["1343", "1328", "1318", "10", "15"]
    assert "1,343 hourly runs: 1,328 reached the quality gate, 1,318 were allowed and 10 were blocked; the other 15 failed in a task before the gate ran" in sql
    kinds = {r["failure_kind"]: int(r["runs"]) for r in RES["02_run_funnel_by_failure_kind__by_failure_kind"]}
    assert kinds == {"freshness": 5, "relationships": 4, "residual": 1, "gate_infra": 3, "ingest": 3, "transform": 9}
    chk = {r["rule_name"]: r for r in RES["02_run_funnel_by_failure_kind__gate_checks"]}
    assert chk["completeness_vs_expectation"]["failed"] == "1304" and chk["completeness_vs_expectation"]["failed_share"] == "0.981928" and "0.981928" in sql
    t = row_of("03_task_vs_attempt_success__overall")
    assert [t[k] for k in ("tasks_terminal", "tasks_successful", "task_success_rate", "attempts", "attempts_successful", "attempt_success_rate", "tasks_retried", "retried_then_succeeded")] == ["5332", "5307", "0.995311", "5462", "5307", "0.971622", "115", "100"]
    fv = {r["source_id"]: r for r in RES["04_freshness_vs_ingestion_age__freshness_vs_age"]}
    assert (fv["src-refunds"]["freshness_seconds"], fv["src-refunds"]["ingestion_age_seconds"], fv["src-refunds"]["silent"], fv["src-refunds"]["over_target"]) == ("262378", "17363", "true", "false")
    assert [s for s, r in fv.items() if r["silent"] == "true"] == ["src-refunds"] and "262,378 s" in sql and "17,363 s" in sql and "4,372.9667" in sql and "289.3833" in sql
    ss = row_of("04_freshness_vs_ingestion_age__silent_source")
    assert [ss[k] for k in ("runs_since", "runs_succeeded", "runs_allowed_by_the_gate", "freshness_checks_passed", "committed_batches_since", "batches_with_no_accepted_record", "accepted_since", "duplicates_since")] == ["72", "72", "72", "72", "12", "11", "16", "156"]
    sm = row_of("05_publication_pointer_and_blocked_runs__summary")
    assert (sm["pointer"], sm["runs_that_moved_the_pointer"], sm["runs_that_left_it"], sm["publications_of_failed_or_blocked_runs"]) == ("pub-1343", "1318", "25", "0")
    assert all(r["pointer_unchanged"] == "true" and r["publication_exists"] == "false" for r in RES["05_publication_pointer_and_blocked_runs__unmoved_runs"])
    i = row_of("06_incidents_and_verified_recovery__summary")
    assert (i["incidents"], i["verified"], i["closures_consistent"], i["mean_recovery_minutes"], i["min_recovery_minutes"], i["max_recovery_minutes"]) == ("25", "25", "25", "60.6827", "50.7500", "72.4000")
    assert row_of("06_incidents_and_verified_recovery__residual_candidate")["residual"] == "-141.46" and "-141.46" in sql
    c = row_of("07_backfill_coverage_and_refused_overlaps__coverage_summary")
    assert [c[k] for k in ("accepted_requests", "requested_partitions", "verified_partitions", "coverage", "refused_requests", "refused_partitions")] == ["13", "15", "11", "0.733333", "2", "4"]
    r = row_of("08_fetch_log_retry_after__retry_summary")
    assert [r[k] for k in ("rate_limited_responses", "retries", "retries_honouring_retry_after", "retries_too_soon", "min_slack_seconds", "max_slack_seconds", "sessions_rate_limited", "source_id")] == ["49", "49", "49", "0", "0", "25", "33", "src-shipments"]
    sc = {x["scope"]: x for x in RES["10_sample_scope_reconciliation__rates_by_scope"]}
    dup = [x["duplicate_rate"] for x in RES["10_sample_scope_reconciliation__rates_by_scope"]]
    assert dup == ["0.052655", "0.040469", "0.012247"] and "0.012247" in sql and "0.040469" in sql and len(sc) == 3
    assert row_of("10_sample_scope_reconciliation__scope_total")["sample_rows"] == "2000" and row_of("10_sample_scope_reconciliation__scope_total")["world_rows"] == "40191"
    assert row_of("10_sample_scope_reconciliation__publications")["verifiable_from_the_sample"] == "0"


def test_designed_relationships_and_defects_are_present_in_the_results(world):
    man = world["manifest"]
    dr = {d["id"]: d["realised"] for d in man["designed_relationships"]}
    ss = row_of("04_freshness_vs_ingestion_age__silent_source")
    assert (int(ss["runs_since"]), int(ss["committed_batches_since"]), int(ss["accepted_since"]), int(ss["duplicates_since"])) == (dr["DR-01"]["runs_in_window"], dr["DR-01"]["committed_batches_in_window"], dr["DR-01"]["accepted_in_window"], dr["DR-01"]["duplicates_in_window"])
    d2 = row_of("05_publication_pointer_and_blocked_runs__designed_blocked_run")
    assert (d2["run_id"], d2["pointer_before"], d2["pointer_after"], d2["incident_id"], d2["recovery_run_id"]) == (dr["DR-02"]["run_id"], dr["DR-02"]["pointer_before"], dr["DR-02"]["pointer_after"], dr["DR-02"]["incident_id"], dr["DR-02"]["recovery_run_id"])
    assert row_of("06_incidents_and_verified_recovery__incidents", incident_id="inc-022")["recovery_minutes"] == dr["DR-02"]["recovery_minutes"] == "67.8833"
    rs = row_of("08_fetch_log_retry_after__retry_summary")
    assert (int(rs["retries"]), int(rs["retries_honouring_retry_after"]), int(rs["sessions_rate_limited"])) == (dr["DR-03"]["retries"], dr["DR-03"]["retries_honouring_retry_after"], dr["DR-03"]["sessions_rate_limited"])
    assert sum(dr["DR-04"]["by_cause"].values()) == dr["DR-04"]["late_events_in_all"] == 757 and dr["DR-04"]["lost"] == 0               # recorded: not recomputable
    rc = row_of("06_incidents_and_verified_recovery__residual_candidate")
    cand = dr["DR-05"]["candidates_with_nonzero_residual"][0]
    assert (rc["run_id"], rc["source_total"], rc["exclusions_total"], rc["stored_candidate_total"], rc["residual"]) == (cand["run_id"], cand["source_total"], cand["exclusions_total"], cand["published_total"], cand["residual"])
    cr = {r["aborted_batch"]: r for r in RES["01_ingestion_by_source__crash_replay"]}
    assert len(cr) == 8 and all(r["rows_classified_once"] == "true" and r["version_step"] == "1" and r["aborted_checkpoints"] == "0" for r in cr.values())
    assert (cr["b-0596"]["aborted_rows"], cr["b-0596"]["replay_batch"], cr["b-0596"]["replay_accepted"]) == ("71", "b-0597", "69")
    assert [r["refused_request"] for r in RES["07_backfill_coverage_and_refused_overlaps__refused_overlaps"]] == ["bf-006", "bf-012"]
    sq = RES["01_ingestion_by_source__schema_quarantined"]
    assert (sq[0]["batch_id"], sq[0]["status"], sq[0]["schema_changed_rows"], sq[0]["checkpoints"]) == ("b-0847", "quarantined", "17", "0") and sq[1]["batch_id"] == "b-0848"
    rv = {r["status"]: r for r in RES["08_fetch_log_retry_after__refetch_check"]}
    assert rv["refetch"]["refetch_conditions_met"] == "48" and rv["refetch"]["repeats_inside_its_session"] == "0" and rv["cursor_loop"]["repeats_inside_its_session"] == "1"
    assert row_of("08_fetch_log_retry_after__cursor_loop")["loop_fetch"] == "577"
    assert any("known gap" in r["check"] and r["equal"] is True for r in RES["reconciliation"])                       # the reference SQL does not model delete events: reconciled, not hidden


@pytest.mark.skipif(not (os.environ.get("ARTIFACTS_DATABASE_URL") and os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL")),
                    reason="ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts08_*; the test prepares them with data/sql/analysis/prepare_snapshot.py) are not set")
def test_sql_files_rerun_against_the_prepared_databases_give_the_stored_rows(ps, ra, prep):
    import psycopg
    from psycopg.rows import dict_row
    url, gurl = os.environ["ARTIFACTS_DATABASE_URL"], os.environ["ARTIFACTS_GOLDEN_DATABASE_URL"]
    for u in (url, gurl):
        assert u.rsplit("/", 1)[-1].startswith(SCRATCH)
        prep.assert_scratch(u)
    assert url != gurl
    prep.prepare(url, False)
    prep.prepare(gurl, True)
    with psycopg.connect(url, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        ra.run_script(c, SQL_DIR / "00_definitions.sql")
        for prefix in NUMBERED:
            f = next(SQL_DIR.glob(f"{prefix}_*.sql"))
            for key, rows in ra.run_file(c, f).items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key
        for name in ra.BI_FILES:
            for key, rows in ra.run_file(c, SQL_DIR / f"{name}.sql").items():
                csv_name = key.split("__")[-1] if "__" in key else key.removeprefix("bi_")
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == _csv(csv_name), csv_name
    with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        ra.run_script(c, SQL_DIR / "00_definitions.sql")
        for key, rows in ra.run_file(c, SQL_DIR / "09_golden_known_answer.sql").items():
            assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key


def test_a_database_rerun_without_the_scratch_urls_is_skipped_with_a_reason():
    marks = [m for m in test_sql_files_rerun_against_the_prepared_databases_give_the_stored_rows.pytestmark if m.name == "skipif"]
    assert marks and "ARTIFACTS_DATABASE_URL" in marks[0].kwargs["reason"] and SCRATCH in marks[0].kwargs["reason"] and "ARTIFACTS_GOLDEN_DATABASE_URL" in marks[0].kwargs["reason"]


def test_scratch_guard_refuses_a_non_scratch_database(prep):
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/pipeline_observatory")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts07_snapshot")
    prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts08_snapshot")
    with pytest.raises(SystemExit):
        prep.create_database("postgresql://u:p@127.0.0.1:5432/postgres", "pipeline_observatory")
    with pytest.raises(SystemExit):
        prep.drop_database("postgresql://u:p@127.0.0.1:5432/postgres", "pipeline_observatory")
    assert prep.SCRATCH_PREFIX == SCRATCH


def test_every_sql_file_has_its_header_and_the_numbered_files_read_only():
    files = sorted(SQL_DIR.glob("[01][0-9]_*.sql"))
    assert [f.name[:2] for f in files] == ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]
    for f in files:
        text = f.read_text()
        if f.name.startswith("00_"):
            assert text.startswith("-- P08-ART-04 setup:"), f.name
        else:
            assert re.match(rf"-- P08-ART-04 investigation {f.name[:2]}:", text), f.name
        assert "D-0" in text, f.name
        assert "SCOPE" in text or f.name.startswith("00_"), f.name                                                    # every investigation says what scope its figures have
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b", body, re.I), f.name                 # read only
        if not f.name.startswith("00_"):
            assert "CREATE" not in body, f.name
            for m in re.finditer(r"ORDER BY ([^\n)]*)", body):                            # locale-independent ordering: a text column is ordered COLLATE "C"
                for term in m.group(1).split(","):
                    t = term.strip()
                    if re.search(r"(source_id|batch_id|run_id|rule_name|reason_code|failure_kind|status|stage|kind|partition|publication_id|incident_id|task_name|backfill_id|scope|batch_kind)\b", t) and "COLLATE" not in t and "(" not in t:
                        raise AssertionError((f.name, t))
        assert not re.search(r"make_interval\(days", body), f.name
    setup = (SQL_DIR / "00_definitions.sql").read_text()
    assert len(re.findall(r"CREATE TEMP TABLE", setup)) == 4 and "CREATE TABLE" not in setup.replace("CREATE TEMP TABLE", "")
    for f in sorted(SQL_DIR.glob("bi_*.sql")):
        assert "P08-ART-06" in f.read_text(), f.name
    assert not re.search(r"(?i)\b(insert|update|delete|drop|alter|create)\b", "\n".join(l for l in "\n".join(f.read_text() for f in SQL_DIR.glob("bi_*.sql")).splitlines() if not l.strip().startswith("--")))
    for f in files:                                                                  # every block of a numbered file is a single statement
        for line in f.read_text().splitlines():
            if line.startswith("-- @@ "):
                assert re.fullmatch(r"-- @@ \w+", line), line
    assert "artifact_" in (SQL_DIR / "artifact_tables.sql").read_text() and "NOT a migration" in (SQL_DIR / "artifact_tables.sql").read_text()


def test_the_definitions_are_the_analysis_own_text_and_not_a_copy_of_the_reference_sql():
    ref = (ROOT / "data/sql/reference_metrics.sql").read_text()
    mine = (SQL_DIR / "00_definitions.sql").read_text()
    for token in ("cb AS (", "rw AS (", "tsw AS (", "fv AS (", "batch_json", "src_json"):
        assert token in ref and token not in mine, token
    assert "reference_metrics" not in "\n".join(l for l in mine.splitlines() if not l.startswith("--"))
    for f in sorted(SQL_DIR.glob("[01][0-9]_*.sql")):
        assert "reference_metrics" not in "\n".join(l for l in f.read_text().splitlines() if not l.startswith("--")), f.name


# ---- the workbook --------------------------------------------------------------------------------------------------------------------------

def _b(v):
    """LibreOffice stores a typed TRUE/FALSE constant as the formula =TRUE() / =FALSE() when it saves the recalculated file; read both forms as the boolean."""
    return {"=TRUE()": True, "=FALSE()": False}.get(v, v)


def test_workbook_sheets_present_and_assumptions_listed(wb, bw):
    assert wb.sheetnames == bw.SHEET_ORDER
    ids = [wb["Assumptions"].cell(row=r, column=1).value for r in range(4, 4 + len(bw.ASSUMPTIONS))]
    assert ids == [a[0] for a in bw.ASSUMPTIONS] and {"A-01", "A-07", "W-01", "W-05"} <= set(ids)
    rm = " ".join(str(c.value) for row in wb["Read me"].iter_rows() for c in row if c.value)
    assert DATASET_HASH in rm and CODE_REVISION in rm and "Excel was NOT run" in rm and "synthetic" in rm.lower() and "COMPLETE" in rm and "SAMPLE" in rm and "RECORDED" in rm


def test_data_sheets_equal_the_snapshot_and_the_independent_side(wb, ps):
    c = ps.Ctx()
    ws = wb["Batches"]
    rows = [[ws.cell(row=r, column=k).value for k in range(1, 13)] for r in range(4, 4 + len(c.batches))]
    assert [r[0] for r in rows] == sorted(c.batches)
    for r in rows:
        s = c.summaries[r[0]]
        assert (r[1], r[2], r[3], r[5], r[6], r[7], r[8], r[9], r[10], _b(r[11])) == (c.batches[r[0]]["source_id"], c.batches[r[0]]["status"], s["kind"], s["written_rows"], s["received"], s["accepted_unique"],
                                                                                    s["duplicate"], s["quarantined"], s["deleted"], bool(s["sampled"]))
    assert ws.cell(row=4 + len(c.batches), column=1).value is None and len(rows) == 1311
    assert sum(r[6] for r in rows if r[2] == "committed") == 39901
    cp = wb["Checkpoints"]
    assert sum(1 for r in range(4, 4 + 1302) if cp.cell(row=r, column=1).value) == 1302 and cp.cell(row=4 + 1302, column=1).value is None
    runs = wb["Runs"]
    for r in (4, 100, 4 + 1342):
        rid = runs.cell(row=r, column=1).value
        info = c.run[rid]
        assert runs.cell(row=r, column=3).value == info["status"] and runs.cell(row=r, column=4).value == info["duration"] and runs.cell(row=r, column=5).value == len(c.gate.get(rid, {}))
    assert runs.cell(row=4 + 1343, column=1).value is None
    inc = wb["Incidents"]
    assert [inc.cell(row=r, column=1).value for r in range(4, 29)] == [i["incident_id"] for i in c.incidents]
    bf = wb["Backfills"]
    assert sum(1 for r in range(4, 4 + 19) if bf.cell(row=r, column=3).value == "accepted") == 15 and bf.cell(row=4 + 19, column=1).value is None
    assert wb["Retries"].cell(row=4 + 48, column=1).value is not None and wb["Retries"].cell(row=4 + 49, column=1).value is None
    assert wb["Fetch log"].cell(row=4 + 1360, column=1).value == 1361 and wb["Fetch log"].cell(row=4 + 1361, column=1).value is None
    src = wb["Sources"]
    for r in range(4, 10):
        s = src.cell(row=r, column=1).value
        assert src.cell(row=r, column=4).value == c.contracts[s]["freshness_target_seconds"] and src.cell(row=r, column=6).value == sum(e["expected_records"] for e in c.expect if e["source_id"] == s)


def test_result_cells_of_the_formula_sheets_are_live_formulas_without_hardcoded_figures(wb):
    sh = wb["Source health"]
    for r in range(4, 10):
        for col in range(2, 21):
            v = sh.cell(row=r, column=col).value
            assert isinstance(v, str) and v.startswith("="), (r, col, v)
    for col in "DEFGHIJKPQT":
        assert str(sh[f"{col}10"].value).startswith("="), col
    pd = wb["Publish decision"]
    for r in list(range(3, 11)) + list(range(14, 20)) + list(range(22, 28)) + [30, 31, 34, 35, 38, 39, 40, 41, 44, 45, 46]:
        assert str(pd.cell(row=r, column=2).value).startswith("="), r
    runs = wb["Runs"]
    for r in (4, 100, 4 + 1342):
        for col in (16, 17, 18):
            assert str(runs.cell(row=r, column=col).value).startswith("="), (r, col)
    inc = wb["Incidents"]
    for r in (4, 28):
        assert all(str(inc.cell(row=r, column=col).value).startswith("=") for col in (5, 6, 7))
    rt = wb["Retries"]
    assert all(str(rt.cell(row=4, column=col).value).startswith("=") for col in (6, 7, 8))
    g = wb["Golden case"]
    for r in range(4, 14):
        assert str(g.cell(row=r, column=6).value).startswith("="), r
    for r in range(16, 35):
        assert str(g.cell(row=r, column=2).value).startswith("=") and str(g.cell(row=r, column=4).value).startswith("="), r
    ss = wb["Sample scope"]
    assert all(str(ss.cell(row=4, column=col).value).startswith("=") for col in (7, 8, 11, 12))
    assert wb["Checks"]["B2"].value.startswith("=AND(") and wb.calculation.fullCalcOnLoad
    assert wb["Controls"]["B3"].value == 2 and wb["Controls"]["B5"].value == "complete world"


def test_cached_values_equal_the_domain_recomputed_here(wbv, bw, world):
    d = world["dom"]
    assert _b(wbv["Checks"]["B2"].value) is True and _b(wbv["Controls"]["B7"].value) is True
    for r in range(5, 16):
        assert _b(wbv["Checks"].cell(row=r, column=2).value) is True, r
    sh = wbv["Source health"]
    man = world["manifest"]["stats"]
    for r in range(4, 10):
        s = sh.cell(row=r, column=1).value
        mi = man["ingestion"]["sources"][s]
        assert [sh.cell(row=r, column=c).value for c in (5, 6, 7, 8)] == [mi["received"], mi["accepted_unique"], mi["duplicate"], mi["quarantined"]]
        assert abs(sh.cell(row=r, column=10).value - float(mi["rejection_rate"])) < 5e-7 and abs(sh.cell(row=r, column=11).value - float(mi["duplicate_rate"])) < 5e-7
        assert sh.cell(row=r, column=14).value == d["freshness"][s]["ingestion_age_seconds"] and sh.cell(row=r, column=15).value == man["freshness_at_as_of"][s]["freshness_seconds"]
        assert abs(sh.cell(row=r, column=19).value - float(man["completeness_by_source"][s]["value"])) < 5e-7
        assert _b(sh.cell(row=r, column=20).value) is True
        assert _b(sh.cell(row=r, column=17).value) is (s == "src-refunds") and _b(sh.cell(row=r, column=16).value) is False
    assert sh["E10"].value == 39901 and abs(sh["J10"].value - 0.010752) < 5e-7 and abs(sh["K10"].value - 0.052655) < 5e-7
    pd = wbv["Publish decision"]
    reached = [v for v in d["quality_gate"].values() if v["results"]]
    assert [pd.cell(row=r, column=2).value for r in (14, 15, 16, 17, 18, 19)] == [len(d["quality_gate"]), len(reached), sum(v["decision"] == "allowed" for v in reached),
                                                                                  sum(v["decision"] == "blocked" for v in reached), len(d["quality_gate"]) - len(reached), 1318]
    assert [pd.cell(row=r, column=2).value for r in range(22, 28)] == [man["incidents"]["by_type"][k] for k in bw.KINDS]
    assert abs(pd["B30"].value - float(d["runs"]["overall"]["task_success_rate"])) < 5e-7 and abs(pd["B31"].value - float(d["runs"]["overall"]["attempt_success_rate"])) < 5e-7
    assert pd["B34"].value == d["incidents"]["total"] and abs(pd["B35"].value - float(d["incidents"]["mean_recovery_minutes"])) < 5e-5
    assert (pd["B38"].value, pd["B39"].value) == (d["backfills"]["overall"]["requested_partitions"], d["backfills"]["overall"]["verified_partitions"]) and abs(pd["B40"].value - float(d["backfills"]["overall"]["coverage"])) < 5e-7
    assert pd["B6"].value == d["publications"]["current_publication_id"] and pd["B5"].value == "allowed" and pd["B8"].value == 1 and pd["B7"].value == 0 and pd["B9"].value == "src-refunds"
    assert pd["B10"].value.startswith("PUBLISH WITH A STATED EXCEPTION") and pd["B44"].value == pd["B45"].value == 49 and pd["B46"].value == "48 | 1"
    g = wbv["Golden case"]
    want = {"received": 10, "accepted unique": 8, "duplicate": 1, "quarantined": 1}
    seen = {g.cell(row=r, column=1).value: g.cell(row=r, column=2).value for r in range(16, 35)}
    for k, v in want.items():
        assert seen[k] == v
    assert seen["freshness seconds (as-of minus the latest accepted event)"] == 52200 and abs(seen["recovery minutes (verified 20:15 minus detected 12:20)"] - 475) < 1e-9
    ss = wbv["Sample scope"]
    assert ss["B10"].value == 1878 and ss["C10"].value == 1822 and ss["E10"].value == 23 and ss["K10"].value == 53 and ss["L10"].value == -53


def test_full_calc_on_load_is_set_in_workbook_xml():
    import zipfile
    assert 'fullCalcOnLoad="1"' in zipfile.ZipFile(XLSX).read("xl/workbook.xml").decode()


needs_lo = pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice (soffice) is not installed")


def _lo_recalc(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(exist_ok=True)
    subprocess.run(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{out_dir}/profile",
                    "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out_dir / "out"), str(src)], check=True, capture_output=True, timeout=1800)
    return out_dir / "out" / src.name


@needs_lo
def test_libreoffice_headless_recalculation_of_a_copy_as_delivered(tmp_path):
    src = tmp_path / "copy.xlsx"
    shutil.copy(XLSX, src)
    v = openpyxl.load_workbook(_lo_recalc(src, tmp_path / "a"), data_only=True)
    assert _b(v["Checks"]["B2"].value) is True and _b(v["Controls"]["B7"].value) is True and v["Controls"]["B3"].value == 2 and v["Controls"]["B5"].value == "complete world"


@needs_lo
@pytest.mark.parametrize("silent_factor,scope", [(1, "complete world"), (4, "complete world"), (2, "sample")])
def test_the_switches_are_live_and_the_check_cell_stays_true(tmp_path, silent_factor, scope):
    flip = openpyxl.load_workbook(XLSX)                         # formulas only: openpyxl drops the cached values on save
    flip["Controls"]["B3"] = silent_factor
    flip["Controls"]["B5"] = scope
    src = tmp_path / f"s{silent_factor}{scope[0]}.xlsx"
    flip.save(src)
    assert openpyxl.load_workbook(src, data_only=True)["Checks"]["B2"].value is None          # no cached values until recalculated
    v = openpyxl.load_workbook(_lo_recalc(src, tmp_path / "x"), data_only=True)
    assert _b(v["Checks"]["B2"].value) is True
    sh, pd = v["Source health"], v["Publish decision"]
    silent = [sh.cell(row=r, column=1).value for r in range(4, 10) if _b(sh.cell(row=r, column=17).value) is True]
    assert silent == (["src-orders", "src-refunds"] if silent_factor == 1 else ["src-refunds"])
    assert pd["B8"].value == len(silent) and pd["B10"].value.startswith("PUBLISH WITH A STATED EXCEPTION") and pd["B7"].value == 0
    if scope == "sample":
        assert abs(sh["M4"].value - v["Sample scope"]["H4"].value) < 1e-12 and abs(v["Sample scope"]["B12"].value - 0.012247) < 5e-7
    else:
        assert abs(sh["M4"].value - sh["K4"].value) < 1e-12 and abs(v["Sample scope"]["B12"].value - 0.052655) < 5e-7


def test_pasted_sql_results_sheet_matches_the_stored_results(wb):
    ws = wb["SQL results (pasted)"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    meta = RES["meta"][0]
    assert any(isinstance(c, str) and f"reconciliation rows {meta['reconciliation_rows']}, equal {meta['reconciliation_equal']}" in c and DATASET_HASH in c and CODE_REVISION in c for c in cells)
    assert float(row_of("01_ingestion_by_source__overall")["rejection_rate"]) in cells and float(row_of("01_ingestion_by_source__overall")["duplicate_rate"]) in cells
    assert float(row_of("06_incidents_and_verified_recovery__summary")["mean_recovery_minutes"]) in cells and float(row_of("07_backfill_coverage_and_refused_overlaps__coverage_summary")["coverage"]) in cells
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)               # pasted values, not formulas


# ---- the BI package ------------------------------------------------------------------------------------------------------------------------

def _csv(name: str) -> list[dict]:
    with (ART / "bi" / f"{name}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


BI = ["dim_source", "dim_date", "dim_failure_kind", "dim_check", "dim_scope", "dim_measure", "fact_batch", "fact_run", "fact_gate_check", "fact_incident", "fact_backfill_partition", "fact_fetch",
      "fact_freshness"]


def test_bi_exports_have_the_documented_grain_and_equal_the_snapshot(ps):
    c = ps.Ctx()
    for n in BI:
        assert (ART / "bi" / f"{n}.csv").exists(), n
    assert (ART / "bi" / "measures_recomputed.csv").exists()
    counts = {"dim_source": 6, "dim_date": 56, "dim_failure_kind": 6, "dim_check": 7, "dim_scope": 3, "fact_batch": 1311, "fact_run": 1343, "fact_gate_check": 9296, "fact_incident": 25,
              "fact_backfill_partition": 19, "fact_fetch": 1361, "fact_freshness": 6}
    for n, k in counts.items():
        assert len(_csv(n)) == k, n
    fb = _csv("fact_batch")
    assert len({r["batch_id"] for r in fb}) == 1311 and sum(int(r["received"]) for r in fb if r["counted"] == "true") == 39901
    assert {r["batch_id"] for r in fb if r["counted"] == "false"} == {b for b, r in c.batches.items() if r["status"] != "committed"}
    assert sum(int(r["schema_quarantined_rows"]) for r in fb) == 17 and [r["batch_id"] for r in fb if int(r["schema_quarantined_rows"])] == ["b-0847"]
    fr = _csv("fact_run")
    assert len({r["run_id"] for r in fr}) == 1343 and sum(r["status"] == "failed" for r in fr) == 25 and sum(r["gate_decision"] == "allowed" for r in fr) == 1318
    assert {r["run_id"]: r["failure_kind"] for r in fr if r["failure_kind"]} == {rid: i["kind"] for rid, i in c.run.items() if i["kind"]}
    gc = _csv("fact_gate_check")
    assert len(gc) == 1328 * 7 and {r["scope"] for r in gc} == {"complete_world"} and sum(r["passed"] == "false" and r["severity"] == "critical" for r in gc) == 10
    assert {r["scope"] for n in ("fact_batch", "fact_run", "fact_gate_check", "fact_incident", "fact_backfill_partition", "fact_fetch") for r in _csv(n)} == {"complete_world"}
    ff = {r["source_id"]: r for r in _csv("fact_freshness")}
    assert all(r["freshness_scope"] == "recorded" and r["ingestion_age_scope"] == "complete_world" for r in ff.values()) and ff["src-refunds"]["silent"] == "true"
    assert sum(r["silent"] == "true" for r in ff.values()) == 1
    scopes = {r["scope"] for r in _csv("dim_scope")}
    assert scopes == {"complete_world", "sample", "recorded"}
    assert {r["scope"] for r in _csv("measures_recomputed")} <= scopes
    bp = _csv("fact_backfill_partition")
    assert sum(r["in_coverage"] == "true" for r in bp) == 15 and sum(r["outcome"] == "refused" for r in bp) == 4 and not any(r["verified"] == "true" for r in bp if r["outcome"] == "refused")
    assert [r["retry_honoured"] for r in _csv("fact_fetch") if r["status"] == "rate_limited"].count("true") == 49


def test_bi_measures_recomputed_from_the_csv_files_equal_the_stored_values_and_the_domain(ra, world):
    csvs = {n: _csv(n) for n in BI}
    man = world["manifest"]["stats"]
    facts = {"late_recorded": man["late_events"]["count"], "late_causes": ", ".join(f"{k} {v}" for k, v in man["late_events"]["by_cause"].items()), "late_sample": world["dom"]["late_events"]["count"],
             "recon_publications": man["reconciliation"]["publications"], "recon_publications_nonzero": man["reconciliation"]["residual_not_zero"], "recon_candidates": man["reconciliation"]["candidates"],
             "recon_candidates_nonzero": man["reconciliation"]["candidates_residual_not_zero"], "hash_recorded": man["publications"]["content_hash_ok"],
             "hash_verifiable": int(row_of("10_sample_scope_reconciliation__publications")["verifiable_from_the_sample"])}
    meas = ra.bi_measures(csvs, facts)
    assert [{k: str(v) for k, v in m.items()} for m in meas] == _csv("measures_recomputed")
    assert [{k: str(v) for k, v in m.items()} for m in meas] == RES["bi_measures"]
    mv = {(m["measure"], m["slice"]): m for m in meas}
    d = world["dom"]
    mo = man["ingestion"]["overall"]
    assert mv[("rejection_rate", "all")]["value"] == mo["rejection_rate"] and mv[("duplicate_rate", "all")]["value"] == mo["duplicate_rate"]
    assert mv[("task_success_rate", "all")]["value"] == d["runs"]["overall"]["task_success_rate"] and mv[("attempt_success_rate", "all")]["value"] == d["runs"]["overall"]["attempt_success_rate"]
    assert mv[("mean_recovery_minutes", "all")]["value"] == d["incidents"]["mean_recovery_minutes"] and mv[("backfill_coverage", "all")]["value"] == d["backfills"]["overall"]["coverage"]
    assert mv[("retries_honoured", "all")]["value"] == "1.000000" and mv[("silent_sources", "all")]["value"] == "1"
    assert [(m["measure"], m["slice"]) for m in meas if m["value"] == ""] and all(m["status"] != "value" for m in meas if m["value"] == "")          # nothing withheld silently
    assert {m["status"] for m in meas if m["value"] == ""} >= {"recorded_only", "sample_only", "not_verifiable_from_the_sample"}
    assert not any(m["measure"] == "weighted_score" for m in meas)
    defined = {r["measure"] for r in _csv("dim_measure")}
    assert {m["measure"] for m in meas} <= defined and len(defined) == 30


def test_bi_package_defines_every_measure_and_makes_no_pbix_claim():
    doc = read("bi-package.md")
    for n in BI + ["measures_recomputed"]:
        assert f"`{n}.csv`" in doc, n
    for m in {r["measure"] for r in _csv("dim_measure")}:
        assert f"`{m}`" in doc, m
    assert "no `.pbix`" in doc.lower() or "There is **no `.pbix`**" in doc
    assert not list(ART.rglob("*.pbix")) and not list(ROOT.rglob("*.pbix"))
    for token in ("Power Query", "DAX", "was not executed", "Power BI Desktop", "complete_world", "recorded", "Nothing is withheld silently", "fact_run[date_key]", "dim_scope", "recorded_only"):
        assert token in doc, token
    assert DATASET_HASH in doc and CODE_REVISION in doc and "synthetic" in doc.lower() and "without installing" in doc
    for tok in ("39901", "0.010752", "1343 / 1328 / 1318 / 10 / 15", "60.6827", "0.733333"):
        assert tok in doc, tok


# ---- the data dictionary and the ERD -------------------------------------------------------------------------------------------------------------

def _tables_and_columns() -> dict[str, list[str]]:
    """The tables and columns of the migrations, parsed from their text."""
    out: dict[str, list[str]] = {}
    mig = ROOT / "data" / "sql" / "migrations"
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", (mig / "0001_schema.sql").read_text(), re.S):
        cols = []
        for line in m.group(2).splitlines():
            t = line.strip()
            if not t or t.startswith(("--", "CHECK", "PRIMARY", "UNIQUE", "CONSTRAINT", "FOREIGN")):
                continue
            cols.append(re.match(r"(\w+)\s", t).group(1))
        out[m.group(1)] = cols
    for text in ((mig / "0002_constraints.sql").read_text(), (mig / "0003_review_fixes.sql").read_text()):
        for m in re.finditer(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", text):
            out[m.group(1)].append(m.group(2))
    out["schema_migrations"] = ["version", "checksum", "applied_at"]                  # created by data/migrate.py
    return out


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations():
    tables = _tables_and_columns()
    assert len(tables) == 25
    dd, erd = read("data-dictionary.md"), read("erd.md")
    assert "```mermaid" in erd and "erDiagram" in erd and "Read the text lists below the diagram" in erd
    heads = {}
    for block in dd.split("\n### `")[1:]:
        title, body = block.split("`", 1)
        heads[title] = body.split("\n## ", 1)[0]
    for t, cols in tables.items():
        assert t in heads, t
        mine = re.search(rf"^    {t} \{{\n(.*?)\n    \}}", erd, re.S | re.M)
        assert mine, t
        for c in cols:
            assert f"| `{c}` |" in heads[t], (t, c)
            assert re.search(rf"^\s+[\w\[\]]+ {c}( [A-Z,]+)?$", mine.group(1), re.M), (t, c)
        listed = re.findall(r"^\| `(\w+)` \|", heads[t], re.M)
        assert listed == cols, (t, listed, cols)                                      # nothing invented, same order as the database
    for key in ("Scope vocabulary", "complete world", "2,000-row sample", "recorded", "Foreign keys", "Source-to-target mapping", "Database guards", "idempotency boundary", "payload_json",
                "src-refunds", "artifact_batch_summaries"):
        assert key in dd, key
    counts = {"source_contracts": "6", "source_expectations": "336", "ingestion_batches": "1,311", "raw_records": "2,000", "quarantine_records": "446", "checkpoints": "1,302",
              "model_definitions": "12", "pipeline_runs": "1,343", "task_runs": "5,462", "quality_results": "9,296", "publications": "1,318", "incidents": "25", "fetch_log": "1,361"}
    for k, v in counts.items():
        assert f"| `{k}.json` | {v}" in dd, k
    assert DATASET_HASH in dd and CODE_REVISION in dd and DATASET_HASH in erd and CODE_REVISION in erd and "synthetic" in dd.lower()
    manifest = json.loads((ROOT / "web/public/data/manifest.json").read_text())
    for k, v in manifest["row_counts"].items():
        if k in counts:
            assert counts[k] == f"{v:,}", k
    for rel in re.findall(r"^\* `(\w+)\.(\w+)` references `(\w+)\.(\w+)`\.$", erd, re.M):
        child, ccol, parent, pcol = rel
        assert ccol in tables[child] and pcol in tables[parent], rel
    assert len(re.findall(r"^\* `\w+\.\w+` references `\w+\.\w+`\.$", erd, re.M)) == len(re.findall(r"REFERENCES", (ROOT / "data/sql/migrations/0001_schema.sql").read_text()))


# ---- the documents -------------------------------------------------------------------------------------------------------------------------

def test_sql_analysis_doc_quotes_the_stored_results_and_every_table_is_rendered_from_them(P):
    rn = _load("po_render", ART / "render_sql_analysis.py")
    for doc in ("sql-analysis.md", "bi-package.md"):
        text = read(doc)
        assert rn.render(text, RES) == text, doc
    sql = read("sql-analysis.md")
    keys = set(re.findall(r"<!-- BEGIN:(\w+) -->", sql))
    assert keys <= set(RES) and len(keys) >= 50
    for k in P:
        assert k in keys or k.startswith(("01_", "02_", "03_", "04_", "05_", "06_", "07_", "08_", "10_")), k
    assert {k for k in keys if k[:2] == "09"} == {k for k in RES if k.startswith("09_golden_known_answer__")}
    meta = RES["meta"][0]
    assert f"RESULT: OK ({meta['reconciliation_rows']} reconciliation rows, {meta['reconciliation_equal']} equal; {meta['result_sets']} result sets, {meta['result_rows']} rows)" in sql
    fam = {}
    for r in RES["reconciliation"]:
        fam[r["check"][0]] = fam.get(r["check"][0], 0) + 1
    for k, n in fam.items():
        assert f"**{k} ({n} rows)" in sql, (k, n)
    for inv in ("`01_ingestion_by_source.sql`", "`02_run_funnel_by_failure_kind.sql`", "`03_task_vs_attempt_success.sql`", "`04_freshness_vs_ingestion_age.sql`", "`05_publication_pointer_and_blocked_runs.sql`",
                "`06_incidents_and_verified_recovery.sql`", "`07_backfill_coverage_and_refused_overlaps.sql`", "`08_fetch_log_retry_after.sql`", "`09_golden_known_answer.sql`", "`10_sample_scope_reconciliation.sql`"):
        assert inv in sql, inv
    for tok in ("known gap", "delete events", "**Scope:**", "complete world", "2,000-row sample", "recorded"):
        assert tok in sql, tok
    assert DATASET_HASH in sql and CODE_REVISION in sql and "synthetic" in sql.lower() and "without installing" in sql


def test_the_documents_name_the_real_entities_metrics_and_commands_and_keep_result_kinds_apart():
    for n in DOC_NAMES:
        text = read(n)
        if n in ("data-dictionary.md", "erd.md", "resume-bullets.md", "release-package.md"):
            continue
        assert re.search(r"(?i)observed", text), n
    case, memo = read("business-case.md"), read("executive-memo.md")
    for tok in ("OBSERVED", "SIMULATED", "HYPOTHETICAL"):
        assert tok in memo, tok
    for tok in ("Observed results", "simulated outcomes", "hypothetical real-world benefits"):
        assert tok in case, tok
    for tok in ("source_contracts", "ingestion_batches", "raw_records", "pipeline_runs", "publications", "C01", "C06", "C10", "src-refunds", "run-1187", "pub-1343", "P08-MET-01", "P08-FLOW-05", "P08-TEST-06"):
        assert tok in case or tok in read("requirements.md"), tok
    assert "pipeline-observatory-ci.yml" in read("requirements.md") and "reference-and-domain" in read("requirements.md")
    for tok in ("Is this dataset safe, complete, and fresh enough to publish?", "safe, complete and fresh"):
        assert tok in case or tok in memo
    for n in DOC_NAMES:
        text = read(n)
        assert "safe, complete" in text.lower() or n in ("data-dictionary.md", "erd.md", "resume-bullets.md"), n


def test_requirements_trace_every_requirement_family():
    req = read("requirements.md")
    for fam in ("GOAL", "DOMAIN", "DATA", "MET", "FLOW", "UI", "TEST", "GOLD", "WORK", "ART"):
        assert re.search(rf"P08-{fam}-\d\d", req), fam
    for tok in ("P08-GOAL-01", "P08-GOAL-02..04", "P08-GOAL-05, 06", "P08-GOAL-09, 10", "P08-GOAL-12", "P08-GOAL-13, 14", "P08-DOMAIN-01..03", "P08-DOMAIN-04", "P08-DOMAIN-05, 06",
                "P08-GOLD-01..11", "P08-WORK-01..10"):
        assert tok in req, tok
    for i in range(1, 13):
        assert f"P08-TEST-{i:02d}" in req
    for i in range(1, 11):
        assert f"P08-FLOW-{i:02d}" in req and f"P08-UI-{i:02d}" in req and f"P08-ART-{i:02d}" in req
    for i in range(1, 13):
        assert f"P08-DATA-{i:02d}" in req
    for i in (1, 2, 3, 4, 5, 8, 9, 10, 11, 12):
        assert f"P08-MET-{i:02d}" in req, i
    assert "P08-MET-06, 07" in req
    for tok in ("User stories", "acceptance criteria", "Traceability matrix", "Non-functional", "Deferred and open", "Excel and Power BI Desktop were not run", "skip", "LibreOffice",
                "artifacts08_snapshot", "artifacts08_golden", "not yet attached to a release", DATASET_HASH, CODE_REVISION, "synthetic", "without installing"):
        assert tok in req, tok
    names = " ".join(p.read_text() for p in (ROOT / "tests").glob("test_*.py")) + (ROOT / "web/e2e/journey.spec.ts").read_text()
    for t in re.findall(r"`(test_[a-z0-9_]+)`", req):
        assert f"def {t}" in names, t                                                 # every test named in full exists
    for t in re.findall(r"`(test_[a-z0-9_]+)\*`", req):
        assert re.search(rf"def {t}", names), t
    for t in re.findall(r"`(?:\w+\.py)::(test_[a-z0-9_]+)(\*)?`", req):
        assert re.search(rf"def {t[0]}", names), t


def test_executive_memo_quotes_the_evidence_options_and_the_caveats():
    memo = read("executive-memo.md")
    for tok in ("## Decision", "## Evidence", "## Options", "## Uncertainty", "## Limitations", "## What the sample cannot show", "## Recommendation", "Publish the current snapshot `pub-1343` with a stated exception",
                "262,378 s", "17,363 s", "604,800 s", "0.945541", "0.000000", "60.6827", "0.733333", "-141.46", "757", "141", "0.012247", "0.052655", "61 of the 72", "SIMULATED", "recorded",
                "2026-10-01T23:07:02Z", "2026-08-13", "2026-08-22", "2026-09-07", "2026-09-17", "0 of 1,318", "header", "no authentication", "sandbox", "complete world", "2,000-row sample"):
        assert tok in memo, tok
    assert "| **A. Publish" in memo and "| B. Hold" in memo and "| C. Publish and tighten" in memo and "| D. Publish as the gate says" in memo
    assert DATASET_HASH in memo and CODE_REVISION in memo and "without installing" in memo and "no benefit" in memo.lower()
    # the simulated option: runs of the silent window whose start is later than the instant the freshness would pass two cadences
    runs = RES["02_run_funnel_by_failure_kind__funnel"]
    assert runs
    ss = row_of("04_freshness_vs_ingestion_age__silent_source")
    assert int(ss["runs_since"]) == 72
    first = "2026-10-01T23:07:02Z"
    from datetime import datetime, timedelta, timezone
    limit = datetime.strptime(first, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(seconds=2 * 21600)
    started = [datetime.strptime(r["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) for r in json.loads((ROOT / "web/public/data/pipeline_runs.json").read_text())["rows"]]
    assert sum(s > limit for s in started) == 61


def test_uat_evidence_has_routes_screenshots_scenarios_and_run_links():
    uat = read("uat-evidence.md")
    routes = (ROOT / "web/src/routes.ts").read_text()
    for path in re.findall(r'path: "([a-z-]*)"', routes):
        assert (f"`/{path}/`" if path else "`/`") in uat, path
    shots = (ROOT / "web/e2e/screens.spec.ts").read_text()
    for name in re.findall(r'\{ name: "([\w-]+)"', shots):
        assert f"`{name}`" in uat, name
    for tok in ("75 files", "<view>-<width>.png", "<view>-zoom200.png", "index.json", "playwright-report.json", "360, 768, 1280 and 1920", "200% zoom"):
        assert tok in uat, tok
    for i in range(1, 16):
        assert f"| S{i} |" in uat, i
    for tok in ("40468689563", "40469671918", "40449388766", "40442468507", "40455458608", "40456053215", "40464667890", "pending when this pass was dispatched", "not fetched", "did **not** run `npm run e2e`",
                "R8-01", "R8-08", "R8-16", "Defect disposition", "fixed", "529 passed", "742 checks", "90 passed", "1,180", "255", DATASET_HASH, CODE_REVISION, "synthetic", "without installing"):
        assert tok in uat, tok
    assert "does not exist before" not in uat and "did not exist before it" in uat
    for rid in ("R8-01", "R8-02", "R8-03", "R8-04", "R8-05", "R8-06", "R8-07", "R8-08"):
        assert re.search(rf"\| {rid} ", uat), rid


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    tcs, rel = read("technical-case-study.md"), read("release-package.md")
    for token in ("Architecture", "Trade-offs", "Recovery behaviour", "Reproducible setup", "Measured evidence", "Open gaps", "```mermaid", "R8-01", "R8-08", "at-least-once with idempotent apply", "never exactly-once",
                  "ed7eb5a", "40468689563", "40469671918", "204 reconciliation rows", "Excel and Power BI Desktop were not run", "no hosted run of `tests/test_artifacts.py` is recorded yet", "742", "529", DATASET_HASH,
                  CODE_REVISION, "key boundary", "vacuous", "staged"):
        assert token in tcs or token.lower() in tcs.lower(), token
    for token in ("d58209f", "cf04a0e", "83b6a60", "a2ef4f4130e04f5d70795ba8d83b97f02d962583", "b326690a791ca440e6c616dea361383cb8f7e665", "12f59fe2f3a5533b27dcd3e9189ab034c5bf9d6d42fa62e8dc66343d60a95370", "40468689563",
                  "40469671918", "pending at dispatch", "Rollback procedure", "git revert", "Artifacts and checksums", DATASET_HASH, "committed and pushed nothing", "Main-portfolio metadata", "Excel", "Power BI", "not fetch",
                  "What this artifact pass ran", "private", "529 Python tests"):
        assert token in rel, token
    assert "lab:lab" not in rel and "RUN_LOG_PLACEHOLDER" not in rel and "TBD_" not in rel
    if shutil.which("git"):
        for c in ("ed7eb5a", "b326690"):
            probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", c], capture_output=True, text=True)
            if probe.returncode != 0:
                pytest.skip(f"commit {c} is not in this checkout")
        for c, subj in (("b326690", "Ledgers: Pipeline Observatory fixes accepted"), ("ed7eb5a", "Pipeline Observatory: review R8 fixes")):
            assert subj in subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%s", c], capture_output=True, text=True).stdout
    mp = ROOT.parents[1] / "docs" / "program" / "release-manifest.json"
    if mp.exists():
        site = next(s for s in json.loads(mp.read_text())["sites"] if s["slug"] == "pipeline-observatory")
        releases = [site["release_commit_unified_portfolio"]] + [p["release"] for p in site.get("previous_releases", [])]
        assert "d58209f" in releases and "83b6a60" in releases                                    # a later republish moves d58209f to previous_releases; this package describes it
        assert site["dataset_hash"] == DATASET_HASH
        if site["release_commit_unified_portfolio"] == "d58209f":
            assert site["rollback_commit_unified_portfolio"] == "cf04a0e" and site["source_commit_business_data_lab"].startswith("b326690") and site["published_tree_sha256"] in rel
            assert (site["live_verification"] is None and "pending at dispatch" in rel) or str(site["live_verification"]["run_url"].rsplit("/", 1)[-1]) in rel


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact_and_match_the_ledgers():
    text = read("resume-bullets.md")
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6
    body = " ".join(bullets)
    assert not re.search(r"\b(saved|savings|reduced (?:cost|time)|increased revenue|users|customers? adopted|adoption of|roi|improved|faster than)\b", body, re.I)
    for token in ("742-check", "529 Python tests", "1,180", "255 review checks", "51 worlds", "90 Playwright tests", "R8-01..R8-08", "204 reconciliation rows", "LibreOffice", "`.pbix`", "262,378", "17,363", "60.6827",
                  "0.012247", "0.052655", "273 rows", "8 of 8", "1,343", "labelled as a simulation", "exactly-once is never claimed"):
        assert token in body, token
    assert "synthetic" in text.lower() and "no bullet claims business impact" in text
    assert str(RES["meta"][0]["reconciliation_rows"]) in body
    if PROJECT:
        tech = " ".join(PROJECT["tech"])
        assert "1,180 TypeScript golden and snapshot checks plus 255 review checks over 51 worlds" in tech and re.search(r"\d+ browser tests", tech)


def test_public_case_study_figures_agree_with_the_stored_results():
    if PROJECT is None:
        pytest.skip("the public case study /pipeline-observatory/project.json is not in this checkout (it lives on unified-portfolio)")
    text = re.sub(r"<[^>]+>", " ", PROJECT["results"] + PROJECT["built"] + PROJECT["tagline"] + PROJECT["note"]).replace("−", "-")
    o = row_of("01_ingestion_by_source__overall")
    assert f"the six sources received {int(o['received']):,} rows in committed batches, of which {int(o['accepted_unique']):,} were accepted, {int(o['duplicate']):,} were duplicates of an already accepted key and {int(o['quarantined'])} were quarantined" in text
    assert f"rejection rate {o['rejection_rate']}, duplicate rate {o['duplicate_rate']}" in text and f"plus {o['deleted']} delete events" in text and "17 rows of the one batch quarantined whole" in text
    fn = row_of("02_run_funnel_by_failure_kind__funnel")
    assert f"Of {int(fn['runs']):,} hourly runs, {int(fn['reached_gate']):,} reached the gate, where {int(fn['allowed']):,} were allowed and {fn['blocked_at_gate']} were blocked (five on freshness, four on relationships, one on the residual); the other {fn['failed_before_gate']} failed in a task before the gate ran" in text
    t = row_of("03_task_vs_attempt_success__overall")
    assert f"Task success is {t['task_success_rate']} and attempt success {t['attempt_success_rate']}" in text and "pointer rests on pub-1343" in text
    fv = row_of("04_freshness_vs_ingestion_age__freshness_vs_age", source_id="src-refunds")
    assert f"freshness {int(fv['freshness_seconds']):,} seconds against an ingestion age of {int(fv['ingestion_age_seconds']):,}" in text and "all 72 of its runs stayed green" in text and "completeness 0.000000 on its last three days" in text
    d2 = row_of("05_publication_pointer_and_blocked_runs__designed_blocked_run")
    assert f"left the pointer on {d2['pointer_before']}" in text and f"{row_of('06_incidents_and_verified_recovery__incidents', incident_id='inc-022')['recovery_minutes']} minutes" in text
    sm = row_of("06_incidents_and_verified_recovery__summary")
    assert f"All {sm['incidents']} incidents closed on a verified recovery, mean {sm['mean_recovery_minutes']} minutes" in text
    rs = row_of("08_fetch_log_retry_after__retry_summary")
    assert f"rate-limited {rs['rate_limited_responses']} times and every retry honoured the retry-after hint" in text
    assert "757 late events" in text and "-141.46 on 2026-09-09" in text and "141 late events over the sample" in text
    cs = row_of("07_backfill_coverage_and_refused_overlaps__coverage_summary")
    assert f"Eleven of the fifteen partitions requested by the thirteen accepted backfills were verified ({cs['coverage']})" in text and "two further requests, overlapping earlier ones, were refused" in text
    assert "9,296 quality results instead of 6,640" in text
    rel = read("release-package.md")
    assert PROJECT["repo"].endswith("apps/pipeline-observatory") and PROJECT["date"] == "2026-10" and PROJECT["demo"].rstrip("/").endswith("/labs/pipeline-observatory")
    counts = [int(n.replace(",", "")) for n in re.findall(r"([\d,]+) Python tests", " ".join(PROJECT["tech"]))]
    assert counts and counts[0] >= 529 and "529 Python tests" in rel                      # the case study may state a larger count once this package's tests are counted


def test_no_credentials_or_secrets_in_the_artifact_documents_and_files():
    for d in DOC_NAMES:
        text = read(d)
        assert "lab:lab" not in text, d
        assert not re.search(r"postgres(ql)?://[^<\s]*:[^<\s@]+@", text), d
        assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S{12,}", text), d
    for p in list(ART.glob("*.json")) + list((ART / "bi").glob("*.csv")) + [ART / "CHECKSUMS.txt"] + list(SQL_DIR.glob("*.sql")):
        if not p.exists():
            continue
        assert "postgresql://" not in p.read_text(), p.name
        assert "lab:lab" not in p.read_text(), p.name
    wbtext = " ".join(str(c.value) for ws in openpyxl.load_workbook(XLSX).worksheets[:8] for row in ws.iter_rows() for c in row if c.value)
    assert "postgresql://" not in wbtext and "password" not in wbtext.lower()
    py = (SQL_DIR / "prepare_snapshot.py").read_text()
    assert "lab:lab@127.0.0.1" in py                                          # the local development login of the CI workflow is the one documented default; it is not in any document


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = read("workbook.md")
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "pipeline-observatory-analyst-workbook.xlsx" in doc and "openpyxl 3.1.5" in doc
    for sheet in ("Read me", "Controls", "Checks", "Publish decision", "Source health", "Sample scope", "Golden case", "Assumptions", "Sources", "Batches", "Checkpoints", "Runs", "Incidents", "Backfills", "Retries",
                  "Fetch log", "Domain reference", "SQL results (pasted)"):
        assert f"`{sheet}`" in doc, sheet
    assert "Controls!B3" in doc and "Controls!B5" in doc and "fullCalcOnLoad" in doc and "How to read it without installing" in doc and "Checks!B2" in doc and "Publish decision!B10" in doc
    for v in ("0.010752", "0.052655", "60.6827", "0.733333", "262378", "17363", "0.995311", "0.971622", "0.945541", "475.0000", "0.012247", "0.888889", "0.666667"):
        assert v in doc, v
    assert (ROOT / "requirements-artifacts.txt").read_text().strip() == "openpyxl==3.1.5"
    assert DATASET_HASH in doc and CODE_REVISION in doc and "synthetic" in doc.lower()


def test_every_document_cites_the_dataset_hash_and_the_code_revision_and_says_it_is_synthetic():
    assert len(DOC_NAMES) == 12
    for n in DOC_NAMES:
        text = read(n)
        assert DATASET_HASH in text and CODE_REVISION in text, n
        assert "synthetic" in text.lower(), n
        if n not in ("resume-bullets.md", "erd.md"):
            assert "without installing" in text or "needs nothing installed" in text, n                  # a brief read/use instruction (P08-ART-xx-R12)
    assert "Read the text lists below the diagram" in read("erd.md")
    # important figures are never stated without a scope somewhere in the document that states them
    assert "0.012247" in read("sql-analysis.md") and "2,000-row sample" in read("sql-analysis.md")


def test_the_ci_no_skip_gate_and_the_unrun_tools_are_disclosed():
    req, rel, tcs = read("requirements.md"), read("release-package.md"), read("technical-case-study.md")
    ci = ROOT.parents[1] / ".github" / "workflows" / "pipeline-observatory-ci.yml"
    if ci.exists():
        text = ci.read_text()
        assert "libreoffice-calc" in text and "artifacts08_snapshot" in text and "artifacts08_golden" in text and "ARTIFACTS_DATABASE_URL" in text and "ARTIFACTS_GOLDEN_DATABASE_URL" in text
        assert "fetch-depth: 0" in text and "unified-portfolio" in text
    for doc in (req, rel, tcs):
        assert "skip" in doc.lower() and "LibreOffice" in doc
    assert "not attached to a GitHub release" in rel and "Excel" in rel and "Power BI" in rel


def test_provenance_the_analysed_code_and_data_equal_revision_ed7eb5a():
    """The numbers describe revision ed7eb5a: the domain, API, migrations, loaders, reference SQL, published data, fixtures and the other tests are unchanged since
    (docs/contracts.md and README.md are part of the check: the package changed neither)."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", CODE_REVISION], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"revision {CODE_REVISION} is not in this checkout")
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", CODE_REVISION, "--", "domain", "api", "data/sql/migrations", "data/seed.py", "data/migrate.py", "data/generate.py",
                        "data/sql/reference_metrics.sql", "web/public", "web/src", "web/e2e", "web/scripts", "tests", ":(exclude)tests/test_artifacts.py", "docs/contracts.md", "README.md",
                        "docs/api-contract.md", "docs/web-brief.md", "docs/data-generator.md", "requirements.txt", "pytest.ini"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "", r.stdout
    manifest = json.loads((ROOT / "web/public/data/manifest.json").read_text())
    assert manifest["dataset_hash"] == DATASET_HASH and manifest["dataset_version"] == "po-20261026-20261026"
    full = subprocess.run(["git", "-C", str(ROOT), "rev-parse", CODE_REVISION], capture_output=True, text=True).stdout.strip()
    assert full == CODE_REVISION_FULL


# ---- checksums -----------------------------------------------------------------------------------------------------------------------------

def test_checksums_file_matches_files_and_the_release_package_table():
    path = ART / "CHECKSUMS.txt"
    if not path.exists():
        pytest.skip("CHECKSUMS.txt not written (artifacts/checksums.py)")
    listed = {}
    for line in path.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
        listed[rel] = digest
    chk = _load("po_checksums", ART / "checksums.py")
    assert sorted(listed) == chk.files()                                  # every artifact and doc, nothing stale
    for must in ("artifacts/pipeline-observatory-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py", "artifacts/render_sql_analysis.py", "artifacts/checksums.py",
                 "requirements-artifacts.txt", "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
                 "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md", "docs/business-case.md", "docs/requirements.md", "docs/uat-evidence.md",
                 "docs/contracts.md", "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py", "data/sql/analysis/python_side.py", "data/sql/analysis/artifact_tables.sql",
                 "artifacts/bi/fact_run.csv", "artifacts/bi/dim_date.csv", "artifacts/bi/measures_recomputed.csv"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("[01][0-9]_*.sql")) + sorted(SQL_DIR.glob("bi_*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    assert "docs/release-package.md" not in listed and "artifacts/CHECKSUMS.txt" not in listed
    rel_doc = read("release-package.md")
    for rel, digest in listed.items():
        assert f"| `{rel}` | `{digest}` |" in rel_doc, rel               # release-package.md carries the same table (it cannot list itself)
