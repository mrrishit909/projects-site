# ChangeWorks: the analyst workbook (P09-ART-05)

**Synthetic data only.** File `artifacts/changeworks-analyst-workbook.xlsx`, built by `artifacts/build_workbook.py` (openpyxl 3.1.5, `requirements-artifacts.txt`) from the published snapshot `cw-20261026-20261026` (generator `dataset_hash` `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`), code revision `29948f9`, as-of 2026-10-05T00:00:00Z. Every NPV and payback in it is a **plan estimate** of a synthetic scenario; nothing is a measured benefit of a real organisation.
The decision it serves: **which transformation initiative should be funded, and how will success be established?** It is the financial analyst's working copy of the cash-flow model: change the scenario or the rate and see every initiative's flow, NPV and paybacks, the four classes kept apart and the attributable portfolio NPV beside the plain sum.

## How to read it without installing anything
Open the `.xlsx` in any spreadsheet application (or upload it to a web spreadsheet): the delivered file carries the values LibreOffice cached when it recalculated it, so nothing needs to be computed to read it. `Controls!B3` picks the scenario (any of the 30; `scn-025` as delivered), `Controls!B4` overrides the period rate (blank = the scenario's own), `Checks!B2` is TRUE when every figure agrees with the Python domain, the SQL ledger and the golden hand answer. Blue cells are typed inputs or pasted values; black cells are formulas.

## What was and was not run
* **LibreOffice** (headless, `soffice --convert-to xlsx`) recalculated the delivered file; `Checks!B2` is **TRUE** in it. `tests/test_artifacts.py` recalculates a copy as delivered and copies with the scenario switch set to other scenarios (`scn-001`, `scn-006` with a declared monthly rate, `scn-015` with a 24-period horizon, `scn-030`) and asserts that the check cell stays TRUE and the attributable NPV equals the domain's for that scenario.
* **Excel itself was NOT run.** No figure here was opened or recalculated by Microsoft Excel. `fullCalcOnLoad` is set in `xl/workbook.xml` (LibreOffice drops it; `build_workbook.py` puts it back) so that Excel recalculates on open. The functions used are in the Excel 2010 set (SUMIFS, COUNTIFS, SUMPRODUCT, INDEX, MATCH, IFERROR, ...; no `_xlfn` function), but that Excel computes them identically is **unverified**.

## Sheets
| Sheet | What it holds |
|---|---|
| `Read me` | what the file is, the decision, the synthetic-data statement, how to use it, the recalculation status |
| `Controls` | the scenario switch `Controls!B3`, the rate override `Controls!B4`, the as-of and period start, the effective rate and horizon of the selected scenario (formulas), `Controls!B15` = `Checks!B2`, `Controls!B16` = the attributable NPV |
| `Checks` | `Checks!B2` = AND of every check column (Portfolio, Initiatives, Golden case) and three structural checks |
| `Portfolio` | the ledger of the selected scenario: planned costs, the four classes, avoided cost beside the flow, hours not converted, planned and attributable benefits, the residuals, the plain and attributable NPV; each against the pasted reference |
| `Initiatives` | per initiative: member, has flows, costs, benefits entering, NPV, simple and discounted payback by the last crossing (period, reason, interpolation), against the domain |
| `Cash flow` | 24 initiatives x 36 periods: costs (SUMPRODUCT over the half-open ranges of `Costs`), cash, revenue, avoided cost realised, capacity converted, net, cumulative, discount factor 1/(1+r)^t, discounted, cumulative discounted |
| `Golden case` | the P09-GOLD-01 hand answer with formulas: NPV 5000/121 = 41.32, paybacks 2 (1.6667) and 2 (1.9167), the attributable -8300/11 = -754.55 |
| `Assumptions` | A-01..A-06 (the contract rules the formulas implement) and W-01..W-06 (limits: what is TYPED, recalculation, floating point, the override) |
| `Benefits` | the 700 benefit rows (typed) and, per row, its ramp factor, class, money, the double-count rank and the removed amount and its present value (formulas) |
| `Costs` | the 900 cost rows (typed) and their half-open range (formulas) |
| `Scenario inputs` | per scenario x initiative: the ramp and the conversion rate the scenario uses (TYPED, W-02) |
| `Scenarios` | the 30 scenarios (typed) and their effective period rate (formula) |
| `Periods` | the 36 periods and whether each is matured at the as-of (formulas) |
| `Domain reference` | PASTED VALUES from the Python domain and the SQL ledger, per scenario and per scenario x initiative; used by the check columns only |
| `SQL results (pasted)` | headline result sets of `artifacts/analysis-results.json` as values, with the reconciliation count |

## Figures as delivered (scenario scn-025, cached values after LibreOffice)
Planned costs 25,914,200.00; cash 15,288,067.20; revenue 6,074,000.13; avoided cost realised 5,516,433.35; capacity converted 1,774,010.55; avoided cost beside 4,025,383.47; capacity hours not converted 145,045.62; planned benefits 32,677,894.70; residual 207,146.32; attributable benefits 32,470,748.38; hours residual 5,974.80; NPV plain sum 1,438,382.25; double-counted PV 195,233.20; attributable NPV **1,243,149.05**; six initiatives never pay back. Golden case: 41.32, 1.6667, 1.9167, -754.55. The SQL reconciliation behind the pasted sheet has 763 rows, all equal.

## Limits
* The choice of assumption version per scenario (pinned, else the latest created by the scenario's created_at) is TYPED from `python_side.py`, not replayed by formulas (W-02); every result that depends on it is checked against the domain after recalculation.
* Spreadsheet arithmetic is binary floating point; the checks use 0.005 USD on money. The exact rationals are in the SQL analysis.
* Adoption, training, realisation, forecasts and the roadmap are not in the workbook; they are in `sql-analysis.md` and the BI files.
* The rate override is a what-if: while it is set the checks against the domain stand down (they would compare different rates).
