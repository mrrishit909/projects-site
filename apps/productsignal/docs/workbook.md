# Analyst workbook (P06-ART-05)

`artifacts/productsignal-analyst-workbook.xlsx`, built by `artifacts/build_workbook.py` with openpyxl 3.1.5 and recalculated by LibreOffice 24.2 headless. **Synthetic data only**: the workbook recomputes the experiment read of one onboarding experiment (v1 400 accounts, v2 154) over the published snapshot `ps-20261026-20261026` (generator hash `12672f9c39402517083bbbbe9164cbefe3435361dff086eb0d9e16e60f9b66f8`, seed 20261026, contract v1, code revision `fdf911a`, as-of 2026-10-05T00:00:00Z). Observed, constructed and hypothetical results are kept apart: everything on `Metrics` is OBSERVED in one draw of a generated world; the designed effect (+8.00 pp), v2's sample-ratio mismatch and the INJ-10 instrumentation gap are constructed; no benefit to a real product is claimed.
The decision it supports: **should an onboarding change ship, stop, or receive more investigation?** For the final v1 run the workbook reads 63 of 200 control and 82 of 200 treatment accounts activated, **+9.50 percentage points** (relative lift 0.301587), Newcombe 95% interval **+0.000812 to +0.186863**: **conclusive by a hair**. The published lift sits inside the INJ-10 gap: **published +9.50, drawn +11.50, +9.96 excluding the 11 gap accounts** (`executive-memo.md`).

## How to read it without installing anything
Open the .xlsx in any spreadsheet application, or read this file: it lists every sheet and the checked values. The delivered file already carries the values LibreOffice calculated for run an-004 (the final run of v1).

## Sheets
| Sheet | What it holds |
|---|---|
| `Read me` | What it is, how to use the switch, what the formulas do and do not do, provenance and recalculation status |
| `Cutoff` | **The switch:** `Cutoff!B3` takes an-001, an-002, an-003, an-004 or an-005 (a list); the selected cutoff epoch, version, planned_end, windows, `z`, allocation and plan flags are looked up from `Runs` and `Plans` |
| `Metrics` | 39 metric rows for the selected run in three columns (control, treatment, combined or difference): live formulas, a definition, a tolerance and a check column; `E3` is TRUE when every row equals the domain |
| `Domain reference` | PASTED VALUES from the Python domain (`run_pipeline`, `guardrail_review`, `revenue_difference`) for the five runs, read only by the check column; the word `withheld` for the outcome rows of a sample-ratio MISMATCH |
| `Golden case` | The known answer with formulas (20 of 100 against 30 of 100, Wilson, Newcombe, chi-square 0) and its check against `expected.json` |
| `Plan x segment` | Seven-day activation by plan and segment at the as-of, live `COUNTIFS` over `Accounts` (equals investigation 01) |
| `Assumptions` | The contract decisions applied (D-01 .. D-10) and the workbook's own limits (W-01 .. W-05) |
| `Assignments` | 554 rows (v1 400, v2 154): typed epoch instants of the assignment, the first signup and its receipt, the activation and its receipt, the exposure and the first error received in the guardrail window (blue), and the cutoff-dependent flags `in_read`, `signup_known`, `mature`, `activated`, `exposed`, `guardrail_eligible`, `errored`, `revenue_usd` (formulas) |
| `Subscriptions` | 207 subscriptions with a `carries_revenue` formula (active or ended) |
| `Accounts` | 600 accounts with plan, segment, timezone, `is_internal`, the first signup and activation instants and the as-of maturity and activation flags (formulas) |
| `Runs` | The five logged runs (cutoff and creation instants) |
| `Plans` | The two frozen plans: planned_end, frozen_at, the first logged run, allocation, `z`, confidence, SRM thresholds, windows, hash and its validity |
| `SQL results (pasted)` | PASTED VALUES from `data/sql/analysis/run_all.py` (the lift by cutoff, the sample ratios, the guardrail, the revenue difference, the gap lift, plan x segment, the weekly cohort grid and the tracking weeks); 296 reconciliation rows, all equal |

## How to use the switch
`Cutoff!B3` takes **an-001**, **an-002**, **an-003** (interim runs of v1), **an-004** (the final run at planned_end) or **an-005** (v2). Every figure on `Metrics` follows it, including which assignments existed (the cutoff rule D-08: assignments with `assigned_at` at or before the cutoff, events received by it). The check column compares each figure with the Python domain's value for the same run.

| Run (cutoff) | Assigned (c / t) | Mature | Activated | Conversion | Lift (pp) | Relative lift | Newcombe low | high | SRM verdict | Conclusive |
|---|---|---|---|---|---|---|---|---|---|---|
| an-001 (2026-05-18) | 77 / 78 | 65 / 64 | 18 / 25 | 0.276923 / 0.390625 | +11.37 | 0.410590 | -0.048312 | 0.268068 | OK | false |
| an-002 (2026-06-15) | 127 / 126 | 114 / 115 | 34 / 48 | 0.298246 / 0.417391 | +11.91 | 0.399488 | -0.004952 | 0.238174 | OK | false (interim) |
| an-003 (2026-07-13) | 177 / 176 | 164 / 164 | 53 / 68 | 0.323171 / 0.414634 | +9.15 | 0.283019 | -0.012863 | 0.193048 | OK | false (interim) |
| an-004 (2026-08-02) | 200 / 200 | 200 / 200 | 63 / 82 | 0.315000 / 0.410000 | +9.50 | 0.301587 | +0.000812 | 0.186863 | OK | **true** |
| an-005 (2026-10-04) | 62 / 92 | 56 / 87 | withheld | withheld | withheld | withheld | withheld | withheld | **MISMATCH** (25.004329) | withheld |

At an-004: exposure 0.875000 and 0.870000, the guardrail 31 of 200 against 30 of 200 (0.155000 and 0.150000, difference -0.50 pp, Newcombe -0.076005 to +0.066018, verdict OK), revenue per assigned account USD 97.83 (19,566.00) and USD 130.95 (26,190.00) with t intervals 58.98 to 136.68 and 86.70 to 175.20, and a difference of USD 33.12 with a Welch interval of -25.59 to +91.83 (df 391). At an-005 the sample-ratio statistic is 25.004329 and its p-value 0.0000006 (the domain publishes 0.000001); every outcome row shows `withheld`, as the site does.

## Recalculation status (stated plainly)
openpyxl wrote formulas only. LibreOffice 24.2 (headless) recalculated the delivered file; the cached values in the .xlsx are LibreOffice's. **Microsoft Excel itself was NOT run**: nothing here was opened or recalculated by Excel, and the workbook is not evidence about Excel's behaviour. `fullCalcOnLoad` is set so Excel recalculates when it opens the file. Functions used are common to both engines (`SUMIFS`, `COUNTIFS`, `SUMPRODUCT`, `INDEX`, `MATCH`, `IF`, `AND`, `ABS`, `SQRT`, `INT`, `CHIDIST`, `TINV`). `tests/test_artifacts.py` recalculates copies of the file with LibreOffice for each of the five runs and compares every `Metrics` figure with the Python domain recomputed in the test (skipped, with its reason, when `soffice` is not installed).

## Rebuild
```
cd apps/productsignal
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi   # the pasted SQL results
../../.venv/bin/python artifacts/build_workbook.py --recalc                                                      # builds, recalculates, restores fullCalcOnLoad
```
`requirements-artifacts.txt` pins openpyxl 3.1.5 (also in `requirements.txt`); LibreOffice (`soffice`) is needed only for `--recalc` and for the recalculation tests.

## Limits
* **What the formulas do not do (W-02, W-03).** They do not canonicalise the event log (received by the cutoff, deduplicated, identity forward only, bots and internal accounts excluded) and they do not take the plan's sha256: the instants of the first signup (and when it arrived), the activation and the first error received inside the guardrail window are typed from the independent Python side, and the plan hash validity is typed. A signup whose earliest event arrives late while a later one arrives earlier would be read differently; `build_workbook.py` asserts that no such case exists at the five runs.
* **The raw instants of v2 are in `Assignments`.** The withholding is a formula rule (`Metrics!B4`); a reader who works the typed activation instants of the v2 rows by hand can compute a v2 lift, which the sample-ratio mismatch forbids reading.
* **Doubles, not decimals.** The workbook is compared with the domain within 5E-7 for six-decimal figures and 0.005 for money and percentage points; the domain's exact rounding is not reproduced.
* **The INJ-10 gap is not flagged** in the workbook: it computes the published +9.50 pp, and the gap-excluded and drawn figures live in `sql-analysis.md` and `executive-memo.md`.
* **Segments are exploratory** and carry no multiplicity correction here (`Plan x segment`); none is a decision basis.
* **No Excel, no Power BI.** The workbook was recalculated by LibreOffice only; no `.pbix` exists (`bi-package.md`).
