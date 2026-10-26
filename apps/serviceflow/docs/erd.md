# Entity-relationship diagram (P04-ART-03)

Derived from `data/migrations/0001_schema.sql` and `0002_constraints.sql`. Solid lines are enforced foreign keys; dotted lines are logical joins the contract relies on (D-01, D-02, D-06) that the database does not enforce. Field detail, grain, update semantics and the deletion policy are in `data-dictionary.md`. Synthetic data only (dataset `sf-20261026-20261026`, hash `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4`, code revision `43de7f8`).

```mermaid
erDiagram
    customers {
        TEXT customer_id PK
        TEXT segment
        TEXT timezone
        TIMESTAMPTZ created_at
        BOOLEAN synthetic
    }
    queues {
        TEXT queue_id PK
        TEXT queue_name
        TEXT priority_policy
        TEXT calendar_id
        BOOLEAN active
    }
    agents {
        TEXT agent_id PK
        TEXT agent_name
        TEXT timezone
        TEXT employment_type
        BOOLEAN active
        INT max_concurrent
    }
    skills {
        TEXT skill_id PK
        TEXT skill_name
        TEXT description
        BOOLEAN active
        TIMESTAMPTZ created_at
    }
    agent_skills {
        TEXT agent_skill_id PK
        TEXT agent_id FK
        TEXT skill_id FK
        INT proficiency
        TIMESTAMPTZ effective_from
    }
    queue_skills {
        TEXT queue_id FK
        TEXT skill_id FK
    }
    shifts {
        TEXT shift_id PK
        TEXT agent_id FK
        TIMESTAMPTZ starts_at
        TIMESTAMPTZ ends_at
        INT break_minutes "declared break"
    }
    shift_breaks {
        TEXT break_id PK
        TEXT shift_id FK
        TEXT agent_id FK
        TIMESTAMPTZ starts_at
        TIMESTAMPTZ ends_at
    }
    sla_policies {
        TEXT sla_policy_id PK
        TEXT priority
        INT first_response_minutes
        INT resolution_minutes
        TEXT calendar_id
    }
    tickets {
        TEXT ticket_id PK
        TEXT customer_id FK
        TEXT queue_id FK "current queue"
        TEXT priority
        TIMESTAMPTZ created_at "arrival; never changes"
        TEXT channel
    }
    ticket_events {
        BIGSERIAL event_seq PK
        TEXT event_id "unique; immutable log"
        TEXT ticket_id FK
        TEXT event_type
        TIMESTAMPTZ occurred_at
        TEXT actor_id
        TEXT queue_id FK
        TEXT agent_id FK
    }
    surveys {
        TEXT survey_id PK
        TEXT ticket_id FK
        TIMESTAMPTZ response_at
        INT score
        TIMESTAMPTZ invited_at
    }
    simulation_runs {
        TEXT simulation_id PK
        BIGINT seed
        NUMERIC warmup_minutes
        TEXT policy_version
        NUMERIC horizon_minutes
        JSONB config
        INT replications
        TIMESTAMPTZ created_at
    }
    simulation_events {
        TEXT simulation_id FK
        TEXT simulation_event_id
        TEXT ticket_id "logical: simulated label"
        TEXT event_type
        NUMERIC event_at
        BOOLEAN warmup
    }
    raw_batches {
        TEXT batch_id PK
        TIMESTAMPTZ received_at
        TEXT idempotency_key
        TEXT payload_hash
        JSONB payload
        TEXT status
    }
    rejected_records {
        TEXT entity
        TEXT id
        TEXT reason_code
        JSONB raw_row
        TEXT batch_id FK
        INT ordinal
    }
    audit_events {
        TEXT event_id PK
        TEXT entity_type
        TEXT entity_id
        TEXT action
        TEXT actor_id
        TIMESTAMPTZ occurred_at
        INT before_version
        INT after_version
        TEXT reason
        TEXT request_id
    }
    command_results {
        TEXT idempotency_key PK
        TEXT payload_hash
        TEXT actor_id
        TEXT command_id
        TEXT status
        JSONB result
        TIMESTAMPTZ created_at
    }
    dataset_versions {
        TEXT dataset_version PK
        TEXT dataset_hash
        TEXT contract_version
        TIMESTAMPTZ created_at
    }
    schema_migrations {
        TEXT version PK
        TEXT checksum
        TIMESTAMPTZ applied_at
    }
    customers ||--o{ tickets : "places"
    queues ||--o{ tickets : "holds"
    tickets ||--o{ ticket_events : "logged by"
    queues |o--o{ ticket_events : "queue of"
    agents |o--o{ ticket_events : "served by"
    tickets ||--o{ surveys : "surveyed by"
    agents ||--o{ agent_skills : "holds"
    skills ||--o{ agent_skills : "held as"
    queues ||--o{ queue_skills : "requires"
    skills ||--o{ queue_skills : "required as"
    agents ||--o{ shifts : "works"
    shifts ||--o{ shift_breaks : "has breaks"
    agents ||--o{ shift_breaks : "takes"
    simulation_runs ||--o{ simulation_events : "yields"
    raw_batches ||--o{ rejected_records : "refused rows"
    sla_policies ||..o{ tickets : "priority (logical)"
    tickets ||..o{ simulation_events : "NOT linked: simulated labels"
    queues ||..o{ sla_policies : "calendar_id (logical)"
```

## Reading notes

* **Immutable:** `ticket_events` (a state change is an event: no UPDATE, DELETE or TRUNCATE; a replayed `event_id` is refused). **Append-only:** `audit_events` and `simulation_events`. **Fixed:** `tickets.created_at`, the arrival, which a transfer or a reopen never moves (P04-FLOW-04). The only mutable business column is `tickets.queue_id` (the current queue).
* **A reopen is not a new ticket** and there is no table for a cycle: cycles are replayed from the event log (`resolved` then `reopened`), so a reopened ticket is one customer contact (P04-TEST-02).
* **Logical joins (dotted):** `sla_policies.priority` to `tickets.priority` (the SLA of a ticket is read by priority, `SLA_POLICY_MISSING` is 422 when absent); `calendar_id` on queues and policies (carried, ignored, D-09 R4-18); `simulation_events.ticket_id` carries the simulation's own labels (`t-001`...) and must NOT be joined to `tickets`. `audit_events.entity_id`, `rejected_records.id` and `command_results.idempotency_key` point at any entity.
* **The source queue of a transfer** is not a column: it is the queue of the previous `created`/`queued`/`transferred` event of the same ticket (analysis query 05 derives it).
* **Not drawn:** the analysis views `sf_window`, `sf_ev`, `sf_ticket`, `sf_interval` (`data/sql/analysis/00_event_views.sql`) and the BI star schema (`bi-package.md`).
* **Analysis grains:** the ticket (`fact_ticket`), the service interval (`fact_service_interval`), the shift (`fact_shift`) and the survey (`fact_survey`) are the grains of `bi_fact_*.sql`.
* `schema_migrations` (created by `data/migrate.py`) is drawn for completeness; it has no relationship.
