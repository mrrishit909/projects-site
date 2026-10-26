# InvoiceBridge data layer

* `python data/migrate.py [--reset]` applies `migrations/*.sql` in order (idempotent; a changed applied file is refused; `--reset` drops only this
  project's tables, functions and the `exception_seq` sequence). `python data/seed.py tests/fixtures/golden/inputs.json [--reference-only]` loads a
  fixture through the domain's `validate_batch` (rejected rows go to `rejected_records` with the raw row), stores the workflow state the domain derives
  at the inputs' `as_of` and records a `dataset_versions` row (`ds-` + the first 12 hex digits of the sha256 of the canonical JSON, or the name given with
  `--dataset-version`: the generator's published `ib-20261026-20261026`, which the replay events carry). Loading twice
  changes nothing. `--reference-only` loads vendors, purchase orders and lines, receipts, policies and tolerances only, so the API commands bring the
  invoices, approvals, credits and exports (this is how `tests/support_db.py::drive` replays a fixture through C01..C09).
* **Schema** (`0001`): `vendors`, `purchase_orders`, `po_lines`, `receipts` (a reversal flips `reversed`), `approval_policies` (with an optional
  `escalation_role`), `tolerances` (one row), `invoices` (extracted fields + stored `subtotal`/`tax`/`total`, workflow `status`, C02 `validity`,
  `merged_into`/`merge_reason`, `version`), `invoice_lines`, `import_lineage` (append-only, one row per import attempt with `source_sha256`),
  `match_results`, `exceptions` (+ `exception_seq`), `exception_assignments` (append-only history), `approvals` (decisions approve|reject),
  `credit_notes`, `export_batches`, `export_rows`, `export_requests` (every request, including repeats that returned the prior batch),
  `rejected_records`, `audit_events`, `command_results` (actor-bound idempotency), `dataset_versions`. Money is `NUMERIC(20,2)`, quantities
  `NUMERIC(20,4)`, unit prices `NUMERIC(20,6)`, rates `NUMERIC(8,6)`; every instant is `TIMESTAMPTZ`.
* **Constraints** (`0002`): positive quantities and credit amounts, three-letter currencies, 64-hex hashes, the status vocabulary (there is no `paid`),
  `merged` iff `merged_into`, a rejection needs a reason, an invoice exports once (`UNIQUE (invoice_id)` on `export_rows`), one open exception per
  (invoice, type). Triggers: the extracted source of an invoice never changes (only workflow columns), `invoice_lines`, `import_lineage`,
  `audit_events`, `exception_assignments`, `approvals`, `export_rows` and `credit_notes` are append-only (UPDATE, DELETE and TRUNCATE refused), a
  receipt may only be reversed.
* **`sql/reference_metrics.sql`** is an independent recomputation of every key of `expected.json["metrics"]` from the FACTS (it never reads a stored
  status, total, match result or merge flag): amounts, duplicate merge (a recursive chain in import order), reject decisions, the three-way match with
  cumulative consumption (a recursive chain per cutoff in `(invoice_date, imported_at, invoice_id)` order), approvals, idempotent export, credits,
  quantities and snapshots. Parameters: `%(as_of)s` (timestamptz, inclusive) and `%(cutoffs)s` (timestamptz[]). It returns one row with a jsonb column
  per metric. `tests/test_sql_reference.py` checks it against the three fixtures, the domain on a rich population and on 120 seeded random
  populations, and that it is unaffected by scrambling the stored state.
* **`0003_review_status.sql`** (D-09): adds the invoice status `needs_review` (a byte-twin whose extracted fields differ is held, not merged).
