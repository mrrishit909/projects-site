# Data dictionary: InvoiceBridge relational model (P05-ART-03)

All data in this model is **synthetic**: the golden fixture (`tests/fixtures/golden/inputs.json`) and the generated snapshot `ib-20261026-20261026` (seed 20261026, generator `dataset_hash` `1f001a43a7031d4260f5abb3b9f7a83f6e1b48397e85cf8b04e0b4d9e052162e`, contract v1, code revision `2dcc460`). The vendors, purchase orders, invoices and people do not exist; the vendor names and the `usr-*` actor ids are generated. Sources: `data/migrations/0001_schema.sql`, `0002_constraints.sql` and `0003_review_status.sql`, `data/migrate.py`, `data/seed.py`, `data/generate.py` and the entity files under `web/public/data/`.

**How to read this without installing anything:** section 1 is one row per table (grain, key, rows, update semantics, deletion), section 2 one table per table with every column, section 3 the foreign keys, section 4 the constraints and triggers, section 5 the source-to-target mapping, section 6 the known gaps. `erd.md` draws the same model.

Row counts are `SELECT count(*)` on scratch PostgreSQL 16 databases prepared by `data/sql/analysis/prepare_snapshot.py` (migrate, then `seed.py` through the domain's `validate_batch` over `web/public/data`, then the published exception history). The snapshot database holds all 2,800 published invoices (2,702 accepted and 98 merged on import), 5,322 lines, 2,356 approval decisions and **no rejected rows** (`rejected_records` is empty: every generated row is well formed; the defects the contract refuses are exercised by the tests and the replay events, not by the snapshot). The golden database holds the three invoices of the known answer.

Conventions: all instants are `TIMESTAMPTZ` read as UTC (D-01, D-05); money is `NUMERIC(20,2)`, quantities `NUMERIC(20,4)`, unit prices `NUMERIC(20,6)`, rates `NUMERIC(8,6)`, and nothing is ever a float (D-02); ids are `TEXT` keys supplied by the source; absence is NULL (never an empty string, 0 or NaN). "FK" means a foreign key enforced in `0001`; "logical" means a join the contract relies on that the database does not enforce. Constraint and trigger names are those of `0002_constraints.sql`. **Money is per currency:** every amount is in the currency of its own row (`vendors.currency`, `invoices.currency`, `purchase_orders.currency`) and the model has no dated conversion rate, so no column or query adds one currency to another. Observed, simulated and hypothetical results are kept apart: this file describes structure and observed row counts only; the model holds no simulated outcome.

## 1. Tables, grain, keys and update semantics

| Table | Kind | Grain | Primary key | Rows (snapshot DB) | Rows (golden DB) | Update semantics |
|---|---|---|---|---|---|---|
| `vendors` | source | one vendor (synthetic) | `vendor_id` | 40 | 1 | Insert-only through the seed. `currency` is the vendor's billing currency (25 USD, 10 EUR, 5 GBP); `active` retires a vendor without deleting it (ven-040 is dormant: no invoice). |
| `purchase_orders` | source | one purchase order | `po_id` | 1,200 | 1 | Insert-only. `status` is `open` (221) or `closed` (979); the vendor and currency of an order never change. |
| `po_lines` | source | one ordered line of a purchase order | `po_line_id` | 3,000 | 1 | Insert-only. `quantity` and `unit_price` are the order, not a running balance: what remains is derived (`net received - accepted invoiced`). |
| `receipts` | source | one goods receipt against a PO line | `receipt_id` | 5,067 | 1 | **Reversal only**: trigger `receipts_reverse_only` refuses any change except flipping `reversed` to TRUE (and never back) and refuses DELETE. 101 are reversed (2.0 % of first-entry receipts) and 70 of those were re-entered a day later as a new receipt. `reversed_at` is NULL on every row: the fixture shape carries no `reversed_at`, so a reversed receipt is excluded at every instant (D-07). |
| `approval_policies` | source | one approval policy version | `policy_id` | 2 | 1 | Insert-only. `pol-v1` (limit 5000.00) from 2025-10-01 and `pol-v2` (8000.00) from 2026-04-01; neither carries an `escalation_role`. The policy in force at an instant is the latest `effective_from` not after it. |
| `tolerances` | source | the tolerances the dataset travels with | `id` (always 1) | 1 | 1 | One row, upserted by the seed: price per unit 0.000000, rounding per line 0.010000, rounding per invoice 0.020000 (`tolerances_ck`). |
| `invoices` | source + workflow | one imported invoice document (a merged duplicate keeps its row) | `invoice_id` | 2,800 | 3 | **The extracted source is immutable**: trigger `invoices_source_fixed` refuses DELETE and any UPDATE that changes an extracted field, the amounts or the lineage columns; only the workflow columns (`status`, `validity`, `validation_rules`, `merged_into`, `merge_reason`, `version`, `updated_at`) move. The stored `status` is the workflow state the commands move and may lag the derived view: the metrics never read it (D-06). Snapshot status at load: exported 2,187, exception 232, matched 114, adjusted 112, merged 98, rejected 57. |
| `invoice_lines` | source | one line of one invoice | `invoice_line_id` | 5,322 | 3 | **Append-only** (trigger `invoice_lines_immutable`). `po_line_id` is deliberately not a foreign key: a line naming no PO line is the `NO_PO_LINE` exception, not a load error. 180 lines belong to the 98 merged invoices. `line_amount` (the extracted line amount) is NULL on every snapshot row. |
| `import_lineage` | operational | one import attempt that reached the book, with the sha256 of its source bytes | `lineage_id` (BIGSERIAL) | 2,800 | 3 | **Append-only** (`import_lineage_immutable`, `import_lineage_no_truncate`): the evidence that a document arrived, whatever happened to it afterwards. 2,702 `accepted`, 95 `merged` with reason `DUPLICATE_IDENTITY` and 3 `merged` with `DUPLICATE_SOURCE_BYTES`; a byte-twin held for review carries reason `BYTES_FIELDS_CONFLICT` (none in the snapshot). |
| `match_results` | derived | one line of one invoice with its three-way match outcome at the load as-of | `invoice_line_id` | 5,022 | 2 | Written by the seed (and by C04) from the domain's derivation; carries `rule_version` `1`. It is a stored copy at one instant: the book at any other cutoff is recomputed from facts. 4,719 matched, 247 `QUANTITY_BLOCKED`, 51 `PRICE_VARIANCE`, 5 `CURRENCY_MISMATCH` lines (the book at the as-of: 2,645 invoices). |
| `exceptions` | derived + history | one exception of one type on one invoice | `exception_id` | 660 | 1 | One OPEN exception per (invoice, type) (partial unique index `exceptions_open_uq`); a resolved one stays as history. The seed writes the 232 derived open ones; `prepare_snapshot.py` replaces them with the published history (660 rows, 428 resolved). `owner_id` is a convenience copy: the owner is the latest `exception_assignments` row (D-06). |
| `exception_assignments` | operational | one assignment of an exception to an owner | `assignment_id` (BIGSERIAL) | 698 | 0 | **Append-only** history (`exception_assignments_immutable`): re-assigning adds a row, never edits one. The backlog as of a cutoff is reconstructed from it (query 05). The seed does not load it; `prepare_snapshot.py` inserts the published rows. |
| `approvals` | source | one approve or reject decision by one actor on one invoice | `approval_id` | 2,356 | 1 | **Append-only** (`approvals_immutable`). 2,299 approve and 57 reject (a reject carries a reason: `approvals_decision_ck`). `policy_id` and `policy_version` record the policy in force at `decided_at`. Only the first policy-valid approval counts; an invalid decision stays listed with its refusal code in the metrics. |
| `credit_notes` | source | one credit note against one invoice | `credit_id` | 117 | 0 | **Append-only** (`credit_notes_immutable`); the key makes a credit apply once. 112 invoices carry one or two (107 and 5). `reason` and `created_by` are NULL on every snapshot row. No cash movement is recorded anywhere. |
| `export_batches` | derived | one named export batch | `batch_id` | 52 | 1 | Written by the seed from the non-repeat requests (`requested_by` is `seed`) and by C09; replayed by key, 409 `BATCH_CONFLICT` for another set. `row_count` and `total` are the batch's own counts (a batch may mix currencies, so `total` is a count-of-money across currencies and is not a metric; the per-currency totals are derived from `export_rows`). |
| `export_rows` | derived | one invoice exported in one batch | `export_id` (`exp-<batch>-<invoice>`) | 2,299 | 1 | **Append-only** (`export_rows_immutable`); `UNIQUE (invoice_id)` makes an invoice export once. `content_hash` is the sha256 of `invoice_id|vendor_id|invoice_number|invoice_date|currency|amount`; `exported_at` is excluded from the payload hash so a retry hashes the same. |
| `export_requests` | operational | one export request that reached the handler, repeats included | `request_seq` (BIGSERIAL) | 59 | 2 | Insert-only. `outcome` is `created` (52) or `returned_prior` (7: a retry after a timeout with the same batch id and key). It is what the SQL reference reads, not `export_batches`. |
| `rejected_records` | operational | one raw row refused at ingest, with its reason | `(batch_id, entity, id, reason_code, ordinal)` | 0 | 0 | Insert-only. `raw_row` keeps the row as it arrived; `ordinal` separates two refused occurrences of one id. Empty on the snapshot (query 08). |
| `audit_events` | operational | one audit line per accepted command | `event_id` | 0 | 0 | **Append-only** (`audit_events_immutable`). Written in the SAME transaction as the command it records, refusals included (a self-approval is a 403 and an audit row). Empty in a seeded database; filled by the API. |
| `command_results` | operational | one stored result per idempotency key | `idempotency_key` | 0 | 0 | Insert-only. The same key, payload, actor, role and dataset version replays the stored result; another payload, actor or role is 409 `IDEMPOTENCY_KEY_REUSED` (D-06, D-09.13). Empty in a seeded database. |
| `dataset_versions` | operational | one seeded dataset | `dataset_version` | 1 | 1 | Insert-only. The snapshot database names the generator's published version `ib-20261026-20261026`, which the replay events carry (D-09, `seed(..., dataset_version=)`); the golden database names `ds-` + 12 hex of the hash of its inputs. `dataset_hash` here is the hash of the seed's INPUT JSON, not the generator's file hash (section 6). |
| `schema_migrations` | operational | one applied migration (created by `data/migrate.py`, not by the SQL files) | `version` | 3 | 3 | Holds the sha256 of each applied file; a migration that changed after it was applied is refused. |

**Deletion policy.** Nothing in the application deletes a row: no command issues a `DELETE`, `invoices` refuse DELETE by trigger, `receipts` refuse DELETE (they are reversed), `invoice_lines`, `import_lineage`, `audit_events`, `exception_assignments`, `approvals`, `export_rows` and `credit_notes` refuse UPDATE, DELETE and TRUNCATE by trigger, and every foreign key is the PostgreSQL default (`NO ACTION`), so a parent row cannot be deleted while a child references it. Retirement is a flag (`vendors.active`, `purchase_orders.status`), a correction is a versioned row (C06 `correct-extraction` is routed and answers 501 in this milestone, so no correction version exists yet), and a rejection is a decision row. The only DELETE in the whole package is `prepare_snapshot.py` replacing the seed's derived `exceptions` with the published history inside a scratch database named `artifacts05_*`, and `migrate.py --reset`.

**Append-only lineage.** `import_lineage` keeps every import attempt with its source hash, so the same bytes under another file name (a re-sent PDF) can be traced to the first import, and the extracted source in `invoices` can never be overwritten (`invoices_source_fixed`). A merged duplicate keeps its own lineage row and its `source_sha256`; it consumes no received quantity and is not an obligation.

## 2. Columns

Type is the PostgreSQL type of `0001_schema.sql`; Null is whether the column accepts NULL; Source is the entity-file field the seed loads it from (`web/public/data/<entity>.json`, same field names as `tests/fixtures/golden/inputs.json`) or how it is produced.

### vendors
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `vendor_id` | TEXT | no | Key (`ven-001` .. `ven-040`); `ven-020` .. `ven-029` is the designed group "ven-02x" and `ven-007` the price-list vendor | vendors.vendor_id |
| `vendor_name` | TEXT | no | Generated display name | vendors.vendor_name |
| `tax_reference` | TEXT | no | Generated tax id | vendors.tax_reference |
| `currency` | CHAR(3) | no | ISO-style code (`vendors_currency_ck`): USD, EUR or GBP | vendors.currency |
| `active` | BOOLEAN | no | FALSE for the dormant vendor (an invoice from it fails C02 `VENDOR_INACTIVE`) | vendors.active |

### purchase_orders
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `po_id` | TEXT | no | Key | purchase_orders.po_id |
| `vendor_id` | TEXT | no | FK to `vendors` | purchase_orders.vendor_id |
| `ordered_at` | TIMESTAMPTZ | no | A PO line exists at a cutoff only when its order was placed by then | purchase_orders.ordered_at |
| `status` | TEXT | no | `open` or `closed` (informational; the match reads receipts and invoices, not this) | purchase_orders.status |
| `currency` | CHAR(3) | no | The order's currency (`po_currency_ck`); an invoice in another currency is `CURRENCY_MISMATCH`, never converted (D-02) | purchase_orders.currency |

### po_lines
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `po_line_id` | TEXT | no | Key | po_lines.po_line_id |
| `po_id` | TEXT | no | FK to `purchase_orders` | po_lines.po_id |
| `product_code` | TEXT | no | Generated product code | po_lines.product_code |
| `quantity` | NUMERIC(20,4) | no | Ordered quantity, positive (`po_lines_qty_ck`) | po_lines.quantity |
| `unit_price` | NUMERIC(20,6) | no | Order price per unit in the PO's currency, not negative | po_lines.unit_price |

### receipts
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `receipt_id` | TEXT | no | Key | receipts.receipt_id |
| `po_line_id` | TEXT | no | FK to `po_lines` | receipts.po_line_id |
| `received_quantity` | NUMERIC(20,4) | no | Positive (`receipts_qty_ck`) | receipts.received_quantity |
| `received_at` | TIMESTAMPTZ | no | Counts toward net received from this instant | receipts.received_at |
| `reversed` | BOOLEAN | no | Default FALSE; TRUE excludes the receipt from net received at every instant | receipts.reversed |
| `reversed_at` | TIMESTAMPTZ | yes | NULL on every snapshot row (not in the fixture shape) | not loaded |

### approval_policies
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `policy_id` | TEXT | no | Key (`pol-v1`, `pol-v2`) | approval_policies.policy_id |
| `version_number` | INT | no | At least 1 (`policies_ck`) | approval_policies.version_number |
| `amount_limit` | NUMERIC(20,2) | no | The reviewer role may approve totals up to this, in the invoice's own currency | approval_policies.amount_limit |
| `reviewer_role` | TEXT | no | Role allowed up to the limit | approval_policies.reviewer_role |
| `escalation_role` | TEXT | yes | Role allowed at any amount; NULL in the snapshot, so a matched invoice above the limit stays unapproved | approval_policies.escalation_role |
| `effective_from` | TIMESTAMPTZ | no | The version applies to decisions from this instant | approval_policies.effective_from |

### tolerances
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `id` | INT | no | Always 1 | seed |
| `price_per_unit` | NUMERIC(20,6) | no | Allowed absolute unit-price difference (0.000000) | manifest tolerances |
| `rounding_per_line` | NUMERIC(20,6) | no | Tolerated line rounding (0.010000) | manifest tolerances |
| `rounding_per_invoice` | NUMERIC(20,6) | no | Tolerated declared-versus-computed total difference (0.020000); beyond it `ROUNDING_EXCEPTION` | manifest tolerances |

### invoices
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `invoice_id` | TEXT | no | Key | invoices.invoice_id |
| `vendor_id` | TEXT | no | FK to `vendors` | invoices.vendor_id |
| `invoice_number` | TEXT | no | As extracted | invoices.invoice_number |
| `invoice_number_norm` | TEXT | no | Upper-case letters and digits only (D-05); part of the identity | derived by seed |
| `invoice_date` | DATE | no | The invoice's own date; part of the identity | invoices.invoice_date |
| `currency` | CHAR(3) | no | Invoice currency (`invoices_currency_ck`) | invoices.currency |
| `tax_rate` | NUMERIC(8,6) | no | 0 to 1 (`invoices_rate_ck`); tax is computed once per invoice | invoices.tax_rate |
| `freight` | NUMERIC(20,2) | no | Not negative | invoices.freight |
| `invoice_discount` | NUMERIC(20,2) | no | Not negative | invoices.invoice_discount |
| `declared_total` | NUMERIC(20,2) | no | What the document states; compared with the computed total (tolerance 0.02) | invoices.declared_total |
| `subtotal`, `tax`, `total` | NUMERIC(20,2) | no | Stored at import for reads (round-half-up); the SQL reference recomputes them from the lines | derived by seed |
| `created_by` | TEXT | no | The importing actor; the approver must differ (separation of duties) | invoices.created_by |
| `source_sha256` | CHAR(64) | no | sha256 of the source bytes, 64 lower-case hex (`invoices_sha_ck`); the same bytes are ONE obligation | invoices.source_sha256 |
| `source_filename` | TEXT | no | As received (never part of identity) | invoices.source_filename |
| `idempotency_key` | TEXT | no | The import's key | invoices.idempotency_key |
| `imported_at` | TIMESTAMPTZ | no | The import instant; windows are half-open on it | invoices.imported_at |
| `status` | TEXT | no | Workflow state, default `received`; one of received, valid, invalid, matched, exception, approved, rejected, exported, adjusted, merged, needs_review (`invoices_status_ck`, extended by `0003`); there is no `paid` | derived by seed |
| `validity` | BOOLEAN | yes | The C02 verdict; NULL means not validated yet (outside the book) | derived by seed |
| `validation_rules` | JSONB | no | Rule ids that failed C02 (empty array on every snapshot row) | derived by seed |
| `merged_into` | TEXT | yes | The canonical invoice; set iff `status = 'merged'` (`invoices_merge_ck`) | derived by seed |
| `merge_reason` | TEXT | yes | `DUPLICATE_IDENTITY` or `DUPLICATE_SOURCE_BYTES` | derived by seed |
| `version` | INT | no | Optimistic-concurrency version, default 1; two approvals racing: exactly one wins | default |
| `updated_at` | TIMESTAMPTZ | no | Default now() | default |

### invoice_lines
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `invoice_line_id` | TEXT | no | Key | invoice_lines.invoice_line_id |
| `invoice_id` | TEXT | no | FK to `invoices` | invoice_lines.invoice_id |
| `po_line_id` | TEXT | no | Logical join to `po_lines` (not an FK, see section 1) | invoice_lines.po_line_id |
| `quantity` | NUMERIC(20,4) | no | Positive (`invoice_lines_qty_ck`) | invoice_lines.quantity |
| `unit_price` | NUMERIC(20,6) | no | Not negative | invoice_lines.unit_price |
| `line_amount` | NUMERIC(20,2) | yes | The extracted line amount when the source states one (per-line rounding check); NULL on the snapshot | invoice_lines.line_amount |

### import_lineage
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `lineage_id` | BIGSERIAL | no | Key | default |
| `invoice_id` | TEXT | no | Logical join to `invoices` | derived by seed |
| `source_sha256` | CHAR(64) | no | Hash of the bytes imported (`lineage_sha_ck`) | invoices.source_sha256 |
| `source_filename` | TEXT | no | File name as received | invoices.source_filename |
| `idempotency_key` | TEXT | no | The import's key | invoices.idempotency_key |
| `imported_at` | TIMESTAMPTZ | no | The import instant | invoices.imported_at |
| `actor_id` | TEXT | no | Who imported | invoices.created_by |
| `import_status` | TEXT | no | `accepted`, `rejected` or `merged` (`lineage_status_ck`) | derived |
| `reason_code` | TEXT | yes | The merge reason or `BYTES_FIELDS_CONFLICT` | derived |
| `merged_into` | TEXT | yes | The canonical invoice | derived |
| `recorded_at` | TIMESTAMPTZ | no | Default now() | default |

### match_results
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `invoice_line_id` | TEXT | no | Key and FK to `invoice_lines` | derived |
| `invoice_id` | TEXT | no | FK to `invoices` | derived |
| `rule_version` | TEXT | no | `1` | contract |
| `status` | TEXT | no | `matched` or `exception` (`match_status_ck`) | derived |
| `reason_code` | TEXT | yes | NULL iff matched; otherwise QUANTITY_BLOCKED, PRICE_VARIANCE, NO_PO_LINE or CURRENCY_MISMATCH (`match_reason_ck`; ROUNDING_EXCEPTION is an invoice-level reason, not a line one) | derived |
| `available_quantity` | NUMERIC(20,4) | yes | Net received minus consumed minus earlier lines of the same invoice on the same PO line | derived |
| `quantity_variance` | NUMERIC(20,4) | yes | Invoiced minus available; above 0 blocks | derived |
| `price_variance` | NUMERIC(20,4) | yes | Invoiced unit price minus PO price | derived |
| `explanation` | TEXT | no | Human-readable reason | derived |
| `matched_at` | TIMESTAMPTZ | no | Default now() | default |

### exceptions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `exception_id` | TEXT | no | Key (`exc-001` ..) | exceptions.exception_id |
| `invoice_id` | TEXT | no | FK to `invoices` | exceptions.invoice_id |
| `exception_type` | TEXT | no | QUANTITY_BLOCKED, PRICE_VARIANCE, NO_PO_LINE, ROUNDING_EXCEPTION or CURRENCY_MISMATCH (`exceptions_type_ck`) | exceptions.exception_type |
| `status` | TEXT | no | `open` (no owner), `assigned` or `resolved` (`exceptions_status_ck`) | exceptions.status |
| `owner_id` | TEXT | yes | Convenience copy of the latest assignment | exceptions.owner_id |
| `created_at` | TIMESTAMPTZ | no | The nightly run (02:00 UTC) that raised it | exceptions.created_at |
| `resolved_at` | TIMESTAMPTZ | yes | The run that found it resolved; also set when a reject decision removes the invoice | exceptions.resolved_at |

### exception_assignments
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `assignment_id` | BIGSERIAL | no | Key (the published id is kept) | exception_assignments.assignment_id |
| `exception_id` | TEXT | no | FK to `exceptions` | exception_assignments.exception_id |
| `owner_id` | TEXT | no | The owner from this instant | exception_assignments.owner_id |
| `assigned_by` | TEXT | no | Who assigned | exception_assignments.assigned_by |
| `assigned_at` | TIMESTAMPTZ | no | The owner is the latest row at or before the cutoff | exception_assignments.assigned_at |
| `note` | TEXT | yes | Free text (`triage` or NULL in the snapshot) | exception_assignments.note |

### approvals
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `approval_id` | TEXT | no | Key | approvals.approval_id |
| `invoice_id` | TEXT | no | FK to `invoices` | approvals.invoice_id |
| `actor_id` | TEXT | no | The decider; must differ from `invoices.created_by` for an approval and a rejection (`SELF_APPROVAL`, `SELF_DECISION`) | approvals.actor_id |
| `actor_role` | TEXT | no | clerk, reviewer or admin; `reviewer` in the snapshot | approvals.actor_role |
| `decision` | TEXT | no | `approve` or `reject`; a reject needs a non-empty reason (`approvals_decision_ck`) | approvals.decision |
| `decided_at` | TIMESTAMPTZ | no | Server-stamped by the API (a client-supplied `decided_at` is 422 `FIELD_UNEXPECTED`, D-09.7) | approvals.decided_at |
| `reason` | TEXT | yes | Required for a reject (two wordings in the snapshot) | approvals.reason |
| `policy_id` | TEXT | yes | The policy in force at `decided_at` | derived by seed |
| `policy_version` | INT | yes | Its version | derived by seed |

### credit_notes
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `credit_id` | TEXT | no | Key; a credit applies once (409 `CREDIT_ALREADY_APPLIED`) | credit_notes.credit_id |
| `invoice_id` | TEXT | no | FK to `invoices` | credit_notes.invoice_id |
| `credit_amount` | NUMERIC(20,2) | no | Positive (`credits_amount_ck`), in the invoice's currency; cumulative credits never exceed the invoice total | credit_notes.credit_amount |
| `credited_at` | TIMESTAMPTZ | yes | A credit counts from this instant (NULL counts always) | credit_notes.credited_at |
| `reason` | TEXT | yes | NULL in the snapshot | not loaded |
| `created_by` | TEXT | yes | NULL in the snapshot | not loaded |

### export_batches, export_rows, export_requests
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `export_batches.batch_id` | TEXT | no | Key | export_requests.batch_id |
| `export_batches.idempotency_key` | TEXT | no | The request's key | export_requests.idempotency_key |
| `export_batches.requested_by` | TEXT | no | `seed` for a seeded batch; the actor for C09 | seed |
| `export_batches.exported_at` | TIMESTAMPTZ | no | The first request's instant | export_requests.exported_at |
| `export_batches.row_count`, `total` | INT, NUMERIC(20,2) | no | The batch's own count and sum of row amounts (a count of money across currencies when a batch mixes them; not a metric) | derived |
| `export_batches.created_at` | TIMESTAMPTZ | no | Default now() | default |
| `export_rows.export_id` | TEXT | no | Key `exp-<batch>-<invoice>` | derived |
| `export_rows.batch_id` | TEXT | no | FK to `export_batches` | derived |
| `export_rows.invoice_id` | TEXT | no | FK to `invoices`; unique (`export_rows_inv_uq`) so an invoice exports once | derived |
| `export_rows.exported_at` | TIMESTAMPTZ | no | The request's instant | derived |
| `export_rows.vendor_id`, `invoice_number`, `invoice_date` | TEXT, TEXT, DATE | no | Copied at export (the number as imported) | derived |
| `export_rows.currency` | CHAR(3) | no | The invoice's currency | derived |
| `export_rows.amount` | NUMERIC(20,2) | no | The invoice's computed total in its currency | derived |
| `export_rows.content_hash` | CHAR(64) | no | 64 lower-case hex (`export_rows_hash_ck`) | derived |
| `export_requests.request_seq` | BIGSERIAL | no | Key; order of arrival decides which request is the repeat | default |
| `export_requests.batch_id`, `idempotency_key` | TEXT | no | A request whose key or batch id was seen before is a repeat | export_requests |
| `export_requests.invoice_ids` | TEXT[] | no | The invoices named | export_requests.invoice_ids |
| `export_requests.exported_at` | TIMESTAMPTZ | no | The request's instant | export_requests.exported_at |
| `export_requests.outcome` | TEXT | no | `created` or `returned_prior` (`export_requests_ck`) | derived |
| `export_requests.requested_by`, `recorded_at` | TEXT, TIMESTAMPTZ | no | `seed`; default now() | seed |

### rejected_records, audit_events, command_results, dataset_versions, schema_migrations
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `rejected_records.batch_id`, `entity`, `id`, `reason_code`, `ordinal` | TEXT x4, INT | no | The key; the reason is one of UNKNOWN_PO_LINE, UNKNOWN_VENDOR, UNKNOWN_PO, NON_POSITIVE_QUANTITY, DEPENDENT_REJECTED, MALFORMED_RECORD, DUPLICATE_ID, UNKNOWN_INVOICE, NON_POSITIVE_AMOUNT, CREDIT_EXCEEDS_INVOICE (D-05, D-06) | domain ingest |
| `rejected_records.raw_row`, `recorded_at` | JSONB, TIMESTAMPTZ | no | The row as it arrived; default now() | ingest |
| `audit_events.event_id`, `entity_type`, `entity_id`, `invoice_id`, `action`, `actor_id` | TEXT | no (`invoice_id` yes) | One line per command and refusal | API |
| `audit_events.occurred_at`, `before_version`, `after_version`, `reason`, `request_id`, `details` | TIMESTAMPTZ, INT, INT, TEXT, TEXT, JSONB | mixed | Version before and after, the reason and the details of the effect | API |
| `command_results.idempotency_key`, `payload_hash`, `actor_id`, `command_id`, `status`, `result`, `created_at` | TEXT x5, JSONB, TIMESTAMPTZ | no | The stored response replayed for the same key, payload, actor, role and dataset version | API |
| `dataset_versions.dataset_version`, `dataset_hash`, `contract_version`, `created_at` | TEXT x3, TIMESTAMPTZ | no | The version a command must carry (409 `STALE_DATASET_VERSION` otherwise) | seed |
| `schema_migrations.version`, `checksum`, `applied_at` | TEXT, TEXT, TIMESTAMPTZ | no | The migration file name, its sha256, when applied | migrate.py |

## 3. Foreign keys

Enforced in `0001` (default `NO ACTION`): `purchase_orders.vendor_id` to `vendors`; `po_lines.po_id` to `purchase_orders`; `receipts.po_line_id` to `po_lines`; `invoices.vendor_id` to `vendors`; `invoice_lines.invoice_id` to `invoices`; `match_results.invoice_line_id` to `invoice_lines` and `.invoice_id` to `invoices`; `exceptions.invoice_id` to `invoices`; `exception_assignments.exception_id` to `exceptions`; `approvals.invoice_id` to `invoices`; `credit_notes.invoice_id` to `invoices`; `export_rows.batch_id` to `export_batches` and `.invoice_id` to `invoices`.
Logical joins the contract relies on and the database does not enforce: `invoice_lines.po_line_id` to `po_lines` (so a missing line is `NO_PO_LINE`, not a load error); `import_lineage.invoice_id` to `invoices`; `import_lineage.merged_into` and `invoices.merged_into` to `invoices`; `approvals.policy_id` to `approval_policies`; `export_requests.invoice_ids[]` to `invoices`; `audit_events.invoice_id` to `invoices`.

## 4. Constraints and triggers (`0002`, `0003`)

* **Checks:** currencies match `^[A-Z]{3}$`; quantities and credit amounts are positive; unit prices, freight and discount are not negative; `tax_rate` between 0 and 1; hashes are 64 lower-case hex; the invoice status vocabulary (`0003` adds `needs_review`); `(status = 'merged') = (merged_into IS NOT NULL)`; one match status and reason vocabulary; one exception status vocabulary with `open` iff no owner; a reject needs a reason; the tolerances row is `id = 1` and not negative.
* **Uniqueness:** `export_rows (invoice_id)` (an invoice exports once) and `(invoice_id, batch_id)`; a partial unique index `exceptions_open_uq (invoice_id, exception_type) WHERE status <> 'resolved'` (one open exception per invoice and type); every primary key above.
* **Triggers:** `invoices_source_fixed` (the extracted source never changes, no DELETE); `receipts_reverse_only`; and `<table>_immutable` plus `<table>_no_truncate` for `import_lineage`, `audit_events`, `exception_assignments`, `approvals`, `export_rows`, `credit_notes` and `invoice_lines` (UPDATE, DELETE and TRUNCATE refused with `integrity_constraint_violation`).
* **Not enforced by the database (application rules):** separation of duties, the policy limit, cumulative consumption of received quantity and idempotency are decided by the domain under row locks (C07, C04, C01); the database cannot see them.

## 5. Source-to-target mapping

| Source (`web/public/data/` or fixture) | Target | How |
|---|---|---|
| `vendors`, `purchase_orders`, `po_lines`, `receipts`, `approval_policies` | same-named tables | `seed.py` `insert_reference`, `ON CONFLICT DO NOTHING`; `receipts.reversed_at` stays NULL |
| manifest `tolerances` | `tolerances` | one row, upserted |
| `invoices`, `invoice_lines` | `invoices`, `invoice_lines`, `import_lineage` | through `validate_batch`; `invoice_number_norm`, `subtotal`, `tax`, `total`, `status`, `validity`, `validation_rules`, `merged_into`, `merge_reason` are the domain's derivation at the as-of; one lineage row per invoice (merged ones with their reason) |
| `approvals` | `approvals` | plus the policy in force at `decided_at` |
| `credit_notes` | `credit_notes` | `reason` and `created_by` stay NULL |
| `export_requests` | `export_requests`, `export_batches`, `export_rows` | requests as received with the derived outcome; one batch and its rows per non-repeat request; the published `export_batches.json` (with `requested_by` and `total`) is a cross-check, not a load source |
| the domain's match run | `match_results` | rows for the 2,645 invoices of the book at the as-of; **a stored copy at one instant** |
| the domain's exception derivation | `exceptions` (232 open) | replaced by the published `exceptions.json` (660 rows) and `exception_assignments.json` (698 rows) in `prepare_snapshot.py` |
| ingest rejections | `rejected_records` | none on the snapshot |
| the generator's `manifest.json` | `dataset_versions` | the version `ib-20261026-20261026`; the stored hash is the hash of the seed's input JSON |

The published files and their generator hash (`1f001a43...2162e`) are the source of truth for the dataset; the database is a derived, rebuildable copy. Money in every row is in its own currency (`vendors.currency` 25 USD, 10 EUR, 5 GBP vendors).

## 6. Known gaps and disclosures

* **Two hashes.** The generator's `dataset_hash` (`1f001a43...2162e`, over the entity files) is not the `dataset_versions.dataset_hash` the seed writes (the sha256 of the canonical JSON of the seed's inputs, `cc36983e...e51` for the snapshot). Both are deterministic; neither is a secret.
* **Stored state is a copy.** `invoices.status`, `match_results` and `exceptions` for the open set are the workflow state at one instant and may lag the facts (`WORKFLOW_STATE_DIFFERS`); every metric and every figure in the artifact package is recomputed from facts (`data/sql/reference_metrics.sql`, `data/sql/analysis/00_book.sql`), never from them.
* **The exception history is the nightly run's.** It can differ from the book recomputed for an arbitrary instant: at the March month-end the stored history has 128 open exceptions and the facts-derived book 129 (an invoice imported between the last 02:00 run and the cutoff); at the June month-end and the as-of both agree (201 and 232) (`sql-analysis.md` query 05).
* **`export_batches.total` mixes currencies** when a batch names invoices of several currencies; it is a stored count of money across currencies and is not used by any figure; the per-currency export totals come from `export_rows`.
* **No correction versions, no receipt command.** C06 `correct-extraction` answers 501; receipts are reference data and a reversal is the one UPDATE the schema allows. A `needs_review` invoice has no command that resolves it.
* **Policy limits have no currency.** `approval_policies.amount_limit` is compared with the invoice total in the invoice's own currency (no conversion rate exists).
* **`line_amount`, `reason` (credits), `created_by` (credits) and `reversed_at` are NULL on the snapshot** because the generated files do not carry them; the columns exist for the API and for the per-line rounding rule.
* **Row counts** are those of the scratch databases named above; the shared development database and the hosted `postgres:16` service hold whatever the tests last loaded.
