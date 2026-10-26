"""Artifact package checks (P01-ART-05, P01-ART-10): the analyst workbook and its checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that Allocation and Bridge are
live formulas with no hard-coded totals, (2) re-derives the formula chain's intended results in Python Decimal from the Inputs
sheet and compares them with tests/fixtures/golden/expected.json, (3) compares cached values only when the file carries them,
and (4) recalculates a copy with LibreOffice when soffice is installed. No database is needed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "artifacts" / "revenue-atlas-analyst-workbook.xlsx"
GOLD = json.loads((ROOT / "tests/fixtures/golden/inputs.json").read_text())
EXPECTED = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())
D = Decimal

pytestmark = pytest.mark.skipif(not XLSX.exists(), reason="workbook not built (artifacts/build_workbook.py)")


@pytest.fixture(scope="module")
def wb():
    return openpyxl.load_workbook(XLSX)


def inputs_from_sheet(ws) -> dict[str, list[dict]]:
    """Read the typed blocks of the Inputs sheet back into entity -> rows (title row, header row, data, blank)."""
    out: dict[str, list[dict]] = {}
    r, ent = 1, None
    rows = list(ws.iter_rows(values_only=True))
    i = 0
    while i < len(rows):
        a = rows[i][0]
        if isinstance(a, str) and a in GOLD:
            ent, cols = a, [c for c in rows[i + 1] if c is not None]
            out[ent] = []
            i += 2
            while i < len(rows) and rows[i][0] is not None:
                out[ent].append(dict(zip(cols, rows[i][:len(cols)])))
                i += 1
        i += 1
    return out


def largest_remainder(total_cents: int, weights: dict[str, int]) -> dict[str, int]:
    """D-04: floor shares, then leftover cents to the largest remainders, ties to the lowest key."""
    w = sum(weights.values())
    floor = {k: total_cents * v // w for k, v in weights.items()}
    rem = {k: total_cents * v % w for k, v in weights.items()}
    left = total_cents - sum(floor.values())
    for k in sorted(weights, key=lambda k: (-rem[k], k))[:left]:
        floor[k] += 1
    return floor


def cents(x) -> int:
    return int((D(str(x)).quantize(D("0.01"), ROUND_HALF_UP) * 100).to_integral_value())


def evaluate(inp: dict[str, list[dict]], with_returns: bool) -> dict[str, D]:
    """The bridge arithmetic of docs/contracts.md D-04/D-05 in Python Decimal, from the Inputs sheet rows only."""
    ol = {r["line_id"]: r for r in inp["order_lines"]}
    cost = {r["cost_version_id"]: D(str(r["unit_cost"])) for r in inp["cost_versions"]}
    sls = inp["shipment_lines"]
    gross = {s["shipment_line_id"]: s["shipped_quantity"] * D(str(ol[s["line_id"]]["unit_price"])) for s in sls}
    # freight: per shipment, weight = gross cents (quantity if all gross is 0)
    freight: dict[str, D] = {}
    for shp in inp["shipments"]:
        lines = [s for s in sls if s["shipment_id"] == shp["shipment_id"]]
        w = {s["shipment_line_id"]: cents(gross[s["shipment_line_id"]]) for s in lines}
        if sum(w.values()) == 0:
            w = {s["shipment_line_id"]: s["shipped_quantity"] for s in lines}
        for k, c in largest_remainder(cents(shp["shipping_cost"]), w).items():
            freight[k] = D(c) / 100
    # discounts: per order line, round(discount x shipped/ordered, 2) split by shipped quantity
    disc: dict[str, D] = {}
    for line_id, row in ol.items():
        lines = [s for s in sls if s["line_id"] == line_id]
        shipped = sum(s["shipped_quantity"] for s in lines)
        total = sum((D(str(d["discount_amount"])) for d in inp["discounts"] if d["line_id"] == line_id), D(0))
        t = cents(total * shipped / row["quantity"])
        for k, c in largest_remainder(t, {s["shipment_line_id"]: s["shipped_quantity"] for s in lines}).items():
            disc[k] = D(c) / 100
    returns = inp["returns"] if with_returns else []
    credits = sum((D(str(r["credit_amount"])) for r in returns), D(0))
    cogs_gross = sum(s["shipped_quantity"] * cost[s["cost_version_id"]] for s in sls)
    sl_cost = {s["shipment_line_id"]: cost[s["cost_version_id"]] for s in sls}
    recov = sum((r["returned_quantity"] * sl_cost[r["shipment_line_id"]] for r in returns), D(0))
    g, dd, fr = sum(gross.values()), sum(disc.values()), sum(freight.values())
    net, cogs = g - dd - credits, cogs_gross - recov
    cm = net - cogs - fr
    units = sum(s["shipped_quantity"] for s in sls)
    return {"gross_sales": g, "allocated_discounts": dd, "merchandise_credits": credits, "net_merchandise_sales": net,
            "cogs": cogs, "gross_profit": net - cogs, "shipping_cost": fr, "contribution_margin": cm,
            "allocation_residual": sum((D(str(s["shipping_cost"])) for s in inp["shipments"]), D(0)) - fr,
            "contribution_margin_rate": cm / net, "discount_rate": dd / g,
            "return_rate": D(sum(r["returned_quantity"] for r in returns)) / units}


def test_sheets_present(wb):
    for name in ("Inputs", "Allocation", "Bridge", "Assumptions", "Snapshot summary"):
        assert name in wb.sheetnames
    text = " ".join(str(c.value) for row in wb["Assumptions"].iter_rows() for c in row if c.value)
    for d in ("D-01", "D-02", "D-03", "D-04", "D-05", "D-06", "D-07"):
        assert d in text
    assert "PASTED VALUES" in wb["Snapshot summary"]["A1"].value


def test_inputs_sheet_equals_golden_fixture(wb):
    got = inputs_from_sheet(wb["Inputs"])
    assert set(got) == set(GOLD) - {"contract", "fixture_id", "reporting_currency"}
    for ent, rows in got.items():
        assert len(rows) == len(GOLD[ent]), ent
        for a, b in zip(rows, GOLD[ent]):
            for k, v in b.items():
                if isinstance(v, str) and v.replace(".", "", 1).isdigit():
                    assert D(str(a[k])) == D(v), (ent, k)
                else:
                    assert (str(a[k]).lower() == str(v).lower()) if isinstance(v, bool) else a[k] == v, (ent, k)


def test_allocation_and_bridge_are_live_formulas_without_hardcoded_totals(wb):
    al, br = wb["Allocation"], wb["Bridge"]
    # Allocation blocks 1 and 2 (golden): every data cell is a formula
    blocks = [r for r in range(1, al.max_row + 1) if al.cell(r, 1).value == "shipment_line_id"]
    assert len(blocks) == 2
    for hdr in blocks:
        for r in range(hdr + 1, hdr + 3):
            for c in range(1, 16):
                v = al.cell(r, c).value
                assert isinstance(v, str) and v.startswith("="), (r, c, v)
        # the largest-remainder step is written as formulas
        r = hdr + 1
        assert "QUOTIENT" in al.cell(r, 10).value and "MOD(" in al.cell(r, 11).value
        assert "SUMPRODUCT" in al.cell(r, 13).value and al.cell(r, 15).value.startswith("=(J")
    assert any("Inputs!" in str(al.cell(r, 7).value) for r in range(blocks[0] + 1, blocks[0] + 3))
    # Bridge: rows 5..21 columns B,C are formulas, except the two typed-zero input rows (no shipping revenue / other costs)
    typed = {"Shipping revenue", "Other variable costs"}
    for r in range(5, 22):
        for col in (2, 3):
            v = br.cell(r, col).value
            if br.cell(r, 1).value in typed:
                assert v == 0
            else:
                assert isinstance(v, str) and v.startswith("="), (r, col, v)
    refs = " ".join(str(br.cell(r, 2).value) for r in range(5, 22))
    assert "Allocation!" in refs and "Inputs!" in refs
    assert br["B3"].value == 0 and br["C3"].value == 1          # the returns switch is the only difference between states


@pytest.mark.parametrize("state,with_returns", [("baseline", False), ("after_return", True)])
def test_formula_chain_intent_in_python_matches_golden(wb, state, with_returns):
    got = evaluate(inputs_from_sheet(wb["Inputs"]), with_returns)
    exp = EXPECTED["states"][state]["metrics"]
    for key, val in got.items():
        dp = D("0.000001") if key.endswith("rate") else D("0.01")
        assert val.quantize(dp, ROUND_HALF_UP) == D(exp[key]), (state, key, val)
    if state == "baseline":
        assert [str(got[k].quantize(D("0.01"))) for k in ("gross_sales", "allocated_discounts", "merchandise_credits",
                "net_merchandise_sales", "cogs", "gross_profit", "shipping_cost", "contribution_margin")] == \
            ["250.00", "25.00", "0.00", "225.00", "140.00", "85.00", "15.00", "70.00"]
    else:
        assert [str(got[k].quantize(D("0.01"))) for k in ("merchandise_credits", "net_merchandise_sales", "cogs",
                "gross_profit", "contribution_margin")] == ["90.00", "135.00", "80.00", "55.00", "40.00"]


def test_largest_remainder_ties_go_to_lowest_key():
    assert largest_remainder(1000, {"t-1": 1, "t-2": 1, "t-3": 1}) == {"t-1": 334, "t-2": 333, "t-3": 333}
    assert sum(largest_remainder(1001, {"a": 3, "b": 5, "c": 7}).values()) == 1001


def _bridge_values(path: Path) -> dict[str, tuple]:
    ws = openpyxl.load_workbook(path, data_only=True)["Bridge"]
    return {ws.cell(r, 1).value: (ws.cell(r, 2).value, ws.cell(r, 3).value) for r in range(5, 22)}


def _assert_bridge(values: dict[str, tuple]):
    want = {"Gross sales": (250, 250), "Allocated discounts": (25, 25), "Merchandise credits": (0, 90),
            "Net merchandise sales": (225, 135), "COGS": (140, 80), "Gross profit": (85, 55),
            "Shipping cost (allocated freight)": (15, 15), "Contribution margin": (70, 40), "Allocation residual": (0, 0)}
    for k, (b, a) in want.items():
        assert values[k][0] == pytest.approx(b) and values[k][1] == pytest.approx(a), k
    assert values["Contribution margin rate"][0] == pytest.approx(70 / 225)
    assert values["Return rate"][1] == pytest.approx(1 / 3)


def test_cached_values_if_present():
    vals = _bridge_values(XLSX)
    if all(v == (None, None) for v in vals.values()):
        pytest.skip("workbook carries no cached values (openpyxl output; Excel recalculates on open)")
    _assert_bridge(vals)


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_libreoffice_headless_recalculation_of_a_copy(tmp_path):
    src = tmp_path / "copy.xlsx"
    shutil.copy(XLSX, src)
    out = tmp_path / "out"
    subprocess.run(["soffice", "--headless", "--norestore", "--convert-to", "xlsx:Calc MS Excel 2007 XML",
                    "--outdir", str(out), str(src)], check=True, capture_output=True, timeout=180)
    _assert_bridge(_bridge_values(out / "copy.xlsx"))
    ws = openpyxl.load_workbook(out / "copy.xlsx", data_only=True)["Checks"]
    flags = [ws.cell(r, 5).value for r in range(5, ws.max_row + 1) if ws.cell(r, 5).value is not None]
    assert flags and all(f is True for f in flags)


def test_pasted_snapshot_summary_matches_analysis_results(wb):
    res = json.loads((ROOT / "artifacts/analysis-results.json").read_text())
    total = next(r for r in res["01_margin_bridge_by_month"] if r["period"] == "TOTAL")
    ref = res["reference_totals"][0]
    assert D(total["contribution"]) == D(ref["contribution_margin"]) and D(total["gross_sales"]) == D(ref["gross_sales"])
    ws = wb["Snapshot summary"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    assert float(total["contribution"]) in cells and float(ref["gross_sales"]) in cells
    assert all(r["equal"] for r in res["reconciliation"])


def test_checksums_file_matches_files():
    path = ROOT / "artifacts" / "CHECKSUMS.txt"
    if not path.exists():
        pytest.skip("CHECKSUMS.txt not written (artifacts/checksums.py)")
    for line in path.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
