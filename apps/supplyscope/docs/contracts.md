# SupplyScope — business contracts, version 1 (2026-10-26)

Decision owner: coordinator (Fable 5.1). Spec: `projects/03-supplyscope.md`, SHA-256
`059c8812…c23d` at pack commit `fe5f7981`. Rules cite the requirement they satisfy; changing one
bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
What should be ordered, when, and under which service and working-capital assumptions?
(P03-GOAL-01). Primary user: an operations analyst preparing a weekly buying plan. Non-goals:
submitting real purchase orders, supplier commitments, live feeds (P03-DOMAIN-06).

## D-01 Ledger, day order and as-of stock
* Stock is the sum of posted `inventory_movements.quantity_delta` per (product, location)
  up to a cutoff instant; movements are immutable events; a duplicate `movement_id` is
  rejected at load (P03-FLOW-01, P03-TEST-04).
* Day order within a date is **receipts, then demand, then review** (P03-DOMAIN-02); the
  simulation and the reconstruction use the same order.
* On hand = Σ posted deltas as of the cutoff (never negative in valuation: a negative
  reconstruction is flagged `NEGATIVE_STOCK` and valued at zero). Available = on hand −
  reserved; reserved is declared per fixture (the golden fixture has no reservations).
  Inventory position = on hand + confirmed on order (open PO lines: ordered − received)
  − backorders; reserved is **not** subtracted from position (P03-TEST-10).
* **Amendment A-1 (T-03-07, R3-04, R3-07).** The position of any scope (product, location, supplier, class, all) is the **sum
  over every (product, location) of that scope** of the unclamped ledger value, plus open orders, minus backorders: it is
  never one parameter row's own figure. A product with parameters at one of several locations therefore reports the product
  total (golden with a second location holding 100: 160); the per-pair rows (reorder point, target, order quantity) stay per
  pair. The position uses the **unclamped** ledger sum: a negative reconstruction is flagged `NEGATIVE_STOCK`, valued at
  zero in on hand and working capital, but its deficit still lowers the position (on hand -60, on order 30, backorders 10:
  position -40). `available` (clamped on hand − reserved) below zero is flagged `NEGATIVE_AVAILABLE` (warning on C02 and
  `GET /metrics`, flag on the pipeline result), not hidden. All sums in SQL are BIGINT/NUMERIC.
* **Amendment A-2 (T-03-07, R3-05).** Instants have microsecond resolution in Python, SQL and TypeScript (the TypeScript
  number is epoch milliseconds with a microsecond fraction; digits finer than a microsecond are truncated).
* **Deferred (R3-07).** The day of a movement is its **UTC** date. Ordering a location's day on that location's own time
  zone (`locations.timezone`) is deferred: it would change which day a late-evening local sale belongs to and needs its own
  golden case. Until then the same UTC rule is used by the ledger, the simulation, the SQL and the TypeScript.

## D-02 Replenishment
* Reorder point = expected lead-time demand + safety stock; lead-time demand uses the
  forecast over the supplier's quoted lead days counted on the supplier calendar
  (closures extend lead time, P03-TEST-05); safety stock = z(service_target) × σ of
  lead-time demand from the rolling-origin residuals.
* Order quantity = pack_round_up(max(target_position − position, MOQ)) when position <
  reorder point, else 0. Golden (P03-GOLD-01): on hand 40, on order 30, backorders 10 →
  position 60; ROP 70, target 120 → raw 60; MOQ 50, pack 24 → 72; position 80 → 0.
* A draft order is a recommendation row (`status: draft`); nothing ever becomes a supplier
  commitment; export is CSV only (P03-FLOW-10).
* **Amendment A-3 (T-03-07, R3-06, S-02).** A parameter row with `target_position` below `reorder_point` is rejected at ingest
  (`REPLENISHMENT_PARAMS_INVALID`; the raw row is kept and the pair is "not evaluated", never an order) and refused by C05
  (422, same rule id, nothing written). Target equal to the reorder point is valid. Ingest loads **suppliers before
  products**, so a product row may carry a `supplier_id` (an unknown supplier is still `UNKNOWN_REFERENCE`).

## D-03 Demand, censoring and forecasts
* Observed sales are censored during stockouts; the generator publishes latent demand
  separately and the site labels which is shown (P03-DOMAIN-03, P03-TEST-01).
* Baselines first: naive and seasonal-naive (weekly) are always computed; a model only
  counts if it beats seasonal-naive on the same rolling-origin folds (P03-DOMAIN-01, 04).
* A forecast fit at cutoff `c` may use only sales, movements and promotion *schedules*
  known at `c`; promotion outcomes after `c` are never features (P03-TEST-02). **Amendment (T-03-07, S-03):** a promotion
  covering a day multiplies the EWMA level by `1 + planned_uplift` (0.5 gives 1.5), not by `planned_uplift`; several
  promotions on a day multiply. Python and TypeScript agree. The generator's published forecast points come from its own
  models and are not regenerated from the domain.
* MAE = mean |actual − forecast|; WAPE = Σ|error| ÷ Σ actual, null when Σ actual = 0
  (intermittent SKUs reported with their zero-demand folds disclosed, P03-TEST-06).

## D-04 Receipts, suppliers and unmet demand
* A receipt before its order date is rejected (`RECEIPT_BEFORE_ORDER`, P03-TEST-11); a
  partial receipt leaves the line open (ordered − received > 0) and is never counted as
  complete (P03-TEST-07).
* Supplier on-time rate = receipts within promised deadline ÷ eligible receipts, computed
  only from receipts dated ≤ cutoff (no future leakage, P03-FLOW-09).
* Unmet demand follows the scenario's policy, lost sale **or** backlog, never both
  (P03-TEST-08). Fill rate = immediately fulfilled units ÷ requested units; stockout days
  = days with unmet demand ÷ observed days (**redefined by Amendment A-4 below**).
* **Amendment A-4 (T-03-07, R3-01).** `stockout_days` is a **SKU-day rate**: Σ over active (product, location) pairs of the
  dates on which unmet demand opened for that pair ÷ Σ over those pairs of the calendar days observed in the window. A pair is
  active at `as_of` when it has a movement, a sale or an unmet-demand row by then. Numerators (`stockout_day_count`, now the
  count of SKU-days) and denominators (`observed_sku_days` = active pairs × `observed_days`) add across groups, so groups
  reconcile to the total. The calendar-day figure, dates with unmet demand on **any** pair ÷ calendar days, is the separate key
  `stockout_calendar_days_share` (`observed_days` stays the calendar days). With one pair both are the same number: the
  golden value `0.032258` = 1/31 holds. The two keys are additive to the fixture: `expected.json` keeps exactly its 24 keys;
  `compute_metrics` returns them first and `EXTRA_METRIC_KEYS` after (TypeScript: `computeMetrics` returns the 24,
  `computeMetricsFull` adds the two). The overview tile and the definitions label which is which. On the snapshot:
  431 / 32,880 = 0.013108 (SKU-days) against 290 / 548 = 0.529197 (calendar days).
* **Amendment A-5 (T-03-07, R3-02).** Unmet-demand rows recorded under a scenario (C07, `scenario_id` not null) are
  what-if rows and are **not canonical**: they are excluded from `inventory_position`, backorders, unmet units, fill rate and
  stockout days, from replenishment (C05) and from the default `/data/backorders` and `/data/lost_sales` reads, unless the
  scenario is asked for (`GET /metrics?scenario=<id>` adds that scenario's rows to the canonical ones;
  `GET /data/backorders?scenario_id=<id>` lists them). C07 requires `occurred_at` (422 when missing; it is never defaulted to
  the server clock) and, when `demand_ref` is absent, derives it from (product, location, occurred_at): the scenario and the
  quantity are not part of the event. The same event under two scenarios is therefore one demand: the other kind is
  `409 UNMET_POLICY_CONFLICT`, the same kind `409 UNMET_ALREADY_RECORDED` (lost sale XOR backlog holds across scenarios).

## D-05 Simulation and policies
* Policies are compared on common random numbers: the same seed drives demand and lead
  times for every policy (P03-FLOW-08, P03-TEST-09); warm-up days and replications are
  declared in `policy_scenarios` (P03-DOMAIN-05).
* Working capital = Σ on_hand × unit_cost at the cost in force on the valuation date
  (cost versions by date; a change within the period values each day at its own cost,
  P03-TEST-12). Turnover = annualised COGS ÷ average inventory value (daily average).

## Mode disclosure
Mode A: Python domain + PostgreSQL + FastAPI verified on GitHub-hosted runners. Mode B:
TypeScript re-implementation over the published snapshot; the simulator runs in the browser
on a copy with the published seed; nothing is persisted.

## D-06 Fixture-driven clarifications (2026-10-26, adopted from A-020)
Requested demand = immediately fulfilled sales + backorders opened in the window; a stockout
day is a date on which a backorder opened; raw, MOQ and pack quantities are 0 when the reorder
is not triggered (position ≥ reorder point); with no replenishment parameters the replenishment
fields are null ("not evaluated"); exact replays of a movement id are rejected as
`DUPLICATE_MOVEMENT_ID` with the first occurrence kept.

## D-07 Dataset version and stale drafts (2026-10-26, T-03-07, R3-03)
* **Dataset version.** Every command names the `dataset_version` it was prepared against. When `dataset_versions` has a current
  row (the newest by `created_at`) and the request's value differs, the command answers `409 STALE_DATASET_VERSION` (details
  carry `current` and `requested`) and writes nothing. With no `dataset_versions` row there is nothing to be stale against and
  the request is accepted. The check runs after the idempotency lookup, so a stored command replays with its stored answer.
  A command that loads movements does not mint a new dataset version (the version names a seeded dataset, not the ledger's
  state); ledger staleness is what the next rule covers.
* **Stale drafts.** A draft order stores the position, reorder point, target and quantity of the as-of it was calculated at.
  C10 `export-buying-plan` re-evaluates every selected draft against the **current** ledger, parameters and orders at the
  draft's own as-of (same arithmetic as C05, scenario's service target for derived parameters). A draft is exported with
  `status = draft` only when it is still triggered and its inventory position and order quantity equal the stored ones;
  otherwise it is exported with `status = stale` (its own figures kept, the recomputed ones in the new columns
  `current_inventory_position`, `current_order_quantity`; an unevaluable pair has them empty), is listed in `stale_draft_order_ids`,
  and carries a `STALE_DRAFT` warning. A stale row is a recommendation that must be recalculated (C05), never an order. The
  `draft_orders` table is not modified by the export (the table's status check allows only `draft`); C05 for the same as-of
  withdraws a draft that is no longer triggered.
* **Header.** The CSV header gains `# stale_rows: <n>` and `# ledger_latest_movement_at: <instant of the newest movement in
  the ledger, or ->`, so a reader can see which ledger state the check ran against; the result carries `stale_count` and
  `ledger_latest_movement_at`.
* **Not decided here.** Whether a draft whose as-of is far in the past should be refused rather than marked stale; whether
  a ledger change should mint a dataset version.

**Contract version after T-03-07 (coordinator decision).** `CONTRACT_VERSION` stays `v1`: the input contract and every
golden value are unchanged, `stockout_days` is corrected to the definition D-04 always named (SKU-days), and the two new
metric keys are additive. Clients reading the old calendar-day figure find it under `stockout_calendar_days_share`.
