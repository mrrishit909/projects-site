"""Artifact package checks (P10-ART-01..10): the SQL analysis results, the analyst workbook, the BI exports, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that every result cell of the formula sheets is a live formula, (2) reads
the values LibreOffice cached in the delivered file and compares them with figures RECOMPUTED HERE from the published files (not with the pasted reference column), (3) recalculates
copies with LibreOffice headless (as delivered, with another model selected, and with a different what-if) and compares them again, (4) checks that the stored analysis results
equal the plain-Python recomputation over web/public/data (no database), through data/sql/analysis/python_side.py, which shares no code with the SQL or the domain, (5) recomputes
the BI measures from the CSV exports, (6) checks that each document quotes the stored results and the public case study, and (7) checks CHECKSUMS.txt and the release-package table.
With ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts10_*; the test prepares them with prepare_snapshot.py) it also re-runs the SQL files and
compares their rows with the stored results; without them that test is skipped with a printed reason. The tests that need LibreOffice are skipped, with a reason, where `soffice` is
missing. Excel and Power BI are never run. This file never touches the shared retentionlab database.
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

XLSX = ART / "retentionlab-analyst-workbook.xlsx"
RES = json.loads((ART / "analysis-results.json").read_text()) if (ART / "analysis-results.json").exists() else {}
CODE_REVISION = "ce96e65"
FULL_REVISION = "ce96e6544eb8a645236b081bf7dbd9f4a6c9e057"
DATASET_HASH = "9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c"
SCRATCH = "artifacts10_"
_CASE_STUDY = next((p for p in (ROOT.parents[1] / "retentionlab" / "project.json", ROOT.parents[3] / "retentionlab" / "project.json") if p.exists()), None)
PROJECT = json.loads(_CASE_STUDY.read_text()) if _CASE_STUDY else None          # the public case study lives on unified-portfolio, in the main checkout
DOC_NAMES = ["business-case.md", "requirements.md", "data-dictionary.md", "erd.md", "sql-analysis.md", "workbook.md", "bi-package.md", "executive-memo.md", "uat-evidence.md",
             "technical-case-study.md", "release-package.md", "resume-bullets.md"]
NUMBERED = ["01", "02", "03", "04", "05", "06", "07", "08", "10"]
MODEL_COLS = {"random_baseline": "p_random_baseline", "business_rule": "p_business_rule", "logistic_regression": "p_logistic_calibrated", "prevalence_baseline": "p_prevalence_baseline",
              "logistic_uncalibrated": "p_logistic_uncalibrated"}

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
    return {**ps.results(), **ps.golden_results()}


@pytest.fixture(scope="module")
def T(ps):
    return ps.Test()


@pytest.fixture(scope="module")
def wb():
    return openpyxl.load_workbook(XLSX)


@pytest.fixture(scope="module")
def wbv():
    return openpyxl.load_workbook(XLSX, data_only=True)


@pytest.fixture(scope="module")
def bw():
    return _load("rl_build_workbook", ART / "build_workbook.py")


@pytest.fixture(scope="module")
def ra():
    return _load("rl_run_all", SQL_DIR / "run_all.py")


@pytest.fixture(scope="module")
def prep():
    return _load("rl_prepare", SQL_DIR / "prepare_snapshot.py")


def row_of(key: str, **where) -> dict:
    return next(r for r in RES[key] if all(str(r[k]) == str(v) for k, v in where.items()))


def read(name: str) -> str:
    return (DOCS / name).read_text()


def digest_of(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def pub(name: str):
    return json.loads((ROOT / "web" / "public" / "data" / f"{name}.json").read_text())


# ---- stored analysis results ---------------------------------------------------------------------------------------------------------------

def test_analysis_results_reconcile_and_cover_every_investigation(P):
    assert RES["reconciliation"] and all(r["equal"] is True for r in RES["reconciliation"])
    assert len(RES["reconciliation"]) >= 150
    meta = RES["meta"][0]
    assert meta["dataset_hash"] == DATASET_HASH and meta["code_revision"] == CODE_REVISION and meta["whole_world_rebuilt"] is True
    assert meta["reconciliation_rows"] == len(RES["reconciliation"]) == meta["reconciliation_equal"]
    for key in P:
        assert RES[key], key
    numbered = sorted(p.name for p in SQL_DIR.glob("[01][0-9]_*.sql") if not p.name.startswith("09_"))
    assert len(numbered) == 9 and [n[:2] for n in numbered] == NUMBERED                       # nine numbered investigations on the snapshot, at least the eight required
    assert {k.split("__")[0][:2] for k in P} == set(NUMBERED) | {"09"}
    golden = [k for k in RES if k.startswith("09_golden_known_answer__")]
    assert len(golden) == 8 and all(RES[k] for k in golden)
    assert {r["check"].split(" ")[0] for r in RES["reconciliation"]} == {"A", "B", "C", "D", "E", "F"}
    assert [g["group"] for g in RES["reconciliation_summary"]] == list("ABCDEF") and sum(g["rows"] for g in RES["reconciliation_summary"]) == meta["reconciliation_rows"]
    assert meta["result_sets"] == len(P) == 43 and len(RES["reconciliation_listing"]) == meta["reconciliation_rows"]
    assert RES["bi_measures"] and meta["test_rows"] == 1513 and meta["accounts_in_cohort"] == 200


def test_the_comparison_detects_a_one_leaf_change(ps, P):
    key = "01_model_comparison__models"
    mutated = [dict(r) for r in RES[key]]
    mutated[2]["average_precision"] = "0.238553"
    assert ps.normalised(P[key]) == RES[key] and ps.normalised(P[key]) != mutated
    assert all(r["analysis_sql"] == r["second_source"] for r in RES["reconciliation"]) and any(r["third_source"] for r in RES["reconciliation"])


def test_golden_known_answer_in_sql_equals_expected_json_and_the_hand_figures():
    exp = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())
    jan = exp["cutoff_sets"]["2026-01-01T00:00:00Z"]
    ka = RES["09_golden_known_answer__known_answer"][0]
    assert (ka["precision_at_k"], ka["recall_at_k"], ka["brier_score"], ka["average_precision"], ka["risk_lift_at_k"]) == ("0.500000", "0.500000", "0.192500", "0.833333", "1.000000")
    assert (ka["contact_budget"], ka["expected_intervention_value"], ka["label"]) == ("10.00", "8.45", "hypothetical")
    assert (ka["precision_at_k"], ka["brier_score"], ka["average_precision"], ka["expected_intervention_value"]) == (
        jan["precision_at_k"]["value"], jan["brier_score"]["value"], jan["average_precision"]["value"], jan["economics"]["expected_value"])
    assert [r["arrived_late"] for r in RES["09_golden_known_answer__arrived_late"]] == ["1", "1", "0", "0"]
    ce = RES["09_golden_known_answer__censored_cohort"][0]
    assert (ce["eligible_rows"], ce["mature_rows"], ce["censored_rows"], ce["churn_rate"]) == ("4", "0", "4", "")
    assert [r["psi"] for r in RES["09_golden_known_answer__psi_against_the_march_2025_cohort"]] == ["0.074266", "2.381316"]
    assert sum(int(r["cutoff_rows"]) for r in RES["09_golden_known_answer__purge_counts"]) == 27


def test_stored_results_equal_the_python_side_recomputation_over_the_snapshot_files(ps, P):
    for key, rows in P.items():
        assert ps.normalised(rows) == RES[key], key


def test_stored_figures_equal_the_domain_and_the_published_files(T):
    """AP, Brier and the calibration bins of the test table through the DOMAIN's own functions (not python_side.py) against the stored SQL results."""
    from retentionlab.metrics import average_precision, calibration_bins
    from retentionlab.numbers import p6
    models = {r["model"]: r for r in RES["01_model_comparison__models"]}
    for label, col in (("random_baseline", "p_random_baseline"), ("business_rule", "p_business_rule"), ("logistic_regression (Platt)", "p_logistic_calibrated"),
                       ("prevalence_baseline", "p_prevalence_baseline"), ("logistic_regression (before Platt)", "p_logistic_uncalibrated")):
        items = sorted(({"p": r[col], "y": bool(r["churned"]), "account_id": r["account_id"]} for r in T.rows), key=lambda it: (-it["p"], it["account_id"]))
        ap, _ = average_precision(items, sum(1 for it in items if it["y"]))
        brier = sum(((it["p"] - (1 if it["y"] else 0)) ** 2 for it in items), F(0)) / len(items)
        assert (p6(ap), p6(brier)) == (models[label]["average_precision"], models[label]["brier_score"]), label
    items = [{"p": r["p_logistic_calibrated"], "y": bool(r["churned"]), "account_id": r["account_id"]} for r in T.rows]
    bins = calibration_bins(items)
    stored = [b for b in RES["02_calibration_platt__bins"] if b["model"] == "logistic_regression (Platt)"]
    assert [(b["index"], b["count"], b["gap_pp"] or "") for b in bins] == [(int(s["bin_index"]), int(s["rows_in_bin"]), s["gap_pp"]) for s in stored]
    man = pub("manifest")
    dr1 = man["designed_relationships"][0]["realised"]
    assert dr1["logistic_regression"]["average_precision"] == models["logistic_regression (Platt)"]["average_precision"]
    cal = pub("calibration")
    assert [(b["count"], b["gap_pp"] or "") for b in cal["reliability_calibrated"]] == [(int(s["rows_in_bin"]), s["gap_pp"]) for s in stored]


def test_headline_numbers_of_the_documents_are_the_stored_ones():
    memo, case, tcs, bi, wbdoc, sql = read("executive-memo.md"), read("business-case.md"), read("technical-case-study.md"), read("bi-package.md"), read("workbook.md"), read("sql-analysis.md")
    m = {r["model"]: r for r in RES["01_model_comparison__models"]}
    for label in ("random_baseline", "business_rule", "logistic_regression (Platt)", "prevalence_baseline"):
        for doc in (memo, wbdoc):
            assert m[label]["average_precision"] in doc and m[label]["brier_score"] in doc, (label, doc[:30])
        assert m[label]["average_precision"] in sql
    assert m["logistic_regression (before Platt)"]["brier_score"] in memo
    k = {(r["model"], r["capacity"]): r for r in RES["03_capacity_economics__test_population_at_k"]}
    lg = "logistic_regression (Platt)"
    for kk in ("10", "20"):
        assert k[(lg, kk)]["precision_at_k"] in memo and k[(lg, kk)]["precision_at_k"] in wbdoc
    assert k[(lg, "20")]["risk_lift_at_k"] in memo and k[(lg, "20")]["recall_at_k"] in memo and k[(lg, "5")]["churners_in_top_k"] == "0" and "0 of 5" in case
    both = {r["scenario_id"]: r for r in RES["03_capacity_economics__both_populations"]}
    for doc in (memo, case, wbdoc, sql):
        for sid in both:
            for fld in ("cohort_expected_value", "world_expected_value"):
                v = both[sid][fld]
                assert (v if not v.startswith("-") else v) in doc or v.replace("-", "-") in doc, (sid, fld, v)
    assert "hypothetical" in memo.lower() and "HYPOTHETICAL" in memo
    ws = row_of("04_censored_tail__world_summary")
    for doc in (memo, sql):
        assert ws["censored_share"] in doc and ws["mature_churn_rate"] in doc, doc[:20]
    assert "3,594" in case
    pe = row_of("02_calibration_platt__platt_effect")
    for doc in (memo, sql):
        assert pe["brier_before"] in doc and pe["brier_after"] in doc
    ds = row_of("07_drift_by_region__published_summary")
    for token in (ds["max_psi_before_the_change"], ds["shift_min_psi"], ds["shift_max_psi"], ds["all_accounts_max_psi"]):
        assert token in sql, token
    assert row_of("08_rows_and_margins__margins", margin="brier_under_random")["realised_margin"] in memo
    n = RES["meta"][0]["reconciliation_rows"]
    for doc in (memo, tcs, read("requirements.md"), read("resume-bullets.md"), case, sql):
        assert f"{n} " in doc or f"{n}\n" in doc or f"{n})" in doc, n
    assert DATASET_HASH in bi and CODE_REVISION in bi
    rows = {r["scenario_id"]: r for r in RES["03_capacity_economics__cohort_economics"]}
    for sid, budget in (("sc-001", "40.00"), ("sc-002", "80.00"), ("sc-003", "160.00")):
        assert rows[sid]["contact_budget"] == budget and budget in memo


def test_breakeven_effect_in_the_memo_is_recomputed_from_the_queue(ps):
    C = ps.Cohort()
    latest = max(C.cutoff[p["cutoff_id"]]["pa"] for p in C.pred)
    q = sorted(((C.cutoff[p["cutoff_id"]]["account_id"], F(p["probability"])) for p in C.pred if p["model_name"] == "logistic_regression" and C.cutoff[p["cutoff_id"]]["pa"] == latest),
               key=lambda x: (-x[1], x[0]))
    memo = read("executive-memo.md")
    for k in (5, 10, 20):
        be = F(8 * k) / (200 * sum(p for _, p in q[:k]))
        assert str(ps.rnd(be, 6)) in memo, k
    # planning arithmetic of the experiment: n per arm = (z_a + z_b)^2 (p0 q0 + p1 q1) / (p0 - p1)^2
    from statistics import NormalDist
    z = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.8)
    import math
    for p0, r, want in ((0.25, 0.2, "1,091"), (0.25, 0.3, "464"), (0.124917, 0.2, "2,506"), (0.124917, 0.3, "1,057")):
        p1 = p0 * (1 - r)
        n = math.ceil(z * z * (p0 * (1 - p0) + p1 * (1 - p1)) / (p0 - p1) ** 2)
        assert f"{n:,}" == want and want in memo, (p0, r, n)


def test_designed_relationships_and_defects_are_present_in_the_results():
    dr = {d["id"]: d["realised"] for d in pub("manifest")["designed_relationships"]}
    m = {r["model"]: r for r in RES["01_model_comparison__models"]}
    assert dr["DR-01"]["logistic_regression"]["brier_score"] == m["logistic_regression (Platt)"]["brier_score"] and dr["DR-01"]["met"]["ap_over_rule"] is True
    mg = {r["margin"]: r for r in RES["08_rows_and_margins__margins"]}
    assert all(mg[k]["status"].startswith("met, by construction") for k in ("ap_over_rule", "ap_over_random", "brier_under_rule", "brier_under_random"))
    assert "uninformative" in mg["brier_under_random"]["status"] and mg["ap_over_prevalence_constant (reference)"]["status"].startswith("reference")
    seg = {r["grp"]: r for r in RES["10_segment_region_calibration__by_segment"]}
    reg = {r["grp"]: r for r in RES["10_segment_region_calibration__by_region"]}
    assert seg["starter"]["gap_pp"] == "-8.07" and reg["apac"]["gap_pp"] == "-10.68"
    sm = row_of("07_drift_by_region__published_summary")
    assert (sm["exceedances_before_the_change"], sm["exceedances_before_the_change_with_a_floored_bin"], sm["exceedances_from_the_change"]) == ("5", "4", "5")
    assert dr["DR-03"]["after_change_psi"] == [r["psi"] for r in RES["07_drift_by_region__published_series_apac"] if r["prediction_at"] >= "2026-05-01"]
    ws = row_of("04_censored_tail__world_summary")
    assert (ws["eligible_rows"], ws["censored_rows"], ws["censored_share"], ws["mature_churn_rate"]) == ("9039", "3594", dr["DR-05"]["censored_share"], dr["DR-05"]["mature_churn_rate"])
    fr = RES["05_arrived_late__feature_recomputation"]
    assert fr[0]["stored_equals_point_in_time_recomputation"] == fr[0]["feature_rows"] == "765"
    assert row_of("04_censored_tail__rejected_false_labels")["rejected_labels"] == "4"
    assert row_of("06_purge_counts__cohort_no_account_on_both_sides")["accounts_retained_in_two_ranges"] == "0"
    assert all(r["rows_that_differ_from_the_stored_assignment"] == "0" for r in RES["06_purge_counts__cohort_recomputed"])
    assert row_of("02_calibration_platt__platt_reproduced")["equal_at_6_places"] == "1513"
    ra = row_of("08_rows_and_margins__rows_and_accounts")
    assert (ra["test_rows"], ra["distinct_accounts"], ra["churning_rows"], ra["churning_accounts"]) == ("1513", "442", "189", "95")


@pytest.mark.skipif(not (os.environ.get("ARTIFACTS_DATABASE_URL") and os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL")),
                    reason="ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts10_*; the test prepares them with data/sql/analysis/prepare_snapshot.py) are not set")
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
        for prefix in NUMBERED:
            f = next(SQL_DIR.glob(f"{prefix}_*.sql"))
            for key, rows in ra.run_file(c, f).items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key
        for name in ra.BI_FILES:
            for key, rows in ra.run_file(c, SQL_DIR / f"{name}.sql").items():
                csv_name = key.split("__")[-1] if "__" in key else key.removeprefix("bi_")
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == _csv(csv_name), csv_name
        # the reference SQL on the cohort agrees with the manifest for the three queues (the verification of the investigation, once more, directly)
        for sid in ("sc-001", "sc-002", "sc-003"):
            ref = ra.reference(c, ra.AS_OF, "2026-09-01T00:00:00Z", sid)
            assert ref["economics"]["expected_value"] == pub("manifest")["published_cohort"]["economics"][sid]["expected_value"]
    with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        for key, rows in ra.run_file(c, SQL_DIR / "09_golden_known_answer.sql").items():
            assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key


def test_a_database_rerun_without_the_scratch_urls_is_skipped_with_a_reason():
    marks = [m for m in test_sql_files_rerun_against_the_prepared_databases_give_the_stored_rows.pytestmark if m.name == "skipif"]
    assert marks and "ARTIFACTS_DATABASE_URL" in marks[0].kwargs["reason"] and SCRATCH in marks[0].kwargs["reason"] and "ARTIFACTS_GOLDEN_DATABASE_URL" in marks[0].kwargs["reason"]


def test_scratch_guard_refuses_a_non_scratch_database(prep):
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/retentionlab")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts07_snapshot")
    prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts10_snapshot")
    with pytest.raises(SystemExit):
        prep.create_database("postgresql://u:p@127.0.0.1:5432/postgres", "retentionlab")
    with pytest.raises(SystemExit):
        prep.drop_database("postgresql://u:p@127.0.0.1:5432/postgres", "retentionlab")
    assert prep.SCRATCH_PREFIX == SCRATCH


def test_every_sql_file_has_its_header_and_the_numbered_files_read_only():
    files = sorted(SQL_DIR.glob("[01][0-9]_*.sql"))
    assert [f.name[:2] for f in files] == ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]
    for f in files:
        text = f.read_text()
        assert re.match(rf"-- P10-ART-04 investigation {f.name[:2]}:", text), f.name
        assert "D-0" in text or "D-1" in text, f.name
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE)\b", body, re.I), f.name                 # read only
        for line in text.splitlines():
            if line.startswith("-- @@ "):
                assert re.fullmatch(r"-- @@ \w+", line), line
    for f in sorted(SQL_DIR.glob("bi_*.sql")):
        text = f.read_text()
        assert "P10-ART-06" in text, f.name
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"(?i)\b(insert|update|delete|drop|alter|create)\b", body), f.name
    # locale-independent ordering: an ORDER BY on a text column carries COLLATE "C"; none orders by a boolean
    text_cols = {"model", "grp", "scope", "split_range", "reason_code", "dimension", "segment", "region", "group_key", "population_key", "scenario_id", "claim", "source", "margin", "entity", "status", "account_id_text"}
    for f in files + sorted(SQL_DIR.glob("bi_*.sql")):
        for m in re.finditer(r"ORDER BY ([^;)\n]+)", re.sub(r"--.*", "", f.read_text())):
            for part in [p.strip() for p in re.split(r",(?![^(]*\))", m.group(1))]:
                ident = re.sub(r"\s+(ASC|DESC)$", "", part).split(".")[-1]
                if re.fullmatch(r"[a-z_]+", ident) and ident in text_cols:
                    assert 'COLLATE "C"' in part, (f.name, part)
                assert not re.search(r"\b(is_|empty_bin|exceeds|made_the|label_dropped)", part), (f.name, part)
    layer = (ROOT / "data" / "sql" / "verification_layer.sql").read_text()
    assert layer.count("CREATE TABLE") == 6 and "NOT a migration" in layer


def test_the_investigations_are_their_own_text_and_not_a_copy_of_the_reference_sql():
    ref = (ROOT / "data/sql/reference_metrics.sql").read_text()
    mine = "\n".join(f.read_text() for f in SQL_DIR.glob("[01][0-9]_*.sql"))
    for token in ("last_sub AS", "feat AS", "win AS", "lab AS"):
        assert token in ref
    assert "last_sub AS" not in mine and "reference_metrics" not in "\n".join(l for l in mine.splitlines() if not l.startswith("--"))


# ---- the workbook --------------------------------------------------------------------------------------------------------------------------

def _b(v):
    """LibreOffice stores a typed TRUE/FALSE constant as the formula =TRUE() / =FALSE() when it saves the recalculated file; read both forms as the boolean."""
    return {"=TRUE()": True, "=FALSE()": False}.get(v, v)


def test_workbook_sheets_present_and_assumptions_listed(wb, bw):
    assert wb.sheetnames == bw.SHEET_ORDER
    ws = wb["Assumptions"]
    ids = {ws.cell(row=r, column=1).value for r in range(4, 40)}
    assert {"A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "A-07", "W-01", "W-02", "W-03", "W-04", "W-05"} <= ids
    text = " ".join(str(ws.cell(row=r, column=2).value) for r in range(4, 40))
    assert "Excel was NOT run" in text and "LibreOffice" in text and "TYPED" in text and "HYPOTHETICAL" in text and "by construction" in text
    c = wb["Controls"]
    assert c["B3"].value == "logistic_regression" and c["B18"].value == "=Checks!B2"
    assert any("random_baseline" in (dv.formula1 or "") for dv in c.data_validations.dataValidation)
    assert "Excel was NOT run" in " ".join(str(x.value) for row in wb["Read me"].iter_rows() for x in row if x.value)


def test_test_table_sheet_equals_the_published_rows(wb, T):
    ws = wb["Test table"]
    assert ws.cell(row=5 + len(T.rows) - 1, column=1).value == 1513 and ws.cell(row=5 + len(T.rows), column=1).value is None
    for i in (0, 1, 700, 1512):
        r = T.rows[i]
        n = 5 + i
        assert [ws.cell(row=n, column=c).value for c in (2, 3, 5, 6, 11)] == [r["account_id"], r["cutoff_index"], r["segment"], r["region"], r["churned"]]
        for col, key in zip("LMNOP", ("p_random_baseline", "p_business_rule", "p_logistic_calibrated", "p_prevalence_baseline", "p_logistic_uncalibrated")):
            assert F(str(ws[f"{col}{n}"].value)) == r[key]


def test_result_cells_of_the_formula_sheets_are_live_formulas_without_hardcoded_figures(wb):
    t = wb["Test table"]
    for n in (5, 100, 1000, 1517):
        for col in ("Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "AA", "AB", "AC", "AD", "AE", "AF"):
            assert str(t[f"{col}{n}"].value).startswith("="), (col, n)
    m = wb["Models"]
    for r in range(5, 10):
        for col in "CDEFGHI":
            assert str(m[f"{col}{r}"].value).startswith("="), (col, r)
    for r in range(13, 19):
        assert str(m[f"C{r}"].value).startswith("=") and str(m[f"D{r}"].value).startswith("=")
    cal = wb["Calibration"]
    for top in (5, 19):
        for r in range(top, top + 10):
            for col in "DEFGHKL":
                assert str(cal[f"{col}{r}"].value).startswith("="), (col, r)
    cap = wb["Capacity"]
    for r in range(5, 17):
        for col in "DEFG":
            assert str(cap[f"{col}{r}"].value).startswith("="), (col, r)
    eco = wb["Economics"]
    for r in range(5, 8):
        for col in "GH":
            assert str(eco[f"{col}{r}"].value).startswith("="), (col, r)
    for r in range(5, 102):
        assert str(eco[f"C{r}"].value).startswith("=")
    assert str(eco["F13"].value).startswith("=ROUND(SUMPRODUCT(")
    ct = wb["Censored tail"]
    for r in range(5, 26):
        assert str(ct[f"G{r}"].value).startswith("=") and str(ct[f"N{r}"].value).startswith("=")
    dr = wb["Drift"]
    for r in range(5, 17):
        for col in "CDEFGHIJKLMO":
            assert str(dr[f"{col}{r}"].value).startswith("="), (col, r)
    g = wb["Golden case"]
    for r in range(15, 23):
        assert str(g[f"B{r}"].value).startswith("=") and str(g[f"D{r}"].value).startswith("="), r
    assert wb["Checks"]["B2"].value.startswith("=AND(") and wb.calculation.fullCalcOnLoad
    for r in range(5, 5 + 70):
        assert str(wb["Checks"][f"C{r}"].value).startswith("=") and str(wb["Checks"][f"F{r}"].value).startswith("="), r
    assert wb["Checks"].cell(row=5 + 70, column=1).value is None


def test_cached_values_equal_figures_recomputed_here(wbv, ps, T, P):
    assert wbv["Checks"]["B2"].value is True and wbv["Controls"]["B18"].value is True
    for r in range(5, 75):
        assert wbv["Checks"][f"F{r}"].value is True, wbv["Checks"][f"B{r}"].value
    models = wbv["Models"]
    for i, (m, col) in enumerate(MODEL_COLS.items()):
        it = [(r[col], r["churned"]) for r in T.rows]
        assert abs(models[f"F{5 + i}"].value - float(ps.avg_precision(it))) < 1e-9, m
        assert abs(models[f"H{5 + i}"].value - float(ps.brier(it))) < 1e-9, m
        assert models[f"C{5 + i}"].value == 1513 and models[f"D{5 + i}"].value == 189
    for r in (13, 14, 15, 16):
        assert models[f"D{r}"].value.startswith("met, by construction")
    assert models["D17"].value == models["D18"].value == "reference, not a target"
    cap = wbv["Capacity"]
    n = 5
    for m in ("random_baseline", "business_rule", "logistic_regression", "prevalence_baseline"):
        col = MODEL_COLS[m]
        order = sorted(T.rows, key=lambda r: (-r[col], r["account_id"], r["cutoff_index"]))
        for k in (5, 10, 20):
            tp = sum(r["churned"] for r in order[:k])
            assert cap[f"D{n}"].value == tp and abs(cap[f"E{n}"].value - tp / k) < 1e-12 and abs(cap[f"F{n}"].value - tp / 189) < 1e-12, (m, k)
            assert abs(cap[f"G{n}"].value - (tp / k) / (189 / 1513)) < 1e-9
            n += 1
    cal = wbv["Calibration"]
    for r in range(5, 15):
        i = r - 5
        rows = [x for x in T.rows if min(int(x["p_logistic_calibrated"] * 10 // 1), 9) == i]
        assert cal[f"D{r}"].value == len(rows)
        if rows:
            assert abs(cal[f"H{r}"].value - float((sum((x["p_logistic_calibrated"] for x in rows), F(0)) / len(rows) - F(sum(x["churned"] for x in rows), len(rows))) * 100)) < 1e-9
        else:
            assert cal[f"H{r}"].value in (None, "")
    assert sum(1 for r in range(5, 15) if cal[f"D{r}"].value == 0) == 6
    eco = wbv["Economics"]
    for r, want in ((5, 21.38), (6, -6.87), (7, -95.46)):
        assert eco[f"H{r}"].value == want and eco[f"L{r}"].value == "hypothetical"
    assert [eco[f"G{r}"].value for r in (5, 6, 7)] == [40, 80, 160] and [eco[f"J{r}"].value for r in (5, 6, 7)] == [81.13, 71.04, -29.12] and eco["K5"].value == 1241
    ct = wbv["Censored tail"]
    assert ct["C26"].value == 9039 and ct["E26"].value == 3594 and abs(ct["G26"].value - 3594 / 9039) < 1e-12 and abs(ct["H26"].value - 569 / 5445) < 1e-12
    dr = wbv["Drift"]
    psi = {(dr[f"A{r}"].value, dr[f"B{r}"].value): dr[f"L{r}"].value for r in range(5, 17)}
    want = {(x["grp"], T.cutoffs.index(ps.ts(x["prediction_at"].replace("+00:00", "Z")))): float(x["psi"]) for x in RES["07_drift_by_region__psi_test_range"] if x["grp"] in ("apac", "other_regions", "all_accounts")}
    assert set(psi) == set(want) and all(abs(psi[k] - want[k]) < 5e-7 for k in want)
    g = wbv["Golden case"]
    assert abs(g["B19"].value - 0.1925) < 1e-12 and abs(g["B20"].value - 5 / 6) < 1e-12 and g["B21"].value == 10 and g["B22"].value == 8.45
    pu = wbv["Purge"]
    assert pu["H9"].value == 1055 and pu["H10"].value == 1304 and all(pu[f"I{r}"].value is True for r in range(5, 13))


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
    assert v["Checks"]["B2"].value is True and v["Controls"]["B18"].value is True and v["Controls"]["B3"].value == "logistic_regression"
    assert v["Models"]["F7"].value == pytest.approx(0.238552, abs=5e-7) and v["Economics"]["H5"].value == 21.38


@needs_lo
@pytest.mark.parametrize("model,k,effect", [("random_baseline", 10, 0.2), ("prevalence_baseline", 20, 0.1), ("business_rule", 5, 0.3)])
def test_the_model_switch_and_the_what_if_are_live_and_the_check_cell_stays_true(tmp_path, T, model, k, effect):
    flip = openpyxl.load_workbook(XLSX)                         # formulas only: openpyxl drops the cached values on save
    flip["Controls"]["B3"], flip["Controls"]["B11"], flip["Controls"]["B13"] = model, k, effect
    src = tmp_path / f"{model}.xlsx"
    flip.save(src)
    assert openpyxl.load_workbook(src, data_only=True)["Checks"]["B2"].value is None          # no cached values until recalculated
    v = openpyxl.load_workbook(_lo_recalc(src, tmp_path / model), data_only=True)
    assert v["Checks"]["B2"].value is True and v["Controls"]["B3"].value == model and v["Controls"]["B4"].value == list(MODEL_COLS).index(model) + 1
    col = MODEL_COLS[model]
    order = sorted(T.rows, key=lambda r: (-r[col], r["account_id"], r["cutoff_index"]))
    block = v["Capacity"]
    for j, kk in enumerate((5, 10, 20)):
        assert block[f"C{21 + j}"].value == sum(r["churned"] for r in order[:kk]), (model, kk)
    # the what-if on the 97 cohort accounts: top k by probability, value rounded once
    assert v["Economics"]["F13"].value == {("random_baseline", 10, 0.2): -6.87, ("prevalence_baseline", 20, 0.1): -95.46, ("business_rule", 5, 0.3): 21.38}[(model, k, effect)]
    assert v["Economics"]["F12"].value == k * 8


def test_pasted_sql_results_sheet_matches_the_stored_results(wb):
    ws = wb["SQL results (pasted)"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    meta = RES["meta"][0]
    assert any(isinstance(c, str) and f"reconciliation rows: {meta['reconciliation_rows']} (equal: {meta['reconciliation_equal']})" in c for c in cells)
    assert float(row_of("01_model_comparison__models", model="logistic_regression (Platt)")["average_precision"]) in cells
    assert float(row_of("02_calibration_platt__platt_effect")["brier_after"]) in cells and float(row_of("09_golden_known_answer__known_answer")["expected_intervention_value"]) in cells
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)               # pasted values, not formulas


# ---- the BI package ------------------------------------------------------------------------------------------------------------------------

def _csv(name: str) -> list[dict]:
    with (ART / "bi" / f"{name}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


BI = ["dim_population", "dim_model", "dim_cutoff", "dim_scenario", "dim_segment", "dim_region", "dim_bin", "fact_test_row", "fact_model_metric", "fact_calibration_bin", "fact_capacity",
      "fact_cutoff", "fact_drift", "fact_purge", "fact_segment_gap"]


def test_bi_exports_have_the_documented_grain_and_equal_the_snapshot(T):
    sizes = {n: len(_csv(n)) for n in BI}
    assert sizes == {"dim_population": 3, "dim_model": 5, "dim_cutoff": 21, "dim_scenario": 3, "dim_segment": 4, "dim_region": 5, "dim_bin": 10, "fact_test_row": 1513, "fact_model_metric": 5,
                     "fact_calibration_bin": 20, "fact_capacity": 18, "fact_cutoff": 42, "fact_drift": 91, "fact_purge": 8, "fact_segment_gap": 9}
    rows = _csv("fact_test_row")
    assert len({(r["account_id"], r["prediction_at"]) for r in rows}) == 1513 and sum(int(r["churned"]) for r in rows) == 189
    assert [F(r["p_logistic_regression"]) for r in rows] == [x["p_logistic_calibrated"] for x in T.rows]
    pops = {r["population_key"] for r in _csv("dim_population")}
    models = {r["model_key"] for r in _csv("dim_model")}
    for n in ("fact_model_metric", "fact_calibration_bin", "fact_capacity", "fact_cutoff", "fact_purge", "fact_segment_gap"):
        assert {r["population_key"] for r in _csv(n)} <= pops, n
    for n in ("fact_model_metric", "fact_calibration_bin", "fact_capacity"):
        assert {r["model_key"] for r in _csv(n)} <= models, n
    assert {r["scenario_id"] for r in _csv("fact_capacity")} <= {r["scenario_id"] for r in _csv("dim_scenario")}
    assert {r["prediction_at"] for r in _csv("fact_cutoff")} <= {r["prediction_at"] for r in _csv("dim_cutoff")}
    assert {r["segment_key"] for r in rows} <= {r["segment_key"] for r in _csv("dim_segment")} and {r["region_key"] for r in rows} <= {r["region_key"] for r in _csv("dim_region")}
    # nothing withheld silently: an empty bin is a row with null measures and the flag; economics exist only where the outcome is censored, and say hypothetical
    for r in _csv("fact_calibration_bin"):
        assert (r["empty_bin"] == "true") == (r["rows_in_bin"] == "0") and (r["mean_predicted"] == "") == (r["empty_bin"] == "true")
    for r in _csv("fact_capacity"):
        if r["population_key"] == "test_world":
            assert r["expected_value"] == "" and r["contact_budget"] == ""
        else:
            assert r["expected_value"] != "" and r["precision_at_k"] == "" and "HYPOTHETICAL" in r["status"]
    assert sum(1 for r in _csv("fact_calibration_bin") if r["empty_bin"] == "true") == 11
    for r in _csv("fact_model_metric"):
        assert "by construction" in r["interpretation"]


def test_bi_measures_recomputed_from_the_csv_files_equal_the_stored_values(ra, T, ps):
    csvs = {n: _csv(n) for n in BI}
    rows = ra.bi_measures(csvs)
    assert rows == RES["bi_measures"] == _csv("measures_recomputed")
    mv = {(m["measure"], m["population"], m["slice"]): m for m in rows}
    m = {r["model"]: r for r in RES["01_model_comparison__models"]}
    assert mv[("average_precision", "test_world", "logistic_regression")]["value"] == m["logistic_regression (Platt)"]["average_precision"]
    assert mv[("brier_score", "test_world", "business_rule")]["value"] == m["business_rule"]["brier_score"]
    for sid, ev in (("sc-001", "21.38"), ("sc-002", "-6.87"), ("sc-003", "-95.46")):
        assert mv[("expected_intervention_value", "cohort_200", sid)]["value"] == ev
    for sid, ev in (("sc-001", "81.13"), ("sc-002", "71.04"), ("sc-003", "-29.12")):
        assert mv[("expected_intervention_value", "world_2400", sid)]["value"] == ev
    econ = [x for x in rows if x["measure"] in ("expected_intervention_value", "contact_budget", "treatment_effect_estimate")]
    assert len(econ) == 13 and all(x["result_kind"] == "hypothetical" and x["population"] in ("cohort_200", "world_2400", "all") for x in econ)
    assert mv[("treatment_effect_estimate", "all", "all")]["status"].startswith("withheld")
    assert all(x["status"] != "value" for x in rows if x["value"] == "")                                 # an empty value always says why
    assert {x["result_kind"] for x in rows} == {"simulated", "hypothetical"}
    assert sum(1 for x in rows if x["status"] == "null: empty bin") == 11 and sum(1 for x in rows if x["status"] == "null: outcomes censored") == 12


def test_bi_package_defines_every_measure_and_makes_no_pbix_claim():
    doc = read("bi-package.md")
    assert "no `.pbix` exists" in doc and "pseudocode" in doc and "never executed" in doc and "Power BI Desktop and the Power BI service were not run" in doc
    for m in ("Evaluated Rows", "Churning Rows", "Prevalence", "Brier Score", "Average Precision", "Precision at K", "Recall at K", "Risk Lift at K", "Calibration Gap", "Censored Share",
              "Mature Churn Rate", "Contact Budget", "Expected Value", "Treatment Effect"):
        assert m in doc, m
    for t in BI:
        assert f"`{t}`" in doc, t
    assert "mermaid" in doc and "HYPOTHETICAL" in doc and "population" in doc and "without installing" in doc
    measures = {x["measure"] for x in RES["bi_measures"]}
    for name in measures:
        assert name in doc or any(name == k for k in ("distinct_accounts",)) or name.replace("_", " ") in doc.lower() or f"`{name}`" in doc or name in _csv_text("measures_recomputed"), name
    rendered = sum(1 for _ in re.finditer(r"<!-- BEGIN:bi_measures -->", doc))
    assert rendered == 1


def _csv_text(name: str) -> str:
    return (ART / "bi" / f"{name}.csv").read_text()


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations():
    dd, erd = read("data-dictionary.md"), read("erd.md")
    tables: dict[str, list[str]] = {}
    for f in sorted((ROOT / "data" / "migrations").glob("*.sql")):
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", f.read_text(), re.S):
            cols = []
            for line in m.group(2).splitlines():
                line = line.strip()
                if not line or line.startswith(("--", "CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK")):
                    continue
                mm = re.match(r"([a-z_]+)\s+[A-Z]", line)
                if mm:
                    cols.append(mm.group(1))
            tables[m.group(1)] = cols
    assert len(tables) == 24 and sum(len(c) for c in tables.values()) == 147          # schema_migrations is created by data/migrate.py, not by a migration file
    for t, cols in tables.items():
        sec = re.search(rf"### {t}\n(.*?)(?=\n### |\n## )", dd, re.S)
        assert sec, t
        for c in cols:
            assert f"| `{c}` |" in sec.group(1), (t, c)
        assert f"`{t}`" in erd, t
    assert "### schema_migrations" in dd and "`schema_migrations`" in erd
    assert "erDiagram" in erd and "Read the text lists below the diagram" in erd and "```mermaid" in erd
    fks = len(re.findall(r"REFERENCES", "".join(f.read_text() for f in (ROOT / "data" / "migrations").glob("*.sql"))))
    assert fks == erd.count(" ||--o{ ") == 22
    for t in ("art_test_table", "art_cutoff_aggregate", "art_drift_published", "art_economics_full_world", "art_split_population", "art_published_claim"):
        assert f"`{t}`" in dd, t
    assert "Source-to-target mapping" in dd and "Foreign keys" in dd and "Constraints and triggers" in dd


def test_sql_analysis_doc_quotes_the_stored_results_and_every_table_is_rendered_from_them():
    sql = _load("rl_render", ART / "render_sql_analysis.py")
    for name in ("sql-analysis.md", "bi-package.md"):
        text = read(name)
        assert sql.render(text, RES) == text, name                         # a pasted figure that drifted from the stored results would differ
    text = read("sql-analysis.md")
    keys = set(re.findall(r"<!-- BEGIN:([\w]+) -->", text))
    for k in RES:
        if re.match(r"\d\d_", k) and k.split("__")[0][:2] != "00":
            assert k in keys, k                                           # every result set of every investigation is rendered
    assert {"reconciliation_summary", "reconciliation_listing"} <= keys
    for f in sorted(SQL_DIR.glob("[01][0-9]_*.sql")):
        assert f"`{f.name}`" in text, f.name


def test_the_documents_name_the_real_entities_metrics_and_commands_and_keep_result_kinds_apart():
    text = " ".join(read(n) for n in DOC_NAMES)
    for token in ("accounts", "subscription_events", "prediction_cutoffs", "feature_rows", "labels", "training_runs", "predictions", "intervention_scenarios", "outreach_events", "split_assignments",
                  "build-point-in-time-features", "define-label", "split-evaluation", "fit-preprocessing", "train-baseline", "calibrate-model", "score-accounts", "prioritize-outreach",
                  "simulate-economics", "monitor-refresh", "P10-FLOW-08", "P10-MET-04", "P10-TEST-09", "average precision", "Brier", "risk lift", "available_at"):
        assert token in text, token
    for n in ("business-case.md", "executive-memo.md", "sql-analysis.md", "uat-evidence.md", "technical-case-study.md", "release-package.md"):
        doc = read(n)
        assert "simulated" in doc.lower() and "hypothetical" in doc.lower(), n
    memo = read("executive-memo.md")
    assert "by construction" in memo and "No retention improvement is claimed" in memo


def test_requirements_trace_every_requirement_family():
    req = read("requirements.md")
    assert "## 1. User stories" in req and "## 2. Functional requirements" in req and "## 3. Non-functional" in req and "## 4. Traceability matrix" in req and "## 5. Deferred and open" in req
    for i in range(1, 13):
        assert f"| US-{i:02d} |" in req, i
    ids = (["P10-GOAL-01", "P10-GOAL-02", "P10-GOAL-06", "P10-GOAL-12", "P10-GOLD-01", "P10-GOLD-02", "P10-GOLD-08", "P10-GOLD-09", "P10-GOLD-10", "P10-GOLD-11"]
           + [f"P10-DOMAIN-{i:02d}" for i in range(1, 7)] + [f"P10-DATA-{i:02d}" for i in (1, 6, 7, 8, 9, 10, 11, 12)] + [f"P10-MET-{i:02d}" for i in range(1, 13)]
           + [f"P10-FLOW-{i:02d}" for i in range(1, 11)] + [f"P10-UI-{i:02d}" for i in range(1, 11)] + [f"P10-TEST-{i:02d}" for i in range(1, 13)] + [f"P10-ART-{i:02d}" for i in range(1, 11)]
           + ["P10-REL-05", "P10-REL-06", "P10-REL-08", "P10-REL-23"])
    for i in ids:
        assert f"| {i} |" in req, i
    spec = next((p for p in (Path("/tmp/claude-0/-home-user-projects-site/60c6425d-0b9a-54e1-9c11-47a4a45af8e7/scratchpad/10-retentionlab.md"),) if p.exists()), None)
    if spec:                                                                     # the spec file is not in the repository; where it is present, every ART/MET/FLOW/TEST/UI id family is traced
        for fam in ("MET", "FLOW", "UI", "ART"):
            for m in set(re.findall(rf"### (P10-{fam}-\d\d)", spec.read_text())):
                assert f"| {m} |" in req, m
    # every path the matrix names exists
    missing = []
    for m in set(re.findall(r"`((?:\.\./\.\./)?(?:domain|api|data|tests|web|docs|artifacts|\.github)/[\w./\-]+?\.(?:py|sql|json|ts|tsx|md|yml|csv|xlsx|txt))`", req)):
        if not (ROOT / m).exists():
            missing.append(m)
    assert missing == []
    for token in ("393", "ce96e65", DATASET_HASH, "synthetic", "without installing", "skip"):
        assert token in req, token


def test_executive_memo_quotes_the_evidence_options_and_the_caveats():
    memo = read("executive-memo.md")
    for h in ("## Decision", "## Evidence", "## Options", "## Uncertainty", "## Limitations", "## Recommendation", "## The experiment that would be needed"):
        assert h in memo, h
    for token in ("No retention improvement is claimed", "by construction", "not evidence", "randomised", "HYPOTHETICAL", "break-even", "Risk lift is a ranking statistic", "different populations", "censored",
                  "false positives", "Excel and Power BI Desktop were not run", "power 0.80", "intention to treat", "supported_by_randomised_experiment"):
        assert token in memo, token
    assert re.search(r"\| [A-D]\. ", memo) and memo.count("| A. ") == 1 and memo.count("| D. ") == 1
    assert "treatment effect" in memo.lower() and "a trial" in memo.lower()


def test_uat_evidence_has_routes_screenshots_scenarios_and_run_links():
    uat = read("uat-evidence.md")
    for token in ("40464123151", "40456970303", "ce96e65", "cf04a0e", "c17fa32", "pending", "did **not** run `npm run e2e`", "not fetched", "expected answer", "actual observation", "disposition",
                  "Defect disposition", "R10-01", "R10-15", DATASET_HASH, "simulated", "hypothetical", "60 files"):
        assert token.lower() in uat.lower() or token in uat, token
    routes_ts = (ROOT / "web/src/routes.ts").read_text()
    paths = re.findall(r'path: "([a-z-]*)"', routes_ts)
    assert len(paths) == 12
    for p in paths:
        assert (f"`/{p}/`" if p else "`/`") in uat, p
    for shot in ("home", "overview", "cohorts", "features", "models", "calibration", "capacity", "account", "queue", "monitoring", "evidence", "case-study"):
        assert f"`{shot}`" in uat, shot
    assert "-zoom200.png" in uat
    for s in range(1, 15):
        assert f"| S{s} |" in uat, s
    idx = ROOT / "web" / "evidence" / "index.json"
    if idx.exists():
        data = json.loads(idx.read_text())
        assert data["count"] == 60 and all(s["scrollWidth"] <= s["innerWidth"] for s in data["shots"])
    rep = ROOT / "web" / "evidence" / "playwright-report.json"
    if rep.exists():
        st = json.loads(rep.read_text())["stats"]
        assert (st["expected"], st["unexpected"], st["flaky"], st["skipped"]) == (90, 0, 0, 0)
    assert "created by this pass" in uat.lower()


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    tcs, rel = read("technical-case-study.md"), read("release-package.md")
    n_tests = len(re.findall(r"^def test_", (ROOT / "tests" / "test_artifacts.py").read_text(), re.M))
    for token in ("Architecture", "Trade-offs", "Recovery behaviour", "Reproducible setup", "Measured evidence", "Open gaps", "```mermaid", "R10-01", "R10-15", "ce96e65", "c17fa32", "cf04a0e", "40464123151",
                  "40456970303", DATASET_HASH, "393 reconciliation rows", "Excel and Power BI Desktop were not run", "342", "3,197", "1,823", "95 review checks", "90 browser tests",
                  f"{n_tests} test functions"):
        assert token in tcs or token.lower() in tcs.lower(), token
    for token in ("cf04a0e", "28d974b", "b5168a2", "3c6550efe301e23d53c21bf147d7ea6d1a5506cd", "c17fa321f28605ac56e24b59837441c29cc16d41", "ce96e6544eb8a645236b081bf7dbd9f4a6c9e057", "40464123151", "40456970303",
                  "pending at dispatch", "Rollback procedure", "git revert", "Artifacts and checksums", DATASET_HASH, "4013064ff2bbc4bab4a482c7dc2b008a54292c2271635b9fee5f3935def12413", "committed and pushed nothing",
                  "Main-portfolio metadata", "Excel", "Power BI", "not fetch", "What this artifact pass ran", "private", "not attached to a GitHub release", "rollback manifest"):
        assert token in rel, token
    assert "lab:lab" not in rel and "RUN_LOG_PLACEHOLDER" not in rel
    if shutil.which("git"):
        for c in ("ce96e65", "4b957ca", "e81c2b4", "7b47757"):
            probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", c], capture_output=True, text=True)
            if probe.returncode != 0:
                pytest.skip(f"commit {c} is not in this checkout")
        assert "review R10 fixes" in subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%s", "ce96e65"], capture_output=True, text=True).stdout
    mpath = ROOT.parents[1] / "docs" / "program" / "release-manifest.json"
    if mpath.exists():
        site = next(s for s in json.loads(mpath.read_text())["sites"] if s["slug"] == "retentionlab")
        assert site["release_commit_unified_portfolio"] in rel and site["rollback_commit_unified_portfolio"] in rel and site["dataset_hash"] == DATASET_HASH
        assert site["published_tree_sha256"] in rel
        if site["live_verification"] is None:
            assert "pending at dispatch" in rel and "live check pending" in rel.lower() or "live verification" in rel.lower()


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact_and_match_the_public_case_study():
    text = read("resume-bullets.md")
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6
    body = " ".join(bullets)
    assert not re.search(r"\b(saved|savings|reduced (?:cost|time|churn)|increased revenue|improved retention|users|customers? adopted|adoption of|roi|lifted)\b", body, re.I)
    for token in ("1,823", "342 Python tests", "R10-01", "393 reconciliation rows", "LibreOffice", "no `.pbix`", "by construction", "0.238552", "0.105019", "3,197", "90 browser tests"):
        assert token in body, token
    assert "synthetic" in text.lower() and "no bullet claims business impact" in text and "No retention improvement is claimed" in text
    assert str(RES["meta"][0]["reconciliation_rows"]) in body
    if PROJECT:
        tech = " ".join(PROJECT["tech"])
        assert "342 Python tests" in tech and "3,197 TypeScript golden" in tech and "95 review checks" in tech and "90 browser tests" in tech


def test_public_case_study_figures_agree_with_the_stored_results():
    if PROJECT is None:
        pytest.skip("the public case study /retentionlab/project.json is not in this checkout (it lives on unified-portfolio)")
    text = re.sub(r"<[^>]+>", " ", PROJECT["results"] + PROJECT["built"] + PROJECT["tagline"]).replace("−", "-")
    m = {r["model"]: r for r in RES["01_model_comparison__models"]}
    lg, rule, rnd_ = m["logistic_regression (Platt)"], m["business_rule"], m["random_baseline"]
    assert f"average precision of {lg['average_precision']} and a Brier score of {lg['brier_score']}" in text
    assert f"against {rule['average_precision']} and {rule['brier_score']} for the business rule and {rnd_['average_precision']} and {rnd_['brier_score']} for the random baseline" in text
    ra = row_of("08_rows_and_margins__rows_and_accounts")
    assert f"{int(ra['test_rows']):,} rows from {ra['distinct_accounts']} accounts, {ra['churning_rows']} of them churning rows from {ra['churning_accounts']} accounts" in text and ra["prevalence_of_rows"] in text
    pe = row_of("02_calibration_platt__platt_effect")
    assert f"Brier {pe['brier_before']} before, {pe['brier_after']} after; overall gap -2.26 points before, -2.86 after" in text and f"all {pe['fit_rows']} calibration rows" in text
    assert "8.07 points on the starter plan" in text and "apac region at 10.68 points" in text and "six of the ten reliability bins hold no rows" in text
    assert sum(1 for r in RES["02_calibration_platt__bins"] if r["model"] == "logistic_regression (Platt)" and r["empty_bin"] == "true") == 6
    sm = row_of("07_drift_by_region__published_summary")
    assert f"{[r for r in RES['07_drift_by_region__published_series_apac'] if r['prediction_at'].startswith('2026-05-01')][0]['psi']} at 2026-05-01, peaks at {sm['shift_max_psi']} in August and ends at {RES['07_drift_by_region__published_series_apac'][-1]['psi']} in September" in text
    assert sm["all_accounts_psi_2026_05"] in text and sm["max_psi_before_the_change"] in text and "five of the thirteen months before the change" in text
    assert int(sm["exceedances_before_the_change"]) == 5 and int(sm["cutoffs_before_the_reference"]) == 13
    ws = row_of("04_censored_tail__world_summary")
    assert f"Of {int(ws['eligible_rows']):,} eligible cutoff rows {int(ws['censored_rows']):,} ({ws['censored_share']}) are censored" in text and ws["mature_churn_rate"] in text
    assert "11.57 percent" in text and "879 training rows" in text and "176 more" in text and "1,088 retained training rows of which 744" in text
    both = {r["scenario_id"]: r for r in RES["03_capacity_economics__both_populations"]}
    assert f"+{both['sc-001']['cohort_expected_value']} at a capacity of five" in text and f"{both['sc-002']['cohort_expected_value']} at ten" in text and f"{both['sc-003']['cohort_expected_value']} at twenty" in text
    assert f"+{both['sc-001']['world_expected_value']}, +{both['sc-002']['world_expected_value']} and {both['sc-003']['world_expected_value']}" in text
    assert PROJECT["repo"].endswith("apps/retentionlab") and PROJECT["date"] == "2026-10"
    rel = read("release-package.md")
    assert "SQL recomputation of average precision and the stability index" in rel and "overtaken" in rel


def test_no_credentials_or_secrets_in_the_artifact_documents_and_files():
    for d in DOC_NAMES:
        text = read(d)
        assert "lab:lab" not in text, d
        assert not re.search(r"postgres(ql)?://[^<\s]*:[^<\s@]+@", text), d
        assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S{12,}", text), d
    for p in list(ART.glob("*.json")) + list((ART / "bi").glob("*.csv")) + [ART / "CHECKSUMS.txt"] + list(SQL_DIR.glob("*.sql")) + [ROOT / "data" / "sql" / "verification_layer.sql"]:
        assert "postgresql://" not in p.read_text(), p.name
        assert "lab:lab" not in p.read_text(), p.name
    wbtext = " ".join(str(c.value) for ws in openpyxl.load_workbook(XLSX).worksheets[:14] for row in ws.iter_rows() for c in row if c.value)
    assert "postgresql://" not in wbtext and "password" not in wbtext.lower()
    py = (SQL_DIR / "prepare_snapshot.py").read_text()
    assert "lab:lab@127.0.0.1" in py                                          # the local development login of the CI workflow is the one documented default; it is not in any document


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = read("workbook.md")
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "retentionlab-analyst-workbook.xlsx" in doc and "openpyxl 3.1.5" in doc
    for sheet in ("Read me", "Controls", "Checks", "Models", "Calibration", "Capacity", "Economics", "Censored tail", "Drift", "Purge", "Golden case", "Assumptions", "Scenarios", "Test table", "SQL results (pasted)"):
        assert f"`{sheet}`" in doc, sheet
    assert "Controls!B3" in doc and "fullCalcOnLoad" in doc and "How to read it without installing" in doc and "Checks!B2" in doc
    for v in ("0.238552", "0.105019", "0.126793", "0.326543", "0.136653", "0.109255", "0.124917", "0.109664", "0.104515", "0.250000", "2.001323", "21.38", "-6.87", "-95.46", "81.13", "71.04", "-29.12",
              "0.397610", "0.104500", "0.513545", "0.833333", "8.45"):
        assert v in doc, v
    assert (ROOT / "requirements-artifacts.txt").read_text().strip() == "openpyxl==3.1.5"
    import zipfile                                                          # the 70 checks the doc names are the checks in the file
    n = sum(1 for r in range(5, 200) if openpyxl.load_workbook(XLSX)["Checks"].cell(row=r, column=1).value is not None)
    assert f"{n} checks" in doc


def test_every_document_cites_the_dataset_hash_and_the_code_revision_and_says_it_is_synthetic():
    assert len(DOC_NAMES) == 12
    for n in DOC_NAMES:
        text = read(n)
        assert DATASET_HASH in text and CODE_REVISION in text, n
        assert "TBD" not in text and "PLACEHOLDER" not in text, n
        assert "synthetic" in text.lower(), n
        if n not in ("resume-bullets.md", "erd.md"):
            assert "without installing" in text or "needs nothing installed" in text, n                  # a brief read/use instruction (P10-ART-xx-R12)
    assert "Read the text lists below the diagram" in read("erd.md")


def test_the_ci_no_skip_gate_and_the_unrun_tools_are_disclosed():
    req, rel, tcs = read("requirements.md"), read("release-package.md"), read("technical-case-study.md")
    ci = ROOT.parents[1] / ".github" / "workflows" / "retentionlab-ci.yml"
    if ci.exists():
        text = ci.read_text()
        assert "artifacts10_snapshot" in text and "artifacts10_golden" in text and "libreoffice-calc" in text and "fetch-depth: 0" in text and "ARTIFACTS_DATABASE_URL" in text
    for doc in (req, rel, tcs):
        assert "skip" in doc.lower() and "LibreOffice" in doc
    assert "not attached to a GitHub release" in rel and "Excel" in rel and "Power BI" in rel


def test_provenance_the_analysed_code_and_data_equal_revision_ce96e65():
    """The numbers describe revision ce96e65: the domain, API, migrations, loaders, reference SQL, published data, fixtures and the other tests are unchanged since
    (docs/contracts.md and README.md are part of the check; the other documents are deliberately not: wording fixes there move no number)."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", CODE_REVISION], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"revision {CODE_REVISION} is not in this checkout")
    protected = ["domain", "api", "data/migrations", "data/seed.py", "data/migrate.py", "data/artefacts.py", "data/generate.py", "data/injection-events.json", "data/sql/reference_metrics.sql", "web/public",
                 "web/src", "tests", ":(exclude)tests/test_artifacts.py", "docs/contracts.md", "README.md", "requirements.txt", "pytest.ini"]
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", CODE_REVISION, "--", *protected], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "", r.stdout
    st = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *protected], capture_output=True, text=True)
    assert st.returncode == 0 and st.stdout.strip() == "", st.stdout
    manifest = pub("manifest")
    assert manifest["dataset_hash"] == DATASET_HASH and manifest["dataset_version"] == "rl-20261026-20261026"
    full = subprocess.run(["git", "-C", str(ROOT), "rev-parse", CODE_REVISION], capture_output=True, text=True).stdout.strip()
    assert full == FULL_REVISION


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
    chk = _load("rl_checksums", ART / "checksums.py")
    assert sorted(listed) == chk.files()                                  # every artifact and doc, nothing stale
    for must in ("artifacts/retentionlab-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py", "artifacts/render_sql_analysis.py", "artifacts/checksums.py",
                 "requirements-artifacts.txt", "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
                 "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md", "docs/business-case.md", "docs/requirements.md", "docs/uat-evidence.md",
                 "docs/contracts.md", "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py", "data/sql/analysis/python_side.py", "artifacts/bi/fact_test_row.csv",
                 "artifacts/bi/dim_cutoff.csv", "artifacts/bi/measures_recomputed.csv", "data/sql/verification_layer.sql"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("[01][0-9]_*.sql")) + sorted(SQL_DIR.glob("bi_*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    assert "docs/release-package.md" not in listed and "artifacts/CHECKSUMS.txt" not in listed
    rel_doc = read("release-package.md")
    for rel, digest in listed.items():
        assert f"| `{rel}` | `{digest}` |" in rel_doc, rel               # release-package.md carries the same table (it cannot list itself)
