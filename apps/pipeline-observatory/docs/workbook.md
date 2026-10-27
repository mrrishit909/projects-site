# Analyst workbook (P08-ART-05)

`artifacts/pipeline-observatory-analyst-workbook.xlsx` recomputes the Pipeline Observatory headline measures with live spreadsheet formulas over the published synthetic snapshot `po-20261026-20261026` (generator `dataset_hash` `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`, contract v1, code revision `ed7eb5a`, as-of 2026-10-05T00:00:00Z). **Synthetic data only**; nothing is a claim about a real platform and no benefit is claimed.
Observed results (this one draw), constructed relationships (the generator's designed ones) and hypothetical benefits (not claimed) are kept apart; every figure carries its scope.
The decision it supports: **is this dataset safe, complete and fresh enough to publish?** `Publish decision` applies the printed rule of the site to the figures and says so in one cell.

## How to read it without installing anything
Open the `.xlsx` in any spreadsheet application (or read this page): the cached values are stored in the file. `Checks!B2` is TRUE when every figure agrees with the Python domain, the manifest's record and the golden hand answer. `Publish decision!B10` carries the verdict, now: **PUBLISH WITH A STATED EXCEPTION: 1 source is silent while the jobs stay green, the first is src-refunds**. Nothing needs installing to read either.

## Sheets
| Sheet | What it holds |
|---|---|
| `Read me` | what the workbook is, the decision, the scopes, how to use it, the recalculation status |
| `Controls` | the inputs: `Controls!B3` (how many declared cadences make a source silent; 1, 2, 3 or 4; default 2), `Controls!B4` (the as-of), `Controls!B5` (the scope of the Selected rates: `complete world` or `sample`); the check cell and the verdict repeated |
| `Checks` | `Checks!B2` = AND of eleven checks against the domain, the manifest's record and the golden hand answer |
| `Publish decision` | the verdict by the printed rule; the run funnel; failed runs by kind with the mean recovery minutes; task and attempt success; incidents; backfill coverage; retry-after |
| `Source health` | per source: counts and rates (SUMIFS over the batches), ingestion age (MAXIFS over the checkpoints), freshness (from the recorded latest event), over-target and silent flags, completeness, and a check against the domain |
| `Sample scope` | the sample's own classification beside the world's for the same batches: the sample overstates accepted and understates duplicates |
| `Golden case` | the ten golden rows classified by formula and every known-answer figure against the hand answer |
| `Assumptions` | the read-this-first limits (A-01..A-07, W-01..W-05) |
| `Sources`, `Batches`, `Checkpoints`, `Runs`, `Incidents`, `Backfills`, `Retries`, `Fetch log` | typed inputs from the published files (blue), with the formula columns (black): the stage and failure kind of each of 1,343 runs, recovery minutes, retry slack |
| `Domain reference` | PASTED values: the Python domain over the published files and the manifest's recorded statistics, for the check columns only |
| `SQL results (pasted)` | PASTED headline result sets of `data/sql/analysis/run_all.py` |

## What the formulas do (live)
* **Per source** (complete world): received, accepted, duplicate, quarantined, deleted over the committed batches; rejection rate 0.010752 and duplicate rate 0.052655 overall (`Source health` row 10); the ingestion age as the as-of minus the latest checkpoint; the freshness as the as-of minus the **recorded** latest accepted event; `over_target` against the declared target; `silent` against `Controls!B3` cadences; completeness against the declared expectation (`src-refunds` 0.945541, the lowest).
* **Per run** (complete world): the gate decision (`not_reached`, `allowed`, `blocked`), the stage and the failure kind from the typed check counts; the funnel 1,343 / 1,328 / 1,318 / 10 / 15; failed runs by kind (freshness 5, relationships 4, residual 1, ingest 3, transform 9, gate_infra 3).
* **Tasks against attempts:** task success 0.995311 and attempt success 0.971622.
* **Incidents:** the 25 verified recovery times as (verified recovery - detection) in whole seconds and minutes to 4 places; mean 60.6827 minutes.
* **Backfills:** coverage 11 of 15 partitions = 0.733333 over the accepted requests; 4 refused partitions beside it.
* **Retry-after:** 49 retries, every one at least as late as its hint (slack 0 to 25 s).
* **Silent source:** `src-refunds` freshness 262378 s against an ingestion age of 17363 s; the declared 7-day target is looser than the silence.
* **Golden case:** 10 received, 8 accepted, 1 duplicate, 1 quarantined (0.100000 each), freshness 52200 s against 42900 s, completeness 0.888889, task success 1.000000 against attempt success 0.800000, residual 0.00, recovery 475.0000 minutes, coverage 0.666667, processing 0.666667.

## How to use the switches
* `Controls!B3` = 1: a source is silent above one declared cadence; `src-orders` (14514 s against a cadence of 14400 s) joins `src-refunds`, two sources are silent and the verdict is still the stated exception (it now counts 2). At 4 the silent count is 1 (262378 s is above four cadences of 21600 s = 86400 s) and the verdict is unchanged. No setting of `B3` makes the verdict `DO NOT PUBLISH`: that needs a blocked latest gate or a source past its declared target, neither of which is true at the as-of.
* `Controls!B5` = `sample`: the Selected rate columns of `Source health` show the 2,000-row sample's rates (duplicate rate 0.012247 for all sources together against the pipeline's 0.052655). **The sample's rates are the sample's**; the headline of `Sample scope` follows the switch. `Checks!B2` does not depend on the scope switch and stays TRUE (the tests recalculate under both settings).

## Recalculation status (stated plainly)
openpyxl 3.1.5 (`requirements-artifacts.txt`) writes formulas only; it cannot calculate. The delivered file was opened and recalculated by **LibreOffice 24.2 Calc, headless**, which stores the cached values; `fullCalcOnLoad` is set in the workbook XML so Excel recalculates on open. **Excel itself was NOT run**: nothing here was opened or recalculated by Excel, and `MAXIFS` needs Excel 2019 or later. `tests/test_artifacts.py` (1) proves from the cell contents that every result cell of the formula sheets is a live formula, (2) compares the cached values with the domain recomputed in the test, (3) recalculates copies with LibreOffice under both scope settings and requires the check cell to stay TRUE. The LibreOffice tests skip with a printed reason where `soffice` is missing; the CI workflow installs LibreOffice Calc so they run there.

## Rebuild
```
# from apps/pipeline-observatory, with openpyxl==3.1.5 (requirements-artifacts.txt) and LibreOffice (soffice) installed; artifacts/analysis-results.json must exist (run_all.py)
../../.venv/bin/python artifacts/build_workbook.py --recalc
```

## Limits
* The per-batch counts (the generator's domain run over 40,191 raw rows), the gate and task counts of each run, the recorded latest accepted event of each source, the recovery publication instants and the sample's classification are **typed** from the independent Python side; the spreadsheet cannot classify raw rows. Each is compared with the domain, the manifest or the SQL (`Assumptions` W-02).
* Freshness is **recorded**, not found: the published raw rows are a sample (limits of scope in `sql-analysis.md` section 0).
* No macros, no external links, no credentials.
