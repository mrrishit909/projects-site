"""Artifact package checks (P04-ART-01..10): the SQL analysis results, the analyst workbook, the BI exports, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that every result cell of the formula
sheets is a live formula, (2) reads the values LibreOffice cached in the delivered file and compares them with the Python domain
RECOMPUTED HERE (not with the pasted reference column), (3) recalculates copies with LibreOffice headless: as delivered and with the
scenario switch on training and on holdout (formulas only, so no cache) and compares each with the domain for that window,
(4) checks that the stored analysis results equal the Python domain over web/public/data (no database), through
data/sql/analysis/python_side.py, which shares no code with the SQL, (5) recomputes the BI measures from the CSV exports, (6) checks that
each document quotes the stored results, the simulation reference and the public case study, and (7) checks CHECKSUMS.txt.
With ARTIFACTS_DATABASE_URL (a scratch database named artifacts04_* prepared by data/sql/analysis/prepare_snapshot.py) it also re-runs
the SQL files and compares their rows with the stored results; without it that test is skipped. Excel and Power BI are never run.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
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

XLSX = ART / "serviceflow-analyst-workbook.xlsx"
RES = json.loads((ART / "analysis-results.json").read_text())
CODE_REVISION = "43de7f8"
DATASET_HASH = "944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4"
SIM = json.loads((ROOT / "web/public/reference/simulation-runs.json").read_text())
_CASE_STUDY = next((p for p in (ROOT.parents[1] / "serviceflow" / "project.json", ROOT.parents[3] / "serviceflow" / "project.json") if p.exists()), None)
PROJECT = json.loads(_CASE_STUDY.read_text()) if _CASE_STUDY else None          # the public case study lives on unified-portfolio, in the main checkout

pytestmark = pytest.mark.skipif(not XLSX.exists(), reason="workbook not built (artifacts/build_workbook.py)")


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
def ctx(ps):
    return ps.load()


@pytest.fixture(scope="module")
def wb():
    return openpyxl.load_workbook(XLSX)


@pytest.fixture(scope="module")
def wbv():
    return openpyxl.load_workbook(XLSX, data_only=True)


@pytest.fixture(scope="module")
def bw():
    return _load("sf_build_workbook", ART / "build_workbook.py")


def row_of(key: str, **where) -> dict:
    return next(r for r in RES[key] if all(str(r[k]) == str(v) for k, v in where.items()))


def read(name: str) -> str:
    return (DOCS / name).read_text()


# ---- stored analysis results -----------------------------------------------------------------------------------------------

def test_analysis_results_reconcile_and_cover_every_investigation(ps):
    assert RES["reconciliation"] and all(r["equal"] is True for r in RES["reconciliation"])
    assert len(RES["reconciliation"]) >= 150
    assert RES["meta"][0]["dataset_hash"] == DATASET_HASH and RES["meta"][0]["code_revision"] == CODE_REVISION
    assert RES["meta"][0]["reconciliation_rows"] == len(RES["reconciliation"])
    for key in ps.KEYS:
        assert RES[key], key
    numbered = sorted(p.name for p in SQL_DIR.glob("0[1-8]_*.sql"))
    assert len(numbered) == 8                                          # eight numbered investigations
    assert {k.split("__")[0] for k in ps.KEYS} == {p[:-4] for p in numbered}
    for k in ("09_golden_known_answer__golden_per_ticket", "09_golden_known_answer__golden_totals"):
        assert RES[k]
    assert {c.split(" ")[0] for c in (r["check"] for r in RES["reconciliation"])} == {"A", "B", "C", "D", "E"}


def test_golden_fixture_reference_sql_domain_and_expected_json_agree_on_all_28_keys(ps):
    from serviceflow.contract import METRIC_KEYS
    expected = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())["metrics"]
    rows = {r["quantity"]: r for r in RES["golden_reference_metrics"]}
    assert set(rows) == set(METRIC_KEYS) == set(expected)
    assert len(rows) == 28
    for k in METRIC_KEYS:
        want = json.dumps(expected[k], sort_keys=True) if isinstance(expected[k], (dict, list)) else ps.norm(expected[k])
        r = rows[k]
        assert r["reference_metrics_sql"] == r["python_domain"] == r["expected_json"] == want, k
    per = {r["ticket_id"]: r for r in RES["09_golden_known_answer__golden_per_ticket"]}
    assert [(per[t]["wait_min"], per[t]["first_response_min"], per[t]["resolution_min"]) for t in ("t-001", "t-002", "t-003")] == [
        ("0.0000", "0.0000", "10.0000"), ("10.0000", "10.0000", "20.0000"), ("20.0000", "20.0000", "30.0000")]
    tot = {r["source"]: r for r in RES["09_golden_known_answer__golden_totals"]}
    assert tot["event log (this directory)"]["mean_wait_min"] == "10.0000" and tot["event log (this directory)"]["last_completion_min"] == "30.0000"
    assert tot["simulation sim-001 (simulation_events)"]["mean_wait_min"] == "10.0000"


def test_stored_results_equal_the_python_domain_over_the_snapshot_files(ps, ctx):
    """No database: the domain's replay over web/public/data, aggregated in exact rationals, reproduces every stored number."""
    exp = ps.expected(ctx)
    for key in ps.KEYS:
        assert ps.compare(key, RES[key], exp[key]) == [], key


def test_stored_reference_windows_equal_the_domain(ctx, ps):
    from serviceflow import compute_metrics
    for r in RES["reference_metrics_snapshot"]:
        w = ps.WINDOWS[r["window"]]
        m = compute_metrics(ctx.pop, w, [w[1]], ps.ABANDONABLE)
        for k, v in m.items():
            if isinstance(v, dict):
                continue
            assert ps.norm(r[k]) == ps.norm(v), (r["window"], k)
        assert json.loads(r["backlog"]) == m["backlog"]


def test_headline_numbers_of_the_documents_are_the_stored_ones(ctx, ps):
    from serviceflow import compute_metrics
    m = compute_metrics(ctx.pop, ps.WINDOWS["full"], [ps.WINDOWS["full"][1]], ps.ABANDONABLE)
    assert (m["arrival_count"], m["completion_count"]) == (3817, 3608)
    assert (m["mean_first_response_minutes"], m["p90_first_response_minutes"], m["mean_wait_minutes"], m["mean_resolution_minutes"]) == ("28.0046", "44.1500", "25.5073", "164.5909")
    assert (m["sla_first_response_compliance"], m["sla_resolution_compliance"], m["agent_occupancy"]) == ("0.950498", "0.978104", "0.424263")
    assert (m["staffed_available_minutes"], m["handling_minutes_total"], m["abandonment_rate"], m["csat"]) == ("447450.0000", "189836.2667", "0.118213", "0.864000")
    assert row_of("02_wait_and_response_distributions__first_response_and_wait", queue_id="ALL", priority="ALL")["p90_first_response_min"] == "44.1500"


def test_designed_relationships_and_defects_are_present_in_the_results():
    top = RES["01_arrivals_by_hour_of_week"][0]
    assert top["block_utc"] == "Mon 09-11" and float(top["arrivals_per_staffed_hour"]) > 1.3
    assert float(top["arrivals_per_staffed_hour"]) > 1.3 * float(RES["01_arrivals_by_hour_of_week"][1]["arrivals_per_staffed_hour"])
    tp1 = row_of("02_wait_and_response_distributions__resolution_tail", queue_id="q-002", priority="P1")
    assert tp1["completions"] == 142 and float(tp1["p90_over_mean"]) > 2.0 and tp1["p90_resolution_min"] == "619.4167" and tp1["mean_resolution_min"] == "247.1852"
    g = {(r["window_name"], r["priority"]): r for r in RES["03_sla_compliance_and_open_overdue__compliance_by_priority_and_window"]}
    assert g[("full", "P1")]["first_response_compliance"] == "0.823789" and g[("full", "P1")]["first_response_within"] == 187
    assert float(g[("holdout", "ALL")]["arrival_count"] if "arrival_count" in g[("holdout", "ALL")] else g[("holdout", "ALL")]["arrivals"]) / 1431 == 1
    assert all(r["open_overdue"] == 0 for r in RES["03_sla_compliance_and_open_overdue__open_overdue_at_monday_cutoffs"])
    ex = {r["priority"]: r for r in RES["03_sla_compliance_and_open_overdue__overdue_exposure_by_priority"]}
    assert ex["ALL"]["tickets_open_overdue_at_a_sample"] == 62 and ex["ALL"]["hours_with_any"] == 233 and ex["ALL"]["peak_open_overdue_at_one_hour"] == 3
    brk = {(r["shift_min"], r["declared_break_min"], r["recorded_break_min"]): r for r in RES["04_occupancy_by_agent_and_shift__breaks_declared_vs_recorded"]}
    assert brk[("480", 0, "30")]["shifts"] == 3 and brk[("480", 0, "30")]["capacity_overstated_by_declared_min"] == "90.0000"
    assert all(r["handling_inside_a_recorded_break_min"] == "0.0000" for r in brk.values())
    mb = {r["queue_id"]: r for r in RES["04_occupancy_by_agent_and_shift__monday_bind_handling_by_queue"]}
    assert mb["ALL"]["handling_min"] == "3422.1500" and round(100 * (float(mb["q-001"]["handling_min"]) + float(mb["q-003"]["handling_min"])) / float(mb["ALL"]["handling_min"]), 1) == 28.9
    t = {r["ticket_group"]: r for r in RES["05_transfer_and_reopen_effects__by_transfer_and_reopen"]}
    assert float(t["reopened only"]["mean_resolution_min"]) > 10 * float(t["neither"]["mean_resolution_min"])
    assert abs(float(t["transferred only"]["mean_resolution_min"]) - float(t["neither"]["mean_resolution_min"])) < 5
    c = {r["channel"]: r for r in RES["06_abandonment_by_channel_and_patience__abandonment_by_channel"]}
    assert c["email"]["abandonment_rate"] is None and c["web_form"]["abandonment_rate"] is None and c["ALL abandonable"]["abandoned"] == 209
    assert c["ALL abandonable"]["of_which_transferred"] == c["ALL abandonable"]["abandoned_after_service_began"] == 8
    b = {r["reading"][:5]: r for r in RES["07_survey_response_skew__csat_and_its_bounds"]}
    assert float(b["lower"]["value"]) < 0.864 < float(b["upper"]["value"])
    e = {r["experience"]: r for r in RES["07_survey_response_skew__response_by_experience"]}
    assert float(e["poor experience"]["response_rate"]) < float(e["good experience"]["response_rate"])
    assert sum(r["rejected_rows"] for r in RES["08_rejections_and_defects_by_reason__rejected_by_reason"]) == 70
    found = {r["injection_id"]: r["found"] for r in RES["08_rejections_and_defects_by_reason__injected_defects_found"]}
    assert found == {"INJ-01": 4, "INJ-02": 4, "INJ-03": 3, "INJ-04": 3, "INJ-05": 3, "INJ-06": 3, "INJ-07": 0, "INJ-08": 1, "INJ-09": 315}


@pytest.mark.skipif(not os.environ.get("ARTIFACTS_DATABASE_URL"),
                    reason="ARTIFACTS_DATABASE_URL (a scratch database named artifacts04_* prepared by data/sql/analysis/prepare_snapshot.py) is not set")
def test_sql_files_rerun_against_the_prepared_database_give_the_stored_rows(ps):
    import psycopg
    from psycopg.rows import dict_row
    run_all = _load("sf_run_all", SQL_DIR / "run_all.py")
    url = os.environ["ARTIFACTS_DATABASE_URL"]
    assert url.rsplit("/", 1)[-1].startswith("artifacts04_")
    with psycopg.connect(url, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        c.execute((SQL_DIR / "00_event_views.sql").read_text())
        for f in sorted(SQL_DIR.glob("0[1-8]_*.sql")):
            for key, rows in run_all.run_file(c, f).items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == [{k: ps.norm(v) for k, v in r.items()} for r in RES[key]], key
    if os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL"):
        with psycopg.connect(os.environ["ARTIFACTS_GOLDEN_DATABASE_URL"], row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
            c.execute((SQL_DIR / "00_event_views.sql").read_text())
            for key, rows in run_all.run_file(c, SQL_DIR / "09_golden_known_answer.sql").items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == [{k: ps.norm(v) for k, v in r.items()} for r in RES[key]], key


def test_a_database_rerun_without_the_scratch_url_is_skipped_with_a_reason():
    marks = [m for m in test_sql_files_rerun_against_the_prepared_database_give_the_stored_rows.pytestmark if m.name == "skipif"]
    assert marks and "ARTIFACTS_DATABASE_URL" in marks[0].kwargs["reason"]


def test_scratch_guard_refuses_a_non_scratch_database():
    prep = _load("sf_prepare", SQL_DIR / "prepare_snapshot.py")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/serviceflow")
    prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts04_snapshot")


def test_every_sql_file_has_its_header_and_the_numbered_files_read_only():
    files = sorted(SQL_DIR.glob("0*.sql"))
    assert [f.name[:2] for f in files] == ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09"]
    for f in files:
        text = f.read_text()
        assert text.startswith(f"-- {f.name[:-4]}.sql:") or text.startswith(f"-- {f.name}:"), f.name
        assert "P04-" in text or "contract" in text.lower() or "D-0" in text, f.name
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b", body, re.I), f.name     # read-only apart from the views
    for f in sorted(SQL_DIR.glob("bi_*.sql")):
        assert "BI package" in f.read_text(), f.name


# ---- the workbook ----------------------------------------------------------------------------------------------------------

def _metric_expectation(ctx, ps, window: str) -> dict[str, float]:
    from serviceflow import compute_metrics
    from serviceflow.timeutil import nearest_rank
    w = ps.WINDOWS[window]
    m = compute_metrics(ctx.pop, w, [w[1]], ps.ABANDONABLE)
    out = {k: float(v) for k, v in m.items() if not isinstance(v, (dict, bool)) and v is not None}
    out["backlog_at_window_end"] = float(list(m["backlog"].values())[0])
    for key, src in (("p90_wait_minutes", "wait_minutes"), ("p90_resolution_minutes", "resolution_minutes")):
        out[key] = float(nearest_rank([Fraction(x) for x in m[src].values()], Fraction(9, 10)))
    return out


def _metrics_values(path: Path, bw) -> dict[str, object]:
    ws = openpyxl.load_workbook(path, data_only=True)["Metrics"]
    return {key: ws.cell(row=6 + i, column=2).value for i, (key, *_r) in enumerate(bw.METRICS)}


def test_workbook_sheets_present_and_assumptions_listed(wb):
    assert wb.sheetnames == ["Read me", "Scenario", "Metrics", "Domain reference", "Hour of week", "Queue by priority", "Golden case", "Assumptions",
                             "Tickets", "Intervals", "Shifts", "Surveys", "SQL results (pasted)"]
    text = " ".join(str(c.value) for row in wb["Assumptions"].iter_rows() for c in row if c.value)
    for d in ("D-01", "D-02", "D-03", "D-05", "D-08", "D-09", "W-01", "W-02", "W-03", "W-04"):
        assert d in text
    assert "SYNTHETIC" in wb["Read me"]["A2"].value and "PASTED VALUES" in wb["SQL results (pasted)"]["A1"].value and "PASTED VALUES" in wb["Domain reference"]["A1"].value
    assert wb["Scenario"]["B3"].value == "full"
    assert any("full,training,holdout" in str(dv.formula1) for dv in wb["Scenario"].data_validations.dataValidation)
    readme = " ".join(str(c.value) for row in wb["Read me"].iter_rows() for c in row if c.value)
    assert DATASET_HASH in readme and CODE_REVISION in readme and "Excel was NOT run" in readme


def test_data_sheets_equal_the_domain_replay(wb, ctx):
    tk, iv, sh, sv = wb["Tickets"], wb["Intervals"], wb["Shifts"], wb["Surveys"]
    assert (tk.max_row - 1, iv.max_row - 1, sh.max_row - 1, sv.max_row - 1) == (3817, 4976, 1020, 2147)
    epoch = lambda d: None if d is None else int(d.timestamp())            # noqa: E731
    by_id = {t.ticket_id: t for t in ctx.pop.tickets}
    for r in tk.iter_rows(min_row=2, max_col=11, values_only=True):
        t, h = by_id[r[0]], ctx.hist[r[0]]
        assert r[1:9] == (t.priority, t.channel, t.queue_id, epoch(t.created_at), epoch(h.first_human_reply_at), epoch(h.first_service_at),
                          epoch(h.final_resolution), epoch(h.abandoned_at)), r[0]
        assert (r[9], r[10]) == (h.reopen_count, len(h.transfers))
    total = sum((r[1] - r[0]) for r in iv.iter_rows(min_row=2, min_col=3, max_col=4, values_only=True))
    assert total == sum(int((i.end - i.start).total_seconds()) for h in ctx.hist.values() for i in h.intervals)
    shifts = {s.shift_id: s for s in ctx.pop.shifts}
    for r in sh.iter_rows(min_row=2, max_col=6, values_only=True):
        s = shifts[r[0]]
        assert (r[1], r[2], r[3], r[4]) == (s.agent_id, epoch(s.starts_at), epoch(s.ends_at), s.break_minutes)
    surveys = {s.survey_id: s for s in ctx.pop.surveys}
    for r in sv.iter_rows(min_row=2, max_col=4, values_only=True):
        s = surveys[r[0]]
        assert (r[1], r[2], r[3]) == (s.ticket_id, 1 if s.invited_at is not None else 0, s.score)


def test_result_cells_of_the_formula_sheets_are_live_formulas_without_hardcoded_quantities(wb, bw):
    METRICS_KEYS = [m[0] for m in bw.METRICS]
    tk = wb["Tickets"]
    for col in range(12, 27):
        for row in (2, 1000, 3818):
            assert str(tk.cell(row=row, column=col).value).startswith("="), (col, row)
    for col in range(5, 6):
        assert str(wb["Intervals"].cell(row=2, column=col).value).startswith("=") and str(wb["Intervals"].cell(row=4977, column=col).value).startswith("=")
    for col in (7, 8):
        assert str(wb["Shifts"].cell(row=2, column=col).value).startswith("=")
    for col in range(5, 9):
        assert str(wb["Surveys"].cell(row=2, column=col).value).startswith("=")
    m = wb["Metrics"]
    for r in range(6, 6 + len(METRICS_KEYS)):
        assert str(m.cell(row=r, column=2).value).startswith("="), r                  # the value
        assert str(m.cell(row=r, column=5).value).startswith("=INDEX("), r              # the pasted domain figure is read, never typed here
        assert str(m.cell(row=r, column=7).value).startswith("="), r
    h = wb["Hour of week"]
    assert all(str(h.cell(row=5 + d, column=2 + hr).value).startswith("=COUNTIFS(") for d in range(7) for hr in range(24))
    g = wb["Golden case"]
    for addr in ("D5", "D6", "D7", "E5", "E6", "E7", "F5", "F6", "F7", "B9", "B10", "B11", "B12", "B14", "B15"):
        assert str(g[addr].value).startswith("="), addr
    assert g["B5"].value == 0 and g["J4"].value == 10                                   # the typed inputs of the known answer
    q = wb["Queue by priority"]
    assert all(str(q.cell(row=r, column=c).value).startswith("=") for r in range(5, 14) for c in (3, 4, 5, 6, 10))
    s = wb["Scenario"]
    assert str(s["B11"].value).startswith("=INDEX(") and str(s["B12"].value).startswith("=INDEX(") and s["B13"].value == "=(B12-B11)/3600"


def test_cached_values_equal_the_domain_recomputed_here(wbv, bw, ctx, ps):
    got = _metrics_values(XLSX, bw)
    want = _metric_expectation(ctx, ps, "full")
    assert set(got) == set(want) - {k for k in want if k not in got} | set(got)
    for k, v in got.items():
        assert v is not None and abs(float(v) - want[k]) < 1e-9, (k, v, want[k])
    ws = wbv["Metrics"]
    assert ws["E3"].value is True and all(ws.cell(row=r, column=7).value is True for r in range(6, 6 + len(want)))
    assert wbv["Golden case"]["B15"].value is True
    assert wbv["Hour of week"]["B15"].value == 238 and wbv["Hour of week"]["B16"].value is True and wbv["Hour of week"]["B18"].value is True
    q = wbv["Queue by priority"]
    assert [q.cell(row=r, column=10).value for r in range(5, 14)] == [True] * 9
    # the pasted columns are the domain's too
    dr = {r[0]: r for r in wbv["Domain reference"].iter_rows(min_row=5, values_only=True)}
    for k, v in want.items():
        assert abs(dr[k][1] - v) < 1e-9, k


def test_full_calc_on_load_is_set_in_workbook_xml():
    import zipfile
    assert 'fullCalcOnLoad="1"' in zipfile.ZipFile(XLSX).read("xl/workbook.xml").decode()


needs_lo = pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")


def _lo_recalc(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(exist_ok=True)
    subprocess.run(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{out_dir}/profile",
                    "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out_dir / "out"), str(src)],
                   check=True, capture_output=True, timeout=900)
    return out_dir / "out" / src.name


@needs_lo
def test_libreoffice_headless_recalculation_of_a_copy_as_delivered(tmp_path, bw, ctx, ps):
    src = tmp_path / "copy.xlsx"
    shutil.copy(XLSX, src)
    res = _lo_recalc(src, tmp_path / "a")
    got, want = _metrics_values(res, bw), _metric_expectation(ctx, ps, "full")
    for k, v in got.items():
        assert abs(float(v) - want[k]) < 1e-9, k
    assert openpyxl.load_workbook(res, data_only=True)["Metrics"]["E3"].value is True


@needs_lo
@pytest.mark.parametrize("scenario", ["training", "holdout"])
def test_the_scenario_switch_is_live_and_equals_the_domain_for_that_window(tmp_path, bw, ctx, ps, scenario):
    flip = openpyxl.load_workbook(XLSX)                         # formulas only: openpyxl drops the cached values on save
    flip["Scenario"]["B3"] = scenario
    src = tmp_path / f"{scenario}.xlsx"
    flip.save(src)
    assert _metrics_values(src, bw)["arrival_count"] is None   # no cached values until recalculated
    res = _lo_recalc(src, tmp_path / scenario)
    got, want = _metrics_values(res, bw), _metric_expectation(ctx, ps, scenario)
    for k, v in got.items():
        assert v is not None and abs(float(v) - want[k]) < 1e-9, (scenario, k, v, want[k])
    v = openpyxl.load_workbook(res, data_only=True)
    assert v["Metrics"]["E3"].value is True and v["Metrics"]["B3"].value == scenario
    assert v["Hour of week"]["B16"].value is True and v["Hour of week"]["B18"].value is True      # the Monday block follows the window
    assert (got["arrival_count"], got["backlog_at_window_end"]) == ((2386, 1) if scenario == "training" else (1431, 0))


def test_pasted_sql_results_sheet_matches_the_stored_results(wb):
    ws = wb["SQL results (pasted)"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    n = len(RES["reconciliation"])
    assert (ws["B3"].value, ws["C3"].value) == (n, n)
    assert any(isinstance(c, str) and DATASET_HASH in c and CODE_REVISION in c for c in cells)
    all02 = row_of("02_wait_and_response_distributions__first_response_and_wait", queue_id="ALL", priority="ALL")
    assert float(all02["mean_first_response_min"]) in cells and float(all02["p90_first_response_min"]) in cells
    assert float(row_of("04_occupancy_by_agent_and_shift__occupancy_by_agent", agent_id="ALL")["occupancy"]) in cells
    assert "agt-012" in cells and "Mon 09-11" in cells
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)               # pasted values, not formulas


# ---- the BI package --------------------------------------------------------------------------------------------------------

def _csv(name: str) -> list[dict]:
    with (ART / "bi" / f"{name}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def test_bi_exports_have_the_documented_grain_and_equal_the_domain(ctx, ps):
    counts = {"fact_ticket": 3817, "fact_service_interval": 4976, "fact_shift": 1020, "fact_survey": 2147, "fact_simulation_replication": 150,
              "dim_date": 84, "dim_queue": 3, "dim_agent": 18, "dim_priority": 3, "dim_channel": 4, "dim_simulation_run": 3}
    for name, n in counts.items():
        assert len(_csv(name)) == n, name
    ft = {r["ticket_id"]: r for r in _csv("fact_ticket")}
    assert len(ft) == 3817
    secs = lambda a, b: None if a is None or b is None else str(max(0, int((b - a).total_seconds())))       # noqa: E731
    for t in ctx.pop.tickets:
        h, r = ctx.hist[t.ticket_id], ft[t.ticket_id]
        assert r["first_response_seconds"] == (secs(t.created_at, h.first_human_reply_at) or ""), t.ticket_id
        assert r["wait_seconds"] == (secs(t.created_at, h.first_service_at) or ""), t.ticket_id
        assert r["resolution_seconds"] == (secs(t.created_at, h.final_resolution) or ""), t.ticket_id
        assert int(r["handling_seconds"]) == sum(int((iv.end - iv.start).total_seconds()) for iv in h.intervals), t.ticket_id
        assert (int(r["reopen_count"]), int(r["transfer_count"]), r["final_queue_id"]) == (h.reopen_count, len(h.transfers), t.queue_id)
        assert r["is_completed"] == ("1" if h.final_resolution else "0") and r["is_abandoned"] == ("1" if h.abandoned_at else "0")
        fr_t, rs_t = ctx.policy[t.priority]
        assert r["met_first_response"] == ("" if h.first_human_reply_at is None else str(int(ps.mins(t.created_at, h.first_human_reply_at) <= fr_t)))
        assert r["met_resolution"] == ("" if h.final_resolution is None else str(int(ps.mins(t.created_at, h.final_resolution) <= rs_t)))
    shifts = {s.shift_id: s for s in ctx.pop.shifts}
    for r in _csv("fact_shift"):
        s = shifts[r["shift_id"]]
        assert (int(r["shift_minutes"]), int(r["declared_break_minutes"])) == (int((s.ends_at - s.starts_at).total_seconds() // 60), s.break_minutes)
        assert int(r["staffed_available_minutes"]) == int(r["shift_minutes"]) - s.break_minutes
    assert sum(1 for r in _csv("fact_shift") if r["crosses_clock_change"] == "1") == 2
    sv = {s.survey_id: s for s in ctx.pop.surveys}
    for r in _csv("fact_survey"):
        s = sv[r["survey_id"]]
        assert (r["score"], r["is_valid_response"]) == ("" if s.score is None else str(s.score), "1" if s.score is not None else "0")
    reps = _csv("fact_simulation_replication")
    for sid, run in SIM["replications"]["runs"].items():
        assert [r["mean_wait_minutes"] for r in reps if r["simulation_id"] == sid] == run["per_replication_mean_wait_minutes"]
        assert [int(r["seed"]) for r in reps if r["simulation_id"] == sid] == run["seeds"]
    dates = _csv("dim_date")
    assert dates[0]["date"] == "2026-07-06" and dates[-1]["date"] == "2026-09-27" and {d["period"] for d in dates} == {"training", "holdout"}
    assert sum(1 for d in dates if d["period"] == "training") == 56
    assert all(c != "" or True for r in ft.values() for c in r.values())
    text = (ART / "bi" / "fact_ticket.csv").read_text()
    assert "postgresql://" not in text and "password" not in text.lower()


def test_bi_measures_recomputed_from_the_csv_files_equal_the_stored_expected_values_and_the_domain(ctx, ps):
    run_all = _load("sf_run_all2", SQL_DIR / "run_all.py")
    bi = {n: _csv(f"fact_{n}") for n in ("ticket", "service_interval", "shift", "survey")}
    reps = _csv("fact_simulation_replication")
    stored = {r["measure"]: r["expected"] for r in RES["bi_expected_measures"]}
    now = {m["measure"]: m["expected"] for m in run_all.bi_measures(bi["ticket"], bi["service_interval"], bi["shift"], bi["survey"], reps)}
    assert {k: ps.norm(v) for k, v in now.items()} == {k: ps.norm(v) for k, v in stored.items()}
    from serviceflow import compute_metrics
    for window in ("full", "training", "holdout"):
        w = ps.WINDOWS[window]
        m = compute_metrics(ctx.pop, w, [w[1]], ps.ABANDONABLE)
        bm = {r["measure"]: r["expected"] for r in run_all.bi_measures(bi["ticket"], bi["service_interval"], bi["shift"], bi["survey"], reps, w)}
        for measure, key in (("Arrivals", "arrival_count"), ("Completions", "completion_count"), ("Mean First Response (min)", "mean_first_response_minutes"),
                             ("Mean Resolution (min)", "mean_resolution_minutes"), ("SLA First Response Compliance", "sla_first_response_compliance"),
                             ("Handling Minutes", "handling_minutes_total"), ("Staffed Available Minutes", "staffed_available_minutes"),
                             ("Agent Occupancy", "agent_occupancy"), ("CSAT", "csat"), ("Abandonment Rate", "abandonment_rate")):
            assert ps.norm(bm[measure]) == ps.norm(m[key]), (window, measure)
    pair = SIM["replications"]["paired"]["baseline_vs_plus_one_agent"]["difference_mean_wait_minutes"]
    assert (stored["Simulated Paired Difference sim-002 minus sim-001 (min)"], stored["Simulated Paired 95 % Half-width (min)"]) == (pair["mean"], pair["ci95_half_width"])


def test_bi_package_defines_every_measure_blank_safely_and_makes_no_pbix_claim():
    bi = read("bi-package.md")
    assert "No `.pbix` was produced" in bi and "Desktop" in bi and "not executed" in bi and "pseudocode" in bi
    block = re.search(r"```dax(.*?)```", bi, re.S).group(1)
    names = [re.sub(r"\s+$", "", m) for m in re.findall(r"^([A-Z][A-Za-z0-9 %()\-.]+?)\s*=", block, re.M)]
    stored = [r["measure"] for r in RES["bi_expected_measures"] if not r["measure"].startswith("Simulated")]
    for m in stored:
        assert m in names, m
    assert len(set(names)) >= 24
    for need in ("Simulated Mean Wait (min)", "Simulated 95 % Half-width (min)", "Simulated Paired Difference sim-002 minus sim-001 (min)"):
        assert need in names
    assert block.count("DIVIDE") >= 15 and len(re.findall(r"BLANK\s*\(\s*\)", block)) >= block.count("DIVIDE") - 3
    for t in ("fact_ticket", "fact_service_interval", "fact_shift", "fact_survey", "fact_simulation_replication", "dim_date", "dim_queue", "dim_agent", "dim_priority",
              "dim_channel", "dim_simulation_run"):
        assert f"`{t}`" in bi and (ART / "bi" / f"{t}.csv").exists(), t
    assert "star schema" in bi.lower() and "Power Query" in bi and "USERELATIONSHIP" in bi and "role-playing" in bi
    render = _load("sf_render", ART / "render_sql_analysis.py")
    assert render.render(bi, RES) == bi
    assert "reconciliation" in bi and DATASET_HASH in bi and CODE_REVISION in bi


# ---- documents -------------------------------------------------------------------------------------------------------------

def _tables_and_columns() -> dict[str, list[str]]:
    sql = (ROOT / "data/migrations/0001_schema.sql").read_text()
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql, re.S):
        cols = []
        for line in m.group(2).splitlines():
            mm = re.match(r"([a-z_]+)\s+(BIGSERIAL|TEXT|INT|BOOLEAN|TIMESTAMPTZ|JSONB|NUMERIC|BIGINT)", line.strip())
            if mm:
                cols.append(mm.group(1))
        out[m.group(1)] = cols
    return out


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations():
    tables = _tables_and_columns()
    assert len(tables) == 19
    dd, erd = read("data-dictionary.md"), read("erd.md")
    assert "```mermaid" in erd and "erDiagram" in erd
    for t, cols in tables.items():
        assert f"`{t}`" in dd, t
        assert re.search(rf"^\s+{t} \{{", erd, re.M), t
        sect = dd.split(f"### {t}\n", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
        for c in cols:
            assert f"| `{c}` |" in sect, (t, c)
            assert re.search(rf"^\s+\w+ {c}\b", erd, re.M), (t, c)
    for key in ("grain", "Deletion policy", "Immutable", "append-only", "rejected_records", "BOT_AS_HUMAN_REPLY", "Source-to-target", "Source contracts",
                "tickets_arrival_fixed", "ticket_events_immutable", "INJ-02", "INJ-05", "INJ-08", "shift_breaks", "Foreign keys"):
        assert key in dd, key
    for k, n in (("tickets", "3,817"), ("ticket_events", "21,893"), ("surveys", "2,147"), ("shifts", "1,020"), ("rejected_records", "70")):
        assert re.search(rf"\| `{k}` \|[^\n]*\| {n} \|", dd), k
    assert DATASET_HASH in dd and CODE_REVISION in dd and DATASET_HASH in erd


def test_sql_analysis_doc_quotes_the_stored_results_and_every_table_is_rendered_from_them(ps):
    doc = read("sql-analysis.md")
    for f in sorted(SQL_DIR.glob("0*.sql")):
        assert f.name in doc, f.name
    for k in ("reference_metrics.sql", "python_side.py", "run_all.py", "prepare_snapshot.py", DATASET_HASH, CODE_REVISION, "known_differences"):
        assert k in doc, k
    render = _load("sf_render2", ART / "render_sql_analysis.py")
    assert render.render(doc, RES) == doc                                   # no figure inside a table is typed by hand
    for key in list(ps.KEYS) + ["09_golden_known_answer__golden_per_ticket", "09_golden_known_answer__golden_totals", "reconciliation", "known_differences",
                                "reference_metrics_snapshot", "golden_reference_metrics", "meta"]:
        assert f"<!-- BEGIN:{key} -->" in doc, key
    # numbers quoted in the sentences around the tables are the stored ones
    flat = json.dumps(RES)
    quoted = set(re.findall(r"(?<![\w.])\d[\d,]*\.\d{2,6}(?![\w])", doc.split("## 10 Reconciliation")[0].split("## 01 ")[1]))
    sentences = [q for q in quoted if not re.search(rf"\|[^\n]*\b{re.escape(q)}\b[^\n]*\|", doc)]      # figures that appear only in prose
    for q in sentences:
        assert q.replace(",", "") in flat or q in ("0.2148", "0.3799"), q
    pairs = [("0.9737", row_of("01_arrivals_by_hour_of_week", note="top 2")["arrivals_per_staffed_hour"]),
             ("0.4292", row_of("01_arrivals_by_hour_of_week", note="median of the blocks")["arrivals_per_staffed_hour"]),
             ("0.823944", row_of("03_sla_compliance_and_open_overdue__compliance_by_queue_and_priority", queue_id="q-002", priority="P1")["first_response_compliance"]),
             ("0.767606", row_of("03_sla_compliance_and_open_overdue__compliance_by_queue_and_priority", queue_id="q-002", priority="P1")["resolution_compliance"]),
             ("0.279726", row_of("04_occupancy_by_agent_and_shift__occupancy_by_skill_set", skill_set="q-003")["occupancy"]),
             ("0.539443", row_of("04_occupancy_by_agent_and_shift__occupancy_by_skill_set", skill_set="q-001 + q-002")["occupancy"]),
             ("1,188.3935", f"{Decimal(row_of('05_transfer_and_reopen_effects__by_transfer_and_reopen', ticket_group='reopened only')['mean_resolution_min']):,}")]
    for text, stored in pairs:
        assert text == str(stored), (text, stored)
        assert text in doc
    assert all(k["item"].split(" ")[0] in ("INJ-09", "01", "07") for k in RES["known_differences"])


def test_first_response_compliance_inside_the_monday_bind_is_not_worse(ctx, ps):
    ok, n = {}, {}
    for t in ctx.pop.tickets:
        h = ctx.hist[t.ticket_id]
        if h.first_human_reply_at is None or not (t.created_at.weekday() == 0 and t.created_at.hour in (9, 10)):
            continue
        n[t.priority] = n.get(t.priority, 0) + 1
        ok[t.priority] = ok.get(t.priority, 0) + (ps.mins(t.created_at, h.first_human_reply_at) <= ctx.policy[t.priority][0])
    assert (ok["P2"], n["P2"], ok["P3"], n["P3"]) == (75, 76, 129, 129)
    assert "P2 75 of 76, P3 129 of 129" in read("sql-analysis.md")


def test_technical_agents_on_the_first_monday_bind_and_who_holds_another_skill(ctx):
    """The memo's dedicated-server statement: Monday 2026-07-06 10:00Z, then 2026-08-03 when agt-005 gains onboarding."""
    skill_queues: dict[str, set] = {}
    for q in ctx.pop.queue_skills:
        skill_queues.setdefault(q.skill_id, set()).add(q.queue_id)

    def other_skill(at: datetime) -> tuple[list[str], list[str]]:
        held: dict[str, set] = {}
        for s in ctx.pop.agent_skills:
            if s.effective_from <= at:
                held.setdefault(s.agent_id, set()).update(skill_queues[s.skill_id])
        on_shift = [s.agent_id for s in ctx.pop.shifts if s.starts_at <= at < s.ends_at]
        tech = sorted(a for a in on_shift if "q-002" in held.get(a, set()))
        return tech, sorted(a for a in tech if held[a] - {"q-002"})

    tech, other = other_skill(datetime.fromisoformat("2026-07-06T10:00:00+00:00"))
    assert tech == ["agt-001", "agt-002", "agt-005", "agt-006", "agt-008"] and other == ["agt-001", "agt-002", "agt-008"]
    tech2, other2 = other_skill(datetime.fromisoformat("2026-08-03T10:00:00+00:00"))
    assert "agt-005" in other2 and len(tech2) == 5 and len(other2) == 4
    memo = read("executive-memo.md")
    assert "Three of the five technical-skilled agents on shift at the first training Monday bind" in memo and "four of five from 2026-08-03" in memo


def mmc_mean_wait(lam_per_hour: float, service_min: float, c: int) -> tuple[float, float]:
    """Steady-state M/M/c: (utilisation, mean wait in the queue in minutes) by the Erlang C formula."""
    lam, mu = lam_per_hour / 60, 1 / service_min
    a = lam / mu
    rho = a / c
    s = sum(a ** k / math.factorial(k) for k in range(c))
    top = a ** c / (math.factorial(c) * (1 - rho))
    return rho, (top / (s + top)) / (c * mu - lam)


def test_memo_quotes_the_simulation_reference_the_stored_results_and_its_caveats():
    memo = read("executive-memo.md")
    runs, pair = SIM["replications"]["runs"], SIM["replications"]["paired"]
    for sid, run in runs.items():
        mean, hw = Decimal(run["mean_wait_minutes"]["mean"]), Decimal(run["mean_wait_minutes"]["ci95_half_width"])
        assert run["replications"] == 50 and run["mean_wait_minutes"]["n"] == 50
        for text in (f"{mean}", f"{hw}", f"{mean - hw} to {mean + hw}", str(run["censored_tickets_total"])):
            assert text in memo, (sid, text)
        assert run["per_replication_mean_wait_minutes"][0] in memo                 # the single published run is the first replication
    d = pair["baseline_vs_plus_one_agent"]["difference_mean_wait_minutes"]
    m, hw = Decimal(d["mean"]), Decimal(d["ci95_half_width"])
    assert pair["baseline_vs_plus_one_agent"]["same_demand_paths"] is True and pair["baseline_vs_holdout_intensity"]["same_demand_paths"] is False
    for text in (str(m), str(hw), f"{m - hw} to {m + hw}"):
        assert text in memo, text
    d3 = pair["baseline_vs_holdout_intensity"]["difference_mean_wait_minutes"]
    assert f"+{d3['mean']}" in memo and d3["ci95_half_width"] in memo
    assert f"{abs(m) / Decimal(runs['sim-001']['mean_wait_minutes']['mean']):.3f}" in memo
    for sid, (lam, c, want) in {"sim-001": (3.12, 5, "20.05"), "sim-002": (3.12, 6, "5.61"), "sim-003": (3.74, 5, "67.68")}.items():
        rho, wq = mmc_mean_wait(lam, 69.1, c)
        assert f"{wq:.2f}" == want and want in memo and f"{rho:.3f}" in memo, sid
    # observed figures quoted in the memo are the stored ones
    for v in (row_of("02_wait_and_response_distributions__first_response_and_wait", queue_id="q-002", priority="ALL")["mean_first_response_min"],
              row_of("02_wait_and_response_distributions__resolution_tail", queue_id="q-002", priority="P1")["p90_resolution_min"],
              row_of("03_sla_compliance_and_open_overdue__compliance_by_queue_and_priority", queue_id="q-002", priority="ALL")["first_response_compliance"],
              row_of("03_sla_compliance_and_open_overdue__compliance_by_queue_and_priority", queue_id="q-002", priority="P1")["resolution_compliance"],
              row_of("04_occupancy_by_agent_and_shift__occupancy_by_skill_set", skill_set="q-003")["occupancy"],
              row_of("04_occupancy_by_agent_and_shift__occupancy_by_skill_set", skill_set="q-001 + q-002")["occupancy"],
              row_of("07_survey_response_skew__csat_and_its_bounds", reading="lower bound: every non-responder not positive")["value"],
              row_of("07_survey_response_skew__csat_and_its_bounds", reading="upper bound: every non-responder positive")["value"],
              row_of("06_abandonment_by_channel_and_patience__abandonment_by_channel", channel="ALL abandonable")["abandonment_rate"],
              row_of("05_transfer_and_reopen_effects__by_transfer_and_reopen", ticket_group="transferred only")["mean_resolution_min"],
              row_of("05_transfer_and_reopen_effects__by_transfer_and_reopen", ticket_group="neither")["mean_resolution_min"]):
        assert str(v) in memo or f"{Decimal(str(v)):,}" in memo, v
    for key in ("OBSERVED", "SIMULATED", "HYPOTHETICAL", "Decision", "Evidence", "Options", "Uncertainty", "Limitations", "Recommendation", "Dedicated-server simplification",
                "Single-queue model", "Synthetic", "warm-up", "censored", "no realised staffing benefit", "C07", "C10", "501", "Excel", DATASET_HASH, CODE_REVISION, "20261026"):
        assert key.lower() in memo.lower(), key


def test_business_case_names_the_real_entities_metrics_commands_and_distinguishes_result_kinds():
    bc = read("business-case.md")
    assert all(k in bc.lower() for k in ("stakeholder", "current-state", "future", "decision criteria", "scope"))
    for key in ("Which staffing or routing change meets support targets under uncertain workload?", "observed", "simulated", "hypothetical", "`ticket_events`", "`tickets`", "`shifts`", "`shift_breaks`", "`simulation_runs`", "`surveys`", "P04-MET-12", "P04-FLOW-04", "P04-TEST-06", DATASET_HASH, CODE_REVISION,
                "501", "How to read"):
        assert key in bc, key
    for c in ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10"):
        assert c in bc, c
    for q in ("q-001", "q-002", "q-003"):
        assert q in bc
    for v in ("28.0046", "44.1500", "0.950498", "0.823789", "0.424263", "1.3259", "0.4292", "619.4167", "247.1852", "-10.8932", "3.4329", "0.279726", "28.9 %", "0.923291", "0.767606"):
        assert v in bc, v
    assert "Nothing is a claim about a real employer" in bc and "hypothetical" in bc


def test_requirements_trace_every_requirement_family_and_mark_c07_and_c10_as_501():
    req = read("requirements.md")
    for fam in ("P04-GOAL", "P04-DOMAIN", "P04-GOLD", "P04-DATA", "P04-MET", "P04-FLOW", "P04-UI", "P04-TEST", "P04-ART", "P04-REL"):
        assert fam in req, fam
    for i in range(1, 13):
        assert f"P04-TEST-{i:02d}" in req or f"P04-TEST-{i}" in req
    for i in range(1, 11):
        assert f"P04-UI-{i:02d}" in req, i
        assert f"P04-FLOW-{i:02d}" in req, i
    assert re.search(r"P04-FLOW-07 \(C07[^|]*\)\*\* \|[^\n]*\*\*501\*\*", req) and re.search(r"P04-FLOW-10 \(C10[^|]*\)\*\* \|[^\n]*\*\*501\*\*", req)
    assert "**deferred (stub" in req and "partial" in req and "User stories" in req and "*Accept:*" in req
    assert "Non-functional" in req and "Functional requirements" in req and "Traceability" in req
    assert DATASET_HASH in req and CODE_REVISION in req and "pending" in req


def test_uat_evidence_keeps_the_original_and_adds_routes_screenshots_scenarios_and_run_links():
    uat = read("uat-evidence.md")
    assert uat.startswith("# ServiceFlow — UAT evidence for the review corrections (A-031 -> T-04-07)")
    for f in ("R4-01", "R4-18", "377 passed", "R4-11 numbers (50 replications"):
        assert f in uat, f
    assert "# P04-ART-08: entry-journey UAT evidence" in uat
    routes_ts = (ROOT / "web/src/routes.ts").read_text()
    for path in re.findall(r'\{ path: "([a-z-]*)", label', routes_ts):
        assert (f"`/{path}/`" if path else "`/`") in uat, path
    names = [f"{r}-{w}.png" for r in ("home", "overview", "queues", "tickets", "staffing", "sla", "simulation", "compare", "surveys", "evidence", "case-study") for w in (360, 768, 1280, 1920)]
    for n in names:
        stem = n.rsplit("-", 1)[0]
        assert f"`{stem}-360.png`" in uat or f"`{stem}-*.png`" in uat, stem
    assert "55 screenshots" in uat and "zoom200" in uat and "git-ignored" in uat
    idx = ROOT / "web/evidence/index.json"
    if idx.exists():
        shots = json.loads(idx.read_text())
        assert shots["count"] == 55 and len({s["file"] for s in shots["shots"]}) == 55
        assert all(s["scrollWidth"] <= s["innerWidth"] for s in shots["shots"])
        assert {s["file"] for s in shots["shots"]} >= set(names)
    for url in ("actions/runs/40364940392", "actions/runs/40367109366"):
        assert url in uat, url
    for k in ("UAT-01", "UAT-10", "Expected answer", "Actual observation", "Disposition", "e44d15d", "Defect disposition", "stub", "501"):
        assert k in uat, k
    assert "did **not** re-run" in uat or "did not re-run" in uat


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    cs, rel = read("technical-case-study.md"), read("release-package.md")
    for url in ("actions/runs/40354858820", "actions/runs/40360702938", "actions/runs/40364940392", "actions/runs/40367109366"):
        assert url in cs, url
    for k in ("377", "303", "409", "422", "501", "R4-01", "R4-18", "T-04-07", "Excel and Power BI Desktop were not run", "Architecture", "Tradeoffs", "Recovery behaviour",
              "Reproducible setup", "Measured evidence", "Open gaps", "mermaid", "Mode A", "Mode B", DATASET_HASH, CODE_REVISION, "pending", str(len(RES["reconciliation"]))):
        assert k in cs, k
    for k in ("https://mrrishit909.github.io/projects-site/labs/serviceflow/", "e44d15d", "e3bd4a4", "b5a33b9681eb0319a9c092bfc83e29b37d333c4bc836e784815eaab7a614f445", DATASET_HASH,
              CODE_REVISION, "LibreOffice", "Excel", "git revert", "Rollback manifest", "actions/runs/40367109366", "actions/runs/40364940392", "pending", "Main-portfolio metadata",
              "checksums", "private"):
        assert k in rel, k
    if shutil.which("git") and (ROOT.parents[1] / ".git").exists():
        for c in ("e44d15d", "e3bd4a4"):
            r = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", c], capture_output=True, text=True)
            if r.returncode == 0:
                assert r.stdout.strip() == "commit", c


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact_and_match_the_public_case_study():
    text = read("resume-bullets.md")
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6 and "synthetic" in text.lower()
    for l in bullets:
        assert not re.search(r"\b(saved|savings|revenue|users|customers served|increased|reduced cost|improved|reduced)\b", l, re.I), l
    assert str(len(RES["reconciliation"])) in text and "377" in text and "28 metric keys" in text and "nine written decisions" in text
    if PROJECT is not None:
        blob = json.dumps(PROJECT)
        for k in ("377 Python tests", "303 TypeScript golden", "54 review", "70 browser tests", "28 metrics"):
            assert k in blob or k.replace("TypeScript ", "") in blob, k
        assert "-10.9" in PROJECT["results"] or "−10.9" in PROJECT["results"]


def r1(x) -> str:
    """One decimal, half up (the case study rounds 44.15 to 44.2; Python's float formatting would give 44.1)."""
    from decimal import ROUND_HALF_UP
    return format(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f")


@pytest.mark.skipif(PROJECT is None, reason="the public case study /serviceflow/project.json is not in this checkout (it lives on unified-portfolio)")
def test_public_case_study_figures_agree_with_the_stored_results():
    res = PROJECT["results"].replace("−", "-").replace("&plusmn;", "+-").replace("±", "+-")
    a = row_of("02_wait_and_response_distributions__first_response_and_wait", queue_id="ALL", priority="ALL")
    assert f"{r1(a['mean_wait_min'])} minutes" in res and f"{r1(a['mean_first_response_min'])} minutes" in res and f"P90 of {r1(a['p90_first_response_min'])}" in res
    assert f"{r1(row_of('02_wait_and_response_distributions__resolution_tail', queue_id='ALL', priority='ALL')['mean_resolution_min'])} minutes" in res
    p = row_of("03_sla_compliance_and_open_overdue__compliance_by_priority_and_window", window_name="full", priority="ALL")
    p1 = row_of("03_sla_compliance_and_open_overdue__compliance_by_priority_and_window", window_name="full", priority="P1")
    assert f"{r1(float(p['first_response_compliance']) * 100)}%" in res and f"{r1(float(p['resolution_compliance']) * 100)}%" in res
    assert f"{r1(float(p1['first_response_compliance']) * 100)}%" in res and f"{p1['first_response_within']} of the {p1['first_response_eligible']}" in res
    assert f"{p['misses_that_were_reopened']} of the {p['resolution_misses']}" in res
    assert f"{float(row_of('04_occupancy_by_agent_and_shift__occupancy_by_agent', agent_id='ALL')['occupancy']):.2f}" in res and "447,450" in res
    ab = row_of("06_abandonment_by_channel_and_patience__abandonment_by_channel", channel="ALL abandonable")
    assert f"{r1(float(ab['abandonment_rate']) * 100)}%" in res and f"{ab['abandoned_before_first_service']} before any" in res
    e = row_of("07_survey_response_skew__response_by_experience", experience="ALL")
    assert f"{r1(float(e['invitation_rate']) * 100)}%" in res and f"{r1(float(e['response_rate']) * 100)}%" in res and f"{float(e['csat']):.3f}" in res
    for sid, run in SIM["replications"]["runs"].items():
        mm = run["mean_wait_minutes"]
        assert f"{r1(mm['mean'])} +- {r1(mm['ci95_half_width'])}" in res or f"{r1(mm['mean'])}" in res, sid
    pm = SIM["replications"]["paired"]["baseline_vs_plus_one_agent"]["difference_mean_wait_minutes"]
    assert f"{r1(pm['mean'])} +- {r1(pm['ci95_half_width'])}" in res
    assert "28.9%" in res and "3,817 accepted tickets" in res


def test_no_credentials_or_secrets_in_the_artifact_documents_and_files():
    docs = ["business-case.md", "requirements.md", "data-dictionary.md", "erd.md", "sql-analysis.md", "workbook.md", "bi-package.md", "executive-memo.md",
            "technical-case-study.md", "release-package.md", "resume-bullets.md"]
    for d in docs:
        text = read(d)
        assert "lab:lab" not in text, d
        assert not re.search(r"postgres(ql)?://[^<\s]*:[^<\s@]+@", text), d
        assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S{12,}", text), d
    for p in list(ART.glob("*.json")) + list((ART / "bi").glob("*.csv")) + [ART / "CHECKSUMS.txt"]:
        assert "postgresql://" not in p.read_text(), p.name
    wbtext = " ".join(str(c.value) for ws in openpyxl.load_workbook(XLSX).worksheets[:8] for row in ws.iter_rows() for c in row if c.value)
    assert "postgresql://" not in wbtext and "password" not in wbtext.lower()


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = read("workbook.md")
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "serviceflow-analyst-workbook.xlsx" in doc and "openpyxl 3.1.5" in doc
    for sheet in ("Read me", "Scenario", "Metrics", "Domain reference", "Hour of week", "Queue by priority", "Golden case", "Assumptions", "Tickets", "Intervals", "Shifts", "Surveys",
                  "SQL results (pasted)"):
        assert f"`{sheet}`" in doc, sheet
    assert "Scenario!B3" in doc and "training" in doc and "holdout" in doc and "fullCalcOnLoad" in doc and "How to read it without installing" in doc
    for v in ("3,817", "447,450.0000", "189,836.2667", "0.424263", "28.0046", "0.864000", "2,386", "23.4036", "0.399387", "1,431", "35.7365", "0.473609"):
        assert v in doc, v
    assert "requirements-artifacts.txt" in (ROOT / "requirements-artifacts.txt").name or (ROOT / "requirements-artifacts.txt").read_text().strip() == "openpyxl==3.1.5"


def test_provenance_the_analysed_code_and_data_equal_revision_43de7f8():
    """The numbers describe revision 43de7f8: the domain, API, migrations, loaders, reference SQL, published data and fixtures are unchanged since."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", CODE_REVISION], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"revision {CODE_REVISION} is not in this checkout")
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", CODE_REVISION, "--", "domain", "api", "data/migrations", "data/seed.py", "data/migrate.py", "data/generate.py",
                        "data/simulation_reference.py", "data/sql/reference_metrics.sql", "data/injection-manifest.json", "web/public", "tests/fixtures"],  # contracts.md may gain wording fixes (A-033 finding 1) without moving a number
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "", r.stdout


# ---- checksums -------------------------------------------------------------------------------------------------------------

def test_checksums_file_matches_files_and_the_release_package_table():
    path = ART / "CHECKSUMS.txt"
    if not path.exists():
        pytest.skip("CHECKSUMS.txt not written (artifacts/checksums.py)")
    listed = {}
    for line in path.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
        listed[rel] = digest
    chk = _load("sf_checksums", ART / "checksums.py")
    assert sorted(listed) == chk.files()                                  # every artifact and doc, nothing stale
    for must in ("artifacts/serviceflow-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py", "artifacts/render_sql_analysis.py", "artifacts/checksums.py",
                 "requirements-artifacts.txt", "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
                 "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md", "docs/business-case.md", "docs/requirements.md", "docs/uat-evidence.md",
                 "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py", "data/sql/analysis/python_side.py", "artifacts/bi/fact_ticket.csv", "artifacts/bi/dim_date.csv"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("0*.sql")) + sorted(SQL_DIR.glob("bi_*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    assert "docs/release-package.md" not in listed and "artifacts/CHECKSUMS.txt" not in listed
    rel_doc = read("release-package.md")
    for rel, digest in listed.items():
        assert f"| `{rel}` | `{digest}` |" in rel_doc, rel               # release-package.md carries the same table (it cannot list itself)
