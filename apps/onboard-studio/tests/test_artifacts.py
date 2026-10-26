"""Artifact package checks (P02-ART-03..10): the analyst workbook, the analysis results, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that Calendar, Overlap and Figures are live
formulas with no hard-coded durations, (2) re-derives the formula chain in Python (exact rationals) from the Inputs sheet and compares it with
tests/fixtures/golden/expected.json AND with the domain's run_pipeline, (3) reads the cached values LibreOffice wrote, (4) recalculates copies
with LibreOffice headless, once as delivered and once with the pause switch flipped, (5) checks that the pasted snapshot summary and the documents
agree with artifacts/analysis-results.json, which is itself compared with the Python domain over web/public/data (no database needed),
and (6) checks CHECKSUMS.txt. With ARTIFACTS_DATABASE_URL (a scratch database prepared by data/sql/analysis/prepare_snapshot.py) it also
re-runs the SQL files and compares their rows with the stored results. Excel is never run.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

XLSX = ROOT / "artifacts" / "onboard-studio-analyst-workbook.xlsx"
GOLD = json.loads((ROOT / "tests/fixtures/golden/inputs.json").read_text())
EXPECTED = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())
RES = json.loads((ROOT / "artifacts/analysis-results.json").read_text())
SQL_DIR = ROOT / "data" / "sql" / "analysis"
DOCS = ROOT / "docs"
D = Decimal

pytestmark = pytest.mark.skipif(not XLSX.exists(), reason="workbook not built (artifacts/build_workbook.py)")

ENTITIES = ["organizations", "workflow_versions", "step_definitions", "dependencies", "sla_rules", "calendar_intervals",
            "cases", "step_instances", "assignments", "document_versions", "approvals", "waiting_intervals", "case_events"]


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def wb():
    return openpyxl.load_workbook(XLSX)


@pytest.fixture(scope="module")
def wbv():
    return openpyxl.load_workbook(XLSX, data_only=True)


def inputs_from_sheet(ws) -> dict[str, list[dict]]:
    """Read the typed blocks of the Inputs sheet back into entity -> rows (title row, header row, data, blank)."""
    out: dict[str, list[dict]] = {}
    rows = list(ws.iter_rows(values_only=True))
    i = 0
    while i < len(rows):
        a = rows[i][0]
        if isinstance(a, str) and a in GOLD and a in ENTITIES:
            cols = [c for c in rows[i + 1] if c is not None]
            out[a] = []
            i += 2
            while i < len(rows) and rows[i][0] is not None:
                out[a].append(dict(zip(cols, rows[i][:len(cols)])))
                i += 1
        i += 1
    return out


# ---- structure ----------------------------------------------------------------------------------------------------

def test_sheets_present(wb):
    assert wb.sheetnames == ["Inputs", "Calendar", "Overlap", "Figures", "Assumptions", "Snapshot summary"]
    text = " ".join(str(c.value) for row in wb["Assumptions"].iter_rows() for c in row if c.value)
    for d in ("D-01", "D-02", "D-03", "D-04", "D-05", "D-06"):
        assert d in text
    assert "PASTED VALUES" in wb["Snapshot summary"]["A1"].value
    assert "SYNTHETIC" in wb["Inputs"]["A2"].value


def test_inputs_sheet_equals_golden_fixture(wb):
    got = inputs_from_sheet(wb["Inputs"])
    assert set(got) == set(ENTITIES)
    for ent, rows in got.items():
        assert len(rows) == len(GOLD[ent]), ent
        for a, b in zip(rows, GOLD[ent]):
            for k, v in b.items():
                if isinstance(v, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", v):
                    assert a[k] == ts(v), (ent, k)
                elif isinstance(v, list):
                    assert a[k] == ", ".join(v), (ent, k)
                elif isinstance(v, bool):
                    assert str(a[k]).lower() == str(v).lower(), (ent, k, a[k])
                elif isinstance(v, (int, float)):
                    assert D(str(a[k])) == D(str(v)), (ent, k)
                else:
                    assert a[k] == v, (ent, k)


def test_calendar_overlap_and_figures_are_live_formulas_without_hardcoded_durations(wb):
    cal, ov, fig = wb["Calendar"], wb["Overlap"], wb["Figures"]
    n = len(GOLD["calendar_intervals"])
    assert n == 10
    for r in range(5, 5 + n):
        for c in (1, 2, 3, 4, 6):                       # kind (col 5) is the one typed column, documented in D-06
            v = cal.cell(r, c).value
            assert isinstance(v, str) and v.startswith("=") and "Inputs!" in v or c == 6 and v.startswith("=ROUND("), (r, c, v)
    for r in range(11, 11 + n):
        for c in range(1, 7):
            v = ov.cell(r, c).value
            assert isinstance(v, str) and v.startswith("="), (r, c, v)
        assert "MIN(" in ov.cell(r, 5).value and "MAX(" in ov.cell(r, 5).value and "MIN(" in ov.cell(r, 6).value
    tot = 11 + n
    assert ov.cell(tot, 5).value == f"=ROUND(SUM(E11:E{tot - 1}),4)" and ov.cell(tot, 6).value == f"=ROUND(SUM(F11:F{tot - 1}),4)"
    for c in ("B5", "B6", "B7", "E5", "E6", "E7", "E8"):
        assert isinstance(ov[c].value, str) and ov[c].value.startswith("=") and ("Inputs!" in ov[c].value or "B6" in ov[c].value or "B7" in ov[c].value)
    # Figures rows 8..12 (durations), 13..16 (SLA): columns B, C, D are formulas; E, F are the typed expectations; B3, C7, D7 the switches
    for r in list(range(8, 17)):
        for col in "BCD":
            v = fig[f"{col}{r}"].value
            assert isinstance(v, str) and v.startswith("="), (col, r, v)
    assert fig["B3"].value in (0, 1) and fig["C7"].value == 1 and fig["D7"].value == 0 and fig["B7"].value == "=$B$3"
    assert fig["B4"].value.startswith("=IF(ISNUMBER(SEARCH(Inputs!")
    assert "Overlap!" in fig["B9"].value and "Overlap!" in fig["B11"].value and "Inputs!" in fig["B8"].value
    # no computed result is typed anywhere a formula is expected: the number 66, 65 or 2 never appears as a literal formula
    for col in "BCD":
        for r in (8, 9, 10, 11, 12):
            assert not re.fullmatch(r"=?\d+(\.\d+)?", str(fig[f"{col}{r}"].value))


# ---- the chain, recomputed in Python ------------------------------------------------------------------------------

def overlap_h(lo: datetime, hi: datetime, intervals: list[tuple[datetime, datetime]]) -> Fraction:
    total = Fraction(0)
    for s, e in intervals:
        a, b = max(lo, s), min(hi, e)
        if b > a:
            total += Fraction((b - a).total_seconds()).limit_denominator(1) / 3600
    return total


def evaluate(inp: dict[str, list[dict]], eligible: bool) -> dict[str, Fraction | str]:
    """The chain of the Overlap and Figures sheets in exact rationals, from the Inputs sheet rows only."""
    case, wait, sla = inp["cases"][0], inp["waiting_intervals"][0], inp["sla_rules"][0]
    working = [(c["starts_at"], c["ends_at"]) for c in inp["calendar_intervals"]]
    opened, done = case["opened_at"], case["completed_at"]
    calendar = Fraction((done - opened).total_seconds()).limit_denominator(1) / 3600
    business = overlap_h(opened, done, working)
    lo, hi = max(wait["starts_at"], opened), min(wait["ends_at"], done)
    paused = Fraction((hi - lo).total_seconds()).limit_denominator(1) / 3600 if eligible else Fraction(0)
    pbo = overlap_h(lo, hi, working) if eligible else Fraction(0)
    active = max(Fraction(0), business - pbo)
    return {"calendar_cycle_time_hours": calendar, "business_cycle_time_hours": business, "paused_time_hours": paused,
            "paused_business_overlap_hours": pbo, "active_elapsed_hours": active,
            "sla": "met" if active * 60 <= D(str(sla["business_minutes"])) else "missed"}


@pytest.mark.parametrize("state,eligible", [("pause_eligible", True), ("pause_not_eligible", False)])
def test_formula_chain_intent_in_python_matches_golden_and_domain(wb, state, eligible):
    got = evaluate(inputs_from_sheet(wb["Inputs"]), eligible)
    exp = EXPECTED["states"][state]["metrics"]
    for k in ("calendar_cycle_time_hours", "business_cycle_time_hours", "paused_time_hours",
              "paused_business_overlap_hours", "active_elapsed_hours"):
        assert got[k] == Fraction(D(exp[k])), (state, k)
    assert got["sla"] == "met"
    from onboard_studio import run_pipeline
    dom = run_pipeline(GOLD, state=state).metrics
    for k in ("calendar_cycle_time_hours", "business_cycle_time_hours", "paused_time_hours", "active_elapsed_hours"):
        assert dom[k] == exp[k]
    if state == "pause_eligible":
        assert [str(got[k]) for k in ("calendar_cycle_time_hours", "business_cycle_time_hours", "paused_time_hours",
                "paused_business_overlap_hours", "active_elapsed_hours")] == ["66", "2", "65", "1", "1"]


def _figures(path: Path, sheet: str = "Figures") -> dict[str, tuple]:
    ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    return {ws.cell(r, 1).value: tuple(ws.cell(r, c).value for c in (2, 3, 4)) for r in range(8, 17)}


def _assert_figures(vals: dict[str, tuple], selected_eligible: bool):
    a, b = (1, 2) if selected_eligible else (2, 2)
    want = {"Calendar cycle time": (66, 66, 66), "Business cycle time": (2, 2, 2),
            "Paused time (calendar)": (65 if selected_eligible else 0, 65, 0),
            "Paused business overlap": (1 if selected_eligible else 0, 1, 0),
            "Active elapsed time": (1 if selected_eligible else 2, 1, 2)}
    for k, w in want.items():
        assert vals[k] == pytest.approx(w), k
    assert vals["SLA business minutes (sla_rules)"] == (480, 480, 480)
    assert vals["SLA met (active minutes <= SLA minutes)"] == ("met", "met", "met")
    assert vals["SLA attainment (met / completed eligible, 1 case)"] == pytest.approx((1, 1, 1))


def test_cached_values_in_the_delivered_file(wbv):
    """The delivered file was recalculated by LibreOffice, so it carries cached values."""
    fig, ov = wbv["Figures"], wbv["Overlap"]
    assert ov["E21"].value == pytest.approx(2.0) and ov["F21"].value == pytest.approx(1.0)
    assert ov["E22"].value == 2 and ov["F22"].value == 2                       # two working intervals touched each
    _assert_figures(_figures(XLSX), selected_eligible=fig["B3"].value == 1)
    assert fig["B18"].value is True                                             # every A and B check passed
    for r in list(range(8, 13)) + [16]:
        assert fig[f"G{r}"].value is True and fig[f"H{r}"].value is True
    assert wbv["Calendar"]["F15"].value == pytest.approx(80.0)                  # ten 8-hour working intervals


def test_full_calc_on_load_is_set_in_workbook_xml():
    import zipfile
    xml = zipfile.ZipFile(XLSX).read("xl/workbook.xml").decode()
    assert 'fullCalcOnLoad="1"' in xml


def _lo_recalc(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(exist_ok=True)
    subprocess.run(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{out_dir}/profile",
                    "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out_dir / "out"), str(src)],
                   check=True, capture_output=True, timeout=240)
    return out_dir / "out" / src.name


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_libreoffice_headless_recalculation_of_a_copy(tmp_path):
    src = tmp_path / "copy.xlsx"
    shutil.copy(XLSX, src)
    res = _lo_recalc(src, tmp_path / "a")
    _assert_figures(_figures(res), selected_eligible=True)
    ws = openpyxl.load_workbook(res, data_only=True)
    assert ws["Overlap"]["E21"].value == pytest.approx(2.0) and ws["Overlap"]["F21"].value == pytest.approx(1.0)
    assert ws["Figures"]["B18"].value is True


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_pause_switch_is_live_flipping_it_recalculates_active_hours(tmp_path):
    flip = openpyxl.load_workbook(XLSX)                 # formulas only: openpyxl drops the cached values on save
    flip["Figures"]["B3"] = 0
    src = tmp_path / "flipped.xlsx"
    flip.save(src)
    assert _figures(src)["Active elapsed time"] == (None, None, None)          # no cached values until recalculated
    res = _lo_recalc(src, tmp_path / "b")
    _assert_figures(_figures(res), selected_eligible=False)
    assert openpyxl.load_workbook(res, data_only=True)["Figures"]["B12"].value == pytest.approx(2.0)


# ---- the pasted snapshot summary and the stored analysis results --------------------------------------------------

def test_analysis_results_reconcile_and_cover_every_query():
    assert RES["reconciliation"] and all(r["equal"] is True for r in RES["reconciliation"])
    assert len(RES["reconciliation"]) >= 35
    for q in ("01_cycle_time_by_opening_month", "02_version_comparison_comparable_window", "03_sla_by_segment_region",
              "04_step_waiting_by_step_assignee", "05_rework_first_pass_by_segment", "06_paused_time_by_reason_region",
              "07_backlog_month_ends", "08_flags_and_rejections_by_reason", "09_golden_case_business_hours"):
        assert RES[q], q
        assert (SQL_DIR / f"{q}.sql").exists()
    for row in RES["golden_three_sources"]:
        vals = {row["analysis_sql_09"], row["python_domain"], row["expected_json"]}
        if not row["reference_metrics_sql"].startswith("n/a"):
            vals.add(row["reference_metrics_sql"])
        assert len(vals) == 1, row
    biz = next(r for r in RES["golden_three_sources"] if r["quantity"] == "BUSINESS hours")
    assert (biz["analysis_sql_09"], biz["reference_metrics_sql"], biz["python_domain"]) == ("2.0000", "2.0000", "2.0000")


def test_pasted_snapshot_summary_matches_analysis_results(wb):
    ws = wb["Snapshot summary"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    total = next(r for r in RES["01_cycle_time_by_opening_month"] if r["period"] == "TOTAL")
    for k in ("calendar_h", "business_h", "active_h"):
        assert float(total[k]) in cells, k
    ver = {(r["window"][:7], r["version"]): r for r in RES["02_version_comparison_comparable_window"]}
    for r in ver.values():
        assert float(r["active_h"]) in cells and float(r["sla_attainment"]) in cells
    assert any("03_sla_by_segment_region.sql" == c for c in cells) and any("08_flags_and_rejections_by_reason.sql" == c for c in cells)
    assert any(isinstance(c, str) and "3c20d296bcf178065e9178cae04f763994b4d7197026af2c021ab55b4cc2bc6a" in c for c in cells)
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)        # pasted values, not formulas


@pytest.fixture(scope="module")
def domain_run():
    spec = importlib.util.spec_from_file_location("os_prepare_snapshot", SQL_DIR / "prepare_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from onboard_studio.pipeline import run_pipeline
    cutoffs = [r["cutoff"].replace("T00:00Z", "T00:00:00Z") for r in RES["07_backlog_month_ends"]]
    return run_pipeline(mod.snapshot_inputs(), cutoffs=cutoffs)


def test_stored_results_equal_the_python_domain_over_the_snapshot_files(domain_run):
    """No database: the domain over web/public/data reproduces the numbers the SQL printed."""
    from onboard_studio.metrics import group_metrics
    m = domain_run.metrics
    total = next(r for r in RES["01_cycle_time_by_opening_month"] if r["period"] == "TOTAL")
    assert (total["calendar_h"], total["business_h"], total["active_h"], total["completed_cases"]) == (
        m["calendar_cycle_time_hours"], m["business_cycle_time_hours"], m["active_elapsed_hours"], m["completed_eligible_cases"])
    g = group_metrics(domain_run.population, "workflow_version")
    for r in RES["02_version_comparison_comparable_window"]:
        if r["window"].startswith("all"):
            assert (r["completed_cases"], r["active_h"], r["sla_attainment"], r["rework_rate"], r["first_pass_rate"]) == (
                g[r["version"]]["completed_eligible_cases"], g[r["version"]]["active_elapsed_hours"],
                g[r["version"]]["sla_attainment"], g[r["version"]]["rework_rate"], g[r["version"]]["first_pass_approval"])
    allcell = next(r for r in RES["03_sla_by_segment_region"] if r["segment"] == "ALL" and r["region"] == "ALL")
    assert (allcell["sla_attainment"], allcell["completed_cases"], allcell["open_cases_not_in_rate"]) == (
        m["sla_attainment"], m["completed_eligible_cases"], 21)
    gr = group_metrics(domain_run.population, "region")
    for r in RES["06_paused_time_by_reason_region"]:
        if r["lens"] == "region" and r["region"] != "ALL":
            assert r["paused_h_per_case"] == gr[r["region"]]["paused_time_hours"]
    bl = m["open_backlog_at_cutoff"]
    series = RES["07_backlog_month_ends"]
    for r in series:
        assert bl[r["cutoff"].replace("T00:00Z", "T00:00:00Z")] == r["open_at_end"]
    for prev, cur in zip(series, series[1:]):                                   # the roll-forward identity of query 07
        assert cur["open_at_end"] == prev["open_at_end"] + cur["opened"] - cur["completed"]
    rej = {r["reason"]: r for r in RES["08_flags_and_rejections_by_reason"]}
    assert sum(r["total_rows"] for r in RES["08_flags_and_rejections_by_reason"] if r["lens"] == "rejection") == len(domain_run.rejected) == 269
    assert rej["PAUSE_OUTSIDE_WORKING_INTERVAL"]["total_rows"] == len(domain_run.flags) == 3
    # the rev-004 bottleneck is a reviewer effect: the reviewer lens separates it, the assignee lens does not
    r04 = {(r["lens"], r["who"]): r for r in RES["04_step_waiting_by_step_assignee"]}
    assert D(r04[("reviewer", "rev-004")]["wait_bh"]) > 3 * D(r04[("reviewer", "rev-005")]["wait_bh"])
    assert max(D(r["wait_bh"]) for k, r in r04.items() if k[0] == "assignee") < D("1.5") * min(D(r["wait_bh"]) for k, r in r04.items() if k[0] == "assignee")


@pytest.mark.skipif(not os.environ.get("ARTIFACTS_DATABASE_URL"), reason="ARTIFACTS_DATABASE_URL (prepared scratch database) not set")
def test_sql_files_rerun_against_the_prepared_database_give_the_stored_rows():
    import psycopg
    from psycopg.rows import dict_row

    def norm(rows):
        return [{k: ("" if v is None else format(v, "f") if isinstance(v, Decimal) else str(v)) for k, v in r.items()} for r in rows]

    with psycopg.connect(os.environ["ARTIFACTS_DATABASE_URL"], row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        c.execute((SQL_DIR / "00_case_facts.sql").read_text())
        for f in sorted(SQL_DIR.glob("0[1-8]_*.sql")):
            assert norm(c.execute(f.read_text()).fetchall()) == norm(RES[f.stem]), f.name


def test_every_sql_file_names_its_requirement_and_has_one_statement_after_00():
    for f in sorted(SQL_DIR.glob("0*.sql")):
        text = f.read_text()
        assert text.startswith(f"-- {f.name[:2]}:"), f.name
        assert "P02-" in text or "contract" in text.lower(), f.name
        if not f.name.startswith("00"):
            body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
            assert body.count(";") == 1, f.name


# ---- documents ----------------------------------------------------------------------------------------------------

def _tables_and_columns() -> dict[str, list[str]]:
    sql = (ROOT / "data/migrations/0001_schema.sql").read_text()
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql, re.S):
        cols = []
        for line in m.group(2).splitlines():
            line = line.strip()
            mm = re.match(r"([a-z_]+)\s+(TEXT|INT|BOOLEAN|TIMESTAMPTZ|JSONB|NUMERIC|BIGINT)", line)
            if mm:
                cols.append(mm.group(1))
        out[m.group(1)] = cols
    return out


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations():
    tables = _tables_and_columns()
    assert len(tables) == 21
    dd, erd = (DOCS / "data-dictionary.md").read_text(), (DOCS / "erd.md").read_text()
    for t, cols in tables.items():
        assert f"`{t}`" in dd, t
        assert re.search(rf"^\s+{t} \{{", erd, re.M), t
        assert "```mermaid" in erd
        for c in cols:
            assert f"`{c}`" in dd, (t, c)
            assert re.search(rf"^\s+\w+ {c}\b", erd, re.M), (t, c)
    for key in ("D-01", "D-06", "append-only", "immutable", "rejected_records", "quarantined_records", "inputs.json"):
        assert key in dd


def test_sql_analysis_doc_quotes_the_stored_results():
    doc = (DOCS / "sql-analysis.md").read_text()
    for q in ("01_cycle_time_by_opening_month", "02_version_comparison_comparable_window", "03_sla_by_segment_region",
              "04_step_waiting_by_step_assignee", "05_rework_first_pass_by_segment", "06_paused_time_by_reason_region",
              "07_backlog_month_ends", "08_flags_and_rejections_by_reason", "09_golden_case_business_hours", "reference_metrics.sql"):
        assert q in doc, q
    assert "Business hours of the golden case: 2.0000 from the analysis SQL, 2.0000 from `reference_metrics.sql`, 2.0000 from the Python domain" in doc
    # every row of every result is in the document (the tables are rendered from the JSON, so any drift is caught here)
    for q in ("01_cycle_time_by_opening_month", "03_sla_by_segment_region", "07_backlog_month_ends", "08_flags_and_rejections_by_reason"):
        for row in RES[q]:
            line = "| " + " | ".join("" if v is None else str(v) for v in row.values()) + " |"
            assert line in doc, (q, line)


def test_memo_quotes_numbers_from_the_results_and_states_its_caveats():
    memo = (DOCS / "executive-memo.md").read_text()
    ov = {r["version"]: r for r in RES["02_version_comparison_comparable_window"] if r["window"].startswith("overlap")}
    for v, key in (("wfv-001", "active_h"), ("wfv-002", "active_h"), ("wfv-001", "sla_attainment"), ("wfv-002", "sla_attainment"),
                   ("wfv-001", "handoffs_per_case"), ("wfv-002", "handoffs_per_case"), ("wfv-002", "paused_business_h")):
        assert str(ov[v][key]) in memo, (v, key)
    for key in ("2025-10-01", "02_version_comparison_comparable_window", "04_step_waiting_by_step_assignee", "rev-004",
                "synthetic", "Recommendation", "Uncertainty", "Limitations", "Options"):
        assert key in memo, key
    assert "not real savings" in memo.lower() or "no real savings" in memo.lower()


def test_bi_package_has_twelve_dax_measures_with_blank_safe_division_and_no_pbix_claim():
    bi = (DOCS / "bi-package.md").read_text()
    assert "No `.pbix` was produced" in bi and "star schema" in bi.lower()
    block = re.search(r"```dax(.*?)```", bi, re.S).group(1)
    measures = re.findall(r"^([A-Z][A-Za-z0-9 ]+?)\s*=", block, re.M)
    assert len(set(measures)) >= 12
    for name in ("Calendar Cycle Hours", "Business Cycle Hours", "Active Elapsed Hours", "SLA Attainment", "Rework Rate",
                 "First Pass Rate", "Open Backlog", "Handoffs per Case", "Step Waiting Hours", "Paused Hours",
                 "Document Completeness", "Completed Cases"):
        assert name in measures, name
    assert block.count("DIVIDE") >= 8 and len(re.findall(r"BLANK\s*\(\s*\)", block)) >= block.count("DIVIDE")   # every DIVIDE has the BLANK alternate result
    for t in ("fact_case", "fact_step_instance", "dim_organization", "dim_workflow_version", "dim_step", "dim_date", "dim_assignee"):
        assert t in bi, t


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = (DOCS / "workbook.md").read_text()
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "onboard-studio-analyst-workbook.xlsx" in doc


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact():
    text = (DOCS / "resume-bullets.md").read_text()
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6
    assert "synthetic" in text.lower()
    for l in bullets:
        assert not re.search(r"\b(saved|savings|revenue|users|customers served|increased|reduced cost)\b", l, re.I), l


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    cs = (DOCS / "technical-case-study.md").read_text()
    rel = (DOCS / "release-package.md").read_text()
    for url in ("actions/runs/40322386220", "actions/runs/40326858638", "actions/runs/40328738179"):
        assert url in cs, url
    for k in ("279", "150", "409", "422", "501", "half-up", "Q-01", "Q-03"):
        assert k in cs, k
    for k in ("https://mrrishit909.github.io/projects-site/labs/onboard-studio/", "a614136", "f03b26f",
              "8b7bfab0e61562eff771364e355aa19fc5879cbcf2a1e7227d998aae1d28f47e", "LibreOffice", "Excel"):
        assert k in rel, k


# ---- checksums ----------------------------------------------------------------------------------------------------

def test_checksums_file_matches_files_and_the_release_package_table():
    path = ROOT / "artifacts" / "CHECKSUMS.txt"
    if not path.exists():
        pytest.skip("CHECKSUMS.txt not written (artifacts/checksums.py)")
    listed = {}
    for line in path.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
        listed[rel] = digest
    for must in ("artifacts/onboard-studio-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py",
                 "requirements-artifacts.txt", "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md",
                 "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md", "docs/executive-memo.md",
                 "docs/technical-case-study.md", "docs/resume-bullets.md", "data/sql/analysis/00_case_facts.sql",
                 "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("0*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    rel_doc = (DOCS / "release-package.md").read_text()
    for rel, digest in listed.items():
        assert digest in rel_doc, rel                      # release-package.md carries the same table (it cannot list itself)
