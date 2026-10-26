# Analyst workbook (P01-ART-05)

File: `artifacts/revenue-atlas-analyst-workbook.xlsx` (built by `artifacts/build_workbook.py` with openpyxl 3.1.5, pinned in `requirements-artifacts.txt`). All data is **synthetic**.

| Sheet | Content |
|---|---|
| `Inputs` | The golden fixture rows (`tests/fixtures/golden/inputs.json`, 10 blocks, typed blue cells). |
| `Allocation` | Freight (block 1) and discount (block 2) allocation by shipment line. Integer-cent largest remainder as live formulas: total cents, weight, weight sum, `QUOTIENT` floor, `MOD` remainder, leftover cents, `SUMPRODUCT` rank (ties to the lowest id), extra cent, allocated amount. Block 3 is a formula self-test on author-typed illustrative inputs (10.00 split three ways, expected 3.34 / 3.33 / 3.33), labelled as not data. |
| `Bridge` | Gross sales to contribution margin for **baseline** and **after return**, formulas over `Inputs` and `Allocation`; the only difference between the two columns is the returns switch (row 3). Also CM rate, discount rate, return rate and the residual. |
| `Assumptions` | Decisions D-01..D-07 and four workbook-specific limits (USD only; no unallocated-freight row; single FX rate 1.0; cached-value note). |
| `Snapshot summary` | **Pasted values**, not formulas, from `data/sql/analysis/run_all.py` (query names in each section title, dataset hash in the header). |
| `Checks` | Expected values typed from `expected.json`, each next to the live Bridge result; `TRUE` when equal at 2 dp (rates 6 dp). |

Expected results (`expected.json`): baseline 250.00 / 25.00 / 0.00 / 225.00 / 140.00 / 85.00 / 15.00 / 70.00 (gross, discounts, credits, net, COGS, gross profit, shipping, contribution); after return credits 90.00, net 135.00, COGS 80.00, gross profit 55.00, contribution 40.00.

## Recalculation status (stated plainly)
* **openpyxl cannot calculate.** The builder writes formulas only, so the freshly written file has no cached values.
* **LibreOffice 24.2.7.2 is installed here** (`/usr/bin/soffice`), so the build ran `soffice --headless --convert-to xlsx` and the delivered file is that recalculated output: it keeps the 180 formulas (Allocation 84, Bridge 46, Checks 50; the Snapshot summary sheet has none) and carries LibreOffice-computed cached values. Reading it with openpyxl `data_only=True` gives the expected Bridge values and every row of `Checks` is `TRUE` (including the 3.34 / 3.33 / 3.33 self-test).
* **Excel itself was NOT run.** Nothing here was recalculated or opened by Microsoft Excel; formulas use only functions both engines share (`SUM`, `SUMIF`, `INDEX`, `MATCH`, `ROUND`, `QUOTIENT`, `MOD`, `SUMPRODUCT`, `IF`, `AND`). `fullCalcOnLoad` is set, so Excel recalculates when the file is opened.
* `tests/test_artifacts.py` proves the same independently of any spreadsheet engine: it checks that every Allocation and Bridge cell is a formula (no hard-coded totals; the typed exceptions are the returns switch, two zero inputs and the self-test inputs), re-derives the bridge in Python `Decimal` from the Inputs sheet and compares with `expected.json`, compares cached values when present, and recalculates a copy with LibreOffice when `soffice` exists.

Rebuild: `../../.venv/bin/python artifacts/build_workbook.py --recalc` (run `data/sql/analysis/run_all.py --json artifacts/analysis-results.json` first to refresh the pasted values).
Limits: USD only (fixture FX 1.0); zero-gross shipments use the quantity weight but the explicit unallocated row of D-04 is not modelled; the snapshot sheet is a paste and goes stale if the data changes.
