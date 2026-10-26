# Revenue Atlas — business contracts, version 1.1 (2026-10-26)

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

### D-01a (2026-10-26): window semantics for returns (contract v1.1)
Decision note, supersedes the unspecified windowing of v1 (UAT defect G-01). A window selects
shipment lines by `shipped_at` and return credits by `credit_date`; the return_rate denominator
is shipped units in the window, its numerator returned units with credit_date in the window
(disclosed as cohort-mixing on the returns desk).

Exact rule for a window `[from, to)` (a missing bound is unbounded; no window means everything counts):
* gross sales, allocated discounts, COGS before returns, shipping cost, shipped units, eligible
  orders and shipment lines: lines whose shipment `shipped_at` is in the window;
* merchandise credits, recoverable return cost and returned units: accepted returns whose
  `credit_date` is in the window, read as 00:00 UTC of that date, whatever the shipped_at of their
  line (the line must be in the population, i.e. not quarantined or excluded);
* a credit dated after a window therefore does not change that window (a closed period stays
  closed) and appears in the window that contains its credit date, even when that window has no
  shipments (gross 0.00, net equal to minus the credit; return rate null while shipped units are 0);
* the return is still validated and costed at its line's own cost version and credit-date FX (D-02, D-03);
* implemented identically in `metrics.compute_metrics`, `data/sql/reference_totals.sql` and
  `web/src/domain/metrics.ts`; `CONTRACT_VERSION` is `v1.1`. Input batches that declare `"contract": "v1"` keep
  loading (same shape).

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
* Margin attribution is **exactly additive in the source currency**: every unit of discount, cost, credit and
  freight belongs to exactly one shipment line. Freight no line can carry stays on the explicit unallocated
  freight (see D-08: grouped results show it as the `UNALLOCATED` group, so grouped shipping cost sums to the total).
* **Known limitation R-05 (reviewer finding, behaviour deliberately not changed).** Money is converted to the
  reporting currency per shipment line at full precision and rounded to cents only for presentation (D-02), so
  *converted* sums over groups that are each rounded to cents can differ from the rounded overall total by a few
  cents. Observed on the published snapshot: product-level gross sales add up to 9,651,206.92 against the overall
  9,651,206.89; on the reviewer's EUR fixture product net sales add up to 302.15 against 302.16 and COGS to
  64.12 against 64.11. The ungrouped total is the exact figure; grouped views are labelled "may differ by cents
  after conversion". Not a defect of the allocation (which is exact in cents per line) but of per-group presentation
  rounding; the remedy (carry grouped values unrounded, or largest-remainder the rounding across groups) is left
  for a later contract version.

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

Contribution margin rate and year-over-year may be negative (contribution below zero, or a fall
against the prior period). Discount rate and return rate are proportions in `[0, 1]`
(return rate can exceed 1 only in a window whose credits belong to earlier cohorts, D-01a).
All rates are carried to six decimals. Ratios are computed from the
aggregated numerator and denominator, never averaged over rows (P01-MET-07-R04).

## D-06 Workflow invariants (P01-FLOW-01..10 R03)
* C01 ingest: currencies must be ISO-4217 codes from the configured list; a malformed
  currency rejects the order and all its lines, the raw rows are kept in `raw_batches`
  with the rejection reason. Repeating a batch with the same idempotency key and payload
  returns the prior result; the same key with a different payload is a 409.
* C03 partial return: `returned_quantity ≤ shipped_quantity − already returned`; a
  negative credit (`credit_amount < 0`, including negative zero `-0.00`, D-08) is rejected with
  `CREDIT_SIGN_REVERSED` (P01-TEST-06, P01-TEST-10). A return dated after a published snapshot's period does not
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

## D-07 Scenario deltas (added 2026-10-26 with the web slice)
A scenario holds signed decimal fractions `discount_delta` and `shipping_delta`. They apply
to a copy of the baseline facts as `allocated_discount × (1 + discount_delta)` and
`freight × (1 + shipping_delta)`; merchandise credits and costs are not rescaled. Scenario
results are always labelled estimates and shown beside, never instead of, observed results
(P01-MET-*-R24, P01-FLOW-07/08).

## D-08 Ingest invariants, discount and freight persistence (added 2026-10-26, review findings R-01..R-08)
Decision note, T-01-13. The metric formulas are unchanged, so `CONTRACT_VERSION` stays `v1.1` and the golden fixture
is untouched; what changes is which inputs are accepted and what C04 persists. Implemented in the Python domain
(`ingest.py`), TypeScript (`ingest.ts`), PostgreSQL (migration `0003_shipment_invariants.sql`) and `api/commands.py`.
* **R-01 shipped never exceeds ordered.** For every order line the total `shipped_quantity` over its shipment lines
  must be at most `order_lines.quantity`. A violating order line is rejected at C01 with `SHIPPED_EXCEEDS_ORDERED`
  together with its discounts, its shipment lines and their returns (dependent rejection, same pattern as the
  currency rule; raw rows kept in `rejected_records`). Rows already rejected for a currency or orphan reason keep that
  reason and do not count towards the total. Database guard: trigger `shipment_lines_invariants` (BEFORE INSERT or
  UPDATE of `shipped_quantity`, `line_id`, `shipment_id`) refuses a row that would push the total above the ordered
  quantity (`check_violation`, constraint name `shipment_lines_shipped_le_ordered`, serialised per order line by a
  row lock); trigger `order_lines_quantity_floor` refuses lowering `quantity` below what shipped. A violation that
  only the database sees (a later batch adds shipments to a line that already shipped) is a 422
  `SHIPPED_EXCEEDS_ORDERED` and rolls the whole C01 back. It is *not* a plain `CHECK` because it reads other rows.
  C03 needs no extra rule: returns are bounded by the shipped quantity (D-06), which is now bounded by the ordered one.
* **R-06 a shipment line belongs to its shipment's order.** A shipment line whose order line belongs to a different
  order than its shipment is rejected with `SHIPMENT_LINE_ORDER_MISMATCH` (and so are its returns, with the same
  code); it does not count towards any line's shipped total. Database guard: the same trigger, constraint
  `shipment_lines_order_match`.
* **R-07 negative zero.** `credit_amount` of `-0.00` (any signed zero) is **rejected** with `CREDIT_SIGN_REVERSED`
  rather than normalised to `0.00`: a signed zero is the footprint of a sign-reversed source, and silently
  accepting it would hide that. A plain `0.00` credit stays valid. C03 (Python `validate_return`) and C01 (both
  implementations, so TypeScript recomputation agrees) apply it.
* **R-02 discount persistence.** C04 recomputes the discount split of every order line the shipment touches over
  all of that line's shipment lines that exist and upserts (`ON CONFLICT DO UPDATE`) every row, in the one command
  transaction, so the stored rows always equal the contract split `round(discount x shipped / ordered, 2)` by largest
  remainder. The result lists rows of other shipments whose amount changed (`discount_resplit_on_other_shipments`).
  `data/sql/discount_reconciliation.sql` returns the order lines whose stored sum drifts from that figure (no rows =
  reconciled). Note: the discount split spans all shipment lines, quarantined or not, whereas the pipeline drops
  quarantined lines before splitting; the two agree except for order lines that mix quarantined and kept lines.
* **R-08 freight only over lines that are not quarantined.** C04 evaluates, at allocation time and exactly as the
  pipeline does, FX for the order and shipment currency, the cost version and the order status of every line of the
  shipment; lines that fail get no freight row (reported in `skipped_lines` and a `FREIGHT_LINE_SKIPPED` warning).
  Running C04 again for an allocated shipment is still `409 FREIGHT_ALREADY_ALLOCATED` (P01-TEST-01) when the
  result would not change; when the eligible set has changed (a line was un-quarantined by a new cost version or
  rate, or quarantined since) it is a **re-spread**: stale rows are deleted, the others upserted, status
  `reallocated`, warning `FREIGHT_RESPREAD`, one transaction. The first allocation still uses a plain insert so the
  primary key remains the concurrent double-allocation guard. After C02 + C04 for every shipment the stored
  freight equals the contract freight (query 09 gap 0.00).
* **R-03 grouped results include unallocated freight.** `group_metrics` / `groupMetrics` take the unallocated freight
  (already restricted to the window by the caller; the pipeline exposes `unallocated_freight`,
  `unallocated_freight_in_window` and `unallocated_by_shipment`) and emit an explicit **`UNALLOCATED`** group with
  `shipping_cost` equal to it, `contribution_margin` equal to minus it and everything else zero, for every grouping
  key (region, customer, product, month). Nothing is emitted when it is 0.00. On the reviewer's fixture the overall
  shipping cost 36.25 equals the sum over groups (31.25 + 5.00). The web screens add it only for the unfiltered
  population, as for the totals, because it cannot be attributed to a region, segment, category or part of a window.

## D-09 Where a credit appears in the months, the bridge and the ledger (added 2026-10-26, R-04)
D-01a already says a credit belongs to the window that contains its `credit_date`. The web screens now obey it:
* **Population.** Facts are filtered by the region, segment and category filters only; the date window then selects
  shipment lines by `shipped_at` and credits by `credit_date` (`computeMetrics(dimFacts, window, { returns })`).
  The bridge, the region table and the headline totals use exactly that call; without a date filter nothing changes.
* **Overview months.** Month M is the window [M-01, next M-01) intersected with the filter window: it holds the lines
  shipped in M and the credits dated in M whatever the month of their line (`monthlyMetrics`, mirrored by
  `metrics.monthly_metrics`). A credit dated 2024-11-xx for a line shipped in 2024-10 therefore sits in November
  (published snapshot 2024-11: credits 6,096.40, where grouping by shipment month had shown 15,266.75). A month with
  credits and no shipments appears (gross 0.00, negative net). The months add up to the total to within the cent
  rounding of each month (D-04, R-05). The 2026-01 rate comparison uses the same windows.
* **Ledger.** The ledger lists the shipment lines shipped in the window. Their *Credit* column holds only the credits
  dated in the window (`windowLedger`). Credits dated in the window for lines shipped outside it have no line row, so
  the ledger shows them as **credit rows** under the line table (credit date, return, line, shipped at, customer,
  region, quantity, credit, recoverable cost), with their own totals line. `ledgerTotals` adds them, so the ledger's
  totals equal the bridge for the same filters (lines + credit rows == `computeMetrics`), and the bridge says how
  many credit rows its window holds. The line table's footer stays the sum of the visible line rows; the CSV export
  of the current filters carries the line rows with windowed credits and a header with the number of credit rows.
  Without a date filter there are no credit rows and the figures are the lifetime values as before.
