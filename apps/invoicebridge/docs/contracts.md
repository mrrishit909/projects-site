# InvoiceBridge — business contracts, version 1 (2026-10-26)

Decision owner: coordinator (Fable 5.1). Spec: `projects/05-invoicebridge.md`, SHA-256
`4079b907…00c4` at pack commit `fe5f7981`. Rules cite the requirement they satisfy; changing one
bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
Which invoices may advance and which require exception review? (P05-GOAL-01). Primary user:
an accounts-payable automation analyst. Non-goals: payments, bank connections, marking anything
paid (P05-DOMAIN-01, P05-TEST-12); OCR is an optional adapter, structured import is the core
(P05-DOMAIN-02).

## D-01 Import, identity and lineage
* An import carries an idempotency key and the sha256 of the source bytes; the same bytes
  under a different filename are ONE obligation (P05-FLOW-01, P05-TEST-01). The source
  payload is immutable; corrections are versioned rows that never overwrite the original
  extraction (P05-DOMAIN-06, P05-FLOW-06, P05-TEST-10).
* Invoice identity for duplicate detection is (vendor_id, normalised invoice_number,
  invoice_date, total); the same number from a different vendor is not a duplicate
  (P05-TEST-02). Duplicate candidates are unordered groups, counted once (P05-MET-09).

## D-02 Money
* All money is Decimal (NUMERIC(20,6)); never float (P05-DOMAIN-03). Subtotal = Σ quantity ×
  unit_price at line precision; tax is computed on the subtotal and rounded to currency minor
  units; total = round(subtotal) + round(tax) + freight − invoice_discount, in that declared
  order (P05-MET-01/02). Golden (P05-GOLD-01): 6 × 20 = 120.00; 10 % tax = 12.00; total 132.00.
* A rounding difference up to 0.01 per line and 0.02 per invoice is tolerated and disclosed;
  beyond that the invoice raises a `ROUNDING_EXCEPTION` (P05-TEST-05). Lines in a currency
  other than the PO's are never compared without a dated conversion; without a rate they
  raise `CURRENCY_MISMATCH` (P05-TEST-09).

## D-03 Three-way match
* Available received quantity for a PO line = net received (receipts minus reversals) −
  quantity on previously **accepted** invoices (rejected invoices excluded) (P05-MET-03,
  P05-TEST-03/04). Quantity variance = invoiced − available; price variance = invoiced unit
  price − PO unit price in the same currency and unit (P05-MET-04/05).
* A line matches when quantity variance ≤ 0 and |price variance| ≤ tolerance; otherwise an
  exception of the specific type (`QUANTITY_BLOCKED`, `PRICE_VARIANCE`, `NO_PO_LINE`). Golden:
  the second invoice for 4 units is `QUANTITY_BLOCKED` until a receipt arrives.
* Matching never confers approval (P05-DOMAIN-04); `match_results` carry the rule version.

## D-04 Approval, exceptions and export
* Approval requires an actor different from the invoice's creator/importer and a role allowed
  by the policy version effective at decision time for the invoice total (P05-DOMAIN-05,
  P05-FLOW-07, P05-TEST-06). Two approvals racing: exactly one succeeds (optimistic version,
  P05-TEST-07). Rejection requires a reason (P05-FLOW-08).
* Exceptions have an owner and an assignment history; backlog is reconstructed as-of a cutoff
  (P05-FLOW-05, P05-MET-12).
* Export is an idempotent batch keyed by (invoice_id, batch_id); a repeated export after a
  timeout returns the prior batch (P05-FLOW-09, P05-TEST-11). Export reconciliation =
  accepted export total − eligible approved total = 0.00 with explicit exclusions
  (P05-MET-11). A credit note applies once (unique per credit_id) and adjusts the approved
  payable without any cash movement (P05-FLOW-10, P05-TEST-08).
* Straight-through rate = eligible invoices without a manual exception ÷ eligible invoices;
  exception rate over distinct validated invoices; processing time = approval completed −
  imported, pending shown separately (P05-MET-06/07/08).

## Mode disclosure
Mode A: Python domain + PostgreSQL + FastAPI verified on hosted runners. Mode B: TypeScript
mirror over the published snapshot; the intake desk's actions are browser-memory simulations.

## D-05 Fixture-driven clarifications (2026-10-26, adopted from A-034; full text in tests/fixtures/golden/CALCULATION.md D-P5-1..17)
Tax is computed once per invoice at document level on the unrounded subtotal; money rounds ROUND_HALF_UP to 2 decimals;
quantities carry 4 decimals. A duplicate (same vendor, normalised invoice number (upper-case letters and digits only),
invoice date and computed total; D-01 identity uses the computed total) is **merged** into the earliest import, not
rejected: status `merged`, reason `DUPLICATE_IDENTITY`, lineage and source hash kept, no received quantity consumed.
Import status is accepted / rejected / merged; invoice status is received, valid, invalid, matched, exception,
approved, rejected, exported, adjusted, merged; an exception is `open` until assigned. Rejection codes: UNKNOWN_PO_LINE,
UNKNOWN_VENDOR, UNKNOWN_PO, NON_POSITIVE_QUANTITY, DEPENDENT_REJECTED; an invoice is atomic (one bad line rejects the
header, its sibling lines and any approval on it). Exception reasons: QUANTITY_BLOCKED, PRICE_VARIANCE, NO_PO_LINE,
ROUNDING_EXCEPTION, CURRENCY_MISMATCH. An invoice consumes received quantity once matched or later; matching runs in
(invoice_date, imported_at, invoice_id) order; a receipt with `reversed` true is excluded from net received. Tolerances
travel in the inputs: price per unit 0.00, rounding per line 0.01, rounding per invoice 0.02. Extra invoice fields:
tax_rate, freight, invoice_discount, declared_total, created_by, source_sha256, source_filename, idempotency_key,
imported_at; approvals carry actor_role, and the approver must differ from created_by. An obligation is an approved or
exported invoice; straight-through and exception rates have distinct validated invoices as denominator and are null
when it is zero; processing time is minutes to approval over approved invoices only. Export rows: export_id
`exp-<batch>-<invoice>`, invoice_id, batch_id, exported_at, vendor_id, invoice_number, invoice_date, currency, amount,
content_hash = sha256 of `invoice_id|vendor_id|invoice_number|invoice_date|currency|amount`; a repeated idempotency key
returns the prior batch. Open quantities: open to receive, open to invoice, received-not-invoiced valued at PO price,
blocked (invoiced-not-received) valued at invoice price; `snapshot_cutoffs` re-run the quantity figures as of a date.
Not yet pinned by a fixture row (candidates for the adversarial tests): same-bytes duplicate, multi-line tax, rounding
ties, PRICE_VARIANCE, CURRENCY_MISMATCH, NO_PO_LINE, self-approval, credit notes, racing approvals.

## D-06 Backend clarifications (2026-10-26, adopted from A-035; the 18 numbered assumptions are in README.md)
Metrics are derived from recorded facts only (`book.derive`), never from stored statuses; the SQL reference reads no
stored status, total, match result or merge flag. The stored `invoices.status` is the workflow state the commands move
and may lag the derived view; GET /metrics warns `WORKFLOW_STATE_DIFFERS` per such invoice. `snapshot_cutoffs` live
beside `metrics` (in `PipelineResult.snapshot_cutoffs` and `data.snapshot_cutoffs`), so `metrics` stays exactly the
expected.json keys. Extra rejection codes: MALFORMED_RECORD, DUPLICATE_ID, UNKNOWN_INVOICE, NON_POSITIVE_AMOUNT,
CREDIT_EXCEEDS_INVOICE; floats and over-precise decimals are rejected, not rounded (quantities 4 dp, prices and rates
6 dp, money 2 dp, amounts below 10^12). Same source bytes are checked before identity (DUPLICATE_SOURCE_BYTES, then
DUPLICATE_IDENTITY), greedily in (imported_at, invoice_id) order. Reason order per line: NO_PO_LINE, CURRENCY_MISMATCH
(never converted), QUANTITY_BLOCKED, PRICE_VARIANCE; an invoice with any exception consumes nothing. C08 is an
`approvals` row with decision reject and a required reason; only the first valid approval counts; invalid decisions
are listed (NOT_MATCHED, SELF_APPROVAL, ROLE_OR_LIMIT, NOT_REVIEWABLE, REJECT_AFTER_APPROVAL). Policy in force is the
latest `effective_from`; `escalation_role` may approve any amount; no policy means 403 NO_POLICY. Roles: C01–C05
clerk/reviewer/admin, C07–C10 reviewer/admin; reads need no actor. Status precedence adjusted > exported > approved;
credits reduce `approved_payable` only; export batches are named sets, replayed by key, 409 BATCH_CONFLICT for another
set, `exported_at` excluded from the payload hash. Credits once per credit_id (409 CREDIT_ALREADY_APPLIED), cumulative
no more than the invoice total, no cash movement. Exceptions one per (invoice, type), append-only assignment history.
Windows are [from, to) on imported_at with `to` as the as-of instant; snapshot cutoffs inclusive; group_by none /
vendor / currency. C06 is 501; there is no receipt command (receipts are reference data; reversal is the one UPDATE
the schema allows). Known: the stored canonical copy of concurrent same-bytes imports can differ from the derived
earliest-import canonical (warned, counts agree); metrics can run ahead of the workflow (warned).

## D-07 Synthetic world (2026-10-26, adopted from A-036)
Seed 20261026, 12 months 2025-10-01..2026-09-30, `as_of` 2026-10-01T02:00:00Z (the last nightly matching run at
02:00Z; no fact is later than 2026-09-30T23:59:59Z); `snapshot_cutoffs` 2026-03-31T23:59:59Z, 2026-06-30T23:59:59Z
and the as_of. 40 vendors (25 USD, 10 EUR, 5 GBP; ven-040 dormant), 1,200 purchase orders with 3,000 lines, 5,067
receipts (2.0 % reversed, 70 % of those re-entered a day later; a reversed receipt is excluded at every instant because
the fixture shape has no `reversed_at`), 2,800 invoices with 5,322 lines, 117 credit notes on 112 approved invoices,
policies pol-v1 (limit 5000.00) and pol-v2 (8000.00 from 2026-04-01) without `escalation_role` (matched invoices above
the limit stay unapproved), 2,356 approvals (every row carries `reason`, null for approvals), 59 export requests and
52 batches, 660 exceptions with 698 assignments. "ven-02x" means ven-020..ven-029 (quantity blocks on 30.3 % of their
invoices against 1.4 % elsewhere); ven-007's price-list change produces PRICE_VARIANCE from 2026-03-04 (93.8 % of all
price variances); 74.7 % of re-sent PDFs land in the last three days of a month. Rejections are decided only on
invoices that were exceptions in every run; injected exception invoices are never rejected. `exceptions`,
`exception_assignments`, `export_batches` and `credit_notes` take their columns from 0001_schema.sql; match results,
export rows, lineage and audit events are derived and not written. Clean files: 0 rejections, 98 merges (95 identity,
3 same bytes), empty `invalid_records`, export reconciliation 0.00, 232 open exceptions. Five of the twelve injected
defects are replay-only (INJ-06, 07, 08, 10, 12); EV-01..07 behave as recorded. Known: `book.derive` validates
approvals against the run at the cutoff, not at `decided_at`; `Population.exceptions` ids are last-wins while the SQL
prefers the open record (they agree under the load order the tests use); the SQL reference takes about 80 s per query
on 2,800 invoices.
