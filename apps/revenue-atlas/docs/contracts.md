# Revenue Atlas — business contracts, version 1 (2026-10-26)

Decision owner: coordinator (Fable 5.1). Spec: `projects/01-revenue-atlas.md` at pack
commit `fe5f7981`. Every rule below cites the requirement ID it satisfies. Changing a
rule bumps `CONTRACT_VERSION` in `domain/revenue_atlas/contract.py`, this file, the golden
fixture and the tests together (P01-MET-*-R28, P01-GOLD-11).

## Decision the product supports
Which customer, product, region, or discount policy explains declining contribution
margin? (P01-GOAL-01). Primary user: a revenue analyst preparing a monthly margin review.
Non-goals: statutory revenue recognition, bookings, invoicing, cash (P01-DOMAIN-01/02).

## D-01 Grain, population and time basis
* Fact grain is the **shipment line** (`shipment_line_id`). Every metric is a sum over
  shipment lines or a ratio of two such sums (P01-MET-*-R06, R16).
* Reporting population: shipment lines whose shipment `shipped_at` falls in the half-open
  window `[from, to)` in UTC, whose order status is `shipped` or `partially_returned`,
  excluding quarantined lines. Cancelled orders have no shipment lines and therefore never
  enter the population (P01-TEST-09). Excluded and quarantined counts are returned in
  `meta.exclusions` and shown on screen (P01-MET-*-R11/R12).
* Timestamps are UTC instants; display calendars use a configured IANA zone
  (default `America/New_York`) for labels only (P01-MET-*-R09).
* Returns are recognised on `credit_date` (credit timing is "credit date", not shipment
  date). A window's net sales therefore include credits dated in the window even when the
  shipment is older; the returns desk discloses cohort maturity (P01-MET-08, MET-09).

## D-02 Money, currency and rounding
* All money is `Decimal`; JSON carries decimal strings; database columns are
  `NUMERIC(20,6)` (section 11).
* Each order and shipment carries its currency. Values convert to the reporting currency
  (USD) with the `exchange_rates` row whose `rate_date` equals the shipment's UTC date
  (returns: the credit date). A missing rate **quarantines** the line with reason
  `FX_RATE_MISSING`; it is never replaced by 1.0 or 0 (P01-TEST-04, P01-MET-*-R15).
* Internal precision is six decimals; rounding to cents happens at exactly two steps:
  allocation (discount and freight, see D-04) and presentation (P01-MET-*-R17).

## D-03 Historical cost
* `cost_versions` are half-open validity ranges `[valid_from, valid_to)`; `valid_to` null
  means open. The cost of a shipment line is the single version of its product whose range
  contains `shipped_at`. Zero or more than one matching version quarantines the line with
  `COST_VERSION_AMBIGUOUS` / `COST_VERSION_MISSING` (P01-FLOW-02, P01-TEST-03).
* `shipment_lines.cost_version_id` is set by command C02 and is immutable afterwards;
  a return reverses cost at that same version (`recoverable_return_cost`), never at a
  later price.

## D-04 Allocation of discounts and freight
* Discounts are posted at order-line level. A line's discount is allocated to its shipment
  lines by `shipped_quantity / ordered quantity`, rounded to cents, and any residual cents
  are assigned by largest fractional remainder with the lowest `shipment_line_id` as the
  tie-break, so the allocations sum exactly to the discount.
* Freight: a shipment's `shipping_cost` is allocated over its shipment lines by gross-sales
  weight with the same rounding and remainder rule (P01-FLOW-04 "deterministic remainder
  assignment"). A shipment whose lines have zero gross sales allocates by shipped quantity;
  if that is also zero the freight stays on an explicit `unallocated_freight` row that
  still counts in contribution (P01-TEST-05).
* `allocation_residual = shipping_cost − Σ allocations` must be `0.00` after rounding;
  a non-zero residual fails the reconciliation check and blocks publication
  (P01-MET-12).
* Allocation is keyed by `shipment_line_id`; the allocation table has a unique constraint
  on it, which is how a many-to-many double allocation is detected (P01-TEST-01).
* Margin attribution by customer/product/region is therefore **exact additive**: every
  dollar of discount, cost, credit and freight belongs to exactly one shipment line
  (P01-DOMAIN-05).

## D-05 Metric formulas (P01-MET-01..12 R02)
| Metric | Formula | Zero/empty behaviour |
|---|---|---|
| Gross sales | Σ shipped_quantity × unit_price | 0.00 |
| Net merchandise sales | gross − allocated discounts − merchandise credits | 0.00 |
| COGS | Σ shipped_quantity × historical unit cost − recoverable return cost | 0.00 |
| Gross profit | net − COGS | 0.00 |
| Contribution margin | gross profit + shipping revenue − shipping cost − other variable costs | 0.00 (may be negative) |
| Contribution margin rate | contribution ÷ (net + shipping revenue) | null when denominator 0 |
| Discount rate | allocated discounts ÷ gross sales | null when gross 0 |
| Return rate | returned units ÷ shipped units of the cohort | null when 0 shipped |
| Average order value | net ÷ distinct orders with eligible lines | null when 0 orders |
| Quota attainment | eligible sales ÷ quota for the (rep, period) | null when quota absent or 0 |
| Year-over-year | (current − prior) ÷ \|prior\| | null when prior 0 or absent |
| Allocation residual | shipping total − Σ allocated | must be 0.00 |

Rates are proportions in `[0, 1]` carried to six decimals. Ratios are computed from the
aggregated numerator and denominator, never averaged over rows (P01-MET-07-R04).

## D-06 Workflow invariants (P01-FLOW-01..10 R03)
* C01 ingest: currencies must be ISO-4217 codes from the configured list; a malformed
  currency rejects the order and all its lines, the raw rows are kept in `raw_batches`
  with the rejection reason. Repeating a batch with the same idempotency key and payload
  returns the prior result; the same key with a different payload is a 409.
* C03 partial return: `returned_quantity ≤ shipped_quantity − already returned`; a
  negative credit (`credit_amount < 0`) is rejected with `CREDIT_SIGN_REVERSED`
  (P01-TEST-06, P01-TEST-10). A return dated after a published snapshot's period does not
  alter that snapshot; it appears in the next run with a revision note (P01-TEST-02).
* Region: a customer's region is the `customers` version effective at `shipped_at`
  (`effective_from` versions, type-2). Lines with no customer version resolve to the
  explicit `UNASSIGNED` region, which every regional view shows as its own row
  (P01-TEST-07, P01-TEST-11).
* Quotas join at (rep, period) grain only; they are never joined to transactions
  (P01-TEST-08).
* Scenarios: `scenario_versions` reference an immutable `baseline_run_id`; discount and
  shipping deltas are applied to a copy at calculation time. Historical rows are never
  written by a scenario (P01-FLOW-07/08, P01-TEST-12).
* Exports embed `contract_version`, `dataset_version`, `code_sha`, `generated_at` and the
  applied filters (P01-FLOW-09). Snapshots embed source and build hashes (P01-FLOW-10).

## Mode disclosure
Mode A (verified): the Python domain, PostgreSQL migrations and FastAPI commands run in
GitHub Actions against a transient PostgreSQL service. Mode B (public): the static site
recomputes the same contract in TypeScript over a published synthetic snapshot and keeps
all mutations in browser memory; a reload restores the published fixture.
