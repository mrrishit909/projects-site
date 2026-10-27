# InvoiceBridge: business case (P05-ART-01)

**Every stakeholder, scenario and number here is synthetic.** Nothing is a claim about a real company, a real supplier, a real payment or a measured saving (P05-GOAL-12, P05-DOMAIN-01).
Dataset `ib-20261026-20261026` (seed 20261026, generator `dataset_hash` `1f001a43a7031d4260f5abb3b9f7a83f6e1b48397e85cf8b04e0b4d9e052162e`), contract v1, code revision `2dcc460`; the observed figures describe the book at the as-of **2026-10-01T02:00:00Z** over the twelve months 2025-10-01 to 2026-09-30.
Three kinds of statement are kept apart throughout: **observed** (what the synthetic history shows, reconciled to `data/sql/reference_metrics.sql` and the Python domain), **simulated** (there is no forecasting model in this project: the only simulation is the seeded generator that produced the history, so its designed relationships and the outcome-selected choices listed under "Limits" are the simulated part) and **hypothetical** (what a real accounts-payable team might gain; none is claimed and no figure below is one).

**How to read it:** this file needs nothing installed. The numbers are quoted from `sql-analysis.md` (observed, investigations 01-08 and the reconciliation of section 10 there); `requirements.md` traces each requirement id to code and tests; `executive-memo.md` turns them into a recommendation. Every amount is **per currency** (USD, EUR, GBP): the contract has no dated conversion rate, so money is never added across currencies, here or anywhere in the package.

## The business decision
**Which invoices may advance and which require exception review?** (P05-GOAL-01.) The primary user is an accounts-payable automation analyst; the other portfolio roles are business systems analyst and business analyst (P05-GOAL-02).
Non-goals: payments, bank connections, marking anything paid (there is no `paid` status), optical character recognition as the core (structured import is the core, OCR an optional adapter), live data, any claim of a realised benefit.

## Business problem
A synthetic accounts-payable desk ("the desk") receives supplier invoices as documents, matches each to a purchase order and to the goods actually received, and pays what is right. The failure modes the generator plants on purpose (twelve injected defects, `data/injection-manifest.json`) are the ones that cost real desks money:
a re-sent PDF is paid twice (the same bytes under two file names, or a re-scanned copy with other bytes); an invoice is approved for goods that never arrived, or a second invoice for the same line is approved after the first consumed the receipt; a rounding gap or a price-list change turns every invoice from one supplier into an exception nobody owns; the clerk who keyed an invoice approves it; a credit note is applied twice; a foreign-currency invoice is compared with a purchase order without a rate; an export re-run after a timeout sends the same batch twice; and a matched invoice is mistaken for a paid one.
InvoiceBridge fixes the record first: every import keeps its source hash; identity is vendor, normalised invoice number, date and computed total, so a duplicate is merged and never paid; matching is cumulative against net receipts; approval needs a second person under the policy in force; export is a named, idempotent batch; and every number is derived from the documents, never read from a status.

What the synthetic history shows (OBSERVED, as-of 2026-10-01T02:00:00Z; `sql-analysis.md`):
* **2,800 invoices imported** (2,702 accepted on import and 98 merged as duplicates: 95 by identity, 3 by identical bytes), **57 rejected by a reviewer** and so outside the book, leaving **2,645 invoices in the book**.
* **2,413 are matched or further** (USD 1,615, EUR 474, GBP 324 invoices; totals USD 1,608,460.47, EUR 531,691.91, GBP 347,369.86, each in its own currency) and **2,299 are obligations** (approved or exported: USD 1,547 totalling 1,448,006.25; EUR 447 totalling 457,320.65; GBP 305 totalling 286,543.12).
* **232 exceptions are open at the cutoff** (QUANTITY_BLOCKED 193, PRICE_VARIANCE 32, ROUNDING_EXCEPTION 4, CURRENCY_MISMATCH 3, NO_PO_LINE 0), 29 of them unowned. 660 exceptions were raised over the year, 428 resolved, so **the open backlog is 35.2 % of everything ever raised**: "open at the cutoff" and "ever raised" are different populations and are never quoted as one.
* The published **straight-through rate** is 0.912287 of the 2,645 invoices in the book: it means *not blocked at the cutoff* (D-09.10). The share that **never had an exception** is 0.772401 (602 of the 2,645 were blocked at some point), published beside it. By currency the straight-through rate is USD 0.927628, EUR 0.894340, GBP 0.866310 and the never-excepted rate USD 0.834578, EUR 0.705660, GBP 0.577540.
* **Credit notes** (117 on 112 invoices) reduce the approved payable to USD 1,416,036.99, EUR 450,586.03 and GBP 281,108.17; the 4.0 % credit share is a share of all 2,800 invoices (4.9 % of the 2,299 obligations), never of approvals.
* **Export**: 59 requests answered by 52 batches (7 were retries returning the prior batch), 2,299 export rows; the exported total equals the approved total in every currency, **by construction** (see Limits).
* The designed relationships are present: the vendor group ven-020 .. ven-029 ("ven-02x") has an open quantity block on 163 of its 538 invoices (0.302974; 524 of 538, 0.973978, were blocked at some point) against 30 of the other 2,107 (0.0142); the price-list vendor ven-007 holds 30 of the 32 open price variances (53 of the 57 ever raised); 71 of the 95 re-sent PDFs (0.7474) were imported in the last three days of a month against 0.1904 of all invoices.

## Simulated stakeholders (roles, not people)
| Role (simulated) | Need | Decision criterion | Entities, metrics, commands |
|---|---|---|---|
| AP automation analyst (primary user) | Know, for any invoice, which fact blocks it, and how many are blocked and why | An invoice advances only when every line matches (`quantity variance <= 0`, price within tolerance, totals within 0.02) and nothing marks it a duplicate | `invoices`, `match_results`, `exceptions`; P05-MET-03..07, 12; C04 `match-three-way` |
| AP clerk | Import documents without creating a second obligation | Same bytes or same identity = one obligation; every import keeps its source hash | `invoices`, `import_lineage`; C01 `import-invoice`, C02 `validate-invoice`, C03 `find-duplicates`; P05-MET-09 |
| Reviewer (approver) | Approve what is matched, within the limit, and never one's own import | Approval needs a different actor and a role the policy in force allows for the total; the first valid approval counts | `approvals`, `approval_policies`; C07 `approve-invoice`, C08 `reject-invoice`; P05-MET-08 |
| AP supervisor | Own every exception and keep the history | Every exception has an owner or is counted as unowned; assignments are append-only | `exceptions`, `exception_assignments`; C05 `assign-exception`; P05-MET-12 |
| Receiving / procurement | Book receipts so valid invoices are not blocked | A receipt reversal is visible as an exception on an already exported invoice, never a silent un-export | `receipts`, `po_lines`; P05-MET-03, 05 |
| Finance controller (treasury) | Export exactly what is approved, once, and know the payable net of credits | Export is an idempotent batch; the difference is zero with explicit exclusions; credits reduce the payable once and move no cash | `export_batches`, `export_rows`, `credit_notes`; C09 `export-payable`, C10 `apply-credit-note`; P05-MET-10, 11 |
| Internal audit (reader) | Reconstruct who did what and when | Append-only lineage, assignments, approvals, export rows and audit events | `audit_events`, `import_lineage`; `GET /data/invoices/{id}/audit` |
| BI analyst | A reusable metric model with its definitions | Every measure equals the independent recomputation, per currency | `bi-package.md`, `artifacts/bi/` |
| Data steward | Defects found and refused, not hidden | Every refused row has a reason; the injected defects are found or declared replay-only | `rejected_records`; query 08 |

## Scope
In scope: an import that keeps the source hash and an append-only lineage; identity-based duplicate merging; money in decimal with tax once per invoice; a three-way match per line, cumulative against net receipts, in committed-first order (an approved or exported invoice keeps its quantity); approval under separation of duties and the policy version in force; exceptions with owners and an append-only assignment history; idempotent export batches with a reconciliation and explicit exclusions; credit notes applied once; every figure re-derived from facts as of a cutoff; an independent SQL recomputation; a static interactive demo over a published snapshot.
Out of scope: payments of any kind, bank connections, submitting or persisting anything from the public site, real supplier data, OCR as the core, any dated conversion rate, and **C06 `correct-extraction`, which returns 501**.

## Current-state and future-state process
**Current (simulated):** invoices arrive as files; a clerk keys them; a matching spreadsheet compares them with a purchase order total; a re-sent file is a second payable; an exception queue has no owner and no history; the approver may be the importer; the export is re-run by hand after a timeout; credits are keyed twice; amounts of several currencies are added into one total.
**Future (InvoiceBridge):**
| Step | Command or read | What it does | Rule | Built |
|---|---|---|---|---|
| 1 | C01 `import-invoice` | stores the document with its source sha256 and idempotency key; the same bytes under another name merge into the first | P05-FLOW-01, P05-TEST-01 | yes |
| 2 | C02 `validate-invoice` | decimal totals, required fields, a known active vendor; rounding gaps are exceptions, not validation failures | P05-FLOW-02, P05-TEST-05 | yes |
| 3 | C03 `find-duplicates` | identity (vendor, normalised number, date, computed total) merges later copies into the canonical one; a byte-twin with other fields is held as `needs_review` | P05-FLOW-03, P05-TEST-01, 02 | yes |
| 4 | C04 `match-three-way` | per line: NO_PO_LINE, CURRENCY_MISMATCH, QUANTITY_BLOCKED, PRICE_VARIANCE in that order; an invoice with any exception consumes nothing | P05-FLOW-04, P05-TEST-03, 04, 09 | yes |
| 5 | C05 `assign-exception` | an owner and an append-only assignment history | P05-FLOW-05 | yes |
| 6 | C06 `correct-extraction` | a versioned correction that never overwrites the original | P05-FLOW-06, P05-TEST-10 | **no: 501** |
| 7 | C07 `approve-invoice` | a different actor, a role the policy in force allows; two approvals racing: exactly one wins | P05-FLOW-07, P05-TEST-06, 07 | yes |
| 8 | C08 `reject-invoice` | a reason is required; the creator cannot reject their own invoice | P05-FLOW-08 | yes |
| 9 | C09 `export-payable` | an idempotent batch; a repeat returns the prior batch; a row needs a prior approval | P05-FLOW-09, P05-TEST-11, 12 | yes |
| 10 | C10 `apply-credit-note` | once per credit id, never above the invoice total, reduces the payable, no cash movement | P05-FLOW-10, P05-TEST-08 | yes |
| 11 | `GET /metrics` | the eleven metrics for a half-open window, a cutoff and a grouping (none, vendor, currency) | P05-MET-01..12 | yes |
Exceptions owned (the owners are simulated roles; the data records only the owner ids `usr-ap01` .. `usr-ap06` and the assigning supervisor): a blocked or price-varied invoice, a rounding gap, a currency mismatch, a byte-twin held for review (**no command resolves it in this milestone**: a person acts outside the API), a stale dataset version (409), an invoice that would export twice (409).

## Decision criteria
1. **An invoice advances only if every line matches.** A line matches when the invoiced quantity does not exceed the quantity received and not yet consumed by earlier accepted invoices, and the unit price is within the tolerance (0.00); an invoice also needs its declared total within 0.02 of the computed one. Matching never confers approval (P05-DOMAIN-04).
2. **One document, one obligation.** The same bytes, or the same vendor, normalised number, date and computed total, is one obligation; a repeated number from another vendor is not a duplicate (four such pairs exist and none is merged).
3. **Approval is a second pair of eyes under a limit.** The approver differs from the importer, the role is allowed by the policy version in force at the decision (pol-v1 5,000.00, pol-v2 8,000.00 from 2026-04-01, compared in the invoice's own currency with no conversion), and only the first valid approval counts.
4. **Money is per currency and counts are not money.** No figure adds one currency to another; the all-currency columns carry counts and units only.
5. **Open and ever are different populations.** "Blocked at the cutoff" and "was ever excepted" are stated with their own denominators (the invoices in the book at the cutoff); a rate is never quoted without saying which.
6. **Every exception has an owner or is counted as unowned** (29 at the cutoff); the backlog is reconstructed from the append-only assignments.
7. **A reconciliation of zero is a check, not a finding, when it holds by construction.** The generator closes each period with a batch of everything approved, so the export difference of 0.00 per currency shows the arithmetic and the exclusion list agree.

## Decision supported
The memo (`executive-memo.md`) applies these criteria to the synthetic book: let the 2,413 matched invoices advance to approval, work the 232 open exceptions in order of their cause (the ven-02x quantity blocks and the ven-007 price list first), treat the 114 matched-but-unapproved invoices as a review queue (12 of them exceed the pol-v2 limit and nobody holds an escalation role), keep money and rates per currency, and do not read the zero export difference as evidence about a real process.
That is a recommendation about a synthetic desk; the hypothetical real-world benefit of any of it is not claimed.

## Limits and honesty
* **The history is generated.** The designed relationships were chosen, so finding them shows the queries work, not that a business has them. The generator **approves only invoices that matched without interruption** (3 % of those are never reviewed, and one matched late in the window may be unreviewed at the as-of), **rejects only invoices that were exceptions in every run** (57 of them, never an injected one) and **closes each period with a batch that exports everything approved**; the approval mix, the rejection mix and the zero export difference are therefore outcome-selected or true by construction, not findings (D-07, D-09.17, R5-22).
* **The cumulative match is derived at an instant, in a stated order.** The matching order puts committed (approved or exported) invoices first (D-09); the stored exception history is the nightly 02:00 run's and differs from the book derived at a month-end by one exception (`sql-analysis.md` query 05).
* **A `needs_review` invoice has no resolving command**, C06 returns 501, and the approvals, exports, exceptions and intake screens of the public site do not act, and say so.
* **Policy limits have no currency**; a GBP and a USD invoice of 5,000.00 meet the same limit.
* **The manifest's DR-04 count of 28 invoices "matched but over the limit"** is the generator's planning counter at its own decision times; recomputed from facts at the cutoff, 114 matched invoices are unapproved and 12 of them exceed the limit in force (`sql-analysis.md` query 04). The 12 is the figure used here.
* **No Excel, no Power BI.** The workbook (`workbook.md`) was recalculated by LibreOffice only; the BI package (`bi-package.md`) has no `.pbix`; neither is evidence about those products.
* Claims stay consistent with the public case study (`invoicebridge/project.json` on `unified-portfolio`) and the resume bullets (`resume-bullets.md`).
