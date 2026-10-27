-- ChangeWorks schema, contract v1 (docs/contracts.md D-01..D-05). PostgreSQL 16. Idempotent: every statement is IF NOT EXISTS.
-- Money is NUMERIC(20,6) (JSON shows 2 places or more, never fewer); proportions are NUMERIC(7,6); instants are TIMESTAMPTZ (UTC).
-- Constraints, append-only triggers and helper functions live in 0002_constraints.sql.

-- One row: how this dataset counts periods (D-04) and the as_of it was loaded for.
CREATE TABLE IF NOT EXISTS dataset_config (
    id           INT PRIMARY KEY,
    period_basis TEXT NOT NULL,
    period_start DATE NOT NULL,
    as_of        TIMESTAMPTZ
);

-- A mutable operational row (optimistic ``version``): status, the approved baseline_version and the requested schedule may change; identity may not.
CREATE TABLE IF NOT EXISTS initiatives (
    initiative_id            TEXT PRIMARY KEY,
    title                    TEXT NOT NULL,
    sponsor_id               TEXT NOT NULL,
    status                   TEXT NOT NULL,
    baseline_version         TEXT,
    requested_start_period   INT NOT NULL,
    duration_periods         INT NOT NULL,
    deployment_period        INT NOT NULL,
    eligibility_rule_version TEXT NOT NULL,
    version                  INT NOT NULL DEFAULT 1,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by               TEXT NOT NULL DEFAULT 'seed'
);

-- Evidence (measured), never assumptions. One row per (initiative, baseline_version); append-only; a correction is a new version with a reason.
CREATE TABLE IF NOT EXISTS process_baselines (
    baseline_id      TEXT PRIMARY KEY,
    initiative_id    TEXT NOT NULL REFERENCES initiatives (initiative_id),
    baseline_version TEXT NOT NULL,
    volume           BIGINT NOT NULL,
    minutes_per_case INT NOT NULL,
    error_rate       NUMERIC(7,6) NOT NULL,
    evidence_ref     TEXT NOT NULL,
    measured_at      TIMESTAMPTZ NOT NULL,
    reason           TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       TEXT NOT NULL DEFAULT 'seed',
    CONSTRAINT process_baselines_version_uq UNIQUE (initiative_id, baseline_version)
);

-- Approval (sponsor, admin) names the approved set and freezes it. Append-only history of every approved version.
CREATE TABLE IF NOT EXISTS baseline_approvals (
    approval_id      TEXT PRIMARY KEY,
    initiative_id    TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    approved_by      TEXT NOT NULL,
    approved_at      TIMESTAMPTZ NOT NULL,
    reason           TEXT,
    CONSTRAINT baseline_approvals_version_uq UNIQUE (initiative_id, baseline_version),
    CONSTRAINT baseline_approvals_baseline_fk FOREIGN KEY (initiative_id, baseline_version) REFERENCES process_baselines (initiative_id, baseline_version)
);

-- The approved set an initiative points to must have been approved (checked at commit, so a load can insert both sides in one transaction).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'initiatives_approved_baseline_fk') THEN
        ALTER TABLE initiatives ADD CONSTRAINT initiatives_approved_baseline_fk FOREIGN KEY (initiative_id, baseline_version)
            REFERENCES baseline_approvals (initiative_id, baseline_version) DEFERRABLE INITIALLY DEFERRED;
    END IF;
END
$$;

-- Assumptions, versioned 1..n per (initiative, name); append-only. ``value`` keeps its text (a minutes target "8" stays "8").
CREATE TABLE IF NOT EXISTS assumption_versions (
    assumption_id                 TEXT PRIMARY KEY,
    initiative_id                 TEXT REFERENCES initiatives (initiative_id),
    name                          TEXT NOT NULL,
    version_number                INT NOT NULL,
    value                         TEXT,
    value_list                    JSONB,
    unit                          TEXT,
    rationale                     TEXT NOT NULL,
    author_id                     TEXT NOT NULL,
    evidence_ref                  TEXT,
    staffing_change_evidence_ref  TEXT,
    created_at                    TIMESTAMPTZ NOT NULL,
    CONSTRAINT assumption_versions_version_uq UNIQUE NULLS NOT DISTINCT (initiative_id, name, version_number)
);

CREATE TABLE IF NOT EXISTS opportunity_scores (
    score_id        TEXT PRIMARY KEY,
    initiative_id   TEXT NOT NULL REFERENCES initiatives (initiative_id),
    version_number  INT NOT NULL,
    criteria        JSONB NOT NULL,
    weighted_score  NUMERIC(10,4) NOT NULL,
    weighted_exact  TEXT NOT NULL,
    rationale       TEXT NOT NULL,
    author_id       TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    CONSTRAINT opportunity_scores_version_uq UNIQUE (initiative_id, version_number)
);

CREATE TABLE IF NOT EXISTS resources (
    resource_id         TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    capacity_per_period NUMERIC(20,6) NOT NULL,
    unit                TEXT NOT NULL
);

-- A scenario version is immutable: an edit is a new scenario_id. Only draft -> proposed (C07) ever changes a row.
CREATE TABLE IF NOT EXISTS scenario_versions (
    scenario_id                   TEXT PRIMARY KEY,
    baseline_version              TEXT NOT NULL,
    discount_rate                 NUMERIC(7,6) NOT NULL,
    rate_basis                    TEXT NOT NULL,
    rate_conversion_assumption_id TEXT REFERENCES assumption_versions (assumption_id),
    horizon_periods               INT NOT NULL,
    status                        TEXT NOT NULL,
    created_at                    TIMESTAMPTZ NOT NULL,
    created_by                    TEXT NOT NULL DEFAULT 'seed',
    proposed_at                   TIMESTAMPTZ,
    proposed_by                   TEXT,
    comparison                    JSONB,
    residual_explanation          TEXT
);

CREATE TABLE IF NOT EXISTS scenario_initiatives (
    scenario_id   TEXT NOT NULL REFERENCES scenario_versions (scenario_id),
    initiative_id TEXT NOT NULL REFERENCES initiatives (initiative_id),
    PRIMARY KEY (scenario_id, initiative_id)
);

CREATE TABLE IF NOT EXISTS scenario_pins (
    scenario_id   TEXT NOT NULL REFERENCES scenario_versions (scenario_id),
    assumption_id TEXT NOT NULL REFERENCES assumption_versions (assumption_id),
    PRIMARY KEY (scenario_id, assumption_id)
);

-- A one-time cost has exactly one period_index; a recurring cost has a half-open [start_period, end_period) and a null period_index (D-P9-16).
CREATE TABLE IF NOT EXISTS cost_items (
    cost_id          TEXT PRIMARY KEY,
    initiative_id    TEXT NOT NULL REFERENCES initiatives (initiative_id),
    cost_key         TEXT NOT NULL,
    cost_type        TEXT NOT NULL,
    cost_basis       TEXT NOT NULL,
    amount           NUMERIC(20,6) NOT NULL,
    period_index     INT,
    start_period     INT,
    end_period       INT,
    baseline_version TEXT
);

-- The recurring costs, expanded explicitly into one row per period by C03 (never by a display loop).
CREATE TABLE IF NOT EXISTS expanded_costs (
    scenario_id   TEXT NOT NULL REFERENCES scenario_versions (scenario_id),
    cost_id       TEXT NOT NULL REFERENCES cost_items (cost_id),
    initiative_id TEXT NOT NULL REFERENCES initiatives (initiative_id),
    period_index  INT NOT NULL,
    amount        NUMERIC(20,6) NOT NULL,
    PRIMARY KEY (scenario_id, cost_id, period_index)
);

CREATE TABLE IF NOT EXISTS benefit_items (
    benefit_id                TEXT PRIMARY KEY,
    initiative_id             TEXT NOT NULL REFERENCES initiatives (initiative_id),
    benefit_type              TEXT NOT NULL,
    amount                    NUMERIC(20,6) NOT NULL,          -- USD, or hours for capacity
    period_index              INT NOT NULL,
    starts_period             INT NOT NULL,
    unit                      TEXT NOT NULL,
    cash_realisation          BOOLEAN,
    evidence_ref              TEXT,
    benefit_source_key        TEXT,
    baseline_trend_per_period NUMERIC(20,6)
);

CREATE TABLE IF NOT EXISTS dependencies (
    dependency_id   TEXT PRIMARY KEY,
    initiative_id   TEXT NOT NULL REFERENCES initiatives (initiative_id),
    prerequisite_id TEXT NOT NULL REFERENCES initiatives (initiative_id),
    dependency_type TEXT NOT NULL,
    lag_periods     INT NOT NULL
);

CREATE TABLE IF NOT EXISTS stakeholder_groups (
    group_id       TEXT PRIMARY KEY,
    group_name     TEXT NOT NULL,
    owner_id       TEXT NOT NULL,
    affected_count INT NOT NULL,
    impact_level   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS impact_mappings (
    mapping_id       TEXT PRIMARY KEY,
    initiative_id    TEXT NOT NULL REFERENCES initiatives (initiative_id),
    group_id         TEXT NOT NULL REFERENCES stakeholder_groups (group_id),
    operating_change TEXT NOT NULL,
    impact_level     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_allocations (
    allocation_id TEXT PRIMARY KEY,
    resource_id   TEXT NOT NULL REFERENCES resources (resource_id),
    initiative_id TEXT NOT NULL REFERENCES initiatives (initiative_id),
    period_index  INT NOT NULL,
    amount        NUMERIC(20,6) NOT NULL
);

CREATE TABLE IF NOT EXISTS readiness_assessments (
    assessment_id TEXT PRIMARY KEY,
    group_id      TEXT NOT NULL REFERENCES stakeholder_groups (group_id),
    dimension     TEXT NOT NULL,
    score         INT NOT NULL,
    weight        NUMERIC(20,6) NOT NULL,
    assessed_at   TIMESTAMPTZ NOT NULL,
    assessed_by   TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS adoption_observations (
    observation_id           TEXT PRIMARY KEY,
    initiative_id            TEXT NOT NULL REFERENCES initiatives (initiative_id),
    eligible_count           INT NOT NULL,
    adopted_count            INT NOT NULL,
    observed_at              TIMESTAMPTZ NOT NULL,
    eligibility_rule_version TEXT NOT NULL,
    recorded_by              TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS training_completions (
    training_id              TEXT PRIMARY KEY,
    initiative_id            TEXT NOT NULL REFERENCES initiatives (initiative_id),
    eligible_trainees        INT NOT NULL,
    completed                INT NOT NULL,
    recorded_at              TIMESTAMPTZ NOT NULL,
    eligibility_rule_version TEXT NOT NULL,
    recorded_by              TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS benefit_observations (
    benefit_observation_id TEXT PRIMARY KEY,
    benefit_id             TEXT NOT NULL REFERENCES benefit_items (benefit_id),
    measured_value         NUMERIC(20,6) NOT NULL,
    evidence_ref           TEXT NOT NULL,
    observed_at            TIMESTAMPTZ NOT NULL,
    recorded_by            TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS risk_items (
    risk_id       TEXT PRIMARY KEY,
    initiative_id TEXT NOT NULL REFERENCES initiatives (initiative_id),
    probability   NUMERIC(7,6) NOT NULL,
    impact        NUMERIC(20,6) NOT NULL,                  -- USD (D-P9-13)
    mitigation    TEXT NOT NULL
);

-- Forecast versions: one row per (initiative, version, period); a revision is version n+1 and the original is never overwritten (C10).
CREATE TABLE IF NOT EXISTS forecast_versions (
    forecast_id    TEXT PRIMARY KEY,
    initiative_id  TEXT NOT NULL REFERENCES initiatives (initiative_id),
    version_number INT NOT NULL,
    period_index   INT NOT NULL,
    amount         NUMERIC(20,6) NOT NULL,
    reason         TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    created_by     TEXT NOT NULL DEFAULT 'seed',
    CONSTRAINT forecast_versions_uq UNIQUE (initiative_id, version_number, period_index)
);

CREATE TABLE IF NOT EXISTS rejected_records (
    seq         BIGINT GENERATED ALWAYS AS IDENTITY,
    batch_id    TEXT NOT NULL,
    entity      TEXT NOT NULL,
    id          TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
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

CREATE INDEX IF NOT EXISTS cost_items_initiative_idx   ON cost_items (initiative_id, cost_basis);
CREATE INDEX IF NOT EXISTS benefit_items_initiative_idx ON benefit_items (initiative_id, benefit_type);
CREATE INDEX IF NOT EXISTS dependencies_initiative_idx ON dependencies (initiative_id);
CREATE INDEX IF NOT EXISTS allocations_resource_idx    ON resource_allocations (resource_id, period_index);
CREATE INDEX IF NOT EXISTS readiness_group_idx         ON readiness_assessments (group_id, dimension, assessed_at);
CREATE INDEX IF NOT EXISTS adoption_initiative_idx     ON adoption_observations (initiative_id, observed_at);
CREATE INDEX IF NOT EXISTS benefit_obs_benefit_idx     ON benefit_observations (benefit_id, observed_at);
CREATE INDEX IF NOT EXISTS audit_entity_idx            ON audit_events (entity_type, entity_id, occurred_at);
