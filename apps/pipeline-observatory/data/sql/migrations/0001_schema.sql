-- Pipeline Observatory, schema v1 (PostgreSQL 16). Entity names follow section 03 of the spec (source_contracts, ingestion_batches,
-- raw_records, quarantine_records, checkpoints, model_definitions, pipeline_runs, task_runs, quality_results, publications, incidents,
-- backfill_requests) with the fields D-P8-12 adds; the rest are the pipeline's own tables (accepted_records is the idempotency boundary).
-- Every instant is TIMESTAMPTZ; no floating-point column anywhere (counts are integers, money lives in payload strings and NUMERIC(18,2)).
-- Idempotent: every statement can run twice.

CREATE TABLE IF NOT EXISTS source_contracts (
    source_id                TEXT PRIMARY KEY,
    source_name              TEXT NOT NULL,
    schema_version           TEXT NOT NULL,
    expected_frequency       TEXT NOT NULL,
    owner_id                 TEXT NOT NULL,
    freshness_target_seconds INT CHECK (freshness_target_seconds IS NULL OR freshness_target_seconds > 0)   -- the gate's freshness check; NULL = none
);

-- The synthetic source's declared count per source and UTC-date partition, including rows that later fail (D-P8-02).
CREATE TABLE IF NOT EXISTS source_expectations (
    source_id        TEXT NOT NULL REFERENCES source_contracts (source_id),
    partition        TEXT NOT NULL CHECK (partition ~ '^\d{4}-\d{2}-\d{2}$'),
    expected_records INT  NOT NULL CHECK (expected_records >= 0),
    PRIMARY KEY (source_id, partition)
);

CREATE TABLE IF NOT EXISTS ingestion_batches (
    batch_id       TEXT PRIMARY KEY,
    source_id      TEXT NOT NULL REFERENCES source_contracts (source_id),
    source_cursor  TEXT NOT NULL,                       -- the cursor the batch was fetched from
    started_at     TIMESTAMPTZ NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('staged', 'committed', 'aborted', 'quarantined')),
    next_cursor    TEXT,                                -- what a commit records as committed_cursor
    schema_version TEXT,                                -- the version the page declared; NULL = the contract's
    validated_at   TIMESTAMPTZ,
    fetch_session  TEXT
);

CREATE TABLE IF NOT EXISTS raw_records (
    raw_record_id TEXT PRIMARY KEY,
    batch_id      TEXT NOT NULL REFERENCES ingestion_batches (batch_id),
    source_key    TEXT,                                 -- NULL: the row carries no key (quarantined MISSING_FIELD, never dropped)
    payload_hash  TEXT NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    payload_json  JSONB NOT NULL,
    disposition   TEXT CHECK (disposition IN ('accepted', 'duplicate', 'quarantined', 'deleted')),   -- evidence of the last classification
    reason_code   TEXT
);

-- THE idempotency boundary (D-01): a source_key is accepted once per source, whatever the batch.
CREATE TABLE IF NOT EXISTS accepted_records (
    source_id        TEXT NOT NULL REFERENCES source_contracts (source_id),
    source_key       TEXT NOT NULL,
    raw_record_id    TEXT NOT NULL UNIQUE REFERENCES raw_records (raw_record_id),
    batch_id         TEXT NOT NULL REFERENCES ingestion_batches (batch_id),
    accepted_at      TIMESTAMPTZ NOT NULL,
    deleted_in_batch TEXT REFERENCES ingestion_batches (batch_id),     -- a delete event propagated to the published snapshot
    PRIMARY KEY (source_id, source_key)
);

CREATE TABLE IF NOT EXISTS quarantine_records (
    quarantine_id TEXT PRIMARY KEY,
    batch_id      TEXT NOT NULL REFERENCES ingestion_batches (batch_id),
    source_key    TEXT,
    reason_code   TEXT NOT NULL,
    payload_hash  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id    TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL REFERENCES source_contracts (source_id),
    batch_id         TEXT NOT NULL UNIQUE REFERENCES ingestion_batches (batch_id),
    committed_cursor TEXT NOT NULL,
    committed_at     TIMESTAMPTZ NOT NULL,
    version_number   INT NOT NULL CHECK (version_number >= 1),
    CONSTRAINT checkpoints_version_uq UNIQUE (source_id, version_number)
);

CREATE TABLE IF NOT EXISTS model_definitions (
    model_id        TEXT PRIMARY KEY,
    model_name      TEXT NOT NULL,
    grain           TEXT NOT NULL,
    version_number  INT NOT NULL CHECK (version_number >= 1),
    definition      TEXT NOT NULL,
    definition_hash TEXT NOT NULL CHECK (definition_hash = encode(sha256(convert_to(definition, 'UTF8')), 'hex')),
    CONSTRAINT model_definitions_version_uq UNIQUE (model_name, version_number)
);

CREATE TABLE IF NOT EXISTS backfill_requests (
    backfill_id  TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL REFERENCES source_contracts (source_id),
    start_at     TIMESTAMPTZ NOT NULL,
    end_at       TIMESTAMPTZ NOT NULL,                  -- half-open [start_at, end_at)
    status       TEXT NOT NULL,
    partitions   JSONB NOT NULL DEFAULT '[]'::jsonb,    -- [{"partition": "YYYY-MM-DD", "verified": bool}]
    requested_by TEXT,
    CHECK (start_at < end_at)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id             TEXT PRIMARY KEY,
    started_at         TIMESTAMPTZ NOT NULL,
    finished_at        TIMESTAMPTZ,
    status             TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    code_sha           TEXT NOT NULL,
    backfill_id        TEXT REFERENCES backfill_requests (backfill_id),
    included_batch_ids TEXT[] NOT NULL DEFAULT '{}',    -- the scope the transform consumed
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS task_runs (
    task_run_id TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES pipeline_runs (run_id),
    task_name   TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    attempt     INT  NOT NULL CHECK (attempt >= 1),
    CONSTRAINT task_runs_attempt_uq UNIQUE (run_id, task_name, attempt)
);

CREATE TABLE IF NOT EXISTS quality_results (
    quality_result_id TEXT PRIMARY KEY,
    task_run_id       TEXT NOT NULL REFERENCES task_runs (task_run_id),
    rule_name         TEXT NOT NULL,
    severity          TEXT NOT NULL CHECK (severity IN ('critical', 'warning')),
    eligible_count    INT NOT NULL CHECK (eligible_count >= 0),
    failure_count     INT NOT NULL CHECK (failure_count >= 0),
    CHECK (failure_count <= eligible_count)
);

CREATE TABLE IF NOT EXISTS publications (
    publication_id     TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL UNIQUE REFERENCES pipeline_runs (run_id),
    dataset_name       TEXT NOT NULL,
    published_at       TIMESTAMPTZ NOT NULL,
    watermark          TIMESTAMPTZ NOT NULL,            -- disclosed with every publication (D-02), not the latest included event
    source_ids         TEXT[] NOT NULL,
    included_batch_ids TEXT[] NOT NULL,
    content_hash       TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$')
);

-- The atomic publication pointer: one row, moved only to a passed candidate (guard trigger in 0002).
CREATE TABLE IF NOT EXISTS publication_pointer (
    id             INT PRIMARY KEY CHECK (id = 1),
    publication_id TEXT NOT NULL REFERENCES publications (publication_id),
    updated_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs (run_id),
    severity        TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    opened_at       TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    recovery_run_id TEXT REFERENCES pipeline_runs (run_id),
    reason          TEXT,
    CHECK ((status = 'closed') = (closed_at IS NOT NULL)),
    CHECK (status = 'open' OR recovery_run_id IS NOT NULL),
    CHECK (closed_at IS NULL OR closed_at >= opened_at)
);

-- The analytical table the transform builds (not unique on the key on purpose: the key test must be able to FAIL).
CREATE TABLE IF NOT EXISTS model_outputs (
    output_id    BIGSERIAL PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES pipeline_runs (run_id),
    model_name   TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    record_key   TEXT NOT NULL,
    batch_id     TEXT NOT NULL,
    day          TEXT NOT NULL,
    amount       NUMERIC(18, 2) NOT NULL,
    payload_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_measurements (
    measurement_id  BIGSERIAL PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES source_contracts (source_id),
    batch_id        TEXT NOT NULL REFERENCES ingestion_batches (batch_id),
    measured_seconds NUMERIC NOT NULL CHECK (measured_seconds > 0),
    hardware        TEXT NOT NULL,
    cache_state     TEXT NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fetch_log (
    fetch_id           BIGSERIAL PRIMARY KEY,
    source_id          TEXT NOT NULL REFERENCES source_contracts (source_id),
    cursor_value       TEXT NOT NULL,
    session_id         TEXT,
    status             TEXT NOT NULL CHECK (status IN ('ok', 'rate_limited', 'cursor_loop')),
    next_cursor        TEXT,
    retry_after_seconds INT,
    fetched_at         TIMESTAMPTZ NOT NULL,
    batch_id           TEXT
);

CREATE TABLE IF NOT EXISTS fault_injections (
    fault_id     TEXT PRIMARY KEY,
    fault_type   TEXT NOT NULL CHECK (fault_type IN ('duplicate_key', 'task_failure', 'crash_before_checkpoint')),
    target_id    TEXT NOT NULL,
    injected_by  TEXT NOT NULL,
    injected_at  TIMESTAMPTZ NOT NULL,
    armed        BOOLEAN NOT NULL DEFAULT false,
    consumed_at  TIMESTAMPTZ,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS evidence_archives (
    archive_id    TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL UNIQUE REFERENCES pipeline_runs (run_id),
    created_at    TIMESTAMPTZ NOT NULL,
    created_by    TEXT NOT NULL,
    manifest      JSONB NOT NULL,
    manifest_hash TEXT NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    retention     JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_records (
    batch_id    TEXT NOT NULL,
    entity      TEXT NOT NULL,
    id          TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_row     JSONB NOT NULL,
    ordinal     INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, entity, id, reason_code, ordinal)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id       TEXT PRIMARY KEY,
    entity_type    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    action         TEXT NOT NULL,
    actor_id       TEXT NOT NULL,
    actor_role     TEXT,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    before_version INT,
    after_version  INT,
    reason         TEXT,
    request_id     TEXT,
    details        JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Idempotency: the key is bound to the actor (id and role) and to the payload, which includes the dataset_version.
CREATE TABLE IF NOT EXISTS command_results (
    idempotency_key TEXT PRIMARY KEY,
    payload_hash    TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    actor_role      TEXT NOT NULL,
    command_id      TEXT NOT NULL,
    status          TEXT NOT NULL,
    result          JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset_version  TEXT PRIMARY KEY,
    dataset_hash     TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    as_of            TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS batches_source_idx     ON ingestion_batches (source_id, started_at);
CREATE INDEX IF NOT EXISTS raw_records_batch_idx  ON raw_records (batch_id, raw_record_id);
CREATE INDEX IF NOT EXISTS raw_records_key_idx    ON raw_records (source_key);
CREATE INDEX IF NOT EXISTS accepted_batch_idx     ON accepted_records (batch_id);
CREATE INDEX IF NOT EXISTS quarantine_batch_idx   ON quarantine_records (batch_id);
CREATE INDEX IF NOT EXISTS task_runs_run_idx      ON task_runs (run_id, task_name, attempt);
CREATE INDEX IF NOT EXISTS quality_task_idx       ON quality_results (task_run_id);
CREATE INDEX IF NOT EXISTS model_outputs_run_idx  ON model_outputs (run_id, source_id, record_key);
CREATE INDEX IF NOT EXISTS fetch_log_idx          ON fetch_log (source_id, cursor_value, fetched_at);
CREATE INDEX IF NOT EXISTS backfills_source_idx   ON backfill_requests (source_id, start_at);
CREATE INDEX IF NOT EXISTS audit_entity_idx       ON audit_events (entity_type, entity_id, occurred_at);
