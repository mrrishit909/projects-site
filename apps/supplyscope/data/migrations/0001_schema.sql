-- SupplyScope schema, contract v1 (docs/contracts.md). Idempotent: every statement is IF NOT EXISTS.
-- All instants are TIMESTAMPTZ (UTC). Constraints and triggers live in 0002_constraints.sql.

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id       TEXT PRIMARY KEY,
    supplier_name     TEXT NOT NULL,
    calendar_id       TEXT NOT NULL,
    quoted_lead_days  INT NOT NULL,
    active            BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id             TEXT PRIMARY KEY,
    sku                    TEXT NOT NULL UNIQUE,
    unit_cost              NUMERIC(14,2) NOT NULL,     -- the cost before any cost_versions row (D-05)
    pack_size              INT NOT NULL,
    minimum_order_quantity INT NOT NULL,
    abc_class              TEXT,
    supplier_id            TEXT REFERENCES suppliers (supplier_id)
);

CREATE TABLE IF NOT EXISTS locations (
    location_id      TEXT PRIMARY KEY,
    location_name    TEXT NOT NULL,
    timezone         TEXT NOT NULL,
    storage_capacity INT NOT NULL,
    active           BOOLEAN NOT NULL
);

-- A closed date range of a supplier calendar; closed days do not count towards lead days (P03-TEST-05).
CREATE TABLE IF NOT EXISTS calendar_closures (
    closure_id  TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    closed_from DATE NOT NULL,
    closed_to   DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_versions (
    cost_version_id TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL REFERENCES products (product_id),
    unit_cost       NUMERIC(14,2) NOT NULL,
    effective_from  TIMESTAMPTZ NOT NULL,
    UNIQUE (product_id, effective_from)
);

CREATE TABLE IF NOT EXISTS policy_scenarios (
    scenario_id    TEXT PRIMARY KEY,
    scenario_name  TEXT NOT NULL,
    service_target NUMERIC(4,2) NOT NULL,
    unmet_policy   TEXT NOT NULL,                 -- lost_sale OR backlog, never both (P03-TEST-08)
    seed           BIGINT NOT NULL,
    warmup_days    INT NOT NULL,
    replications   INT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    purchase_order_id TEXT PRIMARY KEY,
    supplier_id       TEXT NOT NULL REFERENCES suppliers (supplier_id),
    ordered_at        TIMESTAMPTZ NOT NULL,
    status            TEXT NOT NULL,
    currency          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    po_line_id        TEXT PRIMARY KEY,
    purchase_order_id TEXT NOT NULL REFERENCES purchase_orders (purchase_order_id),
    product_id        TEXT NOT NULL REFERENCES products (product_id),
    ordered_quantity  INT NOT NULL,
    unit_cost         NUMERIC(14,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    receipt_id        TEXT PRIMARY KEY,
    po_line_id        TEXT NOT NULL REFERENCES purchase_order_lines (po_line_id),
    location_id       TEXT NOT NULL REFERENCES locations (location_id),
    received_quantity INT NOT NULL,
    received_at       TIMESTAMPTZ NOT NULL
);

-- Immutable events (trigger in 0002). UNIQUE (movement_id) rejects a duplicate at the database too (P03-TEST-04).
CREATE TABLE IF NOT EXISTS inventory_movements (
    movement_id    TEXT NOT NULL UNIQUE,
    product_id     TEXT NOT NULL REFERENCES products (product_id),
    location_id    TEXT NOT NULL REFERENCES locations (location_id),
    quantity_delta INT NOT NULL,
    event_at       TIMESTAMPTZ NOT NULL,
    movement_type  TEXT NOT NULL,
    PRIMARY KEY (movement_id)
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id     TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL REFERENCES products (product_id),
    location_id TEXT NOT NULL REFERENCES locations (location_id),
    sold_at     TIMESTAMPTZ NOT NULL,
    quantity    INT NOT NULL
);

CREATE TABLE IF NOT EXISTS promotions (
    promotion_id    TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL REFERENCES products (product_id),
    location_id     TEXT REFERENCES locations (location_id),
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL,
    planned_uplift  NUMERIC(8,4) NOT NULL,      -- the schedule, known when announced
    announced_at    TIMESTAMPTZ NOT NULL,
    realised_uplift NUMERIC(8,4)                -- an outcome: never a forecast feature (P03-TEST-02)
);

CREATE TABLE IF NOT EXISTS latent_demand (
    product_id      TEXT NOT NULL REFERENCES products (product_id),
    location_id     TEXT NOT NULL REFERENCES locations (location_id),
    demand_date     DATE NOT NULL,
    latent_quantity INT NOT NULL,
    PRIMARY KEY (product_id, location_id, demand_date)
);

CREATE TABLE IF NOT EXISTS forecast_runs (
    forecast_run_id  TEXT PRIMARY KEY,
    product_id       TEXT NOT NULL REFERENCES products (product_id),
    location_id      TEXT NOT NULL REFERENCES locations (location_id),
    cutoff           TIMESTAMPTZ NOT NULL,
    horizon_days     INT NOT NULL,
    selected_model   TEXT NOT NULL,
    information_hash TEXT,
    model_report     JSONB,
    notes            JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS forecast_points (
    forecast_point_id TEXT PRIMARY KEY,
    forecast_run_id   TEXT NOT NULL REFERENCES forecast_runs (forecast_run_id),
    model             TEXT NOT NULL,
    target_date       DATE NOT NULL,
    forecast_value    NUMERIC(14,2) NOT NULL,
    UNIQUE (forecast_run_id, model, target_date)
);

CREATE TABLE IF NOT EXISTS backorders (
    backorder_id TEXT PRIMARY KEY,
    product_id   TEXT NOT NULL REFERENCES products (product_id),
    location_id  TEXT NOT NULL REFERENCES locations (location_id),
    quantity     INT NOT NULL,
    opened_at    TIMESTAMPTZ NOT NULL,
    closed_at    TIMESTAMPTZ,
    scenario_id  TEXT REFERENCES policy_scenarios (scenario_id),
    demand_ref   TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS lost_sales (
    lost_sale_id TEXT PRIMARY KEY,
    product_id   TEXT NOT NULL REFERENCES products (product_id),
    location_id  TEXT NOT NULL REFERENCES locations (location_id),
    quantity     INT NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL,
    scenario_id  TEXT REFERENCES policy_scenarios (scenario_id),
    demand_ref   TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    product_id     TEXT NOT NULL REFERENCES products (product_id),
    location_id    TEXT NOT NULL REFERENCES locations (location_id),
    quantity       INT NOT NULL,
    reserved_at    TIMESTAMPTZ NOT NULL,
    released_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS replenishment_params (
    product_id      TEXT NOT NULL REFERENCES products (product_id),
    location_id     TEXT NOT NULL REFERENCES locations (location_id),
    reorder_point   INT NOT NULL,
    target_position INT NOT NULL,
    supplier_id     TEXT REFERENCES suppliers (supplier_id),
    PRIMARY KEY (product_id, location_id)
);

-- Derived rows -----------------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stock_snapshots (
    as_of               TIMESTAMPTZ NOT NULL,
    product_id          TEXT NOT NULL REFERENCES products (product_id),
    location_id         TEXT NOT NULL REFERENCES locations (location_id),
    on_hand_raw         INT NOT NULL,
    on_hand             INT NOT NULL,
    reserved            INT NOT NULL,
    available           INT NOT NULL,
    running_stock_min   INT NOT NULL,
    negative_stock      BOOLEAN NOT NULL,
    flags               JSONB NOT NULL DEFAULT '[]',
    PRIMARY KEY (as_of, product_id, location_id)
);

-- A recommendation row, never a purchase order (status is always 'draft', CHECK in 0002).
CREATE TABLE IF NOT EXISTS draft_orders (
    draft_order_id         TEXT PRIMARY KEY,
    as_of                  TIMESTAMPTZ NOT NULL,
    scenario_id            TEXT REFERENCES policy_scenarios (scenario_id),
    product_id             TEXT NOT NULL REFERENCES products (product_id),
    location_id            TEXT NOT NULL REFERENCES locations (location_id),
    supplier_id            TEXT,
    inventory_position     INT NOT NULL,
    reorder_point          INT NOT NULL,
    target_position        INT NOT NULL,
    raw_order              INT NOT NULL,
    minimum_order_quantity INT NOT NULL,
    order_after_moq        INT NOT NULL,
    pack_size              INT NOT NULL,
    order_quantity         INT NOT NULL,
    parameter_source       TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'draft',
    dataset_version        TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Named fixture states (add_purchase_order_lines) so a state can be requested by name over the API.
CREATE TABLE IF NOT EXISTS fixture_states (
    state_name TEXT PRIMARY KEY,
    payload    JSONB NOT NULL
);

-- Operational tables (as in Onboard Studio) ------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raw_batches (
    batch_id        TEXT PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash    TEXT NOT NULL,
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL
);

-- ordinal separates two rejected occurrences of the same id (a conflicting duplicate rejects both).
CREATE TABLE IF NOT EXISTS rejected_records (
    entity      TEXT NOT NULL,
    id          TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_row     JSONB NOT NULL,
    batch_id    TEXT NOT NULL REFERENCES raw_batches (batch_id),
    ordinal     INT NOT NULL DEFAULT 0,
    PRIMARY KEY (batch_id, entity, id, reason_code, ordinal)
);

CREATE TABLE IF NOT EXISTS quarantined_records (
    entity      TEXT NOT NULL,
    id          TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_row     JSONB NOT NULL,
    batch_id    TEXT,
    PRIMARY KEY (entity, id)
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
    actor_id        TEXT,
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
