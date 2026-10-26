# BI package: Power BI semantic model design (P01-ART-06)

**No `.pbix` was produced, opened or tested.** This file is a design: a star schema, relationships, DAX measures and Power Query steps written from the contract
(`contracts.md` D-01..D-05) and the documented shape of the published files. None of the DAX or M below has been executed; Power BI Desktop is not available in this
environment. Verification steps that need Desktop are listed at the end as open. All data is **synthetic** (snapshot `ra-20261026-20261026`).

## 1. Star schema

Grain of the main fact is the **shipment line** (`shipment_line_id`, D-01). Credits are recognised on `credit_date` (D-01a), so returns are a second fact at return grain that shares the dimensions.

| Table | Grain | Key | Columns (beyond key) | Built from |
|---|---|---|---|---|
| `fact_shipment_line` | shipment line (6,588 rows in the population) | `shipment_line_id` | `shipped_date`, `customer_version_key`, `product_id`, `region_id`, `currency`, `cost_version_id`, `shipped_quantity`, `order_id`, `gross_usd`, `discount_usd`, `cogs_gross_usd`, `freight_usd` | site "Export full population" CSV (contract-computed, USD, population only) |
| `fact_return` | return (380 rows in the population; 384 in `returns`, 4 sit on quarantined lines) | `return_id` | `credit_date`, `shipment_line_id`, `customer_version_key`, `product_id`, `region_id`, `returned_quantity`, `credit_usd`, `recoverable_cost_usd` | `returns.json` + `exchange_rates.json` + fact line cost |
| `dim_customer` | customer **version** (type-2) | `customer_version_key` = `customer_id|effective_from` | `customer_id`, `customer_name`, `segment`, `region_id`, `effective_from`, `effective_to` | `customers.json` |
| `dim_product` | product | `product_id` | `sku`, `category_id`, `unit_of_measure`, `active` | `products.json` |
| `dim_region` | region | `region_id` | name; includes the explicit row `UNASSIGNED` (D-06) | distinct `region_id` of `customers.json` + `UNASSIGNED` |
| `dim_date` | day (2024-10-01..2026-09-30 plus a margin) | `date` | `year`, `month`, `month_start`, `quarter` | generated |
| `dim_currency` | order/shipment currency | `currency` | `reporting_currency` (USD) | distinct `exchange_rates.json` currencies + USD |
| `dim_cost_version` | cost version | `cost_version_id` | `product_id`, `unit_cost`, `valid_from`, `valid_to` | `cost_versions.json` |

Why `freight_usd` and `discount_usd` are loaded rather than recomputed in M: D-04 largest-remainder allocation over lines is a window computation; the contract implementation
(TypeScript in the site, the same as Python and SQL) already did it and the export carries the result per line. Recomputing it in M would create a fourth implementation to verify.

## 2. Relationships

| From (many) | To (one) | Cardinality / direction | Active |
|---|---|---|---|
| `fact_shipment_line[customer_version_key]` | `dim_customer[customer_version_key]` | many-to-one, single | yes |
| `fact_shipment_line[product_id]` | `dim_product[product_id]` | many-to-one, single | yes |
| `fact_shipment_line[region_id]` | `dim_region[region_id]` | many-to-one, single | yes |
| `fact_shipment_line[shipped_date]` | `dim_date[date]` | many-to-one, single | yes |
| `fact_shipment_line[currency]` | `dim_currency[currency]` | many-to-one, single | yes |
| `fact_shipment_line[cost_version_id]` | `dim_cost_version[cost_version_id]` | many-to-one, single | yes |
| `fact_return[customer_version_key]`, `[product_id]`, `[region_id]` | the same three dimensions | many-to-one, single | yes |
| `fact_return[credit_date]` | `dim_date[date]` | many-to-one, single | yes (a second fact may use the same dimension) |

`fact_return` has no relationship to `fact_shipment_line`: it carries its own copies of the dimension keys (taken from the returned line at load time), so a date slicer filters shipments by
`shipped_date` and credits by `credit_date` exactly as D-01a says. `region_id` on both facts is the region **as of the shipped date** (type-2), so `dim_customer[region_id]` must not be used for regional
views; use `dim_region`. No many-to-many relationships and no bi-directional filters.

## 3. DAX measures

Twelve contract measures (D-05) and hidden helpers. Money is USD. Every ratio uses `DIVIDE(numerator, denominator, BLANK())`, so a zero denominator returns BLANK (the contract's null), never 0 and never an
error. Ratios are computed from aggregated numerator and denominator, never averaged over rows (P01-MET-07-R04). Display: money `#,##0.00`, rates `0.000000`.

```dax
-- hidden helpers
[Shipping Revenue]        = 0   -- no source field in the dataset; kept so the contribution formula matches D-05
[Other Variable Costs]    = 0   -- no source field in the dataset
[COGS Before Returns]     = SUM ( fact_shipment_line[cogs_gross_usd] )
[Recoverable Return Cost] = SUM ( fact_return[recoverable_cost_usd] )
[Shipped Units]           = SUM ( fact_shipment_line[shipped_quantity] )
[Returned Units]          = SUM ( fact_return[returned_quantity] )
[Eligible Orders]         = DISTINCTCOUNT ( fact_shipment_line[order_id] )

-- the 12 contract measures
[1 Gross Sales]               = SUM ( fact_shipment_line[gross_usd] )
[2 Allocated Discounts]       = SUM ( fact_shipment_line[discount_usd] )
[3 Merchandise Credits]       = SUM ( fact_return[credit_usd] )
[4 Net Merchandise Sales]     = [1 Gross Sales] - [2 Allocated Discounts] - [3 Merchandise Credits]
[5 COGS]                      = [COGS Before Returns] - [Recoverable Return Cost]
[6 Gross Profit]              = [4 Net Merchandise Sales] - [5 COGS]
[7 Shipping Cost]             = SUM ( fact_shipment_line[freight_usd] )
[8 Contribution Margin]       = [6 Gross Profit] + [Shipping Revenue] - [7 Shipping Cost] - [Other Variable Costs]
[9 Contribution Margin Rate]  = DIVIDE ( [8 Contribution Margin], [4 Net Merchandise Sales] + [Shipping Revenue], BLANK () )
[10 Discount Rate]            = DIVIDE ( [2 Allocated Discounts], [1 Gross Sales], BLANK () )
[11 Return Rate]              = DIVIDE ( [Returned Units], [Shipped Units], BLANK () )
[12 Average Order Value]      = DIVIDE ( [4 Net Merchandise Sales], [Eligible Orders], BLANK () )
```

Notes: `[Eligible Orders]` is the distinct count of orders with a population line (D-05 "distinct orders with eligible lines"). `[11 Return Rate]` follows D-01a (returned units by credit date over shipped units by
shipped date) and can exceed what a pure cohort view gives for a window; it equals the cohort rate over the whole snapshot. Year-over-year and quota attainment are not in the twelve: quota attainment
has no calculation in the slice (ledger P01-TEST-08 blocked); year-over-year would be `DIVIDE ( [x] - [x PY], ABS ( [x PY] ), BLANK () )` over `dim_date`.

## 4. Power Query steps (not executed)

Inputs: the published entity files `data/<entity>.json` (shape `{ "entity", "dataset_version", "rows": [ ... ] }`, listed by `manifest.json`) and one CSV exported from the site's **Export full population**
button (a `#`-prefixed provenance header block of 11 lines, then the header row `Shipped at (UTC),Order,Line,Customer,Product,Region,Qty,Unit price,Gross,Discount,Cost version,Unit cost,COGS,Freight,Credit,FX rate,Currency`).
Parameter `DataRoot` = the site's `data/` URL or a local folder; parameter `ExportCsv` = path of the CSV.

```m
// JSON entity loader (one query per entity: customers, products, order_lines, orders, shipment_lines, returns, cost_versions, exchange_rates)
let Src = Json.Document(Web.Contents(DataRoot & "/customers.json")),
    T   = Table.FromRecords(Src[rows])
in  T

// fx_line: line facts from the export; keep line id as the key, drop the descriptive and per-line credit columns
let Raw  = Csv.Document(File.Contents(ExportCsv), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Body = Table.Skip(Raw, each Text.StartsWith([Column1], "#")),                 // 11 header lines
    Hdr  = Table.PromoteHeaders(Body),
    Typ  = Table.TransformColumnTypes(Hdr, {{"Qty", Int64.Type}, {"Gross", type number}, {"Discount", type number},
                                            {"COGS", type number}, {"Freight", type number}, {"Unit cost", type number}}, "en-US"),
    Ren  = Table.RenameColumns(Typ, {{"Line","shipment_line_id"},{"Order","order_id"},{"Region","region_id"},{"Qty","shipped_quantity"},
                                     {"Gross","gross_usd"},{"Discount","discount_usd"},{"COGS","cogs_gross_usd"},
                                     {"Freight","freight_usd"},{"Cost version","cost_version_id"},{"Currency","currency"}}),
    Date = Table.AddColumn(Ren, "shipped_date", each Date.From(DateTimeZone.From(Text.Replace([#"Shipped at (UTC)"], " ", "T") & ":00Z")), type date)
in  Date
```
Then, in `fact_shipment_line`:
1. Merge `fx_line` with `shipment_lines` on `shipment_line_id` to get `line_id`; merge with `order_lines` on `line_id` for `product_id`; merge with `orders` on `order_id` for `customer_id`.
2. `customer_version_key`: for each row, from `customers` filter `customer_id` equal and `effective_from <= shipped_date`, take the maximum `effective_from`, build `customer_id & "|" & Date.ToText(effective_from, "yyyy-MM-dd")`; rows with no version get `customer_id & "|none"` and a matching dummy row in `dim_customer` with region `UNASSIGNED`.
3. Remove `Customer`, `Product`, `Unit price`, `Credit`, `FX rate`, `Shipped at (UTC)`; the CSV's `Credit` column is per line and is deliberately not used (credits come from `fact_return` by credit date).

`fact_return`: `returns` merged with `shipment_lines` -> `order_lines` -> `orders` to get `currency` and keys; merged with `exchange_rates` on `(currency, credit_date = rate_date, reporting_currency = "USD")`; `credit_usd = credit_amount * rate` (rate 1 when the order currency is USD, never defaulted otherwise: a null rate row is removed and counted); merged with `fact_shipment_line` (`unit_cost`) for `recoverable_cost_usd = returned_quantity * unit_cost`; an inner join to `fact_shipment_line` drops returns of excluded (quarantined) lines.
`dim_customer`: `customers`, add `effective_to` as the next `effective_from` of the same customer (null for the last). `dim_date`: `List.Dates` over the range. `dim_cost_version`, `dim_product`, `dim_currency`: direct loads.

## 5. Desktop verification still to do (open)
1. Load the model, confirm the relationship list in section 2 and that no ambiguity warning appears.
2. With no filters, the measures must show the whole-snapshot totals (from `sql-analysis.md` query 01 and the Python `run_pipeline` metrics in `artifacts/analysis-results.json`): gross 9,651,206.89; discounts 248,870.31; credits 361,316.17; net 9,041,020.42; COGS 5,680,587.06; gross profit 3,360,433.36; shipping cost 50,607.14; contribution 3,309,826.22; CM rate 0.366090; discount rate 0.025786; return rate 0.039861; average order value 3,789.20; eligible orders 2,386; population lines 6,588.
3. Load the golden dataset (`?dataset=golden` export) and confirm 250.00 / 25.00 / 90.00 (after the return) / 135.00 / 80.00 / 55.00 / 15.00 / 40.00.
4. Slice by `dim_region`: the `UNASSIGNED` row must appear and the five rows must add to the total (query 02: 8 lines, contribution 961.43).
5. Slice by month: credits must move with `credit_date`, not `shipped_date` (query 01 monthly credits column).
6. Check blank (not 0, not error) rate measures on an empty selection.
7. Record the Desktop version, the `.pbix` hash and the checks in the verification ledger; until then P01-ART-06 is a design only.
