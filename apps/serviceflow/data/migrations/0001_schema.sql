-- ServiceFlow schema, contract v1 (docs/contracts.md). Idempotent: every statement is IF NOT EXISTS.
-- All instants are TIMESTAMPTZ (UTC). Constraints and triggers live in 0002_constraints.sql.

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    segment     TEXT NOT NULL,
    timezone    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    synthetic   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS queues (
    queue_id        TEXT PRIMARY KEY,
    queue_name      TEXT NOT NULL,
    priority_policy TEXT NOT NULL,
    calendar_id     TEXT NOT NULL,
    active          BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    timezone        TEXT NOT NULL,
    employment_type TEXT NOT NULL,
    active          BOOLEAN NOT NULL,
    max_concurrent  INT NOT NULL DEFAULT 1            -- P04-TEST-04: declared concurrency per agent
);

CREATE TABLE IF NOT EXISTS skills (
    skill_id    TEXT PRIMARY KEY,
    skill_name  TEXT NOT NULL,
    description TEXT,
    active      BOOLEAN NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_skills (
    agent_skill_id TEXT PRIMARY KEY,
    agent_id       TEXT NOT NULL REFERENCES agents (agent_id),
    skill_id       TEXT NOT NULL REFERENCES skills (skill_id),
    proficiency    INT NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS queue_skills (
    queue_id TEXT NOT NULL REFERENCES queues (queue_id),
    skill_id TEXT NOT NULL REFERENCES skills (skill_id),
    PRIMARY KEY (queue_id, skill_id)
);

-- Shift instants are UTC: a daylight-saving day does not stretch or shrink a shift (P04-TEST-07).
CREATE TABLE IF NOT EXISTS shifts (
    shift_id      TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL REFERENCES agents (agent_id),
    starts_at     TIMESTAMPTZ NOT NULL,
    ends_at       TIMESTAMPTZ NOT NULL,
    break_minutes INT NOT NULL
);

-- Recorded break intervals (optional; the golden data has none). C03 refuses a start inside one.
CREATE TABLE IF NOT EXISTS shift_breaks (
    break_id  TEXT PRIMARY KEY,
    shift_id  TEXT NOT NULL REFERENCES shifts (shift_id),
    agent_id  TEXT NOT NULL REFERENCES agents (agent_id),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sla_policies (
    sla_policy_id          TEXT PRIMARY KEY,
    priority               TEXT NOT NULL,
    first_response_minutes INT NOT NULL,
    resolution_minutes     INT NOT NULL,
    calendar_id            TEXT NOT NULL
);

-- ``queue_id`` is the CURRENT queue (a transfer changes it); ``created_at`` is the arrival and never changes.
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id   TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers (customer_id),
    queue_id    TEXT NOT NULL REFERENCES queues (queue_id),
    priority    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    channel     TEXT NOT NULL
);

-- The canonical event log: immutable (trigger in 0002), one row per state change. ``event_seq`` is the insertion
-- order; ``event_id`` is the business key and UNIQUE, so a replayed event is refused by the database too.
CREATE TABLE IF NOT EXISTS ticket_events (
    event_seq   BIGSERIAL PRIMARY KEY,
    event_id    TEXT NOT NULL,
    ticket_id   TEXT NOT NULL REFERENCES tickets (ticket_id),
    event_type  TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor_id    TEXT,
    queue_id    TEXT REFERENCES queues (queue_id),
    agent_id    TEXT REFERENCES agents (agent_id),
    CONSTRAINT ticket_events_event_id_key UNIQUE (event_id)
);

CREATE TABLE IF NOT EXISTS surveys (
    survey_id   TEXT PRIMARY KEY,
    ticket_id   TEXT NOT NULL REFERENCES tickets (ticket_id),
    response_at TIMESTAMPTZ,
    score       INT,
    invited_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    simulation_id  TEXT PRIMARY KEY,
    seed           BIGINT NOT NULL,
    warmup_minutes NUMERIC(14,4) NOT NULL,
    policy_version TEXT NOT NULL,
    horizon_minutes NUMERIC(14,4) NOT NULL,
    config         JSONB NOT NULL,
    replications   INT NOT NULL DEFAULT 1,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Simulated events carry the simulation's own ticket labels (t-001, ...), which are NOT tickets of the table above.
CREATE TABLE IF NOT EXISTS simulation_events (
    simulation_id       TEXT NOT NULL REFERENCES simulation_runs (simulation_id),
    simulation_event_id TEXT NOT NULL,
    ticket_id           TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    event_at            NUMERIC(14,4) NOT NULL,       -- minutes from the start of the run
    warmup              BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (simulation_id, simulation_event_id)
);

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
    ordinal     INT NOT NULL DEFAULT 0,
    PRIMARY KEY (batch_id, entity, id, reason_code, ordinal)
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

-- Actor-bound idempotency: the same key from another actor is refused (Q-06).
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

CREATE INDEX IF NOT EXISTS ticket_events_ticket_idx ON ticket_events (ticket_id, occurred_at, event_id);
CREATE INDEX IF NOT EXISTS ticket_events_agent_idx  ON ticket_events (agent_id, occurred_at) WHERE agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS shifts_agent_idx         ON shifts (agent_id, starts_at);
CREATE INDEX IF NOT EXISTS surveys_ticket_idx       ON surveys (ticket_id);
