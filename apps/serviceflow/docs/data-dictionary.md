# Data dictionary: ServiceFlow relational model (P04-ART-03)

All data in this model is **synthetic**: the golden fixture (`tests/fixtures/golden/inputs.json`, dataset version `golden-v1`) and the generated snapshot `sf-20261026-20261026` (seed 20261026, generator `dataset_hash` `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4`, contract v1, code revision `43de7f8`). The customers, agents and tickets do not exist; the agent names are generated. Sources: `data/migrations/0001_schema.sql` and `0002_constraints.sql`, `data/seed.py`, `data/migrate.py`, `docs/contracts.md` (D-01..D-09), `docs/api-contract.md` and the entity files of `web/public/data`.

**How to read this without installing anything:** section 1 is one row per table (grain, key, rows, update semantics, deletion), section 2 one table per table with every column, section 3 the foreign keys, section 4 the constraints and triggers, section 5 the source-to-target mapping, section 6 the known gaps. `erd.md` draws the same model.

Row counts are `SELECT count(*)` on scratch PostgreSQL 16 databases prepared by `data/sql/analysis/prepare_snapshot.py` (migrate, then `seed.py` through the domain's `validate_batch` over `web/public/data`, then the 1,018 break rows): the snapshot database holds 3,817 of the 3,826 published tickets, 21,893 of the 21,948 events and 2,147 of the 2,153 surveys; **70 rows were rejected** (9 tickets, 55 events, 6 surveys) and kept in `rejected_records`, so accepted + rejected equals the published counts (reconciled in `sql-analysis.md`, query 08 and section 10).

Conventions: all instants are `TIMESTAMPTZ` read as UTC (D-02); durations are never stored (they are computed as epoch seconds divided by 60 once); ids are `TEXT` keys supplied by the source; absence is NULL (never an empty string, 0 or NaN); counts are non-negative integers. "FK" means a foreign key enforced in `0001`; "logical" means a join the contract relies on that the database does not enforce. Constraint and trigger names are those of `0002_constraints.sql`. Observed, simulated and hypothetical are kept apart: the first nineteen tables hold OBSERVED synthetic history, except `simulation_runs` and `simulation_events` which hold the declaration and the events of SIMULATED runs; nothing in this model is a realised benefit.

## 1. Tables, grain, keys and update semantics

| Table | Kind | Grain | Primary key | Rows (snapshot DB) | Rows (golden DB) | Update semantics |
|---|---|---|---|---|---|---|
| `customers` | source | one customer (synthetic) | `customer_id` | 1,004 | 3 | Insert-only through the seed. `created_at` is the customer record, not a ticket; four customers (c-1001..c-1004) were created at the instant of their only ticket: injected defect INJ-02 (a reopen recorded as a new customer), detectable only by an analyst check (`08`). |
| `queues` | source | one service queue | `queue_id` | 3 | 1 | Insert-only. `priority_policy` is `fifo_within_priority` (billing q-001, technical q-002) or `fifo` (onboarding q-003); `active` retires a queue without deleting it. |
| `agents` | source | one support agent (synthetic names) | `agent_id` | 18 | 1 | Insert-only. `max_concurrent` bounds simultaneous services (P04-TEST-04); `active` retires an agent. |
| `skills` | source | one skill | `skill_id` | 3 | 1 | Insert-only. One skill per queue in the snapshot (billing, technical, onboarding). |
| `agent_skills` | source | one skill held by one agent from one instant | `agent_skill_id` | 29 | 1 | Insert-only. A skill counts for an assignment only from `effective_from` (P04-FLOW-03, P04-TEST-03); a later change is a new row, never an edit. |
| `queue_skills` | source | one skill a queue requires | `(queue_id, skill_id)` | 3 | 1 | Insert-only. A service start needs an agent holding the queue's skill. |
| `shifts` | source | one shift of one agent, as UTC instants | `shift_id` | 1,020 | 1 | Insert-only. UTC instants, so a daylight-saving day never stretches a shift (D-02). `break_minutes` is the DECLARED break and is what staffed time deducts (D-03, D-05); three rows declare 0 although a break is recorded (INJ-05) and one row is the 480-minute night shift of agt-018 across the clock change (INJ-08). |
| `shift_breaks` | source | one recorded break interval of one shift | `break_id` | 1,018 | 0 | Insert-only and data-load-only: `data/seed.py` has no loader for it (D-07), `data/sql/analysis/prepare_snapshot.py` inserts the published `shift_breaks.json` rows. C03 `start-service` and `resume-work` refuse a start inside one (`AGENT_ON_BREAK`). 1,015 shifts have one break of 30 minutes; 2 have none; 3 are the INJ-05 shifts. |
| `sla_policies` | source | one SLA target set for one priority | `sla_policy_id` | 3 | 1 | Insert-only. Targets in wall-clock minutes (P1 15 / 240, P2 60 / 1440, P3 240 / 4320). `calendar_id` is carried but calendars are ignored (D-09 R4-18: `SLA_CALENDAR_IGNORED` for any calendar other than `cal-001`). |
| `tickets` | source | one customer contact (a reopen is NOT a new row) | `ticket_id` | 3,817 | 3 | `queue_id` is the CURRENT queue and is the only column ever updated (C02 assign-queue, C04 transfer, C01 ingest); `created_at` is the arrival and is immutable (trigger `tickets_arrival_fixed`, `ARRIVAL_IMMUTABLE`). Rejected tickets (9 in the snapshot) are not in this table; they are in `rejected_records`. |
| `ticket_events` | source | one state change of one ticket (the canonical event log) | `event_seq` (insertion order); `event_id` is unique | 21,893 | 18 | **Immutable**: trigger `ticket_events_immutable` refuses UPDATE and DELETE and `ticket_events_no_truncate` refuses TRUNCATE. A replayed `event_id` is refused by `ticket_events_event_id_key`. Late arrivals keep their own `occurred_at` (P04-FLOW-01); replay order is `(occurred_at, event_id)`, not insertion order. |
| `surveys` | source | one survey invitation and its answer, if any | `survey_id` | 2,147 | 2 | Insert-only. `score` and `response_at` are both NULL or both set (`surveys_pair_ck`); an unanswered invitation has a NULL score, never 0. One row per invited ticket in the snapshot (2,147 rows, 2,147 distinct tickets). |
| `simulation_runs` | source | one declared simulation run (config, seed, warm-up, horizon) | `simulation_id` | 3 | 1 | Insert-only. Seed, warm-up and horizon are declared before the run (P04-DOMAIN-05, P04-TEST-09). The cold-start run of INJ-07 is replay-only and is not in the table. |
| `simulation_events` | derived | one simulated event (service start or resolution) of one run, in minutes from the run start | `(simulation_id, simulation_event_id)` | 206 | 6 | **Append-only** (`simulation_events_append_only`). Written by `data/seed.py` for the first replication of each accepted run and by C08. Its `ticket_id` values (t-001, ...) are the simulation's own labels, NOT tickets of `tickets` (no foreign key by design). |
| `raw_batches` | operational | one received input batch, kept whole | `batch_id`; `idempotency_key` unique | 1 | 0 | Insert-only. `status` is `accepted`, `partial` or `rejected`. The snapshot seed writes one `partial` batch (`batch-seed-<16 hex>`) because rows were refused; C01 writes one per ingest. |
| `rejected_records` | operational | one raw row refused at ingest, with its reason | `(batch_id, entity, id, reason_code, ordinal)` | 70 | 0 | Insert-only. `raw_row` keeps the row as it arrived; `ordinal` separates two refused occurrences of one id. 70 rows in the snapshot (query 08). |
| `audit_events` | operational | one audit line per accepted command | `event_id` | 0 | 0 | **Append-only** (`audit_events_append_only`). Written in the SAME transaction as the command it records, so an audit line exists exactly when the effect does. Empty in a seeded database; filled by the API. |
| `command_results` | operational | one stored result per idempotency key | `idempotency_key` | 0 | 0 | Insert-only. The same key, payload, dataset version and actor replays the stored result; another payload, version or actor is 409 `IDEMPOTENCY_KEY_REUSED` (D-09 R4-05). Empty in a seeded database. |
| `dataset_versions` | operational | one seeded dataset | `dataset_version` | 1 | 1 | Insert-only. The seed hashes the INPUT JSON (`ds-<12 hex>`), which is not the generator's file hash in `manifest.json` (`sf-20261026-20261026`, `944ef91b...cba4`); see section 6. A request naming another version than the newest row is 409 `STALE_DATASET_VERSION`. |
| `schema_migrations` | operational | one applied migration (created by `data/migrate.py`, not by the SQL files) | `version` | 2 | 2 | Holds the sha256 of each applied file; a migration that changed after it was applied is refused. |

**Deletion policy.** Nothing in the application deletes a row: no command issues a `DELETE` (`api/commands.py` has only INSERTs and the single `UPDATE tickets SET queue_id`), the two event tables and `audit_events` refuse UPDATE, DELETE and TRUNCATE by trigger, and every foreign key is the PostgreSQL default (`NO ACTION`), so a parent row cannot be deleted while a child references it. Retirement is a flag (`queues.active`, `agents.active`, `skills.active`), a correction is a new event, and a refused input is kept, never dropped, in `rejected_records`. `data/migrate.py --reset` drops the project's tables and is for scratch databases only (the analysis scripts refuse any database not named `artifacts04_*`).

Immutable and append-only: `ticket_events` (UPDATE, DELETE and TRUNCATE refused), `audit_events` and `simulation_events` (UPDATE and DELETE refused). `tickets.created_at` cannot change (`tickets_arrival_fixed`).

## 2. Columns

Type is the PostgreSQL type of `0001_schema.sql`; Null is whether the column accepts NULL; Source is the entity-file field the seed loads it from (`web/public/data/<entity>.json`, same field names as `tests/fixtures/golden/inputs.json`) or how it is produced.

### customers
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `customer_id` | TEXT | no | Key | customers.customer_id |
| `segment` | TEXT | no | Customer segment: `consumer` (571), `smb` (345) or `enterprise` (88) | customers.segment |
| `timezone` | TEXT | no | IANA zone of the customer, for display only | customers.timezone |
| `created_at` | TIMESTAMPTZ | no | When the customer record was created (UTC) | customers.created_at |
| `synthetic` | BOOLEAN (default TRUE) | no | Always TRUE here: the row is generated, not a real person (P04-GOAL-12) | customers.synthetic |

### queues
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `queue_id` | TEXT | no | Key (`q-001` billing, `q-002` technical, `q-003` onboarding) | queues.queue_id |
| `queue_name` | TEXT | no | Display name | queues.queue_name |
| `priority_policy` | TEXT | no | `fifo_within_priority` or `fifo` (`queues_policy_ck`); across queues `fifo` tickets rank as P2 (D-07) | queues.priority_policy |
| `calendar_id` | TEXT | no | SLA calendar (24x7 `cal-001`; D-09 R4-18) | queues.calendar_id |
| `active` | BOOLEAN | no | Whether the queue takes new tickets | queues.active |

### agents
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `agent_id` | TEXT | no | Key | agents.agent_id |
| `agent_name` | TEXT | no | Display name (synthetic) | agents.agent_name |
| `timezone` | TEXT | no | IANA zone the agent's shifts are declared in (Europe/Berlin or America/Santiago) | agents.timezone |
| `employment_type` | TEXT | no | `full_time`, `part_time` or `contractor` (`agents_employment_ck`) | agents.employment_type |
| `active` | BOOLEAN | no | Whether the agent can be assigned | agents.active |
| `max_concurrent` | INT (default 1) | no | Declared simultaneous services, `>= 1` (`agents_concurrency_ck`, default 1); the concurrency rule P04-TEST-04 bounds intervals by it | agents.max_concurrent |

### skills
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `skill_id` | TEXT | no | Key | skills.skill_id |
| `skill_name` | TEXT | no | Display name | skills.skill_name |
| `description` | TEXT | yes | Free text, may be NULL | skills.description |
| `active` | BOOLEAN | no | Whether the skill can be required | skills.active |
| `created_at` | TIMESTAMPTZ | no | When the skill was defined (UTC) | skills.created_at |

### agent_skills
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `agent_skill_id` | TEXT | no | Key | agent_skills.agent_skill_id |
| `agent_id` | TEXT | no | FK to `agents` | agent_skills.agent_id |
| `skill_id` | TEXT | no | FK to `skills` | agent_skills.skill_id |
| `proficiency` | INT | no | 1 to 5 (`agent_skills_prof_ck`); proficiency >= 4 resolves faster in the generator (designed relationship) | agent_skills.proficiency |
| `effective_from` | TIMESTAMPTZ | no | The skill counts from this instant (UTC) | agent_skills.effective_from |

### queue_skills
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `queue_id` | TEXT | no | FK to `queues`; first key part | queue_skills.queue_id |
| `skill_id` | TEXT | no | FK to `skills`; second key part | queue_skills.skill_id |

### shifts
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `shift_id` | TEXT | no | Key | shifts.shift_id |
| `agent_id` | TEXT | no | FK to `agents` | shifts.agent_id |
| `starts_at` | TIMESTAMPTZ | no | Shift start (UTC instant) | shifts.starts_at |
| `ends_at` | TIMESTAMPTZ | no | Shift end (UTC instant), `> starts_at` (`shifts_order_ck`) | shifts.ends_at |
| `break_minutes` | INT | no | Declared break, `>= 0` and not longer than the shift (`shifts_break_ck`, `shifts_break_fit_ck`); deducted from staffed time only when the window covers the whole shift (D-05) | shifts.break_minutes |

### shift_breaks
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `break_id` | TEXT | no | Key | shift_breaks.break_id |
| `shift_id` | TEXT | no | FK to `shifts` | shift_breaks.shift_id |
| `agent_id` | TEXT | no | FK to `agents` | shift_breaks.agent_id |
| `starts_at` | TIMESTAMPTZ | no | Break start (UTC instant) | shift_breaks.starts_at |
| `ends_at` | TIMESTAMPTZ | no | Break end, `> starts_at` (`shift_breaks_order_ck`) | shift_breaks.ends_at |

### sla_policies
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `sla_policy_id` | TEXT | no | Key | sla_policies.sla_policy_id |
| `priority` | TEXT | no | `P1`, `P2` or `P3` (`sla_priority_ck`); one row per priority | sla_policies.priority |
| `first_response_minutes` | INT | no | Target, `> 0` | sla_policies.first_response_minutes |
| `resolution_minutes` | INT | no | Target, `> 0` (`sla_minutes_ck`) | sla_policies.resolution_minutes |
| `calendar_id` | TEXT | no | Calendar id; only `cal-001` (24x7) is honoured | sla_policies.calendar_id |

### tickets
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `ticket_id` | TEXT | no | Key | tickets.ticket_id |
| `customer_id` | TEXT | no | FK to `customers` | tickets.customer_id |
| `queue_id` | TEXT | no | FK to `queues`: the CURRENT (final, once resolved) queue; the first queue is on the `created` event | tickets.queue_id |
| `priority` | TEXT | no | `P1`, `P2` or `P3` (`tickets_priority_ck`) | tickets.priority |
| `created_at` | TIMESTAMPTZ | no | The ARRIVAL instant (UTC); never changes, not by a transfer or a reopen (P04-FLOW-04) | tickets.created_at |
| `channel` | TEXT | no | `chat`, `email`, `phone` or `web_form`; only chat and phone can abandon (D-05) | tickets.channel |

### ticket_events
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `event_seq` | BIGSERIAL | no | Insertion order (BIGSERIAL); NOT the replay order | generated by the database |
| `event_id` | TEXT | no | Business key, unique (`ticket_events_event_id_key`); a replay is refused | ticket_events.event_id |
| `ticket_id` | TEXT | no | FK to `tickets` | ticket_events.ticket_id |
| `event_type` | TEXT | no | One of created, queued, acknowledged_bot, service_started, replied_human, paused, resumed, transferred, resolved, reopened, abandoned (`events_type_ck`) | ticket_events.event_type |
| `occurred_at` | TIMESTAMPTZ | no | When it happened (UTC), kept for late arrivals | ticket_events.occurred_at |
| `actor_id` | TEXT | yes | Who acted; an id starting `bot-` is automation and never a human reply (`events_bot_reply_ck`); NULL on `created`, `queued`, `reopened` and `abandoned` (customer or system) | ticket_events.actor_id |
| `queue_id` | TEXT | yes | FK to `queues`; set on `created`, `queued` and `transferred` (the destination) | ticket_events.queue_id |
| `agent_id` | TEXT | yes | FK to `agents`; required on `service_started` (`events_agent_ck`) and set on `replied_human`, `paused`, `resumed` and `resolved`; names the agent of an interval | ticket_events.agent_id |

### surveys
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `survey_id` | TEXT | no | Key | surveys.survey_id |
| `ticket_id` | TEXT | no | FK to `tickets` | surveys.ticket_id |
| `response_at` | TIMESTAMPTZ | yes | When it was answered; NULL when unanswered | surveys.response_at |
| `score` | INT | yes | 1 to 5 (`surveys_score_ck`); NULL when unanswered, never 0 | surveys.score |
| `invited_at` | TIMESTAMPTZ | yes | When the invitation was sent; NULL means not invited | surveys.invited_at |

### simulation_runs
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `simulation_id` | TEXT | no | Key (`sim-001` baseline, `sim-002` plus one agent, `sim-003` holdout intensity) | simulation_runs.simulation_id |
| `seed` | BIGINT | no | Base seed; replication r uses seed + r (D-09) | simulation_runs.seed |
| `warmup_minutes` | NUMERIC(14,4) | no | Warm-up, `>= 0`; warm-up observations are excluded from every statistic (P04-TEST-09) | simulation_runs.warmup_minutes |
| `policy_version` | TEXT | no | Label of the policy (`baseline-v1`, ...) | simulation_runs.policy_version |
| `horizon_minutes` | NUMERIC(14,4) | no | Run length, `> 0` (`sim_runs_ck`) | simulation_runs.horizon_minutes |
| `config` | JSONB | no | JSONB: agents, arrival_rate_per_hour, service_minutes, priority_mix, discipline, service | simulation_runs.config |
| `replications` | INT (default 1) | no | Count, `>= 1`; the seeded runs store 1 (the published 50-replication summary is `web/public/reference/simulation-runs.json`) | generated by the seed (default 1) |
| `created_at` | TIMESTAMPTZ (default now()) | no | Row creation time (database clock), NOT a business instant | generated by the database |

### simulation_events
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `simulation_id` | TEXT | no | FK to `simulation_runs`; first key part | generated by `data/seed.py` / C08 |
| `simulation_event_id` | TEXT | no | Event id within the run (`se-001`...); second key part | generated |
| `ticket_id` | TEXT | no | The simulation's own ticket label, not a `tickets` row | generated |
| `event_type` | TEXT | no | `service_started` or `resolved` (`sim_events_type_ck`) | generated |
| `event_at` | NUMERIC(14,4) | no | Minutes from the start of the run, NUMERIC(14,4) | generated |
| `warmup` | BOOLEAN (default FALSE) | no | TRUE for a warm-up ticket (excluded from statistics) | generated |

### raw_batches
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `batch_id` | TEXT | no | Key | generated |
| `received_at` | TIMESTAMPTZ (default now()) | no | Receipt time (database clock) | generated by the database |
| `idempotency_key` | TEXT | no | Unique; a repeat with the same payload replays | generated / request header |
| `payload_hash` | TEXT | no | sha256 of the canonical payload | generated |
| `payload` | JSONB | no | JSONB: the whole input as it arrived | request body / seed input |
| `status` | TEXT | no | `accepted`, `partial` or `rejected` (`raw_batches_status_ck`) | generated |

### rejected_records
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `entity` | TEXT | no | Entity of the refused row (`tickets`, `ticket_events`, `surveys`, ...) | validate_batch |
| `id` | TEXT | no | Business id of the refused row | validate_batch |
| `reason_code` | TEXT | no | Reason: BOT_AS_HUMAN_REPLY, AGENT_NOT_QUALIFIED, CONCURRENCY_EXCEEDED, TRANSFER_RESETS_ARRIVAL, SERVICE_OUTSIDE_SHIFT, RESUME_BEFORE_SERVICE, TICKET_REJECTED (dependants), ... | validate_batch |
| `raw_row` | JSONB | no | JSONB: the row as it arrived | validate_batch |
| `batch_id` | TEXT | no | FK to `raw_batches` | generated |
| `ordinal` | INT (default 0) | no | Separates two refused occurrences of one id (default 0) | generated |

### audit_events
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `event_id` | TEXT | no | Key | generated |
| `entity_type` | TEXT | no | What was changed (ticket, simulation, ...) | command handler |
| `entity_id` | TEXT | no | Its id (logical, not an FK) | command handler |
| `action` | TEXT | no | The command name | command handler |
| `actor_id` | TEXT | no | Who acted (the `X-Actor-Id` header) | request |
| `occurred_at` | TIMESTAMPTZ (default now()) | no | Audit time (database clock) | generated by the database |
| `before_version` | INT | yes | Version before the change | command handler |
| `after_version` | INT | yes | Version after the change | command handler |
| `reason` | TEXT | yes | Free text, may be NULL | request |
| `request_id` | TEXT | yes | The request id of the envelope | request |

### command_results
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `idempotency_key` | TEXT | no | Key | request |
| `payload_hash` | TEXT | no | sha256 of the normalised payload including the dataset version | generated |
| `actor_id` | TEXT | no | The actor the result is bound to | request |
| `command_id` | TEXT | no | Command name | generated |
| `status` | TEXT | no | HTTP-level status of the stored result | generated |
| `result` | JSONB | no | JSONB: the stored response | generated |
| `created_at` | TIMESTAMPTZ (default now()) | no | Row creation time (database clock) | generated by the database |

### dataset_versions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `dataset_version` | TEXT | no | Key (`ds-<12 hex>` from the seed) | generated by `data/seed.py` |
| `dataset_hash` | TEXT | no | sha256 of the canonical input JSON the seed loaded | generated by `data/seed.py` |
| `contract_version` | TEXT | no | `1` | `serviceflow.CONTRACT_VERSION` |
| `created_at` | TIMESTAMPTZ (default now()) | no | Row creation time (database clock) | generated by the database |

### schema_migrations
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `version` | TEXT | no | Migration file name | data/migrate.py |
| `checksum` | TEXT | no | sha256 of the file text | data/migrate.py |
| `applied_at` | TIMESTAMPTZ (default now()) | no | When it was applied (database clock) | data/migrate.py |

## 3. Foreign keys

| Child column | Parent | Note |
|---|---|---|
| `agent_skills.agent_id` | `agents.agent_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `agent_skills.skill_id` | `skills.skill_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `queue_skills.queue_id` | `queues.queue_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `queue_skills.skill_id` | `skills.skill_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `shifts.agent_id` | `agents.agent_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `shift_breaks.shift_id` | `shifts.shift_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `shift_breaks.agent_id` | `agents.agent_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `tickets.customer_id` | `customers.customer_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `tickets.queue_id` | `queues.queue_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `ticket_events.ticket_id` | `tickets.ticket_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `ticket_events.queue_id` | `queues.queue_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `ticket_events.agent_id` | `agents.agent_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `surveys.ticket_id` | `tickets.ticket_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `simulation_events.simulation_id` | `simulation_runs.simulation_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `rejected_records.batch_id` | `raw_batches.batch_id` | enforced in `0001` (no `ON DELETE` action: a referenced parent cannot be deleted) |
| `simulation_events.ticket_id` | (none) | logical only: a simulated ticket label, not a `tickets` row |
| `ticket_events.queue_id` (destination of a transfer) | `queues.queue_id` | enforced; the SOURCE queue of a transfer is the queue of the previous `created`/`queued`/`transferred` event (logical) |
| `audit_events.entity_id`, `rejected_records.id`, `command_results.idempotency_key` | (any entity) | logical |

## 4. Constraints, triggers and indexes

| Name | On | Rule |
|---|---|---|
| `queues_policy_ck` | `queues` | `priority_policy` in `fifo_within_priority`, `fifo` |
| `agents_employment_ck`, `agents_concurrency_ck` | `agents` | employment type enumerated; `max_concurrent >= 1` |
| `agent_skills_prof_ck` | `agent_skills` | proficiency 1..5 |
| `shifts_order_ck`, `shifts_break_ck`, `shifts_break_fit_ck` | `shifts` | `ends_at > starts_at`; `break_minutes >= 0`; the break fits inside the shift |
| `shift_breaks_order_ck` | `shift_breaks` | `ends_at > starts_at` |
| `sla_priority_ck`, `sla_minutes_ck` | `sla_policies` | priority P1..P3; both targets `> 0` |
| `tickets_priority_ck` | `tickets` | priority P1..P3 |
| `events_type_ck`, `events_agent_ck`, `events_bot_reply_ck` | `ticket_events` | the 11 event types; `service_started` needs an agent; a `replied_human` actor is never `bot-...` (P04-TEST-01) |
| `ticket_events_event_id_key` | `ticket_events` | `event_id` unique: a replay is refused by the database too |
| `surveys_score_ck`, `surveys_pair_ck` | `surveys` | score 1..5 or NULL; score and response time are both NULL or both set |
| `sim_runs_ck`, `sim_events_type_ck` | `simulation_runs`, `simulation_events` | warm-up `>= 0`, horizon `> 0`, replications `>= 1`; event types `service_started`, `resolved` |
| `raw_batches_status_ck` | `raw_batches` | `accepted`, `partial`, `rejected` |
| `ticket_events_immutable`, `ticket_events_no_truncate` | `ticket_events` | trigger: UPDATE, DELETE, TRUNCATE refused (`sf_forbid_mutation`) |
| `audit_events_append_only`, `simulation_events_append_only` | `audit_events`, `simulation_events` | trigger: UPDATE and DELETE refused |
| `tickets_arrival_fixed` | `tickets` | trigger: an UPDATE of `created_at` is refused (`ARRIVAL_IMMUTABLE`, P04-FLOW-04) |
| `ticket_events_ticket_idx`, `ticket_events_agent_idx`, `shifts_agent_idx`, `surveys_ticket_idx` | indexes | replay by ticket, intervals by agent, shifts by agent, surveys by ticket |

**Deliberately not a trigger:** "no two overlapping in-service intervals for one agent beyond `max_concurrent`". Intervals are derived from the event log and late arrivals keep their own `occurred_at`, so a row trigger would reject a valid out-of-order load; the rule is enforced by the application (domain ingest and C01/C03, serialised per agent by a row lock) and by `tests/test_adversarial.py` (P04-TEST-04; `docs/contracts.md` D-06).

## 5. Source-to-target mapping

**Source contracts.** Each entity file of `web/public/data` is `{"entity", "dataset_version", "rows": [...]}` with the field names of the table; the golden fixture `inputs.json` has the same shape. The 13 entity files are hashed together (`manifest.json` `dataset_hash`); `injection-manifest.json` and `manifest.json` are not entities.

| Entity file | Published rows | Target table | Loaded by | Accepted rows (snapshot) |
|---|---|---|---|---|
| `customers.json` | 1,004 | `customers` | `seed.py` | 1,004 |
| `queues.json` | 3 | `queues` | `seed.py` | 3 |
| `agents.json` | 18 | `agents` | `seed.py` | 18 |
| `skills.json` | 3 | `skills` | `seed.py` | 3 |
| `agent_skills.json` | 29 | `agent_skills` | `seed.py` | 29 |
| `queue_skills.json` | 3 | `queue_skills` | `seed.py` | 3 |
| `shifts.json` | 1,020 | `shifts` | `seed.py` | 1,020 |
| `shift_breaks.json` | 1,018 | `shift_breaks` | `prepare_snapshot.py` (no loader in `seed.py`, D-07) | 1,018 |
| `sla_policies.json` | 3 | `sla_policies` | `seed.py` | 3 |
| `tickets.json` | 3,826 | `tickets` | `seed.py` (rejects 9) | 3,817 |
| `ticket_events.json` | 21,948 | `ticket_events` | `seed.py` (rejects 55) | 21,893 |
| `surveys.json` | 2,153 | `surveys` | `seed.py` (rejects 6) | 2,147 |
| `simulation_runs.json` | 3 | `simulation_runs` (+ 206 `simulation_events` simulated by the seed) | `seed.py` | 3 |

**Event log to metrics.** The analysis views `sf_ev`, `sf_ticket`, `sf_interval` (`data/sql/analysis/00_event_views.sql`) are not tables; they derive, per accepted ticket and without code shared with the Python domain, the instants the metrics need.

| Derived field | Rule (D-01..D-09) | Source columns | Used by |
|---|---|---|---|
| first human reply | earliest `replied_human` whose actor is not `bot-...` | `ticket_events.event_type`, `actor_id`, `occurred_at` | first response (P04-MET-04), P90 (P04-MET-07) |
| first service | earliest `service_started` | `ticket_events.event_type`, `occurred_at` | wait to first service (D-09 R4-10) |
| final resolution | the last `resolved` that no later `reopened` follows, ordered by `(occurred_at, event_id)` | `ticket_events` | resolution (P04-MET-05), completions (P04-MET-02) |
| service interval | opens at `service_started`/`resumed` (first of a run of openers), closes at the next `paused`/`transferred`/`resolved`/`abandoned`; agent = the opening event's `agent_id` | `ticket_events` | handling (P04-MET-06), occupancy (P04-MET-09) |
| staffed available time | shift overlap with the window minus `break_minutes` only when the window covers the whole shift | `shifts` | occupancy (D-05) |
| abandonment | an `abandoned` event, rate only on chat and phone | `ticket_events`, `tickets.channel` | P04-MET-10 |
| valid survey response | `invited_at` set, `score` and `response_at` set; positive = score >= 4 | `surveys` | CSAT (P04-MET-11) |

Field-level mapping from these views to the BI facts is in `bi-package.md`; to the workbook's data sheets in `workbook.md`.

## 6. Known gaps and notes

* **Two hashes.** `dataset_versions.dataset_hash` is the sha256 of the canonical INPUT JSON the seed read (snapshot: `d5d7a5e1b7dffdec089785448e3ae1241fd12bdbce67f5c14eccad767c6c174c`, version `ds-d5d7a5e1b7df`); the generator's file hash is `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4` (`manifest.json`, version `sf-20261026-20261026`). Both are cited where they apply; the second is the dataset identity of the project.
* **`shift_breaks` has no loader in `seed.py`** (D-07, a later decision); the analysis package loads it itself.
* **INJ-02 is not detectable by the domain** (a reopen recorded as a new customer): `08` finds the four customers created at the instant of their only ticket, an analyst check.
* **Calendars are ignored** (D-09 R4-18): `sla_policies.calendar_id` and `queues.calendar_id` are carried; every policy uses the 24x7 calendar `cal-001` and a different calendar raises `SLA_CALENDAR_IGNORED`.
* **Row counts of `audit_events`, `command_results` and `quarantined`-style tables** are 0 in a seeded database; they fill only through the API.
* This file is checked against the migrations by `tests/test_artifacts.py` (every table and column appears here and in `erd.md`).
