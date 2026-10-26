# InvoiceBridge — backend (Mode A: Python domain + PostgreSQL + FastAPI)

Contract v1 (`docs/contracts.md`, D-01..D-05), routes in `docs/api-contract.md`. The domain is standard library only (Decimal and Fraction, **no float
anywhere**); the API adds FastAPI, pydantic and psycopg. Nothing here imports another lab app. The Mode B web mirror (`web/`) is separate.

```
domain/invoicebridge/  contract, errors, timeutil, money, models, amounts, duplicates, ingest, match, book, metrics, pipeline
data/                  migrate.py, seed.py, migrations/0001_schema.sql, 0002_constraints.sql, sql/reference_metrics.sql   (see data/README.md)
api/                   app, db, schemas, commands, reads, errors     (prefix /api/v1/invoicebridge)
tests/                 golden, variants, rules, migrations, SQL reference, API commands and reads, adversarial; reference_check.py (stdlib only)
```

## Run

```
pip install -r requirements.txt
python -I tests/reference_check.py                                   # independent recomputation, ALL OK (412 checks)
DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/invoicebridge python -m pytest -q
python -m pytest -q                                                  # without DATABASE_URL the database tests skip, the pure-domain tests run
DATABASE_URL=... python data/migrate.py [--reset]                    # apply the migrations
DATABASE_URL=... python data/seed.py tests/fixtures/golden/inputs.json
DATABASE_URL=... CODE_SHA=$(git rev-parse HEAD) uvicorn --factory api.app:create_app   # docs at /api/v1/invoicebridge/docs
```

The CI job (`.github/workflows/invoicebridge-ci.yml`, Mode A) runs exactly the first three commands against a `postgres:16` service.

## Domain

* **Facts, not statuses.** `book.derive(population, cutoff)` is a pure function of the recorded facts (invoices and lines, receipts, approvals and
  rejections, export requests, credit notes, exception assignments). It computes duplicates, the three-way match, approvals, exports, credits and the
  statuses. `metrics.compute_metrics` returns exactly the eleven keys of `expected.json["metrics"]`; the `snapshot_cutoffs` it was given travel beside
  them (`PipelineResult.snapshot_cutoffs`, API `data.snapshot_cutoffs`). `run_pipeline(inputs)` returns `PipelineResult(ingest, population, metrics,
  snapshot_cutoffs, book, warnings)` and `.golden()` is the shape of `expected.json` (ingest counts, rejected and merged records, per-invoice
  documents, match results, metrics).
* **Ingest** (`ingest.py`): D-05 codes UNKNOWN_PO_LINE, UNKNOWN_VENDOR, UNKNOWN_PO, NON_POSITIVE_QUANTITY, DEPENDENT_REJECTED. An invoice is atomic: one bad
  line, an unknown vendor or a malformed header rejects the header, every sibling line and any approval or credit note naming it.
* **Money**: ROUND_HALF_UP to 2 dp, tax once per invoice on the unrounded subtotal, total = subtotal + tax + freight - discount; quantities 4 dp, unit
  prices and rates 6 dp, minutes 4 dp and rates computed with exact integer/Fraction arithmetic. Floats, over-precise decimals and NaN are refused.
* **SQL reference**: `data/sql/reference_metrics.sql` recomputes every metric from the facts and equals the domain on any loaded population.

## API

Commands: C01 `import-invoice`, C02 `validate-invoice`, C03 `find-duplicates`, C04 `match-three-way`, C05 `assign-exception`, C07 `approve-invoice`,
C08 `reject-invoice`, C09 `export-payable`, C10 `apply-credit-note`. **C06 `correct-extraction` is routed and answers 501 `NOT_IMPLEMENTED`** (extension).
Reads: `GET /data/{entity}` (vendors, purchase_orders, po_lines, receipts, invoices, invoice_lines, match_results, exceptions,
exception_assignments, approvals, approval_policies, credit_notes, export_batches, export_rows, export_requests, import_lineage, rejected_records,
audit_events, dataset_versions; filters on a whitelist, `from`/`to` half-open, opaque cursor, code-point ordering), `GET /data/invoices/{id}/audit`
(also `/lineage`: the invoice, lines, import lineage, match results, exceptions with assignments, approvals, credits, export rows and audit trail) and
`GET /metrics?from=&to=&cutoff=&group_by=none|vendor|currency`.

* Envelopes: command `{request_id, dataset_version, idempotency_key, input}` -> `{command_id, status, result, warnings, version}`; read
  `{data, meta, warnings}`; error `{error: {code, message, details: [{path, rule_id, message}]}, request_id}`. 401 without `X-Actor-Id`, 403 for a role
  outside clerk|reviewer|admin or not allowed for the command, 422 for validation (with `rule_id`), 409 for state, idempotency and concurrency.
* **Idempotency** is bound to the actor and to a payload hash that includes `dataset_version`: same key + same payload = the stored response
  (`Idempotent-Replay: true`); other payload or other actor = 409 `IDEMPOTENCY_KEY_REUSED`; a `dataset_version` other than the newest `dataset_versions`
  row = 409 `STALE_DATASET_VERSION` (nothing written).
* **Lock order**: the idempotency key (advisory lock; C01 also locks its invoice id and source bytes), then invoice rows by id, then PO line rows by id.
  A deadlock or serialization failure is retried (3 attempts in all), then 409 `CONCURRENT_UPDATE`. Every command writes its effects, its audit row(s)
  and its stored result in one transaction.
* **Separation of duties** (C07): the approver is never `created_by` (403 `SELF_APPROVAL`, refusal audited); the role must be allowed by the policy version
  in force at decision time for the invoice total (403 `ROLE_OR_LIMIT` / `NO_POLICY`). Roles: C01-C05 clerk, reviewer, admin; C07-C10 reviewer, admin.

## Assumptions where the contract was silent (for D-06)

1. **Metrics derive from facts.** Stored `invoices.status` is the workflow state the commands move; every metric, in the domain, the SQL reference and the API
   read, is re-derived from the facts. They agree after the workflow is run in book order; where they differ (an invoice not yet matched, a receipt
   reversed after a match) `GET /metrics` adds a `WORKFLOW_STATE_DIFFERS` warning per invoice. An invoice is in the book only once validated (`validity`).
2. `snapshot_cutoffs` is not a metric key: it is returned beside `metrics` (`data.snapshot_cutoffs`, `PipelineResult.snapshot_cutoffs`).
3. Rejection codes the contract does not list: `MALFORMED_RECORD` (missing or mistyped field, a float, more decimals than allowed, an invoice with no
   lines), `DUPLICATE_ID`, `UNKNOWN_INVOICE` (an orphan line, credit or approval), `NON_POSITIVE_AMOUNT`, `CREDIT_EXCEEDS_INVOICE`.
   Precision: quantities 4 dp, unit prices and rates 6 dp, money 2 dp; every amount below 10^12; `tax_rate` in [0,1]; freight and discount >= 0.
4. Duplicates: the SAME SOURCE BYTES (`source_sha256`) are checked before the identity (vendor, normalised number, invoice date, computed total); the
   merge reason is `DUPLICATE_SOURCE_BYTES` / `DUPLICATE_IDENTITY`; the earliest `(imported_at, invoice_id)` is canonical; a duplicate of a duplicate merges
   into the canonical; the group key of a bytes merge is `sha256:<hex>`. An invoice rejected by decision still anchors the identity.
5. Per-line rounding: an input line may carry `line_amount` (the extracted line amount); |line_amount - round(quantity x unit_price)| above
   `rounding_per_line` is a `ROUNDING_EXCEPTION`, up to it is tolerated and disclosed. Per invoice: |declared_total - computed total| against
   `rounding_per_invoice`. Tolerated differences are listed in `disclosures`.
6. Order of reasons per line: NO_PO_LINE, CURRENCY_MISMATCH (invoice currency against the PO currency, no rate is ever applied), QUANTITY_BLOCKED, then
   PRICE_VARIANCE. A line of the same PO line earlier in the same invoice consumes first; an invoice with any exception consumes nothing.
7. Rejection (C08) is a decision row (`approvals.decision = 'reject'`, reason required). A valid rejection (role allowed by the policy in force, invoice
   validated, no earlier approve decision) removes the invoice from the book and frees its quantity; invalid decisions are listed in
   `approvals.invalid_records` with NOT_REVIEWABLE, ROLE_OR_LIMIT or REJECT_AFTER_APPROVAL. Only the first valid approval of an invoice counts.
8. Policy: the version in force at `decided_at` is the latest `effective_from` (then version, then id); an optional `escalation_role` may approve any
   amount; no policy in force means no approval. The seeded test policy names `admin` as the escalation role.
9. Status vocabulary adds a precedence: adjusted > exported > approved. Obligations are approved, exported and adjusted invoices. Export reconciliation uses
   invoice totals (gross); credits only reduce `approved_payable`. An adjusted invoice may still be exported (at its total).
10. Export: `batch_id` names one set of invoices. A repeated idempotency key replays the stored batch; another key with the same batch id and the same
    invoices returns the prior batch (`status: returned_prior`); another set of invoices is 409 `BATCH_CONFLICT`; an invoice already exported in another
    batch is 409. `exported_at` is excluded from the payload hash (a retry has another clock). Every request that reaches the handler or replays is recorded
    in `export_requests`; a request is a repeat when an earlier request has the same key or the same batch id.
11. Credit note: once per `credit_id` (409 `CREDIT_ALREADY_APPLIED`); amount > 0, 2 dp, cumulative credits <= the invoice total; only approved, exported or
    adjusted invoices; `credited_at` optional (a credit without it counts at every cutoff). No cash movement, nothing is ever marked paid.
12. Exceptions: one per (invoice, type); ids `exc-NNN` from a sequence; C04 resolves exceptions that no longer hold and opens new ones; assignments are
    append-only; `open_count` counts open and assigned exceptions, `unowned_count` those without an owner; the owner is the latest assignment at or before
    the cutoff (backlog reconstruction). A derived exception without a stored row gets the positional id `exc-NNN` of the sorted list.
13. Windows: `[from, to)` is a half-open window of invoice `imported_at`; `to` is also the as-of instant of every other fact (cutoff `to - 1 microsecond`);
    matching always runs over the whole book so consumption is right; snapshot cutoffs are inclusive. `group_by` is vendor or currency.
14. Processing minutes are exact (Fraction) from `imported_at` to the first valid approval, rounded half up once at the end; rates are exact fractions.
15. API: C01 rejection is 422 with the rule ids, and the raw rows and a lineage row are kept (own transaction); same bytes under another invoice id are
    stored as a `merged` invoice (200, `duplicate_of`); the same invoice id and bytes again is a 200 `duplicate`; same id with other bytes is 409
    `DUPLICATE_ID`. C02 returns 200 with status `valid` or `invalid` and the failed rules (VENDOR_INACTIVE, NO_LINES, NEGATIVE_TOTAL,
    INVOICE_DATE_IN_FUTURE). C03 merges every non-canonical member of the group (refusing an approved or exported copy with 409) and may be run on an
    already merged invoice. C04 may be re-run from valid, matched or exception. C07 re-checks the match (409 `STALE_MATCH` when a receipt was reversed).
16. Error codes: 403 `SELF_APPROVAL` carries its own top-level code, other 403s are `FORBIDDEN` with the `rule_id` in `details`; refused approvals are
    audited as `approve-invoice-refused` in their own transaction.
17. Receipts, vendors, purchase orders and policies are reference data loaded by `data/seed.py`; there is no command for them. A receipt is reversed by
    `UPDATE receipts SET reversed = TRUE` (the only update the database allows). Reads need no actor.
18. Rule version of every match result is `"1"`; `CODE_SHA` is echoed in `meta.code_sha`.

## Not implemented

C06 `correct-extraction` (extension, 501); OCR; currency conversion (a foreign-currency line is always CURRENCY_MISMATCH).
