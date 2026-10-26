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

## D-03 Demand, censoring and forecasts
* Observed sales are censored during stockouts; the generator publishes latent demand
  separately and the site labels which is shown (P03-DOMAIN-03, P03-TEST-01).
* Baselines first: naive and seasonal-naive (weekly) are always computed; a model only
  counts if it beats seasonal-naive on the same rolling-origin folds (P03-DOMAIN-01, 04).
* A forecast fit at cutoff `c` may use only sales, movements and promotion *schedules*
  known at `c`; promotion outcomes after `c` are never features (P03-TEST-02).
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
  = days with unmet demand ÷ observed days.

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
