# Analyst workbook (P04-ART-05)

File: `artifacts/serviceflow-analyst-workbook.xlsx` (built by `artifacts/build_workbook.py` with openpyxl 3.1.5, pinned in `requirements-artifacts.txt`). All data is **synthetic**: the published snapshot `sf-20261026-20261026`
(seed 20261026, generator `dataset_hash` `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4`, contract v1, code revision `43de7f8`). Everything in the workbook is OBSERVED in that synthetic history; no simulation result and no staffing benefit is in it.

The workbook lets an analyst follow, cell by cell, how 3,817 accepted tickets, 4,976 service intervals, 1,020 shifts and 2,147 surveys become the headline metrics of the contract, and how they move between the whole twelve weeks, the **training weeks (1-8)** and the **holdout weeks (9-12)**: one switch cell, `Scenario!B3`, takes `full`, `training` or `holdout`.
It also reproduces the known answer of the golden fixture (three tickets, 10-minute service, FIFO) with formulas.

**How to read it without installing anything:** open the `.xlsx` in any spreadsheet application (the delivered file already carries values), or read the table below and `Expected results`.

| Sheet | Content |
|---|---|
| `Read me` | Purpose, how to use the switch, observed-against-simulated statement, provenance, recalculation status. |
| `Scenario` | The **switch** `B3` (data validation: full / training / holdout), the window table (start and end as UTC epoch seconds, half-open `[start, end)`), the selected window `B11:B14`, the SLA targets (P1 15 / 240, P2 60 / 1440, P3 240 / 4320 minutes), the channels that can abandon (chat, phone) and the positive-CSAT threshold (4). Blue cells are typed inputs. |
| `Metrics` | **Live formulas** for 26 figures of the selected window: arrivals, completions, rates, mean and P90 of first response, wait to first service and resolution, handling, SLA within / eligible / compliance for both targets, backlog and open overdue at the window end, staffed available time and whole-shift time, occupancy, abandonment, survey invitation / response rate and CSAT. Column E is the Python domain's figure for the same window (pasted), F the tolerance (half a unit of the last place), G the check; `E3` is TRUE when every check is TRUE. |
| `Domain reference` | **Pasted values** (not formulas): `compute_metrics` of the Python domain over `web/public/data` for the three windows, plus the nearest-rank P90 of wait and resolution (additions beyond the 28 published keys) and the backlog at the window end. Read only by the check column of `Metrics`. |
| `Hour of week` | The 7 x 24 grid of arrivals by weekday and UTC hour for the selected window (`COUNTIFS` over `Tickets`), the Monday 09:00-11:00 UTC total (238 arrivals in the full window, 144 training, 94 holdout) and a check against query 01 of `sql-analysis.md`. |
| `Queue by priority` | Arrivals, mean first response, mean wait to first service and first-response compliance for the nine queue x priority cells of the selected window (final queue); the expected columns (typed from query 02) and the check apply to the full window only. |
| `Golden case` | The known answer as formulas: starts 0 / 10 / 20, waits 0 / 10 / 20, mean wait 10, last completion 30, handling 30, mean first response 10, each beside the value of `expected.json` (P04-GOLD-01). Independent of every other sheet. |
| `Assumptions` | D-01..D-09 as they apply and the workbook's own limits W-01..W-07. |
| `Tickets` | One row per accepted ticket: typed per-ticket instants (UTC epoch seconds: created, first human reply, first service, final resolution, abandonment), reopen and transfer counts, then 15 formula columns (window flags, first response / wait / resolution in minutes, targets, within-target flags, open and overdue at the window end, can-abandon, weekday, hour). |
| `Intervals` | One row per service interval (ticket, agent, start, end) and the formula for its minutes inside the window. |
| `Shifts` | One row per shift (start, end, declared break, recorded break) and the formulas for staffed available minutes in the window (D-05) and for the whole shift net of the declared break. |
| `Surveys` | One row per survey (invited, score) and formulas for completed-in-window, invited, valid and positive. |
| `SQL results (pasted)` | **Pasted values**, not formulas, from `data/sql/analysis/run_all.py` (query file names in each title, dataset hash and revision in the header): the tables of queries 01 to 08 that matter most, and the reconciliation count. It goes stale if the data or the queries change. |

Expected results (whole twelve weeks, `Metrics!B6:B31` after recalculation; equal to the Python domain and `data/sql/reference_metrics.sql`): arrivals 3,817; completions 3,608; arrival rate 1.893353 per hour; mean first response 28.0046 minutes, P90 44.1500; mean wait to first service 25.5073 (P90 41.5167);
mean resolution 164.5909 (P90 294.5833); handling 189,836.2667 minutes; first response within target 3,437 of 3,616 (0.950498); resolution within target 3,529 of 3,608 (0.978104); backlog and open overdue at the window end 0 and 0; staffed available 447,450.0000 minutes (whole shifts 447,990.0000);
occupancy 0.424263; abandonment 0.118213; survey invitation 0.595067, response 0.349325; CSAT 0.864000. With the switch on `training`: 2,386 arrivals, mean first response 23.4036, occupancy 0.399387, backlog 1; on `holdout`: 1,431 arrivals, mean first response 35.7365, occupancy 0.473609.

## Recalculation status (stated plainly)
* **openpyxl cannot calculate.** The builder writes formulas only, so the file it writes first has no cached values.
* **LibreOffice is installed here** (`/usr/bin/soffice`). The build ran `soffice --headless --convert-to xlsx` and the delivered file is that recalculated output: it keeps its formulas and carries LibreOffice-computed cached values. Read with openpyxl `data_only=True`, `Metrics` column B equals the values above and `Metrics!E3` is `TRUE`.
* **Excel itself was NOT run.** Nothing here was recalculated or opened by Microsoft Excel. The formulas use only functions both engines share (`SUM`, `COUNT`, `COUNTIFS`, `SUMIFS`, `AVERAGE`, `AVERAGEIFS`, `SMALL`, `MAX`, `MIN`, `INT`, `MOD`, `ROUND`, `IF`, `IFERROR`, `AND`, `OR`, `ABS`, `INDEX`, `MATCH`, `ISNUMBER`). LibreOffice drops the `fullCalcOnLoad` flag, so the builder writes `fullCalcOnLoad="1"` back into `xl/workbook.xml` after the conversion (a test reads it); that Excel honours it was not observed.
* `tests/test_artifacts.py` proves the same independently of any spreadsheet engine and of the delivered cache: it checks that every result cell of `Tickets`, `Intervals`, `Shifts`, `Surveys`, `Metrics`, `Hour of week`, `Queue by priority` and `Golden case` is a formula (the typed exceptions are the inputs, the tolerances and the expected values),
  reads the cached values and compares them with the **domain recomputed in the test** (not with the pasted column), recalculates a **copy** with LibreOffice as delivered, and recalculates two more copies with `Scenario!B3` set to `training` and to `holdout` (formulas only, so no cache) to prove the switch is live and equals the domain's figures for those windows.

## Rebuild
```sh
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi   # refresh the pasted values first (creates and drops its scratch databases)
../../.venv/bin/python artifacts/build_workbook.py --recalc                                                          # builds, recalculates with soffice, restores fullCalcOnLoad
../../.venv/bin/python -m pytest -q tests/test_artifacts.py
```

## Limits
* **The event log is not replayed in the spreadsheet.** The first human reply, first service, final resolution, abandonment and service intervals per ticket were derived once in Python (the domain's replay) and typed into `Tickets` and `Intervals` (limit W-02); everything after those instants is a formula. A workbook that replayed 21,893 events would need event-level lookups per ticket.
* **Backlog and open overdue** at the window end read a reopened ticket by its final resolution; this equals the domain for the three windows (checked) but is not a general as-of reconstruction (W-03).
* **Per-group P90, occupancy by agent, the hazard tables, the BI measures and the simulation** are in the SQL investigations, `bi-package.md` and `executive-memo.md`, not in these formulas.
* Instants are integer UTC epoch seconds; comparisons are exact. The check tolerance is half a unit in the last place of the stated precision, not a loosened business tolerance.
* `Domain reference` and `SQL results (pasted)` are pastes and go stale if the data or the queries change; their provenance is in the headers.
