# SupplyScope — user-acceptance evidence (T-03-07, 2026-10-26)

What was attacked, what the system answered, and which test holds the answer. Two sources: the adversarial suite
(`tests/test_adversarial.py`, one test per P03-TEST id plus protocol attacks) and the fixes for the master-18 reviewer
findings R3-01..R3-07 and the worker findings S-02 and S-03 (`tests/test_review_findings.py`,
`web/scripts/review-check.ts`). Decisions are in `contracts.md` (D-01 A-1/A-2, D-02 A-3, D-03, D-04 A-4/A-5, D-07).
Hosted CI has **not** run on this change; the commands below ran locally (Postgres 16 on 127.0.0.1, Python 3.11, Node).

## 1. Adversarial suite (through the API, the database and the pure domain)

| Attack | Required answer | Test |
|---|---|---|
| Sales observed during a stockout presented as demand (P03-TEST-01) | latent demand stays a separate entity; fill rate uses requested = fulfilled + unmet only | `test_p03_test_01_censored_sales_are_not_latent_demand` |
| A forecast that peeks at a promotion outcome after the cutoff (P03-TEST-02) | the outcome is never a feature; schedule announced by the cutoff only | `test_p03_test_02_forecast_at_cutoff_ignores_later_promotion_outcomes` |
| Replaying a sale to drive stock negative (P03-TEST-04) | replay rejected `DUPLICATE_MOVEMENT_ID`, other payload `DUPLICATE_MOVEMENT_CONFLICT`; the table also refuses update, delete and a second insert | `test_p03_test_04_duplicate_movement_cannot_drive_stock_negative` |
| Supplier closure ignored in the lead time (P03-TEST-05) | closure days do not count; the reorder point rises | `test_p03_test_05_supplier_closure_lengthens_the_lead_time_and_the_reorder_point` |
| Intermittent SKU with zero-demand folds (P03-TEST-06) | WAPE null, folds disclosed | `test_p03_test_06_intermittent_sku_has_null_wape_over_the_api` |
| Partial receipt treated as complete (P03-TEST-07) | the line stays open; over-receipt 422 | `test_p03_test_07_partial_receipt_never_completes_the_line` |
| The same demand as lost sale and backlog, also raced (P03-TEST-08) | 409 `UNMET_POLICY_CONFLICT`; of two racing policies exactly one wins | `test_p03_test_08_lost_sale_xor_backlog_even_when_forced` |
| Policies compared on different seeds (P03-TEST-09) | refused `POLICY_SEED_MISMATCH` | `test_p03_test_09_policies_with_different_seeds_are_refused` |
| Reserved stock subtracted from the position twice (P03-TEST-10) | reserved is not in the position | `test_p03_test_10_reserved_stock_is_never_subtracted_twice` |
| Receipt dated before its order (P03-TEST-11) | rejected in ingest, C06 and the table | `test_p03_test_11_receipt_before_the_order_is_refused_everywhere` |
| Cost change inside the valuation period (P03-TEST-12) | each day valued at the cost in force | `test_p03_test_12_cost_change_inside_the_valuation_period` |
| Deadlock, the same key raced, concurrent receipts and loads | retried then 409, never 500; one execution; no over-receipt; no duplicate | `test_a_deadlock_is_retried_then_409_never_500`, `test_pairs_are_locked_in_sorted_order`, `test_the_same_key_raced_runs_the_command_once`, `test_concurrent_receipts_cannot_over_receive_a_line`, `test_two_batches_loading_the_same_ids_never_500_and_never_duplicate` |
| A failing command | no receipt, movement, audit row or stored result remains | `test_a_failed_command_leaves_no_trace` |
| Odd bodies (floats as ints, NaN, NUL, broken JSON) | 422, never 500 | `test_odd_inputs_are_422_not_500` |
| Anything that could become a purchase order | no PO is created; a draft's status is always `draft` (table check) | `test_commands_never_create_a_purchase_order_or_a_non_draft` |

## 2. Reviewer findings (ledger entry "master 18 reviewer disproof pass (SupplyScope)", code `12f866f`)

Before values are the reviewer's, except where marked *measured*: I ran the old code or the old SQL (`git show HEAD:`) for those.
Python, SQL and TypeScript were compared on the reviewer's 18 cases (scratch `cmp`): no difference on any case after the fixes.

| Finding | Before | After | Python / API test | TypeScript check |
|---|---|---|---|---|
| R3-01 stockout days | 290 / 548 = 0.529197 called SKU-days; groups 370 / 373 / 431 against 290 | `stockout_days` = 431 / (60 x 548) = 0.013108 (*measured* on the snapshot); `stockout_calendar_days_share` = 0.529197 is its own key; golden still 1 / 31 = 0.032258; two pairs one stockout 1 / 62 = 0.016129; group pair-days and SKU-days add to the total | `test_R3_01_stockout_days_is_a_sku_day_rate_and_the_golden_value_holds`, `..._two_pairs_one_stockout_gives_half_the_rate_...`, `..._groups_reconcile_to_the_total`, `..._sql_reference_agrees` | "R3-01 ..." (11) |
| R3-02 C07 | the same event under two scenarios recorded as backlog and lost sale (200 and 200); scenario backorders lowered the canonical position; `occurred_at` defaulted to now | second kind 409 `UNMET_POLICY_CONFLICT`, same kind 409 `UNMET_ALREADY_RECORDED`; canonical position stays 60 with 25 + 7 units recorded under scenarios (35 under `?scenario=`); missing `occurred_at` 422 (reviewer repro `api_unmet.py` re-run) | `test_R3_02_the_same_event_under_two_scenarios_is_a_conflict_not_two_kinds`, `..._scenario_backorders_never_change_the_canonical_position`, `..._occurred_at_is_required` | "R3-02 ..." (4) |
| R3-03 stale draft and `dataset_version` | export after +100 receipt: row `draft`, quantity 72 although position is 160 and nothing is triggered; any `dataset_version` accepted | export row `stale` with `current_inventory_position` 160 and `current_order_quantity` 0, `# stale_rows: 1`, `# ledger_latest_movement_at`; wrong `dataset_version` 409 `STALE_DATASET_VERSION`, nothing written (reviewer repro `api_stale.py` re-run) | `test_R3_03_a_stale_dataset_version_is_409_and_writes_nothing`, `..._export_marks_a_draft_stale_when_the_ledger_moved_under_it` | server-side only |
| R3-04 multi-location position | 60 (the parameter row's own) in Python, TypeScript and SQL | 160 (60 + 100) in all three; by location 60 and 100; per-pair ROP 70 and quantity 72 unchanged | `test_R3_04_position_of_a_product_with_parameters_at_one_of_two_locations_is_the_product_total`, `..._over_the_api_...` | "R3-04 ..." (3) |
| R3-05 sub-millisecond instants | TypeScript on hand 47, Python and SQL 40 (movement 0.4 ms after the cutoff) | 40 in all three; `submilli2` 47 in all three; instants are ordered at microsecond resolution | `test_R3_05_sub_millisecond_instants_keep_their_microseconds`, `..._sql_orders_microseconds_like_the_domain` | "R3-05 ..." (7) |
| R3-06 target below ROP | accepted; ROP 70 / target 50 still ordered | row rejected `REPLENISHMENT_PARAMS_INVALID`, pair not evaluated, no order; target = ROP accepted; C05 on a row altered in the database 422 and no draft | `test_R3_06_ingest_rejects_a_target_below_the_reorder_point`, `..._calculate_replenishment_refuses_a_row_that_is_below_its_own_reorder_point` | "R3-06 ..." (3) |
| R3-07 negative available, clamping, int4 | reserved 500 on 40 on hand: available -460, no flag; on hand -60 entered the position as 0 (position 20, *derived*); SQL `integer out of range` on 12 x 10^9 units (*measured*) | `NEGATIVE_AVAILABLE` flag (pipeline, C02, `GET /metrics`); position -40 with `NEGATIVE_STOCK` still flagged and on hand valued at 0; order 168; SQL BIGINT: on hand 20,000,000,040 and position 20,000,000,060 equal the domain | `test_R3_07_available_below_zero_is_flagged`, `..._the_position_uses_the_unclamped_ledger_value`, `..._sql_sums_are_bigint_and_agree` | "R3-07 ..." (6) |
| S-02 supplier order | a product with `supplier_id` rejected `UNKNOWN_REFERENCE` | accepted; unknown supplier still rejected | `test_S_02_a_product_with_a_supplier_id_is_accepted` | "S-02 ..." (2) |
| S-03 promotion factor | 0.5 for a 0.5 uplift | 1.5 (3/2); two promotions 9/4; outside the window or not yet announced 1 | `test_S_03_promo_factor_is_one_plus_the_planned_uplift` | "S-03 ..." (4) |

Side effects that are numbers in the artifacts: the derived reorder point / target of `prod-002` at 0.90 and 0.95 and of `prod-005`
at 0.90 moved by 1 to 3 units (99 / 142 to 102 / 145, 107 / 150 to 109 / 152, 47 / 95 to 48 / 96), because those options use the
domain forecast; `artifacts/analysis-results.json`, `docs/sql-analysis.md` and `docs/bi-package.md` were re-rendered from a fresh
`run_all.py` run (RESULT: OK, 91 reconciliation rows, four more than before), the workbook rebuilt and recalculated with LibreOffice,
`artifacts/CHECKSUMS.txt` and the table in `release-package.md` regenerated. The generator's published forecast files are not
regenerated: `data/generate.py` has its own models and does not call the domain forecast.

## 3. Commands run (this change, local)

| Command | Exit | Result |
|---|---|---|
| `python tests/reference_check.py` | 0 | ALL OK (golden fixtures and hashes untouched) |
| `DATABASE_URL=... pytest -q` | 0 | 176 passed, 1 skipped (the rerun of the analysis SQL needs `ARTIFACTS_DATABASE_URL`, as before) |
| `cd web && npm run check` | 0 | typecheck; golden 221 checks; review 40 checks |
| `cd web && npm run build:pages` | 0 | built, 11 routes |
| `cd web && npm run e2e` | 0 | 36 passed |
| `data/sql/analysis/run_all.py` against a prepared snapshot and golden schema | 0 | RESULT: OK, 91 rows equal |

## 4. Limits of this evidence

* The table columns `stock_snapshots` and `draft_orders.inventory_position` are still `INT`; the domain bounds one movement at 10^9, so
  a pair above about 2 x 10^9 units would fail on C02 with a database error. Only the reference SQL was widened (R3-07 scope).
* The day of a movement is its UTC date; the location's time zone is deferred (D-01).
* `CONTRACT_VERSION` stays `v1`: the input contract and the golden fixture are unchanged and the metric set gained two keys.
  Whether the redefinition of `stockout_days` should bump the version is the coordinator's decision.
* Not re-run: the hosted CI workflow, the live-check workflow, the ledger entry. The narrative documents were edited only where a
  sentence had become false (open-finding statements and the 87 to 91 count); they were not re-reviewed.
