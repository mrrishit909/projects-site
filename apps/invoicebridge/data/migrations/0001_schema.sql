-- InvoiceBridge schema, contract v1 (docs/contracts.md D-01..D-05). Idempotent: every statement is IF NOT EXISTS.
-- Money is NUMERIC (never float); quantities NUMERIC(20,4); unit prices and rates NUMERIC(*,6); instants TIMESTAMPTZ (UTC).
-- Constraints, immutability triggers and the status vocabulary live in 0002_constraints.sql.

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id     TEXT PRIMARY KEY,
    vendor_name   TEXT NOT NULL,
    tax_reference TEXT NOT NULL,
    currency      CHAR(3) NOT NULL,
    active        BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id      TEXT PRIMARY KEY,
    vendor_id  TEXT NOT NULL REFERENCES vendors (vendor_id),
    ordered_at TIMESTAMPTZ NOT NULL,
    status     TEXT NOT NULL,
    currency   CHAR(3) NOT NULL
);

CREATE TABLE IF NOT EXISTS po_lines (
    po_line_id   TEXT PRIMARY KEY,
    po_id        TEXT NOT NULL REFERENCES purchase_orders (po_id),
    product_code TEXT NOT NULL,
    quantity     NUMERIC(20,4) NOT NULL,
    unit_price   NUMERIC(20,6) NOT NULL
);

-- A receipt is a fact; a reversal flips ``reversed`` (the only column that may change, see 0002).
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id        TEXT PRIMARY KEY,
    po_line_id        TEXT NOT NULL REFERENCES po_lines (po_line_id),
    received_quantity NUMERIC(20,4) NOT NULL,
    received_at       TIMESTAMPTZ NOT NULL,
    reversed          BOOLEAN NOT NULL DEFAULT FALSE,
    reversed_at       TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS approval_policies (
    policy_id       TEXT PRIMARY KEY,
    version_number  INT NOT NULL,
    amount_limit    NUMERIC(20,2) NOT NULL,
    reviewer_role   TEXT NOT NULL,
    escalation_role TEXT,
    effective_from  TIMESTAMPTZ NOT NULL
);

-- One row: the tolerances the dataset travels with (D-05).
CREATE TABLE IF NOT EXISTS tolerances (
    id                   INT PRIMARY KEY,
    price_per_unit       NUMERIC(20,6) NOT NULL,
    rounding_per_line    NUMERIC(20,6) NOT NULL,
    rounding_per_invoice NUMERIC(20,6) NOT NULL
);

-- ``subtotal``, ``tax`` and ``total`` are stored at import for reads; the SQL reference recomputes them from the lines.
-- ``validity`` is the C02 verdict (NULL: not validated yet, outside the book). ``status`` is the workflow state.
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id          TEXT PRIMARY KEY,
    vendor_id           TEXT NOT NULL REFERENCES vendors (vendor_id),
    invoice_number      TEXT NOT NULL,
    invoice_number_norm TEXT NOT NULL,
    invoice_date        DATE NOT NULL,
    currency            CHAR(3) NOT NULL,
    tax_rate            NUMERIC(8,6) NOT NULL,
    freight             NUMERIC(20,2) NOT NULL,
    invoice_discount    NUMERIC(20,2) NOT NULL,
    declared_total      NUMERIC(20,2) NOT NULL,
    subtotal            NUMERIC(20,2) NOT NULL,
    tax                 NUMERIC(20,2) NOT NULL,
    total               NUMERIC(20,2) NOT NULL,
    created_by          TEXT NOT NULL,
    source_sha256       CHAR(64) NOT NULL,
    source_filename     TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL,
    imported_at         TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL DEFAULT 'received',
    validity            BOOLEAN,
    validation_rules    JSONB NOT NULL DEFAULT '[]'::jsonb,
    merged_into         TEXT,
    merge_reason        TEXT,
    version             INT NOT NULL DEFAULT 1,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ``po_line_id`` is deliberately not a foreign key: an invoice line naming no PO line is the NO_PO_LINE exception.
CREATE TABLE IF NOT EXISTS invoice_lines (
    invoice_line_id TEXT PRIMARY KEY,
    invoice_id      TEXT NOT NULL REFERENCES invoices (invoice_id),
    po_line_id      TEXT NOT NULL,
    quantity        NUMERIC(20,4) NOT NULL,
    unit_price      NUMERIC(20,6) NOT NULL,
    line_amount     NUMERIC(20,2)
);

-- Append-only import lineage: every import attempt that reached the book, with the sha256 of its source bytes.
CREATE TABLE IF NOT EXISTS import_lineage (
    lineage_id      BIGSERIAL PRIMARY KEY,
    invoice_id      TEXT NOT NULL,
    source_sha256   CHAR(64) NOT NULL,
    source_filename TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    imported_at     TIMESTAMPTZ NOT NULL,
    actor_id        TEXT NOT NULL,
    import_status   TEXT NOT NULL,
    reason_code     TEXT,
    merged_into     TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS match_results (
    invoice_line_id    TEXT PRIMARY KEY REFERENCES invoice_lines (invoice_line_id),
    invoice_id         TEXT NOT NULL REFERENCES invoices (invoice_id),
    rule_version       TEXT NOT NULL,
    status             TEXT NOT NULL,
    reason_code        TEXT,
    available_quantity NUMERIC(20,4),
    quantity_variance  NUMERIC(20,4),
    price_variance     NUMERIC(20,4),
    explanation        TEXT NOT NULL DEFAULT '',
    matched_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS exception_seq;

CREATE TABLE IF NOT EXISTS exceptions (
    exception_id   TEXT PRIMARY KEY,
    invoice_id     TEXT NOT NULL REFERENCES invoices (invoice_id),
    exception_type TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',
    owner_id       TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ
);

-- Assignment history (append-only): who owned the exception and when; the backlog is reconstructed from it.
CREATE TABLE IF NOT EXISTS exception_assignments (
    assignment_id BIGSERIAL PRIMARY KEY,
    exception_id  TEXT NOT NULL REFERENCES exceptions (exception_id),
    owner_id      TEXT NOT NULL,
    assigned_by   TEXT NOT NULL,
    assigned_at   TIMESTAMPTZ NOT NULL,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id    TEXT PRIMARY KEY,
    invoice_id     TEXT NOT NULL REFERENCES invoices (invoice_id),
    actor_id       TEXT NOT NULL,
    actor_role     TEXT NOT NULL,
    decision       TEXT NOT NULL,
    decided_at     TIMESTAMPTZ NOT NULL,
    reason         TEXT,
    policy_id      TEXT,
    policy_version INT
);

CREATE TABLE IF NOT EXISTS credit_notes (
    credit_id     TEXT PRIMARY KEY,
    invoice_id    TEXT NOT NULL REFERENCES invoices (invoice_id),
    credit_amount NUMERIC(20,2) NOT NULL,
    credited_at   TIMESTAMPTZ,
    reason        TEXT,
    created_by    TEXT
);

CREATE TABLE IF NOT EXISTS export_batches (
    batch_id        TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    requested_by    TEXT NOT NULL,
    exported_at     TIMESTAMPTZ NOT NULL,
    row_count       INT NOT NULL,
    total           NUMERIC(20,2) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS export_rows (
    export_id      TEXT PRIMARY KEY,
    batch_id       TEXT NOT NULL REFERENCES export_batches (batch_id),
    invoice_id     TEXT NOT NULL REFERENCES invoices (invoice_id),
    exported_at    TIMESTAMPTZ NOT NULL,
    vendor_id      TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    invoice_date   DATE NOT NULL,
    currency       CHAR(3) NOT NULL,
    amount         NUMERIC(20,2) NOT NULL,
    content_hash   CHAR(64) NOT NULL
);

-- Every export request that reached the handler, including repeats that returned the prior batch (P05-FLOW-09).
CREATE TABLE IF NOT EXISTS export_requests (
    request_seq     BIGSERIAL PRIMARY KEY,
    batch_id        TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    invoice_ids     TEXT[] NOT NULL,
    exported_at     TIMESTAMPTZ NOT NULL,
    outcome         TEXT NOT NULL,
    requested_by    TEXT NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rejected_records (
    batch_id    TEXT NOT NULL,
    entity      TEXT NOT NULL,
    id          TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_row     JSONB NOT NULL,
    ordinal     INT NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, entity, id, reason_code, ordinal)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id       TEXT PRIMARY KEY,
    entity_type    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    invoice_id     TEXT,
    action         TEXT NOT NULL,
    actor_id       TEXT NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    before_version INT,
    after_version  INT,
    reason         TEXT,
    request_id     TEXT,
    details        JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Actor-bound idempotency: the same key from another actor is refused.
CREATE TABLE IF NOT EXISTS command_results (
    idempotency_key TEXT PRIMARY KEY,
    payload_hash    TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    command_id      TEXT NOT NULL,
    status          TEXT NOT NULL,
    result          JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset_version  TEXT PRIMARY KEY,
    dataset_hash     TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS invoice_lines_invoice_idx ON invoice_lines (invoice_id);
CREATE INDEX IF NOT EXISTS invoices_vendor_idx       ON invoices (vendor_id, invoice_date);
CREATE INDEX IF NOT EXISTS invoices_sha_idx          ON invoices (source_sha256);
CREATE INDEX IF NOT EXISTS invoices_status_idx       ON invoices (status);
CREATE INDEX IF NOT EXISTS receipts_line_idx         ON receipts (po_line_id, received_at);
CREATE INDEX IF NOT EXISTS approvals_invoice_idx     ON approvals (invoice_id, decided_at);
CREATE INDEX IF NOT EXISTS audit_invoice_idx         ON audit_events (invoice_id, occurred_at);
CREATE INDEX IF NOT EXISTS lineage_invoice_idx       ON import_lineage (invoice_id);
CREATE INDEX IF NOT EXISTS lineage_sha_idx           ON import_lineage (source_sha256);
CREATE UNIQUE INDEX IF NOT EXISTS exceptions_open_uq ON exceptions (invoice_id, exception_type) WHERE status <> 'resolved';
