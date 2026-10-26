# Technical case study: SupplyScope (P03-ART-09)

A synthetic inventory-analytics product built around one question: what should be ordered, when, and under which service and working-capital assumptions (P03-GOAL-01). It is a **business-data lab** project, not a customer system: all data is generated, there are no live feeds, no real purchase orders and no supplier commitments (P03-DOMAIN-06), and no result describes a real business.

## Architecture
```mermaid
flowchart LR
  G[generate.py seed 20261026] --> S[(web/public/data snapshot JSON, 60 SKUs x 548 days)]
  S --> TS[Mode B: TypeScript domain in the browser, nothing persisted]
  S --> SEED[data/seed.py via validate_batch]
  SEED --> PG[(PostgreSQL 16, two plain-SQL migrations, 28 tables and schema_migrations)]
  API[FastAPI commands C01-C03, C05-C10 + reads + metrics] --> PG
  PY[Python domain: ledger, replenishment, demand, forecast, suppliers, metrics] --> API
  PY --> SEED
  PG --> REF[reference_metrics.sql: independent SQL recomputation]
  PG --> AN[analysis SQL 00-09: month-end, grain and cutoff queries]
  ORACLE[tests/reference_check.py: stdlib oracle over the golden fixture] -.-> PY
  TS --> PAGES[GitHub Pages: labs/supplyscope]
```
* **Mode A (verified on hosted runners):** the standard-library Python domain (`domain/supplyscope`), PostgreSQL migrations (`data/migrations`), FastAPI commands and reads (`api/`), prefix `/api/v1/supplyscope`. Not served by GitHub Pages.
* **Mode B (public):** the same contract in TypeScript (`web/src/domain`) over the published snapshot; the simulator runs in the browser on a copy with the published seed and nothing is persisted.
* **One contract** (`docs/contracts.md`, v1, D-01..D-06) with a **golden fixture** whose answers are hand-derived (`tests/fixtures/golden/CALCULATION.md`: on hand 40, on order 30, backorders 10, position 60; ROP 70, target 120, raw 60, MOQ 50, pack 24, order 72; position 80 gives 0).
* **Independent implementations of the same numbers:** the Python domain, the TypeScript domain, `data/sql/reference_metrics.sql`, the analysis SQL (`data/sql/analysis`), the stdlib oracle `tests/reference_check.py`, and the workbook's spreadsheet formulas for the golden case. They check each other (`sql-analysis.md` section 10: 87 reconciliation rows, all equal).

## Tradeoffs
* **The day order (D-01).** Inside a date the order is receipts, then demand, then review; the sort key is (UTC date, type rank, `event_at`, `movement_id`) and the simulation and the reconstruction use the same one. In the golden ledger a sale stamped 09:00 and a receipt stamped 15:00 fall on the same date: by timestamp the stock reaches -35 (`timestamp_order_stock_min`), in day order it goes 0 -> 35 -> 0.
  Cost: a movement's place depends on its UTC date, not its local time (open finding R3-07 notes day order on the UTC date); a late-posted receipt is "on time" by construction. Benefit: a negative reconstruction becomes a flag (`NEGATIVE_STOCK`, valued at zero) instead of an artefact of clock order, and every implementation agrees (the workbook shows both orders side by side).
* **Position, not availability (D-01, P03-TEST-10).** Inventory position = on hand + confirmed on order - backorders; available = on hand - reserved; reserved is not subtracted from the position. A naive position that subtracts it counts the same units twice (INJ-07 plants six open reservations of 25 % of closing stock). Cost: two numbers to explain. Benefit: the reorder trigger measures supply, not what is promised.
* **Baselines first (D-03).** Naive and seasonal-naive (period 7) are always computed; the EWMA model is selected, and reported as beating them, only when its MAE is lower on the same rolling-origin folds. WAPE is null when the actuals sum to zero and the zero-demand folds of the intermittent SKUs are disclosed (`ZERO_DEMAND_FOLDS_DISCLOSED`). Cost: a model that cannot beat a weekly repeat is not used even when it is more elaborate. Benefit: a forecast is never presented without the thing it has to beat; query 07 shows `ewma` losing for 3 of 14 SKUs.
* **Information cutoff (D-03, P03-TEST-02).** A forecast fit at cutoff `c` uses sales and movements known at `c` and promotion *schedules* announced by `c`; `realised_uplift` is an outcome and never a feature; a cutoff after the data end is 422. The supplier on-time rate is computed only from receipts dated up to the cutoff (P03-FLOW-09). Cost: results are reproducible only with their cutoff printed. Benefit: no hindsight; query 04 is checked cell by cell against the domain at 18 cutoffs.
* **Latent demand published separately (D-03).** Observed sales are censored during stockouts, so the generator publishes latent demand as a separate file and the site labels which one is shown. Cost: the product has data it must never use as a feature. Benefit: the censoring can be measured (query 05: 2,423 latent units unseen, equal to the recorded unmet demand).
* **Immutable ledger, draft orders (D-01, D-02).** A posted movement is an event: triggers refuse UPDATE, DELETE and TRUNCATE; a replay of a movement id is rejected at load and by a unique key. A draft order is a recommendation row whose status is always `draft` (CHECK), exported as CSV and never a purchase order. Cost: corrections are new movements. Benefit: the as-of reconstruction is reproducible for any past instant.
* **Different methods for independent checks.** `reference_metrics.sql` recomputes the golden numbers with no code shared with the domain; the analysis SQL uses window sums and calendar generation where the reference uses sub-selects; the workbook uses `SUMPRODUCT` over serials. One wrong idea is unlikely to be shared by all of them.
* **Idempotent commands with an audit written in the same transaction** (next section). Cost: a result table and an advisory lock per key. Benefit: a retry is safe and a failed command leaves no trace.

## Recovery behaviour (observed in tests)
| Situation | Behaviour | Test |
|---|---|---|
| A receipt dated before its order | 422 `VALIDATION_FAILED` with rule `RECEIPT_BEFORE_ORDER`; the database trigger refuses the same row | `test_c06_receipt_rules`, `test_p03_test_11_receipt_before_the_order_is_refused_everywhere` |
| A receipt before the lead time on the supplier calendar | 422 rule `RECEIPT_BEFORE_LEAD_TIME` with the earliest date; a closure pushes it later | `test_c06_receipt_rules`, `test_c06_a_supplier_closure_pushes_the_earliest_receipt` |
| A receipt that would exceed the ordered quantity, also under concurrency | 422 `RECEIPT_EXCEEDS_ORDERED`; the line is locked `FOR UPDATE`, so two concurrent receipts cannot both fit | `test_concurrent_receipts_cannot_over_receive_a_line` |
| A partial receipt | accepted; the line stays open and is never counted complete | `test_c06_partial_arrival_keeps_the_line_open_and_posts_stock`, `test_p03_test_07_*` |
| Replay of a movement id | rejected `DUPLICATE_MOVEMENT_ID`, the first occurrence is kept and stock cannot go negative; the raw row is kept in `rejected_records` | `test_c01_load_validates_keeps_raw_rows_and_rejects_replays`, `test_p03_test_04_*` |
| The same unmet demand as a backorder and a lost sale | 409 `UNMET_POLICY_CONFLICT` from the `demand_ref` trigger; the scenario policy picks exactly one kind | `test_c07_the_scenario_policy_chooses_exactly_one_kind`, `test_p03_test_08_*` |
| Policies with different seeds compared | refused (`POLICY_SEED_MISMATCH`) | `test_p03_test_09_*` |
| Forecast cutoff after the dataset end | 422 | `test_c03_cutoff_after_the_dataset_end_is_422` |
| Odd inputs (bad dates, out-of-range numbers, long keys) | 422 `VALIDATION_FAILED`, never 500 | `test_odd_inputs_are_422_not_500` |
| Same idempotency key and payload | the stored result is returned with `Idempotent-Replay: true`; another payload or another actor is 409 `IDEMPOTENCY_KEY_REUSED`; an equal instant spelled `+00:00` replays | `test_idempotency_replay_is_actor_bound_and_instant_normalised`, `test_the_same_key_raced_runs_the_command_once` |
| A deadlock between commands | the attempt is rolled back and retried up to 3 times, then 409 `CONCURRENT_UPDATE`, never 500; locks are taken in sorted pair order | `test_a_deadlock_is_retried_then_409_never_500`, `test_pairs_are_locked_in_sorted_order` |
| Any failed command | no partial write and no audit row: the handler, the `audit_events` row and the `command_results` row are one transaction | `test_a_failed_command_leaves_no_trace` |
| A database rule violated inside a command (trigger, unique key) | mapped to a 409 with a stable code (`INTEGRITY_RULE`, `ALREADY_EXISTS`), never a 500 | `api/commands.py` `execute` |
| Classify SKUs (C04) | 501 `NOT_IMPLEMENTED` (extension milestone) | `test_c04_is_not_implemented_and_says_so` |
| A command that tries to make a purchase order or a non-draft | cannot: status is always `draft` (CHECK) and export is CSV text | `test_commands_never_create_a_purchase_order_or_a_non_draft` |

Error envelope: `{error: {code, message, details[]}, request_id}`; `details[].rule_id` carries the domain reason code. Commands need `X-Actor-Id` and `X-Actor-Role` (`planner`, `buyer`, `admin`): 401 without an id, 403 for another role.

## Reproducible setup
```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt            # Mode A; add -r requirements-artifacts.txt for the workbook
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<scratch db>
python data/migrate.py && python data/seed.py tests/fixtures/golden/inputs.json
python data/generate.py --seed 20261026 --out web/public/data               # deterministic: dataset_hash 5bdabb50...bcc8c
python -I tests/reference_check.py                                           # stdlib oracle, ALL OK
python -m pytest -q                                                          # database tests skip cleanly without DATABASE_URL
(cd web && npm ci && npm run check && npm run e2e)                           # Mode B: typecheck + 221 golden checks; Playwright
# artifacts
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py && ../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json
../../.venv/bin/python artifacts/build_workbook.py --recalc && ../../.venv/bin/python -m pytest -q tests/test_artifacts.py
```
Tests that reset the schema must run against a scratch database, never one that holds work in progress (`tests/support_db.py` drops the project's tables). This artifact pass used its own scratch databases and never the shared `supplyscope` one.

## Measured evidence
Hosted runs and ledger entries (`docs/program/verification-ledger.json`):

| Evidence | Result | Code | Run |
|---|---|---|---|
| Mode A CI: reference check ALL OK (184 checks); 110 tests with `postgres:16` | success | `8a35c0b` | https://github.com/mrrishit909/projects-site/actions/runs/40340745348 |
| Generator determinism, 22 generator tests, injected defects detected, designed relationships; 132 tests after the latent-demand ingest fix (S-01) | hash `5bdabb50...bcc8c` reproduced; `sup-03` on-time 0.681 against 0.83-0.86; `loc-02` fill 0.888 against 0.955 and 0.965 | `7b8d208` | https://github.com/mrrishit909/projects-site/actions/runs/40343593698 |
| Mode A (132 tests) and Mode B (221 TypeScript golden checks, 36 Playwright tests at 360/768/1280/1920, 200 % zoom, no overflow, screenshots) | both jobs success | `a4a4364` | https://github.com/mrrishit909/projects-site/actions/runs/40348560761 |
| Live site: every route and `data/manifest.json` served, case study live | success | site from `12f866f` | https://github.com/mrrishit909/projects-site/actions/runs/40347873614 |
| Portfolio case study links to the site and the site links back; all three sites re-verified | success | manifest commit | https://github.com/mrrishit909/projects-site/actions/runs/40348856013 |

Measured in this artifact pass (local, 2026-10-26, on scratch PostgreSQL 16 databases): the existing suite, 132 passed (`pytest -q`, 69 s); `python3 -I tests/reference_check.py` ALL OK; the ten analysis SQL files, `00_ledger_views.sql` and the two BI export queries run with `psql -v ON_ERROR_STOP=1` (exit 0);
`run_all.py` exit 0 with 87 reconciliation rows all equal, including the golden position and order (60 and 72 from the analysis SQL, `reference_metrics.sql` and the Python domain, and 80 and 0 for the position-80 state); the workbook recalculated by LibreOffice headless, also with its switch flipped and with the as-of moved, to prove the formulas are live; `tests/test_artifacts.py` (the artifact package; the count is in `release-package.md`).
Excel and Power BI Desktop were not run; no `.pbix` exists.

## Open gaps
* **Defects and decisions found while building:** **S-02** (`validate_batch` loads `products` before `suppliers`, so `products.supplier_id` is omitted and the supplier lives on `replenishment_params`); **S-03** (the promotion factor of the EWMA applies `planned_uplift` instead of `1 + uplift`, in Python and mirrored in TypeScript; the ledger status is **failed**, fix queued in T-03-07); **S-04** (decision: closed purchase orders with a partly received line are not on order, consistent with D-01 "confirmed"; 72 units in the snapshot). S-01 (latent demand deduplicated by product only) is fixed and verified.
* **Reviewer findings R3-01..R3-07** (ledger entry 2026-10-26T15:22:44Z, status **failed**, fix task T-03-07 pending): R3-01 the case-study text calls the stockout metric SKU-days, but it is distinct calendar dates over calendar days (290 / 548 = 0.529197; the SKU-day rate is 431 / (60 x 548) = 1.3 %; groups do not reconcile); R3-02 C07 can record the same unmet event under two scenarios without a `demand_ref`, scenario backorders lower the real position, and `occurred_at` defaults to now; R3-03 C10 exports a stale draft after later movements and never validates `dataset_version`; R3-04 the position of a product with parameters at one of several locations is reported as the total (no effect on the snapshot, one home location per product); R3-05 sub-millisecond instants differ between TypeScript and Python/SQL; suspected R3-06 `target < ROP` is accepted and still orders; suspected R3-07 negative available is unflagged, the clamped on-hand enters the position, SQL `int4` overflow, day order on the UTC date. None is fixed in this package.
* **Stubs:** C04 classify-skus returns 501; the TypeScript domain and the web views cover the slice (overview, SKU trajectory, forecast evaluation, reorder workbench, case study) and the SQL/BI/workbook artifacts do not replace them.
* **Simulation:** the policy comparison is a compact (s, S) loop; its statistical quality has not been assessed by the reviewer.
* **Artifacts:** the workbook covers the golden case only; no Excel run; the Power BI model is a design with no `.pbix`; the analysis is one seed with no confidence intervals; the derived-parameter options in `sql-analysis.md` section 11 depend on the forecast that carries S-03.
