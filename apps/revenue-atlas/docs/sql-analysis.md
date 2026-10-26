# SQL analysis on the seeded snapshot (P01-ART-04)

Everything here is **synthetic**: the generated snapshot `ra-20261026-20261026` (seed 20261026, `dataset_hash` 40f541fc...f444, contract v1.1) seeded into PostgreSQL 16
and settled with the operator commands C02 and C04. The generator **designed in** three relationships (`data/injection-manifest.json`), so these queries show whether the
data contains what was put there, not facts about a business. Every table below is the observed output of the named file; nothing is typed in by hand
(`artifacts/analysis-results.json` holds the same values, produced by the run below).

## Reproduce
```sh
cd apps/revenue-atlas
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<empty database>
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py      # reset, migrate, seed web/public/data, C01 for INJ-01, C02 + C04 for 2,724 shipments (a few minutes)
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json   # 00 views, 01..09, reconciliation; exit 0 only if every check holds
psql "$DATABASE_URL" -f data/sql/analysis/00_line_facts.sql -f data/sql/analysis/01_margin_bridge_by_month.sql   # any file also runs alone in psql
```
Prepared database: seed refused 17 rows (INJ-01: 3 malformed-currency orders and 14 dependants), inserted 2,397 orders, 6,644 shipment lines, 384 returns; C02 and C04 ran for all
2,724 shipments (`prepare_snapshot.py`). The window is the whole snapshot (shipments 2024-10-03..2026-09-25, credits to 2026-09-30); a window has no effect except where stated.

## Method (shared by every query)
`00_line_facts.sql` defines two views and the rules every query inherits: grain = shipment line (D-01); population = costed, not quarantined, order `shipped`/`partially_returned`, FX present;
USD at the shipped-date (credits: credit-date) rate (D-02); region = `customers` version effective at shipped UTC date else `UNASSIGNED` (D-06); discounts from the stored `discount_allocations`;
**freight re-split over the in-population lines** by gross-sales weight with largest remainder (D-04), because that is what the contract metrics do (see query 09 for why the stored
`freight_allocations` are not used); credits and recoverable cost by `credit_date` (D-01a). Ratios are ratios of sums (D-05).

## Reconciliation (the check that makes the rest trustworthy)
Query 01's TOTAL row against `data/sql/reference_totals.sql` (parameters NULL, NULL = no window; it does not read the view or the allocation tables and has its own largest-remainder logic),
and against the Python domain `run_pipeline` over the same JSON files. Both numbers are shown for every field.

| field | bridge_total | reference_totals_sql | equal |
|---|---|---|---|
| gross_sales | 9651206.89 | 9651206.89 | True |
| allocated_discounts | 248870.31 | 248870.31 | True |
| merchandise_credits | 361316.17 | 361316.17 | True |
| net_merchandise_sales | 9041020.42 | 9041020.42 | True |
| cogs | 5680587.06 | 5680587.06 | True |
| gross_profit | 3360433.36 | 3360433.36 | True |
| shipping_cost | 50607.14 | 50607.14 | True |
| contribution_margin | 3309826.22 | 3309826.22 | True |
| regions TOTAL contribution vs bridge | 3309826.22 | 3309826.22 | True |
| python domain run_pipeline (all 8 money fields) | 3309826.22 | 3309826.22 | True |

Bridge total (contribution margin): **3,309,826.22** from the view; **3,309,826.22** from `reference_totals.sql`; **3,309,826.22** from the Python domain. `reference_totals.sql` reports
`allocation_residual` 0.00. A first version of the view that used the stored C04 freight gave contribution 3,310,114.01 (shipping 50,319.35 against 50,607.14); that gap is explained in query 09.

## 01 Margin bridge by month: `01_margin_bridge_by_month.sql`
Steps (D-05): gross - discounts - credits = net; net - COGS = gross profit; gross profit - freight = contribution (no shipping revenue or other variable costs exist in the data).
Shipment-side steps are in the month of `shipped_at`, credits and recoverable cost in the month of `credit_date`.

| period | gross_sales | discounts | credits | net_sales | cogs | gross_profit | freight | contribution | cm_rate |
|---|---|---|---|---|---|---|---|---|---|
| 2024-10 | 261575.89 | 5067.70 | 2357.53 | 254150.66 | 148894.49 | 105256.17 | 1427.36 | 103828.82 | 0.4085 |
| 2024-11 | 374858.99 | 10581.16 | 6096.40 | 358181.43 | 211585.17 | 146596.26 | 1827.94 | 144768.32 | 0.4042 |
| 2024-12 | 384823.58 | 9789.30 | 19839.68 | 355194.60 | 207231.56 | 147963.04 | 2121.75 | 145841.29 | 0.4106 |
| 2025-01 | 396984.20 | 7677.47 | 17532.58 | 371774.15 | 219372.09 | 152402.06 | 2171.32 | 150230.74 | 0.4041 |
| 2025-02 | 389210.70 | 7668.08 | 8450.23 | 373092.39 | 218408.40 | 154683.99 | 2124.24 | 152559.75 | 0.4089 |
| 2025-03 | 300740.38 | 6688.56 | 29852.07 | 264199.75 | 156247.93 | 107951.82 | 1858.88 | 106092.94 | 0.4016 |
| 2025-04 | 282971.47 | 6530.65 | 2931.66 | 273509.16 | 165882.39 | 107626.77 | 1623.55 | 106003.23 | 0.3876 |
| 2025-05 | 333697.12 | 7226.17 | 10452.40 | 316018.55 | 188269.22 | 127749.33 | 1800.37 | 125948.96 | 0.3985 |
| 2025-06 | 393338.19 | 10178.44 | 19882.59 | 363277.15 | 221056.57 | 142220.58 | 2142.34 | 140078.24 | 0.3856 |
| 2025-07 | 374168.86 | 9957.94 | 4511.86 | 359699.05 | 216820.02 | 142879.03 | 1770.39 | 141108.64 | 0.3923 |
| 2025-08 | 391070.60 | 11675.87 | 11265.66 | 368129.07 | 224610.17 | 143518.90 | 2120.16 | 141398.74 | 0.3841 |
| 2025-09 | 453982.64 | 10901.40 | 5922.10 | 437159.14 | 263721.83 | 173437.31 | 2355.34 | 171081.97 | 0.3913 |
| 2025-10 | 409125.91 | 11368.36 | 11167.39 | 386590.17 | 241086.42 | 145503.75 | 2042.09 | 143461.66 | 0.3711 |
| 2025-11 | 401926.70 | 10633.34 | 22630.45 | 368662.91 | 228497.19 | 140165.72 | 2215.52 | 137950.20 | 0.3742 |
| 2025-12 | 566863.84 | 14503.56 | 22759.49 | 529600.79 | 323408.19 | 206192.60 | 3026.47 | 203166.13 | 0.3836 |
| 2026-01 | 470439.07 | 13681.91 | 31927.64 | 424829.52 | 278228.38 | 146601.14 | 2438.28 | 144162.86 | 0.3393 |
| 2026-02 | 404949.28 | 10917.35 | 5668.42 | 388363.51 | 257713.37 | 130650.14 | 2109.97 | 128540.17 | 0.3310 |
| 2026-03 | 467224.52 | 13133.80 | 29966.29 | 424124.43 | 273501.35 | 150623.08 | 2356.08 | 148267.00 | 0.3496 |
| 2026-04 | 319340.34 | 5678.17 | 23927.38 | 289734.79 | 192945.28 | 96789.51 | 1556.15 | 95233.36 | 0.3287 |
| 2026-05 | 475070.19 | 11974.18 | 7804.65 | 455291.37 | 309456.81 | 145834.56 | 2426.62 | 143407.94 | 0.3150 |
| 2026-06 | 448204.50 | 13233.40 | 12992.75 | 421978.34 | 285550.63 | 136427.71 | 2171.65 | 134256.06 | 0.3182 |
| 2026-07 | 440017.93 | 12825.53 | 14647.03 | 412545.37 | 281500.05 | 131045.32 | 2268.84 | 128776.48 | 0.3122 |
| 2026-08 | 466660.92 | 13755.25 | 11768.87 | 441136.80 | 295740.09 | 145396.71 | 2258.95 | 143137.76 | 0.3245 |
| 2026-09 | 443961.07 | 13222.72 | 26961.04 | 403777.30 | 270859.46 | 132917.84 | 2392.88 | 130524.96 | 0.3233 |
| TOTAL | 9651206.89 | 248870.31 | 361316.17 | 9041020.42 | 5680587.06 | 3360433.36 | 50607.14 | 3309826.22 | 0.3661 |
| SUBTOTAL 2024-10..2025-12 | 5715339.08 | 140448.00 | 195652.08 | 5379238.99 | 3235091.64 | 2144147.35 | 30627.71 | 2113519.64 | 0.3929 |
| SUBTOTAL 2026-01..2026-09 | 3935867.82 | 108422.30 | 165664.08 | 3661781.43 | 2445495.42 | 1216286.01 | 19979.42 | 1196306.59 | 0.3267 |

Observed: contribution margin rate runs 0.37-0.41 through 2025-12, steps down to 0.3393 in 2026-01 and stays at 0.31-0.35. The two subtotals (2024-10..2025-12 against 2026-01..2026-09) give
0.3929 and 0.3267, a drop of 6.62 percentage points.

## 02 Contribution by region with UNASSIGNED: `02_contribution_by_region.sql`

| region_id | shipment_lines | gross_sales | net_sales | contribution | cm_rate |
|---|---|---|---|---|---|
| UNASSIGNED | 8 | 2503.37 | 2411.97 | 961.43 | 0.3986 |
| reg-east | 1192 | 1232751.95 | 1159426.95 | 423813.87 | 0.3655 |
| reg-north | 2287 | 4415286.57 | 4112856.72 | 1496108.16 | 0.3638 |
| reg-south | 2014 | 3259116.50 | 3079326.90 | 1141427.20 | 0.3707 |
| reg-west | 1087 | 741548.51 | 686997.89 | 247515.56 | 0.3603 |
| TOTAL | 6588 | 9651206.89 | 9041020.42 | 3309826.22 | 0.3661 |

Observed: the five rows (UNASSIGNED included, 8 lines) add to the TOTAL, which equals the bridge TOTAL (3,309,826.22). The reconciliation table checks that equality in code. The four regions' margin rates sit between 0.3603 (reg-west) and 0.3707 (reg-south) over the whole period, so the whole-period regional view does not isolate the decline.

## 03 Discount rate by region, before and after 2026-03: `03_discount_rate_by_region_before_after_2026_03.sql`
Discount rate = allocated discounts / gross sales; before = shipped before 2026-03-01, after = from 2026-03-01. `extra_discount_usd` = gross after x (rate after - rate before).

| region | rate_before | rate_after | delta_pp | gross_before | gross_after | extra_discount_usd |
|---|---|---|---|---|---|---|
| UNASSIGNED | 0.0092 |  |  | 2503.37 |  |  |
| reg-east | 0.0263 | 0.0251 | -0.11 | 862711.54 | 370040.40 | -416.37 |
| reg-north | 0.0252 | 0.0260 | 0.08 | 2860569.01 | 1554717.56 | 1288.97 |
| reg-south | 0.0242 | 0.0238 | -0.04 | 2335322.94 | 923793.56 | -383.50 |
| reg-west | 0.0263 | 0.0574 | 3.11 | 529620.56 | 211927.95 | 6592.14 |
| ALL REGIONS | 0.0250 | 0.0274 | 0.23 | 6590727.43 | 3060479.47 | 7181.47 |

Observed: reg-west moves from 0.0263 to 0.0574 (+3.11 pp); the other regions move by -0.11 to +0.08 pp. At the 2026-03 break reg-west has 211,927.95 of gross sales after the change, so the extra discount dollars are 6,592.14. UNASSIGNED has shipments only before the break.

## 04 Fixtures cost against price by month: `04_fixtures_cost_vs_price_by_month.sql`
Unit price = gross / units, unit cost = COGS before returns / units (both USD); `cost_to_price` is their ratio, `other_cost_to_price` the same for the five other categories.
`extra_cost_usd` = fixtures COGS - fixtures gross x (cost_to_price of 2024-10..2025-12).

| month | fixtures_units | fixtures_unit_price | fixtures_unit_cost | cost_to_price | other_cost_to_price | extra_cost_usd |
|---|---|---|---|---|---|---|
| 2024-10 | 712 | 127.69 | 74.22 | 0.5813 | 0.5711 |  |
| 2024-11 | 728 | 143.18 | 82.33 | 0.5750 | 0.5742 |  |
| 2024-12 | 624 | 189.94 | 107.55 | 0.5662 | 0.5704 |  |
| 2025-01 | 830 | 157.64 | 92.27 | 0.5853 | 0.5741 |  |
| 2025-02 | 833 | 142.66 | 83.74 | 0.5870 | 0.5679 |  |
| 2025-03 | 696 | 128.94 | 75.90 | 0.5886 | 0.5727 |  |
| 2025-04 | 542 | 115.42 | 69.17 | 0.5993 | 0.5906 |  |
| 2025-05 | 595 | 144.19 | 86.60 | 0.6006 | 0.5767 |  |
| 2025-06 | 1118 | 126.51 | 75.43 | 0.5963 | 0.5877 |  |
| 2025-07 | 742 | 143.15 | 84.56 | 0.5908 | 0.5857 |  |
| 2025-08 | 1101 | 136.98 | 82.60 | 0.6030 | 0.5834 |  |
| 2025-09 | 866 | 135.67 | 81.27 | 0.5990 | 0.5852 |  |
| 2025-10 | 1193 | 146.10 | 88.07 | 0.6028 | 0.6090 |  |
| 2025-11 | 1188 | 144.35 | 87.86 | 0.6086 | 0.5962 |  |
| 2025-12 | 1208 | 162.10 | 98.41 | 0.6071 | 0.5906 |  |
| 2026-01 | 935 | 152.05 | 109.65 | 0.7212 | 0.5991 | 18033.81 |
| 2026-02 | 981 | 161.73 | 116.01 | 0.7173 | 0.5980 | 19517.57 |
| 2026-03 | 1026 | 153.18 | 108.45 | 0.7080 | 0.5862 | 17864.73 |
| 2026-04 | 586 | 169.67 | 124.62 | 0.7345 | 0.6156 | 13940.10 |
| 2026-05 | 1349 | 147.10 | 108.89 | 0.7403 | 0.6066 | 28966.97 |
| 2026-06 | 989 | 161.98 | 118.75 | 0.7331 | 0.6126 | 22239.93 |
| 2026-07 | 1116 | 141.45 | 104.54 | 0.7391 | 0.6176 | 22853.05 |
| 2026-08 | 1093 | 146.72 | 107.85 | 0.7351 | 0.6051 | 22573.03 |
| 2026-09 | 1182 | 138.46 | 100.42 | 0.7252 | 0.6065 | 21427.21 |
| SUM 2026-01..2026-09 | 9257 |  |  | 0.7284 | 0.6048 | 187416.40 |
| SUM 2024-10..2025-12 | 12976 |  |  | 0.5943 | 0.5826 |  |

Observed: fixtures cost_to_price is 0.5662-0.6086 up to 2025-12, jumps to 0.7212 in 2026-01 and stays at 0.7080-0.7403; the other categories stay at 0.5679-0.6176 with a slow drift. Realised unit price moves with product mix (115.42 to 189.94 before 2026-01, 138.46 to 169.67 after) and shows no step of the size of the cost step (unit cost 69.17 to 107.55 before, 100.42 to 124.62 after).
Cost above the earlier ratio totals 187,416.40 over 2026-01..2026-09.

## 05 Return rate by segment x category with cohort maturity: `05_return_rate_by_segment_category.sql`
Return rate = returned units / shipped units of the shipment cohort. Credits arrive 5 to 45 days after shipment (manifest `return_credit_delay_days`), so `mature` lines are those shipped on or before
the latest shipment date minus 45 days; `mature_rate` excludes the recent, still-maturing shipments. Top 12 cells by `mature_rate`, then the complement and the total.

| segment | category_id | shipped_units | returned_units | return_rate | mature_units | mature_rate |
|---|---|---|---|---|---|---|
| enterprise | cat-apparel | 13904 | 1197 | 0.0861 | 12449 | 0.0866 |
| smb | cat-office | 1256 | 90 | 0.0717 | 1173 | 0.0665 |
| smb | cat-safety | 1219 | 76 | 0.0623 | 1121 | 0.0633 |
| mid_market | cat-safety | 3673 | 181 | 0.0493 | 3355 | 0.0539 |
| enterprise | cat-office | 15810 | 825 | 0.0522 | 14539 | 0.0508 |
| mid_market | cat-fixtures | 4528 | 193 | 0.0426 | 4158 | 0.0464 |
| smb | cat-packaging | 4669 | 204 | 0.0437 | 4338 | 0.0415 |
| mid_market | cat-packaging | 16004 | 614 | 0.0384 | 14825 | 0.0414 |
| enterprise | cat-packaging | 54467 | 1897 | 0.0348 | 51010 | 0.0372 |
| mid_market | cat-apparel | 3725 | 126 | 0.0338 | 3419 | 0.0369 |
| enterprise | cat-tools | 13448 | 488 | 0.0363 | 12680 | 0.0356 |
| smb | cat-fixtures | 1320 | 45 | 0.0341 | 1242 | 0.0354 |
| ALL OTHER | all other cells | 158897 | 5691 | 0.0358 | 147560 | 0.0368 |
| ALL | all cells | 172801 | 6888 | 0.0399 | 160009 | 0.0407 |

Observed: enterprise x cat-apparel has the highest rate (0.0861 all lines, 0.0866 mature) against 0.0358 / 0.0368 for all other cells together, about 2.4x. The generator designed 3x on the per-line probability (0.156 against 0.052); by units the ratio is smaller.
Maturity matters little here: mature rates differ from all-cohort rates by at most 0.0052 in the printed rows (smb x cat-office 0.0717 against 0.0665).

## 06 Top 10 customers by contribution decline: `06_top10_customers_contribution_decline.sql`
Periods are half-open six-month blocks, A = [2025-10-01, 2026-04-01) and B = [2026-04-01, 2026-10-01); decline = A - B (contribution incl. credits by credit date). Rank by decline descending, ties by
`customer_id` ascending, so the order is deterministic. `pct_of_total_decline` is against the sum over all customers.

| rank | customer_id | customer_name | latest_region | contribution_a | contribution_b | decline | pct_of_total_decline | all_customers_a | all_customers_b |
|---|---|---|---|---|---|---|---|---|---|
| 1 | cust-0017 | Umberfield Foundry Trading Company | reg-south | 105429.60 | 62073.12 | 43356.48 | 33.3 | 905548.02 | 775336.56 |
| 2 | cust-0009 | Fenwick Meadow Fabrication Ltd | reg-south | 85987.98 | 48497.24 | 37490.74 | 28.8 | 905548.02 | 775336.56 |
| 3 | cust-0007 | Northern Territories Mining, Forestry and Heavy Equipment Contractors Purchasing Consortium Limited | reg-north | 92749.95 | 63191.30 | 29558.65 | 22.7 | 905548.02 | 775336.56 |
| 4 | cust-0032 | International Association of Municipal Facilities Maintenance and Public Works Procurement Cooperatives | reg-south | 20779.38 | 10012.57 | 10766.80 | 8.3 | 905548.02 | 775336.56 |
| 5 | cust-0039 | Moorfield Lakeside Works Partners | reg-north | 24448.14 | 15388.62 | 9059.52 | 7.0 | 905548.02 | 775336.56 |
| 6 | cust-0048 | Fenwick Lakeside Fabrication Ltd | reg-south | 22939.22 | 15619.74 | 7319.48 | 5.6 | 905548.02 | 775336.56 |
| 7 | cust-0024 | Consolidated Regional Wholesale Distribution and Industrial Supply Partnership of the Great Lakes | reg-west | 12190.51 | 5448.58 | 6741.93 | 5.2 | 905548.02 | 775336.56 |
| 8 | cust-0036 | Thornley Foundry Trading Company | reg-east | 76856.45 | 70325.00 | 6531.45 | 5.0 | 905548.02 | 775336.56 |
| 9 | cust-0005 | Valewood Harbor Works Partners | reg-west | 5551.27 | 443.61 | 5107.66 | 3.9 | 905548.02 | 775336.56 |
| 10 | cust-0040 | Umberfield Foundry Logistics Corp | reg-east | 3913.92 | -88.11 | 4002.03 | 3.1 | 905548.02 | 775336.56 |

Observed: all customers fall from 905,835.80 (A) to 775,336.56 (B), a decline of 130,499.24; the top three (cust-0017, cust-0009, cust-0007) account for 110,433.59 of it (84.6 %), the top ten for 160,061.32 (122.7 %), because the other 38 customer ids net to a rise. This is an absolute-dollar decline that mixes volume and margin; it does not say why those customers fell.

## 07 Quarantine and rejection reasons: `07_quarantine_reasons.sql`

| kind | entity | reason_code | records | shipments | gross_usd_at_stake |
|---|---|---|---|---|---|
| rejected | order_lines | CURRENCY_NOT_ISO4217 | 5 |  |  |
| rejected | orders | CURRENCY_NOT_ISO4217 | 3 |  |  |
| rejected | returns | CURRENCY_NOT_ISO4217 | 1 |  |  |
| rejected | shipment_lines | CURRENCY_NOT_ISO4217 | 5 |  |  |
| rejected | shipments | CURRENCY_NOT_ISO4217 | 3 |  |  |
| quarantined | shipment_lines | COST_VERSION_AMBIGUOUS | 31 | 30 | 42742.55 |
| quarantined | shipment_lines | COST_VERSION_MISSING | 15 | 15 | 5205.01 |
| quarantined | shipment_lines | FX_RATE_MISSING | 10 | 5 |  |

Observed: 31 + 15 + 10 shipment lines are quarantined; they match the injection manifest (INJ-02: 31 lines in 2025-10; INJ-03: 15 lines in 2026-02; INJ-04: 5 shipments on the two missing FX dates, 10 lines).
17 rows from the three malformed-currency orders (INJ-01) are rejected with `CURRENCY_NOT_ISO4217`. `gross_usd_at_stake` is NULL for FX lines because no USD value exists without a rate.

## 08 Allocation residual check: `08_allocation_residual_check.sql`
Freight residual per shipment = `shipping_cost` - sum of its stored `freight_allocations`; discount residual per order line = `round(discount x shipped/ordered, 2)` - sum of its stored `discount_allocations`.

| shipments_checked | shipments_nonzero_residual | freight_abs_residual | shipments_without_allocation | order_lines_checked | order_lines_nonzero_residual | discount_abs_residual | failures |
|---|---|---|---|---|---|---|---|
| 2724 | 0 | 0.000000 | 0 | 6152 | 0 | 0.000000 | 0 |

Observed: 0 failures in 2,724 shipments and 6,152 order lines; `failures` = 0 is also a condition of `run_all.py` exiting 0. `reference_totals.sql` independently reports `allocation_residual` 0.00 for the population.
Scope: this checks the *stored* allocations on the settled seed path (one C04 per shipment); reviewer finding R-02 (a line shipped across several C04 calls drifts by cents) is a different path and is not exercised.

## 09 Stored C04 freight against contract freight (diagnostic, not one of the eight): `09_stored_vs_contract_freight.sql`

| shipments_in_population | partially_quarantined_shipments | contract_freight | stored_c04_freight_on_kept_lines | gap | stored_on_quarantined_siblings |
|---|---|---|---|---|---|
| 2715 | 41 | 50607.14 | 50319.35 | 287.78 | 287.78 |

Observed: C04 splits a shipment's freight over **all** of its lines, including lines C02 quarantined; the contract metrics split it over the in-population lines only. In 41 partially quarantined shipments
287.78 of freight sits on quarantined lines, so summing the stored `freight_allocations` of population lines gives 50,319.35 shipping cost and 3,310,114.01 contribution, against 50,607.14 and 3,309,826.22.
The API/metrics path is unaffected (it uses the pipeline); anyone aggregating the stored allocation table directly would be off by that amount. Recorded as an open finding.

## Derived arithmetic used by the executive memo
Computed in `run_all.py` from the printed outputs of queries 01, 03 and 04 only: contribution lost to the rate drop = (rate before - rate after) x net sales after.

| cm_rate_pre | cm_rate_post | rate_drop_pp | contribution_lost_to_rate_drop_usd | fixtures_extra_cost_usd | west_extra_discount_usd | fixtures_share_of_lost | west_share_of_lost |
|---|---|---|---|---|---|---|---|
| 0.3929 | 0.3267 | 6.62 | 242418.66 | 187416.40 | 6592.14 | 77.3 | 2.7 |

Limits: counterfactuals hold a ratio at its earlier level and ignore mix and volume; they are screening arithmetic, not the scenario engine (C07/C08 are not implemented in the backend; D-07 does not rescale costs).
