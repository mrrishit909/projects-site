"""Artifact package checks (P09-ART-01..10): the SQL analysis results, the analyst workbook, the BI exports, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that the result cells of the formula sheets are live formulas, (2) reads the values
LibreOffice cached in the delivered file and compares them with the Python domain RECOMPUTED HERE (not with the pasted reference sheet), (3) recalculates copies with LibreOffice
headless (as delivered, and with the scenario switch on other scenarios) and compares them with the domain, (4) checks that the stored analysis results equal the plain-Python
recomputation over web/public/data (no database), through data/sql/analysis/python_side.py, which shares no code with the SQL or the domain, (5) recomputes the BI measures from the
CSV exports, (6) checks that each document quotes the stored results and the public case study, and (7) checks CHECKSUMS.txt and the release-package table.
With ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts09_*; the test prepares them with prepare_snapshot.py) it also re-runs the SQL files and
compares their rows with the stored results; without them that test is skipped with a printed reason. The tests that need LibreOffice are skipped, with a reason, where `soffice` is
missing. Excel and Power BI are never run. This file never touches the shared changeworks database.
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

XLSX = ART / "changeworks-analyst-workbook.xlsx"
RES = json.loads((ART / "analysis-results.json").read_text()) if (ART / "analysis-results.json").exists() else {}
CODE_REVISION = "29948f9"
CODE_SHA = "29948f92f0c3839f070e4b6499b99f3810d1361b"
DATASET_HASH = "6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9"
SCRATCH = "artifacts09_"
_CASE_STUDY = next((p for p in (ROOT.parents[1] / "changeworks" / "project.json", ROOT.parents[3] / "changeworks" / "project.json") if p.exists()), None)
PROJECT = json.loads(_CASE_STUDY.read_text()) if _CASE_STUDY else None          # the public case study lives on unified-portfolio (CI copies it to changeworks/project.json)
NUMBERED = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "11"]
EXACT_KEYS = {"02_initiative_npv__scn025_exact", "02_initiative_npv__by_scenario_exact"}
DOCS12 = ["business-case.md", "requirements.md", "data-dictionary.md", "erd.md", "sql-analysis.md", "workbook.md", "bi-package.md", "executive-memo.md", "uat-evidence.md",
          "technical-case-study.md", "release-package.md", "resume-bullets.md"]

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
    out = ps.results()
    out.update(ps.golden_results())
    return out


@pytest.fixture(scope="module")
def wb():
    return openpyxl.load_workbook(XLSX)


@pytest.fixture(scope="module")
def wbv():
    return openpyxl.load_workbook(XLSX, data_only=True)


@pytest.fixture(scope="module")
def bw():
    return _load("cw_build_workbook", ART / "build_workbook.py")


@pytest.fixture(scope="module")
def ra():
    return _load("cw_run_all", SQL_DIR / "run_all.py")


@pytest.fixture(scope="module")
def prep():
    return _load("cw_prepare", SQL_DIR / "prepare_snapshot.py")


@pytest.fixture(scope="module")
def world(prep):
    from changeworks import run_pipeline
    inputs, manifest = prep.snapshot_inputs()
    return {"inputs": inputs, "manifest": manifest, "M": run_pipeline(inputs).metrics}


def row_of(key: str, **where) -> dict:
    return next(r for r in RES[key] if all(str(r[k]) == str(v) for k, v in where.items()))


def rows_by(key: str, col: str) -> dict:
    return {r[col]: r for r in RES[key]}


def read(name: str) -> str:
    return (DOCS / name).read_text()


def all_test_names() -> str:
    return " ".join(p.read_text() for p in (ROOT / "tests").glob("test_*.py"))


# ---- stored analysis results ---------------------------------------------------------------------------------------------------------------

def test_analysis_results_reconcile_and_cover_every_investigation(P):
    assert RES["reconciliation"] and all(r["equal"] is True for r in RES["reconciliation"])
    assert len(RES["reconciliation"]) >= 600
    meta = RES["meta"][0]
    assert meta["dataset_hash"] == DATASET_HASH and meta["code_revision"] == CODE_REVISION and meta["code_sha"] == CODE_SHA
    assert meta["reconciliation_rows"] == len(RES["reconciliation"]) == meta["reconciliation_equal"]
    assert meta["analysis_leaves_snapshot"] == 48476 and meta["analysis_leaves_golden"] == 167
    numbered = sorted(p.name[:2] for p in SQL_DIR.glob("[01][0-9]_*.sql") if not p.name.startswith(("00_", "10_")))
    assert numbered == NUMBERED                                                   # ten investigations on the snapshot (at least the eight required) and the golden one
    for key in P:
        assert RES[key], key
    assert {k.split("__")[0][:2] for k in P} == set(NUMBERED) | {"10"}
    assert {r["check"].split(" ")[0] for r in RES["reconciliation"]} == {"A", "B", "C", "D", "E"}
    assert meta["result_sets"] == len(P)
    assert RES["bi_measures"] and len(RES["bi_measures_scn025"]) + len(RES["bi_measures_portfolio"]) < len(RES["bi_measures"])


def test_golden_known_answer_in_sql_equals_expected_json_the_domain_and_the_hand_figures():
    exp = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())
    a = RES["10_golden_known_answer__init001_answer"][0]
    assert (a["npv"], a["npv_exact"], a["simple_payback_period"], a["simple_payback_interpolated"], a["discounted_payback_period"], a["discounted_payback_interpolated"],
            a["capacity_hours_excluded"]) == ("41.32", "5000/121", "2", "1.6667", "2", "1.9167", "800.00")
    assert F(a["npv_exact"]) == F(-1000) + F(600) / F(11, 10) + F(600) / F(11, 10) ** 2
    e = exp["metrics"]["scenarios"]["scn-001"]["initiatives"]["init-001"]
    assert (a["npv"], a["npv_exact"]) == (e["npv"]["value"], e["npv"]["exact"])
    p = RES["10_golden_known_answer__portfolio"][0]
    assert (p["sum_of_initiatives"], p["double_counted_pv"], p["attributable_npv"], p["attributable_exact"], p["residual"]) == ("-692.56", "61.98", "-754.55", "-8300/11", "75.00")
    assert p["attributable_npv"] == exp["metrics"]["scenarios"]["scn-001"]["npv_total"]["value"]
    i = rows_by("10_golden_known_answer__initiatives", "initiative_id")
    assert (i["init-002"]["npv_exact"], i["init-002"]["discounted_reason"], i["init-003"]["npv_exact"], i["init-003"]["simple_reason"]) == ("-7000/121", "NOT_RECOVERED", "-81800/121", "NOT_RECOVERED")
    from changeworks import run_pipeline
    inputs = json.loads((ROOT / "tests/fixtures/golden/inputs.json").read_text())
    assert run_pipeline(inputs).golden() == exp
    assert RES["meta"][0]["golden_dataset_hash"] == hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def test_stored_results_equal_the_python_side_recomputation_over_the_snapshot_files(ps, P):
    for key, rows in P.items():
        assert ps.normalised(rows) == RES[key], key


def test_stored_reference_figures_equal_the_domain(world):
    M = world["M"]
    s = M["scenarios"]["scn-025"]
    port = row_of("02_initiative_npv__portfolio_scn025")
    assert (port["attributable_npv"], port["sum_of_initiatives"], port["double_counted_pv"]) == (s["npv_total"]["value"], s["npv_total"]["sum_of_initiatives"], s["double_count"]["double_counted_pv"])
    for r in RES["02_initiative_npv__scn025"]:
        assert r["npv"] == s["initiatives"][r["initiative_id"]]["npv"]["value"], r["initiative_id"]
    for r in RES["04_payback__scn025"]:
        pb = s["initiatives"][r["initiative_id"]]["payback"]
        assert (r["simple_payback_period"], r["simple_reason"], r["discounted_payback_period"], r["discounted_reason"]) == (
            str(pb["simple"]["period"] or ""), pb["simple"]["reason"] or "", str(pb["discounted"]["period"] or ""), pb["discounted"]["reason"] or ""), r["initiative_id"]
    for r in RES["03_double_count__by_scenario"]:
        d = M["scenarios"][r["scenario_id"]]["double_count"]
        assert (r["residual"], r["hours_residual"], r["double_counted_pv"]) == (d["residual"], d["hours_residual"], d["double_counted_pv"]), r["scenario_id"]
    po = row_of("07_adoption_training__pooled")
    assert (po["adoption_rate_pooled"], po["training_completion_pooled"]) == (M["summary"]["adoption_rate"], M["summary"]["training_completion"])
    for r in RES["06_variance_realisation__cost_variance_scn025"]:
        assert r["variance"] == (s["initiatives"][r["initiative_id"]]["cost_variance"]["variance"] or ""), r["initiative_id"]
    for r in RES["09_roadmap_capacity__dependency_delay"]:
        rd = M["initiatives"][r["initiative_id"]]["roadmap"]
        assert (int(r["dependency_feasible_start"]), int(r["dependency_delay"]), r["binding_dependency_id"]) == (rd["dependency_feasible_start"], rd["dependency_delay"], rd["binding_dependency_id"] or "")
    v3 = [r["total"] for r in RES["08_forecast_revisions__init003_versions"]]
    assert v3 == [v["total"] for v in M["initiatives"]["init-003"]["forecast"]["versions"]]


def test_the_analysis_npv_exact_rationals_equal_the_domains(world):
    s = world["M"]["scenarios"]
    for r in RES["02_initiative_npv__scn025_exact"]:
        assert r["npv_exact"] == s["scn-025"]["initiatives"][r["initiative_id"]]["npv"]["exact"], r["initiative_id"]
    for r in RES["02_initiative_npv__by_scenario_exact"]:
        assert r["attributable_exact"] == s[r["scenario_id"]]["npv_total"]["exact"], r["scenario_id"]
    for r in RES["bi_measures"]:                                                          # the BI NPVs are recomputed from the CSV facts and equal the domain's
        if r["measure"] == "Attributable NPV":
            assert r["value"] == s[r["slice"]]["npv_total"]["value"], r["slice"]


def test_headline_numbers_of_the_documents_are_the_stored_ones():
    memo, case, tcs, bi, wbdoc, sqla = read("executive-memo.md"), read("business-case.md"), read("technical-case-study.md"), read("bi-package.md"), read("workbook.md"), read("sql-analysis.md")
    port = row_of("02_initiative_npv__portfolio_scn025")
    for doc in (memo, case, wbdoc, sqla):
        for v in (port["attributable_npv"], port["sum_of_initiatives"], port["double_counted_pv"]):
            assert f"{float(v):,.2f}" in doc, v
    key = RES["03_double_count__by_source_key"]
    assert f"{float(key[0]['residual']):,.2f}" in memo and f"{float(key[1]['residual']):,.2f}" in memo and key[0]["benefit_source_key"] in memo
    po = row_of("07_adoption_training__pooled")
    for doc in (memo, case, sqla):
        assert po["adoption_rate_pooled"] in doc and po["training_completion_pooled"] in doc
    opt = rows_by("11_proposal_screen__options", "option_id")
    assert f"{float(opt['D']['attributable_npv']):,.2f}" in memo and f"{float(opt['D']['planned_costs']):,.2f}" in memo and f"{float(opt['B']['attributable_npv']):,.2f}" in memo
    for i in opt["D"]["members"].split(","):
        assert f"`{i}`" in memo, i
    n = RES["meta"][0]["reconciliation_rows"]
    for doc in (memo, tcs, read("requirements.md"), read("resume-bullets.md"), wbdoc, case, sqla):
        assert f"{n} " in doc or f"{n}\n" in doc, n
    assert DATASET_HASH in bi and CODE_REVISION in bi
    assert f"{RES['meta'][0]['analysis_leaves_snapshot']:,}" in sqla and f"{RES['meta'][0]['analysis_leaves_snapshot']:,}" in memo


def test_designed_relationships_and_defects_are_present_in_the_results():
    dr = {d["id"]: d["realised"] for d in json.loads((ROOT / "web/public/data/injection-manifest.json").read_text())["designed_relationships"]}
    s25 = rows_by("01_portfolio_ledger__scn025_by_initiative", "initiative_id")
    assert s25["init-009"]["capacity_hours_not_converted"] == dr["DR-01"]["capacity_hours_not_converted"] and row_of("02_initiative_npv__scn025", initiative_id="init-009")["npv"] == dr["DR-01"]["npv"]
    pv = row_of("03_double_count__present_value_scn025")
    assert (pv["double_counted_amount"], pv["double_counted_pv"], pv["hours_residual"], pv["npv_attributable"]) == (dr["DR-02"]["residual"], dr["DR-02"]["double_counted_pv"], dr["DR-02"]["hours_residual"],
                                                                                                            dr["DR-02"]["npv_total_attributable"])
    for r in RES["04_payback__init015_by_scenario"]:
        assert r["benefit_to_cost"] == dr["DR-03"]["by_scenario"][r["scenario_id"]]["benefit_to_cost"] and r["simple_payback_period"] == ""
    assert [r["total"] for r in RES["08_forecast_revisions__init003_versions"]] == [v["total"] for v in dr["DR-04"]["versions"]]
    assert [int(r["period_index"]) for r in RES["09_roadmap_capacity__resource_at_capacity"]] == dr["DR-05"]["periods"] == [12, 13, 14, 15, 16]
    assert all(r["refused_overallocated"] == "true" for r in RES["09_roadmap_capacity__refused_requests"])
    assert row_of("06_variance_realisation__trend_beside_raw")["trend_share_of_observed"] == dr["DR-06"]["trend_share_of_observed"] == "0.848744"
    assert row_of("07_adoption_training__lag_summary")["lag_periods_sorted"] == "4,4,5,5,6"
    assert [r["initiative_id"] for r in RES["09_roadmap_capacity__deployment_before_feasible_start"]] == ["init-018", "init-019", "init-020"]
    assert row_of("09_roadmap_capacity__refused_cycle")["cycle_it_would_close"] == "init-001 -> init-004 -> init-001"
    assert row_of("09_roadmap_capacity__cycle_check")["cycles_found"] == "0" and row_of("05_cost_expansion__one_time_rule")["cost_keys_in_more_than_one_period"] == "0"
    # the mutation guard: the rows compare different sources, so a one-leaf change to a stored figure would break a row
    assert all(r["analysis_sql"] == r["second_source"] for r in RES["reconciliation"]) and sum(1 for r in RES["reconciliation"] if r["third_source"]) > 100


@pytest.mark.skipif(not (os.environ.get("ARTIFACTS_DATABASE_URL") and os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL")),
                    reason="ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts09_*; the test prepares them with data/sql/analysis/prepare_snapshot.py) are not set")
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
        ra.run_script(c, SQL_DIR / "00_portfolio_model.sql")
        for prefix in NUMBERED:
            f = next(SQL_DIR.glob(f"{prefix}_*.sql"))
            for key, rows in ra.run_file(c, f).items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key
        for name in ra.BI_FILES:
            for key, rows in ra.run_file(c, SQL_DIR / f"{name}.sql").items():
                csv_name = key.split("__")[-1] if "__" in key else key.removeprefix("bi_")
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == _csv(csv_name), csv_name
        leaves = ra.leaves(c)
        ref = ra.reference(c, "2026-10-05T00:00:00Z")
        assert len(leaves) == RES["meta"][0]["analysis_leaves_snapshot"] and all(ref[p] == v for p, v in leaves.items())
    with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        ra.run_script(c, SQL_DIR / "00_portfolio_model.sql")
        for key, rows in ra.run_file(c, SQL_DIR / "10_golden_known_answer.sql").items():
            assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key


def test_a_database_rerun_without_the_scratch_urls_is_skipped_with_a_reason():
    marks = [m for m in test_sql_files_rerun_against_the_prepared_databases_give_the_stored_rows.pytestmark if m.name == "skipif"]
    assert marks and "ARTIFACTS_DATABASE_URL" in marks[0].kwargs["reason"] and SCRATCH in marks[0].kwargs["reason"] and "ARTIFACTS_GOLDEN_DATABASE_URL" in marks[0].kwargs["reason"]


def test_scratch_guard_refuses_a_non_scratch_database(prep):
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/changeworks")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts08_snapshot")
    prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts09_snapshot")
    with pytest.raises(SystemExit):
        prep.create_database("postgresql://u:p@127.0.0.1:5432/postgres", "changeworks")
    with pytest.raises(SystemExit):
        prep.drop_database("postgresql://u:p@127.0.0.1:5432/postgres", "changeworks")
    assert prep.SCRATCH_PREFIX == SCRATCH


def test_every_sql_file_has_its_header_and_the_numbered_files_read_only():
    files = sorted(SQL_DIR.glob("[01][0-9]_*.sql"))
    assert [f.name[:2] for f in files] == ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11"]
    for f in files + [SQL_DIR / "leaves.sql"]:
        text = f.read_text()
        if f.name.startswith("00_"):
            assert text.startswith("-- P09-ART-04 setup:"), f.name
        elif f.name == "leaves.sql":
            assert text.startswith("-- P09-ART-04 leaves:")
        else:
            assert re.match(rf"-- P09-ART-04 investigation {f.name[:2]}:", text), f.name
        assert "D-0" in text, f.name
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b", body, re.I), f.name                 # read only
        if not f.name.startswith("00_"):
            assert "CREATE" not in body, f.name
        assert not re.search(r"\bpower\s*\(", body, re.I), f.name                                             # exact: no power()
        assert not re.search(r"ORDER BY \d+ COLLATE", body), f.name
        for m in re.finditer(r"ORDER BY ([^\n]*)", body):                                                  # locale independent: a bare text key is COLLATE "C"
            for term in re.split(r",(?![^()]*\))", m.group(1)):
                s = term.strip()
                if "COLLATE" not in s and re.fullmatch(r"[\w.]*(_id|_key|name|path|class|reason|benefit_type|cost_type|cost_basis|rule)( (DESC|ASC))?", s):
                    raise AssertionError(f"{f.name}: text ORDER BY without COLLATE \"C\": {s}")
    setup = (SQL_DIR / "00_portfolio_model.sql").read_text()
    assert len(re.findall(r"CREATE TEMP TABLE", setup)) == 23 and "CREATE TABLE" not in setup.replace("CREATE TEMP TABLE", "")
    for f in sorted(SQL_DIR.glob("bi_*.sql")):
        assert "P09-ART-06" in f.read_text(), f.name
    assert not re.search(r"(?i)\b(insert|update|delete|drop|alter|create)\b", "\n".join(l for l in "\n".join(f.read_text() for f in SQL_DIR.glob("bi_*.sql")).splitlines() if not l.strip().startswith("--")))
    for f in files:                                                                  # every block of a file is a single statement
        for line in f.read_text().splitlines():
            if line.startswith("-- @@ "):
                assert re.fullmatch(r"-- @@ \w+", line), line


def test_the_model_is_the_analysis_own_text_and_not_a_copy_of_the_reference_sql():
    ref = (ROOT / "data/sql/reference_metrics.sql").read_text()
    mine = (SQL_DIR / "00_portfolio_model.sql").read_text()
    for token in ("sc_t AS", "pay_i AS", "dc_rank AS", "hpairs AS", "cap_lab AS", "out(path, val)"):
        assert token in ref and token not in mine, token
    assert "reference_metrics" not in "\n".join(l for l in mine.splitlines() if not l.startswith("--"))
    py = (SQL_DIR / "python_side.py").read_text()
    assert "import changeworks" not in py and "from changeworks" not in py and "psycopg" not in py.split('"""', 2)[2]


# ---- the workbook --------------------------------------------------------------------------------------------------------------------------

def _b(v):
    """LibreOffice stores a typed TRUE/FALSE constant as the formula =TRUE() / =FALSE() when it saves the recalculated file; read both forms as the boolean."""
    return {"=TRUE()": True, "=FALSE()": False}.get(v, v)


def test_workbook_sheets_present_and_assumptions_listed(wb, bw):
    assert wb.sheetnames == bw.SHEET_ORDER
    ws = wb["Assumptions"]
    ids = {ws.cell(row=r, column=1).value for r in range(4, 40)}
    assert {"A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "W-01", "W-02", "W-03", "W-04", "W-05", "W-06"} <= ids
    text = " ".join(str(ws.cell(row=r, column=2).value) for r in range(4, 40))
    assert "Excel was NOT run" in text and "LibreOffice" in text and "TYPED" in text
    c = wb["Controls"]
    assert c["B3"].value == "scn-025" and c["B15"].value == "=Checks!B2" and c["B4"].value is None
    assert any(dv.formula1 == "Scenarios!$A$4:$A$33" for dv in c.data_validations.dataValidation)


def test_data_sheets_equal_the_snapshot_and_the_independent_side(wb, ps):
    c = ps.load_snapshot()
    ben = sorted(c.rows["benefit_items"], key=lambda b: b["benefit_id"])
    ws = wb["Benefits"]
    assert len(ben) == 700 and ws.cell(row=703, column=1).value == ben[-1]["benefit_id"] and ws.cell(row=704, column=1).value is None
    for i in (0, 100, 699):
        b = ben[i]
        assert [ws.cell(row=4 + i, column=k).value for k in (1, 2, 5, 6, 7)] == [b["benefit_id"], b["initiative_id"], b["benefit_type"], b["period_index"], b["starts_period"]]
        assert F(str(ws.cell(row=4 + i, column=8).value)) == ps.dec(b["amount"])
    cs = wb["Costs"]
    assert cs.cell(row=903, column=1).value is not None and cs.cell(row=904, column=1).value is None
    si = wb["Scenario inputs"]
    for r in (4, 100, 213):
        sid, iid = si.cell(row=r, column=2).value, si.cell(row=r, column=3).value
        m = c.model(sid, iid)
        assert si.cell(row=r, column=4).value == m["ramp_id"] and si.cell(row=r, column=5).value == len(m["ramp"] or [])
        assert (si.cell(row=r, column=14).value is None) == (m["rate_cap"] is None)
    assert wb["Scenarios"].cell(row=33, column=1).value == "scn-030"


def test_result_cells_of_the_formula_sheets_are_live_formulas_without_hardcoded_figures(wb):
    cf = wb["Cash flow"]
    for r in (4, 400, 867):
        for col in range(3, 18):
            v = cf.cell(row=r, column=col).value
            assert isinstance(v, str) and v.startswith("="), (r, col, v)
    ini = wb["Initiatives"]
    for r in range(4, 28):
        for col in range(2, 22):
            v = ini.cell(row=r, column=col).value
            assert isinstance(v, str) and v.startswith("="), (r, col)
    pf = wb["Portfolio"]
    for r in range(4, 21):
        assert str(pf.cell(row=r, column=2).value).startswith("="), r
    bn = wb["Benefits"]
    for r in (4, 300, 703):
        for col in range(13, 30):
            assert str(bn.cell(row=r, column=col).value).startswith("="), (r, col)
    g = wb["Golden case"]
    for r in range(4, 21):
        v = g.cell(row=r, column=3).value
        assert v is None or str(v).startswith("="), r
    assert wb["Checks"]["B2"].value.startswith("=AND(") and wb.calculation.fullCalcOnLoad


def test_cached_values_equal_the_domain_recomputed_here(wbv, world):
    s = world["M"]["scenarios"]["scn-025"]
    assert wbv["Checks"]["B2"].value is True and wbv["Controls"]["B15"].value is True and all(wbv["Checks"][c].value is True for c in ("B5", "B6", "B7"))
    assert abs(wbv["Controls"]["B16"].value - float(s["npv_total"]["value"])) < 0.005
    ini = wbv["Initiatives"]
    for r in range(4, 28):
        iid = ini.cell(row=r, column=1).value
        d = s["initiatives"][iid]
        assert abs(ini.cell(row=r, column=7).value - float(d["npv"]["value"])) < 0.005, iid
        assert (ini.cell(row=r, column=10).value or None) == d["payback"]["simple"]["period"], iid
        assert (ini.cell(row=r, column=15).value or None) == d["payback"]["discounted"]["period"], iid
        assert ini.cell(row=r, column=21).value is True, iid
    pf = wbv["Portfolio"]
    want = {"NPV, attributable (the headline)": s["npv_total"]["value"], "NPV, plain sum of the initiative NPVs": s["npv_total"]["sum_of_initiatives"],
            "double-counted amount (the residual): claims beyond the largest of a shared key": s["double_count"]["residual"], "hours residual (shared capacity counted twice)": s["double_count"]["hours_residual"]}
    seen = {}
    for r in range(4, 21):
        lab = pf.cell(row=r, column=1).value
        if lab in want:
            seen[lab] = pf.cell(row=r, column=2).value
            assert abs(seen[lab] - float(want[lab])) < 0.005, lab
        if pf.cell(row=r, column=5).value is not None:
            assert pf.cell(row=r, column=5).value is True, lab
    assert set(seen) == set(want)
    g = wbv["Golden case"]
    assert abs(g["C8"].value - 5000 / 121) < 1e-9 and abs(g["C19"].value + 8300 / 11) < 1e-9 and g["E20"].value is True


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
    assert v["Checks"]["B2"].value is True and v["Controls"]["B15"].value is True and v["Controls"]["B3"].value == "scn-025"


@needs_lo
@pytest.mark.parametrize("scenario", ["scn-001", "scn-006", "scn-015", "scn-030"])
def test_the_scenario_switch_is_live_and_the_check_cell_stays_true(tmp_path, world, scenario):
    flip = openpyxl.load_workbook(XLSX)                         # formulas only: openpyxl drops the cached values on save
    flip["Controls"]["B3"] = scenario
    src = tmp_path / f"{scenario}.xlsx"
    flip.save(src)
    assert openpyxl.load_workbook(src, data_only=True)["Checks"]["B2"].value is None          # no cached values until recalculated
    v = openpyxl.load_workbook(_lo_recalc(src, tmp_path / scenario), data_only=True)
    s = world["M"]["scenarios"][scenario]
    assert v["Checks"]["B2"].value is True and v["Controls"]["B3"].value == scenario
    assert abs(v["Controls"]["B16"].value - float(s["npv_total"]["value"])) < 0.005
    assert v["Controls"]["B12"].value == s["horizon_periods"] and abs(v["Controls"]["B11"].value - float(s["effective_period_rate_exact"].split("/")[0]) / float(s["effective_period_rate_exact"].split("/")[1])) < 1e-12


def test_pasted_sql_results_sheet_matches_the_stored_results(wb):
    ws = wb["SQL results (pasted)"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    meta = RES["meta"][0]
    assert any(isinstance(c, str) and f"reconciliation rows {meta['reconciliation_rows']}, equal {meta['reconciliation_equal']}" in c and DATASET_HASH in c and CODE_REVISION in c for c in cells)
    assert float(row_of("02_initiative_npv__portfolio_scn025")["attributable_npv"]) in cells and "5000/121" in cells
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)               # pasted values, not formulas


# ---- the BI package ------------------------------------------------------------------------------------------------------------------------

def _csv(name: str) -> list[dict]:
    with (ART / "bi" / f"{name}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


BI = ["dim_initiative", "dim_scenario", "dim_benefit_class", "dim_period", "dim_resource", "fact_scenario", "fact_scenario_initiative", "fact_cash_flow", "fact_double_count",
      "fact_realisation", "fact_adoption", "fact_forecast", "fact_resource", "fact_risk"]


def test_bi_exports_have_the_documented_grain_and_equal_the_snapshot(world):
    sizes = {n: len(_csv(n)) for n in BI}
    assert sizes == {"dim_initiative": 24, "dim_scenario": 30, "dim_benefit_class": 6, "dim_period": 36, "dim_resource": 8, "fact_scenario": 30, "fact_scenario_initiative": 210,
                     "fact_cash_flow": 7212, "fact_double_count": 240, "fact_realisation": 264, "fact_adoption": 24, "fact_forecast": 144, "fact_resource": 155, "fact_risk": 120}
    ids, scns = {r["initiative_id"] for r in _csv("dim_initiative")}, {r["scenario_id"] for r in _csv("dim_scenario")}
    for name in ("fact_scenario_initiative", "fact_cash_flow", "fact_double_count", "fact_realisation"):
        assert {r["initiative_id"] for r in _csv(name)} <= ids and {r["scenario_id"] for r in _csv(name)} <= scns, name
    assert {int(r["period_index"]) for r in _csv("fact_cash_flow")} <= {int(r["period_index"]) for r in _csv("dim_period")}
    assert len({(r["scenario_id"], r["initiative_id"]) for r in _csv("fact_scenario_initiative")}) == 210
    for r in _csv("fact_scenario_initiative"):                                         # nothing withheld silently: an empty payback carries its reason
        if r["simple_payback_period"] == "":
            assert r["simple_payback_reason"] in ("NOT_RECOVERED", "NO_INVESTMENT", "NO_FLOWS"), r
        assert r["npv"] == (world["M"]["scenarios"][r["scenario_id"]]["initiatives"][r["initiative_id"]]["npv"]["value"] or "")
    for r in _csv("fact_adoption"):
        assert (r["adoption_rate"] == "") == (r["adoption_status"] != "value")


def test_bi_measures_recomputed_from_the_csv_files_equal_the_stored_values_and_the_domain(ra, world):
    csvs = {n: _csv(n) for n in BI}
    rows = ra.bi_measures(csvs)
    assert rows == RES["bi_measures"] == _csv("measures_recomputed")
    mv = {(m["measure"], m["slice"]): m for m in rows}
    M = world["M"]
    for sid, s in M["scenarios"].items():
        assert mv[("Attributable NPV", sid)]["value"] == s["npv_total"]["value"] and mv[("Hours Residual", sid)]["value"] == s["double_count"]["hours_residual"], sid
        assert mv[("Planned Benefits", sid)]["value"] == s["double_count"]["planned_benefits"], sid
    assert mv[("Adoption Rate", "pooled")]["value"] == M["summary"]["adoption_rate"] and mv[("Training Completion", "pooled")]["value"] == M["summary"]["training_completion"]
    assert mv[("Risk Exposure", "portfolio")]["value"] == M["summary"]["risk_exposure_total"]
    assert all(m["status"] != "value" for m in rows if m["value"] == "") and all(m["scope"] for m in rows)          # an empty value always says why; every figure has a scope


def test_bi_package_defines_every_measure_and_makes_no_pbix_claim():
    doc = read("bi-package.md")
    assert "No `.pbix` was produced" in doc and "pseudocode" in doc and "not executed" in doc and "Power BI Desktop is not available here and was not run" in doc
    for m in ("Selected Scenario", "Period Rate", "Planned Costs", "Cash Benefits", "Revenue Benefits", "Avoided Cost Realised", "Capacity Converted", "Avoided Cost Beside",
              "Capacity Hours Not Converted", "Planned Benefits", "Double Counted Amount", "Attributable Benefits", "Hours Residual", "NPV Sum Of Initiatives", "Double Counted PV",
              "Attributable NPV", "Initiatives Never Paying Back", "Simple Payback", "Discounted Payback", "Cost Variance", "Benefit Realisation", "Baseline Trend Share", "Adoption Rate",
              "Training Completion", "Adoption Gap", "Forecast Total", "Forecast Revision Change", "Resource Periods At Capacity", "Resource Periods Over Capacity", "Risk Exposure"):
        assert f"`{m} =" in doc, m
    assert doc.count("DIVIDE") >= 4 and "SELECTEDVALUE" in doc and "BLANK" in doc and "never 0" in doc and "withheld silently" in doc and "never be summed across scenarios" in doc
    for name in BI + ["measures_recomputed"]:
        assert f"`{name}`" in doc and f"artifacts/bi/{name}.csv" in doc, name
    assert DATASET_HASH in doc and CODE_REVISION in doc
    assert not list(ROOT.rglob("*.pbix"))
    sizes = {**{n: len(_csv(n)) for n in BI}, "measures_recomputed": len(RES["bi_measures"])}
    for name, n in sizes.items():
        assert re.search(rf"\| `{name}` \|[^\n]*\| {n:,} \|", doc), name


# ---- data dictionary, ERD, SQL analysis document -------------------------------------------------------------------------------------------------------------

def _tables_and_columns() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    pat = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", re.S)
    col = re.compile(r"(?m)^\s*([a-z_0-9]+)\s+(TEXT|INT|BIGINT|BOOLEAN|TIMESTAMPTZ|JSONB|DATE|NUMERIC\(\d+,\d+\))")
    for m in pat.finditer((ROOT / "data/sql/migrations/0001_schema.sql").read_text()):
        out[m.group(1)] = [c[0] for c in col.findall(m.group(2))]
    for t, c in re.findall(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", (ROOT / "data/sql/migrations/0003_review9.sql").read_text()):
        out[t].append(c)
    out["schema_migrations"] = ["version", "checksum", "applied_at"]
    assert "schema_migrations (" in (ROOT / "data/migrate.py").read_text()
    return out


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations(world):
    tables = _tables_and_columns()
    assert len(tables) == 28
    dd, erd = read("data-dictionary.md"), read("erd.md")
    assert "```mermaid" in erd and "erDiagram" in erd
    section2 = dd.split("## 2. Columns", 1)[1].split("\n## 3.", 1)[0]
    heads = {}
    for block in section2.split("\n### ")[1:]:
        t, body = block.split("\n", 1)
        heads[t.strip()] = body
    for t, cols in tables.items():
        assert f"`{t}`" in dd, t
        assert re.search(rf"^\s+{t} \{{", erd, re.M), t
        assert t in heads, t
        for c in cols:
            assert f"`{c}`" in heads[t], (t, c)
            assert re.search(rf"^\s+\w+ {c}$", erd, re.M), (t, c)
    for key in ("grain", "Deletion policy", "Append-only", "rejected_records", "Source-to-target", "Foreign keys", "cw_forbid_mutation", "COST_KEY_BASIS_CONFLICT", "half-open", "hours", "synthetic", "source file"):
        assert key.lower() in dd.lower(), key
    for k, v in world["manifest"]["row_counts"].items():
        assert re.search(rf"\| `{k}` \|[^\n]*\| {v:,} \|", dd), k
    assert DATASET_HASH in dd and CODE_REVISION in dd and DATASET_HASH in erd and CODE_REVISION in erd


def test_sql_analysis_doc_quotes_the_stored_results_and_every_table_is_rendered_from_them(P):
    render = _load("cw_render", ART / "render_sql_analysis.py")
    for name in ("sql-analysis.md", "bi-package.md"):
        text = read(name)
        assert render.render(text, RES) == text, f"{name} drifted from artifacts/analysis-results.json: run artifacts/render_sql_analysis.py"
        assert "(to be rendered)" not in text
    doc = read("sql-analysis.md")
    for key in P:
        if key not in EXACT_KEYS:
            assert f"<!-- BEGIN:{key} -->" in doc, key
    assert "<!-- BEGIN:reconciliation -->" in doc and DATASET_HASH in doc and CODE_REVISION in doc
    for sentence in ("constructed", "observed", "hypothetical", "Excel and Power BI were not run", "which transformation initiative should be funded, and how will success be established?",
                     "Mutation check", "COLLATE \"C\"", "observed, not attributed", "plan estimate", "**1,243,149.05**", "**1,438,382.25**", "**195,233.20**", "**207,146.32**", "**5,974.80**",
                     "**0.531465**", "**0.620043**", "**745,800.06**", "**598,900.05**", "**534,207.54**", "**0.532881**", "**0.888443**", "**0.963778**", "periods 12..16", "**41.32**",
                     "**5000/121**", "**1.6667**", "**1.9167**", "`DEPLOYMENT_BEFORE_FEASIBLE_START`", "**2,876,982.64**"):
        assert sentence in doc, sentence
    n = RES["meta"][0]["reconciliation_rows"]
    assert f"All {n} rows are equal again" in doc


def test_the_documents_name_the_real_entities_metrics_and_commands_and_keep_result_kinds_apart():
    case = read("business-case.md")
    for token in ("Which transformation initiative should be funded, and how will success be established?", "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10",
                  "establish-baseline", "assess-opportunity", "build-cash-flows", "map-impacts", "assess-readiness", "plan-roadmap", "select-scenario", "record-adoption", "track-benefits",
                  "revise-forecast", "scenario_versions", "cost_items", "benefit_items", "assumption_versions", "forecast_versions", "adoption_observations", "P09-MET-", "P09-FLOW-",
                  "P09-TEST-", "P09-DOMAIN-", "observed", "constructed", "hypothetical", "Decision criteria", "Current-state", "future-state", "Simulated stakeholders", DATASET_HASH,
                  CODE_REVISION, "1,243,149.05", "0.532881", "Mode A and Mode B", "DR-01..DR-07", "INJ-01..INJ-12", "Scope"):
        assert token in case, token
    assert "no figure below is one" in case and "Excel" in case and "Power BI" in case and "funds nothing" in case


def test_requirements_trace_every_requirement_family():
    req = read("requirements.md")
    for fam in ("P09-GOAL", "P09-DOMAIN-01", "P09-DOMAIN-06", "P09-GOLD-01", "P09-DATA-01..12", "P09-UI-01..10", "P09-TEST-01..12", "P09-ART", "P09-REL", "P09-WORK"):
        assert fam in req, fam
    for fam in ["P09-MET-%02d" % i for i in range(1, 13)] + ["P09-FLOW-%02d" % i for i in range(1, 11)]:
        assert fam in req, fam
    assert "Functional requirements" in req and "Non-functional requirements" in req and "User stories" in req and "Traceability" in req and "Acceptance criteria" in req
    for run in ("40474351325", "40474949237"):
        assert run in req, run
    tests_text = all_test_names()
    named = set(re.findall(r"`(test_[a-zA-Z0-9_]+)`", req))
    assert len(named) > 40
    for doc in ("requirements.md", "technical-case-study.md", "uat-evidence.md", "executive-memo.md", "release-package.md"):
        for t in set(re.findall(r"`(test_[a-zA-Z0-9_]+)`", read(doc))):
            assert f"def {t}(" in tests_text, f"{doc} cites a test that does not exist: {t}"
    spec = (ROOT / "web/e2e/journey.spec.ts").read_text()
    for doc in ("requirements.md", "uat-evidence.md"):
        for t in re.findall(r'e2e "([^"]+)"', read(doc)):
            assert f'"{t}"' in spec, t
    assert DATASET_HASH in req and CODE_REVISION in req and "deferred" in req and "not_checked" in req and "pending" in req
    assert "no-skip gate" in req and "hosted" in req


def test_executive_memo_quotes_the_evidence_options_and_the_caveats():
    memo = read("executive-memo.md")
    for token in ("OBSERVED", "SIMULATED", "HYPOTHETICAL", "## Decision", "| Option |", "## Evidence", "## Uncertainty", "## Limitations", "## Recommendation", "How success will be established",
                  "**2,876,982.64**", "**11,779,550.00**", "**1,243,149.05**", "**0.531465**", "**0.667307**", "**0.532881**", "**0.888443**", "**+253,802.33**", "4,560,340.34",
                  "2,177,441.56", "207,146.32", "5,974.80", "`init-006`", "`init-009`", "`init-015`", "`init-019`", "`init-021`", "`init-022`", "stage gate", "One draw",
                  "disclosed in the manifest", "Excel and Power BI were not run", "does not support any statement about a realised benefit", "judgement", "nothing is funded",
                  DATASET_HASH, CODE_REVISION, "observed, not attributed", "before their feasible start"):
        assert token in memo, token
    assert not re.search(r"\b(saves?|saved|savings|roi)\b", memo, re.I)
    assert "(recommended)" in memo and memo.count("| **") >= 1


def test_uat_evidence_has_routes_screenshots_scenarios_and_run_links():
    uat = read("uat-evidence.md")
    for token in ("40474351325", "40474949237", "8b9bcd3", "29948f9", "pending", "did **not** run `npm run e2e`", "did not fetch", "expected answer", "actual observation", "disposition",
                  "Defect disposition", "R9-01", "R9-12", "R9-22", DATASET_HASH, "created by this pass"):
        assert token.lower() in uat.lower() or token in uat, token
    routes_ts = (ROOT / "web/src/routes.ts").read_text()
    for p in re.findall(r'path: "([a-z-]+)"', routes_ts):
        assert f"`/{p}/`" in uat, p
    assert "`/`" in uat
    for shot in ("home", "portfolio", "baseline", "business-case", "business-case-golden", "sensitivity", "roadmap", "impact", "readiness", "benefits", "forecast", "evidence", "case-study"):
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
        assert (st["expected"], st["unexpected"], st["flaky"], st["skipped"]) == (81, 0, 0, 0)


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    tcs, rel = read("technical-case-study.md"), read("release-package.md")
    for token in ("Architecture", "Trade-offs", "Recovery behaviour", "Reproducible setup", "Measured evidence", "Open gaps", "```mermaid", "R9-01", "R9-12", "R9-20", "40474351325",
                  "40474949237", DATASET_HASH, CODE_REVISION, "763 reconciliation rows", "Excel and Power BI Desktop were not run", "no hosted run of `tests/test_artifacts.py` is recorded yet",
                  "3,156", "454"):
        assert token in tcs or token.lower() in tcs.lower(), token
    for token in ("8b9bcd3", "d58209f", CODE_SHA, "40474351325", "40474949237", "pending at dispatch", "Rollback procedure", "git revert", "Artifacts and checksums", DATASET_HASH,
                  "74c310decb2c226c20a52ffda92c79f927cc094287f6b37ecde135e2ac5a8439", "committed and pushed nothing", "Main-portfolio metadata", "Excel", "Power BI", "not fetch",
                  "What this artifact pass ran", "**stale**", "true but ambiguous", "contradicted"):
        assert token in rel, token
    assert "lab:lab" not in rel and "RUN_LOG_SECTION" not in rel
    if shutil.which("git"):
        for c in ("8b9bcd3", "d58209f", CODE_REVISION):
            probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", c], capture_output=True, text=True)
            if probe.returncode != 0:
                pytest.skip(f"commit {c} is not in this checkout")
        assert "changeworks: review R9 fixes" in subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%s", CODE_REVISION], capture_output=True, text=True).stdout
    mpath = ROOT.parents[1] / "docs" / "program" / "release-manifest.json"
    if mpath.exists():
        site = next(s for s in json.loads(mpath.read_text())["sites"] if s["slug"] == "changeworks")
        if site["source_commit_business_data_lab"] == CODE_SHA:            # a later republish moves the manifest on; the package describes 29948f9
            assert site["release_commit_unified_portfolio"] == "8b9bcd3" and site["rollback_commit_unified_portfolio"] == "d58209f"
            assert site["dataset_hash"] == DATASET_HASH and site["published_tree_sha256"] in rel
            if site["live_verification"] is None:
                assert "pending at dispatch" in rel
            else:
                assert site["live_verification"]["run_url"].rsplit("/", 1)[1] in rel


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact_and_match_the_public_case_study():
    text = read("resume-bullets.md")
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6
    body = " ".join(bullets)
    assert not re.search(r"\b(saved|savings|reduced (?:cost|time)|increased revenue|users|customers? adopted|roi)\b", body, re.I)
    for token in ("D-01..D-09", "454 Python tests", "3,156-check", "48,476 leaves", "R9-01..R9-22", "LibreOffice", "no `.pbix`", "5000/121 = 41.32", "1,243,149.05", "1,438,382.25"):
        assert token in body, token
    assert "synthetic" in text.lower() and "no bullet claims business impact" in text
    assert str(RES["meta"][0]["reconciliation_rows"]) in body
    if PROJECT:
        assert "1,243,149.05" in PROJECT["results"] and "454 tests" in PROJECT["built"]


def test_public_case_study_figures_agree_with_the_stored_results():
    if PROJECT is None:
        pytest.skip("the public case study changeworks/project.json is not in this checkout (it lives on unified-portfolio)")
    text = re.sub(r"<[^>]+>", " ", PROJECT["results"] + PROJECT["built"] + PROJECT["tagline"]).replace("−", "-")
    led = row_of("01_portfolio_ledger__by_scenario", scenario_id="scn-025")
    for k in ("planned_costs", "cash", "revenue", "avoided_cost_realised", "capacity_converted", "avoided_cost_beside", "capacity_hours_not_converted", "planned_benefits", "attributable_benefits",
              "double_counted_amount", "hours_residual"):
        assert f"{float(led[k]):,.2f}" in text, k
    port = row_of("02_initiative_npv__portfolio_scn025")
    for k in ("sum_of_initiatives", "double_counted_pv", "attributable_npv"):
        assert f"{float(port[k]):,.2f}" in text, k
    assert sum(1 for r in RES["04_payback__scn025"] if r["simple_payback_period"] == "") == 6 and "six initiatives never reach simple payback" in text
    assert "0.531465" in text and "0.620043" in text and "745,800.06" in text and "598,900.05" in text and "534,207.54" in text and "(12 to 16" in text
    po, cp = row_of("07_adoption_training__pooled"), row_of("07_adoption_training__common_population")
    assert po["training_completion_pooled"] in text and cp["training_completion_pooled"] in text and po["adoption_rate_pooled"] in text and "0.848744" in text
    assert "5000/121 = 41.32" in text and "1.6667" in text and "1.9167" in text
    # the points reported to the coordinator (release-package.md, main-portfolio metadata): the test count in `tech`, "one initiative never pays back",
    # "largely because the window ends before their benefits do", and the first-crossing wording of the payback rule
    rel = read("release-package.md")
    never = [r for r in RES["04_payback__never_pays_back"] if r["never_in_any_scenario"] == "true"]
    assert len(never) == 6
    if "One initiative never pays back in any scenario" in text:
        assert "true but ambiguous" in rel
    if "largely because the window ends before their benefits do" in text:
        assert sum(1 for r in RES["11_proposal_screen__waiting"] if r["reason"] == "NO_BENEFIT_ENTERS_THE_CASH_FLOW") == 4 and "contradicted" in rel
    if any("399 Python tests" in t for t in PROJECT["tech"]):
        assert "**stale**" in rel
    assert PROJECT["repo"].endswith("apps/changeworks") and PROJECT["date"] == "2026-10"


def test_no_credentials_or_secrets_in_the_artifact_documents_and_files():
    for d in DOCS12:
        text = read(d)
        assert "lab:lab" not in text, d
        assert not re.search(r"postgres(ql)?://[^<\s]*:[^<\s@]+@", text.replace("<user>:<password>@", "")), d
        assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S{12,}", text), d
    for p in list(ART.glob("*.json")) + list((ART / "bi").glob("*.csv")) + [ART / "CHECKSUMS.txt"] + list(SQL_DIR.glob("*.sql")):
        assert "postgresql://" not in p.read_text(), p.name
        assert "lab:lab" not in p.read_text(), p.name
    wbtext = " ".join(str(c.value) for ws in openpyxl.load_workbook(XLSX).worksheets for row in ws.iter_rows() for c in row if c.value)
    assert "postgresql://" not in wbtext and "password" not in wbtext.lower()
    assert "lab:lab@127.0.0.1" in (SQL_DIR / "prepare_snapshot.py").read_text()      # the CI workflow's throwaway login is the one documented default; it is in no document


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = read("workbook.md")
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "changeworks-analyst-workbook.xlsx" in doc and "openpyxl 3.1.5" in doc
    for sheet in ("Read me", "Controls", "Checks", "Portfolio", "Initiatives", "Cash flow", "Golden case", "Assumptions", "Benefits", "Costs", "Scenario inputs", "Scenarios", "Periods",
                  "Domain reference", "SQL results (pasted)"):
        assert f"`{sheet}`" in doc, sheet
    assert "Controls!B3" in doc and "Controls!B4" in doc and "fullCalcOnLoad" in doc and "How to read it without installing" in doc and "Checks!B2" in doc
    for v in ("1,243,149.05", "1,438,382.25", "195,233.20", "207,146.32", "5,974.80", "41.32", "1.6667", "1.9167", "-754.55"):
        assert v in doc, v
    assert (ROOT / "requirements-artifacts.txt").read_text().strip() == "openpyxl==3.1.5"


def test_every_document_cites_the_dataset_hash_and_the_code_revision_and_says_it_is_synthetic():
    assert len(DOCS12) == 12
    for n in DOCS12:
        text = read(n)
        assert DATASET_HASH in text and CODE_REVISION in text, n
        assert "synthetic" in text.lower(), n
        if n not in ("resume-bullets.md", "erd.md"):
            assert "without installing" in text or "needs nothing installed" in text, n                  # a brief read/use instruction (P09-ART-xx-R12)
    assert "Read the text lists below the diagram" in read("erd.md")


def test_the_ci_no_skip_gate_and_the_unrun_tools_are_disclosed():
    req, rel, tcs = read("requirements.md"), read("release-package.md"), read("technical-case-study.md")
    ci = ROOT.parents[1] / ".github" / "workflows" / "changeworks-ci.yml"
    if ci.exists():
        t = ci.read_text()
        assert 'skipped="' in t and "artifacts09_snapshot" in t and "artifacts09_golden" in t and "libreoffice-calc" in t and "fetch-depth: 0" in t
    for doc in (req, rel, tcs):
        assert "skip" in doc.lower() and "LibreOffice" in doc
    assert "not attached to a GitHub release" in rel and "Excel" in rel and "Power BI" in rel


def test_provenance_the_analysed_code_and_data_equal_revision_29948f9():
    """The numbers describe revision 29948f9: the domain, API, migrations, loaders, generator, reference SQL, published data, web source, fixtures, the other tests, the contracts
    and the README are unchanged since (tests/test_api_commands.py excepted: one order-dependent assertion was fixed after the package was written, see docs/uat-evidence.md)."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", CODE_SHA], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"revision {CODE_REVISION} is not in this checkout")
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", CODE_SHA, "--", "domain", "api", "data/sql/migrations", "data/seed.py", "data/migrate.py", "data/generate.py",
                        "data/sql/reference_metrics.sql", "web/public", "web/src", "web/e2e", "tests", ":(exclude)tests/test_artifacts.py", ":(exclude)tests/test_api_commands.py", "docs/contracts.md", "README.md"],   # test_api_commands.py: the C03 assertion was made independent of a server-generated id's sort position after 29948f9 (uat-evidence.md erratum); no figure moved
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "", r.stdout
    manifest = json.loads((ROOT / "web/public/data/manifest.json").read_text())
    assert manifest["dataset_hash"] == DATASET_HASH and manifest["dataset_version"] == "cw-20261026-20261026"


# ---- checksums -----------------------------------------------------------------------------------------------------------------------------

def test_checksums_file_matches_files_and_the_release_package_table():
    path = ART / "CHECKSUMS.txt"
    assert path.exists(), "CHECKSUMS.txt not written (artifacts/checksums.py)"
    listed = {}
    for line in path.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
        listed[rel] = digest
    chk = _load("cw_checksums", ART / "checksums.py")
    assert sorted(listed) == chk.files()                                  # every artifact and doc, nothing stale
    for must in ("artifacts/changeworks-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py", "artifacts/render_sql_analysis.py", "artifacts/checksums.py",
                 "requirements-artifacts.txt", "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
                 "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md", "docs/business-case.md", "docs/requirements.md", "docs/uat-evidence.md",
                 "docs/contracts.md", "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py", "data/sql/analysis/python_side.py", "data/sql/analysis/leaves.sql",
                 "artifacts/bi/fact_cash_flow.csv", "artifacts/bi/dim_period.csv", "artifacts/bi/measures_recomputed.csv"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("[01][0-9]_*.sql")) + sorted(SQL_DIR.glob("bi_*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    assert "docs/release-package.md" not in listed and "artifacts/CHECKSUMS.txt" not in listed
    rel_doc = read("release-package.md")
    for rel, digest in listed.items():
        assert f"| `{rel}` | `{digest}` |" in rel_doc, rel               # release-package.md carries the same table (it cannot list itself)
