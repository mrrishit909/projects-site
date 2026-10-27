"""Artifact package checks (P05-ART-01..10): the SQL analysis results, the analyst workbook, the BI exports, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that every result cell of the formula
sheets is a live formula, (2) reads the values LibreOffice cached in the delivered file and compares them with the Python domain
RECOMPUTED HERE (not with the pasted reference column), including the total of every one of the 2,800 invoices, (3) recalculates copies
with LibreOffice headless: as delivered and with the cutoff switch on june and on march (formulas only, so no cache) and compares each with
the domain for that cutoff, (4) checks that the stored analysis results equal the Python domain over web/public/data (no database), through
data/sql/analysis/python_side.py, which shares no code with the SQL, (5) recomputes the BI measures from the CSV exports, (6) checks that
each document quotes the stored results and the public case study, and (7) checks CHECKSUMS.txt and the release-package table.
With ARTIFACTS_DATABASE_URL (a scratch database named artifacts05_* prepared by data/sql/analysis/prepare_snapshot.py) it also re-runs the
SQL files and compares their rows with the stored results; without it that test is skipped. Excel and Power BI are never run.
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
from decimal import Decimal
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

XLSX = ART / "invoicebridge-analyst-workbook.xlsx"
RES = json.loads((ART / "analysis-results.json").read_text()) if (ART / "analysis-results.json").exists() else {}
CODE_REVISION = "2dcc460"
DATASET_HASH = "1f001a43a7031d4260f5abb3b9f7a83f6e1b48397e85cf8b04e0b4d9e052162e"
CURRENCIES = ("USD", "EUR", "GBP")
_CASE_STUDY = next((p for p in (ROOT.parents[1] / "invoicebridge" / "project.json", ROOT.parents[3] / "invoicebridge" / "project.json") if p.exists()), None)
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
    return _load("ib_build_workbook", ART / "build_workbook.py")


@pytest.fixture(scope="module")
def ra():
    return _load("ib_run_all", SQL_DIR / "run_all.py")


@pytest.fixture(scope="module")
def domain_ref(bw, ctx):
    return bw.domain_reference(ctx)


def row_of(key: str, **where) -> dict:
    return next(r for r in RES[key] if all(str(r[k]) == str(v) for k, v in where.items()))


def read(name: str) -> str:
    return (DOCS / name).read_text()


def n(x) -> str:
    """A stored number as the documents print it: thousands separators on the integer part."""
    s = str(x)
    whole, _, frac = s.partition(".")
    return f"{int(whole):,}" + (f".{frac}" if frac else "")


def sha_of(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


# ---- stored analysis results -----------------------------------------------------------------------------------------------

def test_analysis_results_reconcile_and_cover_every_investigation(ps):
    assert RES["reconciliation"] and all(r["equal"] is True for r in RES["reconciliation"])
    assert len(RES["reconciliation"]) >= 250
    assert RES["meta"][0]["dataset_hash"] == DATASET_HASH and RES["meta"][0]["code_revision"] == CODE_REVISION
    assert RES["meta"][0]["reconciliation_rows"] == len(RES["reconciliation"]) == RES["meta"][0]["reconciliation_equal"]
    for key in ps.KEYS:
        assert RES[key], key
    numbered = sorted(p.name for p in SQL_DIR.glob("0[1-8]_*.sql"))
    assert len(numbered) == 8                                          # eight numbered investigations
    assert {k.split("__")[0] for k in ps.KEYS} == {p[:-4] for p in numbered}
    for k in ("09_golden_known_answer__golden_per_invoice", "09_golden_known_answer__golden_identity_groups", "09_golden_known_answer__golden_quantities"):
        assert RES[k]
    assert {c.split(" ")[0] for c in (r["check"] for r in RES["reconciliation"])} == {"A", "B", "C", "D", "E"}
    assert RES["meta"][0]["result_sets"] == len(ps.KEYS) + 3


def test_golden_fixture_reference_sql_domain_and_expected_json_agree_on_all_eleven_keys():
    from invoicebridge import run_pipeline
    from invoicebridge.contract import METRIC_KEYS
    expected = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())["metrics"]
    inputs = json.loads((ROOT / "tests/fixtures/golden/inputs.json").read_text())
    assert run_pipeline(inputs).metrics == expected
    rows = {r["check"].split(" ")[3].rstrip(":"): r for r in RES["reconciliation"] if r["check"].startswith("A golden metric ")}
    assert set(rows) == set(METRIC_KEYS) == set(expected) and len(rows) == 11
    for k in METRIC_KEYS:
        r = rows[k]
        assert r["analysis_sql"] == r["second_source"] == r["third_source"] == sha_of(expected[k]), k       # the SQL reference's row, expected.json and the domain
    for inv in ("inv-001", "inv-002", "inv-003"):
        assert any(r["check"].startswith(f"A golden {inv}:") and r["equal"] for r in RES["reconciliation"])


def test_stored_results_equal_the_python_domain_over_the_snapshot_files(ps, ctx):
    py = ps.compute(ctx)
    for key in ps.KEYS:
        assert RES[key] == ps.normalised(py[key]), key


def test_stored_reference_figures_equal_the_domain(ctx):
    """The B rows of the reconciliation carry the reference SQL's value; recompute the domain's here and compare."""
    from invoicebridge import compute_metrics
    from invoicebridge.timeutil import parse_ts
    dm = compute_metrics(ctx.pop, parse_ts("2026-10-01T02:00:00Z"), [parse_ts(c) for c in ("2026-03-31T23:59:59Z", "2026-06-30T23:59:59Z", "2026-10-01T02:00:00Z")])
    rows = {r["check"]: r for r in RES["reconciliation"]}
    assert rows["B matched.invoice_count"]["analysis_sql"] == str(dm["matched"]["invoice_count"]) == "2413"
    for cur in CURRENCIES:
        assert rows[f"B matched.by_currency.{cur}.total"]["second_source"] == dm["matched"]["by_currency"][cur]["total"]
        assert rows[f"B payable.by_currency.{cur}.approved_payable"]["second_source"] == dm["payable"]["by_currency"][cur]["approved_payable"]
        assert rows[f"B export.by_currency.{cur}.difference"]["second_source"] == dm["export"]["by_currency"][cur]["difference"] == "0.00"
    assert rows["B exceptions.open_count"]["third_source"] == str(dm["exceptions"]["open_count"]) == "232"
    assert rows["B rates.straight_through_rate (not blocked at the cutoff)"]["third_source"] == dm["rates"]["straight_through_rate"] == "0.912287"
    assert dm["rates"]["straight_through_never_excepted_rate"] == "0.772401"
    assert rows["B processing.approved_count"]["third_source"] == "2299"


def test_headline_numbers_of_the_documents_are_the_stored_ones():
    reasons = {r["reason"]: r for r in RES["01_match_outcomes_by_vendor_and_reason__reason_open_vs_ever"]}
    assert (reasons["ALL"]["open_at_cutoff"], reasons["ALL"]["ever_raised"], reasons["ALL"]["ever_resolved"]) == ("232", "660", "428")
    bycur = {r["currency"]: r for r in RES["01_match_outcomes_by_vendor_and_reason__by_currency"]}
    pay = {r["currency"]: r for r in RES["07_credits_and_payable_by_currency__payable_by_currency"]}
    rates = {r["currency"]: r for r in RES["01_match_outcomes_by_vendor_and_reason__rates_by_currency"]}
    apt = {r["currency"]: r for r in RES["04_approvals_under_policy_versions__approval_time_by_currency"]}
    memo, case, sqla, wbd = read("executive-memo.md"), read("business-case.md"), read("sql-analysis.md"), read("workbook.md")
    for cur in CURRENCIES:
        for doc in (memo, case, sqla):
            for v in (bycur[cur]["matched_total"], pay[cur]["approved_total"], pay[cur]["approved_payable"]):
                assert n(v) in doc, (cur, v)
        for doc in (memo, sqla):
            assert n(pay[cur]["credit_total"]) in doc, cur
        for v in (rates[cur]["straight_through_rate"], rates[cur]["never_excepted_rate"]):
            assert v in memo and v in sqla, (cur, v)
        assert n(apt[cur]["mean_minutes_to_approval"]) in memo and n(apt[cur]["mean_minutes_to_approval"]) in wbd
    for doc in (memo, case, sqla):
        for v in ("2,413", "2,299", "2,645", "232", "660", "428", "0.912287", "0.772401", "163", "538", "524", "0.302974", "0.973978"):
            assert v in doc, v
    assert "5,466.7066" in memo and "5,466.7066" in sqla and "5,466.7066" in wbd
    assert "0.351515" in memo and "0.351515" in sqla and "35.2 %" in case
    grp = {r["vendor_group"]: r for r in RES["01_match_outcomes_by_vendor_and_reason__vendor_group_open_vs_ever"]}
    assert (grp["ven-02x"]["invoices_in_book"], grp["ven-02x"]["quantity_blocked_open"], grp["ven-02x"]["quantity_blocked_ever"]) == ("538", "163", "524")
    assert (grp["ven-007"]["price_variance_open"], grp["other vendors"]["price_variance_open"]) == ("30", "2")
    hist = {(r["vendor_group"], r["reason"]): r for r in RES["01_match_outcomes_by_vendor_and_reason__history_by_vendor_group"]}
    assert hist[("ven-007", "PRICE_VARIANCE")]["ever_raised_rows"] == "53" and hist[("ven-007", "PRICE_VARIANCE")]["open_at_cutoff"] == "30"
    assert sum(int(r["ever_raised_rows"]) for (g, k), r in hist.items() if k == "PRICE_VARIANCE") == 57
    assert "53 of the 57" in memo and "30 of the 32" in memo
    back = {r["cutoff"]: r for r in RES["05_exception_backlog_and_assignment_history__backlog_at_cutoffs"]}
    assert [(r["open_from_history"], r["open_from_facts"], r["unowned_from_history"]) for r in back.values()] == [("128", "129", "17"), ("201", "201", "29"), ("232", "232", "29")]
    over = {r["currency"]: r for r in RES["04_approvals_under_policy_versions__matched_not_approved_over_limit"]}
    assert sum(int(r["matched_not_approved"]) for r in over.values()) == 114 and sum(int(r["above_the_limit"]) for r in over.values()) == 12
    assert "114" in memo and "12" in memo and "28" in memo and "28" in read("sql-analysis.md")
    ex = {(r["reason_code"], r["currency"]): r for r in RES["06_export_batches_and_reconciliation__exclusions_by_reason_and_currency"]}
    for cur in CURRENCIES:
        assert n(ex[("EXCEPTION_OPEN", cur)]["invoice_total"]) in memo, cur


def test_designed_relationships_and_defects_are_present_in_the_results():
    grp = {r["vendor_group"]: r for r in RES["01_match_outcomes_by_vendor_and_reason__vendor_group_open_vs_ever"]}
    rate02x = Decimal(grp["ven-02x"]["quantity_blocked_open_rate"])
    elsewhere = (int(grp["ven-007"]["quantity_blocked_open"]) + int(grp["other vendors"]["quantity_blocked_open"])) / (int(grp["ven-007"]["invoices_in_book"]) + int(grp["other vendors"]["invoices_in_book"]))
    assert rate02x > 3 * Decimal(str(elsewhere)) and rate02x > Decimal("0.2")                    # DR-01
    assert Decimal(row_of("03_duplicates_identity_vs_bytes_and_month_end__month_end_clustering", population="merged by identity (re-sent PDFs)")["share"]) > 3 * Decimal(
        row_of("03_duplicates_identity_vs_bytes_and_month_end__month_end_clustering", population="all invoices")["share"])        # DR-03
    assert sum(int(r["approvals"]) for r in RES["04_approvals_under_policy_versions__v1_counterfactual"]) == 20                  # DR-04
    sig = {r["inj"]: r for r in RES["08_rejections_and_injected_defects_by_reason__injected_defect_signatures"]}
    assert [sig[k]["found"] for k in ("INJ-01", "INJ-02", "INJ-05", "INJ-09", "INJ-11")] == ["3", "4", "4", "3", "7"]
    assert all(sig[k]["found"] == "0" and sig[k]["replay_only"] == "true" for k in ("INJ-06", "INJ-07", "INJ-08", "INJ-10", "INJ-12"))
    assert sum(1 for r in sig.values() if r["replay_only"] == "true") == 5 and len(sig) == 12
    sod = {r["check_name"]: r["n"] for r in RES["04_approvals_under_policy_versions__separation_of_duties"]}
    assert [v for k, v in sod.items() if k.startswith(("SELF_", "ROLE_OR_LIMIT", "BEFORE_IMPORT"))] == ["0", "0", "0", "0"]
    over = {r["state"]: int(r["po_lines"]) for r in RES["02_cumulative_consumption_by_po_line__line_state_by_cutoff"] if r["state"] == "over_consumed"}
    assert over == {"over_consumed": 0} and all(r["po_lines"] == "0" for r in RES["02_cumulative_consumption_by_po_line__line_state_by_cutoff"] if r["state"] == "over_consumed")
    for r in RES["06_export_batches_and_reconciliation__reconciliation_by_currency"]:
        assert r["difference"] == "0.00" and r["accepted_export_total"] == r["eligible_approved_total"]
    assert {r["credited_above_the_invoice_total"] for r in RES["07_credits_and_payable_by_currency__credit_size_by_currency"]} == {"0"}
    assert {r["rows_merged"] for r in RES["03_duplicates_identity_vs_bytes_and_month_end__merges_by_reason_and_cutoff"] if r["cutoff"] == "2026-10-01T02:00:00Z"} == {"95", "3"}


@pytest.mark.skipif(not os.environ.get("ARTIFACTS_DATABASE_URL"),
                    reason="ARTIFACTS_DATABASE_URL (a scratch database named artifacts05_* prepared by data/sql/analysis/prepare_snapshot.py) is not set")
def test_sql_files_rerun_against_the_prepared_database_give_the_stored_rows(ps, ra):
    import psycopg
    from psycopg.rows import dict_row
    url = os.environ["ARTIFACTS_DATABASE_URL"]
    assert url.rsplit("/", 1)[-1].startswith("artifacts05_")
    with psycopg.connect(url, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        ra.run_script(c, SQL_DIR / "00_book.sql")
        for f in sorted(SQL_DIR.glob("0[1-8]_*.sql")):
            for key, rows in ra.run_file(c, f).items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key
    if os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL"):
        gurl = os.environ["ARTIFACTS_GOLDEN_DATABASE_URL"]
        assert gurl.rsplit("/", 1)[-1].startswith("artifacts05_")
        with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
            for key, rows in ra.run_file(c, SQL_DIR / "09_golden_known_answer.sql").items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key


def test_a_database_rerun_without_the_scratch_url_is_skipped_with_a_reason():
    marks = [m for m in test_sql_files_rerun_against_the_prepared_database_give_the_stored_rows.pytestmark if m.name == "skipif"]
    assert marks and "ARTIFACTS_DATABASE_URL" in marks[0].kwargs["reason"] and "artifacts05_" in marks[0].kwargs["reason"]


def test_scratch_guard_refuses_a_non_scratch_database():
    prep = _load("ib_prepare", SQL_DIR / "prepare_snapshot.py")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/invoicebridge")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts04_snapshot")
    prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts05_snapshot")


def test_every_sql_file_has_its_header_and_the_numbered_files_read_only():
    files = sorted(SQL_DIR.glob("0*.sql"))
    assert [f.name[:2] for f in files] == ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09"]
    for f in files:
        text = f.read_text()
        assert text.startswith(f"-- {f.name[:-4]}.sql:") or text.startswith(f"-- {f.name}:"), f.name
        assert "P05-" in text or "contract" in text.lower() or "D-0" in text, f.name
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b", body, re.I), f.name           # read-only (00 only creates temporary tables)
        if f.name != "00_book.sql":
            assert "CREATE" not in body, f.name
    assert len(re.findall(r"CREATE TEMP TABLE", (SQL_DIR / "00_book.sql").read_text())) == 2 and "CREATE TABLE" not in (SQL_DIR / "00_book.sql").read_text().replace("CREATE TEMP TABLE", "")
    for f in sorted(SQL_DIR.glob("bi_*.sql")):
        assert "BI package" in f.read_text(), f.name


def test_the_book_is_a_verbatim_copy_of_the_reference_sql():
    """00_book.sql repeats the common table expressions of data/sql/reference_metrics.sql line for line (only the two parameters differ)."""
    ref = (ROOT / "data/sql/reference_metrics.sql").read_text().split("\n")
    book = (SQL_DIR / "00_book.sql").read_text()
    parts = re.split(r"(?m)^-- @@ (\w+)\n", book)
    blocks = {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}
    assert set(blocks) == {"book_run", "book_facts"}
    assert ref[20].startswith("tol AS (") and ref[191].strip() == "WHERE mc.rn > 0" and ref[192].strip() == "),"
    assert "\n".join(ref[20:192]) in blocks["book_run"]                      # tol .. run_inv, the whole recursive chain
    assert "\n".join(ref[20:117]) in blocks["book_facts"]                    # tol .. rej (duplicates, committed approvals, reject decisions)
    assert "%(as_of)s" not in book and "%(cutoffs)s" not in book and "'2026-10-01T02:00:00Z'::timestamptz AS as_of" in book
    assert "main_run" not in book                                              # nothing of the reference's metric assembly is reused


# ---- the workbook ----------------------------------------------------------------------------------------------------------

def _metrics_values(path: Path, bw) -> dict[tuple[str, str], object]:
    ws = openpyxl.load_workbook(path, data_only=True)["Metrics"]
    cols = {"USD": 4, "EUR": 5, "GBP": 6, "ALL": 7}
    return {(ws.cell(row=r, column=1).value, s): ws.cell(row=r, column=c).value for r in range(6, 6 + len(bw.METRICS)) for s, c in cols.items()}


def _expectation(domain_ref, cutoff: str) -> dict[tuple[str, str], float]:
    return {(mid, scope): v for (c, scope), vals in domain_ref.items() if c == cutoff for mid, v in vals.items() if v is not None}


def _assert_metrics_equal(got: dict, want: dict, label: str, bw) -> None:
    tol = {m[0]: {"count": 0, "qty": 5e-5, "money": 5e-3, "rate": 5e-7, "minutes": 5e-5}[m[3]] for m in bw.METRICS}
    for (mid, scope), v in want.items():
        g = got[(mid, scope)]
        assert isinstance(g, (int, float)), (label, mid, scope, g)
        assert abs(float(g) - v) <= tol[mid] + 1e-9, (label, mid, scope, g, v)
    for (mid, scope), g in got.items():
        if (mid, scope) not in want:
            assert g in (None, ""), (label, mid, scope, g)            # nothing is shown that the domain does not publish (money is never summed across currencies)


def test_workbook_sheets_present_and_assumptions_listed(wb):
    assert wb.sheetnames == ["Read me", "Cutoff", "Metrics", "Domain reference", "Golden case", "Assumptions", "Invoices", "Lines", "Decisions", "PO lines", "Receipts",
                             "Credits", "Export requests", "Export lines", "Exceptions", "Assignments", "Policies", "SQL results (pasted)"]
    text = " ".join(str(c.value) for row in wb["Assumptions"].iter_rows() for c in row if c.value)
    for d in ("D-01", "D-02", "D-03", "D-04", "D-05", "D-07", "D-09", "W-01", "W-02", "W-03", "W-04", "W-05", "W-06"):
        assert d in text
    assert "SYNTHETIC" in wb["Read me"]["A2"].value and "PASTED VALUES" in wb["SQL results (pasted)"]["A1"].value and "PASTED VALUES" in wb["Domain reference"]["A1"].value
    assert wb["Cutoff"]["B3"].value == "asof"
    assert any("march,june,asof" in str(dv.formula1) for dv in wb["Cutoff"].data_validations.dataValidation)
    readme = " ".join(str(c.value) for row in wb["Read me"].iter_rows() for c in row if c.value)
    assert DATASET_HASH in readme and CODE_REVISION in readme and "Excel was NOT run" in readme and "Money is per currency" in readme


def test_data_sheets_equal_the_domain(wb, ctx, bw):
    counts = {"Invoices": 2800, "Lines": 5322, "Decisions": 2356, "PO lines": 3000, "Receipts": 5067, "Credits": 117, "Export requests": 59, "Exceptions": 660, "Assignments": 698}
    for sheet, rows in counts.items():
        assert wb[sheet].max_row - 1 == rows, sheet
    inv = {i.invoice_id: i for i in ctx.pop.invoices}
    typed = bw.invoice_rows(ctx)
    for row in wb["Invoices"].iter_rows(min_row=2, max_col=15, values_only=True):
        i = inv[row[0]]
        assert row[1:4] == (i.vendor_id, i.currency, bw.epoch(i.imported_at)) and row[8] == i.created_by, row[0]
        assert abs(row[7] - float(i.declared_total)) < 1e-9 and abs(row[4] - float(i.tax_rate)) < 1e-9
        for k, cut in enumerate(bw.CUTS):                   # the typed match outcome is the domain's at each cutoff
            state, reasons = bw.outcome(ctx, i.invoice_id, cut[1])
            assert (row[9 + 2 * k], row[10 + 2 * k] or "") == (state, reasons), (row[0], cut[0])
    assert len(typed) == 2800
    assert sum((l.quantity * l.unit_price for i in ctx.pop.invoices for l in i.lines), Decimal(0)) == sum(
        Decimal(str(r[3])) * Decimal(str(r[4])) for r in wb["Lines"].iter_rows(min_row=2, max_col=5, values_only=True))
    assert sorted(r[0] for r in wb["Policies"].iter_rows(min_row=5, max_row=6, max_col=1, values_only=True)) == [bw.epoch(p.effective_from) for p in sorted(ctx.pop.approval_policies, key=lambda p: p.effective_from)]


def test_result_cells_of_the_formula_sheets_are_live_formulas_without_hardcoded_quantities(wb, bw):
    assert [m[0] for m in bw.METRICS][:2] == ["eligible_invoices", "matched_invoices"] and len(bw.METRICS) == 34
    m = wb["Metrics"]
    for r in range(6, 6 + len(bw.METRICS)):
        shown = [m.cell(row=r, column=c).value for c in (4, 5, 6, 7)]
        assert any(str(v).startswith("=") for v in shown), r
        assert all(v is None or str(v).startswith("=") for v in shown), (r, shown)                # no typed figure on Metrics
        assert str(m.cell(row=r, column=10).value).startswith("=AND("), r
    inv, lines, dec = wb["Invoices"], wb["Lines"], wb["Decisions"]
    for col in range(16, 40):
        for row in (2, 1500, 2801):
            assert str(inv.cell(row=row, column=col).value).startswith("="), (col, row)
    for col in (6, 7):
        assert str(lines.cell(row=2, column=col).value).startswith("=") and str(lines.cell(row=5323, column=col).value).startswith("=")
    for col in range(7, 16):
        assert str(dec.cell(row=2, column=col).value).startswith("=") and str(dec.cell(row=2357, column=col).value).startswith("=")
    for col in range(7, 15):
        assert str(wb["PO lines"].cell(row=3001, column=col).value).startswith("=")
    assert str(wb["Export requests"]["F60"].value).startswith("=") and str(wb["Export lines"]["F2583"].value).startswith("=")
    assert str(wb["Exceptions"]["F661"].value).startswith("=") and str(wb["Exceptions"]["G661"].value).startswith("=")
    g = wb["Golden case"]
    for r in range(17, 35):
        assert str(g.cell(row=r, column=2).value).startswith("="), r
    assert g["B4"].value == 10 and g["B6"].value == 6 and g["B10"].value == 6 and g["B11"].value == 4                # the typed inputs of the known answer
    c = wb["Cutoff"]
    assert str(c["B10"].value).startswith("=INDEX(") and str(c["B11"].value).startswith("=MATCH(")
    total_formulas = sum(1 for ws in wb.worksheets for row in ws.iter_rows() for cell in row if isinstance(cell.value, str) and cell.value.startswith("="))
    assert total_formulas > 130_000


def test_cached_values_equal_the_domain_recomputed_here(wbv, bw, ctx, domain_ref, wb):
    from invoicebridge.amounts import invoice_amounts
    from invoicebridge.timeutil import parse_ts
    got = _metrics_values(XLSX, bw)
    _assert_metrics_equal(got, _expectation(domain_ref, "asof"), "as delivered", bw)
    ws = wbv["Metrics"]
    assert ws["B3"].value == "asof" and ws["E3"].value is True
    assert all(ws.cell(row=r, column=10).value is True for r in range(6, 6 + len(bw.METRICS)))
    assert wbv["Golden case"]["B36"].value is True and all(wbv["Golden case"].cell(row=r, column=4).value is True for r in range(17, 35))
    # the total of every one of the 2,800 invoices, recomputed here from the lines, equals the workbook's formula
    inv = {i.invoice_id: i for i in ctx.pop.invoices}
    cols = {c.value: k for k, c in enumerate(next(wbv["Invoices"].iter_rows(min_row=1, max_row=1)))}
    bad = 0
    for row in wbv["Invoices"].iter_rows(min_row=2, values_only=True):
        sub, tax, total = invoice_amounts(inv[row[0]])
        if (abs(row[cols["subtotal"]] - float(sub)), abs(row[cols["tax"]] - float(tax)), abs(row[cols["total"]] - float(total))) != (0, 0, 0):
            if max(abs(row[cols["subtotal"]] - float(sub)), abs(row[cols["tax"]] - float(tax)), abs(row[cols["total"]] - float(total))) > 1e-6:
                bad += 1
    assert bad == 0
    # the first valid approval and the export instant per invoice equal the domain's
    book = ctx.books["2026-10-01T02:00:00Z"]
    exported_at = {r["invoice_id"]: parse_ts(r["exported_at"]) for r in book.export_rows}
    for row in wbv["Invoices"].iter_rows(min_row=2, values_only=True):
        iid = row[0]
        want_c = bw.epoch(book.first_valid[iid].decided_at) if iid in book.first_valid else bw.NEVER
        assert row[cols["commit_epoch"]] == want_c, iid
        if iid in exported_at:
            assert row[cols["export_epoch"]] == bw.epoch(exported_at[iid]), iid
    # the pasted column is the domain's too
    dr = wbv["Domain reference"]
    labels = [c.value for c in dr[4]][1:]
    for r in range(5, 5 + len(bw.METRICS)):
        mid = dr.cell(row=r, column=1).value
        for c, label in enumerate(labels, start=2):
            cut, scope = label.split("|")
            v = dr.cell(row=r, column=c).value
            want = domain_ref[(cut, scope)].get(mid)
            assert (v is None and want is None) or abs(v - want) < 1e-9, (mid, label)


def test_full_calc_on_load_is_set_in_workbook_xml():
    import zipfile
    assert 'fullCalcOnLoad="1"' in zipfile.ZipFile(XLSX).read("xl/workbook.xml").decode()


needs_lo = pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")


def _lo_recalc(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(exist_ok=True)
    subprocess.run(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{out_dir}/profile",
                    "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out_dir / "out"), str(src)],
                   check=True, capture_output=True, timeout=1800)
    return out_dir / "out" / src.name


@needs_lo
def test_libreoffice_headless_recalculation_of_a_copy_as_delivered(tmp_path, bw, domain_ref):
    src = tmp_path / "copy.xlsx"
    shutil.copy(XLSX, src)
    res = _lo_recalc(src, tmp_path / "a")
    _assert_metrics_equal(_metrics_values(res, bw), _expectation(domain_ref, "asof"), "recalculated copy", bw)
    assert openpyxl.load_workbook(res, data_only=True)["Metrics"]["E3"].value is True


@needs_lo
@pytest.mark.parametrize("cutoff", ["june", "march"])
def test_the_cutoff_switch_is_live_and_equals_the_domain_for_that_cutoff(tmp_path, bw, domain_ref, cutoff):
    flip = openpyxl.load_workbook(XLSX)                         # formulas only: openpyxl drops the cached values on save
    flip["Cutoff"]["B3"] = cutoff
    src = tmp_path / f"{cutoff}.xlsx"
    flip.save(src)
    assert _metrics_values(src, bw)[("eligible_invoices", "USD")] is None   # no cached values until recalculated
    res = _lo_recalc(src, tmp_path / cutoff)
    got, want = _metrics_values(res, bw), _expectation(domain_ref, cutoff)
    _assert_metrics_equal(got, want, cutoff, bw)
    v = openpyxl.load_workbook(res, data_only=True)
    assert v["Metrics"]["E3"].value is True and v["Metrics"]["B3"].value == cutoff
    expected_obligations = {"march": 1055, "june": 1652}[cutoff]
    assert got[("obligations_count", "ALL")] == expected_obligations
    assert got[("open_exceptions", "ALL")] == {"march": 129, "june": 201}[cutoff] and got[("open_exceptions_history", "ALL")] == {"march": 128, "june": 201}[cutoff]


def test_pasted_sql_results_sheet_matches_the_stored_results(wb):
    ws = wb["SQL results (pasted)"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    meta = RES["meta"][0]
    assert (ws["B3"].value, ws["C3"].value) == (meta["reconciliation_rows"], meta["reconciliation_equal"])
    assert any(isinstance(c, str) and DATASET_HASH in c and CODE_REVISION in c for c in cells)
    pay = row_of("07_credits_and_payable_by_currency__payable_by_currency", currency="USD")
    assert float(pay["approved_payable"]) in cells and float(pay["credit_total"]) in cells
    assert "ven-02x" in cells and "QUANTITY_BLOCKED" in cells
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)               # pasted values, not formulas


# ---- the BI package --------------------------------------------------------------------------------------------------------

def _csv(name: str) -> list[dict]:
    with (ART / "bi" / f"{name}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def test_bi_exports_have_the_documented_grain_and_equal_the_domain(ctx):
    from invoicebridge.amounts import invoice_amounts
    sizes = {"fact_invoice": 2800, "fact_po_line": 3000, "fact_exception": 660, "fact_decision": 2356, "fact_export_row": 2299, "fact_credit_note": 117,
             "dim_vendor": 40, "dim_date": 366, "dim_currency": 3, "dim_policy": 2, "dim_reason": 5}
    for name, rows in sizes.items():
        assert len(_csv(name)) == rows, name
    book = ctx.books["2026-10-01T02:00:00Z"]
    inv = {i.invoice_id: i for i in ctx.pop.invoices}
    for r in _csv("fact_invoice"):
        sub, tax, total = invoice_amounts(inv[r["invoice_id"]])
        assert (r["subtotal"], r["tax"], r["total"]) == (str(sub), str(tax), str(total)), r["invoice_id"]
        assert r["status_at_asof"] == book.status[r["invoice_id"]], r["invoice_id"]
        assert r["currency"] == inv[r["invoice_id"]].currency and r["vendor_id"] == inv[r["invoice_id"]].vendor_id
    assert {r["invoice_id"] for r in _csv("fact_export_row")} == {r["invoice_id"] for r in book.export_rows}
    assert sum(Decimal(r["amount"]) for r in _csv("fact_export_row") if r["currency"] == "USD") == sum(Decimal(r["amount"]) for r in book.export_rows if r["currency"] == "USD")
    assert [r["date_key"] for r in _csv("dim_date")][0] == "20251001" and [r["date_key"] for r in _csv("dim_date")][-1] == "20261001"
    assert {r["currency"] for r in _csv("dim_currency")} == set(CURRENCIES)
    for name in sizes:
        assert "postgresql://" not in (ART / "bi" / f"{name}.csv").read_text()


def test_bi_measures_recomputed_from_the_csv_files_equal_the_stored_expected_values_and_the_domain(ctx, ra):
    from invoicebridge import compute_metrics
    from invoicebridge.timeutil import parse_ts
    meas = ra.bi_measures(_csv("fact_invoice"), _csv("fact_po_line"), _csv("fact_exception"), _csv("fact_export_row"))
    assert meas == RES["bi_measures"]
    assert [{"measure": r["measure"], "currency": r["currency"], "value": r["value"]} for r in _csv("measures_recomputed")] == meas
    dm = compute_metrics(ctx.pop, parse_ts("2026-10-01T02:00:00Z"), [])
    mv = {(m["measure"], m["currency"]): m["value"] for m in meas}
    assert mv[("matched_invoices", "")] == str(dm["matched"]["invoice_count"]) and mv[("obligations", "")] == str(dm["obligations"]["count"])
    assert mv[("straight_through_rate", "")] == dm["rates"]["straight_through_rate"] and mv[("never_excepted_rate", "")] == dm["rates"]["straight_through_never_excepted_rate"]
    assert mv[("mean_minutes_to_approval", "")] == dm["processing"]["mean_minutes"] and mv[("pending_invoices", "")] == str(dm["processing"]["pending_count"])
    for cur in CURRENCIES:
        for k in ("approved_total", "credit_total", "approved_payable"):
            assert mv[(k, cur)] == dm["payable"]["by_currency"][cur][k], (k, cur)
        assert mv[("matched_total", cur)] == dm["matched"]["by_currency"][cur]["total"]
        assert mv[("export_difference", cur)] == dm["export"]["by_currency"][cur]["difference"] == "0.00"
    for reason, c in dm["exceptions"]["by_reason"].items():
        assert mv[("open_exceptions", reason)] == str(c)
    assert sum(1 for r in RES["reconciliation"] if r["check"].startswith("E BI measure") and r["equal"]) >= 40


def test_bi_package_defines_every_measure_blank_safely_and_makes_no_pbix_claim():
    doc = read("bi-package.md")
    assert "No `.pbix` was produced" in doc and "pseudocode" in doc and "not executed" in doc and "Power BI Desktop is not available here and was not run" in doc
    for m in ("Invoices In Book", "Matched Invoices", "Obligations", "Approved Invoices", "Pending Invoices", "Duplicates Merged", "Open Exceptions", "Unowned Exceptions", "Matched Total",
              "Obligations Total", "Credit Total", "Approved Payable", "Accepted Export Total", "Export Difference", "Exception Rate", "Straight Through Rate", "Ever Excepted Rate",
              "Never Excepted Rate", "Mean Minutes To Approval", "Ordered Quantity", "Net Received Quantity", "Accepted Invoiced Quantity", "Open To Receive Quantity", "Open To Invoice Quantity",
              "Received Not Invoiced Qty", "Received Not Invoiced Value", "Is One Currency"):
        assert f"{m} " in doc, m
    assert doc.count("DIVIDE") >= 5 and "HASONEVALUE" in doc and "money may not" in doc and "BLANK" in doc
    for name in ("fact_invoice", "fact_po_line", "fact_exception", "fact_decision", "fact_export_row", "fact_credit_note", "dim_vendor", "dim_date", "dim_currency", "dim_policy", "dim_reason"):
        assert f"`{name}`" in doc and f"artifacts/bi/{name}.csv" in doc, name
    assert DATASET_HASH in doc and CODE_REVISION in doc
    assert not list(ROOT.rglob("*.pbix"))


# ---- data dictionary, ERD, SQL analysis document -----------------------------------------------------------------------------

def _tables_and_columns() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in (ROOT / "data/migrations/0001_schema.sql",):
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", path.read_text(), re.S):
            cols = []
            for line in m.group(2).splitlines():
                mm = re.match(r"([a-z_]+)\s+(BIGSERIAL|TEXT|INT|BOOLEAN|TIMESTAMPTZ|JSONB|NUMERIC|BIGINT|CHAR|DATE)", line.strip())
                if mm:
                    cols.append(mm.group(1))
            out[m.group(1)] = cols
    return out


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations():
    tables = _tables_and_columns()
    assert len(tables) == 21
    dd, erd = read("data-dictionary.md"), read("erd.md")
    assert "```mermaid" in erd and "erDiagram" in erd
    section2 = dd.split("## 2. Columns", 1)[1].split("\n## 3.", 1)[0]
    heads = {}
    for block in section2.split("\n### ")[1:]:
        title, body = block.split("\n", 1)
        for t in [x.strip() for x in title.split(",")]:
            heads[t] = body
    for t, cols in tables.items():
        assert f"`{t}`" in dd, t
        assert re.search(rf"^\s+{t} \{{", erd, re.M), t
        assert t in heads, t
        for c in cols:
            assert f"`{c}`" in heads[t] or f"`{t}.{c}`" in heads[t], (t, c)
            assert re.search(rf"^\s+[\w()\[\]]+ {c}\b", erd, re.M), (t, c)
    for key in ("grain", "Deletion policy", "Append-only lineage", "append-only", "rejected_records", "Source-to-target", "Foreign keys", "invoices_source_fixed", "receipts_reverse_only",
                "import_lineage", "needs_review", "per currency", "synthetic"):
        assert key.lower() in dd.lower(), key
    for k, v in (("vendors", "40"), ("purchase_orders", "1,200"), ("po_lines", "3,000"), ("receipts", "5,067"), ("invoices", "2,800"), ("invoice_lines", "5,322"),
                 ("approvals", "2,356"), ("credit_notes", "117"), ("export_batches", "52"), ("export_rows", "2,299"), ("export_requests", "59"), ("exceptions", "660"),
                 ("exception_assignments", "698"), ("match_results", "5,022"), ("rejected_records", "0")):
        assert re.search(rf"\| `{k}` \|[^\n]*\| {v} \|", dd), k
    assert DATASET_HASH in dd and CODE_REVISION in dd and DATASET_HASH in erd


def test_sql_analysis_doc_quotes_the_stored_results_and_every_table_is_rendered_from_them(ps):
    render = _load("ib_render", ART / "render_sql_analysis.py")
    for name in ("sql-analysis.md", "bi-package.md"):
        text = read(name)
        assert render.render(text, RES) == text, f"{name} drifted from artifacts/analysis-results.json: run artifacts/render_sql_analysis.py"
        assert "(to be rendered)" not in text
    doc = read("sql-analysis.md")
    for key in ps.KEYS:
        assert f"<!-- BEGIN:{key} -->" in doc, key
    assert "<!-- BEGIN:reconciliation -->" in doc and DATASET_HASH in doc and CODE_REVISION in doc
    for sentence in ("0 rows rejected", "Five are replay-only", "zero by construction", "one-exception difference", "outcome-selected", "no hypothetical benefit is claimed", "HYPOTHETICAL",
                     "Money is per currency", "never summed"):
        assert sentence in doc, sentence
    for v in ("98 merges at the as-of: 95 by identity and 3 by identical bytes", "128, 201 and 232", "163 of its 538 invoices (0.302974)", "71 of the 95 re-sent PDFs (0.7474)",
              "114 matched invoices are unapproved", "12 of them exceed the pol-v2 limit", "59 requests, 52 batches created and 7 repeats", "112 invoices of 2,800 imported (0.04)"):
        assert v in doc, v


def test_the_documents_name_the_real_entities_metrics_and_commands_and_keep_result_kinds_apart():
    case = read("business-case.md")
    for token in ("Which invoices may advance and which require exception review", "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "import-invoice", "validate-invoice",
                  "find-duplicates", "match-three-way", "assign-exception", "correct-extraction", "approve-invoice", "reject-invoice", "export-payable", "apply-credit-note", "501",
                  "invoices", "match_results", "exceptions", "exception_assignments", "approvals", "approval_policies", "export_rows", "credit_notes", "import_lineage", "P05-MET-",
                  "P05-FLOW-", "P05-TEST-", "OBSERVED", "observed", "simulated", "hypothetical", "Decision criteria", "Current-state", "Future", "Simulated stakeholders", DATASET_HASH, CODE_REVISION,
                  "approves only invoices that matched without interruption", "rejects only invoices that were exceptions in every run", "closes each period with a batch", "by construction",
                  "needs_review", "no resolving command", "per currency"):
        assert token in case, token
    assert "paid" in case and "no `paid` status" in case


def test_requirements_trace_every_requirement_family_and_mark_c06_as_501():
    req = read("requirements.md")
    for fam in ("P05-GOAL", "P05-DOMAIN", "P05-GOLD", "P05-DATA", "P05-MET-01", "P05-MET-12", "P05-FLOW-01", "P05-FLOW-10", "P05-UI-01", "P05-UI-10", "P05-TEST-01", "P05-TEST-12", "P05-ART", "P05-REL"):
        assert fam in req, fam
    assert re.search(r"P05-FLOW-06 \(C06 correct extraction\)\*\* \|[^\n]*\| \*\*501\*\*", req)
    assert "needs_review" in req and "no command that resolves it" in req
    assert "Functional requirements" in req and "Non-functional requirements" in req and "User stories" in req and "Traceability" in req
    assert "run `40405870287`" in req or "40405870287" in req
    tests_text = " ".join(p.read_text() for p in (ROOT / "tests").glob("test_*.py"))
    named = set(re.findall(r"`(test_[a-z0-9_]+)`", req))
    assert len(named) > 60
    for doc in ("requirements.md", "technical-case-study.md", "uat-evidence.md"):
        for t in set(re.findall(r"`(test_[a-z0-9_]+)`", read(doc))):
            assert f"def {t}(" in tests_text, f"{doc} cites a test that does not exist: {t}"
    assert DATASET_HASH in req and CODE_REVISION in req


def test_executive_memo_quotes_the_per_currency_evidence_and_the_caveats():
    memo = read("executive-memo.md")
    for token in ("OBSERVED", "SIMULATED", "HYPOTHETICAL", "Decision", "| Option |", "Evidence", "Uncertainty", "Limitations", "Recommendation", "by construction",
                  "needs_review", "no resolving command", "synthetic", "Synthetic", "per currency", "Open against ever", "Open at the cutoff", "Ever", "not blocked at the cutoff", "never had an exception",
                  "ven-02x", "ven-007", "163 of 538", "524 of 538", "53 of the 57", "30 of the 32", "approves only invoices that matched without interruption", "rejects only invoices that were exceptions in every run",
                  "closes each period with a batch", "does not support any statement about a realised benefit", "Excel", "Power BI", DATASET_HASH, CODE_REVISION):
        assert token in memo, token
    assert not re.search(r"\b(saves?|saved|savings of|roi)\b", memo, re.I) or "no realised saving" in memo


def test_uat_evidence_keeps_the_original_and_adds_routes_screenshots_scenarios_and_run_links():
    uat = read("uat-evidence.md")
    if shutil.which("git"):
        orig = subprocess.run(["git", "-C", str(ROOT), "show", f"{CODE_REVISION}:apps/invoicebridge/docs/uat-evidence.md"], capture_output=True, text=True)
        if orig.returncode == 0:
            assert uat.startswith(orig.stdout), "uat-evidence.md is append-only: the text of revision 2dcc460 must be unchanged"
    assert "R5-01" in uat and "Final verification (A-042" in uat and "Entry-journey evidence (P05-ART-08" in uat
    for url in ("https://github.com/mrrishit909/projects-site/actions/runs/40405870287", "https://github.com/mrrishit909/projects-site/actions/runs/40406631388"):
        assert url in uat
    for token in ("be20031", "2dcc460", "188e409", "pending", "own CI and live-check runs", "npm run e2e", "did **not** run `npm run e2e`"):
        assert token in uat, token
    for route in ("`/`", "`/intake/`", "`/invoices/`", "`/matching/`", "`/duplicates/`", "`/exceptions/`", "`/approvals/`", "`/vendors/`", "`/exports/`", "`/audit/`", "`/case-study/`"):
        assert route in uat, route
    for shot in ("home", "intake", "invoices", "invoices-golden", "matching", "duplicates", "exceptions", "approvals", "vendors", "exports", "audit", "case-study"):
        assert f"`{shot}`" in uat, shot
    assert "-zoom200.png" in uat and "60 files" in uat
    for s in range(1, 11):
        assert f"| S{s} |" in uat, s
    for token in ("Expected answer", "Actual observation", "Disposition", "Defect disposition", "132.00", "QUANTITY_BLOCKED", "inv-003", "C06"):
        assert token in uat, token
    shots_dir = ROOT / "web" / "evidence"
    if (shots_dir / "index.json").exists():
        idx = json.loads((shots_dir / "index.json").read_text())
        assert idx["count"] == 60 and all(s["scrollWidth"] <= s["innerWidth"] for s in idx["shots"])


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    tcs, rel = read("technical-case-study.md"), read("release-package.md")
    for token in ("Architecture", "Trade-offs", "Recovery behaviour", "Reproducible setup", "Measured evidence", "Open gaps", "committed-first derivation", "```mermaid", "40395845883", "40402231716",
                  "40405870287", "40406631388", "be20031", "2dcc460", "188e409", "3cff603", "pending", DATASET_HASH, "286 reconciliation rows", "by construction", "outcome-selected",
                  "no hosted run recorded yet", "Excel and Power BI Desktop were not run"):
        assert token in tcs, token
    for token in ("188e409", "3cff603", "2dcc460", "40405870287", "40406631388", "pending", "Rollback procedure", "git revert", "Artifacts and checksums", "Not run", DATASET_HASH,
                  "b475a570b3006f2e90e3eb4211f2d96a971f210a8b4881d72a5fe571454036d2", "release-manifest", "nothing was committed or pushed", "Main-portfolio metadata", "Excel", "Power BI"):
        assert token in rel, token


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact_and_match_the_public_case_study():
    text = read("resume-bullets.md")
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6
    body = " ".join(bullets)
    assert not re.search(r"\b(saved|savings|reduced (?:cost|time)|increased revenue|users|customers? adopted|adoption of|roi)\b", body, re.I)
    for token in ("D-01..D-09", "402", "R5-01..R5-22", "286 reconciliation rows", "LibreOffice", "no `.pbix`", "per currency"):
        assert token in body, token
    assert "synthetic" in text.lower() and "no bullet claims business impact" in text
    if PROJECT:
        assert "402 Python tests" in " ".join(PROJECT["tech"]) and "227 TypeScript golden" in " ".join(PROJECT["tech"])


def test_public_case_study_figures_agree_with_the_stored_results():
    if PROJECT is None:
        pytest.skip("the public case study /invoicebridge/project.json is not in this checkout (it lives on unified-portfolio)")
    text = re.sub(r"<[^>]+>", " ", PROJECT["results"] + PROJECT["built"] + PROJECT["tagline"])
    pay = {r["currency"]: r for r in RES["07_credits_and_payable_by_currency__payable_by_currency"]}
    bycur = {r["currency"]: r for r in RES["01_match_outcomes_by_vendor_and_reason__by_currency"]}
    for cur in CURRENCIES:
        assert n(bycur[cur]["matched_total"]) in text and n(pay[cur]["approved_total"]) in text, cur
    assert "2,413" in text and "2,299" in text and "232" in text and "98 duplicate groups" in text
    assert "91.2%" in text and "77.2%" in text and "5,466.7 minutes" in text and "346 invoices pending" in text
    assert "52 export batches answered 59 requests" in text and "7 of them repeats" in text
    assert "30.3%" in text and "97.4%" in text and "1.4%" in text and "30 of the 32 open price variances" in text and "53 of 57" in text
    reasons = {r["reason"]: r["open_at_cutoff"] for r in RES["01_match_outcomes_by_vendor_and_reason__reason_open_vs_ever"]}
    assert (reasons["QUANTITY_BLOCKED"], reasons["PRICE_VARIANCE"], reasons["ROUNDING_EXCEPTION"], reasons["CURRENCY_MISMATCH"]) == ("193", "32", "4", "3")
    assert "193 quantity-blocked, 32 price variances, 4 rounding gaps, 3 currency mismatches" in text
    assert "4.0% of all invoices, 4.9% of approved" in text
    assert PROJECT["repo"].endswith("apps/invoicebridge") and PROJECT["date"] == "2026-10"


def test_no_credentials_or_secrets_in_the_artifact_documents_and_files():
    docs = ["business-case.md", "requirements.md", "data-dictionary.md", "erd.md", "sql-analysis.md", "workbook.md", "bi-package.md", "executive-memo.md", "technical-case-study.md",
            "release-package.md", "resume-bullets.md", "uat-evidence.md"]
    for d in docs:
        text = read(d)
        if d == "uat-evidence.md":
            text = text.split("# Entry-journey evidence", 1)[1]          # the original review evidence (A-040/A-042) is append-only and names the CI workflow's local development login
        assert "lab:lab" not in text, d
        assert not re.search(r"postgres(ql)?://[^<\s]*:[^<\s@]+@", text), d
        assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S{12,}", text), d
    for p in list(ART.glob("*.json")) + list((ART / "bi").glob("*.csv")) + [ART / "CHECKSUMS.txt"] + list(SQL_DIR.glob("*.sql")):
        assert "postgresql://" not in p.read_text(), p.name
        assert "lab:lab" not in p.read_text(), p.name
    wbtext = " ".join(str(c.value) for ws in openpyxl.load_workbook(XLSX).worksheets[:6] for row in ws.iter_rows() for c in row if c.value)
    assert "postgresql://" not in wbtext and "password" not in wbtext.lower()


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = read("workbook.md")
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "invoicebridge-analyst-workbook.xlsx" in doc and "openpyxl 3.1.5" in doc
    for sheet in ("Read me", "Cutoff", "Metrics", "Domain reference", "Golden case", "Assumptions", "Invoices", "Lines", "Decisions", "PO lines", "Receipts", "Credits", "Export requests", "Export lines",
                  "Exceptions", "Assignments", "Policies", "SQL results (pasted)"):
        assert f"`{sheet}`" in doc, sheet
    assert "Cutoff!B3" in doc and "march" in doc and "june" in doc and "fullCalcOnLoad" in doc and "How to read it without installing" in doc and "never summed across currencies" in doc
    for v in ("2,645", "2,413", "1,608,460.47", "531,691.91", "347,369.86", "1,416,036.99", "450,586.03", "281,108.17", "0.927628", "0.834578", "4,804.7573", "15,318.7500", "135,134.34", "W-02"):
        assert v in doc, v
    assert (ROOT / "requirements-artifacts.txt").read_text().strip() == "openpyxl==3.1.5"


def test_provenance_the_analysed_code_and_data_equal_revision_2dcc460():
    """The numbers describe revision 2dcc460: the domain, API, migrations, loaders, reference SQL, published data and fixtures are unchanged since
    (docs/contracts.md is deliberately not part of the check: wording fixes there move no number)."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", CODE_REVISION], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"revision {CODE_REVISION} is not in this checkout")
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", CODE_REVISION, "--", "domain", "api", "data/migrations", "data/seed.py", "data/migrate.py", "data/generate.py",
                        "data/sql/reference_metrics.sql", "web/public", "tests/fixtures"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "", r.stdout
    manifest = json.loads((ROOT / "web/public/data/manifest.json").read_text())
    assert manifest["dataset_hash"] == DATASET_HASH and manifest["dataset_version"] == "ib-20261026-20261026"


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
    chk = _load("ib_checksums", ART / "checksums.py")
    assert sorted(listed) == chk.files()                                  # every artifact and doc, nothing stale
    for must in ("artifacts/invoicebridge-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py", "artifacts/render_sql_analysis.py", "artifacts/checksums.py",
                 "requirements-artifacts.txt", "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
                 "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md", "docs/business-case.md", "docs/requirements.md", "docs/uat-evidence.md",
                 "docs/contracts.md", "docs/api-contract.md", "docs/web-brief.md", "docs/data-generator.md", "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py",
                 "data/sql/analysis/python_side.py", "artifacts/bi/fact_invoice.csv", "artifacts/bi/dim_date.csv", "artifacts/bi/measures_recomputed.csv"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("0*.sql")) + sorted(SQL_DIR.glob("bi_*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    assert "docs/release-package.md" not in listed and "artifacts/CHECKSUMS.txt" not in listed
    rel_doc = read("release-package.md")
    for rel, digest in listed.items():
        assert f"| `{rel}` | `{digest}` |" in rel_doc, rel               # release-package.md carries the same table (it cannot list itself)
