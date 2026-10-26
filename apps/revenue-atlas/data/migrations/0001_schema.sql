-- 0001_schema.sql: tables for every entity in the golden inputs.json plus the
-- operational tables (docs/contracts.md D-02: money NUMERIC(20,6); D-04: allocation
-- keyed by shipment_line_id). Idempotent: every statement is IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS customers (
    customer_id    TEXT NOT NULL,
    customer_name  TEXT NOT NULL,
    region_id      TEXT NOT NULL,
    segment        TEXT NOT NULL,
    effective_from DATE NOT NULL,
    PRIMARY KEY (customer_id, effective_from)   -- type-2 versions (D-06)
);

CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT PRIMARY KEY,
    sku             TEXT NOT NULL,
    category_id     TEXT NOT NULL,
    unit_of_measure TEXT NOT NULL,
    active          BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id    TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_date  DATE NOT NULL,
    currency    TEXT NOT NULL,
    status      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
    line_id    TEXT PRIMARY KEY,
    order_id   TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity   BIGINT NOT NULL,
    unit_price NUMERIC(20,6) NOT NULL
);

CREATE TABLE IF NOT EXISTS discounts (
    discount_id     TEXT PRIMARY KEY,
    line_id         TEXT NOT NULL,
    discount_amount NUMERIC(20,6) NOT NULL,
    reason_code     TEXT NOT NULL,
    approved_by     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id   TEXT PRIMARY KEY,
    order_id      TEXT NOT NULL,
    shipped_at    TIMESTAMPTZ NOT NULL,
    shipping_cost NUMERIC(20,6) NOT NULL,
    currency      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shipment_lines (
    shipment_line_id TEXT PRIMARY KEY,
    shipment_id      TEXT NOT NULL,
    line_id          TEXT NOT NULL,
    shipped_quantity BIGINT NOT NULL,
    cost_version_id  TEXT,                       -- NULL until command C02 sets it (D-03)
    version          INT NOT NULL DEFAULT 1      -- optimistic concurrency (C03)
);

-- Append-only (trigger in 0002): a correction is a new row, never an update.
CREATE TABLE IF NOT EXISTS returns (
    return_id         TEXT PRIMARY KEY,
    shipment_line_id  TEXT NOT NULL,
    returned_quantity BIGINT NOT NULL,
    credit_amount     NUMERIC(20,6) NOT NULL,
    credit_date       DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_versions (
    cost_version_id TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL,
    unit_cost       NUMERIC(20,6) NOT NULL,
    valid_from      DATE NOT NULL,
    valid_to        DATE                         -- NULL = open (D-03)
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    rate_id            TEXT PRIMARY KEY,
    currency           TEXT NOT NULL,
    reporting_currency TEXT NOT NULL,
    rate_date          DATE NOT NULL,
    rate               NUMERIC(20,6) NOT NULL
);

-- Operational tables ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raw_batches (
    batch_id        TEXT PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash    TEXT NOT NULL,
    payload         JSONB NOT NULL,              -- raw rows preserved (D-06 C01)
    status          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_records (
    entity      TEXT NOT NULL,
    id          TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_row     JSONB NOT NULL,
    batch_id    TEXT NOT NULL REFERENCES raw_batches (batch_id),
    PRIMARY KEY (batch_id, entity, id)
);

CREATE TABLE IF NOT EXISTS quarantined_records (
    entity      TEXT NOT NULL,
    id          TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_row     JSONB NOT NULL,
    batch_id    TEXT,
    PRIMARY KEY (entity, id)                     -- one active quarantine per record
);

-- P01-TEST-01: the PRIMARY KEY on shipment_line_id is the double-allocation guard (D-04).
CREATE TABLE IF NOT EXISTS freight_allocations (
    shipment_line_id TEXT PRIMARY KEY REFERENCES shipment_lines (shipment_line_id),
    shipment_id      TEXT NOT NULL,
    amount           NUMERIC(20,6) NOT NULL,
    allocated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS discount_allocations (
    shipment_line_id TEXT PRIMARY KEY REFERENCES shipment_lines (shipment_line_id),
    line_id          TEXT NOT NULL,
    amount           NUMERIC(20,6) NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id       TEXT PRIMARY KEY,
    entity_type    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    action         TEXT NOT NULL,
    actor_id       TEXT NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    before_version INT,
    after_version  INT,
    reason         TEXT,
    request_id     TEXT
);

CREATE TABLE IF NOT EXISTS command_results (
    idempotency_key TEXT PRIMARY KEY,
    payload_hash    TEXT NOT NULL,
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
