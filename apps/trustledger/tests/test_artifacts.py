"""Artifact package checks (P07-ART-01..10): the SQL analysis results, the analyst workbook, the BI exports, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that every result cell of the formula sheets is a live formula, (2) reads
the values LibreOffice cached in the delivered file and compares them with the Python domain RECOMPUTED HERE (not with the pasted reference column), (3) recalculates
copies with LibreOffice headless (as delivered, and with the weight-version switch flipped) and compares them with the domain, (4) checks that the stored analysis results
equal the plain-Python recomputation over web/public/data (no database), through data/sql/analysis/python_side.py, which shares no code with the SQL or the domain, (5) recomputes
the BI measures from the CSV exports, (6) checks that each document quotes the stored results and the public case study, and (7) checks CHECKSUMS.txt and the release-package table.
With ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts07_*; the test prepares them with prepare_snapshot.py) it also re-runs the SQL files and
compares their rows with the stored results; without them that test is skipped with a printed reason. The tests that need LibreOffice are skipped, with a reason, where `soffice` is
missing. Excel and Power BI are never run. This file never touches the shared trustledger database.
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
from fractions import Fraction as F
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

XLSX = ART / "trustledger-analyst-workbook.xlsx"
RES = json.loads((ART / "analysis-results.json").read_text()) if (ART / "analysis-results.json").exists() else {}
CODE_REVISION = "0b5d686"
DATASET_HASH = "a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff"
SCRATCH = "artifacts07_"
_CASE_STUDY = next((p for p in (ROOT.parents[1] / "trustledger" / "project.json", ROOT.parents[3] / "trustledger" / "project.json") if p.exists()), None)
PROJECT = json.loads(_CASE_STUDY.read_text()) if _CASE_STUDY else None          # the public case study lives on unified-portfolio, in the main checkout

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
    return _load("tl_build_workbook", ART / "build_workbook.py")


@pytest.fixture(scope="module")
def ra():
    return _load("tl_run_all", SQL_DIR / "run_all.py")


@pytest.fixture(scope="module")
def prep():
    return _load("tl_prepare", SQL_DIR / "prepare_snapshot.py")


@pytest.fixture(scope="module")
def world(prep):
    from trustledger import run_pipeline
    inputs, manifest = prep.snapshot_inputs()
    truth = manifest["synthetic_truth"]["true_entity"]
    return {"inputs": inputs, "manifest": manifest, "truth": truth, "w2": run_pipeline(inputs, truth=truth), "w1": run_pipeline(inputs, weight_version="w1", truth=truth)}


def row_of(key: str, **where) -> dict:
    return next(r for r in RES[key] if all(str(r[k]) == str(v) for k, v in where.items()))


def read(name: str) -> str:
    return (DOCS / name).read_text()


def sha_of(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def all_test_names() -> str:
    return " ".join(p.read_text() for p in (ROOT / "tests").glob("test_*.py"))


NUMBERED = ["01", "02", "03", "04", "05", "06", "07", "08", "10"]


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
    assert len(numbered) == 9 and [n[:2] for n in numbered] == NUMBERED                       # nine numbered investigations on the snapshot, at least the eight required
    assert {k.split("__")[0][:2] for k in P} == set(NUMBERED)
    golden = [k for k in RES if k.startswith("09_golden_known_answer__")]
    assert len(golden) == 4 and all(RES[k] for k in golden)
    assert {r["check"].split(" ")[0] for r in RES["reconciliation"]} == {"A", "B", "C", "D", "E"}
    assert meta["result_sets"] == len(P) + len(golden)
    assert RES["bi_measures"] and len(RES["bi_measures_portfolio"]) + len(RES["bi_measures_dataset_scores"]) == len(RES["bi_measures"])


def test_golden_known_answer_in_sql_equals_expected_json_the_domain_and_the_hand_figures():
    exp = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())
    cv = RES["09_golden_known_answer__completeness_validity"][0]
    assert (cv["eligible"], cv["missing"], cv["populated"], cv["completeness"]) == ("100", "5", "95", "0.950000")
    assert (cv["passing"], cv["validity_populated_only"], cv["validity_all_eligible"]) == ("90", "0.947368", "0.900000")
    assert cv["validity_populated_only"] == exp["metrics"]["validity"]["r-cust-valid-email"]["populated_only"]["value"]
    assert cv["validity_all_eligible"] == exp["metrics"]["validity"]["r-cust-valid-email"]["all_eligible"]["value"]
    ur = RES["09_golden_known_answer__uniqueness_relationship"][0]
    assert (ur["group_share"], ur["row_share"], ur["fk_eligible"], ur["fk_matched"], ur["relationship"]) == ("0.010204", "0.020000", "37", "35", "0.945946")
    w = {r["weight_version"]: r for r in RES["09_golden_known_answer__weighted_scores"]}
    assert (w["w1"]["weighted_score"], w["w2"]["weighted_score"]) == ("0.958116", "0.963932") and w["w1"]["critical_override"] == w["w2"]["critical_override"] == "true"
    assert float(w["w2"]["weighted_score"]) > 0.95 and float(w["w1"]["weighted_score"]) > 0.95            # a critical failure stays visible above 0.95
    pf = RES["09_golden_known_answer__portfolio"][0]
    assert (pf["timeliness_on_time"], pf["timeliness_monitored"], pf["ownership_covered"], pf["datasets"], pf["definitions_complete"], pf["published_metrics"]) == ("3", "4", "4", "5", "3", "4")
    assert (pf["lineage_observed_matching"], pf["lineage_declared"], pf["approved_correct"], pf["approved"], pf["resolution_mean_hours"]) == ("5", "6", "2", "3", "38.4444")
    from trustledger import run_pipeline
    inputs = json.loads((ROOT / "tests/fixtures/golden/inputs.json").read_text())
    dom = run_pipeline(inputs)
    assert dom.golden() == exp
    assert RES["meta"][0]["golden_dataset_hash"] == hashlib.sha256(json.dumps({k: v for k, v in inputs.items() if k != "synthetic_truth"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def test_stored_results_equal_the_python_side_recomputation_over_the_snapshot_files(ps, P):
    for key, rows in P.items():
        assert ps.normalised(rows) == RES[key], key


def test_stored_reference_figures_equal_the_domain(world):
    m1, m2 = world["w1"].metrics, world["w2"].metrics
    d2 = m2["weighted_score"]["datasets"]
    w = {r["weight_version"]: r for r in RES["01_ds_customers_override_both_weights__weighted"]}
    assert (w["w1"]["weighted_score"], w["w2"]["weighted_score"]) == (m1["weighted_score"]["datasets"]["ds-customers"]["value"], d2["ds-customers"]["value"])
    assert d2["ds-customers"]["critical_override"] is True
    own = RES["02_ownership_coverage__summary"][0]
    assert (own["covered"], own["datasets"], own["coverage"]) == (str(m2["ownership_coverage"]["covered"]), str(m2["ownership_coverage"]["datasets"]), m2["ownership_coverage"]["value"])
    assert [r["dataset_id"] for r in RES["02_ownership_coverage__uncovered"]] == m2["ownership_coverage"]["uncovered"]
    cl = {r["class"]: r["issues"] for r in RES["04_issue_classes_and_resolution__classes"]}
    rt = m2["resolution_time"]
    assert (cl["resolved"], cl["claimed"], cl["open"]) == (str(rt["resolved_count"]), str(rt["claimed_count"]), str(rt["open_count"]))
    assert row_of("04_issue_classes_and_resolution__resolution_overall")["mean_hours"] == rt["mean_hours"]
    lc = m2["lineage_coverage"]
    assert row_of("05_lineage_coverage_evidence__coverage")["coverage"] == lc["value"] and row_of("05_lineage_coverage_evidence__coverage")["undeclared_observed"] == str(len(lc["undeclared_observed"]))
    dc = m2["definition_coverage"]
    assert row_of("06_definition_coverage__summary")["coverage"] == dc["value"] and {r["metric_id"] for r in RES["06_definition_coverage__incomplete"]} == set(dc["incomplete"])
    mp = m2["match_precision"]
    pr = row_of("07_match_precision__precision")
    assert (pr["precision"], pr["reviewed_correct_share"], pr["approved_correct"], pr["reviewed_correct"]) == (mp["precision"], mp["reviewed_correct_share"], str(mp["approved_correct"]), str(mp["reviewed_correct"]))
    tm = m2["timeliness"]
    assert row_of("08_timeliness_states__summary")["timeliness"] == tm["value"] and row_of("08_timeliness_states__summary")["on_time"] == str(tm["on_time_count"])
    cf = m2["critical_failures"]
    assert (row_of("01_ds_customers_override_both_weights__critical")["critical_failures"], row_of("01_ds_customers_override_both_weights__critical")["critical_open_issues"]) == (str(cf["failures"]), str(cf["open_issues"]))
    # every dataset's score under both weight versions
    got = {(r["dataset_id"]): (r["score_w1"], r["score_w2"]) for r in RES["03_weight_shift_dr03__shift_by_dataset"]}
    for d, (a, b) in got.items():
        assert m1["weighted_score"]["datasets"][d]["value"] == a and d2[d]["value"] == b, d


def test_headline_numbers_of_the_documents_are_the_stored_ones():
    memo, case, tcs, bi, wbdoc = read("executive-memo.md"), read("business-case.md"), read("technical-case-study.md"), read("bi-package.md"), read("workbook.md")
    w = {r["weight_version"]: r for r in RES["01_ds_customers_override_both_weights__weighted"]}
    for doc in (memo, case, wbdoc):
        assert w["w1"]["weighted_score"] in doc and w["w2"]["weighted_score"] in doc
    sm = row_of("03_weight_shift_dr03__summary")
    for token in (sm["mean_score_w1"], sm["mean_score_w2"], sm["largest_move"]):
        assert token in memo and token in case, token
    assert f"{sm['datasets_with_different_score']} of {sm['datasets_scored']}" in memo and f"{sm['datasets_with_different_score']} of the {sm['datasets_scored']}" in case
    cl = {r["class"]: r["issues"] for r in RES["04_issue_classes_and_resolution__classes"]}
    for doc in (memo, case):
        for c in ("resolved", "claimed", "open"):
            assert cl[c] in doc, (c, cl[c])
    teams = {r["group_name"]: r for r in RES["04_issue_classes_and_resolution__fast_team_vs_others"]}
    for doc in (memo, case, wbdoc):
        assert teams["Data Platform"]["mean_hours"] in doc and teams["all other teams"]["mean_hours"] in doc
    ov = row_of("04_issue_classes_and_resolution__resolution_overall")
    assert ov["mean_hours"] in memo and ov["fast_team_ratio"] in read("sql-analysis.md")
    assert row_of("02_ownership_coverage__summary")["coverage"] in memo and row_of("05_lineage_coverage_evidence__coverage")["coverage"] in memo
    assert row_of("06_definition_coverage__summary")["coverage"] in memo
    mp = row_of("07_match_precision__precision")
    for token in (mp["precision"], mp["reviewed_correct_share"], mp["decision_agreement_share"]):
        assert token in memo and token in wbdoc, token
    assert f"{mp['reviewed_correct']} of {mp['reviewed']}" in memo
    ts = row_of("08_timeliness_states__summary")
    assert ts["timeliness"] in memo and ts["timeliness"] in wbdoc
    pt = row_of("08_timeliness_states__by_read_instant", read_no=1)
    assert pt["pending"] == "3" and pt["timeliness"] in memo and "3 datasets pending" in memo
    ac = RES["10_fix_first_queue__accountability"][0]
    assert ac["either_owner_inactive"] in memo and ac["critical_or_high_with_an_inactive_owner"] in memo
    assert RES["10_fix_first_queue__queue_top"][0]["issue_id"] == "iss-0461" and "iss-0461" in memo
    n = RES["meta"][0]["reconciliation_rows"]
    for doc in (memo, tcs, read("requirements.md"), read("resume-bullets.md"), wbdoc):
        assert f"{n} " in doc or f"{n}\n" in doc, n
    assert DATASET_HASH in bi and CODE_REVISION in bi


def test_designed_relationships_and_defects_are_present_in_the_results(world):
    dr = {d["id"]: d["realised"] for d in json.loads((ROOT / "web/public/data/injection-manifest.json").read_text())["designed_relationships"]}
    w = {r["weight_version"]: r["weighted_score"] for r in RES["01_ds_customers_override_both_weights__weighted"]}
    assert (w["w1"], w["w2"]) == (dr["DR-01"]["weighted_score_w1"], dr["DR-01"]["weighted_score_w2"])
    assert row_of("02_ownership_coverage__summary")["coverage"] == dr["DR-02"]["value"]
    s = row_of("03_weight_shift_dr03__summary")
    assert (s["datasets_scored"], s["datasets_with_different_score"], s["datasets_moved_at_least_0_005"], s["largest_move"]) == (
        str(dr["DR-03"]["datasets_scored"]), str(dr["DR-03"]["datasets_with_different_score"]), str(dr["DR-03"]["datasets_moved_at_least_0.005"]), dr["DR-03"]["largest_move"])
    f = {r["group_name"]: r for r in RES["04_issue_classes_and_resolution__fast_team_vs_others"]}
    assert (f["Data Platform"]["mean_hours"], f["all other teams"]["mean_hours"]) == (dr["DR-04"]["fast_mean_hours"], dr["DR-04"]["other_mean_hours"])
    cs = row_of("04_issue_classes_and_resolution__claimed_split")
    assert (cs["leading_claimed_run"], cs["first_not_claimed"], cs["oldest_unresolved_issue"]) == (str(dr["DR-05"]["leading_claimed_run"]), dr["DR-05"]["first_not_claimed"], dr["DR-05"]["oldest_issue"])
    pr = row_of("07_match_precision__precision")
    assert (pr["precision"], pr["reviewed_correct_share"]) == (dr["DR-06"]["precision"], dr["DR-06"]["reviewed_correct_share"])
    assert row_of("03_weight_shift_dr03__rule_changes_near_the_weight_change")["within_14_days_of_the_weight_change"] == "0"
    assert row_of("07_match_precision__candidates")["canonical_distinct_pairs"] == "400" and row_of("07_match_precision__candidates")["reviews_by_the_proposer"] == "0"
    assert {r["rule_id"]: (r["runs_retained"], r["issues_retained"]) for r in RES["04_issue_classes_and_resolution__disabled_rules"]}["r-leads-valid-email"] == ("77", "17")
    assert row_of("08_timeliness_states__by_read_instant", read_no=0)["pending"] == "0"
    # the mutation guard: a one-leaf change to a stored figure would break a reconciliation row, so the rows are not tautologies
    assert all(r["analysis_sql"] == r["second_source"] for r in RES["reconciliation"]) and any(r["third_source"] for r in RES["reconciliation"])


@pytest.mark.skipif(not (os.environ.get("ARTIFACTS_DATABASE_URL") and os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL")),
                    reason="ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts07_*; the test prepares them with data/sql/analysis/prepare_snapshot.py) are not set")
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
        ra.run_script(c, SQL_DIR / "00_measure_rules.sql")
        for prefix in NUMBERED:
            f = next(SQL_DIR.glob(f"{prefix}_*.sql"))
            for key, rows in ra.run_file(c, f).items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key
        for name in ra.BI_FILES:
            for key, rows in ra.run_file(c, SQL_DIR / f"{name}.sql").items():
                csv_name = key.split("__")[-1] if "__" in key else key.removeprefix("bi_")
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == _csv(csv_name), csv_name
    with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        ra.run_script(c, SQL_DIR / "00_measure_rules.sql")
        for key, rows in ra.run_file(c, SQL_DIR / "09_golden_known_answer.sql").items():
            assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key


def test_a_database_rerun_without_the_scratch_urls_is_skipped_with_a_reason():
    marks = [m for m in test_sql_files_rerun_against_the_prepared_databases_give_the_stored_rows.pytestmark if m.name == "skipif"]
    assert marks and "ARTIFACTS_DATABASE_URL" in marks[0].kwargs["reason"] and SCRATCH in marks[0].kwargs["reason"] and "ARTIFACTS_GOLDEN_DATABASE_URL" in marks[0].kwargs["reason"]


def test_scratch_guard_refuses_a_non_scratch_database(prep):
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/trustledger")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts06_snapshot")
    prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts07_snapshot")
    with pytest.raises(SystemExit):
        prep.create_database("postgresql://u:p@127.0.0.1:5432/postgres", "trustledger")
    with pytest.raises(SystemExit):
        prep.drop_database("postgresql://u:p@127.0.0.1:5432/postgres", "trustledger")
    assert prep.SCRATCH_PREFIX == SCRATCH


def test_every_sql_file_has_its_header_and_the_numbered_files_read_only():
    files = sorted(SQL_DIR.glob("[01][0-9]_*.sql"))
    assert [f.name[:2] for f in files] == ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]
    for f in files:
        text = f.read_text()
        if f.name.startswith("00_"):
            assert text.startswith("-- P07-ART-04 setup:"), f.name
        else:
            assert re.match(rf"-- P07-ART-04 investigation {f.name[:2]}:", text), f.name
        assert "D-0" in text or "D-1" in text, f.name
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b", body, re.I), f.name                 # read only
        if not f.name.startswith("00_"):
            assert "CREATE" not in body, f.name
        assert not re.search(r"make_interval\(days", body), f.name
    setup = (SQL_DIR / "00_measure_rules.sql").read_text()
    assert len(re.findall(r"CREATE TEMP TABLE", setup)) == 9 and "CREATE TABLE" not in setup.replace("CREATE TEMP TABLE", "")
    for f in sorted(SQL_DIR.glob("bi_*.sql")):
        assert "P07-ART-06" in f.read_text(), f.name
    assert not re.search(r"(?i)\b(insert|update|delete|drop|alter|create)\b", "\n".join(l for l in "\n".join(f.read_text() for f in SQL_DIR.glob("bi_*.sql")).splitlines() if not l.strip().startswith("--")))
    for f in files:                                                                  # every block of a numbered file is a single statement
        for line in f.read_text().splitlines():
            if line.startswith("-- @@ "):
                assert re.fullmatch(r"-- @@ \w+", line), line


def test_the_measurement_is_the_analysis_own_text_and_not_a_copy_of_the_reference_sql():
    ref = (ROOT / "data/sql/reference_metrics.sql").read_text()
    mine = (SQL_DIR / "00_measure_rules.sql").read_text()
    for token in ("rows_cur", "jsonb_object_agg", "carried AS", "tl2 AS", "FROM comp", "gaps AS"):
        assert token in ref and token not in mine, token
    assert "reference_metrics" not in "\n".join(l for l in mine.splitlines() if not l.startswith("--"))


# ---- the workbook --------------------------------------------------------------------------------------------------------------------------

def _b(v):
    """LibreOffice stores a typed TRUE/FALSE constant as the formula =TRUE() / =FALSE() when it saves the recalculated file; read both forms as the boolean."""
    return {"=TRUE()": True, "=FALSE()": False}.get(v, v)


def _sheet_rows(ws, first: int, last: int, cols: int):
    return [[ws.cell(row=r, column=c).value for c in range(1, cols + 1)] for r in range(first, last + 1)]


def test_workbook_sheets_present_and_assumptions_listed(wb, bw):
    assert wb.sheetnames == bw.SHEET_ORDER
    ws = wb["Assumptions"]
    ids = {ws.cell(row=r, column=1).value for r in range(4, 40)}
    assert {"A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "W-01", "W-02", "W-03", "W-04", "W-05"} <= ids
    text = " ".join(str(ws.cell(row=r, column=2).value) for r in range(4, 40))
    assert "Excel was NOT run" in text and "LibreOffice" in text and "TYPED" in text
    c = wb["Controls"]
    assert c["B3"].value == "w2" and c["B15"].value == "=Checks!B2"
    assert any(dv.formula1 == '"w1,w2"' for dv in c.data_validations.dataValidation)


def test_data_sheets_equal_the_snapshot_and_the_independent_side(wb, ps):
    c = ps.Ctx()
    owners = sorted(c.owners.values(), key=lambda o: o["owner_id"])
    ws = wb["Owners"]
    assert [ws.cell(row=4 + i, column=1).value for i in range(18)] == [o["owner_id"] for o in owners] and [_b(ws.cell(row=4 + i, column=3).value) for i in range(18)] == [bool(o["active"]) for o in owners]
    ds = wb["Datasets"]
    assert [ds.cell(row=4 + i, column=1).value for i in range(40)] == sorted(c.datasets) and ds.cell(row=44, column=1).value is None
    rr = wb["Rule results"]
    ms = sorted(c.ms.values(), key=lambda m: m["rule_id"])
    assert len(ms) == 55
    for i, m in enumerate(ms):
        r = 4 + i
        assert [rr.cell(row=r, column=k).value for k in (1, 2, 3, 4, 5, 6, 7)] == [m["rule_id"], m["dataset_id"], m["dimension"], m["severity"], m["eligible"], m["populated"], m["failing"]], m["rule_id"]
    iss = wb["Issues"]
    assert iss.cell(row=577, column=1).value == "iss-0574" and iss.cell(row=578, column=1).value is None
    assert wb["Lineage"].cell(row=163, column=1).value is not None and wb["Lineage"].cell(row=164, column=1).value is None
    assert wb["Definitions"].cell(row=33, column=1).value is not None and wb["Definitions"].cell(row=34, column=1).value is None
    assert wb["Matching"].cell(row=403, column=1).value == "cand-0400" and wb["Timeliness"].cell(row=18, column=1).value is not None
    wts = wb["Weights"]
    assert [wts.cell(row=4 + i, column=1).value for i in range(2)] == ["w1", "w2"] and abs(sum(wts.cell(row=5, column=c).value for c in range(3, 8)) - 1) < 1e-12


def test_result_cells_of_the_formula_sheets_are_live_formulas_without_hardcoded_figures(wb):
    ds = wb["Dataset scores"]
    for r in range(4, 44):
        for col in range(2, 22):
            v = ds.cell(row=r, column=col).value
            if col in (19, 20):
                assert isinstance(v, str) and v.startswith("='Domain reference'!"), (r, col)
            else:
                assert isinstance(v, str) and v.startswith("="), (r, col, v)
    pf = wb["Portfolio"]
    for r in range(4, 39):
        assert str(pf.cell(row=r, column=2).value).startswith("="), r
        assert str(pf.cell(row=r, column=5).value or "=").startswith("="), r
    iss = wb["Issues"]
    for r in (4, 100, 577):
        for col in range(18, 24):
            assert str(iss.cell(row=r, column=col).value).startswith("="), (r, col)
    for name in ("Lineage", "Definitions", "Timeliness", "Rule results"):
        assert any(str(c.value).startswith("=") for row in wb[name].iter_rows(min_row=4, max_row=6) for c in row if c.value is not None), name
    g = wb["Golden case"]
    for r in range(4, 24):
        for col in (3, 5):
            v = g.cell(row=r, column=col).value
            assert v is None or str(v).startswith("="), (r, col)
    assert wb["Checks"]["B2"].value.startswith("=AND(") and wb.calculation.fullCalcOnLoad


def test_cached_values_equal_the_domain_recomputed_here(wbv, bw, world):
    assert wbv["Checks"]["B2"].value is True and wbv["Controls"]["B15"].value is True and wbv["Checks"]["B5"].value is True and wbv["Checks"]["B6"].value is True
    ds = wbv["Dataset scores"]
    for r in range(4, 44):
        d = ds.cell(row=r, column=1).value
        for col, wv in ((8, "w1"), (10, "w2")):
            want = world[wv].metrics["weighted_score"]["datasets"][d]["value"]
            got = ds.cell(row=r, column=col).value
            if want is None:
                assert got in (None, ""), (d, wv)
            else:
                assert abs(round(got, 6) - float(want)) < 5e-7, (d, wv, got, want)
        assert ds.cell(row=r, column=21).value is True, d
    pf = wbv["Portfolio"]
    d2 = world["w2"].metrics
    want = {"ownership coverage": float(d2["ownership_coverage"]["value"]), "lineage coverage": float(d2["lineage_coverage"]["value"]), "definition coverage": float(d2["definition_coverage"]["value"]),
            "match precision (over approvals)": float(d2["match_precision"]["precision"]), "timeliness": float(d2["timeliness"]["value"]),
            "mean resolution hours (resolved only)": float(d2["resolution_time"]["mean_hours"]),
            "review-correct share (reviewed candidates that are the same entity)": float(d2["match_precision"]["reviewed_correct_share"])}
    seen = {}
    for r in range(4, 39):
        lab = pf.cell(row=r, column=1).value
        if lab in want:
            seen[lab] = pf.cell(row=r, column=2).value
            assert abs(seen[lab] - want[lab]) < (5e-5 if "hours" in lab else 5e-7), lab
        if pf.cell(row=r, column=5).value is not None:
            assert pf.cell(row=r, column=5).value is True, lab
    assert set(seen) == set(want)
    sm = {wbv["Dataset scores"].cell(row=r, column=1).value: wbv["Dataset scores"].cell(row=r, column=2).value for r in range(45, 56)}
    s = row_of("03_weight_shift_dr03__summary")
    assert sm["datasets scored (w1)"] == int(s["datasets_scored"]) and sm["datasets whose score differs between w1 and w2"] == int(s["datasets_with_different_score"])
    assert sm["datasets moved by at least 0.005"] == int(s["datasets_moved_at_least_0_005"]) and abs(sm["largest move (signed)"] - float(s["largest_move"])) < 5e-7
    g = wbv["Golden case"]
    assert abs(g["C19"].value - 0.958116) < 5e-7 and abs(g["C20"].value - 0.963932) < 5e-7 and g["C22"].value is True


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
    assert v["Checks"]["B2"].value is True and v["Controls"]["B15"].value is True and v["Controls"]["B3"].value == "w2"


@needs_lo
@pytest.mark.parametrize("version", ["w1", "w2"])
def test_the_weight_version_switch_is_live_and_the_check_cell_stays_true(tmp_path, world, version):
    flip = openpyxl.load_workbook(XLSX)                         # formulas only: openpyxl drops the cached values on save
    flip["Controls"]["B3"] = version
    src = tmp_path / f"{version}.xlsx"
    flip.save(src)
    assert openpyxl.load_workbook(src, data_only=True)["Checks"]["B2"].value is None          # no cached values until recalculated
    v = openpyxl.load_workbook(_lo_recalc(src, tmp_path / version), data_only=True)
    assert v["Checks"]["B2"].value is True and v["Controls"]["B3"].value == version
    ds = v["Dataset scores"]
    for r in range(4, 44):
        d = ds.cell(row=r, column=1).value
        want = world[version].metrics["weighted_score"]["datasets"][d]["value"]
        got = ds.cell(row=r, column=12).value                          # Selected
        if want is None:
            assert got in (None, ""), d
        else:
            assert abs(round(got, 6) - float(want)) < 5e-7, (d, got, want)
    assert abs(sum(v["Controls"].cell(row=7 + j, column=2).value for j in range(5)) - 1) < 1e-12


def test_pasted_sql_results_sheet_matches_the_stored_results(wb):
    ws = wb["SQL results (pasted)"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    meta = RES["meta"][0]
    assert any(isinstance(c, str) and f"reconciliation rows {meta['reconciliation_rows']}, equal {meta['reconciliation_equal']}" in c and DATASET_HASH in c and CODE_REVISION in c for c in cells)
    w = row_of("01_ds_customers_override_both_weights__weighted", weight_version="w2")
    assert float(w["weighted_score"]) in cells and "w1" in cells and "w2" in cells
    assert float(row_of("07_match_precision__precision")["precision"]) in cells and float(row_of("05_lineage_coverage_evidence__coverage")["coverage"]) in cells
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)               # pasted values, not formulas


# ---- the BI package ------------------------------------------------------------------------------------------------------------------------

def _csv(name: str) -> list[dict]:
    with (ART / "bi" / f"{name}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


BI = ["dim_owner", "dim_dataset", "dim_rule", "dim_weight_version", "dim_date", "dim_metric", "fact_rule_measure", "fact_dataset_score", "fact_issue", "fact_lineage_edge", "fact_candidate", "fact_timeliness"]


def test_bi_exports_have_the_documented_grain_and_equal_the_snapshot(ps):
    c = ps.Ctx()
    sizes = {n: len(_csv(n)) for n in BI}
    assert sizes == {"dim_owner": 18, "dim_dataset": 40, "dim_rule": 60, "dim_weight_version": 2, "dim_date": 85, "dim_metric": 30, "fact_rule_measure": 55, "fact_dataset_score": 80,
                     "fact_issue": 574, "fact_lineage_edge": 160, "fact_candidate": 400, "fact_timeliness": 15}
    assert len({r["issue_id"] for r in _csv("fact_issue")}) == 574 and len({(r["dataset_id"], r["weight_version"]) for r in _csv("fact_dataset_score")}) == 80
    assert {r["dataset_id"] for r in _csv("fact_issue")} <= {r["dataset_id"] for r in _csv("dim_dataset")}
    assert {r["owner_id"] for r in _csv("fact_issue")} <= {r["owner_id"] for r in _csv("dim_owner")}
    assert {r["detected_date"] for r in _csv("fact_issue")} <= {r["date"] for r in _csv("dim_date")}
    assert {r["rule_id"] for r in _csv("fact_rule_measure")} <= {r["rule_id"] for r in _csv("dim_rule")}
    cls = {r["issue_id"]: r["class"] for r in _csv("fact_issue")}
    assert cls == {i["issue_id"]: i["class"] for i in c.issue_rows}
    pend = [r for r in _csv("fact_timeliness") if r["state"] == "pending"]
    assert len(pend) == 0 and {r["state"] for r in _csv("fact_timeliness")} == {"on_time", "late"}
    # nothing withheld silently: an empty weighted score always carries a status; the file never holds a zero score for a dataset that measures nothing
    for r in _csv("fact_dataset_score"):
        if r["weighted_score"] == "":
            assert r["score_status"].startswith("not_measured") and r["measured_dimensions"] == "", r
        else:
            assert r["score_status"] == "measured"
    assert sum(1 for r in _csv("fact_dataset_score") if r["weighted_score"] == "") == 22                       # 11 datasets x 2 versions measure nothing
    for r in _csv("fact_rule_measure"):
        assert (r["score"] == "") == (r["score_status"] != "measured")


def test_bi_measures_recomputed_from_the_csv_files_equal_the_stored_values_and_the_domain(ra, world):
    csvs = {n: _csv(n) for n in BI}
    rows = ra.bi_measures(csvs)
    assert rows == RES["bi_measures"] == _csv("measures_recomputed")
    mv = {(m["measure"], m["slice"]): m for m in rows}
    d2 = world["w2"].metrics
    assert mv[("ownership_coverage", "portfolio")]["value"] == d2["ownership_coverage"]["value"] and mv[("lineage_coverage", "portfolio")]["value"] == d2["lineage_coverage"]["value"]
    assert mv[("definition_coverage", "portfolio")]["value"] == d2["definition_coverage"]["value"] and mv[("timeliness", "portfolio")]["value"] == d2["timeliness"]["value"]
    assert mv[("match_precision", "portfolio")]["value"] == d2["match_precision"]["precision"] and mv[("reviewed_correct_share", "portfolio")]["value"] == d2["match_precision"]["reviewed_correct_share"]
    assert mv[("mean_resolution_hours", "all resolved")]["value"] == d2["resolution_time"]["mean_hours"]
    for wv in ("w1", "w2"):
        for d, x in world[wv].metrics["weighted_score"]["datasets"].items():
            m = mv[("weighted_score", f"{d}|{wv}")]
            assert m["value"] == (x["value"] or ""), (d, wv)
            assert (m["status"] == "value") == (x["value"] is not None)
    assert all(m["status"] != "value" for m in rows if m["value"] == "")                                 # an empty value always says why


def test_bi_package_defines_every_measure_and_makes_no_pbix_claim():
    doc = read("bi-package.md")
    assert "No `.pbix` was produced" in doc and "pseudocode" in doc and "not executed" in doc and "Power BI Desktop is not available here and was not run" in doc
    for m in ("Selected Weight Version", "Dataset Count", "Covered Datasets", "Ownership Coverage", "Uncovered Datasets", "Published Metrics", "Complete Metrics", "Definition Coverage", "Declared Pairs",
              "Observed Matching Declared", "Lineage Coverage", "Undeclared Observed", "Issue Count", "Issues Resolved", "Issues Claimed", "Issues Open", "Resolved Share", "Claimed Share", "Unresolved Issues", "Mean Resolution Hours",
              "Unresolved With Inactive Owner", "Monitored Datasets", "On Time Datasets", "Pending Datasets", "Late Datasets", "Timeliness", "Approved Decisions", "Approved Correct", "Match Precision",
              "Reviewed Candidates", "Reviewed Correct Share", "Decision Agreement Share", "Weighted Score", "Mean Weighted Score", "Score Shift", "Critical Failures", "Critical Override Datasets",
              "Open Critical Issues"):
        assert f"`{m} =" in doc, m
    assert doc.count("DIVIDE") >= 8 and "SELECTEDVALUE" in doc and "BLANK" in doc and "never 0" in doc and "withheld silently" in doc
    for name in BI + ["measures_recomputed"]:
        assert f"`{name}`" in doc and f"artifacts/bi/{name}.csv" in doc, name
    assert DATASET_HASH in doc and CODE_REVISION in doc
    assert not list(ROOT.rglob("*.pbix"))
    sizes = {**{n: len(_csv(n)) for n in BI}, "measures_recomputed": len(RES["bi_measures"])}
    for name, rows in sizes.items():
        assert re.search(rf"\| `{name}` \|[^\n]*\| {rows:,} \|", doc), name


# ---- data dictionary, ERD, SQL analysis document -------------------------------------------------------------------------------------------------------------

def _tables_and_columns() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    pat = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", re.S)
    col = re.compile(r"(?m)^\s*([a-z_0-9]+)\s+(TEXT\[\]|TEXT|INT|BOOLEAN|TIMESTAMPTZ|JSONB|NUMERIC\(\d+,\d+\))")
    for path in ("data/migrations/0001_schema.sql", "data/migrations/0003_review_r7.sql", "data/sql/verification_truth.sql"):
        for m in pat.finditer((ROOT / path).read_text()):
            out[m.group(1)] = col.findall(m.group(2)) and [c[0] for c in col.findall(m.group(2))]
    out["dataset_rows"] += re.findall(r"ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS (\w+)", (ROOT / "data/migrations/0003_review_r7.sql").read_text())
    out["schema_migrations"] = ["version", "checksum", "applied_at"]
    assert "schema_migrations (" in (ROOT / "data/migrate.py").read_text()
    return out


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations():
    tables = _tables_and_columns()
    assert len(tables) == 26
    dd, erd = read("data-dictionary.md"), read("erd.md")
    assert "```mermaid" in erd and "erDiagram" in erd
    section2 = dd.split("## 2. Columns", 1)[1].split("\n## 3.", 1)[0]
    heads = {}
    for block in section2.split("\n### ")[1:]:
        title, body = block.split("\n", 1)
        heads[title.strip()] = body
    for t, cols in tables.items():
        assert f"`{t}`" in dd, t
        assert re.search(rf"^\s+{t} \{{", erd, re.M), t
        assert t in heads, t
        for c in cols:
            assert f"`{c}`" in heads[t], (t, c)
            assert re.search(rf"^\s+[\w()\[\]]+ {c}\b", erd, re.M), (t, c)
    for key in ("grain", "Deletion policy", "Append-only events and versioned definitions", "append-only", "rejected_records", "Source-to-target", "Foreign keys", "verification_truth", "ledger_config", "row_version",
                "candidates_canonical_ck", "tl_issue_guard", "synthetic", "owner", "source file", "weights_valid_ck"):
        assert key.lower() in dd.lower(), key
    counts = {"owners": "18", "datasets": "40", "fields": "420", "dataset_rows": "2,554", "quality_rules": "60", "quality_rule_versions": "75", "rule_weight_versions": "2", "rule_runs": "4,609",
              "issues": "574", "issue_events": "1,328", "lineage_edges": "160", "metric_versions": "45", "definition_changes": "15", "customer_records": "2,000", "match_candidates": "400",
              "merge_decisions": "235", "rejected_records": "0", "audit_events": "0", "command_results": "0", "dataset_versions": "1", "verification_truth": "2,000"}
    for k, v in counts.items():
        assert re.search(rf"\| `{k}` \|[^\n]*\| {v}[ (|]", dd), k
    assert DATASET_HASH in dd and CODE_REVISION in dd and DATASET_HASH in erd and CODE_REVISION in erd
    manifest = json.loads((ROOT / "web/public/data/manifest.json").read_text())
    for k, v in manifest["row_counts"].items():
        if k in counts:
            assert counts[k] == f"{v:,}", k


def test_sql_analysis_doc_quotes_the_stored_results_and_every_table_is_rendered_from_them(P):
    render = _load("tl_render", ART / "render_sql_analysis.py")
    for name in ("sql-analysis.md", "bi-package.md"):
        text = read(name)
        assert render.render(text, RES) == text, f"{name} drifted from artifacts/analysis-results.json: run artifacts/render_sql_analysis.py"
        assert "(to be rendered)" not in text
    doc = read("sql-analysis.md")
    for key in list(P) + [k for k in RES if k.startswith("09_golden_known_answer__")]:
        assert f"<!-- BEGIN:{key} -->" in doc, key
    assert "<!-- BEGIN:reconciliation -->" in doc and DATASET_HASH in doc and CODE_REVISION in doc
    for sentence in ("constructed", "observed", "hypothetical", "Excel and Power BI were not run", "which data issues should be fixed first, and who is accountable", "decision-agreement share", "Mutation check",
                     "All twelve injected defects appear in the reconciliation", "stated rule", "claimed", "pending"):
        assert sentence in doc, sentence
    for v in ("**13 of 29** scored datasets", "**-0.167477**", "0.990329", "0.990175", "**0.875000**", "**66 unresolved issues**", "**315 of 574**", "**68.2716**", "**34.4202**", "**86.1833**", "**0.399384**",
              "**58**", "**0.725000**", "**23 of 30**", "**0.766667**", "172 of the 174 approvals are right: precision 0.988506", "185 of 220 = 0.840909", "205 of 220 (0.931818)", "10 are on time and 5 late (0.666667)",
              "309.5667 hours", "7 of the first 15", "3 of 15", "the 65th, `iss-0252`"):
        assert v in doc, v
    n = RES["meta"][0]["reconciliation_rows"]
    assert f"all {n} rows are equal again" in doc


def test_the_documents_name_the_real_entities_metrics_and_commands_and_keep_result_kinds_apart():
    case = read("business-case.md")
    for token in ("Which data issues should be fixed first, and who is accountable", "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12", "register-dataset", "publish-definition", "run-rule",
                  "open-issue", "triage-issue", "suggest-match", "approve-merge", "reverse-merge", "disable-rule", "verify-remediation", "correct-dataset-rows", "record-refresh", "owners", "datasets", "quality_rules",
                  "rule_runs", "issues", "lineage_edges", "metric_versions", "merge_decisions", "verification_truth", "P07-MET-", "P07-FLOW-", "P07-TEST-", "P07-DOMAIN-", "observed", "constructed",
                  "hypothetical", "Decision criteria", "Current-state", "Future", "Simulated stakeholders", DATASET_HASH, CODE_REVISION, "0.990175", "0.875000", "Mode A and Mode B", "DR-01..DR-06", "INJ-01..INJ-12"):
        assert token in case, token
    assert "no figure below is one" in case and "Excel" in case and "Power BI" in case
    assert "claim about a real organisation" in case


def test_requirements_trace_every_requirement_family():
    req = read("requirements.md")
    for fam in ("P07-GOAL", "P07-DOMAIN-01", "P07-DOMAIN-06", "P07-GOLD-01", "P07-DATA-01..12", "P07-MET-01", "P07-MET-12", "P07-FLOW-01", "P07-FLOW-10", "P07-UI-01", "P07-UI-10", "P07-TEST-01", "P07-TEST-12",
                "P07-ART", "P07-REL"):
        assert fam in req, fam
    assert "functional requirements" in req.lower() and "Non-functional requirements" in req and "User stories" in req and "Traceability" in req
    for run in ("40448066870", "40439001518", "40439868137", "40433219610", "40436104537"):
        assert run in req, run
    tests_text = all_test_names()
    named = set(re.findall(r"`(test_[a-zA-Z0-9_]+)`", req))
    assert len(named) > 60
    for doc in ("requirements.md", "technical-case-study.md", "uat-evidence.md", "executive-memo.md", "release-package.md"):
        for t in set(re.findall(r"`(test_[a-zA-Z0-9_]+)`", read(doc))):
            assert f"def {t}(" in tests_text, f"{doc} cites a test that does not exist: {t}"
    spec = (ROOT / "web/e2e/journey.spec.ts").read_text()
    titles = re.findall(r'"((?:landing|every route|scorecard|catalog|glossary|rules|issues|lineage|duplicates|merges|impact|evidence|case study)[^"]*)"', req)
    assert len(titles) >= 12
    for t in titles:
        assert f'"{t}"' in spec, t
    for doc in ("uat-evidence.md",):
        for t in re.findall(r'e2e "([^"]+)"', read(doc)):
            assert f'"{t}"' in spec, t
    assert DATASET_HASH in req and CODE_REVISION in req and "deferred" in req and "not_checked" in req and "pending" in req
    for fam in ("P07-MET-%02d" % i for i in range(1, 13)):
        assert fam in req, fam
    for fam in ("P07-FLOW-%02d" % i for i in range(1, 11)):
        assert fam in req, fam
    for fam in ("P07-TEST-%02d" % i for i in range(1, 13)):
        assert fam in req, fam
    assert "no-skip gate" in req and "hosted runner" in req


def test_executive_memo_quotes_the_evidence_options_and_the_caveats():
    memo = read("executive-memo.md")
    for token in ("OBSERVED", "SIMULATED", "HYPOTHETICAL", "## Decision", "| Option |", "## Evidence", "## Uncertainty", "## Limitations", "## Recommendation", "iss-0461", "own-07", "0.990175", "0.990329",
                  "**0.875000**", "66 unresolved issues", "**315 resolved**", "**99 claimed**", "**160 open**", "**34.4202**", "**86.1833**", "**0.725000**", "**23 of 30**", "**0.988506**", "**0.840909**",
                  "0.931818", "**0.666667**", "-0.167477", "One draw", "disclosed in the manifest", "Excel and Power BI were not run", "does not support any statement about a realised benefit", "ds-tickets",
                  "175 rows", DATASET_HASH, CODE_REVISION, "judgement", "7 of its first 15"):
        assert token in memo, token
    assert not re.search(r"\b(saves?|saved|savings of|roi)\b", memo, re.I)
    assert memo.count("| **") >= 1 and "(recommended)" in memo


def test_uat_evidence_has_routes_screenshots_scenarios_and_run_links():
    uat = read("uat-evidence.md")
    for token in ("40448066870", "40439001518", "40439868137", "0b5d686", "e205202", "031705d", "77665db", "pending", "did **not** run `npm run e2e`", "not fetched", "expected answer",
                  "actual observation", "disposition", "Defect disposition", "R7-01", "R7-08", DATASET_HASH):
        assert token.lower() in uat.lower() or token in uat, token
    for route in ("`/`", "`/catalog/`", "`/glossary/`", "`/scorecard/`", "`/rules/`", "`/issues/`", "`/lineage/`", "`/duplicates/`", "`/merges/`", "`/impact/`", "`/evidence/`", "`/case-study/`"):
        assert route in uat, route
    routes_ts = (ROOT / "web/src/routes.ts").read_text()
    for p in re.findall(r'path: "([a-z-]+)"', routes_ts):
        assert f"`/{p}/`" in uat, p
    for shot in ("home", "catalog", "glossary", "scorecard", "scorecard-golden", "rules", "issues", "lineage", "duplicates", "merges", "impact", "evidence", "case-study"):
        assert f"`{shot}`" in uat, shot
    assert "-zoom200.png" in uat and "65 files" in uat
    for s in range(1, 14):
        assert f"| S{s} |" in uat, s
    idx = ROOT / "web" / "evidence" / "index.json"
    if idx.exists():
        data = json.loads(idx.read_text())
        assert data["count"] == 65 and all(s["scrollWidth"] <= s["innerWidth"] for s in data["shots"])
    rep = ROOT / "web" / "evidence" / "playwright-report.json"
    if rep.exists():
        st = json.loads(rep.read_text())["stats"]
        assert (st["expected"], st["unexpected"], st["flaky"], st["skipped"]) == (80, 0, 0, 0)
    assert "created by this pass" in uat.lower() or "Created by this pass" in uat


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    tcs, rel = read("technical-case-study.md"), read("release-package.md")
    for token in ("Architecture", "Trade-offs", "Recovery behaviour", "Reproducible setup", "Measured evidence", "Open gaps", "```mermaid", "R7-01", "R7-08", "1e0283f", "40448066870", "40439001518", "40439868137",
                  "e205202", "031705d", DATASET_HASH, CODE_REVISION, "175 reconciliation rows", "Excel and Power BI Desktop were not run", "no hosted run of `tests/test_artifacts.py` is recorded yet", "805", "405"):
        assert token in tcs or token.lower() in tcs.lower(), token
    for token in ("e205202", "031705d", "77665db", "0b5d686869f289681a795b022e185a1eb614c1d0", "40448066870", "40439001518", "40439868137", "pending at dispatch", "Rollback procedure", "git revert", "Artifacts and checksums",
                  DATASET_HASH, "7221af120c136f7c1c39d7b953a6fe5699594173798938e94889a896ec7a796d", "committed and pushed nothing", "Main-portfolio metadata", "Excel", "Power BI", "205 of the 220", "0.947368",
                  "not fetch", "What this artifact pass ran", "private"):
        assert token in rel, token
    assert "lab:lab" not in rel and "RUN_LOG_PLACEHOLDER" not in rel
    if shutil.which("git"):
        for c in ("e205202", "031705d", "77665db", "0b5d686", "1e0283f", "78a4390"):
            probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", c], capture_output=True, text=True)
            if probe.returncode != 0:
                pytest.skip(f"commit {c} is not in this checkout")
        for c, subj in (("0b5d686", "Ledgers: TrustLedger fixes accepted"), ("1e0283f", "TrustLedger: review R7 fixes")):
            assert subj in subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%s", c], capture_output=True, text=True).stdout
    manifest = json.loads((ROOT.parents[1] / "docs" / "program" / "release-manifest.json").read_text()) if (ROOT.parents[1] / "docs" / "program" / "release-manifest.json").exists() else None
    if manifest:
        site = next(s for s in manifest["sites"] if s["slug"] == "trustledger")
        assert site["release_commit_unified_portfolio"] == "e205202" and site["rollback_commit_unified_portfolio"] == "031705d" and site["source_commit_business_data_lab"].startswith(CODE_REVISION)
        assert site["dataset_hash"] == DATASET_HASH and site["published_tree_sha256"] in rel
        if site["live_verification"] is None:
            assert "pending at dispatch" in rel


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact_and_match_the_public_case_study():
    text = read("resume-bullets.md")
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6
    body = " ".join(bullets)
    assert not re.search(r"\b(saved|savings|reduced (?:cost|time)|increased revenue|users|customers? adopted|adoption of|roi)\b", body, re.I)
    for token in ("D-01..D-10", "805-check", "405 Python tests", "R7-01..R7-08", "175 reconciliation rows", "LibreOffice", "no `.pbix`", "0.990175", "0.988506", "0.840909", "2,539", "58 review checks", "80 Playwright"):
        assert token in body, token
    assert "synthetic" in text.lower() and "no bullet claims business impact" in text
    assert str(RES["meta"][0]["reconciliation_rows"]) in body
    if PROJECT:
        tech = " ".join(PROJECT["tech"])
        assert "405 Python tests" in tech and "2,539 TypeScript golden" in tech and "58 review checks" in tech and "80 browser tests" in tech


def test_public_case_study_figures_agree_with_the_stored_results():
    if PROJECT is None:
        pytest.skip("the public case study /trustledger/project.json is not in this checkout (it lives on unified-portfolio)")
    text = re.sub(r"<[^>]+>", " ", PROJECT["results"] + PROJECT["built"] + PROJECT["tagline"]).replace("−", "-")
    w = {r["weight_version"]: r["weighted_score"] for r in RES["01_ds_customers_override_both_weights__weighted"]}
    assert f"ds-customers scores {w['w2']} ({w['w1']} under the earlier one)" in text
    assert f"coverage {row_of('02_ownership_coverage__summary')['coverage']}" in text
    sm = row_of("03_weight_shift_dr03__summary")
    assert f"{sm['datasets_with_different_score']} of the {sm['datasets_scored']} scored datasets differ" in text and sm["largest_move"] in text
    cl = {r["class"]: r["issues"] for r in RES["04_issue_classes_and_resolution__classes"]}
    assert f"{cl['resolved']} are resolved by a verifying rerun, {cl['claimed']} were closed without one" in text and f"{cl['open']} are open" in text
    assert f"the {row_of('04_issue_classes_and_resolution__claimed_split')['leading_claimed_run']} oldest unresolved issues are all claims" in text
    f = {r["group_name"]: r for r in RES["04_issue_classes_and_resolution__fast_team_vs_others"]}
    assert f["Data Platform"]["mean_hours"] in text and f["all other teams"]["mean_hours"] in text
    lc = row_of("05_lineage_coverage_evidence__coverage")
    assert f"Of {lc['declared_pairs']} declared lineage edges {lc['observed_matching_declared']} were observed (coverage {lc['coverage']})" in text and f"{lc['undeclared_observed']} observed edges are undeclared" in text
    dc = row_of("06_definition_coverage__summary")
    assert f"({dc['coverage']})" in text and f"fifteen carry more than one version" in text
    pr = row_of("07_match_precision__precision")
    assert f"{pr['approved_correct']} of the {pr['approved']} approvals are right" in text
    assert pr["precision"] in text
    # the two wording points reported to the coordinator: the decision-agreement count is quoted as such, and a stale golden relationship figure
    assert f"{pr['decisions_agreeing_with_truth']} of the {pr['reviewed']} reviews" in text and pr["reviewed_correct_share"] not in text
    rel = read("release-package.md")
    assert "true but ambiguous" in rel
    if "relationship integrity 0.947368 with two null foreign keys" in text:
        assert "**stale**" in rel
    assert PROJECT["repo"].endswith("apps/trustledger") and PROJECT["date"] == "2026-10"


def test_no_credentials_or_secrets_in_the_artifact_documents_and_files():
    docs = ["business-case.md", "requirements.md", "data-dictionary.md", "erd.md", "sql-analysis.md", "workbook.md", "bi-package.md", "executive-memo.md", "technical-case-study.md",
            "release-package.md", "resume-bullets.md", "uat-evidence.md"]
    for d in docs:
        text = read(d)
        assert "lab:lab" not in text, d
        assert not re.search(r"postgres(ql)?://[^<\s]*:[^<\s@]+@", text), d
        assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S{12,}", text), d
    for p in list(ART.glob("*.json")) + list((ART / "bi").glob("*.csv")) + [ART / "CHECKSUMS.txt"] + list(SQL_DIR.glob("*.sql")):
        assert "postgresql://" not in p.read_text(), p.name
        assert "lab:lab" not in p.read_text(), p.name
    wbtext = " ".join(str(c.value) for ws in openpyxl.load_workbook(XLSX).worksheets[:8] for row in ws.iter_rows() for c in row if c.value)
    assert "postgresql://" not in wbtext and "password" not in wbtext.lower()
    py = (SQL_DIR / "prepare_snapshot.py").read_text()
    assert "lab:lab@127.0.0.1" in py                                          # the local development login of the CI workflow is the one documented default; it is not in any document


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = read("workbook.md")
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "trustledger-analyst-workbook.xlsx" in doc and "openpyxl 3.1.5" in doc
    for sheet in ("Read me", "Controls", "Checks", "Portfolio", "Dataset scores", "Golden case", "Assumptions", "Rule results", "Issues", "Owners", "Datasets", "Lineage", "Definitions", "Matching",
                  "Timeliness", "Weights", "Domain reference", "SQL results (pasted)"):
        assert f"`{sheet}`" in doc, sheet
    assert "Controls!B3" in doc and "w1" in doc and "w2" in doc and "fullCalcOnLoad" in doc and "How to read it without installing" in doc and "Checks!B2" in doc
    for v in ("0.990329", "0.990175", "0.875000", "68.2716", "34.4202", "86.1833", "0.725000", "0.766667", "0.988506", "0.840909", "0.931818", "0.666667", "-0.167477"):
        assert v in doc, v
    assert (ROOT / "requirements-artifacts.txt").read_text().strip() == "openpyxl==3.1.5"


def test_every_document_cites_the_dataset_hash_and_the_code_revision_and_says_it_is_synthetic():
    names = ["business-case.md", "requirements.md", "data-dictionary.md", "erd.md", "sql-analysis.md", "workbook.md", "bi-package.md", "executive-memo.md", "uat-evidence.md",
             "technical-case-study.md", "release-package.md", "resume-bullets.md"]
    assert len(names) == 12
    for n in names:
        text = read(n)
        assert DATASET_HASH in text and CODE_REVISION in text, n
        assert "synthetic" in text.lower(), n
        if n not in ("resume-bullets.md", "erd.md"):
            assert "without installing" in text or "needs nothing installed" in text, n                  # a brief read/use instruction (P07-ART-xx-R12)
    assert "Read the text lists below the diagram" in read("erd.md")


def test_the_ci_no_skip_gate_and_the_unrun_tools_are_disclosed():
    req, rel, tcs = read("requirements.md"), read("release-package.md"), read("technical-case-study.md")
    ci = (ROOT.parents[1] / ".github" / "workflows" / "trustledger-ci.yml")
    if ci.exists():
        assert 'skipped="0"' in ci.read_text() or "skipped" in ci.read_text()
    for doc in (req, rel, tcs):
        assert "skip" in doc.lower() and "LibreOffice" in doc
    assert "not attached to a GitHub release" in rel and "Excel" in rel and "Power BI" in rel


def test_provenance_the_analysed_code_and_data_equal_revision_0b5d686():
    """The numbers describe revision 0b5d686: the domain, API, migrations, loaders, reference SQL, published data, fixtures and the other tests are unchanged since
    (docs/contracts.md and the other documents are deliberately not part of the check: wording fixes there move no number)."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", CODE_REVISION], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"revision {CODE_REVISION} is not in this checkout")
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", CODE_REVISION, "--", "domain", "api", "data/migrations", "data/seed.py", "data/migrate.py", "data/generate.py",
                        "data/sql/reference_metrics.sql", "data/sql/verification_truth.sql", "web/public", "web/src", "tests", ":(exclude)tests/test_artifacts.py", "docs/contracts.md", "README.md"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "", r.stdout
    manifest = json.loads((ROOT / "web/public/data/manifest.json").read_text())
    assert manifest["dataset_hash"] == DATASET_HASH and manifest["dataset_version"] == "tl-20261026-20261026"
    full = subprocess.run(["git", "-C", str(ROOT), "rev-parse", CODE_REVISION], capture_output=True, text=True).stdout.strip()
    assert full == "0b5d686869f289681a795b022e185a1eb614c1d0"


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
    chk = _load("tl_checksums", ART / "checksums.py")
    assert sorted(listed) == chk.files()                                  # every artifact and doc, nothing stale
    for must in ("artifacts/trustledger-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py", "artifacts/render_sql_analysis.py", "artifacts/checksums.py",
                 "requirements-artifacts.txt", "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
                 "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md", "docs/business-case.md", "docs/requirements.md", "docs/uat-evidence.md",
                 "docs/contracts.md", "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py", "data/sql/analysis/python_side.py", "artifacts/bi/fact_issue.csv",
                 "artifacts/bi/dim_date.csv", "artifacts/bi/measures_recomputed.csv"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("[01][0-9]_*.sql")) + sorted(SQL_DIR.glob("bi_*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    assert "docs/release-package.md" not in listed and "artifacts/CHECKSUMS.txt" not in listed
    rel_doc = read("release-package.md")
    for rel, digest in listed.items():
        assert f"| `{rel}` | `{digest}` |" in rel_doc, rel               # release-package.md carries the same table (it cannot list itself)
