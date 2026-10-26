# Analyst workbook (P02-ART-05)

File: `artifacts/onboard-studio-analyst-workbook.xlsx` (built by `artifacts/build_workbook.py` with openpyxl 3.1.5, pinned in `requirements-artifacts.txt`). All data is **synthetic**.
The workbook lets an analyst follow, cell by cell, how the golden case of the contract (P02-GOLD-01: opened Friday 16:00, completed Monday 10:00) becomes calendar 66 h, business 2 h, paused 65 h and active 1 h or 2 h.

| Sheet | Content |
|---|---|
| `Inputs` | The golden fixture rows (`tests/fixtures/golden/inputs.json`, 13 blocks, typed blue cells; instants are UTC date serials shown as `yyyy-mm-dd hh:mm`; booleans kept as the fixture's text `true`). |
| `Calendar` | The ten working intervals of `cal-001` as live links to `Inputs`, with an hours formula per interval (80 working hours in all). `kind` is typed `working` because the fixture rows carry none and D-06 defaults it. |
| `Overlap` | **Live formulas** for the overlap of the case span and of the waiting interval (clipped to the case span, D-06) with each working interval: `MAX(0, MIN(range_end, interval_end) - MAX(range_start, interval_start))` in hours, `ROUND(..., 6)` per row. Totals: business cycle time **2.0000** (Fri 16:00-17:00 + Mon 09:00-10:00) and waiting overlap **1.0000** (Fri 16:30-17:00 + Mon 09:00-09:30); two working intervals touched by each. |
| `Figures` | Calendar 66, business 2, paused 65, paused business overlap 1, active 1 / 2, SLA minutes, SLA met and attainment. The cell `B3` is the **pause-eligible switch** (1 or 0); column B follows it, column C always evaluates "eligible", column D "not eligible". `B4` reads the policy from `sla_rules` in `Inputs` and returns 1. Columns E and F hold the expected values typed from `expected.json`; G, H and `B18` compare them to the live results. |
| `Assumptions` | D-01..D-06 as they apply to the workbook plus four workbook-specific limits (W-01..W-04). |
| `Snapshot summary` | **Pasted values**, not formulas, from `data/sql/analysis/run_all.py` (query file names in each section title, generator `dataset_hash` in the header): queries 01..09, the golden three-source table, the `reference_metrics.sql` row and the reconciliation count. |

Expected results (`expected.json`): pause-eligible calendar 66.0000, business 2.0000, paused 65.0000, paused business overlap 1.0000, active 1.0000, SLA 1.000000; not eligible paused 0.0000, active 2.0000, SLA 1.000000 (120 minutes against 480).

## Recalculation status (stated plainly)
* **openpyxl cannot calculate.** The builder writes formulas only, so the file it writes first has no cached values.
* **LibreOffice 24.2.7.2 is installed here** (`/usr/bin/soffice`). The build ran `soffice --headless --convert-to xlsx` and the delivered file is that recalculated output: it keeps its formulas and carries LibreOffice-computed cached values. Read with openpyxl
  `data_only=True`, `Overlap!E21` is 2, `Overlap!F21` is 1, `Figures` column C is 66 / 2 / 65 / 1 / 1 and column D is 66 / 2 / 0 / 0 / 2, SLA "met" in both, and the check cell `Figures!B18` is `TRUE`.
* **Excel itself was NOT run.** Nothing here was recalculated or opened by Microsoft Excel. The formulas use only functions both engines share (`MAX`, `MIN`, `ROUND`, `SUM`, `SUMIF`, `COUNTIF`, `IF`, `AND`, `ABS`, `SEARCH`, `ISNUMBER`). LibreOffice drops the `fullCalcOnLoad`
  flag, so the builder writes `fullCalcOnLoad="1"` back into `xl/workbook.xml` after the conversion (a test reads it); that Excel honours it was not observed.
* `tests/test_artifacts.py` proves the same independently of any spreadsheet engine and of the delivered cache: it checks that every `Calendar`, `Overlap` and `Figures` result cell is a formula (no hard-coded durations; the typed exceptions are the `kind` column, the three switch cells and the expected values),
  re-derives the chain in exact rationals from the `Inputs` sheet and compares it with `expected.json` and with the domain's `run_pipeline` in both states, reads the cached values, recalculates a **copy** with LibreOffice as delivered, and recalculates another copy with `Figures!B3` flipped to 0
  (formulas only, so no cache) to prove the switch is live: active becomes 2.0000 and paused 0.0000.

## Rebuild
```sh
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json   # refresh the pasted values first (needs the two prepared databases)
../../.venv/bin/python artifacts/build_workbook.py --recalc                                    # builds, recalculates with soffice, restores fullCalcOnLoad
../../.venv/bin/python -m pytest -q tests/test_artifacts.py
```

## Limits
* One case, one waiting interval, no holidays: holiday subtraction, merging of overlapping waits and the population means are done by the SQL and Python implementations (`sql-analysis.md`), not by these formulas.
* Instants are Excel date serials (UTC, no zone); each overlap row is rounded to 6 decimal hours (1 second is 0.000278 hours) to remove binary floating-point noise, totals to 4.
* `Snapshot summary` is a paste and goes stale if the data or the queries change; its dataset hash is in the header.
