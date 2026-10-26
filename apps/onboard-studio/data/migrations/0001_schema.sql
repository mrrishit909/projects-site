-- Onboard Studio schema, contract v1 (docs/contracts.md). Idempotent: every statement is IF NOT EXISTS.
-- All instants are TIMESTAMPTZ (UTC). Constraints and triggers live in 0002_constraints.sql.

CREATE TABLE IF NOT EXISTS organizations (
    organization_id   TEXT PRIMARY KEY,
    organization_name TEXT NOT NULL,
    segment           TEXT NOT NULL,
    region            TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_versions (
    workflow_version_id TEXT PRIMARY KEY,
    template_id         TEXT NOT NULL,
    version_number      INT NOT NULL,
    published_at        TIMESTAMPTZ,                 -- NULL = draft; immutable once set (D-02)
    definition_hash     TEXT,
    UNIQUE (template_id, version_number)
);

CREATE TABLE IF NOT EXISTS step_definitions (
    step_definition_id  TEXT PRIMARY KEY,
    workflow_version_id TEXT NOT NULL REFERENCES workflow_versions (workflow_version_id),
    step_name           TEXT NOT NULL,
    required            BOOLEAN NOT NULL,
    role_key            TEXT NOT NULL,
    sequence            INT NOT NULL,
    UNIQUE (workflow_version_id, sequence)
);

CREATE TABLE IF NOT EXISTS dependencies (
    dependency_id      TEXT PRIMARY KEY,
    step_definition_id TEXT NOT NULL REFERENCES step_definitions (step_definition_id),
    prerequisite_id    TEXT NOT NULL REFERENCES step_definitions (step_definition_id),
    dependency_type    TEXT NOT NULL DEFAULT 'mandatory',
    created_at         TIMESTAMPTZ,
    UNIQUE (step_definition_id, prerequisite_id)
);

-- Required document types per workflow version (D-05 carries them as a block until this table exists).
CREATE TABLE IF NOT EXISTS workflow_requirements (
    workflow_version_id TEXT NOT NULL REFERENCES workflow_versions (workflow_version_id),
    document_type       TEXT NOT NULL,
    PRIMARY KEY (workflow_version_id, document_type)
);

CREATE TABLE IF NOT EXISTS sla_rules (
    sla_rule_id         TEXT PRIMARY KEY,
    workflow_version_id TEXT NOT NULL UNIQUE REFERENCES workflow_versions (workflow_version_id),
    business_minutes    NUMERIC(12,4) NOT NULL,
    pause_policy        TEXT[] NOT NULL DEFAULT '{}',
    calendar_id         TEXT NOT NULL
);

-- kind: 'working' interval, or 'holiday' (subtracted from the working set; a weekend holiday subtracts nothing).
CREATE TABLE IF NOT EXISTS calendar_intervals (
    calendar_interval_id TEXT PRIMARY KEY,
    calendar_id          TEXT NOT NULL,
    starts_at            TIMESTAMPTZ NOT NULL,
    ends_at              TIMESTAMPTZ NOT NULL,
    timezone             TEXT NOT NULL,
    kind                 TEXT NOT NULL DEFAULT 'working'
);

CREATE TABLE IF NOT EXISTS cases (
    case_id             TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL REFERENCES organizations (organization_id),
    workflow_version_id TEXT NOT NULL REFERENCES workflow_versions (workflow_version_id),
    status              TEXT NOT NULL,
    opened_at           TIMESTAMPTZ NOT NULL,
    completed_at        TIMESTAMPTZ,
    linked_case_id      TEXT REFERENCES cases (case_id),   -- a correction opens a linked new case (P02-TEST-11)
    version             INT NOT NULL DEFAULT 1             -- optimistic-concurrency counter for commands
);

CREATE TABLE IF NOT EXISTS step_instances (
    step_instance_id   TEXT PRIMARY KEY,
    case_id            TEXT NOT NULL REFERENCES cases (case_id),
    step_definition_id TEXT NOT NULL REFERENCES step_definitions (step_definition_id),
    status             TEXT NOT NULL,
    version_number     INT NOT NULL DEFAULT 1,
    ready_at           TIMESTAMPTZ,
    started_at         TIMESTAMPTZ,
    approved_at        TIMESTAMPTZ,
    UNIQUE (case_id, step_definition_id)
);

-- ended_at NULL means the assignment is open; reassignment closes it and never deletes it (D-03).
CREATE TABLE IF NOT EXISTS assignments (
    assignment_id    TEXT PRIMARY KEY,
    step_instance_id TEXT NOT NULL REFERENCES step_instances (step_instance_id),
    assignee_id      TEXT NOT NULL,
    assigned_at      TIMESTAMPTZ NOT NULL,
    ended_at         TIMESTAMPTZ
);

-- Append-only (trigger in 0002): a resubmission is a new row; a review is a row of document_reviews.
-- review_status holds the status at the time of insertion.
CREATE TABLE IF NOT EXISTS document_versions (
    document_version_id TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases (case_id),
    document_type       TEXT NOT NULL,
    version_number      INT NOT NULL,
    content_hash        TEXT NOT NULL,                -- synthetic placeholder, never a real file (P02-FLOW-02)
    review_status       TEXT NOT NULL,
    submitted_at        TIMESTAMPTZ NOT NULL,
    reviewed_at         TIMESTAMPTZ,
    UNIQUE (case_id, document_type, version_number)
);

CREATE TABLE IF NOT EXISTS document_reviews (
    review_id           TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions (document_version_id),
    decision            TEXT NOT NULL,
    reason              TEXT,
    reviewer_id         TEXT NOT NULL,
    decided_at          TIMESTAMPTZ NOT NULL
);

-- UNIQUE (step_instance_id, version_number) is what makes a second decision on a step version a DECISION_CONFLICT.
CREATE TABLE IF NOT EXISTS approvals (
    approval_id      TEXT PRIMARY KEY,
    step_instance_id TEXT NOT NULL REFERENCES step_instances (step_instance_id),
    reviewer_id      TEXT NOT NULL,
    decision         TEXT NOT NULL,
    decided_at       TIMESTAMPTZ NOT NULL,
    reason           TEXT,
    version_number   INT NOT NULL DEFAULT 1,
    UNIQUE (step_instance_id, version_number)
);

CREATE TABLE IF NOT EXISTS waiting_intervals (
    waiting_interval_id TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases (case_id),
    reason_code         TEXT NOT NULL,
    starts_at           TIMESTAMPTZ NOT NULL,
    ends_at             TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS case_events (
    event_id    TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases (case_id),
    event_type  TEXT NOT NULL,
    actor_id    TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);

-- Operational tables (as in Revenue Atlas) ------------------------------------------------------

CREATE TABLE IF NOT EXISTS raw_batches (
    batch_id        TEXT PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash    TEXT NOT NULL,
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_records (
    entity      TEXT NOT NULL,
    id          TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_row     JSONB NOT NULL,
    batch_id    TEXT NOT NULL REFERENCES raw_batches (batch_id),
    PRIMARY KEY (batch_id, entity, id, reason_code)
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
