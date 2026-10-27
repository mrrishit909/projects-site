# Analyst workbook (P10-ART-05)

**Synthetic data; the economics are hypothetical; no retention improvement is claimed.** File: `artifacts/retentionlab-analyst-workbook.xlsx`, built by `artifacts/build_workbook.py` with openpyxl 3.1.5 (`requirements-artifacts.txt`) and recalculated by LibreOffice (headless). Dataset `rl-20261026-20261026`, `dataset_hash` `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`, code revision `ce96e65`, as-of 2026-10-05T00:00:00Z.

## How to read it without installing anything
The cached values are stored in the file, so any spreadsheet viewer shows them. The `Read me` sheet repeats this. **Excel itself was NOT run**: the delivered file was recalculated by LibreOffice, not by Excel (see "Recalculation status"). `Checks!B2` is the single cell to look at: it is TRUE when every figure in the workbook agrees with the SQL/Python results of `docs/sql-analysis.md` and with the golden hand answer.

## Sheets
Blue = typed input or pasted value; black = formula.

| Sheet | What it holds |
|---|---|
| `Read me` | what the workbook is, the decision, recalculation status |
| `Controls` | `Controls!B3` the selected model; `B5` a scenario; `B11:B14` a what-if (capacity, contact cost, assumed effect, margin); `B18` repeats `Checks!B2` |
| `Checks` | 70 checks: workbook value, typed reference, tolerance, TRUE/FALSE; `Checks!B2` is AND of all |
| `Models` | rows, churning rows, prevalence, average precision, Brier and mean probability of the five probability columns (live formulas over the test table); the six margins against their declared values, each marked "met, by construction (D-G02)" or "reference, not a target" |
| `Calibration` | the ten bins with counts for the Platt-calibrated and the uncalibrated logistic model, gaps in percentage points (blank for an empty bin), the Platt effect, gaps by segment and region |
| `Capacity` | churners in the top K, precision, recall and risk lift at K = 5, 10, 20 for four models (tie-broken rank), and the block of the selected model |
| `Economics` | the 97 scored accounts of the 2026-09-01 queue with their rank, the contact budget and the HYPOTHETICAL expected value per scenario (ROUND once at the end), the published world values beside them (typed, 1,241 scored accounts), and a what-if |
| `Censored tail` | eligible, mature, censored and churned rows by cutoff (world, typed) and the cohort's counts, censored share, mature churn rate, the implied cancellations seen so far |
| `Drift` | PSI of `usage_events_30d` for apac, other regions and all accounts at the four test cutoffs, recomputed from the test table with live `COUNTIFS` and `LN`; the 21-cutoff published apac series with the false-positive reading |
| `Purge` | cutoff rows, retained, LABEL_WINDOW, GROUP_TEST and GROUP_VALIDATION counts for the cohort and the world |
| `Golden case` | the four-account known answer rebuilt by formulas against the hand answers |
| `Assumptions` | A-01..A-07 and W-01..W-05: read before relying on a figure |
| `Scenarios` | the three immutable scenarios (capacity, contact cost, assumed effect, margin) |
| `Test table` | the 1,513 test rows (blue, published) with live columns: tie-broken rank (inside the 25 highest probabilities of a model), average-precision term, squared error, calibration bin |
| `SQL results (pasted)` | pasted headline result sets of `artifacts/analysis-results.json` and the reconciliation count |

## What the formulas do, live
* **Average precision** is the mean, over churning rows, of tp(p >= row) / n(p >= row): the scikit-learn step form, tied probabilities one threshold. **Brier** is the mean of (p - y)^2.
* **Precision, recall and risk lift at K** use the rank: probability descending, then account id, then the earlier cutoff. A tie across the cut (the rule and the prevalence constant) is flagged in the reference column; risk lift is a ranking statistic, not uplift.
* **Calibration**: bin = floor(10 p) from integer arithmetic on p x 10^6; an empty bin shows blank, not 0.
* **Economics**: value = ROUND(SUMPRODUCT((rank <= K) x (p x effect x margin - cost)), 2), rounded once. The cohort value is computed here; the world value is typed from the published aggregates and cannot be recomputed from the cohort.
* **Drift**: three-bin PSI with the 0.0001 floor, counted per row (`floored bins`); `LN` is floating point here (the domain uses 60-digit decimals).

## How to use the switches
Change `Controls!B3` to any of `random_baseline`, `business_rule`, `logistic_regression`, `prevalence_baseline`: the selected-model block of `Capacity` follows it, and `Checks!B2` stays TRUE (every model is always computed and checked). `Controls!B5` selects a scenario; `Controls!B11:B14` run a what-if on the 97 cohort accounts: with the defaults (K 5, cost 8, effect 0.3, margin 200) it reproduces +21.38 USD, and with K 10 and effect 0.2 it reproduces -6.87. A what-if is an assumption, not an estimate.

## Headline values (all reconciled; see `sql-analysis.md`)
Average precision / Brier: logistic (Platt) 0.238552 / 0.105019, rule 0.136653 / 0.109255, random 0.126793 / 0.326543, prevalence constant 0.124917 / 0.109664, logistic before Platt 0.238552 / 0.104515. Logistic precision at K = 5 / 10 / 20: 0.000000 / 0.200000 / 0.250000; lift 0.000000 / 1.601058 / 2.001323. Hypothetical values on the cohort: 21.38 / -6.87 / -95.46 (budgets 40.00 / 80.00 / 160.00); world (typed): 81.13 / 71.04 / -29.12. Censored share 0.397610, mature churn 0.104500. apac PSI at 2026-05-01: 0.513545. Golden: precision 0.5, recall 0.5, Brier 0.1925, AP 0.833333, budget 10.00, value 8.45.

## Recalculation status (stated plainly)
openpyxl writes formulas only and cannot calculate. The delivered file was opened by **LibreOffice** (`soffice --headless`) and saved over itself, so it carries cached values; `fullCalcOnLoad="1"` is put back into `xl/workbook.xml` afterwards so that Excel recalculates when it opens the file. **Excel was not run**: nothing here was opened or recalculated by Excel, and any Excel-specific behaviour is unverified. Functions used: COUNTIF, COUNTIFS, AVERAGEIFS, SUMPRODUCT, SUM, INDEX, MATCH, LARGE, LN, IF, AND, ABS, MAX, ROUND, INT, MIN (no `_xlfn` functions). The workbook was built and recalculated in a sandbox, not on a GitHub-hosted runner, and is not attached to a GitHub release (`release-package.md`).

## Rebuild
```bash
# from apps/retentionlab, with openpyxl==3.1.5 (requirements-artifacts.txt) and LibreOffice (soffice) installed
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi
../../.venv/bin/python artifacts/build_workbook.py --recalc
```

## Limits
* The test table is the held-out population of the full world (1,513 rows, 442 accounts); rows are correlated, so no interval is given.
* The ranking cells evaluate the rank only inside the 25 highest probabilities of a model, exact for K <= 25.
* World-level figures (1,241 scored accounts, per-cutoff counts of 2,400 accounts, the published drift series, the purge counts) are TYPED from the published files; the cohort figures are typed from the loaded tables.
* The reference columns of `Checks` are pasted from `artifacts/analysis-results.json`; `tests/test_artifacts.py` compares the workbook's recalculated values with a Python recomputation made independently of that file.
* Nothing in the workbook estimates a treatment effect.
