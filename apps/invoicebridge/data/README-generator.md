# InvoiceBridge synthetic data generator

`data/generate.py` (stdlib only, specification `docs/data-generator.md`) writes the published synthetic snapshot. A master
`random.Random(seed)` hands one child stream to each purpose (vendors, catalog, pos, plans, receipts, invoices, pricing,
duplicates, injections, decisions, exceptions, exports, credits, events). Quantities (1e-4), prices and rates (1e-6) and money
(cents) are integers until written as decimal strings, so no float exists anywhere; dates use `date`/`datetime` arithmetic only;
nothing iterates a set of strings. Same seed gives byte-identical entity files and `dataset_hash` (checked under
`PYTHONHASHSEED` 0, 1, 2). The generator imports nothing from `domain/`: the nightly three-way match, duplicate identity,
amounts and approval policy are restated from `docs/contracts.md` (D-01..D-06); the tests run the domain over the output.

```sh
python data/generate.py --seed 20261026 --out web/public/data     # about 1 s, 3.75 MB (3,745,653 bytes in the 13 entity files + manifests)
python data/generate.py --profile golden-shape-check              # field names vs tests/fixtures/golden and the schema columns
DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/invoicebridge python -m pytest tests/test_generator.py   # also seeds Postgres (about 5 min, the SQL reference is slow on 2,800 invoices)
```

## Output

| File | Content |
|---|---|
| `web/public/data/<entity>.json` | `{"entity","dataset_version","rows"}` for the 10 domain inputs (`vendors`, `purchase_orders`, `po_lines`, `receipts`, `invoices`, `invoice_lines`, `credit_notes`, `approval_policies`, `approvals`, `export_requests`) plus `exceptions`, `exception_assignments`, `export_batches` (columns of `0001_schema.sql`). Field names equal `tests/fixtures/golden/inputs.json`; `approvals` rows also carry `reason` (null for approvals, text for rejections). Quantities `"10.0000"`, prices and rates `"20.000000"`, money `"132.00"`. |
| `manifest.json` | `dataset_version` `ib-20261026-20261026`, `dataset_hash`, `generated_at` (not hashed), `contract_version` "v1", `as_of` `2026-10-01T02:00:00Z`, `snapshot_cutoffs`, `tolerances`, `generator`, `row_counts`, `designed_relationships` (realised numbers), `stats`. |
| `data/injection-manifest.json` (+ copy in `web/public/data/`) | `INJ-01..12` with `test`, `entity`, `location`, `record_ids`, `handling_kind` (merged, accepted_distinct, exception, warned, replay_only), `expected_handling`, `expected_merges`, `expected_exceptions`, `expected_rejections` (none), `detail`. |
| `data/injection-events.json` | `EV-01..07`: replay-only command sequences (`steps`, last step checked; EV-03 sends the last two concurrently) with `expected_status`, `expected_reason`, `expected`. |
| `web/public/data/golden/` | the fixture in the same per-entity shape (`golden-v1`), `expected.json`, `manifest.json`. |

`dataset_hash` = sha256 over the concatenation, in entity-name order, of `json.dumps(rows, sort_keys=True, separators=(",", ":"))`
per entity file (13 files). Source bytes appear as `source_sha256` and a filename only.

## The world

Window 2025-10-01..2026-09-30; every fact is at or before 2026-09-30T23:59:59Z. 40 vendors (25 USD, 10 EUR, 5 GBP; ven-001 is the
golden vendor; ven-040 is a dormant inactive vendor with no POs). 1,200 POs (ordered up to 2026-08-31) with exactly 3,000 lines, each
delivered in 1-4 shipments (a receipt per line and shipment: 5,067 receipt rows, 101 reversed = 2.0 %, 70 of them re-entered a day
later), one invoice per shipment: exactly 2,800 invoices (5,322 lines) = 2,699 shipment invoices + 95 re-sent PDFs + 3 same-bytes
copies + 3 cumulative second invoices. Matching is a nightly run at 02:00Z (365 runs, the last is the dataset `as_of`); exceptions
open at the run that first flags them and resolve at the run where the pair disappears (receipt arrives) or at a rejection;
2,356 approval rows (2,299 approvals, 57 rejections), weekly Friday export batches plus a period-close batch, 117 credit notes on 112 invoices (4.0 %).
Approval policy pol-v1 (reviewer up to 5000.00 from 2025-10-01) and pol-v2 (8000.00 from 2026-04-01).

## Designed relationships (realised numbers in `manifest.designed_relationships`)

* DR-01 ven-020..ven-029 invoice 3-25 days before delivery and 40 % of their lines never get their last delivery fully received:
  QUANTITY_BLOCKED on 163 of 538 invoices (30.3 %) against 30 of 2,107 (1.4 %) elsewhere; every ven-02x vendor is above 25 %, every other below 4 %.
* DR-02 ven-007 bills +7.5 % from 2026-03-01 on POs still carrying old prices (catalogue updated 2026-04-15): 30 of its invoices raise
  PRICE_VARIANCE, the first on the run of 2026-03-04, none before March; 93.8 % of all PRICE_VARIANCE (4 noise invoices elsewhere).
* DR-03 71 of 95 re-sent PDFs (74.7 %) are imported in the last three days of a month against 19 % of all invoices.
* DR-04 limit change: 20 approvals of 5000.00 < total <= 8000.00 after 2026-04-01; 28 matched invoices above the limit stay unapproved.

## Defects: where each lives

| Defect | Entity files | Events | Domain handling |
|---|---|---|---|
| INJ-01 same bytes, two filenames (3) | yes | EV-01 | merged, DUPLICATE_SOURCE_BYTES |
| INJ-02 number reused across vendors (4 pairs) | yes | | both accepted, not merged |
| INJ-03 receipt short of invoiced quantity (5) | yes | | QUANTITY_BLOCKED |
| INJ-04 cumulative consumption (3) | yes | | second invoice QUANTITY_BLOCKED |
| INJ-05 rounding gap over 0.02 (4) | yes | | ROUNDING_EXCEPTION |
| INJ-06 self-approval | no | EV-02 | 403 SELF_APPROVAL |
| INJ-07 racing approvals | no | EV-03 | one 200, one 409 INVALID_STATE |
| INJ-08 credit applied twice | no | EV-04 | 409 CREDIT_ALREADY_APPLIED |
| INJ-09 foreign currency, no rate (3) | yes | | CURRENCY_MISMATCH |
| INJ-10 correction overwriting original | no | EV-05 | 409 DUPLICATE_ID |
| INJ-11 repeated export after timeout (7 repeats) | yes | EV-06 | prior batch returned, counted |
| INJ-12 "paid" flag | no | EV-07 | 422 FIELD_UNEXPECTED |

The clean files produce no ingest rejection at all (`expected_rejections` is empty everywhere); injected exception invoices are never rejected.

## Assumptions where the spec or contract was silent (for D-07)

* The fixture policy shape has no `escalation_role`: reviewers approve up to the limit in force and nobody above it, so larger matched invoices stay unapproved.
* `approvals.reason` is carried on every approvals row (null for approvals).
* `exceptions` / `exception_assignments` / `export_batches` are generator records (ids `exc-NNN` in creation order, integer `assignment_id`); the domain derives its own positional ids unless the stored ones are supplied (the SQL reference reads them). `match_results`, `export_rows`, `import_lineage`, `audit_events` are derived and not written (size).
* `as_of` is the final nightly run 2026-10-01T02:00:00Z; "monthly windows" for the SQL comparison are as-of cutoffs 2026-03-31 and 2026-06-30 (the SQL has no from-parameter).
* A reversed receipt is excluded at every instant (no `reversed_at` in the fixture shape); 70 % are re-entered.
* Rejections are decided only on invoices that were exceptions in every run; credit notes only on approved invoices; one close batch exports everything approved so reconciliation is 0.00.
* The volume cap did not bind: all spec volumes are met exactly at 3.75 MB.

## Domain behaviours noted (unchanged)

* `derive` validates approvals against the run at the cutoff, not at `decided_at`; the generator therefore approves only invoices matched without interruption from their first matched run on.
* `Population.exceptions` ids are last-wins while the SQL prefers the open record; consistent only when the list is ordered as in `tests/test_generator.py::_with_history`.
