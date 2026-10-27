# Data dictionary: TrustLedger relational model (P07-ART-03)

Dataset `tl-20261026-20261026` (seed 20261026, generator `dataset_hash` `a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff`), contract v1, code revision `0b5d686`. **Synthetic data only**: every owner, dataset, row, issue, edge, definition and customer record is generated; nothing is a real person, organisation or record (P07-DOMAIN-06).
How to read it without installing anything: section 1 lists every table with its grain, key and update rule; section 2 every column; section 3 the foreign keys; section 4 the constraints and triggers; section 5 maps each source file of the published snapshot to its table and to the figures it feeds; section 6 states the gaps. Row counts are those of the loaded snapshot at its as-of **2026-10-05T00:00:00Z** (the scratch database `data/sql/analysis/prepare_snapshot.py` builds), reconciled to `web/public/data/manifest.json` `row_counts` by `data/sql/analysis/run_all.py`.
The relational model is created by `data/migrations/0001_schema.sql`, `0002_constraints.sql` and `0003_review_r7.sql` (applied in order by `data/migrate.py`, which also creates `schema_migrations`). `verification_truth` is deliberately not a migration. Instants are `TIMESTAMPTZ` (UTC); proportions are never stored: every ratio is derived by the metrics (D-05).

## 1. Tables, grain, keys and update semantics
Entity grain is the row; "append-only" means a trigger refuses UPDATE, DELETE and TRUNCATE (`tl_forbid_mutation`).

| Table | Grain | Key | Update semantics | Rows (snapshot) |
|---|---|---|---|---|
| `tl_timezones` | one row per IANA zone name the server knows | name | written by 0001 only (a copy of pg_timezone_names, which scans the zone files on every read) | 499 (this server) |
| `owners` | one row per accountable person (synthetic names) | owner_id | loaded; an owner is deactivated by setting `active` false with a `deactivated_at` (D-07: stored data is not edited by a command) | 18 (15 active, 3 inactive) |
| `datasets` | one row per registered dataset | dataset_id | loaded or registered by C01; schedule fields and `last_refreshed_at` stay as loaded (a later refresh is a `dataset_refreshes` row) | 40 |
| `fields` | one row per field of a dataset | field_id | loaded | 420 |
| `dataset_rows` | one row per version of one measured record of a dataset | (dataset_id, ordinal); unique (dataset_id, row_id, row_version) | append-only (trigger): C11 adds a new `row_version`, nothing is edited | 2,554 (30 datasets; all row_version 1) |
| `quality_rules` | one current row per rule | rule_id | only `status`, `disabled_at` and `disabled_reason` ever change, active -> disabled once (`tl_rule_guard`); no delete | 60 (55 active at the as-of, 5 disabled) |
| `quality_rule_versions` | one row per version of a rule | (rule_id, version_number) | append-only (trigger) | 75 (60 current versions + 15 earlier) |
| `rule_weight_versions` | one row per weight version | weight_version | append-only (trigger); a change is a new version, never an edit | 2 (`w1` from 2026-01-01, `w2` from 2026-09-01) |
| `checklist_versions` | one row per contract checklist version | checklist_version | append-only (trigger) | 1 (`cl-1`: definition, grain, source_fields, owner, refresh) |
| `ledger_config` | the single configuration row a dataset travels with | id (always 1) | loaded once | 1 |
| `rule_runs` | one row per rule run | rule_run_id | append-only (trigger) | 4,609 (4,257 scheduled, 352 reruns; 2,568 under w1, 2,041 under w2) |
| `issues` | one row per issue (one issue per failing scheduled run) | issue_id; unique rule_run_id | `status`, `closed_at`, `verification_run_id`, `reopened_at` and `due_at` change by C05/C10; the run, the severity and `detected_at` never do (`tl_issue_guard`) | 574 (315 resolved, 99 claimed, 160 open at the as-of) |
| `issue_events` | one row per lifecycle event of an issue | event_id | append-only (trigger) | 1,328 (574 detected, 422 claimed, 323 verified, 9 reopened) |
| `lineage_edges` | one row per lineage edge | edge_id | append-only (trigger) | 160 (80 declared, 70 observed, 10 inferred) |
| `metric_versions` | one row per version of a metric definition | metric_version_id; unique (metric_id, version_number) | append-only (trigger): a change is a new row | 45 (30 published + 15 superseded; 30 metrics) |
| `definition_changes` | one row per change of a definition (a version 2 or later) | change_id; unique metric_version_id | append-only (trigger) | 15 |
| `customer_records` | one row per source customer record (synthetic) | record_id | append-only (trigger) | 2,000 (crm 759, billing 676, support 565) |
| `match_candidates` | one row per proposed pair, stored once in canonical order | candidate_id; unique (left_record_id, right_record_id) | append-only (trigger) | 400 (207 flagged as a possible household) |
| `merge_decisions` | one row per human decision: approve, reject or reverse | merge_id; unique reverses_merge_id | append-only (trigger); `tl_decision_guard` refuses a decision by the proposer and a reversal of anything but an approval of the same candidate | 235 (174 approve, 46 reject, 15 reverse) |
| `dataset_refreshes` | one row per recorded refresh of a dataset (C12) | (dataset_id, refreshed_at) | append-only (trigger) | 0 on the snapshot |
| `rejected_records` | one row per rejected raw input row | (batch_id, entity, id, reason_code, ordinal) | append-only (trigger) | 0 on the snapshot (nothing was rejected) |
| `audit_events` | one row per audited action, including refusals | event_id | append-only (trigger) | 0 on the snapshot (produced by the API) |
| `command_results` | one row per executed command, keyed by its idempotency key | idempotency_key | append-only (trigger) | 0 on the snapshot (produced by the API) |
| `dataset_versions` | one row per load of a dataset | dataset_version | inserted by the seeder; commands do not bump it | 1 (`tl-20261026-20261026`) |
| `verification_truth` | one row per customer record: the synthetic true entity | record_id | NOT a migration (`data/sql/verification_truth.sql`): created and loaded only by a test or reviewer (here `prepare_snapshot.py`); the matcher, the API and the seeder never read it | 2,000 (1,646 true entities) |
| `schema_migrations` | one row per applied migration | version | written by `data/migrate.py` (created by the migrator, not by a migration file) | 3 (0001, 0002, 0003) |

**Deletion policy.** Nothing is deleted: rows are versioned or superseded (`dataset_rows.row_version`, `metric_versions` and `quality_rule_versions`, `rule_weight_versions`), disabled with a reason (`quality_rules`), reversed by a new decision (`merge_decisions`) or appended (`dataset_refreshes`, `issue_events`, `audit_events`). The only deletes in the tree are `migrate.py --reset` (scratch and test databases) and the scratch databases of this package.
**Append-only events and versioned definitions.** Runs, decisions, edges, events, audits, command results and the weight and checklist versions can only be inserted; a published definition is never rewritten in place (a change is a new `metric_versions` row plus a `definition_changes` row with the reason and approver, P07-FLOW-02); a rule's identity and definition never change (`tl_rule_guard`) and a disabled rule stays disabled with its reason and date (P07-FLOW-09).

## 2. Columns

### tl_timezones
*Grain: one row per IANA zone name the server knows. Key: name.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `name` | TEXT | no | IANA zone name; a dataset's `refresh_timezone` must be one of them (`tl_valid_tz`) |

### owners
*Grain: one row per accountable person (synthetic names). Key: owner_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `owner_id` | TEXT | no | key, e.g. `own-09` |
| `owner_name` | TEXT | no | synthetic person name, never empty |
| `team` | TEXT | no | one of six teams (Customer Data, Data Governance, Data Platform, Finance Systems, Supply Chain, Support Operations) |
| `role` | TEXT | no | `analyst`, `steward` or `admin`: the role the API accepts for this actor (D-10 R7-03) |
| `active` | BOOLEAN | no | false when the owner has left |
| `deactivated_at` | TIMESTAMPTZ | yes | required when `active` is false (`owners_inactive_ck`); an owner is accountable at the as-of when it is active or deactivated after it |

### datasets
*Grain: one row per registered dataset. Key: dataset_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `dataset_id` | TEXT | no | key, e.g. `ds-customers` |
| `dataset_name` | TEXT | no | display name |
| `source_system` | TEXT | no | one of six source systems (crm, billing, support, ...) |
| `owner_id` | TEXT | no | the accountable owner (never empty, `datasets_class_ck`); the foreign key to `owners` |
| `classification` | TEXT | no | never empty (a dataset is registered only with an owner and a classification, D-02) |
| `registered_at` | TIMESTAMPTZ | no | when it was registered; a dataset registered after the as-of does not exist yet |
| `monitored` | BOOLEAN | no | true when timeliness is judged |
| `refresh_timezone` | TEXT | yes | IANA zone of the schedule; required when monitored (`datasets_schedule_ck`) |
| `refresh_local_time` | TEXT | yes | `HH:MM` on the dataset's own clock; required when monitored |
| `refresh_grace_minutes` | INT | yes | 0..1439; required when monitored |
| `last_refreshed_at` | TIMESTAMPTZ | yes | the latest refresh as loaded (null: never refreshed) |
| `registered_by` | TEXT | yes | the actor or `seed` |

### fields
*Grain: one row per field of a dataset. Key: field_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `field_id` | TEXT | no | key, e.g. `fld-0002` |
| `dataset_id` | TEXT | no | the dataset |
| `field_name` | TEXT | no | column name in the rows |
| `data_type` | TEXT | no | declared type name |
| `nullable` | BOOLEAN | no | declared nullability |

### dataset_rows
*Grain: one row per version of one measured record of a dataset. Key: (dataset_id, ordinal); unique (dataset_id, row_id, row_version).*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `dataset_id` | TEXT | no | the dataset |
| `ordinal` | INT | no | position of the record in the dataset (the first version's position is kept) |
| `row_id` | TEXT | no | the record's id within the dataset |
| `data` | JSONB | no | one flat JSON object of text, integer, boolean or null; floats and nested values are refused (`MALFORMED_RECORD`) |
| `row_version` | INT | no | 1 for a loaded row; a correction is version n+1 |
| `supersedes_row_id` | TEXT | yes | `<row_id>@<previous version>`; null for version 1 (`dataset_rows_version_ck`) |
| `reason` | TEXT | yes | required for a correction |
| `corrected_by` | TEXT | yes | the actor of a correction |
| `recorded_at` | TIMESTAMPTZ | yes | the server instant of a correction; null for the rows loaded with the dataset (measurement reads the latest version recorded by the as-of) |

### quality_rules
*Grain: one current row per rule. Key: rule_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `rule_id` | TEXT | no | key, e.g. `r-customers-unique-customer_key` |
| `dataset_id` | TEXT | no | the dataset measured |
| `field_id` | TEXT | yes | the field measured (null for timeliness) |
| `rule_type` | TEXT | no | the dimension: `completeness`, `validity`, `uniqueness`, `relationship` or `timeliness` |
| `severity` | TEXT | no | `low`, `medium`, `high` or `critical` |
| `version_number` | INT | no | the current rule version (earlier definitions are in `quality_rule_versions`) |
| `status` | TEXT | no | `active` or `disabled` |
| `disabled_at` | TIMESTAMPTZ | yes | when it was disabled (required with `disabled`) |
| `disabled_reason` | TEXT | yes | required with `disabled` (disabling is not repair: runs and issues stay) |
| `definition` | JSONB | no | JSON: `field`, optional `filter {field, equals}`, `pattern` (validity), `parent_dataset_id` and `parent_field` (relationship); a pattern may not use `\s \d \w \b` (`rules_pattern_portable_ck`) |

### quality_rule_versions
*Grain: one row per version of a rule. Key: (rule_id, version_number).*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `rule_id` | TEXT | no | the rule |
| `version_number` | INT | no | 1..n; the current version equals the rule's own row |
| `rule_type` | TEXT | no | dimension of that version |
| `severity` | TEXT | no | severity of that version |
| `definition` | JSONB | no | the eligibility and pattern of that version (so an earlier denominator is readable) |
| `valid_from` | TIMESTAMPTZ | yes | when the version took effect (null when the loader does not know it) |

### rule_weight_versions
*Grain: one row per weight version. Key: weight_version.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `weight_version` | TEXT | no | key, e.g. `w2` |
| `valid_from` | TIMESTAMPTZ | no | the version in force at an instant is the latest `valid_from` not after it |
| `weights` | JSONB | no | JSON with exactly the five dimensions, each in [0, 1], summing to 1 (`weights_valid_ck`) |

### checklist_versions
*Grain: one row per contract checklist version. Key: checklist_version.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `checklist_version` | TEXT | no | key |
| `items` | JSONB | no | JSON list of the checklist items |

### ledger_config
*Grain: the single configuration row a dataset travels with. Key: id (always 1).*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INT | no | always 1 |
| `whitespace_policy` | JSONB | no | JSON `{name: trim_empty_is_missing, trim_characters}`: a value that is null or empty after trimming those characters is missing |
| `checklist_version` | TEXT | no | the checklist applied |
| `probes` | JSONB | no | JSON probes (e.g. `definition_at`) |

### rule_runs
*Grain: one row per rule run. Key: rule_run_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `rule_run_id` | TEXT | no | key, e.g. `rr-00007` |
| `rule_id` | TEXT | no | the rule run |
| `rule_version` | INT | no | the rule version it was made under; two runs are comparable only when it is the same |
| `weight_version` | TEXT | no | the weight version in force when it ran |
| `kind` | TEXT | no | `scheduled` or `rerun` (a rerun names its issue: `runs_kind_ck`) |
| `run_at` | TIMESTAMPTZ | no | when the run was made |
| `eligible_count` | INT | no | rows the rule measured |
| `failure_count` | INT | no | failing rows, at most `eligible_count` (`runs_counts_ck`) |
| `rerun_for_issue` | TEXT | yes | the issue a rerun re-checks (null for a scheduled run) |
| `details` | JSONB | no | JSON extras (populated_count, null_fk_count, failing record ids); empty on the seeded snapshot |
| `run_by` | TEXT | yes | the actor or `seed` |

### issues
*Grain: one row per issue (one issue per failing scheduled run). Key: issue_id; unique rule_run_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `issue_id` | TEXT | no | key, e.g. `iss-0461` |
| `rule_run_id` | TEXT | no | the failing scheduled run that opened it (unique) |
| `severity` | TEXT | no | the rule's severity at detection |
| `owner_id` | TEXT | no | the accountable owner of the issue |
| `status` | TEXT | no | `open`, `investigating` or `closed`; `resolved` and `claimed` are derived (D-07) |
| `detected_at` | TIMESTAMPTZ | no | the failing run's `run_at`; kept across reopen cycles |
| `due_at` | TIMESTAMPTZ | yes | set at triage |
| `closed_at` | TIMESTAMPTZ | yes | required when closed; kept on reopen |
| `verification_run_id` | TEXT | yes | the rerun that verified it; accepted only if it is a passing rerun of the same rule and version for this issue |
| `reopened_at` | TIMESTAMPTZ[] | no | timestamps of the reopen cycles (only ever appended) |
| `record_ids` | JSONB | yes | failing record ids the issue covers (null on the seeded snapshot: C10 reruns the whole rule) |
| `version` | INT | no | optimistic-concurrency counter |

### issue_events
*Grain: one row per lifecycle event of an issue. Key: event_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `event_id` | TEXT | no | key |
| `issue_id` | TEXT | no | the issue |
| `event_type` | TEXT | no | `detected`, `triaged`, `claimed`, `verified`, `verification_failed` or `reopened` |
| `occurred_at` | TIMESTAMPTZ | no | when |
| `actor_id` | TEXT | yes | who (`seed` on the snapshot) |
| `details` | JSONB | no | JSON extras |

### lineage_edges
*Grain: one row per lineage edge. Key: edge_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `edge_id` | TEXT | no | key, e.g. `ed-001`, `eo-001` |
| `source_dataset_id` | TEXT | no | upstream dataset (never equal to the target: `edges_evidence_ck`) |
| `target_dataset_id` | TEXT | no | downstream dataset |
| `evidence_type` | TEXT | no | `declared`, `observed` or `inferred`; the graphs are kept separate and an inferred edge is never observed |
| `observed_at` | TIMESTAMPTZ | yes | present exactly when the evidence is `observed` |

### metric_versions
*Grain: one row per version of a metric definition. Key: metric_version_id; unique (metric_id, version_number).*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `metric_version_id` | TEXT | no | key, e.g. `mv-net-revenue-2` |
| `metric_id` | TEXT | no | the metric |
| `metric_name` | TEXT | no | display name |
| `version_number` | INT | no | 1..n |
| `definition` | TEXT | yes | the written definition (checklist item) |
| `grain` | TEXT | yes | the grain (checklist item) |
| `source_fields` | JSONB | yes | JSON list of `dataset.field` names (checklist item) |
| `owner_id` | TEXT | yes | the owner (checklist item; must exist in `owners`) |
| `refresh` | TEXT | yes | refresh cadence (checklist item) |
| `valid_from` | TIMESTAMPTZ | no | when the version took effect |
| `status` | TEXT | no | `draft`, `reviewed`, `published` or `superseded` (C02 steps draft -> reviewed -> published; only published versions count) |
| `published_by` | TEXT | yes | the approver (`seed` on the snapshot) |

### definition_changes
*Grain: one row per change of a definition (a version 2 or later). Key: change_id; unique metric_version_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `change_id` | TEXT | no | key, e.g. `dc-csat-score-2` |
| `metric_version_id` | TEXT | no | the new version |
| `previous_metric_version_id` | TEXT | yes | the version it replaced |
| `reason` | TEXT | no | never empty |
| `approved_by` | TEXT | no | the approver |
| `changed_at` | TIMESTAMPTZ | no | equals the new version's `valid_from` |

### customer_records
*Grain: one row per source customer record (synthetic). Key: record_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `record_id` | TEXT | no | key, e.g. `rec-0394` |
| `source_system` | TEXT | no | crm, billing or support |
| `source_customer_id` | TEXT | no | id in the source system |
| `normalized_name` | TEXT | no | normalised synthetic name |
| `address_key` | TEXT | no | normalised synthetic address key |

### match_candidates
*Grain: one row per proposed pair, stored once in canonical order. Key: candidate_id; unique (left_record_id, right_record_id).*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `candidate_id` | TEXT | no | key, e.g. `cand-0161` |
| `left_record_id` | TEXT | no | the smaller record id in code-point order (`candidates_canonical_ck`) |
| `right_record_id` | TEXT | no | the larger; a merge maps it to the left |
| `score` | NUMERIC(7,6) | no | in [0, 1], 6 places |
| `features` | JSONB | no | JSON of decimal-string features (non-empty) |
| `explanation` | TEXT | no | never empty |
| `uncertainty` | TEXT | yes | e.g. `Shared name and address; possible household`; a candidate is never an automatic merge |
| `proposed_by` | TEXT | no | an owner id (the separation-of-duties check compares it with the reviewer) |
| `proposed_at` | TIMESTAMPTZ | no | when proposed |

### merge_decisions
*Grain: one row per human decision: approve, reject or reverse. Key: merge_id; unique reverses_merge_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `merge_id` | TEXT | no | key, e.g. `md-0095` |
| `candidate_id` | TEXT | no | the candidate |
| `reviewer_id` | TEXT | no | the reviewer (never the proposer) |
| `decision` | TEXT | no | `approve`, `reject` or `reverse` |
| `decided_at` | TIMESTAMPTZ | no | when |
| `reverses_merge_id` | TEXT | yes | the approval a reversal undoes (present exactly for `reverse`) |
| `reason` | TEXT | yes | required for a reversal |

### dataset_refreshes
*Grain: one row per recorded refresh of a dataset (C12). Key: (dataset_id, refreshed_at).*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `dataset_id` | TEXT | no | the dataset |
| `refreshed_at` | TIMESTAMPTZ | no | when it refreshed (not in the future, not before registration) |
| `recorded_at` | TIMESTAMPTZ | no | the server instant of the record |
| `recorded_by` | TEXT | no | the actor |

### rejected_records
*Grain: one row per rejected raw input row. Key: (batch_id, entity, id, reason_code, ordinal).*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `batch_id` | TEXT | no | the load |
| `entity` | TEXT | no | the entity of the rejected row |
| `id` | TEXT | no | its id |
| `reason_code` | TEXT | no | e.g. `OWNER_REQUIRED`, `DUPLICATE_PAIR`, `NON_CANONICAL_ORDER`, `REVIEWER_IS_PROPOSER`, `DEPENDENT_REJECTED` |
| `raw_row` | JSONB | no | the raw row as received |
| `ordinal` | INT | no | separates repeated occurrences of one id |
| `created_at` | TIMESTAMPTZ | no | when kept |

### audit_events
*Grain: one row per audited action, including refusals. Key: event_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `event_id` | TEXT | no | key |
| `entity_type` | TEXT | no | what was acted on |
| `entity_id` | TEXT | no | its id |
| `action` | TEXT | no | what was done |
| `actor_id` | TEXT | no | who |
| `actor_role` | TEXT | yes | the register's role |
| `occurred_at` | TIMESTAMPTZ | no | server instant |
| `before_version` | INT | yes | version before |
| `after_version` | INT | yes | version after |
| `reason` | TEXT | yes | why (refusals state the code) |
| `request_id` | TEXT | yes | the client's request id |
| `details` | JSONB | no | JSON extras |

### command_results
*Grain: one row per executed command, keyed by its idempotency key. Key: idempotency_key.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `idempotency_key` | TEXT | no | client key |
| `payload_hash` | TEXT | no | hash of the payload including the dataset version |
| `actor_id` | TEXT | no | the actor bound to the key |
| `actor_role` | TEXT | no | the role bound to the key |
| `command_id` | TEXT | no | e.g. `C07` |
| `status` | TEXT | no | outcome |
| `result` | JSONB | no | the stored result, replayed on a repeat |
| `created_at` | TIMESTAMPTZ | no | server instant |

### dataset_versions
*Grain: one row per load of a dataset. Key: dataset_version.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `dataset_version` | TEXT | no | key; a command carrying another value is `STALE_DATASET_VERSION` |
| `dataset_hash` | TEXT | no | sha256 of the generator's output: `a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff` |
| `contract_version` | TEXT | no | `1` |
| `as_of` | TIMESTAMPTZ | yes | the dataset's as-of (2026-10-05T00:00:00Z) |
| `created_at` | TIMESTAMPTZ | no | when loaded |

### verification_truth
*Grain: one row per customer record: the synthetic true entity. Key: record_id.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `record_id` | TEXT | no | the customer record |
| `true_entity` | TEXT | no | the synthetic true entity id, e.g. `E-1233`; precision is computed from it, never the matcher |

### schema_migrations
*Grain: one row per applied migration. Key: version.*

| Column | Type | Null | Meaning |
|---|---|---|---|
| `version` | TEXT | no | the migration file name |
| `checksum` | TEXT | no | sha256 of its text; a changed applied file is refused |
| `applied_at` | TIMESTAMPTZ | no | when applied |

## 3. Foreign keys
| From | To |
|---|---|
| `datasets.owner_id` | `owners.owner_id` |
| `fields.dataset_id`, `dataset_rows.dataset_id`, `quality_rules.dataset_id`, `dataset_refreshes.dataset_id` | `datasets.dataset_id` |
| `lineage_edges.source_dataset_id`, `lineage_edges.target_dataset_id` | `datasets.dataset_id` |
| `quality_rules.field_id` | `fields.field_id` |
| `quality_rule_versions.rule_id`, `rule_runs.rule_id` | `quality_rules.rule_id` |
| `rule_runs.weight_version` | `rule_weight_versions.weight_version` |
| `issues.rule_run_id`, `issues.verification_run_id` | `rule_runs.rule_run_id` |
| `issues.owner_id` | `owners.owner_id` |
| `issue_events.issue_id` | `issues.issue_id` |
| `definition_changes.metric_version_id`, `definition_changes.previous_metric_version_id` | `metric_versions.metric_version_id` |
| `match_candidates.left_record_id`, `match_candidates.right_record_id` | `customer_records.record_id` |
| `merge_decisions.candidate_id` | `match_candidates.candidate_id` |
| `merge_decisions.reverses_merge_id` | `merge_decisions.merge_id` |

Logical joins the database does not enforce (they carry meaning, not a constraint): `rule_runs.rerun_for_issue` -> `issues.issue_id` (a rerun names its issue); `merge_decisions.reviewer_id`, `match_candidates.proposed_by`, `metric_versions.owner_id` (may name an owner that no longer exists: the checklist item `owner` then fails), `definition_changes.approved_by`, `issues.owner_id` -> `owners.owner_id` by id only for the audit columns; `rule_runs.rule_version` -> `quality_rule_versions.version_number`; `verification_truth.record_id` -> `customer_records.record_id`; `quality_rules.definition.parent_dataset_id` -> `datasets.dataset_id`.

## 4. Constraints and triggers (`0002`, `0003`)
* **Checks:** `owners_role_ck`, `owners_inactive_ck`; `datasets_class_ck` (owner and classification never empty), `datasets_schedule_ck` (a monitored dataset declares a valid IANA zone, `HH:MM` time and a grace of 0..1439); `rules_type_ck`, `rules_status_ck` (disabled <=> `disabled_at` and a reason), `rules_pattern_portable_ck` and `rule_versions_ck` (no `\s \d \w \b`); `runs_counts_ck` (failures at most eligible), `runs_kind_ck` (a rerun names its issue); `issues_status_ck`; `edges_evidence_ck` (observed <=> `observed_at`; source <> target); `metric_versions_ck` (draft, reviewed, published, superseded); `changes_reason_ck`; `candidates_canonical_ck` (left < right in code-point order), `candidates_score_ck`; `decisions_kind_ck` (a reversal names an approval and a reason); `weights_valid_ck` (the five dimensions, summing to 1); `dataset_rows_version_ck`; `command_results_role_ck`.
* **Uniqueness:** `issues_run_uq` (one issue per run), `metric_versions_uq` (metric, version), `changes_version_uq`, `candidates_pair_uq` (a pair once; the reverse orientation cannot be stored), `decisions_reversal_uq` (an approval is reversed once), `dataset_rows_version_uq`.
* **Triggers:** `*_immutable` and `*_no_truncate` on the append-only tables; `quality_rules_guard` and `quality_rules_no_delete`; `issues_guard` (`ISSUE_IMMUTABLE`, `REOPEN_HISTORY`, `VERIFICATION_IMMUTABLE`, `VERIFICATION_RUN_INVALID`: an issue is resolved only by a successful rerun of the same rule version, D-03); `merge_decisions_guard` (`REVIEWER_IS_PROPOSER`, `INVALID_REVERSAL`).
* **Functions:** `tl_valid_tz`, `tl_cell` (the exact text of a cell), `tl_iso`, `tl_valid_weights`, `tl_pattern_not_portable`, `tl_forbid_mutation`, `tl_rule_guard`, `tl_rule_no_delete`, `tl_issue_guard`, `tl_decision_guard`.

## 5. Source-to-target mapping
Published snapshot `web/public/data/*.json` (wrapped: `{entity, dataset_version, rows}`; the configuration is in `manifest.json` `config`) -> table, loaded by `data/seed.py` through the domain's `validate_batch` (the same rules as the API); the figures a table feeds are the metrics of D-01..D-06.

| Source file | Target table | Feeds |
|---|---|---|
| `owners.json` | `owners` | ownership coverage (P07-MET-09), accountability of every issue |
| `datasets.json` | `datasets` | ownership coverage, timeliness (P07-MET-05), every per-dataset score |
| `fields.json` | `fields` | rule targets |
| `dataset_rows.json` (grouped by `dataset_id`) | `dataset_rows` (`ordinal` = position, `row_version` 1) | completeness, validity, uniqueness, relationship integrity (P07-MET-01..04) |
| `quality_rules.json`, `quality_rule_versions.json` | `quality_rules`, `quality_rule_versions` | which rule measures what, comparable runs (RULE_VERSION_DIFFERS) |
| `weight_versions.json` (manifest `config.weight_versions`) | `rule_weight_versions` | the weighted score under a named version (P07-MET-06) |
| `manifest.json` `config.checklist_versions`, `whitespace_policy`, `probes` | `checklist_versions`, `ledger_config` | definition coverage (P07-MET-10), the missing-value policy |
| `rule_runs.json` | `rule_runs` | comparable runs, weight-version run counts, the verification of issues |
| `issues.json` | `issues`, `issue_events` (derived at load: detected, claimed, verified, reopened) | resolution time and the claimed split (P07-MET-08) |
| `lineage_edges.json` | `lineage_edges` | observed lineage coverage (P07-MET-12) |
| `metric_versions.json`, `definition_changes.json` | `metric_versions`, `definition_changes` | definition coverage, versioned definitions |
| `customer_records.json`, `match_candidates.json`, `merge_decisions.json` | `customer_records`, `match_candidates`, `merge_decisions` | identity matching, reversible merges |
| `manifest.json` `synthetic_truth.true_entity` | `verification_truth` (loaded by `prepare_snapshot.py` only) | match precision (P07-MET-11), outside the matcher |
| (none) | `rejected_records`, `audit_events`, `command_results`, `dataset_refreshes` | produced by ingest refusals and the API; empty on the snapshot |
| `manifest.json` `dataset_version`, `dataset_hash`, `as_of` | `dataset_versions` | the version commands must carry |

## 6. Known gaps and disclosures
* **The snapshot has no rejected record, audit event, command result or refresh** (the generator's replay-only events are driven through the API by the tests, and leave no row in a snapshot).
* **Seeded issues carry no `record_ids`**, so C10 re-measures the whole rule; `rule_runs.details` is empty on the snapshot (the populated counts are recomputed from the rows, not read from a stored run).
* **Row-level measurement is authoritative at the as-of.** The last scheduled run of each active row-based rule stores the same eligible and failing counts, except `r-contacts-fk-customer_key` (INJ-12), whose current version adds a filter, so its stored runs are not comparable with the measurement; `run_all.py` checks both statements.
* **A pattern is a regular expression in three engines** (PostgreSQL, Python `re`, JavaScript): the schema refuses the escapes they disagree on (D-10 R7-04); beyond the patterns in the data no assurance is given.
* **The truth table is a synthetic verification device**, not part of the model the product serves: without it match precision is null (unknown), never 0.
* **Dictionary scope.** Descriptions state contract meaning; `docs/contracts.md` is the authority and is unchanged by this package.
