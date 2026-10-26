# InvoiceBridge golden calculation (contract v1, decisions D-01..D-04)

Independent of application code. `../../reference_check.py` recomputes every figure below from `inputs.json` and
compares it with `expected.json` leaf by leaf (standard library only, no app imports). `expected.json` was written by hand
from this page, not generated from the checker. Money: Decimal strings, 2 decimals. Quantities and unit-price
variances: 4 decimals. Rates: 6 decimals. Minutes: 4 decimals. Rounding: ROUND_HALF_UP (DECISIONS, D-P5-2).

## The spec sentence [P05-GOLD-01]

> PO 10 units at $20; accepted receipt 6 units; first invoice 6 units at $20 matches $120 before tax. A second invoice for
> 4 units is quantity-blocked until receipt arrives. Importing the first invoice twice must leave one obligation. With 10%
> tax and no other charges, first total = $132.

## Part (a): the golden case

Vendor ven-001 (USD). po-001 (2026-10-01, USD), line pol-001 WIDGET-A, 10 units at 20.00.
Receipt rc-001: 6 units on 2026-10-05T10:00Z, not reversed. Tolerances: unit price 0.00, rounding 0.02 per invoice.
Policy pol-v1: reviewer role may approve totals up to 5000.00 from 2026-01-01.

| Invoice | Number | Imported | Lines | Declared total | Bytes |
|---|---|---|---|---|---|
| inv-001 | INV-1001 | 2026-10-06 09:00Z | il-001: 6 x 20.00 | 132.00 | original PDF |
| inv-002 | INV-1002 | 2026-10-06 09:05Z | il-002: 4 x 20.00 | 88.00 | its own PDF |
| inv-003 | inv-1001 | 2026-10-07 09:00Z | il-003: 6 x 20.00 | 132.00 | re-sent, re-scanned PDF (different sha256) |

All three: tax rate 0.10, freight 0.00, discount 0.00, created by usr-clerk01.

### Amounts (D-02)

* inv-001: subtotal 6 x 20.00 = 120.00; tax 120.00 x 0.10 = 12.00; total = 120.00 + 12.00 + 0.00 - 0.00 = **132.00**.
  Declared 132.00, rounding difference 0.00 (tolerance 0.02).
* inv-002: 4 x 20.00 = 80.00; tax 8.00; total 88.00; rounding difference 0.00.
* inv-003: identical figures to inv-001 (120.00 / 12.00 / 132.00).

### Identity and duplicate (D-01)

Identity = (vendor_id, normalised invoice_number, invoice_date, computed total). Normalise = upper-case, letters and digits only:
"INV-1001" -> INV1001 and "inv-1001" -> INV1001. inv-001 and inv-003 both have key `ven-001|INV1001|2026-10-06|132.00`.
inv-002 has key `ven-001|INV1002|2026-10-06|88.00`. The earliest import (inv-001) is canonical; inv-003 is **merged** into it
(status merged, reason DUPLICATE_IDENTITY, merged_into inv-001, its source sha256 kept as lineage; its line il-003 counts as
merged, not accepted). Different bytes, so the hash rule does not catch it: the identity rule does.
* Detected duplicate groups: 1. Rows merged: 1. Unresolved groups: 0 (exact identity is merged automatically, no review).
* Invoices: 2 accepted, 0 rejected, 1 merged. Invoice lines: 2 accepted, 0 rejected, 1 merged.
* Exactly one obligation results from the pair.

### Three-way match (D-03), in order (invoice_date, imported_at, invoice_id): inv-001 then inv-002

* Net received on pol-001 = 6 (rc-001 not reversed). Consumed by accepted invoices so far = 0.
* il-001: available 6 - 0 = 6; quantity variance 6 - 6 = 0 (<= 0); price variance 20.00 - 20.00 = 0.0000 (|0| <= 0.00).
  -> **matched**. inv-001 matches 120.00 before tax. It now consumes 6.
* il-002: available 6 - 6 = 0; quantity variance 4 - 0 = **4.0000 > 0** -> **QUANTITY_BLOCKED**. inv-002 is an exception
  (exc-001, open, unowned), consumes nothing, and is not an obligation. It would match only after a receipt arrives that makes
  available >= 4, i.e. net received >= 10.
* Match results carry rule_version "1".

### Approval and export (D-04)

* ap-001: usr-rev01 (role reviewer) approves inv-001 on 2026-10-06T15:30Z. Actor differs from creator usr-clerk01; policy pol-v1
  effective; reviewer role allowed; 132.00 <= 5000.00 -> valid. Matching alone never conferred approval.
* Obligation: inv-001, **count 1, total 132.00**. inv-002 is excluded (EXCEPTION_OPEN); inv-003 is merged.
* Export: bat-001 requested twice with the same idempotency key (a retry after a timeout). The first creates the batch; the
  repeat returns the prior batch. 2 requests, 1 batch, 1 repeat returned prior. One export row for inv-001, amount 132.00,
  content_hash = sha256 of `inv-001|ven-001|INV-1001|2026-10-06|USD|132.00`.
* Reconciliation: accepted export total 132.00 - eligible approved total 132.00 = **0.00**; exclusion: inv-002 EXCEPTION_OPEN.
* Credit notes: none. Approved payable = 132.00 - 0.00 = 132.00.

### Quantities at 2026-10-26 (all PO lines; one line here)

| Figure | Value | Hand calculation |
|---|---|---|
| ordered | 10.0000 | |
| net received | 6.0000 | |
| accepted invoiced | 6.0000 | inv-001 only |
| open to receive | 4.0000 | 10 - 6 |
| open to invoice | 4.0000 | 10 - 6 (the blocked 4 is not accepted) |
| received-not-invoiced qty / value | 0.0000 / 0.00 | 6 - 6 |
| invoiced-not-received (blocked) qty / value | 4.0000 / 80.00 | variance 4 x invoice price 20.00 |

Snapshot at 2026-10-05T23:00Z (receipt arrived, no invoice yet): ordered 10, net received 6, accepted invoiced 0, open to receive 4,
open to invoice 10, received-not-invoiced 6.0000 / 120.00 (6 x 20.00), blocked 0.

### Rates and times

* Eligible invoices (distinct validated, merged excluded): inv-001, inv-002 = 2.
* Straight-through = eligible without exception / eligible = 1 / 2 = "0.500000". Exception rate = 1 / 2 = "0.500000".
* Processing time (approval completed - imported): 15:30 - 09:00 = 6.5 h = "390.0000" minutes over 1 approved invoice;
  pending (eligible, not approved) 1, shown separately.
* Exceptions: open 1 (unowned 1); by reason QUANTITY_BLOCKED 1, PRICE_VARIANCE 0, NO_PO_LINE 0, ROUNDING_EXCEPTION 0, CURRENCY_MISMATCH 0.
* Matched (matched or later): count 1, 120.00 before tax, tax 12.00, total 132.00.

## Part (b): variant-rejected

Same vendor, PO, line, rc-001 and inv-001 as above, plus:
* rc-002: 5 units against **pol-999**, which does not exist. Rejected `UNKNOWN_PO_LINE` (a receipt must reference a PO line).
* inv-003 (INV-1003, declared -44.00) with il-003-1 (2 x 20.00) and il-003-2 (**-4** x 20.00), and ap-002 approving inv-003.
  il-003-2 violates a real constraint (quantity must be > 0): `NON_POSITIVE_QUANTITY`. An invoice is atomic, so the header inv-003,
  the valid sibling il-003-1 and the approval ap-002 on it carry `DEPENDENT_REJECTED`.
* Counts: receipts 1 accepted / 1 rejected; invoices 1 / 1; invoice_lines 1 / 2; approvals 1 / 1.

Why rejection is correct (what acceptance would have done): subtotal 2 x 20 - 4 x 20 = -40.00, tax -4.00, total -44.00, a negative
payable that is not a credit note (credit notes have their own entity and once-only rule); and the -4 would be subtracted from the
quantity consumed on pol-001 (6 - 4 + 2 = 4), freeing 2 received units that were already invoiced on inv-001 so a later invoice
could be matched against receipts already paid for. Accepting rc-002 would add 5 received units to a line that does not exist.
After rejection the book is unchanged: net received 6, accepted invoiced 6, one obligation 132.00, eligible invoices 1,
straight-through "1.000000", exception rate "0.000000", approvals valid 1, no exception, no duplicate, one export row.

## Part (c): variant-empty

No vendors, POs, lines, receipts, invoices, credits, approvals or export requests (only policy pol-v1 as configuration).
Every count is 0 and every money figure "0.00", every quantity "0.0000". Ratios: eligible invoices 0, so straight-through rate and
exception rate are `null` (zero denominator, never 0.000000); mean processing time is `null` (no approved invoice) while the pending
count is 0. Reconciliation difference "0.00" = 0.00 - 0.00. The empty-state snapshot at the cutoff is all zeros.

## DECISIONS (proposed; the contract is not edited, see "Contract gaps" for what blocks nothing but needs the owner)

* **D-P5-1 Tax at document level.** Tax = round(Σ quantity x unit_price at line precision x rate) once per invoice, on the
  unrounded subtotal (D-02 reads "tax is computed on the subtotal"). Line-level tax is not used. The golden cannot distinguish
  line from document tax (one line per invoice); a rounding fixture with several lines is needed to pin it.
* **D-P5-2 Rounding mode.** D-02 says "rounded to currency minor units" without a mode: propose ROUND_HALF_UP to 2 dp. Not
  exercised by the golden (12.00 and 8.00 are exact).
* **D-P5-3 Duplicate = merged, not rejected.** An exact identity match is auto-merged: status `merged`, reason `DUPLICATE_IDENTITY`,
  `merged_into` the canonical (earliest imported_at, then invoice_id), the row and source sha256 kept as lineage, counted as `merged`
  (R10's "deduplicated"), never as `rejected`, and it consumes no received quantity. `duplicates.groups_detected` counts groups
  once (MET-09); `unresolved_groups` is what MET-09 calls the potential duplicate count and is 0 after an auto-merge.
* **D-P5-4 Identity total.** D-01's "total" is the COMPUTED total (D-02), not the declared total, so a re-sent PDF with an
  extraction typo is still caught by the declared/computed rounding check separately.
* **D-P5-5 Status names.** Import status: accepted, rejected, merged. Invoice status: received, valid, invalid, matched, exception,
  approved, rejected, exported, adjusted, merged (the fixture asserts matched/exception/approved/exported/merged). Exception status: open
  (owner null until assigned). Match line status: matched | exception.
* **D-P5-6 Invoice number normalisation.** Upper-case, keep only A-Z and 0-9.
* **D-P5-7 "Accepted invoice" for consumption (D-03).** An invoice consumes received quantity once it is matched or later; an
  exception, rejected or merged invoice consumes nothing. Matching runs in (invoice_date, imported_at, invoice_id) order.
* **D-P5-8 Reversals.** `receipts.reversed = true` removes that receipt's quantity from net received.
* **D-P5-9 Rejection codes (the contract defines none for import).** `UNKNOWN_PO_LINE`, `UNKNOWN_VENDOR`, `UNKNOWN_PO`,
  `NON_POSITIVE_QUANTITY`, and the dependent code **`DEPENDENT_REJECTED`** (invoice header, sibling lines and any approval or
  credit note whose parent invoice was rejected). The invoice is atomic. ServiceFlow's analogue is TICKET_REJECTED.
* **D-P5-10 Extra input fields (documented purpose).** invoices: tax_rate, freight, invoice_discount, declared_total (the extracted
  total for the rounding check), created_by (separation of duties), source_sha256, source_filename, idempotency_key, imported_at
  (D-01, D-04, processing time); approvals.actor_role (role at decision time). The contract's minimum field lists carry none of
  these, but the D-02/D-04 rules cannot be evaluated without them.
* **D-P5-11 Tolerances are inputs.** `tolerances.price_per_unit` (the contract says "tolerance" and gives no value; fixture uses
  0.00), `rounding_per_line` 0.01 (carried, not exercised: no per-line stated amount exists in the field list), `rounding_per_invoice` 0.02.
* **D-P5-12 Obligation.** An invoice that is approved (or later exported); matched-but-unapproved invoices are not obligations.
  Eligible invoices for the rates = distinct validated (non-merged, non-rejected) invoices imported by the cutoff.
* **D-P5-13 Export row shape.** `export_id` (`exp-<batch_id>-<invoice_id>`), invoice_id, batch_id, exported_at (first request's),
  vendor_id, invoice_number (as imported), invoice_date, currency, amount (total, 2 dp), content_hash = sha256 hex of
  `invoice_id|vendor_id|invoice_number|invoice_date|currency|amount`. One row per (invoice_id, batch_id); a repeated idempotency key
  returns the prior batch. Exclusions listed with `EXCEPTION_OPEN` or `NOT_APPROVED`.
* **D-P5-14 Open quantities.** open_to_receive = Σ max(ordered - net received, 0); open_to_invoice = Σ max(ordered - accepted invoiced, 0);
  received-not-invoiced = Σ max(net received - accepted invoiced, 0) valued at PO unit price; invoiced-not-received = Σ positive
  quantity variance on QUANTITY_BLOCKED lines valued at the invoice unit price.
* **D-P5-15 Snapshots.** `snapshot_cutoffs` re-run the quantities with receipts received_at <= cutoff and invoices imported_at <= cutoff.
* **D-P5-16 Explanation text.** match_results.explanation is free text and is not asserted by the fixture; status, reason code, available
  quantity and both variances are.
* **D-P5-17 Processing time** is in minutes (4 dp), mean over approved invoices only; pending invoices are counted separately; null when none.

## Contract gaps found (propose; nothing was edited)

1. The contract has no import/rejection reason codes and no dependent-rejection code (D-P5-9).
2. D-03 says "tolerance" for price variance without a value (D-P5-11), and D-02 gives no rounding mode (D-P5-2).
3. The minimum invoice field list has no total, tax rate, freight, discount or creator although D-01/D-02/D-04 depend on them (D-P5-10).
4. "Accepted invoice" in D-03 is ambiguous between matched and approved (D-P5-7).
5. Not exercised by this fixture, so unpinned: the same-bytes rule (D-01), line-level versus document-level tax with several lines,
   rounding tie-breaking, ROUNDING_EXCEPTION, PRICE_VARIANCE, CURRENCY_MISMATCH, NO_PO_LINE, self-approval, credit notes, racing
   approvals. The reference implements the cheap ones but no fixture row asserts a non-zero value for them.
