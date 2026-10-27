# Entity-relationship diagram (P05-ART-03)

Derived from `data/migrations/0001_schema.sql`, `0002_constraints.sql` and `0003_review_status.sql` (dataset `ib-20261026-20261026`, generator `dataset_hash` `1f001a43a7031d4260f5abb3b9f7a83f6e1b48397e85cf8b04e0b4d9e052162e`, contract v1, code revision `2dcc460`; **synthetic data only**). Solid lines are enforced foreign keys; dotted lines are logical joins the contract relies on (D-01, D-05, D-06) that the database does not enforce, so that an invoice line naming no PO line can exist and be an exception instead of a load error. Field detail, grain, update semantics and the deletion policy are in `data-dictionary.md`.
How to read it without installing anything: any Markdown viewer that renders Mermaid draws the diagram; otherwise the field lists below are the whole model. Types are those of the migration with the comma of a precision written as an underscore (`NUMERIC(20_2)` is `NUMERIC(20,2)`, because Mermaid attribute types cannot contain a comma). `PK` marks the primary key (a composite key marks every member), `FK` an enforced foreign key. The 21 tables are those of `0001`; `schema_migrations` is created by `data/migrate.py` and has no relationship, so it is not drawn.

```mermaid
erDiagram
    vendors {
        TEXT vendor_id PK
        TEXT vendor_name
        TEXT tax_reference
        CHAR(3) currency
        BOOLEAN active
    }
    purchase_orders {
        TEXT po_id PK
        TEXT vendor_id FK
        TIMESTAMPTZ ordered_at
        TEXT status
        CHAR(3) currency
    }
    po_lines {
        TEXT po_line_id PK
        TEXT po_id FK
        TEXT product_code
        NUMERIC(20_4) quantity
        NUMERIC(20_6) unit_price
    }
    receipts {
        TEXT receipt_id PK
        TEXT po_line_id FK
        NUMERIC(20_4) received_quantity
        TIMESTAMPTZ received_at
        BOOLEAN reversed
        TIMESTAMPTZ reversed_at
    }
    approval_policies {
        TEXT policy_id PK
        INT version_number
        NUMERIC(20_2) amount_limit
        TEXT reviewer_role
        TEXT escalation_role
        TIMESTAMPTZ effective_from
    }
    tolerances {
        INT id PK
        NUMERIC(20_6) price_per_unit
        NUMERIC(20_6) rounding_per_line
        NUMERIC(20_6) rounding_per_invoice
    }
    invoices {
        TEXT invoice_id PK
        TEXT vendor_id FK
        TEXT invoice_number
        TEXT invoice_number_norm
        DATE invoice_date
        CHAR(3) currency
        NUMERIC(8_6) tax_rate
        NUMERIC(20_2) freight
        NUMERIC(20_2) invoice_discount
        NUMERIC(20_2) declared_total
        NUMERIC(20_2) subtotal
        NUMERIC(20_2) tax
        NUMERIC(20_2) total
        TEXT created_by
        TEXT source_filename
        TEXT idempotency_key
        TIMESTAMPTZ imported_at
        TEXT status
        BOOLEAN validity
        JSONB validation_rules
        TEXT merged_into
        TEXT merge_reason
        INT version
        TIMESTAMPTZ updated_at
    }
    invoice_lines {
        TEXT invoice_line_id PK
        TEXT invoice_id FK
        TEXT po_line_id
        NUMERIC(20_4) quantity
        NUMERIC(20_6) unit_price
        NUMERIC(20_2) line_amount
    }
    import_lineage {
        BIGSERIAL lineage_id PK
        TEXT invoice_id
        TEXT source_filename
        TEXT idempotency_key
        TIMESTAMPTZ imported_at
        TEXT actor_id
        TEXT import_status
        TEXT reason_code
        TEXT merged_into
        TIMESTAMPTZ recorded_at
    }
    match_results {
        TEXT invoice_line_id PK
        TEXT invoice_id FK
        TEXT rule_version
        TEXT status
        TEXT reason_code
        NUMERIC(20_4) available_quantity
        NUMERIC(20_4) quantity_variance
        NUMERIC(20_4) price_variance
        TEXT explanation
        TIMESTAMPTZ matched_at
    }
    exceptions {
        TEXT exception_id PK
        TEXT invoice_id FK
        TEXT exception_type
        TEXT status
        TEXT owner_id
        TIMESTAMPTZ created_at
        TIMESTAMPTZ resolved_at
    }
    exception_assignments {
        BIGSERIAL assignment_id PK
        TEXT exception_id FK
        TEXT owner_id
        TEXT assigned_by
        TIMESTAMPTZ assigned_at
        TEXT note
    }
    approvals {
        TEXT approval_id PK
        TEXT invoice_id FK
        TEXT actor_id
        TEXT actor_role
        TEXT decision
        TIMESTAMPTZ decided_at
        TEXT reason
        TEXT policy_id
        INT policy_version
    }
    credit_notes {
        TEXT credit_id PK
        TEXT invoice_id FK
        NUMERIC(20_2) credit_amount
        TIMESTAMPTZ credited_at
        TEXT reason
        TEXT created_by
    }
    export_batches {
        TEXT batch_id PK
        TEXT idempotency_key
        TEXT requested_by
        TIMESTAMPTZ exported_at
        INT row_count
        NUMERIC(20_2) total
        TIMESTAMPTZ created_at
    }
    export_rows {
        TEXT export_id PK
        TEXT batch_id FK
        TEXT invoice_id FK
        TIMESTAMPTZ exported_at
        TEXT vendor_id
        TEXT invoice_number
        DATE invoice_date
        CHAR(3) currency
        NUMERIC(20_2) amount
        CHAR(64) content_hash
    }
    export_requests {
        BIGSERIAL request_seq PK
        TEXT batch_id
        TEXT idempotency_key
        TEXT[] invoice_ids
        TIMESTAMPTZ exported_at
        TEXT outcome
        TEXT requested_by
        TIMESTAMPTZ recorded_at
    }
    rejected_records {
        TEXT batch_id PK
        TEXT entity PK
        TEXT id PK
        TEXT reason_code PK
        JSONB raw_row
        INT ordinal PK
        TIMESTAMPTZ recorded_at
    }
    audit_events {
        TEXT event_id PK
        TEXT entity_type
        TEXT entity_id
        TEXT invoice_id
        TEXT action
        TEXT actor_id
        TIMESTAMPTZ occurred_at
        INT before_version
        INT after_version
        TEXT reason
        TEXT request_id
        JSONB details
    }
    command_results {
        TEXT idempotency_key PK
        TEXT payload_hash
        TEXT actor_id
        TEXT command_id
        TEXT status
        JSONB result
        TIMESTAMPTZ created_at
    }
    dataset_versions {
        TEXT dataset_version PK
        TEXT dataset_hash
        TEXT contract_version
        TIMESTAMPTZ created_at
    }
    vendors ||--o{ purchase_orders : "orders from"
    purchase_orders ||--o{ po_lines : "has lines"
    po_lines ||--o{ receipts : "received as"
    vendors ||--o{ invoices : "bills"
    invoices ||--o{ invoice_lines : "has lines"
    invoices ||--o{ import_lineage : "arrived as (logical)"
    invoice_lines ||--o| match_results : "matched as"
    invoices ||--o{ match_results : "match outcome"
    invoices ||--o{ exceptions : "blocked by"
    exceptions ||--o{ exception_assignments : "owned through"
    invoices ||--o{ approvals : "decided by"
    invoices ||--o{ credit_notes : "reduced by"
    export_batches ||--o{ export_rows : "contains"
    invoices ||--o| export_rows : "exported once"
    po_lines ||..o{ invoice_lines : "po_line_id (logical, so NO_PO_LINE can exist)"
    approval_policies ||..o{ approvals : "policy in force (logical)"
    invoices ||..o{ invoices : "merged_into (logical)"
    invoices ||..o{ export_requests : "invoice_ids (logical)"
    invoices ||..o{ audit_events : "invoice_id (logical)"
```

## Reading notes

* **Money is per currency.** `vendors.currency`, `purchase_orders.currency`, `invoices.currency` and `export_rows.currency` carry the unit of every amount of their row; there is no exchange-rate table, so no relationship and no query converts or sums across currencies (`CURRENCY_MISMATCH` is the exception raised instead).
* **Immutable and append-only:** `invoice_lines`, `import_lineage`, `approvals`, `export_rows`, `credit_notes`, `exception_assignments` and `audit_events` refuse UPDATE, DELETE and TRUNCATE; `invoices` refuse DELETE and any change to the extracted source; `receipts` can only be reversed. Lineage is therefore append-only: the same bytes arriving again adds a lineage row and a merged invoice, it never edits the first.
* **One obligation per document:** `export_rows` has `UNIQUE (invoice_id)` (an invoice exports once) and `credit_notes.credit_id` is the key (a credit applies once). The identity used for duplicates (vendor, normalised number, date, computed total) is derived, not a column; `invoices.merged_into` and `import_lineage.merged_into` point at the canonical copy.
* **Logical joins (dotted):** `invoice_lines.po_line_id` to `po_lines` (a missing line is `NO_PO_LINE`); `approvals.policy_id` to `approval_policies` (the policy in force at `decided_at`); `export_requests.invoice_ids[]` to `invoices`; `invoices.merged_into` to `invoices`; `import_lineage.invoice_id` to `invoices`; `audit_events.invoice_id` to `invoices`.
* **Derived, rebuildable tables:** `match_results`, `export_batches`, `export_rows` and the open part of `exceptions` are written from the domain's derivation at one as-of; the metrics never read them (D-06).
* **Not drawn:** the temporary tables of the analysis (`ib_run`, `ib_facts`, `data/sql/analysis/00_book.sql`) and the BI star schema (`bi-package.md`).
