# Data dictionary: Onboard Studio relational model (P02-ART-03)

All data in this model is **synthetic**: the golden fixture `onboard-studio-golden-v1` and the generated snapshot `os-20261026-20261026`
(seed 20261026, generator `dataset_hash` `3c20d296bcf178065e9178cae04f763994b4d7197026af2c021ab55b4cc2bc6a`, contract v1). Sources:
`data/migrations/0001_schema.sql` and `0002_constraints.sql`, `data/migrate.py`, `data/seed.py`, `docs/contracts.md` (rules cited as D-01..D-06),
`docs/api-contract.md` (commands C01..C10), `data/README-generator.md`. The ER diagram is `erd.md`.

Row counts are `SELECT count(*)` on a scratch database prepared by `data/sql/analysis/prepare_snapshot.py` (migrate, then `seed.py`
through the domain's `validate_batch` over `web/public/data`): 733 of the snapshot's 740 cases were accepted; 269 rejected rows (7 whole cases with their child rows,
plus 2 single approvals) were kept in `rejected_records`. The golden database holds 1 case.
Conventions: all instants are `TIMESTAMPTZ` read as UTC (D-01); durations are not stored, they are computed (hours as decimal strings at 4 dp,
rates at 6 dp, ROUND_HALF_UP; D-01, D-04); ids are `TEXT` keys supplied by the source. "FK" means a foreign key enforced in `0001`; "logical" means a join the
contract relies on that the database does not enforce. Constraint names are those of `0002`.

## 1. Business entities (one table per `inputs.json` entity, plus `workflow_requirements` and `document_reviews`)

| Table | Grain | Primary key | Rows (snapshot DB) | Update semantics |
|---|---|---|---|---|
| `organizations` | one customer organization | `organization_id` | 40 | Insert-only through seed; `segment` (`smb`, `mid_market`, `enterprise`) and `region` (`reg-north/south/east/west`) are attributes of the organization, not versioned. |
| `workflow_versions` | one version of a workflow template | `workflow_version_id`; unique `(template_id, version_number)` | 2 | **Immutable once `published_at` is set** (trigger `workflow_versions_immutable`, D-02). Created as a draft (`published_at` NULL), published by the single NULL-to-value update, which also writes `definition_hash`. |
| `step_definitions` | one step of one version | `step_definition_id`; unique `(workflow_version_id, sequence)` | 10 | Insert-only while the version is a draft; any INSERT/UPDATE/DELETE after publication is refused (`step_definitions_immutable`). |
| `dependencies` | one prerequisite edge between two steps of a version | `dependency_id`; unique `(step_definition_id, prerequisite_id)` | 8 | Same immutability as `step_definitions` (`dependencies_immutable`). `dependencies_self_ck` forbids a self edge; cycles are rejected at publish (Kahn, `DEPENDENCY_CYCLE`), not by a constraint. |
| `workflow_requirements` | one required document type of one version | `(workflow_version_id, document_type)` | 5 | The D-05 block turned into a table (D-06); immutable after publication (`workflow_requirements_immutable`). |
| `sla_rules` | the SLA of one version | `sla_rule_id`; unique `workflow_version_id` | 2 | Insert-only in the slice. Carries `business_minutes`, the versioned `pause_policy` and the calendar. `calendar_id` has no FK (logical join to `calendar_intervals`). |
| `calendar_intervals` | one working or holiday interval of a calendar | `calendar_interval_id` | 398 (392 working, 6 holiday) | Insert-only. Half-open `[starts_at, ends_at)`, `ends_at > starts_at` (`calendar_intervals_range_ck`). A holiday is subtracted from the working set; a holiday on a weekend subtracts nothing (D-01). |
| `cases` | one onboarding case | `case_id` | 733 (712 completed, 21 open) | `workflow_version_id` is fixed at creation (trigger `cases_no_reopen` refuses a change). A completed case cannot change `status`, `completed_at` or version: no reopen, a correction opens a new case linked by `linked_case_id` (D-03, P02-TEST-11). `version` is the optimistic-concurrency counter of the commands. |
| `step_instances` | one step of one case | `step_instance_id`; unique `(case_id, step_definition_id)` | 3,665 (3,623 started) | Updated by commands along `blocked, ready, in_progress, in_review, approved or changes_requested` (D-03); `version_number` increases when a rejected document sends the step back. |
| `assignments` | one assignee holding one step over an interval | `assignment_id` | 4,362 | `ended_at` NULL means open. Reassignment closes the prior row and never deletes it (D-03, P02-FLOW-07; the command C07 is 501 in the slice). Handoffs = distinct `(assignee_id, assigned_at)` rows per step minus 1 (P02-MET-08). |
| `document_versions` | one submitted version of one document type in one case | `document_version_id`; unique `(case_id, document_type, version_number)` | 2,153 (2,014 accepted, 139 rejected) | **Append-only** (trigger `document_versions_append_only`): a resubmission is a new row; the prior row is never edited. `review_status` records the status at insertion time. |
| `document_reviews` | one review decision on one document version | `review_id` | 0 in the seeded snapshot (written by the commands C03, accept-document) | **Append-only** (`document_reviews_append_only`). The effective status of a document version is its latest review; the seed carries the final status in `document_versions.review_status` instead. |
| `approvals` | one decision on one step version | `approval_id`; unique `(step_instance_id, version_number)` | 3,601 | Insert-only. The unique pair is the `DECISION_CONFLICT` guard: a second decision on the same step version fails (P02-TEST-02). |
| `waiting_intervals` | one period during which the case waits for a reason | `waiting_interval_id` | 874 (731 `customer_info_requested`, 143 `external_verification`; 10 still open) | Insert-only in the slice; `ends_at` NULL while open. Eligible reasons (those in `sla_rules.pause_policy`) are clipped to the case span and merged before deduction (D-06). |
| `case_events` | one timeline event of a case | `event_id` | 12,699 | Insert-only; index `case_events_case_idx (case_id, occurred_at)`. Event types in the snapshot: `case_opened`, `step_started`, `document_submitted`, `document_rejected`, `waiting_started`, `waiting_ended`, `step_approved`, `case_completed`. |

## 2. Operational tables (rejection, quarantine, audit, idempotency)

| Table | Grain | Primary key | Rows (snapshot DB) | Update semantics |
|---|---|---|---|---|
| `raw_batches` | one received input batch | `batch_id`; unique `idempotency_key` | 1 (the seed's batch, status `partial`) | Insert-only; `status` in `accepted`, `partial` (`raw_batches_status_ck`); the whole payload is kept as `JSONB` with its `payload_hash`. |
| `rejected_records` | one raw row refused at ingest | `(batch_id, entity, id, reason_code)` | 269 | Insert-only; FK `batch_id` to `raw_batches`; `raw_row` keeps the row exactly as it arrived. A rejected **case** is stored with every child row under the same reason (`MISSING_REQUIRED_DOCUMENT`, `PAUSE_REASON_NOT_CONFIGURED`, `SELF_APPROVAL`, ...); `DECISION_CONFLICT` rejects only the later approval. |
| `quarantined_records` | one record held back for repair | `(entity, id)` | 0 | Reserved for current-state quarantine as in Revenue Atlas; the Onboard Studio slice rejects rather than quarantines, so nothing writes to it (exposed by the reads API). |
| `audit_events` | one audit line per command | `event_id` | 0 in the seeded snapshot (written by commands) | **Append-only** (`audit_events_append_only`); written in the same transaction as the command it records (atomic audit). |
| `command_results` | one stored command result per idempotency key | `idempotency_key` | 0 in the seeded snapshot | Insert-only; the same key and payload replays the stored result, the same key with another payload is 409 `IDEMPOTENCY_KEY_REUSED`. |
| `dataset_versions` | one seeded dataset | `dataset_version` | 1 | Insert-only. Note: `seed.py` hashes the *input JSON* (`ds-<12 hex>`), which is not the generator's file hash in `manifest.json`; see section 5. |
| `schema_migrations` | one applied migration (created by `data/migrate.py`, not by the SQL files) | `version` | 2 | Holds the sha256 of each applied file; a changed file is refused. |

## 3. Columns

Types are PostgreSQL types as declared in `0001_schema.sql`. "Null" is whether the column accepts NULL.

### organizations
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `organization_id` | TEXT | no | Key (PK) | inputs `organizations` |
| `organization_name` | TEXT | no | Display name (synthetic; four are 60+ characters) | |
| `segment` | TEXT | no | `smb`, `mid_market`, `enterprise` (snapshot); `smb` in the golden fixture. Grouping key of the segment metrics | |
| `region` | TEXT | no | `reg-north`, `reg-south`, `reg-east`, `reg-west` (snapshot); `emea` in the golden fixture. Grouping key of the region metrics | |
| `created_at` | TIMESTAMPTZ | no | Creation instant | |

### workflow_versions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `workflow_version_id` | TEXT | no | Key (PK); a case binds one (D-02) | `workflow_versions` |
| `template_id` | TEXT | no | The workflow template; part of unique `(template_id, version_number)` | |
| `version_number` | INT | no | 1 or more (`workflow_versions_number_ck`); v1 = `wfv-001`, v2 = `wfv-002` | |
| `published_at` | TIMESTAMPTZ | yes | NULL = draft; once set the row, its steps, dependencies and requirements are immutable. v1 2025-03-10, v2 2025-10-01 (snapshot) | |
| `definition_hash` | TEXT | yes | sha256 of the compact sorted-key JSON of ordered steps and dependencies (D-05); required once published (`workflow_versions_hash_ck`) | computed by `workflow.definition_hash` |

### step_definitions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `step_definition_id` | TEXT | no | Key (PK) | `step_definitions` |
| `workflow_version_id` | TEXT | no | FK `workflow_versions` | |
| `step_name` | TEXT | no | `collect_documents`, `verify_identity` (v1 only), `collect_address_proof` (v2 only), `compliance_review`, `approve_account`, `activate_account`. The same name in v1 and v2 has different ids | |
| `required` | BOOLEAN | no | A required step must be approved before the case can complete (P02-FLOW-09) | |
| `role_key` | TEXT | no | `ops`, `compliance` or `reviewer`: the role a reviewer must hold to approve (P02-FLOW-06) | |
| `sequence` | INT | no | 0 or more (`step_definitions_seq_ck`); unique within the version | |

### dependencies
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `dependency_id` | TEXT | no | Key (PK) | `dependencies` |
| `step_definition_id` | TEXT | no | FK: the step that waits | |
| `prerequisite_id` | TEXT | no | FK: the step that must be approved first; not equal to `step_definition_id` | |
| `dependency_type` | TEXT | no | `mandatory` (default) or `optional` (`dependencies_type_ck`); only mandatory ones gate readiness | |
| `created_at` | TIMESTAMPTZ | yes | Creation instant | |

### workflow_requirements
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `workflow_version_id` | TEXT | no | PK part, FK `workflow_versions` | inputs block `workflow_requirements` (D-05) |
| `document_type` | TEXT | no | PK part: `identity_proof`, `business_registration` (v1); plus `address_proof` (v2) | |

### sla_rules
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `sla_rule_id` | TEXT | no | Key (PK) | `sla_rules` |
| `workflow_version_id` | TEXT | no | FK, unique: one rule per version | |
| `business_minutes` | NUMERIC(12,4) | no | Greater than 0 (`sla_rules_minutes_ck`); 480 in the fixture and snapshot | |
| `pause_policy` | TEXT[] | no | Reasons that pause the SLA (default empty); `customer_info_requested`, `external_verification` in the snapshot | |
| `calendar_id` | TEXT | no | Working calendar of the SLA (logical join to `calendar_intervals`; no FK) | |

### calendar_intervals
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `calendar_interval_id` | TEXT | no | Key (PK) | `calendar_intervals` |
| `calendar_id` | TEXT | no | Calendar the interval belongs to (`cal-001`) | |
| `starts_at`, `ends_at` | TIMESTAMPTZ | no | Half-open `[starts_at, ends_at)`, `ends_at > starts_at` | |
| `timezone` | TEXT | no | Explicit IANA zone of the calendar (`UTC` in the fixture; P02-DOMAIN-04) | |
| `kind` | TEXT | no | `working` (default) or `holiday` (`calendar_intervals_kind_ck`, D-06); the fixture rows carry none and take the default | optional field `kind` |

### cases
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `case_id` | TEXT | no | Key (PK) | `cases` |
| `organization_id` | TEXT | no | FK `organizations` | |
| `workflow_version_id` | TEXT | no | FK; never changes (`cases_no_reopen`) | |
| `status` | TEXT | no | `open` or `completed`; `(status = 'completed') = (completed_at IS NOT NULL)` (`cases_completion_ck`) | |
| `opened_at` | TIMESTAMPTZ | no | Start of the case span; the month of opening is the grouping of query 01 | |
| `completed_at` | TIMESTAMPTZ | yes | End of the span, `>= opened_at` (`cases_range_ck`); NULL for open cases | |
| `linked_case_id` | TEXT | yes | FK to `cases`: the completed case this one corrects (P02-TEST-11); not in `inputs.json` | commands only |
| `version` | INT | no | Concurrency counter, default 1; not in `inputs.json` | commands only |

### step_instances
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `step_instance_id` | TEXT | no | Key (PK) | `step_instances` |
| `case_id`, `step_definition_id` | TEXT | no | FKs; unique together | |
| `status` | TEXT | no | `blocked`, `ready`, `in_progress`, `in_review`, `approved`, `changes_requested` (`step_instances_status_ck`) | |
| `version_number` | INT | no | 1 or more, default 1; the decision version a second decision must not repeat | |
| `ready_at` | TIMESTAMPTZ | yes | Instant the last mandatory prerequisite was approved (D-03); NULL for steps never made ready | |
| `started_at` | TIMESTAMPTZ | yes | First `in_progress` instant; step waiting = business time `ready_at` to `started_at` (D-05) | |
| `approved_at` | TIMESTAMPTZ | yes | Approval instant | |

### assignments
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `assignment_id` | TEXT | no | Key (PK) | `assignments` |
| `step_instance_id` | TEXT | no | FK `step_instances`; index `assignments_step_idx` | |
| `assignee_id` | TEXT | no | Person holding the step (`ops-*`, `cmp-*`, `acc-*`); never a reviewer id except in the injected self-approvals | |
| `assigned_at` | TIMESTAMPTZ | no | Start of the interval | |
| `ended_at` | TIMESTAMPTZ | yes | End, `>= assigned_at` (`assignments_range_ck`); NULL while open | |

### document_versions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `document_version_id` | TEXT | no | Key (PK) | `document_versions` |
| `case_id` | TEXT | no | FK `cases` | |
| `document_type` | TEXT | no | `identity_proof`, `business_registration`, `address_proof`, `approval_form` (optional extra); unique with `case_id`, `version_number` | |
| `version_number` | INT | no | 1 or more; version 1 is the "first submission" of first-pass approval | |
| `content_hash` | TEXT | no | Synthetic placeholder `sha256:...`, never a real file (P02-FLOW-02) | |
| `review_status` | TEXT | no | `submitted`, `accepted`, `rejected` (`document_versions_status_ck`), as of insertion | |
| `submitted_at`, `reviewed_at` | TIMESTAMPTZ | no, yes | Submission and review instants | |

### document_reviews
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `review_id` | TEXT | no | Key (PK) | commands C03 and accept-document |
| `document_version_id` | TEXT | no | FK `document_versions` | |
| `decision` | TEXT | no | `accepted` or `rejected` (`document_reviews_decision_ck`) | |
| `reason` | TEXT | yes | Required for a rejection by the command (P02-FLOW-03) | |
| `reviewer_id` | TEXT | no | The reviewing person | |
| `decided_at` | TIMESTAMPTZ | no | Decision instant | |

### approvals
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `approval_id` | TEXT | no | Key (PK) | `approvals` |
| `step_instance_id` | TEXT | no | FK `step_instances` | |
| `reviewer_id` | TEXT | no | Approving reviewer (`rev-001..008`); must hold `role_key` and not be an assignee of the step (`SELF_APPROVAL`) | |
| `decision` | TEXT | no | `approved`, `rejected`, `changes_requested` (`approvals_decision_ck`); all 3,601 accepted rows are `approved` | |
| `decided_at` | TIMESTAMPTZ | no | Decision instant; latency from `started_at` is the review time of query 04 | |
| `reason` | TEXT | yes | Free text | |
| `version_number` | INT | no | 1 or more (`approvals_version_ck`); the seed fills it from the step instance when the input has none; unique with `step_instance_id` | |

### waiting_intervals
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `waiting_interval_id` | TEXT | no | Key (PK) | `waiting_intervals` |
| `case_id` | TEXT | no | FK `cases` | |
| `reason_code` | TEXT | no | `customer_info_requested`, `external_verification` in the snapshot; eligible when listed in the rule's `pause_policy` | |
| `starts_at` | TIMESTAMPTZ | no | Start | |
| `ends_at` | TIMESTAMPTZ | yes | End, `>= starts_at` (`waiting_intervals_range_ck`); NULL while open (clipped to `completed_at` in completed cases) | |

### case_events
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `event_id` | TEXT | no | Key (PK) | `case_events` |
| `case_id` | TEXT | no | FK `cases` | |
| `event_type` | TEXT | no | See section 1 | |
| `actor_id` | TEXT | no | The person or role that caused the event | |
| `occurred_at` | TIMESTAMPTZ | no | Event instant | |

### raw_batches
| Field | Type | Null | Meaning and rule |
|---|---|---|---|
| `batch_id` | TEXT | no | PK (`batch-seed-<hash16>` for the seed) |
| `received_at` | TIMESTAMPTZ | no | Default `now()` |
| `idempotency_key` | TEXT | no | Unique |
| `payload_hash` | TEXT | no | sha256 of the canonical JSON of the payload |
| `payload` | JSONB | no | The batch as received |
| `status` | TEXT | no | `accepted` or `partial` (`raw_batches_status_ck`) |

### rejected_records
| Field | Type | Null | Meaning and rule |
|---|---|---|---|
| `entity` | TEXT | no | The refused row's table (PK with `batch_id`, `id`, `reason_code`) |
| `id` | TEXT | no | The refused row's key |
| `reason_code` | TEXT | no | Stable code, e.g. `SELF_APPROVAL` (section 5) |
| `raw_row` | JSONB | no | The row exactly as received |
| `batch_id` | TEXT | no | FK `raw_batches` |

### quarantined_records
| Field | Type | Null | Meaning and rule |
|---|---|---|---|
| `entity` | TEXT | no | PK part |
| `id` | TEXT | no | PK part |
| `reason_code` | TEXT | no | Why the row is held back (unused in the slice) |
| `raw_row` | JSONB | no | The held row |
| `batch_id` | TEXT | yes | Originating batch (no FK) |

### audit_events
| Field | Type | Null | Meaning and rule |
|---|---|---|---|
| `event_id` | TEXT | no | PK |
| `entity_type` | TEXT | no | The kind of row changed |
| `entity_id` | TEXT | no | Its key (by value, no FK) |
| `action` | TEXT | no | The command or transition |
| `actor_id` | TEXT | no | The person who acted (from `X-Actor-Id`) |
| `occurred_at` | TIMESTAMPTZ | no | Default `now()` |
| `before_version` | INT | yes | Version counter before the change |
| `after_version` | INT | yes | Version counter after the change |
| `reason` | TEXT | yes | Reason given, if any |
| `request_id` | TEXT | yes | Request correlation id |

### command_results
| Field | Type | Null | Meaning and rule |
|---|---|---|---|
| `idempotency_key` | TEXT | no | PK |
| `payload_hash` | TEXT | no | Replay fingerprint |
| `command_id` | TEXT | no | The command (C01..C09, P) |
| `status` | TEXT | no | Outcome |
| `result` | JSONB | no | Stored response |
| `created_at` | TIMESTAMPTZ | no | Default `now()` |

### dataset_versions
| Field | Type | Null | Meaning and rule |
|---|---|---|---|
| `dataset_version` | TEXT | no | PK |
| `dataset_hash` | TEXT | no | sha256 of the canonical JSON the seed was given |
| `contract_version` | TEXT | no | `v1` |
| `created_at` | TIMESTAMPTZ | no | Default `now()` |

## 4. Constraints, triggers and indexes that carry business rules (`0002_constraints.sql`)

| Rule | Mechanism | Contract |
|---|---|---|
| Published version, steps, dependencies and requirements are immutable | triggers `workflow_versions_immutable`, `step_definitions_immutable`, `dependencies_immutable`, `workflow_requirements_immutable` (functions `os_workflow_version_immutable`, `os_definition_immutable`); the NULL-to-published update is the one allowed change | D-02, P02-TEST-04 |
| Documents, reviews and audit events are append-only | triggers `document_versions_append_only`, `document_reviews_append_only`, `audit_events_append_only` (function `os_forbid_mutation`) | D-03, P02-TEST-06 |
| A completed case cannot be reopened or re-dated; a case keeps its version | trigger `cases_no_reopen` (function `os_case_no_reopen`) | D-03, P02-TEST-11 |
| A second decision on a step version conflicts | `approvals` unique `(step_instance_id, version_number)` | D-03, P02-TEST-02 |
| Non-negative, ordered intervals | `calendar_intervals_range_ck`, `cases_range_ck`, `assignments_range_ck`, `waiting_intervals_range_ck` | D-01 |
| Not enforced by the database | dependency cycles (rejected at publish by Kahn's algorithm), reviewer role and independence (command and ingest), required documents (ingest and `complete-case`), `sla_rules.calendar_id` existence | D-02, D-03 |
| Indexes | `cases_opened_idx`, `cases_org_idx`, `step_instances_case_idx`, `assignments_step_idx`, `document_versions_case_idx`, `waiting_intervals_case_idx`, `case_events_case_idx`, `calendar_intervals_cal_idx` | access paths of the analysis queries |

## 5. Source-to-target mapping and the metric fields they feed

`inputs.json` (golden) and the published snapshot `web/public/data/<entity>.json` carry the same 13 entity lists plus the `workflow_requirements`
block. `data/seed.py` loads each accepted row with `ON CONFLICT DO NOTHING`, workflow versions as drafts that are published last.

| inputs.json entity | Target table | Columns not in the input | Fields consumed by the metrics (`expected.json` keys) |
|---|---|---|---|
| `organizations` | `organizations` | none | `segment`, `region`: grouping of every metric |
| `workflow_versions` | `workflow_versions` | `definition_hash` computed when absent | `workflow_version_id`: grouping; `published_at`: comparability window |
| `step_definitions` | `step_definitions` | none | `step_name`, `role_key`; key of `step_waiting_time_hours` |
| `dependencies` | `dependencies` | `dependency_type` defaults to `mandatory` | step readiness; not a metric input |
| `workflow_requirements` (block) | `workflow_requirements` | one row per required type | `document_completeness` |
| `sla_rules` | `sla_rules` | none | `business_minutes`, `pause_policy`, `calendar_id`: `paused_time_hours`, `paused_business_overlap_hours`, `active_elapsed_hours`, `sla_attainment`, `within_sla_cases` |
| `calendar_intervals` | `calendar_intervals` | `kind` defaults to `working` | `business_cycle_time_hours`, `paused_business_overlap_hours`, `step_waiting_time_hours` (working set minus holidays) |
| `cases` | `cases` | `linked_case_id`, `version` | `opened_at`, `completed_at`: `calendar_cycle_time_hours`, `open_backlog_at_cutoff`, `completed_eligible_cases` |
| `step_instances` | `step_instances` | none | `ready_at`, `started_at`: `step_waiting_time_hours` |
| `assignments` | `assignments` | none | `handoff_count` (distinct `(assignee_id, assigned_at)` per step minus 1) |
| `document_versions` | `document_versions` | none | `rework_rate` (any rejected version), `first_pass_approval` (version 1 per case and type), `document_completeness` |
| `approvals` | `approvals` | `version_number` filled from the step instance | review time of query 04; the `SELF_APPROVAL` and `DECISION_CONFLICT` rules |
| `waiting_intervals` | `waiting_intervals` | none (`pause_requested` is read by ingest, not stored) | `paused_time_hours`, `paused_business_overlap_hours`, `active_elapsed_hours` |
| `case_events` | `case_events` | none | the timeline; no metric reads it |
| (rejected rows) | `raw_batches`, `rejected_records` | `batch_id`, `reason_code` | counts of query 08 |
| (seed run) | `dataset_versions` | `ds-<sha256(input)[:12]>` | provenance |

Two hashes exist and must not be confused: the generator's `dataset_hash` (`3c20d296...cc2bc6a`) is sha256 over the 14 entity files and identifies the published
snapshot; `dataset_versions.dataset_hash` (`399038e6f2ec...`) is sha256 over the canonical JSON the seed was given in the analysis database
(`prepare_snapshot.py` rebuilds that input from the files, so it is a different byte string).

### Rejection and quarantine codes (what lands in `rejected_records`)
| Code | Rejects | Injected defect (snapshot) | Rows kept |
|---|---|---|---|
| `MISSING_REQUIRED_DOCUMENT` | the case and all child rows | INJ-01: `case-000218`, `case-000545` | 70 |
| `DECISION_CONFLICT` | only the later approval | INJ-02: `apr-000623`, `apr-003152` | 2 |
| `PAUSE_REASON_NOT_CONFIGURED` | the case and all child rows | INJ-09: `case-000138`, `case-000473`, `case-000541` | 113 |
| `SELF_APPROVAL` | the case and all child rows | INJ-10: `case-000075`, `case-000685` | 84 |
| (flag, not a rejection) `PAUSE_OUTSIDE_WORKING_INTERVAL` | nothing: accepted, 0 business hours, counted | INJ-03: `wi-00396`, `wi-00704`, `wi-00753` | 0 (returned by the metrics) |

The remaining defects (INJ-04..07, 11, 12) exist only as command replays (`data/injection-events.json`) because the seed would reject or the triggers forbid them;
INJ-08 (two weekend holidays) is data and subtracts nothing. The snapshot totals 269 rows = 2 + 70 + 113 + 84 (query 08).
