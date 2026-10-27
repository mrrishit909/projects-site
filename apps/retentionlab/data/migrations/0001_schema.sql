-- RetentionLab schema, contract v1 (docs/contracts.md D-01..D-05). Idempotent: every statement is IF NOT EXISTS.
-- Instants are TIMESTAMPTZ (UTC). Money is NUMERIC(20,6); probabilities and model parameters are NUMERIC(20,6) too (they are 6-place
-- decimal strings in the API and are never stored as floating point). Constraints, append-only triggers and the helper functions
-- live in 0002_constraints.sql; the audit, idempotency and rejection tables are at the end.

CREATE TABLE IF NOT EXISTS label_versions (
    label_version_id TEXT PRIMARY KEY,
    horizon_days     INT NOT NULL CHECK (horizon_days > 0),
    grace_days       INT NOT NULL CHECK (grace_days >= 0)
);

CREATE TABLE IF NOT EXISTS feature_versions (
    feature_version  TEXT PRIMARY KEY,
    observation_days INT NOT NULL CHECK (observation_days > 0)
);

-- The feature registry (D-01): every feature, its source entity and window; post_outcome / latent / id_derived fields can never be features.
CREATE TABLE IF NOT EXISTS feature_registry (
    feature_name   TEXT NOT NULL,
    feature_version TEXT NOT NULL REFERENCES feature_versions (feature_version),
    source_entity  TEXT NOT NULL,
    window_days    INT CHECK (window_days IS NULL OR window_days > 0),
    post_outcome   BOOLEAN NOT NULL DEFAULT false,
    latent         BOOLEAN NOT NULL DEFAULT false,
    id_derived     BOOLEAN NOT NULL DEFAULT false,
    lineage        TEXT NOT NULL,
    PRIMARY KEY (feature_version, feature_name)
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id BIGINT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    segment    TEXT NOT NULL,
    region     TEXT NOT NULL,
    synthetic  BOOLEAN NOT NULL CHECK (synthetic IS TRUE)       -- D-04: always true
);

-- The four event sources. An event is known at ``available_at``, never before it happened.
CREATE TABLE IF NOT EXISTS subscription_events (
    subscription_event_id TEXT PRIMARY KEY,
    account_id   BIGINT NOT NULL REFERENCES accounts (account_id),
    event_type   TEXT NOT NULL CHECK (event_type IN ('start', 'renew', 'cancel')),
    event_at     TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT subscription_events_availability CHECK (available_at >= event_at)
);

CREATE TABLE IF NOT EXISTS billing_events (
    billing_event_id TEXT PRIMARY KEY,
    account_id   BIGINT NOT NULL REFERENCES accounts (account_id),
    amount       NUMERIC(20,6) NOT NULL,
    event_at     TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT billing_events_availability CHECK (available_at >= event_at)
);

CREATE TABLE IF NOT EXISTS usage_events (
    usage_event_id TEXT PRIMARY KEY,
    account_id   BIGINT NOT NULL REFERENCES accounts (account_id),
    event_name   TEXT NOT NULL,
    event_at     TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT usage_events_availability CHECK (available_at >= event_at)
);

CREATE TABLE IF NOT EXISTS support_events (
    support_event_id TEXT PRIMARY KEY,
    account_id   BIGINT NOT NULL REFERENCES accounts (account_id),
    severity     TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    event_at     TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT support_events_availability CHECK (available_at >= event_at)
);

CREATE TABLE IF NOT EXISTS prediction_cutoffs (
    cutoff_id         TEXT PRIMARY KEY,
    account_id        BIGINT NOT NULL REFERENCES accounts (account_id),
    prediction_at     TIMESTAMPTZ NOT NULL,
    horizon_end       TIMESTAMPTZ NOT NULL,
    observation_start TIMESTAMPTZ NOT NULL,
    CONSTRAINT cutoff_order CHECK (observation_start < prediction_at AND prediction_at < horizon_end),
    CONSTRAINT cutoff_account_instant_uq UNIQUE (account_id, prediction_at)
);

-- Eligible rows only. ``max_available_at`` is the largest available_at used: it is strictly before the cutoff (trigger).
CREATE TABLE IF NOT EXISTS feature_rows (
    feature_row_id  TEXT PRIMARY KEY,
    cutoff_id       TEXT NOT NULL REFERENCES prediction_cutoffs (cutoff_id),
    feature_version TEXT NOT NULL REFERENCES feature_versions (feature_version),
    features_json   JSONB NOT NULL,
    max_available_at TIMESTAMPTZ,
    CONSTRAINT feature_rows_cutoff_version_uq UNIQUE (cutoff_id, feature_version)
);

-- ``churned`` is NULL while the label window is immature (censored): never false (D-01).
CREATE TABLE IF NOT EXISTS labels (
    label_id  TEXT PRIMARY KEY,
    cutoff_id TEXT NOT NULL UNIQUE REFERENCES prediction_cutoffs (cutoff_id),
    churned   BOOLEAN,
    label_end TIMESTAMPTZ NOT NULL,
    mature    BOOLEAN NOT NULL,
    CONSTRAINT labels_censored_is_null CHECK (mature OR churned IS NULL),
    CONSTRAINT labels_mature_is_known CHECK (NOT mature OR churned IS NOT NULL)
);

-- ``config`` holds the frozen run configuration as strings (D-P10-17); config_hash is the SHA-256 of its canonical JSON.
CREATE TABLE IF NOT EXISTS training_runs (
    training_run_id TEXT PRIMARY KEY,
    train_end       TIMESTAMPTZ NOT NULL,
    validation_end  TIMESTAMPTZ NOT NULL,
    test_end        TIMESTAMPTZ NOT NULL,
    config          JSONB NOT NULL,
    config_hash     TEXT NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    created_at      TIMESTAMPTZ,
    created_by      TEXT,
    CONSTRAINT training_runs_order CHECK (train_end < validation_end AND validation_end < test_end)
);

-- Model artefacts as queryable numbers (the config keeps the same values as strings): the fitted preprocessing, the coefficients,
-- the Platt mapping. They are rewritten only while the run has no prediction (trigger).
CREATE TABLE IF NOT EXISTS model_preprocessing (
    training_run_id TEXT NOT NULL REFERENCES training_runs (training_run_id),
    feature_name    TEXT NOT NULL,
    median          NUMERIC(20,6) NOT NULL,
    mean            NUMERIC(20,6) NOT NULL,
    std             NUMERIC(20,6) NOT NULL CHECK (std > 0),
    missing_in_fit  INT NOT NULL CHECK (missing_in_fit >= 0),
    missing_indicator BOOLEAN NOT NULL,
    PRIMARY KEY (training_run_id, feature_name)
);

CREATE TABLE IF NOT EXISTS model_coefficients (
    training_run_id TEXT NOT NULL REFERENCES training_runs (training_run_id),
    model_name      TEXT NOT NULL CHECK (model_name IN ('random_baseline', 'business_rule', 'logistic_regression')),
    term            TEXT NOT NULL,
    value           NUMERIC(20,6) NOT NULL,
    PRIMARY KEY (training_run_id, model_name, term)
);

CREATE TABLE IF NOT EXISTS calibration_maps (
    training_run_id TEXT PRIMARY KEY REFERENCES training_runs (training_run_id),
    method          TEXT NOT NULL CHECK (method = 'platt'),
    a               NUMERIC(20,6) NOT NULL,
    b               NUMERIC(20,6) NOT NULL,
    fit_rows        INT NOT NULL CHECK (fit_rows > 0)
);

CREATE TABLE IF NOT EXISTS split_assignments (
    assignment_id   TEXT PRIMARY KEY,
    training_run_id TEXT NOT NULL REFERENCES training_runs (training_run_id),
    cutoff_id       TEXT NOT NULL REFERENCES prediction_cutoffs (cutoff_id),
    split           TEXT NOT NULL CHECK (split IN ('train', 'validation', 'test', 'outside')),
    status          TEXT NOT NULL CHECK (status IN ('retained', 'dropped')),
    drop_reason     TEXT CHECK (drop_reason IN ('LABEL_WINDOW', 'GROUP_TEST', 'GROUP_VALIDATION')),
    CONSTRAINT split_assignment_uq UNIQUE (training_run_id, cutoff_id),
    CONSTRAINT split_drop_reason CHECK ((status = 'dropped') = (drop_reason IS NOT NULL))
);

-- model_name: which model made the prediction (the fixture's predictions are the run's scoring model, the calibrated logistic one).
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id   TEXT PRIMARY KEY,
    training_run_id TEXT NOT NULL REFERENCES training_runs (training_run_id),
    cutoff_id       TEXT NOT NULL REFERENCES prediction_cutoffs (cutoff_id),
    model_name      TEXT NOT NULL DEFAULT 'logistic_regression' CHECK (model_name IN ('random_baseline', 'business_rule', 'logistic_regression')),
    probability     NUMERIC(20,6) NOT NULL CHECK (probability >= 0 AND probability <= 1),
    scored_at       TIMESTAMPTZ NOT NULL,
    config_hash     TEXT NOT NULL,
    feature_version TEXT NOT NULL REFERENCES feature_versions (feature_version),
    label_version   TEXT NOT NULL REFERENCES label_versions (label_version_id),
    CONSTRAINT predictions_run_cutoff_model_uq UNIQUE (training_run_id, cutoff_id, model_name)
);

CREATE TABLE IF NOT EXISTS scoring_publications (
    publication_id  TEXT PRIMARY KEY,
    training_run_id TEXT NOT NULL REFERENCES training_runs (training_run_id),
    model_name      TEXT NOT NULL DEFAULT 'logistic_regression' CHECK (model_name IN ('random_baseline', 'business_rule', 'logistic_regression')),
    prediction_at   TIMESTAMPTZ NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('completed', 'incomplete'))
);

-- Assumptions of a what-if (D-03). Immutable: an edit is a new scenario_id.
CREATE TABLE IF NOT EXISTS intervention_scenarios (
    scenario_id    TEXT PRIMARY KEY,
    capacity       INT NOT NULL CHECK (capacity >= 1),
    contact_cost   NUMERIC(20,6) NOT NULL CHECK (contact_cost >= 0),
    assumed_effect NUMERIC(20,6) NOT NULL CHECK (assumed_effect >= 0 AND assumed_effect <= 1),
    margin_value   NUMERIC(20,6) NOT NULL CHECK (margin_value >= 0),
    selected_on    TEXT NOT NULL DEFAULT 'validation' CHECK (selected_on = 'validation'),   -- K is chosen on validation, never on test (P10-TEST-06)
    created_at     TIMESTAMPTZ,
    created_by     TEXT
);

-- The outreach queue: DRAFT only, nothing is ever sent (D-03). training_run_id / prediction_at / queue_rank are set by C08.
CREATE TABLE IF NOT EXISTS outreach_events (
    outreach_event_id TEXT PRIMARY KEY,
    account_id      BIGINT NOT NULL REFERENCES accounts (account_id),
    scenario_id     TEXT NOT NULL REFERENCES intervention_scenarios (scenario_id),
    action          TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status = 'draft'),
    training_run_id TEXT REFERENCES training_runs (training_run_id),
    prediction_at   TIMESTAMPTZ,
    queue_rank      INT CHECK (queue_rank IS NULL OR queue_rank >= 1),
    created_at      TIMESTAMPTZ,
    CONSTRAINT outreach_scenario_account_uq UNIQUE (scenario_id, account_id)
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

-- The idempotency record: bound to the actor id, the role and the payload hash (which includes the dataset_version).
CREATE TABLE IF NOT EXISTS command_results (
    idempotency_key TEXT PRIMARY KEY,
    payload_hash    TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    actor_role      TEXT NOT NULL CHECK (actor_role IN ('scientist', 'analyst', 'admin')),
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

CREATE INDEX IF NOT EXISTS subscription_events_acct_idx ON subscription_events (account_id, event_at);
CREATE INDEX IF NOT EXISTS billing_events_acct_idx      ON billing_events (account_id, event_at);
CREATE INDEX IF NOT EXISTS usage_events_acct_idx        ON usage_events (account_id, event_at);
CREATE INDEX IF NOT EXISTS support_events_acct_idx      ON support_events (account_id, event_at);
CREATE INDEX IF NOT EXISTS cutoffs_prediction_idx       ON prediction_cutoffs (prediction_at, account_id);
CREATE INDEX IF NOT EXISTS predictions_run_idx          ON predictions (training_run_id, cutoff_id);
CREATE INDEX IF NOT EXISTS audit_entity_idx             ON audit_events (entity_type, entity_id, occurred_at);
