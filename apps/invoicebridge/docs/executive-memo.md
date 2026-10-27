# Executive memo: which invoices may advance and which require exception review? (P05-ART-07)

**Synthetic.** The 40 vendors, 1,200 purchase orders and 2,800 invoices are generated (seed 20261026, dataset `ib-20261026-20261026`, generator hash `1f001a43a7031d4260f5abb3b9f7a83f6e1b48397e85cf8b04e0b4d9e052162e`, contract v1, code revision `2dcc460`). Nothing below is a measured effect on a real accounts-payable team:
**no realised saving, error rate, processing time or adoption is claimed**, and the relationships the data shows (one vendor group that invoices before the goods arrive, one vendor whose price list changed, re-sent PDFs that cluster at month ends) were designed into it (`web/public/data/manifest.json`). Three kinds of statement are kept apart and labelled:
**OBSERVED** (what the synthetic history shows; SQL investigations 01-08 in `sql-analysis.md`, reconciled to `data/sql/reference_metrics.sql` and the Python domain), **SIMULATED** (there is no forecasting model here; the only simulation is the seeded generator that produced the history, and its three outcome-selected choices are listed under "Limitations") and **HYPOTHETICAL** (what a real desk might gain; none is claimed).
Query numbers are the files of `data/sql/analysis/`; P05 ids and command ids C01-C10 are in `requirements.md`. Every amount is **per currency** (USD, EUR, GBP): the contract has no dated conversion rate, so no figure adds one currency to another.

## Decision
Question (P05-GOAL-01): which invoices may advance and which require exception review?

**Of the options this package can evaluate, let the matched invoices advance to approval, put the open exceptions into review in the order of their cause (the vendor group that invoices before receipt, then the price-list vendor, then the rest), hold the matched invoices above the approval limit for a decision about who may approve them, and keep every money figure and every rate per currency with its definition beside it.**
"Advance" means move to approval, never to payment: matching confers no approval and nothing here marks anything paid. This is a recommendation about a synthetic desk, not an instruction.

| Option | Evidence | Status |
|---|---|---|
| **A. Review everything by hand** (baseline) | Observed: 2,413 of 2,645 invoices in the book are matched or further and 2,299 are already obligations; a manual review of all of them spends review effort where nothing blocks. | the reference point |
| **B. Advance the matched, review the 232 open exceptions in cause order** | Observed: 193 quantity blocks, 32 price variances, 4 rounding gaps, 3 currency mismatches; 29 unowned. Invoice totals held by an open exception: USD 163,162.81 (126 invoices), EUR 82,980.52 (56), GBP 77,677.89 (50). | recommended; OBSERVED |
| **C. Fix the cause upstream for the ven-02x group and the ven-007 price list** | Observed: ven-02x has an open quantity block on 163 of 538 invoices (0.302974) and 524 of 538 (0.973978) were blocked at some point, against 30 of 2,107 (0.0142) elsewhere; ven-007 holds 30 of the 32 open price variances. Whether a changed receiving or catalogue process would remove them is not simulated here. | an untested hypothesis (HYPOTHETICAL) |
| **D. Give the over-limit matched invoices an escalation role** | Observed: 114 matched invoices are unapproved at the cutoff and 12 exceed the pol-v2 limit of 8,000.00 (USD 6 totalling 57,379.12, EUR 4 totalling 42,165.56, GBP 2 totalling 16,277.09); no policy carries an escalation role, so nobody may approve them. | recommended as a policy gap; OBSERVED |
| **E. Approve automatically whatever matches** | Not supported: matching never confers approval (P05-DOMAIN-04), approval needs a second person under the policy in force, and in this history only 2,299 of the 2,413 matched invoices were approved by the as-of. | rejected by the contract |

## Evidence (OBSERVED, as-of 2026-10-01T02:00:00Z, per currency)
| What | USD | EUR | GBP | Query |
|---|---|---|---|---|
| Invoices in the book (2,645 in all) | 1,741 | 530 | 374 | 01 |
| Matched or further (2,413) and their total | 1,615 / 1,608,460.47 | 474 / 531,691.91 | 324 / 347,369.86 | 01 |
| Obligations (approved or exported; 2,299) and their total | 1,547 / 1,448,006.25 | 447 / 457,320.65 | 305 / 286,543.12 | 06, 07 |
| Credit notes applied (117 notes on 112 invoices) | 31,969.26 | 6,734.62 | 5,434.95 | 07 |
| **Approved payable** | **1,416,036.99** | **450,586.03** | **281,108.17** | 07 |
| Exported total less approved total (by construction) | 0.00 | 0.00 | 0.00 | 06 |
| Invoices with an open exception (232 in all) | 126 | 56 | 50 | 01 |
| Straight-through rate (not blocked at the cutoff) | 0.927628 | 0.894340 | 0.866310 | 01 |
| Never-excepted rate | 0.834578 | 0.705660 | 0.577540 | 01 |
| Mean minutes from import to approval (5,466.7066 over all 2,299) | 4,804.7573 | 6,692.4482 | 7,027.7852 | 04 |
| Matched, not approved, invoice totals (114 in all) | 160,454.22 (68) | 74,371.26 (27) | 60,826.74 (19) | 06 |

| What | Number | Query |
|---|---|---|
| The two rates over all 2,645 invoices | straight-through **0.912287** (not blocked at the cutoff), never excepted **0.772401** (602 invoices were blocked at some point) | 01 |
| Open against ever raised | 232 open of 660 raised (0.351515); 428 resolved | 01 |
| The vendor group that invoices before receipt | quantity blocks open on **163 of 538 invoices (0.302974)**; ever blocked **524 of 538 (0.973978)**; elsewhere open 30 of 2,107 (0.0142), ever 39 | 01 |
| The price-list vendor | ven-007: **30 of the 32 open price variances** (0.9375) and **53 of the 57 ever raised** (0.9298); none before March | 01 |
| Age of the queue | 186 of the 193 open quantity blocks are older than 30 days, the oldest 358 days; every open price variance is older than 30 days | 05 |
| Ownership | 29 open exceptions have no owner; 78 exceptions were never assigned (49 resolved before triage); the stored history shows 128, 201 and 232 open at the two month-ends and the as-of (the facts-derived book 129, 201, 232) | 05 |
| Duplicates | 98 merged (95 by identity, 3 by identical bytes); 71 of 95 re-sent PDFs (0.7474) arrived in the last three days of a month against 0.1904 of all invoices; four reused numbers across vendors, none merged | 03 |
| Approval limits | 1,055 approvals under pol-v1 (5,000.00) and 1,244 under pol-v2 (8,000.00 from 2026-04-01); 20 approvals above 5,000.00 under pol-v2 (a HYPOTHETICAL under pol-v1: nobody could have approved them) | 04 |
| Separation of duties | 0 self-approvals, 0 role or limit breaches, 0 approvals before import in the snapshot (the rules are exercised by the tests and the replay events, not by this history) | 04 |
| Export | 59 requests, 52 batches, 7 retries answered with the prior batch; 346 invoices not exported, all explained: 232 EXCEPTION_OPEN and 114 NOT_APPROVED | 06 |
| Credits | 4.0 % of invoices (112 of 2,800), 4.9 % of the 2,299 obligations; no credit above its invoice | 07 |
| Defects found, not hidden | 7 of the 12 injected defects are found in the snapshot (the receipt-short and cumulative ones as supersets containing the injected invoices); the other 5 are replay-only and are held by the adversarial tests | 08 |

## Open against ever: the definitions
* **Open at the cutoff** is a reason the match still raises at 2026-10-01T02:00:00Z, recomputed from facts; its denominator is the **2,645 invoices in the book** (not merged, not held for review, not rejected, imported by then).
* **Ever** is an exception of that type raised at some point (the stored nightly history), resolved or not. The rate that counts invoices (524 of 538) and the share that counts exception rows (553 of 596 quantity-block rows belong to ven-02x) differ because a rejected invoice is outside the book but its rows stay in the history; both are published, labelled, and never quoted as one.
* **The published straight-through rate (0.912287) means not blocked at the cutoff**, as its definition says; **0.772401 never had an exception**. A reader who wants "how clean is the intake" should read the second.

## Uncertainty
* **One seeded world.** The relationships were chosen by the generator; a different seed would give different counts. The memo's ordering (ven-02x first) follows from where the open exceptions are in this world, not from a law of accounts payable.
* **The approval mix is outcome-selected.** The generator approves only invoices that matched without interruption (3 % of those are never reviewed) with a delay drawn from a fixed distribution, so the mean minutes to approval and the 114 unapproved matched invoices describe the generator, not a reviewer.
* **The stored history and the derived book can differ.** At the March month-end the nightly history has 128 open exceptions and the book derived from facts 129 (one invoice imported after the last 02:00 run); at the June month-end and the as-of they agree.
* **Limits have no currency.** A GBP and a USD invoice of 6,000.00 are treated alike by pol-v2; any decision about the 12 over-limit invoices should first decide whether a limit is a number or an amount in a currency.
* **The manifest's DR-04 figure of 28 over-limit invoices** is the generator's planning counter at its own decision times; recomputed at the cutoff the figure is 12 (query 04). The 12 is used here.

## Limitations
* **Synthetic.** The desk does not exist; volumes, prices and behaviour are generated, and the designed relationships were chosen, so finding them shows the queries work, not that a business has them.
* **By construction and outcome-selected.** The generator **approves only invoices that matched without interruption**, **rejects only invoices that were exceptions in every run** (57, never an injected one) and **closes each period with a batch that exports everything approved**, so the export difference of 0.00 in every currency, the approval mix and the rejection mix are not findings (D-07, D-09.17, R5-22). A zero reconciliation is a check that the arithmetic and the exclusion list agree.
* **A `needs_review` invoice has no resolving command**, and C06 `correct-extraction` returns 501: the byte-twin-with-other-fields path and any extraction correction are not exercised by the snapshot and not buildable through the API in this milestone. The intake, exceptions, approvals and exports screens of the public site act on nothing.
* **No payment, no bank, no cash.** A credit note reduces the approved payable and moves no cash; nothing marks an invoice paid.
* **The match is derived at an instant** in a stated order (committed invoices first); a real nightly process could order differently.
* **No Excel, no Power BI.** The workbook (`workbook.md`) was recalculated by LibreOffice only; the BI package (`bi-package.md`) has no `.pbix`; neither is evidence about those products.

## Recommendation
What the synthetic data supports: advance the 2,413 matched invoices to the approval desk (they are the invoices that may advance) and work the 232 open exceptions by cause, ven-02x quantity blocks first (163 invoices, 84.5 % of the open quantity blocks), then the ven-007 price list (30 of 32 open price variances), then the four rounding gaps and three currency mismatches; give the 29 unowned exceptions an owner;
decide who may approve the 12 matched invoices above the approval limit; report every rate with its definition and denominator (the invoices in the book), and every amount per currency. **The data does not support any statement about a realised benefit, real error rates or real processing time.**
