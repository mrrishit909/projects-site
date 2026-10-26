"""Artifact package checks (P03-ART-03..10): the analyst workbook, the analysis results, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that Ledger, Position, Replenishment and
Figures are live formulas with no hard-coded quantities, (2) re-derives the formula chain in Python (day-order sort key, as-of filter, open
lines, MOQ, pack rounding) from the Inputs sheet and compares it with tests/fixtures/golden/expected.json AND with the domain's
run_pipeline, (3) reads the cached values LibreOffice wrote, (4) recalculates copies with LibreOffice headless: as delivered, with the
position-80 switch flipped, and with the as-of moved, (5) checks that the pasted snapshot summary and the documents agree with
artifacts/analysis-results.json, which is itself compared with the Python domain over web/public/data (no database needed), and
(6) checks CHECKSUMS.txt. With ARTIFACTS_DATABASE_URL (a scratch database prepared by data/sql/analysis/prepare_snapshot.py) it also
re-runs the SQL files and compares their rows with the stored results. Excel is never run.
"""
from __future__ import annotations

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
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

XLSX = ROOT / "artifacts" / "supplyscope-analyst-workbook.xlsx"
GOLD = json.loads((ROOT / "tests/fixtures/golden/inputs.json").read_text())
EXPECTED = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())["states"]
RES = json.loads((ROOT / "artifacts/analysis-results.json").read_text())
SQL_DIR = ROOT / "data" / "sql" / "analysis"
DOCS = ROOT / "docs"
D = Decimal

pytestmark = pytest.mark.skipif(not XLSX.exists(), reason="workbook not built (artifacts/build_workbook.py)")

QUERIES = ["01_stock_position_month_end_by_location", "02_draft_orders_arithmetic", "03_fill_rate_stockout_by_location_abc",
           "04_supplier_on_time_by_month", "05_censored_vs_latent_class_a", "06_working_capital_by_location",
           "07_forecast_wape_by_sku", "08_rejections_and_defects_by_reason", "09_golden_position_and_order"]
BLOCKS = ["inventory_movements", "purchase_orders", "purchase_order_lines", "receipts", "backorders"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wb():
    return openpyxl.load_workbook(XLSX)


@pytest.fixture(scope="module")
def wbv():
    return openpyxl.load_workbook(XLSX, data_only=True)


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def inputs_from_sheet(ws) -> dict:
    """Read the parameter block and the typed entity blocks of the Inputs sheet back (title row, header row, data, blank)."""
    out: dict = {"params": {}}
    rows = list(ws.iter_rows(values_only=True))
    i = 0
    while i < len(rows):
        a = rows[i][0]
        if a == "parameters":
            i += 2
            while rows[i][0] is not None:
                out["params"][rows[i][0]] = rows[i][1]
                i += 1
        elif isinstance(a, str) and a in BLOCKS:
            cols = [c for c in rows[i + 1] if c is not None]
            out[a] = []
            i += 2
            while i < len(rows) and rows[i][0] is not None:
                out[a].append({k: ("" if (k == "state_added" and v is None) else v) for k, v in zip(cols, rows[i][:len(cols)])})
                i += 1
        i += 1
    return out


# ---- structure ----------------------------------------------------------------------------------------------------

def test_sheets_present(wb):
    assert wb.sheetnames == ["Inputs", "Ledger", "Position", "Replenishment", "Figures", "Assumptions", "Snapshot summary"]
    text = " ".join(str(c.value) for row in wb["Assumptions"].iter_rows() for c in row if c.value)
    for d in ("D-01", "D-02", "D-03", "D-04", "D-05", "D-06"):
        assert d in text
    assert "PASTED VALUES" in wb["Snapshot summary"]["A1"].value
    assert "SYNTHETIC" in wb["Inputs"]["A2"].value


def test_inputs_sheet_equals_golden_fixture(wb):
    got = inputs_from_sheet(wb["Inputs"])
    p = got["params"]
    assert p["as_of"] == ts(GOLD["as_of"]) and p["window_start"] == ts(GOLD["window_start"])
    assert (p["reorder_point"], p["target_position"]) == (GOLD["replenishment_params"][0]["reorder_point"], GOLD["replenishment_params"][0]["target_position"])
    prod = GOLD["products"][0]
    assert (p["minimum_order_quantity"], p["pack_size"], D(str(p["unit_cost"]))) == (prod["minimum_order_quantity"], prod["pack_size"], D(prod["unit_cost"]))
    assert p["reserved"] == 0 and GOLD["reservations"] == []
    assert len(got["inventory_movements"]) == len(GOLD["inventory_movements"]) == 7
    for a, b in zip(got["inventory_movements"], GOLD["inventory_movements"]):
        assert (a["movement_id"], a["quantity_delta"], a["event_at"], a["movement_type"]) == (b["movement_id"], b["quantity_delta"], ts(b["event_at"]), b["movement_type"])
    po = GOLD["purchase_orders"][0]
    assert (got["purchase_orders"][0]["status"], got["purchase_orders"][0]["ordered_at"]) == (po["status"], ts(po["ordered_at"]))
    extra = [ln for s in GOLD["states"].values() for ln in s["add_purchase_order_lines"]]
    assert [(l["po_line_id"], l["ordered_quantity"], l["state_added"]) for l in got["purchase_order_lines"]] == (
        [(l["po_line_id"], l["ordered_quantity"], "") for l in GOLD["purchase_order_lines"]]
        + [(l["po_line_id"], l["ordered_quantity"], "position_80") for l in extra])
    assert GOLD["receipts"] == [] and len(got["backorders"]) == 2
    for a, b in zip(got["backorders"], GOLD["backorders"]):
        assert (a["backorder_id"], a["quantity"], a["opened_at"], a["closed_at"]) == (
            b["backorder_id"], b["quantity"], ts(b["opened_at"]), ts(b["closed_at"]) if b["closed_at"] else None)


def test_ledger_position_replenishment_and_figures_are_live_formulas_without_hardcoded_quantities(wb):
    led, pos, rep, fig = wb["Ledger"], wb["Position"], wb["Replenishment"], wb["Figures"]
    n = len(GOLD["inventory_movements"])
    for r in range(5, 5 + n):
        for c in range(1, 12):
            v = led.cell(r, c).value
            assert isinstance(v, str) and v.startswith("="), (r, c, v)
    assert "Inputs!" in led["B5"].value and led["H5"].value == "=IF(B5<=Inputs!$B$6,1,0)"
    assert "SUMPRODUCT" in led["J5"].value and "SUMPRODUCT" in led["K5"].value
    for r in range(5 + n + 1, 5 + n + 7):
        assert isinstance(led.cell(r, 2).value, str) and led.cell(r, 2).value.startswith("="), r
    nl = 2
    for r in range(6, 6 + nl):
        for c in range(1, 8):
            assert isinstance(pos.cell(r, c).value, str) and pos.cell(r, c).value.startswith("="), (r, c)
    for r in range(6 + nl + 2, 6 + nl + 8):
        for c in (2, 3, 4):
            v = pos.cell(r, c).value
            assert isinstance(v, str) and v.startswith("="), (r, c, v)
    for r in range(5, 15):
        for c in (2, 3, 4):
            v = rep.cell(r, c).value
            assert isinstance(v, str) and v.startswith("="), (r, c, v)
    text = " ".join(str(rep.cell(r, 4).value) for r in range(5, 15))
    assert "CEILING(" in text and "MAX(" in text and "IF(" in text
    for r in range(8, 19):
        for col in "BCD":
            v = fig[f"{col}{r}"].value
            assert isinstance(v, str) and v.startswith("=") and ("Position!" in v or "Replenishment!" in v), (col, r, v)
            assert not re.fullmatch(r"=?\d+(\.\d+)?", v)
    assert fig["B3"].value in (0, 1)
    assert fig["B4"].value.startswith("=IF(ISNUMBER(SEARCH(")
    assert fig["B20"].value == "=AND(G8:G18,H8:H18)"
    for r in range(8, 19):                          # the typed expectations are numbers, the comparisons formulas
        assert isinstance(fig[f"E{r}"].value, (int, float)) and fig[f"G{r}"].value.startswith("=")


# ---- the chain, recomputed in Python ------------------------------------------------------------------------------

def evaluate(inp: dict, state: str, as_of: datetime | None = None) -> dict:
    """The chain of Ledger, Position and Replenishment, from the Inputs sheet rows only."""
    P = inp["params"]
    cut = as_of or P["as_of"]
    rank = {"receipt": 0, "sale": 1}
    scope = [m for m in inp["inventory_movements"] if m["event_at"] <= cut]
    run = low = 0
    for m in sorted(scope, key=lambda m: (m["event_at"].date(), rank.get(m["movement_type"], 2), m["event_at"], m["movement_id"])):
        run += m["quantity_delta"]
        low = min(low, run)
    run_ts = low_ts = 0
    for m in sorted(scope, key=lambda m: (m["event_at"], m["movement_id"])):
        run_ts += m["quantity_delta"]
        low_ts = min(low_ts, run_ts)
    orders = {o["purchase_order_id"]: o for o in inp["purchase_orders"]}
    on_order = 0
    for l in inp["purchase_order_lines"]:
        if l["state_added"] not in ("", state):
            continue
        o = orders[l["purchase_order_id"]]
        if o["status"] == "confirmed" and o["ordered_at"] <= cut:
            got = sum(r["received_quantity"] or 0 for r in inp["receipts"] if r["po_line_id"] == l["po_line_id"] and r["received_at"] and r["received_at"] <= cut)
            on_order += max(l["ordered_quantity"] - got, 0)
    backorders = sum(b["quantity"] for b in inp["backorders"] if b["opened_at"] <= cut and (b["closed_at"] is None or b["closed_at"] > cut))
    on_hand = max(run, 0)
    position = on_hand + on_order - backorders
    trig = position < P["reorder_point"]
    raw = max(P["target_position"] - position, 0) if trig else 0
    after = max(raw, P["minimum_order_quantity"]) if trig else 0
    qty = math.ceil(after / P["pack_size"]) * P["pack_size"] if trig else 0
    return {"on_hand_raw": run, "on_hand": on_hand, "running_min": low, "running_min_ts": low_ts, "on_order": on_order, "backorders": backorders,
            "inventory_position": position, "reorder_triggered": trig, "raw_order": raw, "order_after_moq": after, "order_quantity": qty,
            "working_capital": D(str(on_hand)) * D(str(P["unit_cost"]))}


@pytest.mark.parametrize("state", ["golden", "position_80"])
def test_formula_chain_intent_in_python_matches_golden_and_domain(wb, state):
    got = evaluate(inputs_from_sheet(wb["Inputs"]), state)
    exp = EXPECTED[state]["metrics"]
    for k in ("on_hand", "on_order", "backorders", "inventory_position", "reorder_triggered", "raw_order", "order_after_moq", "order_quantity"):
        assert got[k] == exp[k], (state, k)
    assert got["working_capital"] == D(exp["working_capital"])
    assert (got["running_min"], got["running_min_ts"]) == (exp["running_stock_min"], exp["timestamp_order_stock_min"]) == (0, -35)
    from supplyscope import run_pipeline
    dom = run_pipeline(GOLD, state=state).metrics
    for k in ("on_hand", "on_order", "backorders", "inventory_position", "raw_order", "order_after_moq", "order_quantity"):
        assert dom[k] == got[k], (state, k)
    if state == "golden":
        assert [got[k] for k in ("on_hand", "on_order", "backorders", "inventory_position", "raw_order", "order_after_moq", "order_quantity")] == [40, 30, 10, 60, 60, 60, 72]
    else:
        assert (got["inventory_position"], got["order_quantity"]) == (80, 0)


def test_python_chain_with_a_moved_as_of_equals_the_sql_reference_tests(wb):
    inp = inputs_from_sheet(wb["Inputs"])
    later = evaluate(inp, "golden", ts("2026-04-03T00:00:00Z"))          # the sale of 10 on 04-02 is now inside the cutoff (test_sql_reference.py)
    assert (later["on_hand"], later["working_capital"]) == (30, D("375.00"))
    before = evaluate(inp, "golden", ts("2026-03-12T10:00:00Z"))         # the receipt of 15:00 is not yet posted
    assert (before["on_hand"], before["on_hand_raw"], before["running_min"]) == (0, -35, -35)


def _figures(path: Path, sheet: str = "Figures") -> dict[str, tuple]:
    ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    return {ws.cell(r, 1).value: tuple(ws.cell(r, c).value for c in (2, 3, 4)) for r in range(8, 19)}


def _assert_figures(vals: dict[str, tuple], selected_80: bool):
    want = {"On hand": (40, 40, 40), "On order": (50 if selected_80 else 30, 30, 50), "Backorders open": (10, 10, 10),
            "Inventory position": (80 if selected_80 else 60, 60, 80), "Reorder point": (70, 70, 70), "Target position": (120, 120, 120),
            "Raw order (target - position)": (0 if selected_80 else 60, 60, 0), "Order after MOQ": (0 if selected_80 else 60, 60, 0),
            "Order quantity (pack rounded)": (0 if selected_80 else 72, 72, 0), "Working capital (on hand x unit cost)": (500, 500, 500),
            "Reorder triggered (1/0)": (0 if selected_80 else 1, 1, 0)}
    assert set(vals) == set(want)
    for k, w in want.items():
        assert vals[k] == pytest.approx(w), k


def test_cached_values_in_the_delivered_file(wbv):
    """The delivered file was recalculated by LibreOffice, so it carries cached values."""
    fig, led = wbv["Figures"], wbv["Ledger"]
    _assert_figures(_figures(XLSX), selected_80=fig["B3"].value == 1)
    assert fig["B20"].value is True and fig["B21"].value == "40 / 30 / 10 / 60 / 60 / 60 / 72"
    for r in range(8, 19):
        assert fig[f"G{r}"].value is True and fig[f"H{r}"].value is True
    assert (led["B13"].value, led["B14"].value, led["B15"].value, led["B16"].value, led["B17"].value, led["B18"].value) == (40, 40, 0, -35, "ok", "6 / 1")
    assert (led["I8"].value, led["I9"].value) == (5, 4)                  # day order: the 15:00 receipt (mv-005) is applied before the 09:00 sale (mv-004)
    assert led["H11"].value == 0 and led["J11"].value in (None, "")      # mv-007 is after the cutoff and excluded


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


needs_lo = pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")


@needs_lo
def test_libreoffice_headless_recalculation_of_a_copy(tmp_path):
    src = tmp_path / "copy.xlsx"
    shutil.copy(XLSX, src)
    res = _lo_recalc(src, tmp_path / "a")
    _assert_figures(_figures(res), selected_80=False)
    ws = openpyxl.load_workbook(res, data_only=True)
    assert ws["Figures"]["B20"].value is True and ws["Ledger"]["B13"].value == 40


@needs_lo
def test_position_80_switch_is_live_flipping_it_selects_the_other_state(tmp_path):
    flip = openpyxl.load_workbook(XLSX)                 # formulas only: openpyxl drops the cached values on save
    flip["Figures"]["B3"] = 1
    src = tmp_path / "flipped.xlsx"
    flip.save(src)
    assert _figures(src)["Inventory position"] == (None, None, None)          # no cached values until recalculated
    res = _lo_recalc(src, tmp_path / "b")
    _assert_figures(_figures(res), selected_80=True)
    v = openpyxl.load_workbook(res, data_only=True)
    assert (v["Position"]["B15"].value, v["Replenishment"]["B13"].value, v["Figures"]["B20"].value) == (80, 0, True)


@needs_lo
@pytest.mark.parametrize("as_of,want", [(datetime(2026, 4, 3), (30, 30, 0, -35, "ok", "7 / 0")),
                                        (datetime(2026, 3, 12, 10, 0), (0, -35, -35, -35, "NEGATIVE_STOCK", "4 / 3"))])
def test_the_as_of_filter_is_live(tmp_path, as_of, want):
    moved = openpyxl.load_workbook(XLSX)
    moved["Inputs"]["B6"] = as_of
    src = tmp_path / "moved.xlsx"
    moved.save(src)
    res = openpyxl.load_workbook(_lo_recalc(src, tmp_path / "c"), data_only=True)
    led = res["Ledger"]
    got = (led["B13"].value, led["B14"].value, led["B15"].value, led["B16"].value, led["B17"].value, led["B18"].value)
    exp = evaluate(inputs_from_sheet(moved["Inputs"]), "golden")
    assert (exp["on_hand_raw"], exp["on_hand"], exp["running_min"], exp["running_min_ts"]) == (got[0], got[1], got[2], got[3])
    if want[4] == "ok":
        assert (got[1], got[2]) == (want[1], 0) and res["Figures"]["C17"].value == pytest.approx(375.0)
    else:
        assert (got[0], got[1], got[2], got[4]) == (-35, 0, -35, "NEGATIVE_STOCK") and got[5] == want[5]


# ---- the pasted snapshot summary and the stored analysis results --------------------------------------------------

def test_analysis_results_reconcile_and_cover_every_query():
    assert RES["reconciliation"] and all(r["equal"] is True for r in RES["reconciliation"])
    assert len(RES["reconciliation"]) >= 80
    for q in QUERIES:
        assert RES[q], q
        assert (SQL_DIR / f"{q}.sql").exists()
    for r in RES["golden_three_sources"]:
        vals = {r["analysis_sql_09"], r["reference_metrics_sql"], r["python_domain"], r["expected_json"]}
        assert len(vals) == 1, r
    g = {(r["state"], r["quantity"]): r for r in RES["golden_three_sources"]}
    for state, want in (("golden", {"on_hand": "40", "on_order": "30", "backorders": "10", "inventory_position": "60", "raw_order": "60",
                                    "order_after_moq": "60", "order_quantity": "72"}),
                        ("position_80", {"inventory_position": "80", "order_quantity": "0", "raw_order": "0"})):
        for k, v in want.items():
            r = g[(state, k)]
            assert (r["analysis_sql_09"], r["reference_metrics_sql"], r["python_domain"]) == (v, v, v), (state, k)


def test_pasted_snapshot_summary_matches_analysis_results(wb):
    ws = wb["Snapshot summary"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    all03 = next(r for r in RES["03_fill_rate_stockout_by_location_abc"] if r["location_id"] == "ALL")
    assert float(all03["fill_rate"]) in cells and float(all03["stockout_pair_day_share"]) in cells
    assert float(next(r for r in RES["06_working_capital_by_location"] if r["month"] == "ALL")["avg_daily_total"]) in cells
    for r in RES["07_forecast_wape_by_sku"]:
        assert float(r["wape_ewma"]) in cells
    assert any(f"{q}.sql" in cells for q in QUERIES)
    checks = next(c for c in cells if isinstance(c, str) and c.startswith("reconciliation (run_all.py)"))
    ok = [r for r in ws.iter_rows(values_only=True) if r[0] == len(RES["reconciliation"]) and r[1] == len(RES["reconciliation"])]
    assert checks and ok                                                # the pasted count is the stored one (every check equal)
    assert any(isinstance(c, str) and c.startswith("options.py: draft plan") for c in cells)
    assert any(isinstance(c, str) and "5bdabb50eea4b192e3b17e1e5b1a79dc6b26feb4a2b8b78ad094acde9f8bcc8c" in c for c in cells)
    assert "2026-09" in cells and "sup-03" in cells                     # identifiers that look like numbers stay text
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)        # pasted values, not formulas


@pytest.fixture(scope="module")
def domain_run():
    mod = _load("ss_prepare_snapshot", SQL_DIR / "prepare_snapshot.py")
    from supplyscope import run_pipeline
    return run_pipeline(mod.snapshot_inputs())


def test_stored_results_equal_the_python_domain_over_the_snapshot_files(domain_run):
    """No database: the domain over web/public/data reproduces the numbers the SQL printed."""
    from supplyscope.metrics import compute_metrics
    from supplyscope.models import parse_ts
    m = domain_run.metrics
    t02 = next(r for r in RES["02_draft_orders_arithmetic"] if r["product_id"].startswith("TOTAL"))
    assert (t02["on_hand"], t02["on_order"], t02["position"], t02["order_qty"]) == (m["on_hand"], m["on_order"], m["inventory_position"], m["order_quantity"])
    a03 = next(r for r in RES["03_fill_rate_stockout_by_location_abc"] if r["location_id"] == "ALL")
    assert (str(a03["fill_rate"]), a03["fulfilled_units"], a03["unmet_units"]) == (m["fill_rate"], m["fulfilled_units"], m["unmet_units"])
    assert str(next(r for r in RES["06_working_capital_by_location"] if r["month"] == "2026-09")["end_total"]) == m["working_capital"]
    assert RES["reference_metrics_snapshot"][0]["fill_rate"] == m["fill_rate"] and RES["reference_metrics_snapshot"][0]["on_hand"] == m["on_hand"]
    # the two stockout-day metrics of R3-01
    assert (m["stockout_day_count"], m["observed_days"], m["stockout_days"]) == (290, 548, "0.529197")
    assert a03["stockout_pair_days"] == 431 and str(a03["stockout_pair_day_share"]) == "0.013108"
    for r in RES["03_fill_rate_stockout_by_location_abc"]:
        locs = None if r["location_id"] == "ALL" else {r["location_id"]}
        prods = {p.product_id for p in domain_run.population.products if r["abc_class"] == "ALL" or p.abc_class == r["abc_class"]}
        mm = compute_metrics(domain_run.population, parse_ts("2026-09-30T23:59:59Z"), (parse_ts("2025-04-01T00:00:00Z"), None), None, products=prods, locations=locs)
        assert mm["fill_rate"] == str(r["fill_rate"]), r
    # supplier reliability: the designed relationship is present
    by = {r["supplier_id"]: float(r["on_time_rate"]) for r in RES["04_supplier_on_time_by_month"] if r["month"] == "ALL"}
    assert by["sup-03"] < min(by["sup-01"], by["sup-02"], by["sup-04"]) - 0.1
    # censoring: observed on stockout days sits far below latent, and equals the recorded unmet demand
    for r in RES["05_censored_vs_latent_class_a"]:
        assert r["censored_units"] == r["unmet_recorded"] and r["days_observed_ne_latent"] == 0 and r["observed_on_stockout_days"] < r["latent_on_stockout_days"]
    # forecasts: no leakage, baselines beaten by the model for every class A SKU
    assert all(r["leaky_points"] == 0 for r in RES["07_forecast_wape_by_sku"])
    assert all(r["ewma_beats_seasonal_naive"] == "yes" for r in RES["07_forecast_wape_by_sku"] if r["abc_class"] == "A")
    # month-end roll: position = on hand + on order - backorders in every cell
    for r in RES["01_stock_position_month_end_by_location"]:
        assert r["position"] == r["on_hand"] + r["on_order"] - r["backorders"]
    assert sum(r["records"] for r in RES["08_rejections_and_defects_by_reason"] if r["lens"] == "rejection") == len(domain_run.rejected) == 4


@pytest.mark.skipif(not os.environ.get("ARTIFACTS_DATABASE_URL"), reason="ARTIFACTS_DATABASE_URL (prepared scratch database) not set")
def test_sql_files_rerun_against_the_prepared_database_give_the_stored_rows():
    import psycopg
    from psycopg.rows import dict_row

    def norm(rows):
        return [{k: ("" if v is None else format(v, "f") if isinstance(v, Decimal) else str(v)) for k, v in r.items()} for r in rows]

    with psycopg.connect(os.environ["ARTIFACTS_DATABASE_URL"], row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        c.execute((SQL_DIR / "00_ledger_views.sql").read_text())
        for f in sorted(SQL_DIR.glob("0[1-8]_*.sql")):
            assert norm(c.execute(f.read_text()).fetchall()) == norm(RES[f.stem]), f.name


def test_every_sql_file_names_its_requirement_and_has_one_statement_after_00():
    files = sorted(SQL_DIR.glob("0*.sql"))
    assert len(files) == 10
    for f in files:
        text = f.read_text()
        assert text.startswith(f"-- {f.name[:2]}:"), f.name
        assert "P03-" in text or "contract" in text.lower(), f.name
        if not f.name.startswith("00"):
            body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
            assert body.count(";") == 1, f.name
    for f in sorted(SQL_DIR.glob("bi_fact_*.sql")):
        body = "\n".join(l for l in f.read_text().splitlines() if not l.strip().startswith("--"))
        assert body.count(";") == 1 and "docs/bi-package.md" in f.read_text(), f.name


# ---- documents ----------------------------------------------------------------------------------------------------

def _tables_and_columns() -> dict[str, list[str]]:
    sql = (ROOT / "data/migrations/0001_schema.sql").read_text()
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql, re.S):
        cols = []
        for line in m.group(2).splitlines():
            mm = re.match(r"([a-z_]+)\s+(TEXT|INT|BOOLEAN|TIMESTAMPTZ|JSONB|NUMERIC|BIGINT|DATE)", line.strip())
            if mm:
                cols.append(mm.group(1))
        out[m.group(1)] = cols
    return out


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations():
    tables = _tables_and_columns()
    assert len(tables) == 28
    dd, erd = (DOCS / "data-dictionary.md").read_text(), (DOCS / "erd.md").read_text()
    assert "```mermaid" in erd and "erDiagram" in erd
    for t, cols in tables.items():
        assert f"`{t}`" in dd, t
        assert re.search(rf"^\s+{t} \{{", erd, re.M), t
        sect = dd.split(f"### {t}\n", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
        for c in cols:
            assert f"| `{c}` |" in sect, (t, c)
            assert re.search(rf"^\s+\w+ {c}\b", erd, re.M), (t, c)
    for key in ("D-01", "D-06", "append-only", "Immutable", "rejected_records", "quarantined_records", "DUPLICATE_MOVEMENT_ID",
                "RECEIPT_BEFORE_ORDER", "Source-to-target", "grain", "draft", "S-02", "inputs.json"):
        assert key in dd or key.lower() in dd.lower(), key
    assert "5bdabb50eea4b192e3b17e1e5b1a79dc6b26feb4a2b8b78ad094acde9f8bcc8c" in dd


def test_sql_analysis_doc_quotes_the_stored_results_and_every_table_is_rendered_from_them():
    doc = (DOCS / "sql-analysis.md").read_text()
    for q in QUERIES + ["00_ledger_views", "reference_metrics.sql", "options.py"]:
        assert q in doc, q
    render = _load("ss_render", ROOT / "artifacts" / "render_sql_analysis.py")
    assert render.render(doc, RES) == doc                                  # no figure in the tables is typed by hand
    for q in ("01_stock_position_month_end_by_location", "02_draft_orders_arithmetic", "03_fill_rate_stockout_by_location_abc", "09_golden_position_and_order"):
        assert f"<!-- BEGIN:{q} -->" in doc
    assert ("**On hand 40, on order 30, backorders 10, position 60 from the analysis SQL, 60 from `reference_metrics.sql`, 60 from the Python domain. "
            "Raw order 60, order after MOQ 60, order quantity 72 from all three.") in doc
    assert "position 80 and order quantity 0 from all three" in doc
    assert str(len(RES["reconciliation"])) in doc and "R3-01" in doc and "S-03" in doc and "A-1" in doc


def test_memo_quotes_numbers_from_the_results_and_states_its_caveats():
    memo = (DOCS / "executive-memo.md").read_text()
    t02 = {r["product_id"]: r for r in RES["02_draft_orders_arithmetic"]}
    for sku in ("prod-002", "prod-005"):
        r = t02[sku]
        for k in ("on_hand", "on_order", "position", "reorder_point", "target_position", "raw_order", "order_qty"):
            assert str(r[k]) in memo, (sku, k)
        assert str(r["order_value"]) in memo
    total = next(r for r in RES["02_draft_orders_arithmetic"] if r["product_id"].startswith("TOTAL"))
    assert str(total["order_value"]) in memo and str(total["order_qty"]) in memo
    wc = next(r for r in RES["06_working_capital_by_location"] if r["month"] == "2026-09")["end_total"]
    assert str(wc) in memo
    assert f"{float(total['order_value']) / float(wc) * 100:.1f} %" in memo
    a03 = {(r["location_id"], r["abc_class"]): r for r in RES["03_fill_rate_stockout_by_location_abc"]}
    assert str(a03[("loc-02", "A")]["fill_rate"]) in memo and str(a03[("ALL", "ALL")]["fill_rate"]) in memo
    s03 = next(r for r in RES["04_supplier_on_time_by_month"] if r["supplier_id"] == "sup-03" and r["month"] == "ALL")
    assert str(s03["on_time_rate"]) in memo
    for r in RES["10_options_service_target"]:
        assert str(r["order_units"]) in memo and str(r["order_value"]) in memo, r
    for r in RES["10_options_unmet_policy"]:
        assert r["fill_rate"] in memo and r["stockout_day_share"] in memo, r
    for key in ("2026-09-30", "query 02", "query", "synthetic", "Recommendation", "Uncertainty", "Limitations", "Options", "S-03", "S-04", "R3-01",
                "0.90", "0.95", "lost sale", "backlog", "20261026"):
        assert key.lower() in memo.lower(), key
    assert "no real savings" in memo.lower()


def test_bi_package_has_twelve_dax_measures_with_blank_safe_division_and_no_pbix_claim():
    bi = (DOCS / "bi-package.md").read_text()
    assert "No `.pbix` was produced" in bi and "Desktop" in bi
    block = re.search(r"```dax(.*?)```", bi, re.S).group(1)
    core = block.split("-- optional, hidden")[0]
    measures = re.findall(r"^([A-Z][A-Za-z0-9 ]+?)\s*=", core, re.M)
    assert len(set(measures)) == 12, measures
    for name in ("Fulfilled Units", "Unmet Units", "Requested Units", "Fill Rate", "Stockout SKU Day Share", "Stockout Calendar Day Share", "On Hand Units",
                 "Working Capital", "Average Inventory Value", "Inventory Turnover", "Inventory Position", "Draft Order Units"):
        assert name in measures, name
    assert block.count("DIVIDE") >= 8 and len(re.findall(r"BLANK\s*\(\s*\)", block)) >= block.count("DIVIDE")   # every DIVIDE has the BLANK alternate result
    for t in ("fact_movement_day", "fact_draft_order", "dim_product", "dim_location", "dim_supplier", "dim_date", "dim_scenario"):
        assert t in bi, t
    assert "star schema" in bi.lower() and "Power Query" in bi
    render = _load("ss_render2", ROOT / "artifacts" / "render_sql_analysis.py")
    assert render.render(bi, RES) == bi
    exp = {r["measure"]: r["expected"] for r in RES["bi_expected_measures"]}
    assert exp["Fill Rate"] == next(r for r in RES["03_fill_rate_stockout_by_location_abc"] if r["location_id"] == "ALL")["fill_rate"]
    assert exp["Stockout Calendar Day Share"] == "0.529197" and exp["Stockout SKU Day Share"] == "0.013108"


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = (DOCS / "workbook.md").read_text()
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "supplyscope-analyst-workbook.xlsx" in doc
    for sheet in ("Inputs", "Ledger", "Position", "Replenishment", "Figures", "Assumptions", "Snapshot summary"):
        assert f"`{sheet}`" in doc


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact():
    text = (DOCS / "resume-bullets.md").read_text()
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6
    assert "synthetic" in text.lower()
    for l in bullets:
        assert not re.search(r"\b(saved|savings|revenue|users|customers served|increased|reduced cost|improved)\b", l, re.I), l
    assert str(len(RES["reconciliation"])) in text


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    cs = (DOCS / "technical-case-study.md").read_text()
    rel = (DOCS / "release-package.md").read_text()
    for url in ("actions/runs/40340745348", "actions/runs/40343593698", "actions/runs/40348560761", "actions/runs/40347873614", "actions/runs/40348856013"):
        assert url in cs, url
    for k in ("132", "221", "36 Playwright", "409", "422", "501", "S-02", "S-03", "S-04", "R3-01", "R3-07", "T-03-07", "Excel and Power BI Desktop were not run"):
        assert k in cs, k
    for k in ("https://mrrishit909.github.io/projects-site/labs/supplyscope/", "7df1914", "244acba", "12f866f", "7c25780b5586ec6ff10973bca78c4e5a4bea5b3bab7db674964e765b2f637a70",
              "5bdabb50eea4b192e3b17e1e5b1a79dc6b26feb4a2b8b78ad094acde9f8bcc8c", "LibreOffice", "Excel", "git revert"):
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
    for must in ("artifacts/supplyscope-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py", "requirements-artifacts.txt",
                 "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
                 "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md", "data/sql/analysis/00_ledger_views.sql",
                 "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("0*.sql")) + sorted(SQL_DIR.glob("bi_fact_*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    rel_doc = (DOCS / "release-package.md").read_text()
    for rel, digest in listed.items():
        assert digest in rel_doc, rel                      # release-package.md carries the same table (it cannot list itself)
