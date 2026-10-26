-- ProductSignal schema, contract v1 (docs/contracts.md D-01..D-05). Idempotent: every statement is IF NOT EXISTS.
-- Instants are TIMESTAMPTZ (UTC); amounts NUMERIC(14,2) (USD, never float); proportions are never stored (derived).
-- Constraints, append-only triggers and helper functions live in 0002_constraints.sql.

-- The IANA zone names this server knows (a copy of pg_timezone_names: the view scans the zone files on every read, which makes a
-- CHECK on it far too slow for a bulk load). ps_valid_tz() looks a name up here.
CREATE TABLE IF NOT EXISTS ps_timezones (
    name TEXT PRIMARY KEY
);
INSERT INTO ps_timezones (name) SELECT name FROM pg_timezone_names ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    plan       TEXT NOT NULL,
    segment    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    internal   BOOLEAN NOT NULL,
    timezone   TEXT NOT NULL                       -- IANA name (D-P6-2): the account's calendar for day-7 / week-4 retention
);

CREATE TABLE IF NOT EXISTS users (
    user_id    TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts (account_id),
    created_at TIMESTAMPTZ NOT NULL,
    timezone   TEXT NOT NULL,
    bot_flag   BOOLEAN NOT NULL
);

-- The earliest link of an anonymous_id fixes its user; it attributes only events at or after linked_at (D-01).
CREATE TABLE IF NOT EXISTS identity_links (
    identity_link_id TEXT PRIMARY KEY,
    anonymous_id     TEXT NOT NULL,
    user_id          TEXT NOT NULL REFERENCES users (user_id),
    linked_at        TIMESTAMPTZ NOT NULL,
    rule_version     TEXT NOT NULL,
    created_by       TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users (user_id),
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    device_type TEXT NOT NULL
);

-- The immutable event log. user_id and anonymous_id carry no foreign key: an event of an unknown identity is logged and
-- excluded from every figure (D-01); a re-sent event under another event_id is logged and dropped as a duplicate per run.
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    user_id      TEXT,
    anonymous_id TEXT,
    event_name   TEXT NOT NULL,
    event_at     TIMESTAMPTZ NOT NULL,              -- the business instant
    received_at  TIMESTAMPTZ NOT NULL,              -- when the log accepted it: a run at cutoff C uses received_at <= C
    ingested_by  TEXT
);

CREATE TABLE IF NOT EXISTS event_properties (
    property_id    TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL REFERENCES events (event_id),
    property_key   TEXT NOT NULL,
    property_value TEXT NOT NULL,
    value_type     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts (account_id),
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ,
    status          TEXT NOT NULL,
    amount_usd      NUMERIC(14,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS experiment_versions (
    experiment_version_id TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    unit_type             TEXT NOT NULL,
    primary_metric        TEXT NOT NULL,
    planned_end           TIMESTAMPTZ NOT NULL
);

-- The frozen analysis plan (C06): written once, before any outcome is read; config_hash = sha256 of the compact key-sorted
-- JSON of ``plan`` (the plan without its hash). ``plan`` is the plan as frozen, frozen_at included.
-- No foreign key: a plan is configuration and may exist before the version has any data; C06 checks the version exists.
CREATE TABLE IF NOT EXISTS analysis_plans (
    experiment_version_id TEXT PRIMARY KEY,
    plan                  JSONB NOT NULL,
    config_hash           TEXT NOT NULL,
    frozen_at             TIMESTAMPTZ NOT NULL,
    frozen_by             TEXT
);

CREATE TABLE IF NOT EXISTS assignments (
    assignment_id         TEXT PRIMARY KEY,
    experiment_version_id TEXT NOT NULL REFERENCES experiment_versions (experiment_version_id),
    unit_id               TEXT NOT NULL REFERENCES accounts (account_id),
    variant               TEXT NOT NULL,
    assigned_at           TIMESTAMPTZ NOT NULL,
    created_by            TEXT
);

CREATE TABLE IF NOT EXISTS exposures (
    exposure_id   TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL REFERENCES assignments (assignment_id),
    exposed_at    TIMESTAMPTZ NOT NULL,
    surface       TEXT NOT NULL,
    event_id      TEXT,
    created_by    TEXT
);

CREATE TABLE IF NOT EXISTS metric_observations (
    observation_id TEXT PRIMARY KEY,
    assignment_id  TEXT NOT NULL REFERENCES assignments (assignment_id),
    metric_name    TEXT NOT NULL,
    value          TEXT NOT NULL,
    window_end     TIMESTAMPTZ NOT NULL
);

-- Every analysis run is logged (C08). Seeded runs carry the core columns; runs made by the API also carry the result they
-- published, which never changes (a late event changes only a later run).
CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_id           TEXT PRIMARY KEY,
    experiment_version_id TEXT NOT NULL REFERENCES experiment_versions (experiment_version_id),
    cutoff_at             TIMESTAMPTZ NOT NULL,
    config_hash           TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by            TEXT,
    interim               BOOLEAN,
    srm_verdict           TEXT,
    conclusive            BOOLEAN,
    prior_runs            INT,
    result                JSONB
);

CREATE TABLE IF NOT EXISTS funnel_definitions (
    definition_id TEXT NOT NULL,
    version       INT NOT NULL,
    steps         TEXT[] NOT NULL,
    max_gap_hours INT NOT NULL,
    window_from   TIMESTAMPTZ NOT NULL,
    window_to     TIMESTAMPTZ NOT NULL,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (definition_id, version)
);

-- One row: the metric windows the dataset travels with (the funnel's window lives on its definition).
CREATE TABLE IF NOT EXISTS metric_config (
    id      INT PRIMARY KEY,
    windows JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS guardrail_reviews (
    review_id             TEXT PRIMARY KEY,
    analysis_id           TEXT NOT NULL REFERENCES analysis_runs (analysis_id),
    experiment_version_id TEXT NOT NULL REFERENCES experiment_versions (experiment_version_id),
    verdict               TEXT NOT NULL,
    result                JSONB NOT NULL,
    reviewed_by           TEXT NOT NULL,
    reviewed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id           TEXT PRIMARY KEY,
    experiment_version_id TEXT NOT NULL REFERENCES experiment_versions (experiment_version_id),
    analysis_id           TEXT NOT NULL REFERENCES analysis_runs (analysis_id),
    review_id             TEXT NOT NULL REFERENCES guardrail_reviews (review_id),
    decision              TEXT NOT NULL,
    basis                 TEXT NOT NULL DEFAULT 'primary',
    rationale             TEXT NOT NULL,
    decided_by            TEXT NOT NULL,
    decided_role          TEXT NOT NULL,
    decided_at            TIMESTAMPTZ NOT NULL,
    evidence              JSONB NOT NULL DEFAULT '{}'::jsonb
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
    event_id              TEXT PRIMARY KEY,
    entity_type           TEXT NOT NULL,
    entity_id             TEXT NOT NULL,
    experiment_version_id TEXT,
    action                TEXT NOT NULL,
    actor_id              TEXT NOT NULL,
    occurred_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    before_version        INT,
    after_version         INT,
    reason                TEXT,
    request_id            TEXT,
    details               JSONB NOT NULL DEFAULT '{}'::jsonb
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
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Two-sided 95 % Student t quantiles for df = 1..N generated by Python at fixed precision (data/sql/t_quantiles.csv, made by
-- data/sql/generate_t_quantiles.py): the SQL reference cannot reproduce the t quantile series, so it reads this table.
CREATE TABLE IF NOT EXISTS t_critical_975 (
    df INT PRIMARY KEY,
    t  NUMERIC(30,20) NOT NULL
);

CREATE INDEX IF NOT EXISTS events_name_at_idx    ON events (event_name, event_at);
CREATE INDEX IF NOT EXISTS events_user_idx       ON events (user_id);
CREATE INDEX IF NOT EXISTS events_anon_idx       ON events (anonymous_id);
CREATE INDEX IF NOT EXISTS events_received_idx   ON events (received_at);
CREATE INDEX IF NOT EXISTS event_props_event_idx ON event_properties (event_id);
CREATE INDEX IF NOT EXISTS links_anon_idx        ON identity_links (anonymous_id, linked_at);
CREATE INDEX IF NOT EXISTS sessions_user_idx     ON sessions (user_id, started_at);
CREATE INDEX IF NOT EXISTS users_account_idx     ON users (account_id);
CREATE INDEX IF NOT EXISTS assignments_unit_idx  ON assignments (unit_id);
CREATE INDEX IF NOT EXISTS subscriptions_acct_idx ON subscriptions (account_id, starts_at);
CREATE INDEX IF NOT EXISTS runs_version_idx      ON analysis_runs (experiment_version_id, created_at);
CREATE INDEX IF NOT EXISTS audit_entity_idx      ON audit_events (entity_type, entity_id, occurred_at);
