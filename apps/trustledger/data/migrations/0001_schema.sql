-- TrustLedger schema, contract v1 (docs/contracts.md D-01..D-06). Idempotent: every statement is IF NOT EXISTS.
-- Instants are TIMESTAMPTZ (UTC). Proportions are never stored (derived by the metrics). Constraints, append-only triggers and the
-- helper functions live in 0002_constraints.sql.

-- The IANA zone names this server knows (a copy of pg_timezone_names, which scans the zone files on every read).
CREATE TABLE IF NOT EXISTS tl_timezones (name TEXT PRIMARY KEY);
INSERT INTO tl_timezones (name) SELECT name FROM pg_timezone_names ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS owners (
    owner_id       TEXT PRIMARY KEY,
    owner_name     TEXT NOT NULL,
    team           TEXT NOT NULL,
    role           TEXT NOT NULL,
    active         BOOLEAN NOT NULL,
    deactivated_at TIMESTAMPTZ
);

-- A dataset is registered only with an owner and a classification (D-02). The schedule fields were added by D-06.
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id            TEXT PRIMARY KEY,
    dataset_name          TEXT NOT NULL,
    source_system         TEXT NOT NULL,
    owner_id              TEXT NOT NULL REFERENCES owners (owner_id),
    classification        TEXT NOT NULL,
    registered_at         TIMESTAMPTZ NOT NULL,
    monitored             BOOLEAN NOT NULL,
    refresh_timezone      TEXT,
    refresh_local_time    TEXT,                      -- HH:MM on the dataset's own clock
    refresh_grace_minutes INT,
    last_refreshed_at     TIMESTAMPTZ,
    registered_by         TEXT
);

CREATE TABLE IF NOT EXISTS fields (
    field_id   TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets (dataset_id),
    field_name TEXT NOT NULL,
    data_type  TEXT NOT NULL,
    nullable   BOOLEAN NOT NULL
);

-- The measured rows of a dataset, as loaded (append-only). ``data`` is one flat JSON object of text, integer, boolean or null.
CREATE TABLE IF NOT EXISTS dataset_rows (
    dataset_id TEXT NOT NULL REFERENCES datasets (dataset_id),
    ordinal    INT NOT NULL,
    row_id     TEXT NOT NULL,
    data       JSONB NOT NULL,
    PRIMARY KEY (dataset_id, ordinal)
);

-- One current row per rule; a rule's runs name the rule_version they were made under. Only status, disabled_at and disabled_reason
-- ever change (active -> disabled, once); the history stays.
CREATE TABLE IF NOT EXISTS quality_rules (
    rule_id         TEXT PRIMARY KEY,
    dataset_id      TEXT NOT NULL REFERENCES datasets (dataset_id),
    field_id        TEXT REFERENCES fields (field_id),
    rule_type       TEXT NOT NULL,
    severity        TEXT NOT NULL,
    version_number  INT NOT NULL,
    status          TEXT NOT NULL,
    disabled_at     TIMESTAMPTZ,
    disabled_reason TEXT,
    definition      JSONB NOT NULL
);

-- Rule weight versions and checklist versions are never edited: a change is a new version (P07-TEST-05).
CREATE TABLE IF NOT EXISTS rule_weight_versions (
    weight_version TEXT PRIMARY KEY,
    valid_from     TIMESTAMPTZ NOT NULL,
    weights        JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist_versions (
    checklist_version TEXT PRIMARY KEY,
    items             JSONB NOT NULL
);

-- One row: the configuration the fixture travels with.
CREATE TABLE IF NOT EXISTS ledger_config (
    id                INT PRIMARY KEY,
    whitespace_policy JSONB NOT NULL,
    checklist_version TEXT NOT NULL,
    probes            JSONB NOT NULL
);

-- Append-only. A scheduled run measures the rule; a rerun re-checks the records of one issue. ``details`` carries populated_count,
-- null_fk_count and the failing record ids.
CREATE TABLE IF NOT EXISTS rule_runs (
    rule_run_id      TEXT PRIMARY KEY,
    rule_id          TEXT NOT NULL REFERENCES quality_rules (rule_id),
    rule_version     INT NOT NULL,
    weight_version   TEXT NOT NULL REFERENCES rule_weight_versions (weight_version),
    kind             TEXT NOT NULL,
    run_at           TIMESTAMPTZ NOT NULL,
    eligible_count   INT NOT NULL,
    failure_count    INT NOT NULL,
    rerun_for_issue  TEXT,
    details          JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_by           TEXT
);

CREATE TABLE IF NOT EXISTS issues (
    issue_id             TEXT PRIMARY KEY,
    rule_run_id          TEXT NOT NULL REFERENCES rule_runs (rule_run_id),
    severity             TEXT NOT NULL,
    owner_id             TEXT NOT NULL REFERENCES owners (owner_id),
    status               TEXT NOT NULL,
    detected_at          TIMESTAMPTZ NOT NULL,
    due_at               TIMESTAMPTZ,
    closed_at            TIMESTAMPTZ,
    verification_run_id  TEXT REFERENCES rule_runs (rule_run_id),
    reopened_at          TIMESTAMPTZ[] NOT NULL DEFAULT '{}',
    record_ids           JSONB,
    version              INT NOT NULL DEFAULT 1
);

-- The lifecycle of an issue, append-only: detected, triaged, claimed, verified, verification_failed, reopened.
CREATE TABLE IF NOT EXISTS issue_events (
    event_id    TEXT PRIMARY KEY,
    issue_id    TEXT NOT NULL REFERENCES issues (issue_id),
    event_type  TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor_id    TEXT,
    details     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS lineage_edges (
    edge_id           TEXT PRIMARY KEY,
    source_dataset_id TEXT NOT NULL REFERENCES datasets (dataset_id),
    target_dataset_id TEXT NOT NULL REFERENCES datasets (dataset_id),
    evidence_type     TEXT NOT NULL,
    observed_at       TIMESTAMPTZ
);

-- A published definition is never rewritten: a change is a new version row (valid_from) plus a definition_changes row.
CREATE TABLE IF NOT EXISTS metric_versions (
    metric_version_id TEXT PRIMARY KEY,
    metric_id         TEXT NOT NULL,
    metric_name       TEXT NOT NULL,
    version_number    INT NOT NULL,
    definition        TEXT,
    grain             TEXT,
    source_fields     JSONB,
    owner_id          TEXT,
    refresh           TEXT,
    valid_from        TIMESTAMPTZ NOT NULL,
    status            TEXT NOT NULL,
    published_by      TEXT
);

CREATE TABLE IF NOT EXISTS definition_changes (
    change_id                 TEXT PRIMARY KEY,
    metric_version_id         TEXT NOT NULL REFERENCES metric_versions (metric_version_id),
    previous_metric_version_id TEXT REFERENCES metric_versions (metric_version_id),
    reason                    TEXT NOT NULL,
    approved_by               TEXT NOT NULL,
    changed_at                TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_records (
    record_id          TEXT PRIMARY KEY,
    source_system      TEXT NOT NULL,
    source_customer_id TEXT NOT NULL,
    normalized_name    TEXT NOT NULL,
    address_key        TEXT NOT NULL
);

-- A pair is stored once, in canonical order (left < right in code-point order); the reverse pair cannot be stored.
CREATE TABLE IF NOT EXISTS match_candidates (
    candidate_id    TEXT PRIMARY KEY,
    left_record_id  TEXT NOT NULL REFERENCES customer_records (record_id),
    right_record_id TEXT NOT NULL REFERENCES customer_records (record_id),
    score           NUMERIC(7,6) NOT NULL,
    features        JSONB NOT NULL,
    explanation     TEXT NOT NULL,
    uncertainty     TEXT,
    proposed_by     TEXT NOT NULL,
    proposed_at     TIMESTAMPTZ NOT NULL
);

-- Append-only human decisions. A merge maps the right record to the left; a reversal is a decision that names the approval it
-- reverses, so the mapping history is kept and both identities are restored.
CREATE TABLE IF NOT EXISTS merge_decisions (
    merge_id          TEXT PRIMARY KEY,
    candidate_id      TEXT NOT NULL REFERENCES match_candidates (candidate_id),
    reviewer_id       TEXT NOT NULL,
    decision          TEXT NOT NULL,
    decided_at        TIMESTAMPTZ NOT NULL,
    reverses_merge_id TEXT REFERENCES merge_decisions (merge_id),
    reason            TEXT
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

CREATE INDEX IF NOT EXISTS rule_runs_rule_idx       ON rule_runs (rule_id, run_at);
CREATE INDEX IF NOT EXISTS issues_run_idx           ON issues (rule_run_id);
CREATE INDEX IF NOT EXISTS issue_events_issue_idx   ON issue_events (issue_id, occurred_at);
CREATE INDEX IF NOT EXISTS dataset_rows_row_idx     ON dataset_rows (dataset_id, row_id);
CREATE INDEX IF NOT EXISTS metric_versions_idx      ON metric_versions (metric_id, version_number);
CREATE INDEX IF NOT EXISTS merge_decisions_cand_idx ON merge_decisions (candidate_id);
CREATE INDEX IF NOT EXISTS audit_entity_idx         ON audit_events (entity_type, entity_id, occurred_at);
