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
  imported, pending shown separately (P05-MET-06/07/08). D-09 pins what "without a manual exception"
  means: not blocked at the cutoff.

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

## D-08 Static site (2026-10-26, adopted from A-037)
The site reads the stored exception ids and assignments (the API read path), so "unowned" counts stored assignments
(29 on the snapshot) while a bare `run_pipeline` without stored records reports every open exception as unowned
(232); the golden check verifies both modes against Python digests in `scripts/snapshot-reference.json`. `?dataset=golden`
is a full reload; `/invoices/` shows the golden pair under it and otherwise the canonical copy of the first merge.
The approval trail labels a later valid approval that does not count as SUPERSEDED, and match lines show "previously
invoiced" (consumed, including earlier lines of the same invoice); both are additions beyond the contract figures. The
audit timeline is derived from recorded facts (no stored event log); lineage states that no correction versions exist
and that C06 returns 501. Parser limits: decimals as strings or safe integers (non-integer JSON numbers and exponent
notation rejected); timestamps with a non-zero sub-second part rejected (Python keeps microseconds; the data has none);
tolerances stored at 6 decimals and compared against cents × 10^4. Intake is a position slider with a re-send button in
browser memory. Per-vendor totals are in each vendor's own currency, never converted. The exports page treats the stored
`export_batches` as a cross-check, not a source. No dark mode.

## D-09 Review A-038 (2026-10-26, findings R5-01 .. R5-22; adopted from A-040; evidence in docs/uat-evidence.md)
The book is derived from facts, and a later fact must not be able to drop an earlier committed one. Every rule below is
implemented in the Python domain, the SQL reference and the TypeScript mirror, and held to the same hand-derived values by
`tests/review_cases.json` (Python, SQL and TypeScript read the same file). Golden values and the eleven metric keys are unchanged;
where a metric gains a key it is added only when the fixture does not have the thing it describes.

1. **Committed outcomes (R5-01, R5-02, R5-03, R5-09).** An invoice is *committed* when it has a **policy-valid approval** at or
   before the cutoff: the first approve decision (by `decided_at`, then id) whose actor is not the creator, whose role the policy
   in force at `decided_at` allows for the total, and whose `decided_at` is not before the invoice's import. Policy validity does
   not depend on the match, so it is not circular. The commit instant is that approval's `decided_at` (an export requires an
   approval, so it is never earlier than the approval).
2. **Consumption order.** Received quantity is consumed by committed invoices first, by commit instant (then approval id), then by
   the uncommitted in (invoice_date, imported_at, invoice_id) order. A later-arriving back-dated invoice is therefore
   QUANTITY_BLOCKED when the committed invoices already consume the receipt. An invoice's match lines show the position it held
   in this order; an exception or unmatched invoice still consumes nothing.
3. **Canonical copy.** Duplicates are detected over the invoices imported at or before the cutoff (R5-07: a re-sent PDF imported
   after the cutoff does not exist yet; `merged_records` and the duplicate counts follow). Processing order is committed
   invoices first (by commit instant), then by (imported_at, invoice_id); the first of a group is its canonical copy, so a
   committed copy is never displaced by a later import, even one stamped earlier (R5-02). Only an invoice that has not failed
   C02 can be canonical or be merged (R5-05: no merge into an invalid invoice; an unvalidated one may be, until C02 says
   otherwise). If two copies are committed, the earlier commit is canonical and the other is merged, its approval listed as
   NOT_MATCHED. C04, C07, C09 and C10 refuse a copy the derivation has merged (409 `DUPLICATE_PENDING`, or `INVALID_STATE` at
   C04); C03 merges it. A client `imported_at` later than the server clock is clamped to it (warning `IMPORTED_AT_CLAMPED`);
   an earlier-than-latest stamp is accepted because the committed-first rule makes it harmless.
4. **Byte-twin with other fields (R5-20).** Source bytes equal to the canonical's but another identity (vendor, normalised
   number, date, computed total) is a conflicting extraction: status `needs_review`, reason `BYTES_FIELDS_CONFLICT`, outside the
   book, merged into nothing, and it seeds neither the bytes map nor the identity map, so it cannot pull later invoices into the
   group. `duplicates.unresolved_groups` counts the canonicals such twins are held against; a person resolves them (C06 is
   501). The same bytes with the same identity remain one obligation (merged). Migration 0003 adds the status.
5. **Reversal after approval or export (R5-03).** An approval that no longer matches is NOT_MATCHED and the obligation drops (an
   approved invoice whose receipt is reversed before it is exported). An invoice named by a valid export row **stays exported**:
   its approval is kept, it remains an obligation, the export row and the reconciliation do not move (difference stays 0.00), and
   the reversal surfaces as the QUANTITY_BLOCKED **exception on the exported invoice** (it counts in the exception rate and the
   open exceptions). C09 and C10 re-derive the match like C07 and refuse an invoice that no longer matches (409 `STALE_MATCH`,
   rule `NOT_MATCHED`), exported or not. The consumption of an invoice that does not match is nil, so a reversed receipt never
   shows negative open quantities.
6. **Export rows (R5-09, R5-13).** A row needs a policy-valid approval at or before `exported_at`; otherwise it is invalid and the
   invoice is listed as an exclusion `EXPORT_BEFORE_APPROVAL`. A batch's content at a cutoff never changes afterwards (a row
   depends only on facts at or before it). Every in-book invoice the export did not take is an exclusion with a reason:
   `EXCEPTION_OPEN`, `NOT_APPROVED`, `APPROVED_NOT_EXPORTED`, `EXPORT_BEFORE_APPROVAL`, so a non-zero difference
   (accepted export total minus eligible approved total) is always explained. `GET /metrics` also reconciles the derived rows with
   the stored `export_rows` (`data.export_reconciliation`, warning `EXPORT_ROWS_DIFFER`). The API refuses `exported_at` earlier than
   an approval (422 `EXPORTED_BEFORE_APPROVAL`) and stamps the server clock when it is absent.
7. **Decision instants (R5-04).** The API has no `decided_at`: C07 and C08 stamp the server clock (a payload carrying it is 422
   `FIELD_UNEXPECTED`). In the domain an approval or rejection decided before the invoice's import is invalid (`BEFORE_IMPORT`),
   so processing minutes are never negative. Verdict precedence for an approval: NOT_MATCHED, SELF_APPROVAL, ROLE_OR_LIMIT,
   BEFORE_IMPORT (the first that applies is listed).
8. **Vendor mismatch (R5-06).** A PO line whose purchase order belongs to another vendor is no PO line of this invoice:
   `NO_PO_LINE` (no new reason, so the five `by_reason` keys, the database checks and the golden object stay as they are).
9. **Rejection (R5-08, R5-19).** A reject decision is valid when the invoice is validated and not merged or held, the role is allowed
   by the policy in force, the decider is not the creator (`SELF_DECISION`, API 403 `SELF_DECISION`, refusal audited), the decision
   is not before the import and **no earlier VALID approval** exists. An earlier invalid approval (self, wrong role) does not block
   it; one that passes the policy rules does, even if the invoice later stopped matching (REJECT_AFTER_APPROVAL).
10. **Straight-through (R5-10).** The stated definition ("never had an exception") needs the history of exceptions, which is
    stored (wall-clock created) and not a fact at a cutoff, so it was **not** substituted: `straight_through_rate` keeps its published
    meaning, **not blocked at the cutoff** (1 - exception rate; golden 0.500000), and the site says so. Where the stored exception
    history adds invoices beyond the open ones, `rates` also carries `straight_through_never_excepted_rate` and
    `ever_excepted_rate` (history over the same eligible denominator; absent when the history adds nothing, so the golden rates keep
    their three keys). **Rejected invoices are outside the denominator**: eligible = validated invoices still in the book, a
    rejected invoice has left it (57 on the snapshot, all with an exception history; counting them would raise ever-excepted).
11. **Money per currency (R5-11).** `matched`, `obligations`, `payable` and `export` carry `by_currency` (per-currency counts and
    totals) when the figures span more than one currency; the sums stay as published and are labelled "sum across currencies, not
    converted" wherever the site shows one, with per-currency figures preferred. A single-currency book (the golden fixture) has no
    `by_currency` key.
12. **Grouped export counts (R5-18).** With `group_by`, a request is counted once, in the group of the first invoice (code-point order)
    it names that is in the window; a batch naming two groups is not counted in both, so the groups add up to the whole. A batch whose
    invoices are all outside the window is counted in no group. A window without `group_by` counts requests naming any invoice in it.
    Repeat flags are global (first request with a key or batch id).
13. **Idempotency (R5-19).** The payload hash includes the actor's **role**: the same key and actor under another role is 409
    `IDEMPOTENCY_KEY_REUSED`, not a replay.
14. **Spellings and order (R5-16, R5-17).** Decimal strings are ASCII only (`[+-]?digits[.digits]`, in the domain, the pydantic schemas
    and the TypeScript parser: no underscores, exponents, or non-ASCII digits). Every ordering that decides a result is by code
    point: the TypeScript mirror uses a code-point comparator, not `<` / `.sort()`.
15. **Published data (R5-21, dataset version).** Generator parameters in `manifest.json` are strings (no float); the entity files are
    byte-identical to before. The seed can name the dataset as published (`seed(..., dataset_version=)`, `--dataset-version`): the
    replay events carry `ib-20261026-20261026` and replay as published. Events 06 and 07 carry no `exported_at` (the server stamps
    it). The TypeScript disclosures gain `rounding_tolerated_lines`.
16. **What moved on the snapshot (the published entity files did not).** Matched, obligations, exceptions, approvals and export figures are
    unchanged; `quantities.invoiced_not_received_*` (and the snapshot cutoffs) move because blocked lines now see the committed
    invoices' consumption (9,085.7500 to 9,256.7500 units, 116,771.18 to 118,382.45 at the as-of); `matched`, `obligations`,
    `payable` and `export` gain `by_currency`; the stored-history reading gains the history rates. `web/scripts/snapshot-reference.json`
    was regenerated by the Python domain and the TypeScript mirror reproduces it.
17. **Wording that must travel with the figures (R5-12, R5-14, R5-15, R5-22).** Credit share: 112 invoices carry the 117 credit notes =
    4.0 % of all 2,800 invoices = 4.9 % of the 2,299 approved. PRICE_VARIANCE: ven-007 holds 30 of the 32 invoices open at the as-of
    (93.8 %) and 53 of the 57 that ever raised it (93.0 %). ven-02x quantity blocks: 163 of 538 invoices open at the as-of (30.3 %),
    524 of 538 ever (97.4 %) against 30 of 2,107 (1.4 %) and 39 (1.9 %) elsewhere. The generator selects approvals and rejections
    after the outcome (approvals only on invoices that match, rejections only on invoices excepted in every run) and closes the
    period with one batch of everything approved, so reconciliation 0.00 holds by construction on the snapshot: it checks the code, it is
    not a finding about the data.
