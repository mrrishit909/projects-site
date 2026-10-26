# SQL analysis on the seeded snapshot (P03-ART-04)

Everything here is **synthetic**: the generated snapshot `ss-20261026-20261026` (seed 20261026, generator `dataset_hash`
`5bdabb50eea4b192e3b17e1e5b1a79dc6b26feb4a2b8b78ad094acde9f8bcc8c`, contract v1) seeded into PostgreSQL 16 through the domain's `validate_batch`, and the golden fixture seeded into a second database.
The generator **designed in** three relationships (`web/public/data/manifest.json` `designed_relationships`: class A promoted SKUs are censored during stockouts, `sup-03` is late on about 30 % of receipts, `loc-02` is capacity-bound),
so these queries show whether the data contains what was put there, not facts about a business. Every table below is the observed output of the named file, rendered from `artifacts/analysis-results.json`, which `run_all.py` writes from the same run (`artifacts/render_sql_analysis.py` fills the tables; no figure in them is typed).
Contract rules are cited as D-01..D-06 and requirement ids as P03-MET-nn / P03-TEST-nn / P03-GOLD-nn.

## Reproduce
```sh
cd apps/supplyscope
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<empty snapshot database>
export GOLDEN_DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<empty golden database>
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py            # reset + migrate + seed web/public/data (about 11 s)
DATABASE_URL=$GOLDEN_DATABASE_URL ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json   # 00 views, 01..08, golden 09, options, reconciliations; exit 0 only if every check holds
../../.venv/bin/python artifacts/render_sql_analysis.py                                      # refresh the tables below
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f data/sql/analysis/00_ledger_views.sql -f data/sql/analysis/01_stock_position_month_end_by_location.sql   # any file also runs alone in psql after 00
psql -v ON_ERROR_STOP=1 "$GOLDEN_DATABASE_URL" -f data/sql/analysis/09_golden_position_and_order.sql                                              # 09 needs no views
```
Prepared snapshot database: 60 SKU x location pairs, 10,913 movements (of 10,916 generated), 9,475 sales, 1,282 order lines, 1,308 receipts, 70 backorders, 361 lost sales, 6,380 latent-demand days, 56 forecast runs, 2,352 forecast points, 4 rejected rows kept. Cutoff of the snapshot: `2026-09-30T23:59:59Z`; observed window 2025-04-01 .. 2026-09-30 (548 days).

| File | Question | Requirement |
|---|---|---|
| `00_ledger_views.sql` | views `ss_ledger` (running stock in day order and in timestamp order) and `ss_home` (home location of a product) | D-01 |
| `01_stock_position_month_end_by_location.sql` | stock and position at every month-end, by location | P03-MET-01..04, P03-TEST-10 |
| `02_draft_orders_arithmetic.sql` | the draft buying plan with every arithmetic column | P03-GOLD-01, P03-MET-05..08 |
| `03_fill_rate_stockout_by_location_abc.sql` | fill rate and stockout days by location and ABC class | P03-MET-09..10 |
| `04_supplier_on_time_by_month.sql` | supplier on-time rate by supplier and month, no future leakage | P03-MET-11, P03-FLOW-09 |
| `05_censored_vs_latent_class_a.sql` | censored against latent demand on stockout days, class A promoted SKUs | P03-DOMAIN-03, P03-TEST-01 |
| `06_working_capital_by_location.sql` | working capital by location at the cost in force across the cost step | P03-MET-12, P03-TEST-12 |
| `07_forecast_wape_by_sku.sql` | forecast WAPE by SKU, baselines against the model | P03-DOMAIN-01, P03-TEST-06 |
| `08_rejections_and_defects_by_reason.sql` | rejections by reason and the planted defects still in the data | P03-TEST-04, 07, 11 |
| `09_golden_position_and_order.sql` | the golden fixture, reconciled in section 10 | P03-GOLD-01 |
| `bi_fact_movement_day.sql`, `bi_fact_draft_order.sql` | the two fact tables of `bi-package.md` | P03-ART-06 |

Assumptions used by the queries (each is also stated in the file header):
* **A-1 as-of order status.** `purchase_orders.status` is the current status. A past month-end counts every order that is not cancelled; the cancellation instant is not stored, so a cancelled order is excluded at every as-of. The contract's confirmed-only figure is printed beside it (query 01, `on_order_confirmed_only`).
* **A-2 home location.** A purchase order line has no location; its open quantity counts at the product's home location (first `replenishment_params` row), the same allocation as `data/sql/reference_metrics.sql`.
* **A-3 UTC days.** Dates are UTC calendar dates; month-ends are `23:59:59` UTC; the day order is receipts, sales, the rest, then `event_at`, `movement_id` (D-01).

## 01 Stock and position at month-ends, by location (`01_stock_position_month_end_by_location.sql`)
On hand is the sum of posted deltas up to the cutoff (negative counts as 0, `negative_pairs` counts how many pairs were negative: none). On order is `ordered - received` on lines of orders placed by the cutoff; backorders are those open at the cutoff; position = on hand + on order - backorders, reserved is not subtracted.
`pct_of_capacity` is (on hand + on order) / `storage_capacity`.

<!-- BEGIN:01_stock_position_month_end_by_location -->
| month | location_id | on_hand | on_order | backorders | position | on_order_confirmed_only | pct_of_capacity | negative_pairs |
|---|---|---|---|---|---|---|---|---|
| 2025-04 | loc-01 | 378 | 420 | 0 | 798 | 0 | 41.0 | 0 |
| 2025-04 | loc-02 | 228 | 314 | 0 | 542 | 0 | 96.6 | 0 |
| 2025-04 | loc-03 | 214 | 140 | 0 | 354 | 0 | 38.5 | 0 |
| 2025-05 | loc-01 | 426 | 340 | 0 | 766 | 0 | 39.4 | 0 |
| 2025-05 | loc-02 | 173 | 348 | 0 | 521 | 0 | 92.9 | 0 |
| 2025-05 | loc-03 | 212 | 120 | 0 | 332 | 0 | 36.1 | 0 |
| 2025-06 | loc-01 | 347 | 498 | 0 | 845 | 0 | 43.5 | 0 |
| 2025-06 | loc-02 | 200 | 342 | 0 | 542 | 0 | 96.6 | 0 |
| 2025-06 | loc-03 | 233 | 108 | 0 | 341 | 0 | 37.1 | 0 |
| 2025-07 | loc-01 | 484 | 288 | 0 | 772 | 0 | 39.7 | 0 |
| 2025-07 | loc-02 | 228 | 296 | 0 | 524 | 0 | 93.4 | 0 |
| 2025-07 | loc-03 | 135 | 232 | 1 | 366 | 0 | 39.9 | 0 |
| 2025-08 | loc-01 | 409 | 354 | 0 | 763 | 0 | 39.2 | 0 |
| 2025-08 | loc-02 | 202 | 350 | 0 | 552 | 0 | 98.4 | 0 |
| 2025-08 | loc-03 | 194 | 180 | 0 | 374 | 0 | 40.7 | 0 |
| 2025-09 | loc-01 | 426 | 384 | 0 | 810 | 0 | 41.7 | 0 |
| 2025-09 | loc-02 | 223 | 320 | 0 | 543 | 0 | 96.8 | 0 |
| 2025-09 | loc-03 | 277 | 150 | 0 | 427 | 0 | 46.4 | 0 |
| 2025-10 | loc-01 | 409 | 436 | 0 | 845 | 0 | 43.5 | 0 |
| 2025-10 | loc-02 | 188 | 360 | 0 | 548 | 0 | 97.7 | 0 |
| 2025-10 | loc-03 | 220 | 170 | 0 | 390 | 0 | 42.4 | 0 |
| 2025-11 | loc-01 | 467 | 320 | 0 | 787 | 0 | 40.5 | 0 |
| 2025-11 | loc-02 | 201 | 340 | 0 | 541 | 0 | 96.4 | 0 |
| 2025-11 | loc-03 | 190 | 192 | 0 | 382 | 0 | 41.5 | 0 |
| 2025-12 | loc-01 | 437 | 288 | 0 | 725 | 0 | 37.3 | 0 |
| 2025-12 | loc-02 | 208 | 346 | 0 | 554 | 0 | 98.8 | 0 |
| 2025-12 | loc-03 | 199 | 120 | 9 | 310 | 0 | 34.7 | 0 |
| 2026-01 | loc-01 | 410 | 384 | 0 | 794 | 0 | 40.8 | 0 |
| 2026-01 | loc-02 | 280 | 258 | 0 | 538 | 0 | 95.9 | 0 |
| 2026-01 | loc-03 | 216 | 132 | 0 | 348 | 0 | 37.8 | 0 |
| 2026-02 | loc-01 | 489 | 304 | 0 | 793 | 0 | 40.8 | 0 |
| 2026-02 | loc-02 | 216 | 342 | 0 | 558 | 0 | 99.5 | 0 |
| 2026-02 | loc-03 | 279 | 36 | 0 | 315 | 0 | 34.2 | 0 |
| 2026-03 | loc-01 | 281 | 586 | 0 | 867 | 0 | 44.6 | 0 |
| 2026-03 | loc-02 | 143 | 410 | 0 | 553 | 0 | 98.6 | 0 |
| 2026-03 | loc-03 | 236 | 162 | 0 | 398 | 0 | 43.3 | 0 |
| 2026-04 | loc-01 | 299 | 652 | 0 | 951 | 0 | 48.9 | 0 |
| 2026-04 | loc-02 | 184 | 372 | 0 | 556 | 0 | 99.1 | 0 |
| 2026-04 | loc-03 | 215 | 152 | 0 | 367 | 0 | 39.9 | 0 |
| 2026-05 | loc-01 | 271 | 530 | 0 | 801 | 0 | 41.2 | 0 |
| 2026-05 | loc-02 | 142 | 408 | 0 | 550 | 0 | 98.0 | 0 |
| 2026-05 | loc-03 | 236 | 228 | 0 | 464 | 0 | 50.4 | 0 |
| 2026-06 | loc-01 | 476 | 360 | 0 | 836 | 0 | 43.0 | 0 |
| 2026-06 | loc-02 | 259 | 274 | 0 | 533 | 0 | 95.0 | 0 |
| 2026-06 | loc-03 | 292 | 156 | 0 | 448 | 0 | 48.7 | 0 |
| 2026-07 | loc-01 | 318 | 570 | 0 | 888 | 0 | 45.7 | 0 |
| 2026-07 | loc-02 | 229 | 300 | 0 | 529 | 0 | 94.3 | 0 |
| 2026-07 | loc-03 | 224 | 236 | 0 | 460 | 0 | 50.0 | 0 |
| 2026-08 | loc-01 | 563 | 262 | 0 | 825 | 0 | 42.4 | 0 |
| 2026-08 | loc-02 | 228 | 304 | 0 | 532 | 0 | 94.8 | 0 |
| 2026-08 | loc-03 | 244 | 216 | 0 | 460 | 0 | 50.0 | 0 |
| 2026-09 | loc-01 | 504 | 284 | 0 | 788 | 248 | 40.5 | 0 |
| 2026-09 | loc-02 | 246 | 336 | 0 | 582 | 336 | 103.7 | 0 |
| 2026-09 | loc-03 | 270 | 60 | 0 | 330 | 24 | 35.9 | 0 |
<!-- END:01_stock_position_month_end_by_location -->

Observed: `loc-02` runs at 92.9 % to 103.7 % of its capacity at every month-end (loc-01 37.3 % to 48.9 %, loc-03 34.2 % to 50.4 %), which is the capacity-bound relationship the generator designed in; at 2026-09 it is over 100 % (582 units against 561). Backorders are open at only 2 of the 54 cells, both at `loc-03` (the one backlog location; 1 unit at 2025-07 and 9 at 2025-12, so position is below on hand + on order there); each backorder is filled within 7 days.
The two on-order columns differ for a reason that matters for any as-of report: with the contract's confirmed-only filter every month-end before 2026-09 shows 0 on order (17 months x 3 locations), because the orders open then are `closed` now. At 2026-09 the difference is 72 units, the two closed orders with a partly received line (S-04).

## 02 The draft buying plan with its arithmetic (`02_draft_orders_arithmetic.sql`)
At the snapshot cutoff, per SKU x location with position below the reorder point: position = on hand + on order (confirmed orders, D-01) - backorders; raw = target - position; after MOQ = MAX(raw, MOQ); order = CEILING(after MOQ / pack) x pack. `unit_cost` is the cost in force on the cutoff date, `order_value` = order x cost.
The `draft_orders` table is empty in the seeded snapshot (C05 writes it), so this is the arithmetic the command would persist from `replenishment_params`.

<!-- BEGIN:02_draft_orders_arithmetic -->
| product_id | location_id | abc_class | supplier_id | on_hand | on_order | backorders | position | reorder_point | target_position | raw_order | moq | after_moq | pack_size | order_qty | unit_cost | order_value |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| prod-002 | loc-02 | A | sup-02 | 70 | 48 | 0 | 118 | 128 | 252 | 134 | 24 | 134 | 12 | 144 | 41.74 | 6010.56 |
| prod-005 | loc-02 | A | sup-01 | 0 | 48 | 0 | 48 | 51 | 144 | 96 | 24 | 96 | 12 | 96 | 53.17 | 5104.32 |
| TOTAL (2 of 60 triggered) |  |  |  | 1020 | 608 | 0 | 1628 | 1198 | 2336 | 230 |  | 230 |  | 240 |  | 11114.88 |
<!-- END:02_draft_orders_arithmetic -->

Observed: 2 of 60 pairs are triggered, both class A at `loc-02`: `prod-002` (position 118 < 128, raw 134, 24 <= 134, 12 packs = 144) and `prod-005` (on hand 0, position 48 < 51, raw 96, 8 packs). 240 units worth 11,114.88 at the cost in force, against 29,090.64 of working capital at the cutoff (query 06).
Not in the arithmetic by contract: the storage capacity of `loc-02` (query 01 shows it already at 103.7 %), and the 6 open reservations (reserved is not subtracted from position).
`bi_fact_draft_order.sql` returns all 60 rows; each equals the domain's `replenish` for that pair (section 10).

## 03 Fill rate and stockout days by location and ABC class (`03_fill_rate_stockout_by_location_abc.sql`)
Window 2025-04-01 .. 2026-09-30. fill rate = fulfilled / (fulfilled + unmet), unmet = backorders opened + lost sales (D-06). `stockout_pair_days` counts SKU x location x day cells with unmet demand; `stockout_pair_day_share` divides by pairs x 548.

<!-- BEGIN:03_fill_rate_stockout_by_location_abc -->
| location_id | abc_class | pairs | fulfilled_units | unmet_units | requested_units | fill_rate | stockout_pair_days | stockout_pair_day_share |
|---|---|---|---|---|---|---|---|---|
| loc-01 | A | 3 | 10983 | 425 | 11408 | 0.962745 | 42 | 0.025547 |
| loc-01 | B | 10 | 2353 | 69 | 2422 | 0.971511 | 54 | 0.009854 |
| loc-01 | C | 16 | 1402 | 46 | 1448 | 0.968232 | 32 | 0.003650 |
| loc-01 | ALL | 29 | 14738 | 540 | 15278 | 0.964655 | 128 | 0.008054 |
| loc-02 | A | 3 | 12087 | 1682 | 13769 | 0.877842 | 205 | 0.124696 |
| loc-02 | B | 3 | 679 | 18 | 697 | 0.974175 | 15 | 0.009124 |
| loc-02 | C | 11 | 862 | 14 | 876 | 0.984018 | 13 | 0.002157 |
| loc-02 | ALL | 17 | 13628 | 1714 | 15342 | 0.888281 | 233 | 0.025011 |
| loc-03 | A | 2 | 6120 | 316 | 6436 | 0.950901 | 47 | 0.042883 |
| loc-03 | B | 3 | 771 | 28 | 799 | 0.964956 | 13 | 0.007908 |
| loc-03 | C | 9 | 819 | 14 | 833 | 0.983193 | 10 | 0.002028 |
| loc-03 | ALL | 14 | 7710 | 358 | 8068 | 0.955627 | 70 | 0.009124 |
| ALL | ALL | 60 | 36076 | 2612 | 38688 | 0.932486 | 431 | 0.013108 |
<!-- END:03_fill_rate_stockout_by_location_abc -->

Observed: overall fill rate 0.932486 (36,076 of 38,688 requested). `loc-02` is lowest (0.888281; class A 0.877842, with 205 stockout pair-days of 1,644, a 12.47 % share), against 0.964655 at `loc-01` and 0.955627 at `loc-03`, matching the designed relationship (0.888 against 0.96).
**Two stockout-day figures exist and must not be mixed up (reviewer finding R3-01, fixed in T-03-07, decision in `contracts.md` D-04).** The contract's `stockout_days` is now the SKU-day rate: 431 stockout pair-days over 60 pairs x 548 days = 32,880 SKU-days = 0.013108, so groups reconcile to the total. The share of calendar dates with any unmet demand, 290 / 548 = 0.529197, is the separate key `stockout_calendar_days_share`. Both are computed here and agree with `reference_metrics.sql` and the domain (section 10).

## 04 Supplier on-time rate by month, no future leakage (`04_supplier_on_time_by_month.sql`)
Promised date = order date + quoted lead days counted on the supplier calendar (closure days do not count). A receipt is on time when its UTC date is on or before the promised date. `on_time_rate` uses only receipts dated inside the month; `cum_*` uses only receipts dated up to that month-end; `overdue_open_lines` counts lines promised on or before the cutoff and not fully received by it (censored: neither on time nor late yet). The `ALL` rows are the whole history.

<!-- BEGIN:04_supplier_on_time_by_month -->
| supplier_id | month | eligible_receipts | on_time_receipts | on_time_rate | cum_eligible | cum_on_time_rate | overdue_open_lines |
|---|---|---|---|---|---|---|---|
| sup-01 | 2025-04 | 23 | 20 | 0.869565 | 23 | 0.869565 | 0 |
| sup-01 | 2025-05 | 19 | 14 | 0.736842 | 42 | 0.809524 | 0 |
| sup-01 | 2025-06 | 21 | 20 | 0.952381 | 63 | 0.857143 | 0 |
| sup-01 | 2025-07 | 20 | 14 | 0.700000 | 83 | 0.819277 | 1 |
| sup-01 | 2025-08 | 20 | 15 | 0.750000 | 103 | 0.805825 | 0 |
| sup-01 | 2025-09 | 19 | 17 | 0.894737 | 122 | 0.819672 | 0 |
| sup-01 | 2025-10 | 15 | 13 | 0.866667 | 137 | 0.824818 | 1 |
| sup-01 | 2025-11 | 20 | 15 | 0.750000 | 157 | 0.815287 | 0 |
| sup-01 | 2025-12 | 19 | 16 | 0.842105 | 176 | 0.818182 | 0 |
| sup-01 | 2026-01 | 18 | 14 | 0.777778 | 194 | 0.814433 | 0 |
| sup-01 | 2026-02 | 20 | 16 | 0.800000 | 214 | 0.813084 | 0 |
| sup-01 | 2026-03 | 13 | 12 | 0.923077 | 227 | 0.819383 | 1 |
| sup-01 | 2026-04 | 21 | 20 | 0.952381 | 248 | 0.830645 | 1 |
| sup-01 | 2026-05 | 14 | 11 | 0.785714 | 262 | 0.828244 | 6 |
| sup-01 | 2026-06 | 23 | 14 | 0.608696 | 285 | 0.810526 | 0 |
| sup-01 | 2026-07 | 18 | 18 | 1.000000 | 303 | 0.821782 | 2 |
| sup-01 | 2026-08 | 18 | 15 | 0.833333 | 321 | 0.822430 | 0 |
| sup-01 | 2026-09 | 19 | 18 | 0.947368 | 340 | 0.829412 | 3 |
| sup-01 | ALL | 340 | 282 | 0.829412 | 340 | 0.829412 |  |
| sup-02 | 2025-04 | 15 | 12 | 0.800000 | 15 | 0.800000 | 0 |
| sup-02 | 2025-05 | 17 | 16 | 0.941176 | 32 | 0.875000 | 0 |
| sup-02 | 2025-06 | 22 | 16 | 0.727273 | 54 | 0.814815 | 0 |
| sup-02 | 2025-07 | 20 | 15 | 0.750000 | 74 | 0.797297 | 0 |
| sup-02 | 2025-08 | 22 | 20 | 0.909091 | 96 | 0.822917 | 0 |
| sup-02 | 2025-09 | 22 | 20 | 0.909091 | 118 | 0.838983 | 1 |
| sup-02 | 2025-10 | 20 | 17 | 0.850000 | 138 | 0.840580 | 0 |
| sup-02 | 2025-11 | 18 | 16 | 0.888889 | 156 | 0.846154 | 1 |
| sup-02 | 2025-12 | 17 | 14 | 0.823529 | 173 | 0.843931 | 0 |
| sup-02 | 2026-01 | 16 | 16 | 1.000000 | 189 | 0.857143 | 0 |
| sup-02 | 2026-02 | 16 | 14 | 0.875000 | 205 | 0.858537 | 0 |
| sup-02 | 2026-03 | 18 | 18 | 1.000000 | 223 | 0.869955 | 0 |
| sup-02 | 2026-04 | 20 | 15 | 0.750000 | 243 | 0.860082 | 0 |
| sup-02 | 2026-05 | 19 | 17 | 0.894737 | 262 | 0.862595 | 1 |
| sup-02 | 2026-06 | 24 | 21 | 0.875000 | 286 | 0.863636 | 0 |
| sup-02 | 2026-07 | 20 | 17 | 0.850000 | 306 | 0.862745 | 0 |
| sup-02 | 2026-08 | 22 | 19 | 0.863636 | 328 | 0.862805 | 0 |
| sup-02 | 2026-09 | 20 | 18 | 0.900000 | 348 | 0.864943 | 0 |
| sup-02 | ALL | 348 | 301 | 0.864943 | 348 | 0.864943 |  |
| sup-03 | 2025-04 | 14 | 11 | 0.785714 | 14 | 0.785714 | 1 |
| sup-03 | 2025-05 | 18 | 12 | 0.666667 | 32 | 0.718750 | 0 |
| sup-03 | 2025-06 | 15 | 13 | 0.866667 | 47 | 0.765957 | 2 |
| sup-03 | 2025-07 | 15 | 10 | 0.666667 | 62 | 0.741935 | 0 |
| sup-03 | 2025-08 | 15 | 13 | 0.866667 | 77 | 0.766234 | 2 |
| sup-03 | 2025-09 | 17 | 8 | 0.470588 | 94 | 0.712766 | 0 |
| sup-03 | 2025-10 | 11 | 8 | 0.727273 | 105 | 0.714286 | 1 |
| sup-03 | 2025-11 | 14 | 11 | 0.785714 | 119 | 0.722689 | 0 |
| sup-03 | 2025-12 | 10 | 9 | 0.900000 | 129 | 0.736434 | 0 |
| sup-03 | 2026-01 | 14 | 11 | 0.785714 | 143 | 0.741259 | 1 |
| sup-03 | 2026-02 | 13 | 7 | 0.538462 | 156 | 0.724359 | 2 |
| sup-03 | 2026-03 | 13 | 6 | 0.461538 | 169 | 0.704142 | 2 |
| sup-03 | 2026-04 | 13 | 6 | 0.461538 | 182 | 0.686813 | 3 |
| sup-03 | 2026-05 | 16 | 10 | 0.625000 | 198 | 0.681818 | 2 |
| sup-03 | 2026-06 | 13 | 13 | 1.000000 | 211 | 0.701422 | 3 |
| sup-03 | 2026-07 | 13 | 7 | 0.538462 | 224 | 0.691964 | 4 |
| sup-03 | 2026-08 | 16 | 11 | 0.687500 | 240 | 0.691667 | 4 |
| sup-03 | 2026-09 | 14 | 7 | 0.500000 | 254 | 0.681102 | 2 |
| sup-03 | ALL | 254 | 173 | 0.681102 | 254 | 0.681102 |  |
| sup-04 | 2025-04 | 13 | 12 | 0.923077 | 13 | 0.923077 | 0 |
| sup-04 | 2025-05 | 20 | 20 | 1.000000 | 33 | 0.969697 | 0 |
| sup-04 | 2025-06 | 18 | 18 | 1.000000 | 51 | 0.980392 | 0 |
| sup-04 | 2025-07 | 22 | 22 | 1.000000 | 73 | 0.986301 | 1 |
| sup-04 | 2025-08 | 24 | 20 | 0.833333 | 97 | 0.948454 | 0 |
| sup-04 | 2025-09 | 21 | 19 | 0.904762 | 118 | 0.940678 | 0 |
| sup-04 | 2025-10 | 17 | 15 | 0.882353 | 135 | 0.933333 | 0 |
| sup-04 | 2025-11 | 28 | 22 | 0.785714 | 163 | 0.907975 | 1 |
| sup-04 | 2025-12 | 22 | 14 | 0.636364 | 185 | 0.875676 | 0 |
| sup-04 | 2026-01 | 18 | 14 | 0.777778 | 203 | 0.866995 | 0 |
| sup-04 | 2026-02 | 16 | 11 | 0.687500 | 219 | 0.853881 | 0 |
| sup-04 | 2026-03 | 16 | 16 | 1.000000 | 235 | 0.863830 | 2 |
| sup-04 | 2026-04 | 24 | 17 | 0.708333 | 259 | 0.849421 | 0 |
| sup-04 | 2026-05 | 24 | 21 | 0.875000 | 283 | 0.851590 | 0 |
| sup-04 | 2026-06 | 25 | 23 | 0.920000 | 308 | 0.857143 | 0 |
| sup-04 | 2026-07 | 21 | 14 | 0.666667 | 329 | 0.844985 | 0 |
| sup-04 | 2026-08 | 22 | 16 | 0.727273 | 351 | 0.837607 | 0 |
| sup-04 | 2026-09 | 15 | 14 | 0.933333 | 366 | 0.841530 | 1 |
| sup-04 | ALL | 366 | 308 | 0.841530 | 366 | 0.841530 |  |
<!-- END:04_supplier_on_time_by_month -->

Observed: whole-history on-time rate `sup-03` 0.681102 (173 of 254, so 31.9 % late) against `sup-01` 0.829412, `sup-02` 0.864943 and `sup-04` 0.841530, the designed unreliable supplier. Its monthly rate swings from 0.461538 (2026-03, 2026-04) to 1.000000 (2026-06) on 10 to 18 receipts a month, so a single month is noisy; the cumulative rate settles near 0.68 to 0.70 from 2026-04. Each of the 72 cumulative cells (4 suppliers x 18 cutoffs) equals the domain's `on_time_rate` called with that cutoff, which is the executable proof that no receipt after a cutoff is read.

## 05 Censored against latent demand, class A promoted SKUs (`05_censored_vs_latent_class_a.sql`)
All 8 class A SKUs carry three ten-day promotions. A stockout day is a UTC date with a backorder opened or a lost sale. `censored_units` = latent - observed on stockout days; `unmet_recorded` = backorder + lost-sale units those days (they must be equal); `days_observed_ne_latent` counts other days on which observed and latent differ (0). `latent_demand` is the generator's published truth and is never a forecast input.

<!-- BEGIN:05_censored_vs_latent_class_a -->
| product_id | location_id | unmet_policy | stockout_days | stockout_days_in_promo | observed_on_stockout_days | latent_on_stockout_days | censored_units | unmet_recorded | share_of_latent_unseen | days_observed_ne_latent |
|---|---|---|---|---|---|---|---|---|---|---|
| prod-001 | loc-01 | lost_sale | 5 | 1 | 8 | 54 | 46 | 46 | 0.851852 | 0 |
| prod-002 | loc-02 | lost_sale | 74 | 12 | 176 | 806 | 630 | 630 | 0.781638 | 0 |
| prod-003 | loc-03 | backlog | 19 | 4 | 29 | 145 | 116 | 116 | 0.800000 | 0 |
| prod-004 | loc-01 | lost_sale | 10 | 7 | 25 | 202 | 177 | 177 | 0.876238 | 0 |
| prod-005 | loc-02 | lost_sale | 82 | 11 | 187 | 735 | 548 | 548 | 0.745578 | 0 |
| prod-006 | loc-03 | backlog | 28 | 5 | 23 | 223 | 200 | 200 | 0.896861 | 0 |
| prod-007 | loc-01 | lost_sale | 27 | 9 | 8 | 210 | 202 | 202 | 0.961905 | 0 |
| prod-008 | loc-02 | lost_sale | 49 | 11 | 148 | 652 | 504 | 504 | 0.773006 | 0 |
<!-- END:05_censored_vs_latent_class_a -->

Observed: on stockout days the observed sales show only 3.8 % to 25.4 % of the latent demand (`share_of_latent_unseen` 0.745578 to 0.961905); 2,423 latent units are invisible in sales, exactly the 2,423 units of recorded unmet demand, and observed equals latent on every other day. Stockout days of `prod-001, 002, 004, 005, 007, 008` are 5, 74, 10, 82, 27, 49, equal to the manifest's designed counts. A forecast trained on observed sales alone would learn the censored level; that is why latent demand is published separately and labelled.
Between 1 and 12 stockout days per SKU fall inside a promotion window (`stockout_days_in_promo`), consistent with reorder parameters that ignore promotions.

## 06 Working capital by location at the cost in force (`06_working_capital_by_location.sql`)
Every day is valued at its own cost: the latest `cost_versions` row effective on or before that day, else the product's base cost (D-05); negative stock counts as 0. The step is +6 % on the 15 `sup-04` products from 2026-02-01. `avg_daily_*` is the average of daily totals over the month (the contract's average inventory value), `step_effect` their difference, `ALL` the whole 548 days.

<!-- BEGIN:06_working_capital_by_location -->
| month | end_loc_01 | end_loc_02 | end_loc_03 | end_total | avg_daily_total | avg_daily_at_base_cost | step_effect |
|---|---|---|---|---|---|---|---|
| 2025-04 | 8405.25 | 6533.12 | 7092.51 | 22030.88 | 29741.51 | 29741.51 | 0.00 |
| 2025-05 | 9512.13 | 4143.87 | 4279.22 | 17935.22 | 21330.36 | 21330.36 | 0.00 |
| 2025-06 | 7588.55 | 6397.81 | 4714.13 | 18700.49 | 18573.59 | 18573.59 | 0.00 |
| 2025-07 | 11280.83 | 7202.22 | 3449.99 | 21933.04 | 21012.67 | 21012.67 | 0.00 |
| 2025-08 | 8783.45 | 6289.24 | 4781.29 | 19853.98 | 19930.70 | 19930.70 | 0.00 |
| 2025-09 | 10310.82 | 6804.63 | 8096.07 | 25211.52 | 21895.41 | 21895.41 | 0.00 |
| 2025-10 | 10537.20 | 4355.02 | 7360.95 | 22253.17 | 22460.25 | 22460.25 | 0.00 |
| 2025-11 | 8899.53 | 5906.75 | 3571.34 | 18377.62 | 22680.15 | 22680.15 | 0.00 |
| 2025-12 | 9192.73 | 5912.90 | 3447.35 | 18552.98 | 22038.51 | 22038.51 | 0.00 |
| 2026-01 | 9656.06 | 9264.51 | 5223.02 | 24143.59 | 21867.29 | 21867.29 | 0.00 |
| 2026-02 | 13452.34 | 7118.96 | 8556.33 | 29127.63 | 23302.54 | 22811.89 | 490.65 |
| 2026-03 | 5474.44 | 3004.12 | 7643.63 | 16122.19 | 21591.06 | 21085.26 | 505.80 |
| 2026-04 | 6202.72 | 4377.43 | 6596.39 | 17176.54 | 23076.81 | 22436.29 | 640.53 |
| 2026-05 | 4208.01 | 2781.05 | 6618.28 | 13607.34 | 17834.45 | 17463.75 | 370.70 |
| 2026-06 | 13179.79 | 7807.42 | 7986.73 | 28973.94 | 21756.03 | 21320.51 | 435.52 |
| 2026-07 | 6341.03 | 8088.76 | 6404.68 | 20834.47 | 20691.62 | 20275.78 | 415.85 |
| 2026-08 | 14405.38 | 6494.67 | 6938.06 | 27838.11 | 21910.81 | 21416.39 | 494.41 |
| 2026-09 | 13078.47 | 7855.29 | 8156.88 | 29090.64 | 22533.64 | 22060.66 | 472.98 |
| ALL |  |  |  |  | 21881.18 | 21670.23 | 210.95 |
<!-- END:06_working_capital_by_location -->

Observed: working capital at the cutoff is 29,090.64 (loc-01 13,078.47, loc-02 7,855.29, loc-03 8,156.88); the average daily inventory value over the 548 days is 21,881.18, of which 210.95 is the cost step (valuing the whole period at the base cost would give 21,670.23). Before February 2026 the step effect is 0.00 in every month; from February it is 370.70 to 640.53 a month. A single month-end value is volatile (13,607.34 in 2026-05, 28,973.94 in 2026-06) so the daily average is the steadier measure.

## 07 Forecast WAPE by SKU, baselines against the model (`07_forecast_wape_by_sku.sql`)
14 pairs x 4 cutoffs (2026-06-30, 07-31, 08-31, 09-16) x 14 target days x 3 models, scored on the same points against observed sales (0 when none). `naive` and `seasonal_naive` (period 7) are the baselines, `ewma` the model; a lower WAPE is a lower MAE on identical points, and the model counts only when it beats seasonal-naive (D-03). `leaky_points` must be 0; `zero_demand_runs` discloses the 14-day windows with no demand at all.

<!-- BEGIN:07_forecast_wape_by_sku -->
| product_id | location_id | abc_class | runs | points | total_actual | zero_demand_runs | wape_naive | wape_seasonal_naive | wape_ewma | ewma_beats_seasonal_naive | leaky_points | selected_models |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| prod-001 | loc-01 | A | 4 | 56 | 351 | 0 | 0.612536 | 0.680912 | 0.518291 | yes | 0 | ewma+naive |
| prod-002 | loc-02 | A | 4 | 56 | 416 | 0 | 0.653846 | 0.754808 | 0.606346 | yes | 0 | ewma+naive |
| prod-003 | loc-03 | A | 4 | 56 | 273 | 0 | 0.545788 | 0.692308 | 0.508571 | yes | 0 | ewma |
| prod-004 | loc-01 | A | 4 | 56 | 547 | 0 | 0.659963 | 0.510055 | 0.447020 | yes | 0 | ewma |
| prod-005 | loc-02 | A | 4 | 56 | 353 | 0 | 0.654391 | 0.643059 | 0.522720 | yes | 0 | ewma+seasonal_naive |
| prod-006 | loc-03 | A | 4 | 56 | 296 | 0 | 0.709459 | 0.662162 | 0.490338 | yes | 0 | ewma+naive+seasonal_naive |
| prod-007 | loc-01 | A | 4 | 56 | 256 | 0 | 0.828125 | 0.734375 | 0.609375 | yes | 0 | ewma |
| prod-008 | loc-02 | A | 4 | 56 | 449 | 0 | 0.661470 | 0.759465 | 0.629220 | yes | 0 | ewma+naive |
| prod-012 | loc-01 | B | 4 | 56 | 21 | 0 | 1.571429 | 1.571429 | 1.637143 | no | 0 | ewma+naive+seasonal_naive |
| prod-016 | loc-03 | B | 4 | 56 | 36 | 0 | 1.000000 | 1.222222 | 1.053889 | yes | 0 | ewma+naive |
| prod-034 | loc-01 | C | 4 | 56 | 25 | 0 | 2.120000 | 1.800000 | 1.569600 | yes | 0 | naive |
| prod-037 | loc-02 | C | 4 | 56 | 14 | 1 | 3.000000 | 1.285714 | 1.648571 | no | 0 | naive+seasonal_naive |
| prod-043 | loc-03 | C | 4 | 56 | 5 | 3 | 1.000000 | 2.200000 | 1.940000 | yes | 0 | naive+seasonal_naive |
| prod-046 | loc-02 | C | 4 | 56 | 9 | 2 | 1.000000 | 1.000000 | 1.015556 | no | 0 | ewma+naive+seasonal_naive |
<!-- END:07_forecast_wape_by_sku -->

Observed: `ewma` beats `seasonal_naive` for 11 of 14 SKUs, including all 8 class A (WAPE 0.447020 to 0.629220 against 0.510055 to 0.759465). The three where it does not (`prod-012`, `prod-037`, `prod-046`) are slow SKUs with WAPE of 1.0 or more, i.e. no better than forecasting zero; the intermittent SKUs `prod-037`, `prod-043`, `prod-046` have 1, 3 and 2 zero-demand windows, disclosed rather than dropped (P03-TEST-06). No forecast point is dated on or before its cutoff (`leaky_points` is 0 everywhere).
Note on S-03 (fixed in T-03-07): the domain's promotion factor is now `1 + planned_uplift` (Python and TypeScript). These forecast points are the stored ones written by `data/generate.py` with its own models, not by the domain's forecast, so they are not regenerated and the queries do not recompute them; only the domain-derived parameters (the options of section 11) changed.

## 08 Rejections and planted defects by reason (`08_rejections_and_defects_by_reason.sql`)

<!-- BEGIN:08_rejections_and_defects_by_reason -->
| lens | entity | reason | records | ids |
|---|---|---|---|---|
| rejection | inventory_movements | DUPLICATE_MOVEMENT_ID | 3 | mv-002230, mv-005418, mv-006574 |
| rejection | receipts | RECEIPT_BEFORE_ORDER | 1 | rcpt-01309 |
| detected | purchase_order_lines | CLOSED_ORDER_PARTLY_RECEIVED | 2 | pol-00795, pol-00840 |
| detected | receipts | LEAD_TIME_SPANS_CLOSURE | 8 | rcpt-00690, rcpt-00702, rcpt-00712, rcpt-00713, rcpt-00714, rcpt-00715, rcpt-00716, rcpt-00721 |
| detected | reservations | OPEN_RESERVATION_AT_CUTOFF | 6 | res-001, res-002, res-003, res-004, res-005, res-006 |
<!-- END:08_rejections_and_defects_by_reason -->

Observed: the load rejected exactly 4 rows and kept their raw rows in `rejected_records`: 3 replays of already posted movement ids (INJ-01, the first occurrence is kept so on hand is unchanged) and `rcpt-01309`, dated ten days before its order (INJ-02; the line stays open and on order). Three further defects are accepted rows by design and are found by query: 2 closed orders with a partly received line (INJ-03, `pol-00795` and `pol-00840`, 36 units each never received), 8 receipts of `sup-02` orders that span its 2026-01-05 .. 2026-01-18 closure (INJ-04), and 6 reservations still open at the cutoff (INJ-07). All five equal `data/injection-manifest.json`.

## 09 The golden fixture (`09_golden_position_and_order.sql`)
Run on the golden database (state `golden`, then `position_80` with the fixture's second line inserted inside a rolled-back transaction):

<!-- BEGIN:09_golden_position_and_order -->
| on_hand | on_order | backorders | position | reorder_point | target_position | triggered | raw_order | moq | order_after_moq | pack_size | order_quantity | running_min_day_order | running_min_timestamp_order | working_capital | fulfilled_units | unmet_units | fill_rate | stockout_days_count | stockout_days |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 40 | 30 | 10 | 60 | 70 | 120 | True | 60 | 50 | 60 | 24 | 72 | 0 | -35 | 500.00 | 95 | 5 | 0.950000 | 1 | 0.032258 |
| 40 | 50 | 10 | 80 | 70 | 120 | False | 0 | 50 | 0 | 24 | 0 | 0 | -35 | 500.00 | 95 | 5 | 0.950000 | 1 | 0.032258 |
<!-- END:09_golden_position_and_order -->

## 10 Reconciliation of the golden position and order, three sources
Position and order for the golden fixture from the analysis SQL (`09_golden_position_and_order.sql`), from `data/sql/reference_metrics.sql` and from the Python domain (`run_pipeline`), with the hand-derived `tests/fixtures/golden/expected.json` as a fourth column:
**On hand 40, on order 30, backorders 10, position 60 from the analysis SQL, 60 from `reference_metrics.sql`, 60 from the Python domain. Raw order 60, order after MOQ 60, order quantity 72 from all three. With the second line (position_80): position 80 and order quantity 0 from all three.** Day order: the running minimum is 0 in day order and -35 in timestamp order from all three.

<!-- BEGIN:golden_three_sources -->
| state | quantity | analysis_sql_09 | reference_metrics_sql | python_domain | expected_json |
|---|---|---|---|---|---|
| golden | on_hand | 40 | 40 | 40 | 40 |
| golden | on_order | 30 | 30 | 30 | 30 |
| golden | backorders | 10 | 10 | 10 | 10 |
| golden | inventory_position | 60 | 60 | 60 | 60 |
| golden | reorder_point | 70 | 70 | 70 | 70 |
| golden | target_position | 120 | 120 | 120 | 120 |
| golden | reorder_triggered | True | True | True | True |
| golden | raw_order | 60 | 60 | 60 | 60 |
| golden | order_after_moq | 60 | 60 | 60 | 60 |
| golden | order_quantity | 72 | 72 | 72 | 72 |
| golden | running_stock_min | 0 | 0 | 0 | 0 |
| golden | timestamp_order_stock_min | -35 | -35 | -35 | -35 |
| golden | working_capital | 500.00 | 500.00 | 500.00 | 500.00 |
| golden | fulfilled_units | 95 | 95 | 95 | 95 |
| golden | unmet_units | 5 | 5 | 5 | 5 |
| golden | fill_rate | 0.950000 | 0.950000 | 0.950000 | 0.950000 |
| golden | stockout_day_count | 1 | 1 | 1 | 1 |
| golden | stockout_days | 0.032258 | 0.032258 | 0.032258 | 0.032258 |
| position_80 | on_hand | 40 | 40 | 40 | 40 |
| position_80 | on_order | 50 | 50 | 50 | 50 |
| position_80 | backorders | 10 | 10 | 10 | 10 |
| position_80 | inventory_position | 80 | 80 | 80 | 80 |
| position_80 | reorder_point | 70 | 70 | 70 | 70 |
| position_80 | target_position | 120 | 120 | 120 | 120 |
| position_80 | reorder_triggered | False | False | False | False |
| position_80 | raw_order | 0 | 0 | 0 | 0 |
| position_80 | order_after_moq | 0 | 0 | 0 | 0 |
| position_80 | order_quantity | 0 | 0 | 0 | 0 |
| position_80 | running_stock_min | 0 | 0 | 0 | 0 |
| position_80 | timestamp_order_stock_min | -35 | -35 | -35 | -35 |
| position_80 | working_capital | 500.00 | 500.00 | 500.00 | 500.00 |
| position_80 | fulfilled_units | 95 | 95 | 95 | 95 |
| position_80 | unmet_units | 5 | 5 | 5 | 5 |
| position_80 | fill_rate | 0.950000 | 0.950000 | 0.950000 | 0.950000 |
| position_80 | stockout_day_count | 1 | 1 | 1 | 1 |
| position_80 | stockout_days | 0.032258 | 0.032258 | 0.032258 | 0.032258 |
<!-- END:golden_three_sources -->

Snapshot totals and cell-by-cell checks (`run_all.py`; 91 checks; exit code 0 only if every row is equal):

<!-- BEGIN:reconciliation -->
| check | analysis_sql | second_source | third_source | fourth_source | equal |
|---|---|---|---|---|---|
| B options: params-of-record row equals the 02 TOTAL (triggered pairs / order units) | 2 / 240 | 2 / 240 |  |  | True |
| B snapshot on_hand: query 01/02/03/06 vs reference_metrics.sql vs domain | 1020 | 1020 | 1020 |  | True |
| B snapshot on_order: query 01/02/03/06 vs reference_metrics.sql vs domain | 608 | 608 | 608 |  | True |
| B snapshot backorders: query 01/02/03/06 vs reference_metrics.sql vs domain | 0 | 0 | 0 |  | True |
| B snapshot inventory_position: query 01/02/03/06 vs reference_metrics.sql vs domain | 1628 | 1628 | 1628 |  | True |
| B snapshot reorder_point: query 01/02/03/06 vs reference_metrics.sql vs domain | 1198 | 1198 | 1198 |  | True |
| B snapshot target_position: query 01/02/03/06 vs reference_metrics.sql vs domain | 2336 | 2336 | 2336 |  | True |
| B snapshot raw_order: query 01/02/03/06 vs reference_metrics.sql vs domain | 230 | 230 | 230 |  | True |
| B snapshot order_after_moq: query 01/02/03/06 vs reference_metrics.sql vs domain | 230 | 230 | 230 |  | True |
| B snapshot order_quantity: query 01/02/03/06 vs reference_metrics.sql vs domain | 240 | 240 | 240 |  | True |
| B snapshot fulfilled_units: query 01/02/03/06 vs reference_metrics.sql vs domain | 36076 | 36076 | 36076 |  | True |
| B snapshot unmet_units: query 01/02/03/06 vs reference_metrics.sql vs domain | 2612 | 2612 | 2612 |  | True |
| B snapshot requested_units: query 01/02/03/06 vs reference_metrics.sql vs domain | 38688 | 38688 | 38688 |  | True |
| B snapshot fill_rate: query 01/02/03/06 vs reference_metrics.sql vs domain | 0.932486 | 0.932486 | 0.932486 |  | True |
| B snapshot working_capital: query 01/02/03/06 vs reference_metrics.sql vs domain | 29090.64 | 29090.64 | 29090.64 |  | True |
| B on hand 02 TOTAL vs 01 month-end 2026-09 | 1020 | 1020 | 1020 |  | True |
| B on order (contract, confirmed only) 02 TOTAL vs 01 column on_order_confirmed_only | 608 | 608 | 608 |  | True |
| B observed days 548 (03 pair-days / 60 pairs) vs reference vs domain | 548 | 548 | 548 |  | True |
| B stockout calendar dates (distinct dates with unmet demand, all pairs): SQL vs reference vs domain | 0.529197 | 0.529197 | 0.529197 |  | True |
| B stockout SKU-days (pair x date cells, R3-01): query 03 ALL vs reference stockout_day_count vs domain | 431 | 431 | 431 |  | True |
| B stockout SKU-day rate = pair-days / (60 pairs x 548 days): query 03 ALL vs reference vs domain | 0.013108 | 0.013108 | 0.013108 |  | True |
| B observed SKU-days (60 pairs x 548 days): reference vs domain | 32880 | 32880 | 32880 |  | True |
| B average daily inventory value 06 row ALL vs domain supplementary() | 21881.18 | 21881.18 |  |  | True |
| B on-order difference as-of rule vs confirmed only at the final month-end (S-04: closed orders with a partial line) | 72 | 72 |  |  | True |
| B bi_fact_movement_day rows (60 pairs x 548 days) | 32880 | 32880 |  |  | True |
| B bi_fact_movement_day stock value on 2026-09-30 vs working capital | 29090.64 | 29090.64 |  |  | True |
| B bi_fact_movement_day fulfilled units vs reference | 36076 | 36076 |  |  | True |
| B bi_fact_movement_day unmet units vs reference | 2612 | 2612 |  |  | True |
| B bi Inventory Turnover (facts) vs domain supplementary() | 40.487277 | 40.487277 |  |  | True |
| B bi Stockout Calendar Day Share (facts) vs reference_metrics.sql stockout_calendar_days_share | 0.529197 | 0.529197 |  |  | True |
| B bi Stockout SKU Day Share (facts) vs reference_metrics.sql stockout_days | 0.013108 | 0.013108 |  |  | True |
| B bi Inventory Position (facts) vs reference_metrics.sql | 1628 | 1628 |  |  | True |
| B bi Draft Order Units (facts) vs reference_metrics.sql order_quantity | 240 | 240 |  |  | True |
| B draft_orders rows persisted in the seeded snapshot (derived table, written by the API) | 0 | 0 |  |  | True |
| B bi_fact_draft_order rows (60 pairs at the cutoff) | 60 | 60 |  |  | True |
| C 01 month-end cells (18 months x 3 locations) differing from the Python replay of on hand / on order / backorders | 0 | 0 |  |  | True |
| C 60 draft-order rows (bi_fact_draft_order) differing from the domain per pair | 0 | 0 |  |  | True |
| C triggered pairs: 02 rows vs bi_fact_draft_order triggered vs domain | 2 | 2 | 2 |  | True |
| C 03 rows (location x ABC, location subtotals, ALL) differing from compute_metrics | 0 | 0 |  |  | True |
| C 04 cumulative as-of rate cells (4 suppliers x 18 cutoffs) differing from on_time_rate(cutoff) | 0 | 0 |  |  | True |
| C 04 cells compared | 72 | 72 |  |  | True |
| C 04 sup-01 whole history: eligible / on-time rate | 340 / 0.829412 | 340 / 0.829412 |  |  | True |
| C 04 sup-02 whole history: eligible / on-time rate | 348 / 0.864943 | 348 / 0.864943 |  |  | True |
| C 04 sup-03 whole history: eligible / on-time rate | 254 / 0.681102 | 254 / 0.681102 |  |  | True |
| C 04 sup-04 whole history: eligible / on-time rate | 366 / 0.841530 | 366 / 0.841530 |  |  | True |
| C 04 sup-03 late share vs the manifest's designed 31.9 % of 254 | 31.9 % of 254 | 31.9 % of 254 |  |  | True |
| C 05 SKUs (8 class A) differing from censored_vs_latent, censored = unmet, or the manifest's stockout days | 0 | 0 |  |  | True |
| C 07 WAPE cells (14 SKUs x 3 models) differing from Python over forecast_points.json and sales.json | 0 | 0 |  |  | True |
| C 07 leaky forecast points (target date on or before the cutoff) | 0 | 0 |  |  | True |
| D INJ-01 DUPLICATE_MOVEMENT_ID ids | mv-002230, mv-005418, mv-006574 | mv-002230, mv-005418, mv-006574 |  |  | True |
| D INJ-02 RECEIPT_BEFORE_ORDER ids | rcpt-01309 | rcpt-01309 |  |  | True |
| D INJ-03 closed orders partly received (po lines) | pol-00795, pol-00840 | pol-00795, pol-00840 |  |  | True |
| D INJ-04 receipts spanning the closure | 8 | 8 |  |  | True |
| D INJ-07 open reservations at the cutoff | res-001, res-002, res-003, res-004, res-005, res-006 | res-001, res-002, res-003, res-004, res-005, res-006 |  |  | True |
| D rejected rows kept (table) vs domain ingest | 4 | 4 | 4 |  | True |
| A golden state golden: on_hand | 40 | 40 | 40 | 40 | True |
| A golden state golden: on_order | 30 | 30 | 30 | 30 | True |
| A golden state golden: backorders | 10 | 10 | 10 | 10 | True |
| A golden state golden: inventory_position | 60 | 60 | 60 | 60 | True |
| A golden state golden: reorder_point | 70 | 70 | 70 | 70 | True |
| A golden state golden: target_position | 120 | 120 | 120 | 120 | True |
| A golden state golden: reorder_triggered | True | True | True | True | True |
| A golden state golden: raw_order | 60 | 60 | 60 | 60 | True |
| A golden state golden: order_after_moq | 60 | 60 | 60 | 60 | True |
| A golden state golden: order_quantity | 72 | 72 | 72 | 72 | True |
| A golden state golden: running_stock_min | 0 | 0 | 0 | 0 | True |
| A golden state golden: timestamp_order_stock_min | -35 | -35 | -35 | -35 | True |
| A golden state golden: working_capital | 500.00 | 500.00 | 500.00 | 500.00 | True |
| A golden state golden: fulfilled_units | 95 | 95 | 95 | 95 | True |
| A golden state golden: unmet_units | 5 | 5 | 5 | 5 | True |
| A golden state golden: fill_rate | 0.950000 | 0.950000 | 0.950000 | 0.950000 | True |
| A golden state golden: stockout_day_count | 1 | 1 | 1 | 1 | True |
| A golden state golden: stockout_days | 0.032258 | 0.032258 | 0.032258 | 0.032258 | True |
| A golden state position_80: on_hand | 40 | 40 | 40 | 40 | True |
| A golden state position_80: on_order | 50 | 50 | 50 | 50 | True |
| A golden state position_80: backorders | 10 | 10 | 10 | 10 | True |
| A golden state position_80: inventory_position | 80 | 80 | 80 | 80 | True |
| A golden state position_80: reorder_point | 70 | 70 | 70 | 70 | True |
| A golden state position_80: target_position | 120 | 120 | 120 | 120 | True |
| A golden state position_80: reorder_triggered | False | False | False | False | True |
| A golden state position_80: raw_order | 0 | 0 | 0 | 0 | True |
| A golden state position_80: order_after_moq | 0 | 0 | 0 | 0 | True |
| A golden state position_80: order_quantity | 0 | 0 | 0 | 0 | True |
| A golden state position_80: running_stock_min | 0 | 0 | 0 | 0 | True |
| A golden state position_80: timestamp_order_stock_min | -35 | -35 | -35 | -35 | True |
| A golden state position_80: working_capital | 500.00 | 500.00 | 500.00 | 500.00 | True |
| A golden state position_80: fulfilled_units | 95 | 95 | 95 | 95 | True |
| A golden state position_80: unmet_units | 5 | 5 | 5 | 5 | True |
| A golden state position_80: fill_rate | 0.950000 | 0.950000 | 0.950000 | 0.950000 | True |
| A golden state position_80: stockout_day_count | 1 | 1 | 1 | 1 | True |
| A golden state position_80: stockout_days | 0.032258 | 0.032258 | 0.032258 | 0.032258 | True |
<!-- END:reconciliation -->

`reference_metrics.sql` over the whole snapshot (cross-check of queries 01, 02, 03 and 06):

<!-- BEGIN:reference_metrics_snapshot -->
| fill_rate | requested_units | fulfilled_units | unmet_units | observed_days | stockout_day_count | stockout_days | running_stock_min | timestamp_order_stock_min | negative_stock | working_capital | empty_population | on_hand | on_order | backorders | reserved | available | inventory_position | reorder_point | target_position | reorder_triggered | raw_order | order_after_moq | order_quantity | stockout_calendar_days_share | observed_sku_days |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.932486 | 38688 | 36076 | 2612 | 548 | 431 | 0.013108 | 0 | 0 | False | 29090.64 | False | 1020 | 608 | 0 | 123 | 897 | 1628 | 1198 | 2336 | True | 230 | 230 | 240 | 0.529197 | 32880 |
<!-- END:reference_metrics_snapshot -->

## 11 Decision options, computed with the domain (`options.py`)
Not SQL: the forecast-derived parameters and the common-random-number simulation are domain functions. Service target: the replenishment parameters of record were generated with z = 1.28 (about a 0.90 target); the table also gives the plan when the domain derives ROP and target from the forecast at 0.90 and at 0.95 (the path C05 takes for a SKU with no parameter row).
Unmet policy: `sc-95-lost` against `sc-95-backlog` (stored scenarios, seed 20261026, warm-up 28 days, 100 replications) on common random numbers, 180 days, lead time from the quoted days to quoted + 7 (the generator's lateness), mean daily demand from the published latent demand, initial stock = on hand at the cutoff. A simulated direction only: the simulation is a compact (s, S) loop and its statistical quality was not assessed.

<!-- BEGIN:10_options_service_target -->
| option | triggered_pairs | class_a_triggered | order_units | order_value |
|---|---|---|---|---|
| params of record (generator z 1.28, about 0.90) | 2 | 2 | 240 | 11114.88 |
| derived from the forecast at 0.90 | 7 | 0 | 88 | 1457.40 |
| derived from the forecast at 0.95 | 9 | 1 | 154 | 4707.66 |
<!-- END:10_options_service_target -->

<!-- BEGIN:10_options_service_target_sku_detail -->
| sku | option | position | reorder_point | target_position | triggered | order_quantity | order_value |
|---|---|---|---|---|---|---|---|
| prod-002 | params of record (generator z 1.28, about 0.90) | 118 | 128 | 252 | True | 144 | 6010.56 |
| prod-002 | derived from the forecast at 0.90 | 118 | 102 | 145 | False | 0 | 0.00 |
| prod-002 | derived from the forecast at 0.95 | 118 | 109 | 152 | False | 0 | 0.00 |
| prod-005 | params of record (generator z 1.28, about 0.90) | 48 | 51 | 144 | True | 96 | 5104.32 |
| prod-005 | derived from the forecast at 0.90 | 48 | 48 | 96 | False | 0 | 0.00 |
| prod-005 | derived from the forecast at 0.95 | 48 | 51 | 99 | True | 60 | 3190.20 |
<!-- END:10_options_service_target_sku_detail -->

<!-- BEGIN:10_options_unmet_policy -->
| sku | scenario | policy | seed | replications | mean_latent_demand_per_day | lead_days | fill_rate | stockout_day_share |
|---|---|---|---|---|---|---|---|---|
| prod-002 | sc-95-lost | lost_sale | 20261026 | 100 | 8.91 | 12-19 | 0.9119 | 0.1009 |
| prod-002 | sc-95-backlog | backlog | 20261026 | 100 | 8.91 | 12-19 | 0.9038 | 0.1115 |
| prod-005 | sc-95-lost | lost_sale | 20261026 | 100 | 7.15 | 5-12 | 0.8979 | 0.1142 |
| prod-005 | sc-95-backlog | backlog | 20261026 | 100 | 7.15 | 5-12 | 0.8876 | 0.1286 |
<!-- END:10_options_unmet_policy -->

## What the queries do not show
* Nothing here is a measured effect on a business; the company, suppliers, demand and costs are generated.
* Query 07 uses the stored forecast points written by the generator's own models (S-03 concerns the domain's forecast only); query 02 and option 11 follow decision S-04 (closed orders with a partly received line are not on order); R3-04 (position of a product with parameters at one of several locations) is fixed and the snapshot has one home location per product, so no figure here is affected.
* The derived-parameter plan in section 11 differs from the plan of record because the generator's parameters are a formula, not the domain's forecast; the data cannot say which is right.
