# SQL analysis on the seeded snapshot (P05-ART-04)

Everything here is **synthetic**: the generated snapshot `ib-20261026-20261026` (seed 20261026, generator `dataset_hash` `1f001a43a7031d4260f5abb3b9f7a83f6e1b48397e85cf8b04e0b4d9e052162e`, contract v1, code revision `2dcc460`) seeded into PostgreSQL 16 through the domain's `validate_batch`,
and the golden fixture seeded into a second database. The generator **designed in** four relationships and twelve defects (`web/public/data/manifest.json` `designed_relationships`, `data/injection-manifest.json`: vendors ven-020 .. ven-029 invoicing before the goods arrive, one vendor whose price list changed in March, re-sent PDFs clustering at month ends, an approval-limit change on 2026-04-01; the same bytes under two file names, a reused invoice number across vendors, partial receipts, cumulative consumption, a rounding gap, a self-approval attempt, racing approvals, a credit applied twice, a foreign-currency line without a rate, a correction that would overwrite the original, a repeated export after a timeout, a "paid" flag attempt).
These queries therefore show whether the data contains what was put there and whether the metrics read it correctly; they are **observed results in a synthetic history**, not facts about a real company, and they say nothing about a realised benefit.
The generator also made three outcome-selected choices that every reader of a figure here must keep in mind: it **approves only invoices that matched without interruption**, **rejects only invoices that were exceptions in every run** and **closes each period with a batch that exports everything approved** (D-07, D-09.17, R5-22), so the approval and rejection mix and the zero export difference are not findings. There is no forecasting model in this project, so there are no simulated outcomes beyond the generator itself, and no hypothetical benefit is claimed.
Every table below is the observed output of the named file, rendered from `artifacts/analysis-results.json`, which `run_all.py` writes from the same run (`artifacts/render_sql_analysis.py` fills the tables; no figure inside a table is typed). The sentences around the tables quote them and are checked by `tests/test_artifacts.py`.
Contract rules are cited as D-01..D-09 and requirement ids as P05-MET-nn / P05-TEST-nn / P05-GOLD-nn. **Money is per currency in every table** (USD, EUR, GBP; the contract has no dated conversion rate); quantities are units and may be added across currencies, money may not.

The organising question is the one of the whole package: **which invoices may advance and which require exception review?** (P05-GOAL-01). Each investigation says what it contributes to it.

## Reproduce

```sh
cd apps/invoicebridge
# one command: creates the scratch databases artifacts05_run_snapshot and artifacts05_run_golden, seeds them (data/migrate.py, data/seed.py), runs everything, drops them (about six minutes)
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi    # exit 0 only if every reconciliation row is equal
../../.venv/bin/python artifacts/render_sql_analysis.py                                                              # refresh the tables below

# or step by step on databases you made (names must start with artifacts05_; the shared invoicebridge database is refused)
export ARTIFACTS_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/artifacts05_snapshot
export ARTIFACTS_GOLDEN_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/artifacts05_golden
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py             # reset + migrate + seed web/public/data + the published exception history (under a minute)
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden
# 00_book.sql creates TEMPORARY tables, so it must run in the same psql session as the investigation:
psql -v ON_ERROR_STOP=1 "$ARTIFACTS_DATABASE_URL" -f data/sql/analysis/00_book.sql -f data/sql/analysis/01_match_outcomes_by_vendor_and_reason.sql
psql -v ON_ERROR_STOP=1 "$ARTIFACTS_GOLDEN_DATABASE_URL" -f data/sql/analysis/09_golden_known_answer.sql      # the golden file needs no book
```

The credentials are placeholders: the local development login of the repository's CI workflow is the default of `run_all.py` and can be replaced with `ARTIFACTS_ADMIN_URL`. No other credential exists and none is stored in this package.
Files with several blocks (`-- @@ name`) hold several statements; `run_all.py` runs each block and stores it as `<file>__<name>`.

Prepared snapshot database (counts from `data-dictionary.md`): 40 vendors (25 USD, 10 EUR, 5 GBP), 1,200 purchase orders with 3,000 lines, 5,067 receipts (101 reversed), 2,800 invoices with 5,322 lines, 2,356 approval decisions (2,299 approve, 57 reject), 117 credit notes, 59 export requests, 660 stored exceptions with 698 assignments; **0 rows rejected** at ingest (`rejected_records` is empty, query 08).
Cutoffs: the as-of `2026-10-01T02:00:00Z` (the last nightly matching run; no fact is later) and the two month-ends `2026-03-31T23:59:59Z` and `2026-06-30T23:59:59Z` (`snapshot_cutoffs`). Instants are UTC and inclusive.

## 00 The book (`00_book.sql`)
The three-way match is a cumulative chain: whether an invoice matches depends on the quantity consumed by the invoices before it, so it cannot be a window function. `00_book.sql` therefore holds a **verbatim copy of the common table expressions of `data/sql/reference_metrics.sql`**
(the independent SQL recomputation of every metric: tax once per invoice on the unrounded subtotal, duplicates by source bytes then identity with committed invoices first, policy-valid approvals, the recursive match chain per cutoff) with one change: its two parameters are the snapshot's literals, so the file runs under psql as it is.
`tests/test_artifacts.py` checks the copy equals the reference text line for line. It writes two temporary tables, `ib_run` (one row per invoice in the book at each cutoff: matched, reasons, total, vendor, currency, line results) and `ib_facts` (merges, held byte-twins, the first policy-valid approval of each invoice, reject decisions). It reads no stored status, match result, merge flag or total.
The investigations then read `ib_run` and `ib_facts` and the raw facts, and the stored exception history where the question is about history (`exceptions`, `exception_assignments`). Building the book takes about two minutes, as long as one reference query. The file is not an investigation: it has no result set.

## 01 Match outcomes by vendor and reason (`01_match_outcomes_by_vendor_and_reason.sql`)
Question: where do the exceptions come from, and what does "open" mean? Two populations are kept apart in every block: **open at the cutoff** (a reason the match still raises at 2026-10-01T02:00:00Z, recomputed from facts) and **ever** (an exception of that type was raised at some point, from the stored history, resolved or not).

`reason_open_vs_ever`: **232 exceptions are open** (QUANTITY_BLOCKED 193, PRICE_VARIANCE 32, ROUNDING_EXCEPTION 4, CURRENCY_MISMATCH 3, NO_PO_LINE 0) against **660 ever raised** (596, 57, 4, 3, 0), 428 of them resolved (403 quantity blocks and 25 price variances): the open backlog is 0.351515 of everything ever raised. 659 distinct invoices carry the 660 rows (one invoice was blocked twice).
<!-- BEGIN:01_match_outcomes_by_vendor_and_reason__reason_open_vs_ever -->
| reason | open_at_cutoff | ever_raised | ever_resolved | ever_invoices | open_share_of_ever |
|---|---|---|---|---|---|
| QUANTITY_BLOCKED | 193 | 596 | 403 | 595 | 0.323826 |
| PRICE_VARIANCE | 32 | 57 | 25 | 57 | 0.561404 |
| NO_PO_LINE | 0 | 0 | 0 | 0 |  |
| ROUNDING_EXCEPTION | 4 | 4 | 0 | 4 | 1.000000 |
| CURRENCY_MISMATCH | 3 | 3 | 0 | 3 | 1.000000 |
| ALL | 232 | 660 | 428 | 659 | 0.351515 |
<!-- END:01_match_outcomes_by_vendor_and_reason__reason_open_vs_ever -->

`vendor_group_open_vs_ever` counts **invoices in the book** (2,645; a rejected invoice is outside both columns). The vendor group ven-020 .. ven-029 ("ven-02x") has an open quantity block on **163 of its 538 invoices (0.302974)**, and **524 of 538 (0.973978)** were blocked at some point; elsewhere (ven-007 and the other vendors, 2,107 invoices) 30 are open (0.0142: 2 for ven-007 and 28 for the others) and 39 were ever blocked.
The price-list vendor ven-007 has **30 open price variances** on its 184 invoices in the book; the other vendors have 2.
<!-- BEGIN:01_match_outcomes_by_vendor_and_reason__vendor_group_open_vs_ever -->
| vendor_group | invoices_in_book | quantity_blocked_open | quantity_blocked_open_rate | quantity_blocked_ever | quantity_blocked_ever_rate | price_variance_open | price_variance_ever |
|---|---|---|---|---|---|---|---|
| other vendors | 1923 | 28 | 0.014561 | 37 | 0.019241 | 2 | 2 |
| ven-007 | 184 | 2 | 0.010870 | 2 | 0.010870 | 30 | 30 |
| ven-02x | 538 | 163 | 0.302974 | 524 | 0.973978 | 0 | 0 |
<!-- END:01_match_outcomes_by_vendor_and_reason__vendor_group_open_vs_ever -->

`history_by_vendor_group` counts **exception rows** over the whole stored history (resolved ones and those of invoices later rejected included), so its denominators differ from the block above and the two are never quoted as one: **ven-007 accounts for 53 of the 57 price-variance rows ever raised (0.9298) and 30 of the 32 open ones (0.9375)**; ven-02x for 553 of the 596 quantity-block rows (0.9279) and 163 of the 193 open ones (0.8446).
<!-- BEGIN:01_match_outcomes_by_vendor_and_reason__history_by_vendor_group -->
| vendor_group | reason | ever_raised_rows | ever_raised_invoices | open_at_cutoff |
|---|---|---|---|---|
| other vendors | PRICE_VARIANCE | 4 | 4 | 2 |
| ven-007 | PRICE_VARIANCE | 53 | 53 | 30 |
| other vendors | QUANTITY_BLOCKED | 41 | 41 | 28 |
| ven-007 | QUANTITY_BLOCKED | 2 | 2 | 2 |
| ven-02x | QUANTITY_BLOCKED | 553 | 552 | 163 |
<!-- END:01_match_outcomes_by_vendor_and_reason__history_by_vendor_group -->

`by_vendor` (one row per vendor; ven-040 is dormant and has no invoice): the ten ven-02x vendors have between 3 and 28 invoices with an open exception each, and 5 to 56 of their matched invoices were blocked before they matched.
<!-- BEGIN:01_match_outcomes_by_vendor_and_reason__by_vendor -->
| vendor_id | currency | vendor_group | invoices_in_book | matched_at_cutoff | with_open_exception | matched_after_an_exception |
|---|---|---|---|---|---|---|
| ven-001 | USD | other vendors | 93 | 91 | 2 | 0 |
| ven-002 | USD | other vendors | 86 | 83 | 3 | 0 |
| ven-003 | USD | other vendors | 43 | 43 | 0 | 0 |
| ven-004 | USD | other vendors | 105 | 103 | 2 | 1 |
| ven-005 | USD | other vendors | 73 | 73 | 0 | 0 |
| ven-006 | USD | other vendors | 127 | 125 | 2 | 0 |
| ven-007 | USD | ven-007 | 184 | 152 | 32 | 0 |
| ven-008 | USD | other vendors | 47 | 46 | 1 | 0 |
| ven-009 | USD | other vendors | 13 | 12 | 1 | 0 |
| ven-010 | USD | other vendors | 90 | 89 | 1 | 0 |
| ven-011 | GBP | other vendors | 91 | 89 | 2 | 0 |
| ven-012 | EUR | other vendors | 32 | 32 | 0 | 0 |
| ven-013 | USD | other vendors | 59 | 58 | 1 | 0 |
| ven-014 | USD | other vendors | 72 | 70 | 2 | 2 |
| ven-015 | EUR | other vendors | 26 | 25 | 1 | 0 |
| ven-016 | USD | other vendors | 122 | 119 | 3 | 0 |
| ven-017 | USD | other vendors | 80 | 79 | 1 | 1 |
| ven-018 | USD | other vendors | 25 | 24 | 1 | 0 |
| ven-019 | USD | other vendors | 76 | 76 | 0 | 0 |
| ven-020 | USD | ven-02x | 37 | 25 | 12 | 23 |
| ven-021 | EUR | ven-02x | 37 | 22 | 15 | 21 |
| ven-022 | USD | ven-02x | 53 | 39 | 14 | 36 |
| ven-023 | USD | ven-02x | 61 | 44 | 17 | 41 |
| ven-024 | EUR | ven-02x | 8 | 5 | 3 | 5 |
| ven-025 | GBP | ven-02x | 82 | 55 | 27 | 53 |
| ven-026 | USD | ven-02x | 85 | 57 | 28 | 56 |
| ven-027 | EUR | ven-02x | 43 | 31 | 12 | 31 |
| ven-028 | GBP | ven-02x | 74 | 55 | 19 | 54 |
| ven-029 | EUR | ven-02x | 58 | 42 | 16 | 41 |
| ven-030 | GBP | other vendors | 37 | 36 | 1 | 0 |
| ven-031 | EUR | other vendors | 126 | 121 | 5 | 0 |
| ven-032 | EUR | other vendors | 45 | 45 | 0 | 0 |
| ven-033 | EUR | other vendors | 121 | 119 | 2 | 2 |
| ven-034 | GBP | other vendors | 89 | 89 | 0 | 1 |
| ven-035 | USD | other vendors | 56 | 55 | 1 | 0 |
| ven-036 | EUR | other vendors | 32 | 32 | 0 | 0 |
| ven-037 | USD | other vendors | 35 | 34 | 1 | 0 |
| ven-038 | USD | other vendors | 50 | 49 | 1 | 2 |
| ven-039 | USD | other vendors | 72 | 69 | 3 | 0 |
| ven-040 | USD | other vendors | 0 | 0 | 0 | 0 |
<!-- END:01_match_outcomes_by_vendor_and_reason__by_vendor -->

`by_currency`: 2,413 invoices are matched at the cutoff: **USD 1,615 (total 1,608,460.47), EUR 474 (531,691.91), GBP 324 (347,369.86)**, each total in its own currency; 126, 56 and 50 invoices of the three currencies carry an open exception.
<!-- BEGIN:01_match_outcomes_by_vendor_and_reason__by_currency -->
| currency | invoices_in_book | matched_at_cutoff | matched_total | with_open_exception |
|---|---|---|---|---|
| EUR | 530 | 474 | 531691.91 | 56 |
| GBP | 374 | 324 | 347369.86 | 50 |
| USD | 1741 | 1615 | 1608460.47 | 126 |
<!-- END:01_match_outcomes_by_vendor_and_reason__by_currency -->

`rates_by_currency`: the published straight-through rate means *not blocked at the cutoff* (D-09.10); the never-excepted rate is the share that was never blocked. By currency: **straight-through USD 0.927628, EUR 0.894340, GBP 0.866310; never excepted USD 0.834578, EUR 0.705660, GBP 0.577540**. Over all 2,645 invoices the two are 0.912287 and 0.772401 (602 invoices ever excepted).
<!-- BEGIN:01_match_outcomes_by_vendor_and_reason__rates_by_currency -->
| currency | invoices_in_book | blocked_at_cutoff | ever_excepted | straight_through_rate | never_excepted_rate |
|---|---|---|---|---|---|
| EUR | 530 | 56 | 156 | 0.894340 | 0.705660 |
| GBP | 374 | 50 | 158 | 0.866310 | 0.577540 |
| USD | 1741 | 126 | 288 | 0.927628 | 0.834578 |
<!-- END:01_match_outcomes_by_vendor_and_reason__rates_by_currency -->

## 02 Cumulative consumption by PO line (`02_cumulative_consumption_by_po_line.sql`)
Question: how much of what was received has been invoiced and accepted, so which invoices can still advance? Consumption is the sum of the quantities on the lines of **matched** invoices (an invoice with any exception consumes nothing), net received is receipts not reversed and received by the cutoff, and a PO line exists at a cutoff when its order was placed by then. Quantities are units and may be added across currencies; the value of received-not-invoiced is per currency and is never summed (the money column is empty on the `ALL` rows).
<!-- BEGIN:02_cumulative_consumption_by_po_line__totals_by_cutoff -->
| cutoff | currency | po_lines | ordered_quantity | net_received_quantity | accepted_invoiced_quantity | open_to_receive_quantity | open_to_invoice_quantity | received_not_invoiced_quantity | received_not_invoiced_value |
|---|---|---|---|---|---|---|---|---|---|
| 2026-03-31T23:59:59Z | ALL | 1585 | 105243.2500 | 89156.2500 | 78554.5000 | 16087.0000 | 26688.7500 | 10601.7500 |  |
| 2026-03-31T23:59:59Z | EUR | 345 | 32308.5000 | 28118.0000 | 24058.0000 | 4190.5000 | 8250.5000 | 4060.0000 | 42551.45 |
| 2026-03-31T23:59:59Z | GBP | 228 | 16955.0000 | 13947.5000 | 12168.5000 | 3007.5000 | 4786.5000 | 1779.0000 | 14216.52 |
| 2026-03-31T23:59:59Z | USD | 1012 | 55979.7500 | 47090.7500 | 42328.0000 | 8889.0000 | 13651.7500 | 4762.7500 | 94597.54 |
| 2026-06-30T23:59:59Z | ALL | 2454 | 170228.0000 | 147243.5000 | 129745.5000 | 22984.5000 | 40482.5000 | 17498.0000 |  |
| 2026-06-30T23:59:59Z | EUR | 505 | 49302.0000 | 39309.7500 | 35525.5000 | 9992.2500 | 13776.5000 | 3784.2500 | 43496.96 |
| 2026-06-30T23:59:59Z | GBP | 344 | 25069.0000 | 21305.7500 | 18527.7500 | 3763.2500 | 6541.2500 | 2778.0000 | 28439.13 |
| 2026-06-30T23:59:59Z | USD | 1605 | 95857.0000 | 86628.0000 | 75692.2500 | 9229.0000 | 20164.7500 | 10935.7500 | 146635.00 |
| 2026-10-01T02:00:00Z | ALL | 3000 | 202310.2500 | 191431.0000 | 176112.2500 | 10879.2500 | 26198.0000 | 15318.7500 |  |
| 2026-10-01T02:00:00Z | EUR | 627 | 56695.5000 | 52272.2500 | 47989.2500 | 4423.2500 | 8706.2500 | 4283.0000 | 49602.39 |
| 2026-10-01T02:00:00Z | GBP | 417 | 29161.2500 | 25829.2500 | 22291.7500 | 3332.0000 | 6869.5000 | 3537.5000 | 38609.28 |
| 2026-10-01T02:00:00Z | USD | 1956 | 116453.5000 | 113329.5000 | 105831.2500 | 3124.0000 | 10622.2500 | 7498.2500 | 135134.34 |
<!-- END:02_cumulative_consumption_by_po_line__totals_by_cutoff -->
Accepted invoiced quantity grows with the cutoff: **78,554.5000 units at the March month-end, 129,745.5000 in June and 176,112.2500 at the as-of**, against net received 89,156.2500, 147,243.5000 and 191,431.0000; received-not-invoiced is 10,601.7500, 17,498.0000 and 15,318.7500 units.
At the as-of its value at the PO price is **USD 135,134.34, EUR 49,602.39 and GBP 38,609.28**, each in its own currency.

`line_state_by_cutoff`: every PO line is in exactly one state; at the as-of 2,482 of the 3,000 lines are fully invoiced, 229 partly invoiced, 194 received and not invoiced and 95 have nothing received; **no line is over-consumed at any cutoff** (the quantity block is the control that keeps it so).
<!-- BEGIN:02_cumulative_consumption_by_po_line__line_state_by_cutoff -->
| cutoff | state | po_lines |
|---|---|---|
| 2026-03-31T23:59:59Z | nothing_received | 155 |
| 2026-03-31T23:59:59Z | received_none_invoiced | 140 |
| 2026-03-31T23:59:59Z | partly_invoiced | 121 |
| 2026-03-31T23:59:59Z | fully_invoiced | 1169 |
| 2026-03-31T23:59:59Z | over_consumed | 0 |
| 2026-06-30T23:59:59Z | nothing_received | 191 |
| 2026-06-30T23:59:59Z | received_none_invoiced | 202 |
| 2026-06-30T23:59:59Z | partly_invoiced | 213 |
| 2026-06-30T23:59:59Z | fully_invoiced | 1848 |
| 2026-06-30T23:59:59Z | over_consumed | 0 |
| 2026-10-01T02:00:00Z | nothing_received | 95 |
| 2026-10-01T02:00:00Z | received_none_invoiced | 194 |
| 2026-10-01T02:00:00Z | partly_invoiced | 229 |
| 2026-10-01T02:00:00Z | fully_invoiced | 2482 |
| 2026-10-01T02:00:00Z | over_consumed | 0 |
<!-- END:02_cumulative_consumption_by_po_line__line_state_by_cutoff -->

`ladder_top_lines`: the ten lines with the most accepted quantity at the as-of, shown at the three cutoffs. Consumption only grows as invoices are accepted and never passes what was received (for example pol-2188: 0 at the March month-end, 586 of 3,000 in June, 3,000 of 3,000 at the as-of).
<!-- BEGIN:02_cumulative_consumption_by_po_line__ladder_top_lines -->
| po_line_id | vendor_id | currency | ordered_quantity | net_at_march | invoiced_at_march | net_at_june | invoiced_at_june | net_at_asof | invoiced_at_asof |
|---|---|---|---|---|---|---|---|---|---|
| pol-0124 | ven-021 | EUR | 3000.0000 | 3000.0000 | 3000.0000 | 3000.0000 | 3000.0000 | 3000.0000 | 3000.0000 |
| pol-0465 | ven-032 | EUR | 3000.0000 | 3000.0000 | 3000.0000 | 3000.0000 | 3000.0000 | 3000.0000 | 3000.0000 |
| pol-2188 | ven-013 | USD | 3000.0000 | 0.0000 | 0.0000 | 3000.0000 | 586.0000 | 3000.0000 | 3000.0000 |
| pol-0274 | ven-017 | USD | 2006.0000 | 2006.0000 | 2006.0000 | 2006.0000 | 2006.0000 | 2006.0000 | 2006.0000 |
| pol-2740 | ven-016 | USD | 1820.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1820.0000 | 1820.0000 |
| pol-1934 | ven-001 | USD | 1696.0000 | 0.0000 | 0.0000 | 1696.0000 | 1696.0000 | 1696.0000 | 1696.0000 |
| pol-2304 | ven-032 | EUR | 1622.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1622.0000 | 1622.0000 |
| pol-1802 | ven-007 | USD | 1585.0000 | 0.0000 | 0.0000 | 1585.0000 | 1585.0000 | 1585.0000 | 1585.0000 |
| pol-2119 | ven-033 | EUR | 1393.0000 | 0.0000 | 0.0000 | 1393.0000 | 1393.0000 | 1393.0000 | 1393.0000 |
| pol-2632 | ven-018 | USD | 1283.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1283.0000 | 1283.0000 |
<!-- END:02_cumulative_consumption_by_po_line__ladder_top_lines -->

## 03 Duplicates by identity and by bytes, and when re-sent files arrive (`03_duplicates_identity_vs_bytes_and_month_end.sql`)
Question: which invoices are merged rather than paid twice, and is a repeated number a duplicate? Identity is the vendor, the number upper-cased with only letters and digits, the invoice date and the **computed** total; the same source bytes are checked first. A merged invoice keeps its lineage row and consumes nothing.

`merges_by_reason_and_cutoff`: **98 merges at the as-of: 95 by identity and 3 by identical bytes** (52 at the March month-end, 70 in June). Every canonical copy has exactly one merged copy here.
<!-- BEGIN:03_duplicates_identity_vs_bytes_and_month_end__merges_by_reason_and_cutoff -->
| cutoff | reason_code | rows_merged | canonical_invoices |
|---|---|---|---|
| 2026-03-31T23:59:59Z | DUPLICATE_IDENTITY | 50 | 50 |
| 2026-03-31T23:59:59Z | DUPLICATE_SOURCE_BYTES | 2 | 2 |
| 2026-06-30T23:59:59Z | DUPLICATE_IDENTITY | 68 | 68 |
| 2026-06-30T23:59:59Z | DUPLICATE_SOURCE_BYTES | 2 | 2 |
| 2026-10-01T02:00:00Z | DUPLICATE_IDENTITY | 95 | 95 |
| 2026-10-01T02:00:00Z | DUPLICATE_SOURCE_BYTES | 3 | 3 |
<!-- END:03_duplicates_identity_vs_bytes_and_month_end__merges_by_reason_and_cutoff -->

`identity_vs_bytes`: the 95 identity merges are re-sent PDFs with **other bytes** and other file names (0 share their bytes), imported on average 17.1271 days after the canonical copy and always by the same vendor; the 3 byte merges arrive 4.4861 days after it. Neither rule alone catches both.
<!-- BEGIN:03_duplicates_identity_vs_bytes_and_month_end__identity_vs_bytes -->
| reason_code | rows_merged | same_source_bytes | same_file_name | same_vendor | mean_days_after_canonical |
|---|---|---|---|---|---|
| DUPLICATE_IDENTITY | 95 | 0 | 0 | 95 | 17.1271 |
| DUPLICATE_SOURCE_BYTES | 3 | 3 | 0 | 3 | 4.4861 |
<!-- END:03_duplicates_identity_vs_bytes_and_month_end__identity_vs_bytes -->

`month_end_clustering`: **71 of the 95 re-sent PDFs (0.7474) were imported in the last three days of a month**, against 533 of all 2,800 invoices (0.1904) and 462 of the 2,705 that are not re-sent copies (0.1708) (DR-03).
<!-- BEGIN:03_duplicates_identity_vs_bytes_and_month_end__month_end_clustering -->
| population | invoices | imported_in_last_three_days | share |
|---|---|---|---|
| merged by identity (re-sent PDFs) | 95 | 71 | 0.7474 |
| all invoices | 2800 | 533 | 0.1904 |
| invoices that are not re-sent copies | 2705 | 462 | 0.1708 |
<!-- END:03_duplicates_identity_vs_bytes_and_month_end__month_end_clustering -->
<!-- BEGIN:03_duplicates_identity_vs_bytes_and_month_end__merged_by_import_month -->
| import_month | rows_merged_by_identity | in_last_three_days |
|---|---|---|
| 2025-10 | 1 | 1 |
| 2025-11 | 13 | 8 |
| 2025-12 | 5 | 5 |
| 2026-01 | 12 | 8 |
| 2026-02 | 9 | 6 |
| 2026-03 | 10 | 8 |
| 2026-04 | 5 | 4 |
| 2026-05 | 7 | 6 |
| 2026-06 | 6 | 5 |
| 2026-07 | 11 | 11 |
| 2026-08 | 12 | 7 |
| 2026-09 | 4 | 2 |
<!-- END:03_duplicates_identity_vs_bytes_and_month_end__merged_by_import_month -->

`same_number_other_vendor`: four normalised numbers are shared by invoices of two vendors each (HAR6441, FAL8545, BLU4775, WES8970; INJ-02) and **none is merged**: the vendor is part of the identity.
<!-- BEGIN:03_duplicates_identity_vs_bytes_and_month_end__same_number_other_vendor -->
| number_norm | invoices | vendors | merged_rows |
|---|---|---|---|
| BLU4775 | 2 | 2 | 0 |
| FAL8545 | 2 | 2 | 0 |
| HAR6441 | 2 | 2 | 0 |
| WES8970 | 2 | 2 | 0 |
<!-- END:03_duplicates_identity_vs_bytes_and_month_end__same_number_other_vendor -->

`lineage_append_only`: the import lineage keeps one row per import, 2,702 accepted and 98 merged, so the 2,800 documents are all traceable to their bytes.
<!-- BEGIN:03_duplicates_identity_vs_bytes_and_month_end__lineage_append_only -->
| import_status | reason_code | lineage_rows | invoices |
|---|---|---|---|
| accepted |  | 2702 | 2702 |
| merged | DUPLICATE_IDENTITY | 95 | 95 |
| merged | DUPLICATE_SOURCE_BYTES | 3 | 3 |
<!-- END:03_duplicates_identity_vs_bytes_and_month_end__lineage_append_only -->

## 04 Approvals under policy v1 and v2, with separation of duties (`04_approvals_under_policy_versions.sql`)
Question: which matched invoices may advance to approval, and by whom? The policy in force at a decision is the latest `effective_from` not after it: pol-v1 (limit 5,000.00) and from 2026-04-01 pol-v2 (8,000.00), neither with an escalation role. A limit is compared with the invoice total in the invoice's own currency, with no conversion.

`decisions_by_policy_version`: **1,055 approvals and 18 rejections were decided under pol-v1, 1,244 approvals and 39 rejections under pol-v2**, every one valid.
<!-- BEGIN:04_approvals_under_policy_versions__decisions_by_policy_version -->
| policy_id | version_number | amount_limit | approve_decisions | valid_approvals | reject_decisions | valid_rejections |
|---|---|---|---|---|---|---|
| pol-v1 | 1 | 5000.00 | 1055 | 1055 | 18 | 18 |
| pol-v2 | 2 | 8000.00 | 1244 | 1244 | 39 | 39 |
<!-- END:04_approvals_under_policy_versions__decisions_by_policy_version -->

`approvals_by_policy_and_currency`: the largest approved invoice under pol-v1 is 4,982.04 (GBP), under pol-v2 6,960.77 (EUR); mean minutes from import to approval run from 4,657.2566 (USD, pol-v2) to 7,988.1517 (GBP, pol-v1).
<!-- BEGIN:04_approvals_under_policy_versions__approvals_by_policy_and_currency -->
| policy_id | currency | valid_approvals | approved_total | largest_invoice | mean_minutes_to_approval |
|---|---|---|---|---|---|
| pol-v1 | EUR | 222 | 215322.00 | 4764.63 | 6594.0014 |
| pol-v1 | GBP | 150 | 130627.12 | 4982.04 | 7988.1517 |
| pol-v1 | USD | 683 | 616417.56 | 4972.06 | 4991.3469 |
| pol-v2 | EUR | 225 | 241998.65 | 6960.77 | 6789.5824 |
| pol-v2 | GBP | 155 | 155916.00 | 6570.89 | 6098.3983 |
| pol-v2 | USD | 864 | 831588.69 | 6774.44 | 4657.2566 |
<!-- END:04_approvals_under_policy_versions__approvals_by_policy_and_currency -->

`approval_time_by_currency`: all 2,299 valid approvals take on average **USD 4,804.7573, EUR 6,692.4482 and GBP 7,027.7852 minutes**; over all of them the mean is 5,466.7066 minutes.
<!-- BEGIN:04_approvals_under_policy_versions__approval_time_by_currency -->
| currency | valid_approvals | mean_minutes_to_approval | longest_minutes |
|---|---|---|---|
| EUR | 447 | 6692.4482 | 41239.1000 |
| GBP | 305 | 7027.7852 | 38569.6500 |
| USD | 1547 | 4804.7573 | 38456.8000 |
<!-- END:04_approvals_under_policy_versions__approval_time_by_currency -->

`limit_bands`: 20 approvals under pol-v2 are for totals above 5,000.00 (EUR 5, GBP 2, USD 13), the band pol-v1 could not have approved.
<!-- BEGIN:04_approvals_under_policy_versions__limit_bands -->
| policy_id | band | currency | valid_approvals |
|---|---|---|---|
| pol-v1 | total up to 5000.00 | EUR | 222 |
| pol-v1 | total up to 5000.00 | GBP | 150 |
| pol-v1 | total up to 5000.00 | USD | 683 |
| pol-v2 | total above 5000.00 up to 8000.00 | EUR | 5 |
| pol-v2 | total above 5000.00 up to 8000.00 | GBP | 2 |
| pol-v2 | total above 5000.00 up to 8000.00 | USD | 13 |
| pol-v2 | total up to 5000.00 | EUR | 220 |
| pol-v2 | total up to 5000.00 | GBP | 153 |
| pol-v2 | total up to 5000.00 | USD | 851 |
<!-- END:04_approvals_under_policy_versions__limit_bands -->

`matched_not_approved_over_limit`: **114 matched invoices are unapproved at the cutoff (USD 68, EUR 27, GBP 19) and 12 of them exceed the pol-v2 limit** (USD 6, EUR 4, GBP 2); nobody holds an escalation role, so nobody may approve those 12. (The manifest's DR-04 figure of 28 is the generator's planning counter at its own decision times, not this cutoff count.)
<!-- BEGIN:04_approvals_under_policy_versions__matched_not_approved_over_limit -->
| currency | matched_not_approved | above_the_limit | above_the_limit_total |
|---|---|---|---|
| EUR | 27 | 4 | 42165.56 |
| GBP | 19 | 2 | 16277.09 |
| USD | 68 | 6 | 57379.12 |
<!-- END:04_approvals_under_policy_versions__matched_not_approved_over_limit -->

`v1_counterfactual` is **HYPOTHETICAL** and labelled so: the 20 approvals of the band above would have had no one allowed to decide them under pol-v1 and no escalation role. Nothing in the data says they would have waited.
<!-- BEGIN:04_approvals_under_policy_versions__v1_counterfactual -->
| statement | currency | approvals |
|---|---|---|
| HYPOTHETICAL: approvals under pol-v2 above the pol-v1 limit | EUR | 5 |
| HYPOTHETICAL: approvals under pol-v2 above the pol-v1 limit | GBP | 2 |
| HYPOTHETICAL: approvals under pol-v2 above the pol-v1 limit | USD | 13 |
<!-- END:04_approvals_under_policy_versions__v1_counterfactual -->

`separation_of_duties`: every refusal the rules can make, counted from facts, is **0 in the snapshot** (no self-approval, no role or limit breach, none before the import, no self-rejection): the generator approves with an actor other than the creator and inside the limit, so these zeros show the rules were never tripped here, not that they are untested (`tests/test_rules.py` and the replay event INJ-06 exercise them). Five actors decide invoices and eleven import them; all five deciders also import other invoices, which is allowed: the rule is per invoice.
<!-- BEGIN:04_approvals_under_policy_versions__separation_of_duties -->
| check_name | n |
|---|---|
| approve decisions recorded | 2299 |
| approve decisions that are policy-valid (the committed invoices) | 2299 |
| SELF_APPROVAL: approver is the invoice creator | 0 |
| ROLE_OR_LIMIT: role not allowed, or total above the limit in force | 0 |
| BEFORE_IMPORT: decided before the invoice was imported | 0 |
| reject decisions recorded | 57 |
| reject decisions that are valid | 57 |
| SELF_DECISION: rejecter is the invoice creator | 0 |
| deciding actors who also created other invoices (allowed: the rule is per invoice) | 5 |
| distinct deciding actors | 5 |
| distinct invoice creators | 11 |
<!-- END:04_approvals_under_policy_versions__separation_of_duties -->

## 05 Exception backlog and assignment history (`05_exception_backlog_and_assignment_history.sql`)
Question: which invoices require exception review, how old is the queue and does every review have an owner? The stored history is written by the nightly matching run at 02:00 UTC; the book is recomputed for any instant.

`backlog_at_cutoffs`: **128, 201 and 232 exceptions are open in the stored history** at the three cutoffs and the facts-derived book has 129, 201 and 232: **the one-exception difference at the March month-end** is inv-1329, imported after the last 02:00 run on 2026-03-31 and recorded by the next one. Unowned: 17, 29 and 29.
<!-- BEGIN:05_exception_backlog_and_assignment_history__backlog_at_cutoffs -->
| cutoff | open_from_history | open_from_facts | difference | owned_from_history | unowned_from_history |
|---|---|---|---|---|---|
| 2026-03-31T23:59:59Z | 128 | 129 | 1 | 111 | 17 |
| 2026-06-30T23:59:59Z | 201 | 201 | 0 | 172 | 29 |
| 2026-10-01T02:00:00Z | 232 | 232 | 0 | 203 | 29 |
<!-- END:05_exception_backlog_and_assignment_history__backlog_at_cutoffs -->

`open_by_reason_and_age`: **186 of the 193 open quantity blocks are older than 30 days** (the oldest 358 days); every open price variance (32), rounding gap (4) and currency mismatch (3) is older than 30 days.
<!-- BEGIN:05_exception_backlog_and_assignment_history__open_by_reason_and_age -->
| reason | open_exceptions | age_0_to_6_days | age_7_to_13_days | age_14_to_29_days | age_30_days_or_more | oldest_days |
|---|---|---|---|---|---|---|
| CURRENCY_MISMATCH | 3 | 0 | 0 | 0 | 3 | 198 |
| PRICE_VARIANCE | 32 | 0 | 0 | 0 | 32 | 303 |
| QUANTITY_BLOCKED | 193 | 2 | 1 | 4 | 186 | 358 |
| ROUNDING_EXCEPTION | 4 | 0 | 0 | 0 | 4 | 254 |
<!-- END:05_exception_backlog_and_assignment_history__open_by_reason_and_age -->

`assignments_per_exception`: assignment history is append-only; **78 exceptions were never assigned (29 still open, 49 resolved before triage), 479 have one owner, 90 two and 13 three**.
<!-- BEGIN:05_exception_backlog_and_assignment_history__assignments_per_exception -->
| assignments | exceptions | open_at_cutoff | resolved |
|---|---|---|---|
| 0 | 78 | 29 | 49 |
| 1 | 479 | 167 | 312 |
| 2 | 90 | 29 | 61 |
| 3 | 13 | 7 | 6 |
<!-- END:05_exception_backlog_and_assignment_history__assignments_per_exception -->

`first_assignment_and_resolution`: the first assignment comes on average 30.9132 hours after a quantity block is raised and 27.7846 hours after a price variance; resolved quantity blocks took 8.9814 days on average and price variances 9.0417 days (25 price variances were resolved and 25 invoices with a price variance were rejected).
<!-- BEGIN:05_exception_backlog_and_assignment_history__first_assignment_and_resolution -->
| reason | exceptions | with_an_assignment | mean_hours_to_first_assignment | resolved | mean_days_to_resolution |
|---|---|---|---|---|---|
| CURRENCY_MISMATCH | 3 | 2 | 29.2551 | 0 |  |
| PRICE_VARIANCE | 57 | 49 | 27.7846 | 25 | 9.0417 |
| QUANTITY_BLOCKED | 596 | 527 | 30.9132 | 403 | 8.9814 |
| ROUNDING_EXCEPTION | 4 | 4 | 37.5711 | 0 |  |
<!-- END:05_exception_backlog_and_assignment_history__first_assignment_and_resolution -->

`owner_workload_at_cutoff`: the 232 open exceptions are spread over six owners (25 to 40 each) and 29 are unowned.
<!-- BEGIN:05_exception_backlog_and_assignment_history__owner_workload_at_cutoff -->
| owner | open_exceptions |
|---|---|
| usr-ap02 | 40 |
| usr-ap04 | 40 |
| usr-ap05 | 35 |
| usr-ap03 | 32 |
| usr-ap01 | 31 |
| unowned | 29 |
| usr-ap06 | 25 |
<!-- END:05_exception_backlog_and_assignment_history__owner_workload_at_cutoff -->

## 06 Export batches and reconciliation (`06_export_batches_and_reconciliation.sql`)
Question: which approved invoices have advanced to export, which have not and why? A request whose idempotency key or batch id was seen before is a repeat and returns the prior batch; an export row needs a policy-valid approval at or before its request. The difference is **zero by construction** of the generator's closing batch, so a zero shows the arithmetic and the exclusion list agree, not that a real process is complete.

`batch_summary`: **59 requests, 52 batches created and 7 repeats**, 2,299 export rows, equal to the stored `export_batches` and `export_rows`.
<!-- BEGIN:06_export_batches_and_reconciliation__batch_summary -->
| measure | n |
|---|---|
| requests received | 59 |
| batches created (non-repeat requests) | 52 |
| repeat requests answered with the prior batch | 7 |
| export rows (invoices exported) | 2299 |
| distinct invoices named by any request | 2299 |
| stored export_batches rows (cross-check) | 52 |
| stored export_rows rows (cross-check) | 2299 |
<!-- END:06_export_batches_and_reconciliation__batch_summary -->

`reconciliation_by_currency`: accepted export total against eligible approved total, **USD 1,448,006.25 (1,547 invoices), EUR 457,320.65 (447), GBP 286,543.12 (305), difference 0.00 in each currency**.
<!-- BEGIN:06_export_batches_and_reconciliation__reconciliation_by_currency -->
| currency | exported_invoices | accepted_export_total | approved_invoices | eligible_approved_total | difference |
|---|---|---|---|---|---|
| EUR | 447 | 457320.65 | 447 | 457320.65 | 0.00 |
| GBP | 305 | 286543.12 | 305 | 286543.12 | 0.00 |
| USD | 1547 | 1448006.25 | 1547 | 1448006.25 | 0.00 |
<!-- END:06_export_batches_and_reconciliation__reconciliation_by_currency -->

`exclusions_by_reason_and_currency`: the 346 invoices in the book that no export row took are explained: **232 EXCEPTION_OPEN** (USD 126, EUR 56, GBP 50) and **114 NOT_APPROVED** (USD 68, EUR 27, GBP 19); there is no APPROVED_NOT_EXPORTED and no EXPORT_BEFORE_APPROVAL here.
<!-- BEGIN:06_export_batches_and_reconciliation__exclusions_by_reason_and_currency -->
| reason_code | currency | invoices | invoice_total |
|---|---|---|---|
| EXCEPTION_OPEN | EUR | 56 | 82980.52 |
| EXCEPTION_OPEN | GBP | 50 | 77677.89 |
| EXCEPTION_OPEN | USD | 126 | 163162.81 |
| NOT_APPROVED | EUR | 27 | 74371.26 |
| NOT_APPROVED | GBP | 19 | 60826.74 |
| NOT_APPROVED | USD | 68 | 160454.22 |
<!-- END:06_export_batches_and_reconciliation__exclusions_by_reason_and_currency -->

`batch_cadence`: 51 batches go out on Fridays at 16:00 UTC (mean 44.6667 invoices, from 1 to 95) and one on a Wednesday at 22:00 (21 invoices), the closing batch.
<!-- BEGIN:06_export_batches_and_reconciliation__batch_cadence -->
| weekday_and_time | batches | fewest_invoices | most_invoices | mean_invoices |
|---|---|---|---|---|
| Fri 16:00 | 51 | 1 | 95 | 44.6667 |
| Wed 22:00 | 1 | 21 | 21 | 21.0000 |
<!-- END:06_export_batches_and_reconciliation__batch_cadence -->

`repeat_requests`: the seven retries (INJ-11) come 23 to 61 seconds after the first request and return the prior batch; none adds a row.
<!-- BEGIN:06_export_batches_and_reconciliation__repeat_requests -->
| batch_id | idempotency_key | invoices_named | seconds_after_first_request |
|---|---|---|---|
| bat-003 | exp-key-003 | 15 | 57 |
| bat-008 | exp-key-008 | 50 | 44 |
| bat-022 | exp-key-022 | 42 | 35 |
| bat-032 | exp-key-032 | 52 | 52 |
| bat-034 | exp-key-034 | 38 | 23 |
| bat-046 | exp-key-046 | 47 | 31 |
| bat-049 | exp-key-049 | 39 | 61 |
<!-- END:06_export_batches_and_reconciliation__repeat_requests -->

`approval_to_export_lag`: an approved invoice waits on average 3.1176 days (USD), 3.0633 (EUR) and 3.3183 (GBP) for its batch.
<!-- BEGIN:06_export_batches_and_reconciliation__approval_to_export_lag -->
| currency | exported_invoices | mean_days_approval_to_export | longest_days |
|---|---|---|---|
| EUR | 447 | 3.0633 | 15.3340 |
| GBP | 305 | 3.3183 | 18.3280 |
| USD | 1547 | 3.1176 | 18.3080 |
<!-- END:06_export_batches_and_reconciliation__approval_to_export_lag -->

## 07 Credits and payable by currency (`07_credits_and_payable_by_currency.sql`)
Question: how much of what advanced is payable once credits are applied? A credit reduces the payable of an obligation, once per credit id and by no more than the invoice total, and moves no cash.

`payable_by_currency`: **approved payable USD 1,416,036.99, EUR 450,586.03, GBP 281,108.17** (approved 1,448,006.25, 457,320.65, 286,543.12 less credits 31,969.26, 6,734.62, 5,434.95); 117 credit notes in all, 75 USD, 19 EUR and 23 GBP.
<!-- BEGIN:07_credits_and_payable_by_currency__payable_by_currency -->
| currency | obligations | approved_total | credit_notes | invoices_credited | credit_total | approved_payable | credit_share_of_approved_total |
|---|---|---|---|---|---|---|---|
| EUR | 447 | 457320.65 | 19 | 17 | 6734.62 | 450586.03 | 0.014726 |
| GBP | 305 | 286543.12 | 23 | 22 | 5434.95 | 281108.17 | 0.018967 |
| USD | 1547 | 1448006.25 | 75 | 73 | 31969.26 | 1416036.99 | 0.022078 |
<!-- END:07_credits_and_payable_by_currency__payable_by_currency -->

`credit_share_of_invoices`: "credit share 4.0 %" is **112 invoices of 2,800 imported (0.04), 4.9 % of the 2,299 obligations**, never a share of approvals; no credit note is against an invoice that is not an obligation.
<!-- BEGIN:07_credits_and_payable_by_currency__credit_share_of_invoices -->
| measure | n |
|---|---|
| invoices carrying at least one credit note | 112 |
| credit notes | 117 |
| invoices imported (denominator of the 4.0 % claim) | 2800 |
| obligations at the as-of (denominator of the 4.9 % reading) | 2299 |
| credit notes against an invoice that is not an obligation | 0 |
<!-- END:07_credits_and_payable_by_currency__credit_share_of_invoices -->
<!-- BEGIN:07_credits_and_payable_by_currency__credits_per_invoice -->
| credit_notes_on_the_invoice | invoices |
|---|---|
| 1 | 107 |
| 2 | 5 |
<!-- END:07_credits_and_payable_by_currency__credits_per_invoice -->

`credit_size_by_currency`: a credit is between 3 % and 100 % of its invoice; **no invoice is credited above its total** (largest share 1.000000 in each currency).
<!-- BEGIN:07_credits_and_payable_by_currency__credit_size_by_currency -->
| currency | invoices_credited | smallest_share | mean_share | largest_share | credited_above_the_invoice_total |
|---|---|---|---|---|---|
| EUR | 17 | 0.039997 | 0.577458 | 1.000000 | 0 |
| GBP | 22 | 0.039999 | 0.511591 | 1.000000 | 0 |
| USD | 73 | 0.030178 | 0.471633 | 1.000000 | 0 |
<!-- END:07_credits_and_payable_by_currency__credit_size_by_currency -->

## 08 Rejections and injected defects by reason (`08_rejections_and_injected_defects_by_reason.sql`)
Question: what was refused and why, and are the planted defects found rather than hidden? Three kinds of "no" are kept apart: ingest rejections (none here), merges (query 03) and reject decisions by a reviewer.

`ingest_outcomes`: 2,702 imports accepted, 95 + 3 merged, **0 rows rejected at ingest**, 57 reject decisions all valid.
<!-- BEGIN:08_rejections_and_injected_defects_by_reason__ingest_outcomes -->
| outcome | n |
|---|---|
| import lineage: accepted | 2702 |
| import lineage: merged (DUPLICATE_IDENTITY) | 95 |
| import lineage: merged (DUPLICATE_SOURCE_BYTES) | 3 |
| rejected_records kept (ingest rejections) | 0 |
| reject decisions (C08) recorded | 57 |
| reject decisions that are valid | 57 |
| reject decisions refused (invalid) | 0 |
<!-- END:08_rejections_and_injected_defects_by_reason__ingest_outcomes -->

`reject_decisions_by_reason`: the 57 rejections are **32 "billed ahead of receipt" on invoices that carry a quantity-block exception and 25 "unit price differs" on price-variance invoices**; all are outside the book and each has a resolved exception. The generator rejects only invoices that were exceptions in every run, so this mix is outcome-selected, not a finding.
<!-- BEGIN:08_rejections_and_injected_defects_by_reason__reject_decisions_by_reason -->
| reviewer_reason | exception_type_in_history | reject_decisions | valid | still_in_the_book | with_a_resolved_exception |
|---|---|---|---|---|---|
| Billed ahead of receipt; vendor to re-send once the delivery is booked. | QUANTITY_BLOCKED | 32 | 32 | 0 | 32 |
| Unit price differs from the purchase order; vendor to credit and re-bill at the PO price. | PRICE_VARIANCE | 25 | 25 | 0 | 25 |
<!-- END:08_rejections_and_injected_defects_by_reason__reject_decisions_by_reason -->

`injected_defect_signatures`: one signature per injected defect, written from the facts alone (it does not read the manifest; the reconciliation compares it with the manifest). **Seven are found in the snapshot** (INJ-01: 3 byte groups, INJ-02: 4 reused numbers, INJ-05: 4 rounding gaps, INJ-09: 3 foreign-currency invoices, INJ-11: 7 repeated exports, and the supersets INJ-03: 30 and INJ-04: 19 candidates that contain the 5 and 3 injected invoices). **Five are replay-only** (INJ-06 self-approval, INJ-07 racing approvals, INJ-08 a credit applied twice, INJ-10 a correction overwriting the original, INJ-12 a paid flag): they are attempts through the API that the commands refuse and that leave no row in a snapshot, so the signature finds 0 by design; the evidence for them is `tests/test_adversarial.py` and the replay events.
<!-- BEGIN:08_rejections_and_injected_defects_by_reason__injected_defect_signatures -->
| inj | signature | found | replay_only |
|---|---|---|---|
| INJ-01 | groups of invoices that share source bytes under different ids | 3 | false |
| INJ-02 | normalised invoice numbers shared by invoices of different vendors | 4 | false |
| INJ-03 | invoices with an open QUANTITY_BLOCKED outside vendors ven-020 .. ven-029 (a superset: the receipt is short, nothing follows) | 30 | false |
| INJ-04 | invoices outside ven-020 .. ven-029 with an open QUANTITY_BLOCKED line whose own quantity is within what was received (blocked by earlier consumption; a superset) | 19 | false |
| INJ-05 | invoices whose declared total differs from the computed total by more than 0.02 | 4 | false |
| INJ-06 | approvals by the invoice creator (self-approval attempt) | 0 | true |
| INJ-07 | invoices with more than one approve decision (racing approvals) | 0 | true |
| INJ-08 | credit notes beyond the first for one credit id (a credit applied twice) | 0 | true |
| INJ-09 | invoices with a line in a currency other than its purchase order's | 3 | false |
| INJ-10 | invoice ids with more than one stored version (a correction overwriting the original) | 0 | true |
| INJ-11 | export requests repeated after a timeout (same batch id and key, later exported_at) | 7 | false |
| INJ-12 | export batches carrying a paid flag (the schema has no such column) | 0 | true |
<!-- END:08_rejections_and_injected_defects_by_reason__injected_defect_signatures -->
<!-- BEGIN:08_rejections_and_injected_defects_by_reason__open_quantity_blocked_outside_02x -->
| invoice_id | vendor_id |
|---|---|
| inv-0150 | ven-031 |
| inv-0169 | ven-016 |
| inv-0278 | ven-031 |
| inv-0326 | ven-016 |
| inv-0384 | ven-007 |
| inv-0535 | ven-031 |
| inv-0598 | ven-006 |
| inv-0622 | ven-038 |
| inv-0882 | ven-033 |
| inv-0897 | ven-037 |
| inv-1042 | ven-004 |
| inv-1078 | ven-031 |
| inv-1158 | ven-011 |
| inv-1329 | ven-017 |
| inv-1522 | ven-013 |
| inv-1728 | ven-002 |
| inv-1876 | ven-039 |
| inv-1880 | ven-015 |
| inv-1994 | ven-039 |
| inv-2078 | ven-011 |
| inv-2122 | ven-001 |
| inv-2150 | ven-014 |
| inv-2272 | ven-033 |
| inv-2351 | ven-035 |
| inv-2397 | ven-002 |
| inv-2425 | ven-004 |
| inv-2590 | ven-002 |
| inv-2662 | ven-007 |
| inv-2724 | ven-016 |
| inv-2784 | ven-014 |
<!-- END:08_rejections_and_injected_defects_by_reason__open_quantity_blocked_outside_02x -->
<!-- BEGIN:08_rejections_and_injected_defects_by_reason__cumulative_blocked_candidates -->
| invoice_id | vendor_id |
|---|---|
| inv-0150 | ven-031 |
| inv-0169 | ven-016 |
| inv-0326 | ven-016 |
| inv-0535 | ven-031 |
| inv-0598 | ven-006 |
| inv-0882 | ven-033 |
| inv-0897 | ven-037 |
| inv-1042 | ven-004 |
| inv-1329 | ven-017 |
| inv-1522 | ven-013 |
| inv-1728 | ven-002 |
| inv-1876 | ven-039 |
| inv-1994 | ven-039 |
| inv-2078 | ven-011 |
| inv-2150 | ven-014 |
| inv-2272 | ven-033 |
| inv-2351 | ven-035 |
| inv-2590 | ven-002 |
| inv-2724 | ven-016 |
<!-- END:08_rejections_and_injected_defects_by_reason__cumulative_blocked_candidates -->

## 09 The golden fixture (`09_golden_known_answer.sql`)
The spec sentence recomputed from the facts of the golden database (P05-GOLD-01): the first invoice is 6 x 20.00 = 120.00 + 12.00 tax = **132.00**, the second 4 x 20.00 = 80.00 + 8.00 = 88.00 is blocked (available for it 0.0000 after the first took the 6 received, a quantity variance of 4.0000), and the third has the same identity as the first (one group of two invoices with two different source hashes): importing the first twice leaves one obligation.
<!-- BEGIN:09_golden_known_answer__golden_per_invoice -->
| invoice_id | subtotal | tax | total | declared_total | rounding_difference |
|---|---|---|---|---|---|
| inv-001 | 120.00 | 12.00 | 132.00 | 132.00 | 0.00 |
| inv-002 | 80.00 | 8.00 | 88.00 | 88.00 | 0.00 |
| inv-003 | 120.00 | 12.00 | 132.00 | 132.00 | 0.00 |
<!-- END:09_golden_known_answer__golden_per_invoice -->
<!-- BEGIN:09_golden_known_answer__golden_identity_groups -->
| identity_key | invoices | distinct_source_bytes | earliest_invoice_id |
|---|---|---|---|
| ven-001/INV1001/2026-10-06/132.00 | 2 | 2 | inv-001 |
| ven-001/INV1002/2026-10-06/88.00 | 1 | 1 | inv-002 |
<!-- END:09_golden_known_answer__golden_identity_groups -->
<!-- BEGIN:09_golden_known_answer__golden_quantities -->
| po_line_id | ordered_quantity | net_received_quantity | first_invoice_quantity | available_for_the_second_invoice | second_invoice_quantity | quantity_variance_of_the_second_invoice |
|---|---|---|---|---|---|---|
| pol-001 | 10.0000 | 6.0000 | 6.0000 | 0.0000 | 4.0000 | 4.0000 |
<!-- END:09_golden_known_answer__golden_quantities -->

## 10 Reconciliation
Five kinds of check, all in `run_all.py`: **A** the golden fixture (`data/sql/reference_metrics.sql`, the Python domain and `expected.json` agree on all eleven metric keys; the per-invoice amounts, the duplicate identity and the quantities of 09 equal the hand calculation of `expected.json`);
**B** snapshot headline figures (each investigation against `reference_metrics.sql` and the domain, and the two against each other on all eleven keys; quantities are compared across currencies as units, money per currency, and the received-not-invoiced value per currency against the domain only because the reference has one unconverted sum);
**C** every result set cell by cell against `data/sql/analysis/python_side.py` (the domain's book and exact arithmetic, no SQL: the stored numbers equal the Python domain without a database);
**D** group figures against the domain's `group_metrics` (vendor and currency) and the two month-ends against the SQL reference and the domain at those instants; **E** the injection manifest and the designed relationships against what the SQL finds, and the BI measures recomputed from the CSV facts against the reference and the domain.
Columns: the investigation's value, then the other sources; `equal` is true only if every present source prints the same text. The one disclosed difference (the stored history against the derived book at the March month-end) is compared as the pair of differences it is, not hidden.

<!-- BEGIN:reconciliation -->
| check | analysis_sql | second_source | third_source | fourth_source | equal |
|---|---|---|---|---|---|
| A golden metric matched: reference SQL = Python domain = expected.json (digest) | 898f235f83a84ba1 | 898f235f83a84ba1 | 898f235f83a84ba1 |  | true |
| A golden metric obligations: reference SQL = Python domain = expected.json (digest) | e0c8e7b23e500747 | e0c8e7b23e500747 | e0c8e7b23e500747 |  | true |
| A golden metric exceptions: reference SQL = Python domain = expected.json (digest) | 699b4735882a8b2d | 699b4735882a8b2d | 699b4735882a8b2d |  | true |
| A golden metric duplicates: reference SQL = Python domain = expected.json (digest) | d90fa60126350562 | d90fa60126350562 | d90fa60126350562 |  | true |
| A golden metric quantities: reference SQL = Python domain = expected.json (digest) | e15e6f97ce67b460 | e15e6f97ce67b460 | e15e6f97ce67b460 |  | true |
| A golden metric snapshots: reference SQL = Python domain = expected.json (digest) | b3dd5236f51db1ee | b3dd5236f51db1ee | b3dd5236f51db1ee |  | true |
| A golden metric rates: reference SQL = Python domain = expected.json (digest) | e8f2248d5d2616dd | e8f2248d5d2616dd | e8f2248d5d2616dd |  | true |
| A golden metric processing: reference SQL = Python domain = expected.json (digest) | 22913235bfa5949b | 22913235bfa5949b | 22913235bfa5949b |  | true |
| A golden metric approvals: reference SQL = Python domain = expected.json (digest) | 3a117ba094d99650 | 3a117ba094d99650 | 3a117ba094d99650 |  | true |
| A golden metric payable: reference SQL = Python domain = expected.json (digest) | 2cfb9a9e8cfe7c79 | 2cfb9a9e8cfe7c79 | 2cfb9a9e8cfe7c79 |  | true |
| A golden metric export: reference SQL = Python domain = expected.json (digest) | a235342489774801 | a235342489774801 | a235342489774801 |  | true |
| A golden inv-001: subtotal/tax/total/declared/rounding difference (09 vs expected.json vs domain) | 120.00/12.00/132.00/132.00/0.00 | 120.00/12.00/132.00/132.00/0.00 | 120.00/12.00/132.00/132.00/0.00 |  | true |
| A golden inv-002: subtotal/tax/total/declared/rounding difference (09 vs expected.json vs domain) | 80.00/8.00/88.00/88.00/0.00 | 80.00/8.00/88.00/88.00/0.00 | 80.00/8.00/88.00/88.00/0.00 |  | true |
| A golden inv-003: subtotal/tax/total/declared/rounding difference (09 vs expected.json vs domain) | 120.00/12.00/132.00/132.00/0.00 | 120.00/12.00/132.00/132.00/0.00 | 120.00/12.00/132.00/132.00/0.00 |  | true |
| A golden duplicate identity group (09 vs expected.json merged record) | ven-001/INV1001/2026-10-06/132.00 | ven-001/INV1001/2026-10-06/132.00 | ven-001/INV1001/2026-10-06/132.00 |  | true |
| A golden ordered / net received / available to the second invoice / quantity variance (09 vs expected.json vs domain) | 10.0000/6.0000/0.0000/4.0000 | 10.0000/6.0000/0.0000/4.0000 | 10.0000/6.0000/0.0000/4.0000 |  | true |
| B reference SQL equals the Python domain on metric key matched (snapshot, as-of, digest) | b1475bd72b2158ed | b1475bd72b2158ed |  |  | true |
| B reference SQL equals the Python domain on metric key obligations (snapshot, as-of, digest) | d2540c2e98991051 | d2540c2e98991051 |  |  | true |
| B reference SQL equals the Python domain on metric key exceptions (snapshot, as-of, digest) | eebaa25ac98a34cc | eebaa25ac98a34cc |  |  | true |
| B reference SQL equals the Python domain on metric key duplicates (snapshot, as-of, digest) | e8fd4900c6185ffe | e8fd4900c6185ffe |  |  | true |
| B reference SQL equals the Python domain on metric key quantities (snapshot, as-of, digest) | f70ca91b32cd0124 | f70ca91b32cd0124 |  |  | true |
| B reference SQL equals the Python domain on metric key snapshots (snapshot, as-of, digest) | 4ddb58bfbe99c50b | 4ddb58bfbe99c50b |  |  | true |
| B reference SQL equals the Python domain on metric key rates (snapshot, as-of, digest) | e94424aa852b1d90 | e94424aa852b1d90 |  |  | true |
| B reference SQL equals the Python domain on metric key processing (snapshot, as-of, digest) | c3197cce74d5a7b7 | c3197cce74d5a7b7 |  |  | true |
| B reference SQL equals the Python domain on metric key approvals (snapshot, as-of, digest) | 3b5bca1e6b087a63 | 3b5bca1e6b087a63 |  |  | true |
| B reference SQL equals the Python domain on metric key payable (snapshot, as-of, digest) | 03577ef402b2bcdb | 03577ef402b2bcdb |  |  | true |
| B reference SQL equals the Python domain on metric key export (snapshot, as-of, digest) | c673d02f54ca5176 | c673d02f54ca5176 |  |  | true |
| B matched.invoice_count | 2413 | 2413 | 2413 |  | true |
| B matched.by_currency.EUR.invoice_count | 474 | 474 | 474 |  | true |
| B matched.by_currency.EUR.total | 531691.91 | 531691.91 | 531691.91 |  | true |
| B obligations.by_currency.EUR.count | 447 | 447 | 447 | 447 | true |
| B obligations.by_currency.EUR.total | 457320.65 | 457320.65 | 457320.65 | 457320.65 | true |
| B payable.by_currency.EUR.approved_total | 457320.65 | 457320.65 | 457320.65 |  | true |
| B payable.by_currency.EUR.credit_total | 6734.62 | 6734.62 | 6734.62 |  | true |
| B payable.by_currency.EUR.approved_payable | 450586.03 | 450586.03 | 450586.03 |  | true |
| B export.by_currency.EUR.accepted_export_total | 457320.65 | 457320.65 | 457320.65 |  | true |
| B export.by_currency.EUR.eligible_approved_total | 457320.65 | 457320.65 | 457320.65 |  | true |
| B export.by_currency.EUR.difference | 0.00 | 0.00 | 0.00 |  | true |
| B matched.by_currency.GBP.invoice_count | 324 | 324 | 324 |  | true |
| B matched.by_currency.GBP.total | 347369.86 | 347369.86 | 347369.86 |  | true |
| B obligations.by_currency.GBP.count | 305 | 305 | 305 | 305 | true |
| B obligations.by_currency.GBP.total | 286543.12 | 286543.12 | 286543.12 | 286543.12 | true |
| B payable.by_currency.GBP.approved_total | 286543.12 | 286543.12 | 286543.12 |  | true |
| B payable.by_currency.GBP.credit_total | 5434.95 | 5434.95 | 5434.95 |  | true |
| B payable.by_currency.GBP.approved_payable | 281108.17 | 281108.17 | 281108.17 |  | true |
| B export.by_currency.GBP.accepted_export_total | 286543.12 | 286543.12 | 286543.12 |  | true |
| B export.by_currency.GBP.eligible_approved_total | 286543.12 | 286543.12 | 286543.12 |  | true |
| B export.by_currency.GBP.difference | 0.00 | 0.00 | 0.00 |  | true |
| B matched.by_currency.USD.invoice_count | 1615 | 1615 | 1615 |  | true |
| B matched.by_currency.USD.total | 1608460.47 | 1608460.47 | 1608460.47 |  | true |
| B obligations.by_currency.USD.count | 1547 | 1547 | 1547 | 1547 | true |
| B obligations.by_currency.USD.total | 1448006.25 | 1448006.25 | 1448006.25 | 1448006.25 | true |
| B payable.by_currency.USD.approved_total | 1448006.25 | 1448006.25 | 1448006.25 |  | true |
| B payable.by_currency.USD.credit_total | 31969.26 | 31969.26 | 31969.26 |  | true |
| B payable.by_currency.USD.approved_payable | 1416036.99 | 1416036.99 | 1416036.99 |  | true |
| B export.by_currency.USD.accepted_export_total | 1448006.25 | 1448006.25 | 1448006.25 |  | true |
| B export.by_currency.USD.eligible_approved_total | 1448006.25 | 1448006.25 | 1448006.25 |  | true |
| B export.by_currency.USD.difference | 0.00 | 0.00 | 0.00 |  | true |
| B export.requests_received | 59 | 59 | 59 |  | true |
| B export.batches_created | 52 | 52 | 52 |  | true |
| B export.repeat_requests_returned_prior | 7 | 7 | 7 |  | true |
| B export rows | 2299 | 2299 | 2299 | 2299 | true |
| B export.exclusions EXCEPTION_OPEN (invoices) | 232 | 232 | 232 |  | true |
| B export.exclusions NOT_APPROVED (invoices) | 114 | 114 | 114 |  | true |
| B export.exclusions EXPORT_BEFORE_APPROVAL (invoices) | 0 | 0 | 0 |  | true |
| B export.exclusions APPROVED_NOT_EXPORTED (invoices) | 0 | 0 | 0 |  | true |
| B exceptions.open_count | 232 | 232 | 232 | 232 | true |
| B exceptions.unowned_count | 29 | 29 | 29 |  | true |
| B exceptions.by_reason.QUANTITY_BLOCKED | 193 | 193 | 193 |  | true |
| B exceptions.by_reason.PRICE_VARIANCE | 32 | 32 | 32 |  | true |
| B exceptions.by_reason.NO_PO_LINE | 0 | 0 | 0 |  | true |
| B exceptions.by_reason.ROUNDING_EXCEPTION | 4 | 4 | 4 |  | true |
| B exceptions.by_reason.CURRENCY_MISMATCH | 3 | 3 | 3 |  | true |
| B duplicates.rows_merged | 98 | 98 | 98 |  | true |
| B duplicates.groups_detected | 98 | 98 | 98 |  | true |
| B quantities.ordered_quantity (units, all currencies) | 202310.2500 | 202310.2500 | 202310.2500 |  | true |
| B quantities.net_received_quantity (units, all currencies) | 191431.0000 | 191431.0000 | 191431.0000 |  | true |
| B quantities.accepted_invoiced_quantity (units, all currencies) | 176112.2500 | 176112.2500 | 176112.2500 |  | true |
| B quantities.open_to_receive_quantity (units, all currencies) | 10879.2500 | 10879.2500 | 10879.2500 |  | true |
| B quantities.open_to_invoice_quantity (units, all currencies) | 26198.0000 | 26198.0000 | 26198.0000 |  | true |
| B quantities.received_not_invoiced_quantity (units, all currencies) | 15318.7500 | 15318.7500 | 15318.7500 |  | true |
| B snapshots.2026-03-31T23:59:59Z.ordered_quantity (units, all currencies) | 105243.2500 | 105243.2500 | 105243.2500 |  | true |
| B snapshots.2026-03-31T23:59:59Z.net_received_quantity (units, all currencies) | 89156.2500 | 89156.2500 | 89156.2500 |  | true |
| B snapshots.2026-03-31T23:59:59Z.accepted_invoiced_quantity (units, all currencies) | 78554.5000 | 78554.5000 | 78554.5000 |  | true |
| B snapshots.2026-03-31T23:59:59Z.open_to_receive_quantity (units, all currencies) | 16087.0000 | 16087.0000 | 16087.0000 |  | true |
| B snapshots.2026-03-31T23:59:59Z.open_to_invoice_quantity (units, all currencies) | 26688.7500 | 26688.7500 | 26688.7500 |  | true |
| B snapshots.2026-03-31T23:59:59Z.received_not_invoiced_quantity (units, all currencies) | 10601.7500 | 10601.7500 | 10601.7500 |  | true |
| B snapshots.2026-06-30T23:59:59Z.ordered_quantity (units, all currencies) | 170228.0000 | 170228.0000 | 170228.0000 |  | true |
| B snapshots.2026-06-30T23:59:59Z.net_received_quantity (units, all currencies) | 147243.5000 | 147243.5000 | 147243.5000 |  | true |
| B snapshots.2026-06-30T23:59:59Z.accepted_invoiced_quantity (units, all currencies) | 129745.5000 | 129745.5000 | 129745.5000 |  | true |
| B snapshots.2026-06-30T23:59:59Z.open_to_receive_quantity (units, all currencies) | 22984.5000 | 22984.5000 | 22984.5000 |  | true |
| B snapshots.2026-06-30T23:59:59Z.open_to_invoice_quantity (units, all currencies) | 40482.5000 | 40482.5000 | 40482.5000 |  | true |
| B snapshots.2026-06-30T23:59:59Z.received_not_invoiced_quantity (units, all currencies) | 17498.0000 | 17498.0000 | 17498.0000 |  | true |
| B snapshots.2026-10-01T02:00:00Z.ordered_quantity (units, all currencies) | 202310.2500 | 202310.2500 | 202310.2500 |  | true |
| B snapshots.2026-10-01T02:00:00Z.net_received_quantity (units, all currencies) | 191431.0000 | 191431.0000 | 191431.0000 |  | true |
| B snapshots.2026-10-01T02:00:00Z.accepted_invoiced_quantity (units, all currencies) | 176112.2500 | 176112.2500 | 176112.2500 |  | true |
| B snapshots.2026-10-01T02:00:00Z.open_to_receive_quantity (units, all currencies) | 10879.2500 | 10879.2500 | 10879.2500 |  | true |
| B snapshots.2026-10-01T02:00:00Z.open_to_invoice_quantity (units, all currencies) | 26198.0000 | 26198.0000 | 26198.0000 |  | true |
| B snapshots.2026-10-01T02:00:00Z.received_not_invoiced_quantity (units, all currencies) | 15318.7500 | 15318.7500 | 15318.7500 |  | true |
| B received_not_invoiced_value EUR at 2026-03-31T23:59:59Z (own currency; SQL analysis vs domain) | 42551.45 | 42551.45 |  |  | true |
| B received_not_invoiced_value GBP at 2026-03-31T23:59:59Z (own currency; SQL analysis vs domain) | 14216.52 | 14216.52 |  |  | true |
| B received_not_invoiced_value USD at 2026-03-31T23:59:59Z (own currency; SQL analysis vs domain) | 94597.54 | 94597.54 |  |  | true |
| B received_not_invoiced_value EUR at 2026-06-30T23:59:59Z (own currency; SQL analysis vs domain) | 43496.96 | 43496.96 |  |  | true |
| B received_not_invoiced_value GBP at 2026-06-30T23:59:59Z (own currency; SQL analysis vs domain) | 28439.13 | 28439.13 |  |  | true |
| B received_not_invoiced_value USD at 2026-06-30T23:59:59Z (own currency; SQL analysis vs domain) | 146635.00 | 146635.00 |  |  | true |
| B received_not_invoiced_value EUR at 2026-10-01T02:00:00Z (own currency; SQL analysis vs domain) | 49602.39 | 49602.39 |  |  | true |
| B received_not_invoiced_value GBP at 2026-10-01T02:00:00Z (own currency; SQL analysis vs domain) | 38609.28 | 38609.28 |  |  | true |
| B received_not_invoiced_value USD at 2026-10-01T02:00:00Z (own currency; SQL analysis vs domain) | 135134.34 | 135134.34 |  |  | true |
| B rates.eligible_invoices | 2645 | 2645 | 2645 |  | true |
| B rates.straight_through_rate (not blocked at the cutoff) | 0.912287 | 0.912287 | 0.912287 |  | true |
| B rates.exception_rate | 0.087713 | 0.087713 | 0.087713 |  | true |
| B processing.approved_count | 2299 | 2299 | 2299 |  | true |
| B approvals.valid_count | 2299 | 2299 | 2299 |  | true |
| B processing.pending_count | 346 | 346 | 346 |  | true |
| B approvals.invalid_records (count) | 0 | 0 | 0 |  | true |
| B credit notes applied (count across currencies) | 117 | 117 |  |  | true |
| C 01_match_outcomes_by_vendor_and_reason__reason_open_vs_ever: 6 rows, 36 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 01_match_outcomes_by_vendor_and_reason__vendor_group_open_vs_ever: 3 rows, 24 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 01_match_outcomes_by_vendor_and_reason__by_vendor: 40 rows, 280 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 01_match_outcomes_by_vendor_and_reason__by_currency: 3 rows, 15 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 01_match_outcomes_by_vendor_and_reason__history_by_vendor_group: 5 rows, 25 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 01_match_outcomes_by_vendor_and_reason__rates_by_currency: 3 rows, 18 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 02_cumulative_consumption_by_po_line__totals_by_cutoff: 12 rows, 120 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 02_cumulative_consumption_by_po_line__line_state_by_cutoff: 15 rows, 45 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 02_cumulative_consumption_by_po_line__ladder_top_lines: 10 rows, 100 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_duplicates_identity_vs_bytes_and_month_end__merges_by_reason_and_cutoff: 6 rows, 24 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_duplicates_identity_vs_bytes_and_month_end__identity_vs_bytes: 2 rows, 12 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_duplicates_identity_vs_bytes_and_month_end__month_end_clustering: 3 rows, 12 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_duplicates_identity_vs_bytes_and_month_end__merged_by_import_month: 12 rows, 36 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_duplicates_identity_vs_bytes_and_month_end__same_number_other_vendor: 4 rows, 16 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_duplicates_identity_vs_bytes_and_month_end__lineage_append_only: 3 rows, 12 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_approvals_under_policy_versions__decisions_by_policy_version: 2 rows, 14 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_approvals_under_policy_versions__approvals_by_policy_and_currency: 6 rows, 36 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_approvals_under_policy_versions__approval_time_by_currency: 3 rows, 12 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_approvals_under_policy_versions__limit_bands: 9 rows, 36 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_approvals_under_policy_versions__matched_not_approved_over_limit: 3 rows, 12 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_approvals_under_policy_versions__v1_counterfactual: 3 rows, 9 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_approvals_under_policy_versions__separation_of_duties: 11 rows, 22 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 05_exception_backlog_and_assignment_history__backlog_at_cutoffs: 3 rows, 18 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 05_exception_backlog_and_assignment_history__open_by_reason_and_age: 4 rows, 28 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 05_exception_backlog_and_assignment_history__assignments_per_exception: 4 rows, 16 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 05_exception_backlog_and_assignment_history__first_assignment_and_resolution: 4 rows, 24 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 05_exception_backlog_and_assignment_history__owner_workload_at_cutoff: 7 rows, 14 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 06_export_batches_and_reconciliation__batch_summary: 7 rows, 14 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 06_export_batches_and_reconciliation__reconciliation_by_currency: 3 rows, 18 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 06_export_batches_and_reconciliation__exclusions_by_reason_and_currency: 6 rows, 24 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 06_export_batches_and_reconciliation__batch_cadence: 2 rows, 10 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 06_export_batches_and_reconciliation__repeat_requests: 7 rows, 28 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 06_export_batches_and_reconciliation__approval_to_export_lag: 3 rows, 12 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 07_credits_and_payable_by_currency__payable_by_currency: 3 rows, 24 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 07_credits_and_payable_by_currency__credit_share_of_invoices: 5 rows, 10 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 07_credits_and_payable_by_currency__credits_per_invoice: 2 rows, 4 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 07_credits_and_payable_by_currency__credit_size_by_currency: 3 rows, 18 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 08_rejections_and_injected_defects_by_reason__ingest_outcomes: 7 rows, 14 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 08_rejections_and_injected_defects_by_reason__reject_decisions_by_reason: 2 rows, 12 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 08_rejections_and_injected_defects_by_reason__injected_defect_signatures: 12 rows, 48 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 08_rejections_and_injected_defects_by_reason__open_quantity_blocked_outside_02x: 30 rows, 60 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| C 08_rejections_and_injected_defects_by_reason__cumulative_blocked_candidates: 19 rows, 38 cells, cells differing from the Python side | 0 | 0 |  |  | true |
| D vendor ven-001: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 93/91/2 | 93/91/2 |  |  | true |
| D vendor ven-002: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 86/83/3 | 86/83/3 |  |  | true |
| D vendor ven-003: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 43/43/0 | 43/43/0 |  |  | true |
| D vendor ven-004: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 105/103/2 | 105/103/2 |  |  | true |
| D vendor ven-005: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 73/73/0 | 73/73/0 |  |  | true |
| D vendor ven-006: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 127/125/2 | 127/125/2 |  |  | true |
| D vendor ven-007: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 184/152/32 | 184/152/32 |  |  | true |
| D vendor ven-008: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 47/46/1 | 47/46/1 |  |  | true |
| D vendor ven-009: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 13/12/1 | 13/12/1 |  |  | true |
| D vendor ven-010: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 90/89/1 | 90/89/1 |  |  | true |
| D vendor ven-011: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 91/89/2 | 91/89/2 |  |  | true |
| D vendor ven-012: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 32/32/0 | 32/32/0 |  |  | true |
| D vendor ven-013: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 59/58/1 | 59/58/1 |  |  | true |
| D vendor ven-014: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 72/70/2 | 72/70/2 |  |  | true |
| D vendor ven-015: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 26/25/1 | 26/25/1 |  |  | true |
| D vendor ven-016: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 122/119/3 | 122/119/3 |  |  | true |
| D vendor ven-017: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 80/79/1 | 80/79/1 |  |  | true |
| D vendor ven-018: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 25/24/1 | 25/24/1 |  |  | true |
| D vendor ven-019: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 76/76/0 | 76/76/0 |  |  | true |
| D vendor ven-020: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 37/25/12 | 37/25/12 |  |  | true |
| D vendor ven-021: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 37/22/15 | 37/22/15 |  |  | true |
| D vendor ven-022: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 53/39/14 | 53/39/14 |  |  | true |
| D vendor ven-023: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 61/44/17 | 61/44/17 |  |  | true |
| D vendor ven-024: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 8/5/3 | 8/5/3 |  |  | true |
| D vendor ven-025: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 82/55/27 | 82/55/27 |  |  | true |
| D vendor ven-026: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 85/57/28 | 85/57/28 |  |  | true |
| D vendor ven-027: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 43/31/12 | 43/31/12 |  |  | true |
| D vendor ven-028: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 74/55/19 | 74/55/19 |  |  | true |
| D vendor ven-029: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 58/42/16 | 58/42/16 |  |  | true |
| D vendor ven-030: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 37/36/1 | 37/36/1 |  |  | true |
| D vendor ven-031: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 126/121/5 | 126/121/5 |  |  | true |
| D vendor ven-032: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 45/45/0 | 45/45/0 |  |  | true |
| D vendor ven-033: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 121/119/2 | 121/119/2 |  |  | true |
| D vendor ven-034: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 89/89/0 | 89/89/0 |  |  | true |
| D vendor ven-035: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 56/55/1 | 56/55/1 |  |  | true |
| D vendor ven-036: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 32/32/0 | 32/32/0 |  |  | true |
| D vendor ven-037: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 35/34/1 | 35/34/1 |  |  | true |
| D vendor ven-038: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 50/49/1 | 50/49/1 |  |  | true |
| D vendor ven-039: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 72/69/3 | 72/69/3 |  |  | true |
| D vendor ven-040: invoices in the book / matched / open exceptions (SQL vs domain group_metrics) | 0/0/0 | 0/0/0 |  |  | true |
| D currency EUR: in the book / matched / matched total / obligations / approved total (SQL vs domain group_metrics) | 530/474/531691.91/447/457320.65 | 530/474/531691.91/447/457320.65 |  |  | true |
| D currency GBP: in the book / matched / matched total / obligations / approved total (SQL vs domain group_metrics) | 374/324/347369.86/305/286543.12 | 374/324/347369.86/305/286543.12 |  |  | true |
| D currency USD: in the book / matched / matched total / obligations / approved total (SQL vs domain group_metrics) | 1741/1615/1608460.47/1547/1448006.25 | 1741/1615/1608460.47/1547/1448006.25 |  |  | true |
| D 2026-03-31T23:59:59Z: duplicates.rows_merged (03 vs reference SQL vs domain) | 52 | 52 | 52 |  | true |
| D 2026-03-31T23:59:59Z: exceptions.open_count (05 facts vs reference SQL vs domain) | 129 | 129 | 129 |  | true |
| D 2026-03-31T23:59:59Z: quantities.net_received_quantity (02 vs reference SQL vs domain) | 89156.2500 | 89156.2500 | 89156.2500 |  | true |
| D 2026-03-31T23:59:59Z: quantities.accepted_invoiced_quantity (02 vs reference SQL vs domain) | 78554.5000 | 78554.5000 | 78554.5000 |  | true |
| D 2026-03-31T23:59:59Z: quantities.received_not_invoiced_quantity (02 vs reference SQL vs domain) | 10601.7500 | 10601.7500 | 10601.7500 |  | true |
| D 2026-03-31T23:59:59Z: matched.invoice_count (the domain book's matched invoices vs reference SQL vs domain metric) | 1131 | 1131 | 1131 |  | true |
| D 2026-06-30T23:59:59Z: duplicates.rows_merged (03 vs reference SQL vs domain) | 70 | 70 | 70 |  | true |
| D 2026-06-30T23:59:59Z: exceptions.open_count (05 facts vs reference SQL vs domain) | 201 | 201 | 201 |  | true |
| D 2026-06-30T23:59:59Z: quantities.net_received_quantity (02 vs reference SQL vs domain) | 147243.5000 | 147243.5000 | 147243.5000 |  | true |
| D 2026-06-30T23:59:59Z: quantities.accepted_invoiced_quantity (02 vs reference SQL vs domain) | 129745.5000 | 129745.5000 | 129745.5000 |  | true |
| D 2026-06-30T23:59:59Z: quantities.received_not_invoiced_quantity (02 vs reference SQL vs domain) | 17498.0000 | 17498.0000 | 17498.0000 |  | true |
| D 2026-06-30T23:59:59Z: matched.invoice_count (the domain book's matched invoices vs reference SQL vs domain metric) | 1787 | 1787 | 1787 |  | true |
| D the stored exception history differs from the facts-derived backlog only at the March month-end (open_from_facts - open_from_history) | 1/0/0 | 1/0/0 |  |  | true |
| E INJ-01 same bytes under two ids: groups found / manifest | 3 | 3 |  |  | true |
| E INJ-02 invoice number reused across vendors: groups found / manifest | 4 | 4 |  |  | true |
| E INJ-03 partial receipts: injected invoices inside the SQL candidate set (of the manifest's) | 5 | 5 |  |  | true |
| E INJ-04 cumulative consumption: injected invoices inside the SQL candidate set (of the manifest's) | 3 | 3 |  |  | true |
| E INJ-05 rounding gap over tolerance: invoices found / manifest | 4 | 4 |  |  | true |
| E INJ-09 foreign-currency lines: invoices found / manifest | 3 | 3 |  |  | true |
| E INJ-11 repeated export requests: found / manifest | 7 | 7 |  |  | true |
| E INJ-06 replay-only: rows in the snapshot / manifest record_count (handling_kind replay_only) | 0/true | 0/true |  |  | true |
| E INJ-07 replay-only: rows in the snapshot / manifest record_count (handling_kind replay_only) | 0/true | 0/true |  |  | true |
| E INJ-08 replay-only: rows in the snapshot / manifest record_count (handling_kind replay_only) | 0/true | 0/true |  |  | true |
| E INJ-10 replay-only: rows in the snapshot / manifest record_count (handling_kind replay_only) | 0/true | 0/true |  |  | true |
| E INJ-12 replay-only: rows in the snapshot / manifest record_count (handling_kind replay_only) | 0/true | 0/true |  |  | true |
| E ingest rejections kept / manifest expected rejections | 0 | 0 |  |  | true |
| E INJ-01 merges by bytes at the as-of / manifest | 3 | 3 |  |  | true |
| E DR-01 ven-02x invoices / quantity-blocked open / rate (4 dp) | 538/163/0.3030 | 538/163/0.3030 |  |  | true |
| E DR-01 other invoices / quantity-blocked open / rate (4 dp) | 2107/30/0.0142 | 2107/30/0.0142 |  |  | true |
| E DR-01 ven-02x share of open quantity blocks (4 dp) | 0.8446 | 0.8446 |  |  | true |
| E DR-02 ven-007 open price variances / all open price variances / ven-007 invoices / share (4 dp) | 30/32/184/0.9375 | 30/32/184/0.9375 |  |  | true |
| E DR-03 re-sent PDFs / imported in the last three days / share / all-invoice share (4 dp) | 95/71/0.7474/0.1904 | 95/71/0.7474/0.1904 |  |  | true |
| E DR-04 approvals between the two limits after the change (HYPOTHETICAL v1 counterfactual rows summed) | 20 | 20 |  |  | true |
| E BI fact_invoice: 2,800 rows, status_at_asof equals the domain's derived status for every invoice (mismatches) | 2800/0 | 2800/0 |  |  | true |
| E BI measure matched_invoices (CSV facts vs reference SQL vs domain) | 2413 | 2413 | 2413 |  | true |
| E BI measure obligations (CSV facts vs reference SQL vs domain) | 2299 | 2299 | 2299 |  | true |
| E BI measure open_exceptions (CSV facts vs reference SQL vs domain) | 232 | 232 | 232 |  | true |
| E BI measure unowned_exceptions (CSV facts vs reference SQL vs domain) | 29 | 29 | 29 |  | true |
| E BI measure eligible_invoices (CSV facts vs reference SQL vs domain) | 2645 | 2645 | 2645 |  | true |
| E BI measure exception_rate (CSV facts vs reference SQL vs domain) | 0.087713 | 0.087713 | 0.087713 |  | true |
| E BI measure straight_through_rate (CSV facts vs reference SQL vs domain) | 0.912287 | 0.912287 | 0.912287 |  | true |
| E BI measure ever_excepted_rate (CSV facts vs reference SQL vs domain) | 0.227599 | 0.227599 | 0.227599 |  | true |
| E BI measure never_excepted_rate (CSV facts vs reference SQL vs domain) | 0.772401 | 0.772401 | 0.772401 |  | true |
| E BI measure approved_invoices (CSV facts vs reference SQL vs domain) | 2299 | 2299 | 2299 |  | true |
| E BI measure mean_minutes_to_approval (CSV facts vs reference SQL vs domain) | 5466.7066 | 5466.7066 | 5466.7066 |  | true |
| E BI measure pending_invoices (CSV facts vs reference SQL vs domain) | 346 | 346 | 346 |  | true |
| E BI measure duplicates_merged (CSV facts vs reference SQL vs domain) | 98 | 98 | 98 |  | true |
| E BI measure open_exceptions QUANTITY_BLOCKED | 193 | 193 | 193 |  | true |
| E BI measure open_exceptions PRICE_VARIANCE | 32 | 32 | 32 |  | true |
| E BI measure open_exceptions NO_PO_LINE | 0 | 0 | 0 |  | true |
| E BI measure open_exceptions ROUNDING_EXCEPTION | 4 | 4 | 4 |  | true |
| E BI measure open_exceptions CURRENCY_MISMATCH | 3 | 3 | 3 |  | true |
| E BI measure ordered_quantity (units) | 202310.2500 | 202310.2500 | 202310.2500 |  | true |
| E BI measure net_received_quantity (units) | 191431.0000 | 191431.0000 | 191431.0000 |  | true |
| E BI measure accepted_invoiced_quantity (units) | 176112.2500 | 176112.2500 | 176112.2500 |  | true |
| E BI measure open_to_receive_quantity (units) | 10879.2500 | 10879.2500 | 10879.2500 |  | true |
| E BI measure open_to_invoice_quantity (units) | 26198.0000 | 26198.0000 | 26198.0000 |  | true |
| E BI measure received_not_invoiced_quantity (units) | 15318.7500 | 15318.7500 | 15318.7500 |  | true |
| E BI measure matched_invoices EUR | 474 | 474 |  |  | true |
| E BI measure matched_total EUR | 531691.91 | 531691.91 | 531691.91 |  | true |
| E BI measure obligations EUR | 447 | 447 |  |  | true |
| E BI measure approved_total EUR | 457320.65 | 457320.65 | 457320.65 |  | true |
| E BI measure credit_total EUR | 6734.62 | 6734.62 | 6734.62 |  | true |
| E BI measure approved_payable EUR | 450586.03 | 450586.03 | 450586.03 |  | true |
| E BI measure accepted_export_total EUR | 457320.65 | 457320.65 |  |  | true |
| E BI measure export_difference EUR | 0.00 | 0.00 |  |  | true |
| E BI measure received_not_invoiced_value EUR (own currency; vs domain) | 49602.39 | 49602.39 |  |  | true |
| E BI measure matched_invoices GBP | 324 | 324 |  |  | true |
| E BI measure matched_total GBP | 347369.86 | 347369.86 | 347369.86 |  | true |
| E BI measure obligations GBP | 305 | 305 |  |  | true |
| E BI measure approved_total GBP | 286543.12 | 286543.12 | 286543.12 |  | true |
| E BI measure credit_total GBP | 5434.95 | 5434.95 | 5434.95 |  | true |
| E BI measure approved_payable GBP | 281108.17 | 281108.17 | 281108.17 |  | true |
| E BI measure accepted_export_total GBP | 286543.12 | 286543.12 |  |  | true |
| E BI measure export_difference GBP | 0.00 | 0.00 |  |  | true |
| E BI measure received_not_invoiced_value GBP (own currency; vs domain) | 38609.28 | 38609.28 |  |  | true |
| E BI measure matched_invoices USD | 1615 | 1615 |  |  | true |
| E BI measure matched_total USD | 1608460.47 | 1608460.47 | 1608460.47 |  | true |
| E BI measure obligations USD | 1547 | 1547 |  |  | true |
| E BI measure approved_total USD | 1448006.25 | 1448006.25 | 1448006.25 |  | true |
| E BI measure credit_total USD | 31969.26 | 31969.26 | 31969.26 |  | true |
| E BI measure approved_payable USD | 1416036.99 | 1416036.99 | 1416036.99 |  | true |
| E BI measure accepted_export_total USD | 1448006.25 | 1448006.25 |  |  | true |
| E BI measure export_difference USD | 0.00 | 0.00 |  |  | true |
| E BI measure received_not_invoiced_value USD (own currency; vs domain) | 135134.34 | 135134.34 |  |  | true |
<!-- END:reconciliation -->

## What the queries do not show
* **One seed, one synthetic world.** The relationships were designed in; finding them shows the queries and the metrics work, not that a business has them.
* **The reconciliation reference is slow and is not a production query.** `data/sql/reference_metrics.sql` takes about 110 seconds for the as-of with its three cutoffs on 2,800 invoices (one recursive chain per cutoff); `00_book.sql` costs the same once. No performance change was attempted.
* **The zero export difference, the approval mix and the rejection mix are by construction or outcome-selected** (see the head of this file); none is evidence about a real desk.
* **The signatures of INJ-03 and INJ-04 are supersets** (30 and 19 invoices contain the 5 and 3 injected); they are written from the facts alone and the manifest is only used to check them.
* **The stored history is the nightly run's.** It differs from the book derived at an arbitrary instant by one exception at the March month-end; every figure here is recomputed from facts except where a block says it reads the history.
* **Policy limits have no currency** and the limit band of query 04 compares a total in its own currency with a number.
* **No dated conversion rate exists**, so no cross-currency total appears anywhere; the all-currency rows carry counts and units only.
* **`needs_review` has no resolving command and C06 returns 501**; the snapshot holds no byte-twin with other fields (0 unresolved groups), so that path is exercised by the tests, not here.
