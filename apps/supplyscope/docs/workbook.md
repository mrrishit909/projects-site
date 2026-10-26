# Analyst workbook (P03-ART-05)

File: `artifacts/supplyscope-analyst-workbook.xlsx` (built by `artifacts/build_workbook.py` with openpyxl 3.1.5, pinned in `requirements-artifacts.txt`). All data is **synthetic**.
The workbook lets an analyst follow, cell by cell, how the golden fixture of the contract (P03-GOLD-01) becomes on hand 40, on order 30, backorders 10, position 60, raw order 60, order after MOQ 60 and order quantity 72, and why a position of 80 gives no order.

| Sheet | Content |
|---|---|
| `Inputs` | The golden fixture rows (`tests/fixtures/golden/inputs.json`): a parameter block (as-of, window start, reorder point 70, target 120, MOQ 50, pack 24, unit cost 12.50, reserved 0), the 7 inventory movements, the purchase order, its two lines (`pol-001`, and `pol-002` which only the `position_80` state adds), the receipts block (empty in the fixture) and the 2 backorders. Typed blue cells; instants are UTC date serials shown as `yyyy-mm-dd hh:mm:ss`. The column `state_added` on the lines is not a fixture field: it records which fixture state adds the line. |
| `Ledger` | **Live formulas** over `Inputs`: per movement the date, the type rank (receipt 0, sale 1, other 2), the day-order sort key `date x 10 + rank + time/10`, the **as-of filter** (`event_at <= as_of`), the rank in day order, the running stock in **day order** and, beside it, in plain **timestamp order**. Totals: on hand 40, lowest running stock 0 in day order and **-35** in timestamp order (the 2026-03-12 sale stamped 09:00 before the receipt stamped 15:00), flag `ok`, and "6 / 1" movements counted / excluded (`mv-007`, dated 2026-04-02, is after the cutoff). Change `Inputs!B6` (the as-of) and the whole chain follows. |
| `Position` | Live formulas: the open quantity of each order line (ordered minus received by the as-of, confirmed order placed by the as-of), on hand, on order, open backorders, reserved, available and the **position = on hand + on order - backorders** (reserved is not subtracted). Column C is state `golden` (30 on order, position 60), column D state `position_80` (adds `pol-002`, 50 on order, position 80), column B follows the switch `Figures!B3`. |
| `Replenishment` | Live formulas: ROP and target from `Inputs`, the **triggered** switch (`position < ROP`), `raw = target - position`, `after MOQ = MAX(raw, MOQ)`, `order = CEILING(after MOQ, pack)`, packs. Golden: raw 60, MOQ 60, order 72 (3 packs). `position_80`: not triggered, raw, MOQ and order are all 0. |
| `Figures` | The figures side by side: `B3` is the **state switch** (0 golden, 1 position_80); column B follows it, C is always golden, D always position_80; E and F hold the hand-derived expectations typed from `expected.json`; G and H compare (`ROUND(C - E, 6) = 0`); `B20` is TRUE when every figure matches; `B21` reads the chain `40 / 30 / 10 / 60 / 60 / 60 / 72` off column C. Working capital is `on hand x unit cost` = 500. |
| `Assumptions` | D-01..D-06 as they apply, plus the workbook's own limits W-01..W-05. |
| `Snapshot summary` | **Pasted values**, not formulas, from `data/sql/analysis/run_all.py` (query file names in each section title, generator `dataset_hash` in the header): queries 01..09, the golden three-source table, the `reference_metrics.sql` row and the reconciliation count. It goes stale if the data or the queries change. |

Expected results (`expected.json`): golden on hand 40, on order 30, backorders 10, position 60, ROP 70, target 120, raw 60, after MOQ 60, order 72, working capital 500.00; `position_80`: on order 50, position 80, not triggered, raw 0, MOQ 0, order 0.

## Recalculation status (stated plainly)
* **openpyxl cannot calculate.** The builder writes formulas only, so the file it writes first has no cached values.
* **LibreOffice is installed here** (`/usr/bin/soffice`). The build ran `soffice --headless --convert-to xlsx` and the delivered file is that recalculated output: it keeps its formulas and carries LibreOffice-computed cached values. Read with openpyxl `data_only=True`, `Figures` column C is 40 / 30 / 10 / 60 / 70 / 120 / 60 / 60 / 72 / 500, column D is 40 / 50 / 10 / 80 / 70 / 120 / 0 / 0 / 0 / 500, and the check cell `Figures!B20` is `TRUE`.
* **Excel itself was NOT run.** Nothing here was recalculated or opened by Microsoft Excel. The formulas use only functions both engines share (`SUMPRODUCT`, `MAX`, `MIN`, `INT`, `MOD`, `IF`, `AND`, `OR`, `INDEX`, `MATCH`, `CEILING`, `ROUND`, `SUM`, `ISNUMBER`, `SEARCH`). LibreOffice drops the `fullCalcOnLoad` flag, so the builder writes `fullCalcOnLoad="1"` back into `xl/workbook.xml` after the conversion (a test reads it); that Excel honours it was not observed.
* `tests/test_artifacts.py` proves the same independently of any spreadsheet engine and of the delivered cache: it checks that every `Ledger`, `Position`, `Replenishment` and `Figures` result cell is a formula (no hard-coded quantity; the typed exceptions are the switch cell and the expected values), re-derives the chain in Python from the `Inputs` sheet rows (day-order sort key, as-of filter, open lines, MOQ, pack rounding) and compares it with `expected.json` and with the domain's `run_pipeline` in both states, reads the cached values, recalculates a **copy** with LibreOffice as delivered, recalculates another copy with `Figures!B3` flipped to 1 (formulas only, so no cache) to prove the switch is live (selected position 80, order 0), and recalculates copies with the as-of moved (2026-04-03 gives on hand 30 and working capital 375.00; 2026-03-12 10:00 gives on hand 0, flag `NEGATIVE_STOCK` and lowest stock -35, the same figures as `test_sql_reference.py`).

## Rebuild
```sh
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json   # refresh the pasted values first (needs the two prepared databases)
../../.venv/bin/python artifacts/build_workbook.py --recalc                                    # builds, recalculates with soffice, restores fullCalcOnLoad
../../.venv/bin/python -m pytest -q tests/test_artifacts.py
```

## Limits
* One SKU, one location, one supplier, no cost versions: fill rate, stockout days, supplier reliability, forecast accuracy and the cost step are done by the SQL and Python implementations (`sql-analysis.md`), not by these formulas.
* Instants are Excel date serials (UTC, no zone). Comparisons use `SUMPRODUCT` over serials rather than string-built criteria, because a criterion such as `"<="&B5` would round a time like 08:00 to 15 digits and could exclude the row itself.
* A purchase order line has no location; the single product/location of the fixture makes the home-location rule of the SQL unnecessary here.
* `Snapshot summary` is a paste and goes stale if the data or the queries change; its dataset hash is in the header.
