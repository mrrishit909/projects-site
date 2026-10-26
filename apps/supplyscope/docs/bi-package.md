# BI package: Power BI semantic model design (P03-ART-06)

**No `.pbix` was produced, opened or tested.** This file is a design: a star schema, relationships, DAX measures and Power Query steps written from the contract (`contracts.md` D-01..D-06) and the
shape of two CSV exports whose SQL was run here (`data/sql/analysis/bi_fact_movement_day.sql`: 32,880 rows; `bi_fact_draft_order.sql`: 60 rows, both executed with `psql -v ON_ERROR_STOP=1`, exit 0). None of the DAX or M below has
been executed; Power BI Desktop is not available in this environment. The "expected" values in section 5 were computed from those exports in Python and checked against `reference_metrics.sql` and the domain by `data/sql/analysis/run_all.py`, not by Power BI.
Verification steps that need Desktop are listed in section 6 as open. All data is **synthetic** (snapshot `ss-20261026-20261026`, generator hash `5bdabb50eea4b192e3b17e1e5b1a79dc6b26feb4a2b8b78ad094acde9f8bcc8c`).

## 1. Star schema

Two fact grains share the dimensions: the **movement-day** (`fact_movement_day`, one row per SKU x location x UTC date: stock, value, demand and unmet demand) and the **draft order** (`fact_draft_order`, one row per SKU x location x as-of x scenario: the buying plan with its arithmetic).
Stock and money are loaded as stored integers and 2-decimal money, never as averaged ratios, so every ratio divides once at the end like the contract (D-04, D-05).

| Table | Grain | Key | Columns (beyond key) | Built from |
|---|---|---|---|---|
| `fact_movement_day` | SKU x location x date (32,880 rows = 60 pairs x 548 days) | `date_key`, `product_id`, `location_id` | `receipt_units`, `sale_movement_units`, `fulfilled_units`, `unmet_units`, `stockout_flag`, `closing_on_hand_raw`, `closing_on_hand`, `unit_cost_in_force`, `stock_value`, `cogs_value` | CSV of `data/sql/analysis/bi_fact_movement_day.sql` (uses the view `ss_ledger` of `00_ledger_views.sql`) |
| `fact_draft_order` | SKU x location x as-of x scenario (60 rows at the cutoff; the persisted `draft_orders` table is empty in the snapshot) | `date_key`, `product_id`, `location_id`, `scenario_key` | `supplier_id`, `parameter_source`, `on_hand`, `on_order`, `backorders`, `inventory_position`, `reorder_point`, `target_position`, `triggered`, `raw_order`, `minimum_order_quantity`, `order_after_moq`, `pack_size`, `order_quantity`, `unit_cost_in_force`, `order_value` | CSV of `data/sql/analysis/bi_fact_draft_order.sql` (the arithmetic of query 02 for every pair, plus persisted `draft_orders` rows when any exist) |
| `dim_product` | SKU | `product_id` | `sku`, `abc_class`, `pack_size`, `minimum_order_quantity`, `base_unit_cost`, `supplier_id` (from `replenishment_params`, because `products.supplier_id` is NULL, open S-02) | `products.json` merged with `replenishment_params.json` |
| `dim_location` | location | `location_id` | `location_name`, `timezone`, `storage_capacity`, `unmet_policy` (`backlog` at `loc-03`, else `lost_sale`) | `locations.json` |
| `dim_supplier` | supplier | `supplier_id` | `supplier_name`, `calendar_id`, `quoted_lead_days` | `suppliers.json` |
| `dim_date` (calendar) | day | `date_key` (yyyymmdd) | `date`, `year`, `month`, `month_start`, `is_month_end` | generated, 2025-04-01 .. 2026-09-30 |
| `dim_scenario` | policy scenario | `scenario_key` | `scenario_name`, `service_target`, `unmet_policy`, `seed`, `warmup_days`, `replications`; plus the member `none` (parameters of record, no scenario) | `policy_scenarios.json` + one typed row |

## 2. Relationships

| From (many) | To (one) | Cardinality / direction | Active |
|---|---|---|---|
| `fact_movement_day[date_key]` | `dim_date[date_key]` | many-to-one, single | yes |
| `fact_movement_day[product_id]` | `dim_product[product_id]` | many-to-one, single | yes |
| `fact_movement_day[location_id]` | `dim_location[location_id]` | many-to-one, single | yes |
| `fact_draft_order[date_key]` | `dim_date[date_key]` | many-to-one, single | yes (the as-of date) |
| `fact_draft_order[product_id]` | `dim_product[product_id]` | many-to-one, single | yes |
| `fact_draft_order[location_id]` | `dim_location[location_id]` | many-to-one, single | yes |
| `fact_draft_order[scenario_key]` | `dim_scenario[scenario_key]` | many-to-one, single | yes |
| `fact_draft_order[supplier_id]` | `dim_supplier[supplier_id]` | many-to-one, single | no (`USERELATIONSHIP`; the supplier is also reachable through `dim_product`, so an active second path would be ambiguous) |
| `dim_product[supplier_id]` | `dim_supplier[supplier_id]` | many-to-one, single | yes |

No many-to-many relationships and no bi-directional filters. A `date_key` relationship (an integer) is used instead of a datetime so no time zone can shift a day.

## 3. DAX measures

Twelve contract measures (the first block) and optional helpers. Every ratio uses `DIVIDE(numerator, denominator, BLANK())`, so a zero denominator returns BLANK (the contract's null), never 0 and never an error; ratios are computed from aggregated numerators and denominators,
never averaged over rows (D-04). Stock and money are **semi-additive**: they are read on the last selected date (`LASTDATE`), never summed over days; the average inventory value divides the daily sum by the number of days. Rates are formatted `0.000000`, money `0.00`.

```dax
-- the twelve contract measures
Fulfilled Units = SUM ( fact_movement_day[fulfilled_units] )
Unmet Units = SUM ( fact_movement_day[unmet_units] )
Requested Units = [Fulfilled Units] + [Unmet Units]
Fill Rate = DIVIDE ( [Fulfilled Units], [Requested Units], BLANK () )
Stockout SKU Day Share =
    DIVIDE (
        CALCULATE ( COUNTROWS ( fact_movement_day ), fact_movement_day[stockout_flag] = TRUE () ),
        COUNTROWS ( fact_movement_day ),
        BLANK ()
    )
Stockout Calendar Day Share =
    DIVIDE (
        CALCULATE ( DISTINCTCOUNT ( fact_movement_day[date_key] ), fact_movement_day[stockout_flag] = TRUE () ),
        DISTINCTCOUNT ( fact_movement_day[date_key] ),
        BLANK ()
    )
On Hand Units = CALCULATE ( SUM ( fact_movement_day[closing_on_hand] ), LASTDATE ( dim_date[date] ) )
Working Capital = CALCULATE ( SUM ( fact_movement_day[stock_value] ), LASTDATE ( dim_date[date] ) )
Average Inventory Value =
    DIVIDE ( SUM ( fact_movement_day[stock_value] ), DISTINCTCOUNT ( fact_movement_day[date_key] ), BLANK () )
Inventory Turnover =
    DIVIDE (
        SUM ( fact_movement_day[cogs_value] ) * 365,
        SUM ( fact_movement_day[stock_value] ),
        BLANK ()
    )
Inventory Position = CALCULATE ( SUM ( fact_draft_order[inventory_position] ), LASTDATE ( dim_date[date] ) )
Draft Order Units = SUM ( fact_draft_order[order_quantity] )

-- optional, hidden
Draft Order Value = SUM ( fact_draft_order[order_value] )
Triggered Pairs = CALCULATE ( COUNTROWS ( fact_draft_order ), fact_draft_order[triggered] = TRUE () )
Order Units per Triggered Pair = DIVIDE ( [Draft Order Units], [Triggered Pairs], BLANK () )
Days of Cover =
    DIVIDE (
        [On Hand Units],
        DIVIDE ( [Fulfilled Units], DISTINCTCOUNT ( fact_movement_day[date_key] ), BLANK () ),
        BLANK ()
    )
Supplier Draft Order Units =
    CALCULATE ( [Draft Order Units], USERELATIONSHIP ( fact_draft_order[supplier_id], dim_supplier[supplier_id] ) )
```

Notes on the choices:
* **Two stockout-day measures on purpose (reviewer finding R3-01).** The contract's `stockout_days` is distinct calendar dates with any unmet demand over observed days (`Stockout Calendar Day Share`: 290 / 548). The share of SKU x location x day cells (`Stockout SKU Day Share`: 431 / 32,880) is a different, smaller number. A visual must label which one it shows; the two do not reconcile across groups.
* **`Inventory Turnover`** equals annualised cost of goods sold over average inventory value (D-05): `SUM(cogs) * 365 / days` divided by `SUM(stock_value) / days`, the days cancel, so it is `SUM(cogs) * 365 / SUM(stock_value)` over the selected dates.
* **`Inventory Position`** is read at the as-of date of the draft facts (one date in the snapshot, 2026-09-30); with no date selection `LASTDATE` is the last date of the date table, which is that date. Reserved stock is not part of it (P03-TEST-10).
* **`stock_value` and `cogs_value`** are already valued at the cost in force on each day by the SQL export (D-05), so the cost step of 2026-02-01 cannot be averaged away by the model.
* **`Requested Units`** is fulfilled plus unmet (D-06); backlog fills do not appear in `sales` and are not counted twice.

## 4. Power Query (M) steps

```m
// fact_movement_day
let
    Source   = Csv.Document(File.Contents("bi_fact_movement_day.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers  = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Headers, {
                 {"date_key", Int64.Type}, {"receipt_units", Int64.Type}, {"sale_movement_units", Int64.Type},
                 {"fulfilled_units", Int64.Type}, {"unmet_units", Int64.Type}, {"closing_on_hand_raw", Int64.Type},
                 {"closing_on_hand", Int64.Type}, {"unit_cost_in_force", Currency.Type}, {"stock_value", Currency.Type},
                 {"cogs_value", Currency.Type}}, "en-US"),
    // psql prints booleans as t / f
    Flag     = Table.TransformColumns(Typed, {{"stockout_flag", each _ = "t" or _ = "true", type logical}})
in
    Flag

// fact_draft_order: same pattern; order_quantity, inventory_position, reorder_point, target_position, raw_order, order_after_moq,
// pack_size, minimum_order_quantity are Int64; on_hand, on_order, backorders are nullable Int64 (null stays null); order_value and
// unit_cost_in_force are Currency; triggered is logical as above; scenario_key is text ("none" = parameters of record)

// dim_supplier (and likewise dim_location, dim_scenario) from the published JSON: { "entity": ..., "dataset_version": ..., "rows": [ ... ] }
let
    Source = Json.Document(File.Contents("suppliers.json")),
    Rows   = Table.FromRecords(Source[rows]),
    Typed  = Table.TransformColumnTypes(Rows, {{"supplier_id", type text}, {"calendar_id", type text}, {"quoted_lead_days", Int64.Type}})
in
    Typed

// dim_product: products merged with the supplier stated on replenishment_params (products.supplier_id is NULL, S-02)
let
    P = Table.FromRecords(Json.Document(File.Contents("products.json"))[rows]),
    R = Table.FromRecords(Json.Document(File.Contents("replenishment_params.json"))[rows]),
    Supplier = Table.Distinct(Table.SelectColumns(R, {"product_id", "supplier_id"}), {"product_id"}),
    Merged = Table.NestedJoin(Table.RemoveColumns(P, {"supplier_id"}, MissingField.Ignore), {"product_id"}, Supplier, {"product_id"}, "s", JoinKind.LeftOuter),
    Expanded = Table.ExpandTableColumn(Merged, "s", {"supplier_id"}),
    Renamed = Table.RenameColumns(Expanded, {{"unit_cost", "base_unit_cost"}})
in
    Renamed

// dim_date: one row per day of the data range
let
    Days = List.Dates(#date(2025, 4, 1), Duration.Days(#date(2026, 9, 30) - #date(2025, 4, 1)) + 1, #duration(1, 0, 0, 0)),
    T    = Table.FromList(Days, Splitter.SplitByNothing(), {"date"}, null, ExtraValues.Error),
    Typed = Table.TransformColumnTypes(T, {{"date", type date}}),
    Key  = Table.AddColumn(Typed, "date_key", each Date.Year([date]) * 10000 + Date.Month([date]) * 100 + Date.Day([date]), Int64.Type),
    Mon  = Table.AddColumn(Key, "month_start", each Date.StartOfMonth([date]), type date),
    EndM = Table.AddColumn(Mon, "is_month_end", each [date] = Date.EndOfMonth([date]), type logical)
in
    EndM
```
The M above is a design: it has not been run. Open the exports with `UTF-8` encoding, set the data-source privacy level to Organizational or Ignore for a local-files-only model, and keep `Detect data types` off so the typed steps above are authoritative. Export with `psql ... --csv -f data/sql/analysis/bi_fact_movement_day.sql` (booleans come out as `t`/`f`).

## 5. Expected values to check in Desktop (computed outside Power BI)

From the two exports, `run_all.py` (Python exact rationals) and the analysis queries; all-time, no slicer, except the as-of measures (date 2026-09-30). They are the targets the model must hit; **none has been confirmed in Power BI**.

<!-- BEGIN:bi_expected_measures -->
| measure | expected | source |
|---|---|---|
| Fulfilled Units | 36076 | fact_movement_day, sum |
| Unmet Units | 2612 | fact_movement_day, sum |
| Requested Units | 38688 | fulfilled + unmet |
| Fill Rate | 0.932486 | query 03 ALL |
| Stockout SKU Day Share | 0.013108 | 431 / 32880, query 03 ALL |
| Stockout Calendar Day Share | 0.529197 | 290 / 548, reference_metrics.sql stockout_days |
| On Hand Units (2026-09-30) | 1020 | query 01, 2026-09 |
| Working Capital (2026-09-30) | 29090.64 | query 06, 2026-09 end_total |
| Average Inventory Value | 21881.18 | query 06 row ALL |
| Inventory Turnover | 40.487277 | domain supplementary() |
| Inventory Position (2026-09-30) | 1628 | query 02 TOTAL |
| Draft Order Units | 240 | query 02 TOTAL |
| Draft Order Value | 11114.88 | query 02 TOTAL |
| Triggered Pairs | 2 | query 02 |
<!-- END:bi_expected_measures -->

## 6. Remaining Desktop verification (open)
1. Load the two CSVs and the JSON dimensions; confirm no query error and no rows lost (32,880 and 60) and that `unit_cost_in_force` has two decimals.
2. Confirm the nine relationships (eight active, one inactive) and that the model shows no ambiguity warning.
3. Create the measures and tick every row of section 5; select one month on `dim_date` and confirm `Working Capital` equals query 06 `end_total` and `On Hand Units` equals query 01 for that month.
4. Check blank behaviour: filter to a SKU with no sales in the selected window and confirm `Fill Rate` shows blank, not 0 (`Requested Units` is 0).
5. Select scenario `none` on `dim_scenario` and confirm `Draft Order Units` is 240; select a scenario with no draft rows and confirm it is blank or 0 as DAX returns for an empty `SUM`.
6. Confirm a refresh from changed CSVs works and that the report opens without gateway or credential prompts (local files only).
7. Save as `.pbix`, record its sha256 and the Desktop version here. Until then this package is a design.
