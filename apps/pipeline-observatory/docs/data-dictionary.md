# Pipeline Observatory: data dictionary (P08-ART-03)

Dataset `po-20261026-20261026` (generator `dataset_hash` `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`), contract v1, code revision `ed7eb5a` (the app content published as `b326690`). **Synthetic data only**: nothing here describes a real platform, a real source or a real person.
The decision it supports: **is this dataset safe, complete and fresh enough to publish?** (P08-GOAL-01).

**How to read it without installing anything:** the scope vocabulary first (every figure is complete world, 2,000-row sample or recorded), then the six source contracts, then one table per entity with its grain, origin, field types and meaning, then foreign keys and the source-to-target mapping from the published files. The names are the migrations' (`data/sql/migrations/0001..0003`), checked against them by `tests/test_artifacts.py`.

## Scope vocabulary (D-08, D-09 R8-09)
| Scope | Meaning | Where it applies |
|---|---|---|
| complete world | the published files carry every row | batches, checkpoints, runs, tasks, quality results, publications, incidents, backfills, quarantine rows, expectations, the fetch log, the per-batch summaries |
| 2,000-row sample | computed from `raw_records`, which holds 2,000 of the world's 40,191 raw rows in 62 whole batches (50 of which carry rows) | anything that needs raw rows: classification of rows, freshness from events, late events, reconciliation parts, content hashes |
| recorded | a statement of the generator about the complete world that the files cannot recompute (`manifest.json`) | the latest accepted event of each source, the 757 late events, the residual of each publication |

## The six source contracts (`source_contracts` and `source_expectations`)
| source_id | expected_frequency | cadence (s) | freshness target (s) | schema_version | expected records (56 partitions) | note |
|---|---|---|---|---|---|---|
| `src-orders` | every 4 hours | 14,400 | 19,800 (5.5 h) | 1 | 16,176 | the largest source; nine events held back to a later batch (DR-04) |
| `src-payments` | every 4 hours | 14,400 | 21,600 (6 h) | 2 (from 2026-09-15) | 10,207 | its first page declaring the new required field is quarantined whole (INJ-04) |
| `src-refunds` | every 6 hours | 21,600 | 604,800 (7 days) | 1 | 4,003 | stops delivering new events at 2026-10-02T00:00:00Z; its target is looser than its silence (DR-01) |
| `src-shipments` | every 6 hours | 21,600 | 259,200 (72 h) | 1 | 4,004 | rate-limited on 12.5 % of its fetches; retry-after 30, 60, 90 or 120 s (DR-03) |
| `src-inventory` | daily | 86,400 | 259,200 (72 h) | 1 | 1,645 | |
| `src-web-events` | every 12 hours | 43,200 | 216,000 (60 h) | 1 | 1,678 | carries the one repeated pagination token (INJ-10) |

Payload contract (`raw_records.payload_json`, D-P8-12): `record_id` (the source key), `quantity` (JSON integer, magnitude at most 2^53), `unit_price` and `amount` (strings matching `-?[0-9]+(\.[0-9]{1,2})?`, ASCII only, full match), `event_ts` (a real UTC instant, not later than the batch's arrival or the cutoff), optional `op` (`delete` or another value; an unknown op is quarantined UNKNOWN_OP). Check order: key already accepted = duplicate; else missing field, invalid field, negative quantity, event in the future.

## Tables

### `source_contracts`
**Grain:** one row per source (6 in the world, 2 in the golden fixture). **Origin:** loaded from `source_contracts.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `source_id` | text | no | key, e.g. `src-orders` |
| `source_name` | text | no | display name |
| `schema_version` | text | no | the schema version the contract expects; changes only by C02 `bump_schema_version` (operator or admin); `src-payments` declares `2` from 2026-09-15 |
| `expected_frequency` | text | no | declared cadence text: `every 4 hours`, `every 6 hours`, `every 12 hours`, `daily` (the analysis parses it into seconds) |
| `owner_id` | text | no | accountable owner of the source (`own-01`..) |
| `freshness_target_seconds` | integer | yes | the gate's freshness target in seconds, NULL = none; `src-refunds` declares 604800 (7 days) on purpose |

### `source_expectations`
**Grain:** one row per source and UTC-date partition (336 = 6 x 56). **Origin:** loaded from `source_expectations.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `source_id` | text | no | FK source_contracts |
| `partition` | text | no | UTC date `YYYY-MM-DD` of the freshness timestamp field (`event_ts`) |
| `expected_records` | integer | no | the synthetic source's declared count for the partition, including rows that later fail (D-P8-02) |

### `ingestion_batches`
**Grain:** one row per fetched page of a source (1,311). **Origin:** loaded from `ingestion_batches.json`; `next_cursor` from the batch's checkpoint.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `batch_id` | text | no | key, `b-NNNN` |
| `source_id` | text | no | FK source_contracts |
| `source_cursor` | text | no | the cursor the batch was fetched from |
| `started_at` | timestamptz | no | arrival instant of the batch (also the upper bound of its events: a later event is EVENT_IN_FUTURE) |
| `status` | text | no | `staged` (fetched, uncounted), `committed`, `aborted` (a crashed ingest: rows, no checkpoint), `quarantined` (refused whole, SCHEMA_CHANGED); only `committed` counts (D-P8-04) |
| `next_cursor` | text | yes | what a commit records as committed_cursor |
| `schema_version` | text | yes | the version the page declared, NULL = the contract's |
| `validated_at` | timestamptz | yes | set by C02 (nothing counted yet) |
| `fetch_session` | text | yes | the fetch session of C01 (runtime; the world's sessions are in fetch_log) |

### `raw_records`
**Grain:** one row per received row; the published file is a 2,000-row SAMPLE of 62 whole batches. **Origin:** loaded from `raw_records.json` (sample); `disposition` and `reason_code` are the domain's classification written by the seeder.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `raw_record_id` | text | no | key, `rr-b-NNNN-MMMM` |
| `batch_id` | text | no | FK ingestion_batches |
| `source_key` | text | yes | `payload_json.record_id`; NULL when the row carries no key (quarantined MISSING_FIELD, never dropped) |
| `payload_hash` | text | no | sha256 of the canonical JSON payload (sorted keys, `,`/`:`, ASCII), D-P8-10 |
| `payload_json` | jsonb | no | the payload: `record_id`, `quantity` (integer), `unit_price`, `amount` (2-place decimal strings), `event_ts` (UTC instant), optional `op` (`delete` or another value) |
| `disposition` | text | yes | evidence of the last classification: accepted, duplicate, quarantined, deleted (the SQL reference never reads it) |
| `reason_code` | text | yes | the quarantine reason when quarantined |

### `accepted_records`
**Grain:** one row per (source, source_key) accepted once: THE idempotency boundary. **Origin:** derived by the seeder / written by C03 (not a published file).

| Column | Type | Null | Meaning |
|---|---|---|---|
| `source_id` | text | no | FK source_contracts; with source_key the primary key |
| `source_key` | text | no | the business key accepted once per source whatever the batch |
| `raw_record_id` | text | no | FK raw_records, unique |
| `batch_id` | text | no | FK ingestion_batches: the batch that accepted it |
| `accepted_at` | timestamptz | no | the arrival of that batch (the instant the key became known) |
| `deleted_in_batch` | text | yes | FK ingestion_batches: the batch of the delete event that propagated to the snapshot |

### `quarantine_records`
**Grain:** one row per quarantined occurrence (446: 429 in committed batches, 17 in the schema-quarantined batch). **Origin:** loaded from `quarantine_records.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `quarantine_id` | text | no | key, `q-b-NNNN-NN` |
| `batch_id` | text | no | FK ingestion_batches |
| `source_key` | text | yes | NULL for a keyless row |
| `reason_code` | text | no | NEGATIVE_QUANTITY, MISSING_FIELD, INVALID_FIELD, EVENT_IN_FUTURE, DELETE_TARGET_UNKNOWN, UNKNOWN_OP, SCHEMA_CHANGED |
| `payload_hash` | text | no | sha256 of the canonical payload |

### `checkpoints`
**Grain:** one row per committed batch (1,302), committed in the same transaction as its rows. **Origin:** loaded from `checkpoints.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `checkpoint_id` | text | no | key, `cp-b-NNNN` |
| `source_id` | text | no | FK source_contracts |
| `batch_id` | text | no | FK ingestion_batches, unique: one checkpoint per batch |
| `committed_cursor` | text | no | the cursor a replay resumes from |
| `committed_at` | timestamptz | no | the instant of the last successful ingestion of the source (ingestion age is measured from it) |
| `version_number` | integer | no | previous + 1 per source (trigger); unique per source |

### `fetch_log`
**Grain:** one row per fetch (1,361). **Origin:** published in `fetch_log.json`; NOT loaded by the seeder: `prepare_snapshot.py` inserts it into this table for the analysis.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `fetch_id` | bigint | no | key |
| `source_id` | text | no | FK source_contracts |
| `cursor_value` | text | no | the cursor fetched |
| `session_id` | text | yes | the fetch session; a loop is a repeated cursor inside ONE session |
| `status` | text | no | ok, rate_limited, refetch, cursor_loop (migration 0003) |
| `next_cursor` | text | yes | the page's next cursor |
| `retry_after_seconds` | integer | yes | the rate-limit hint of a 429 |
| `fetched_at` | timestamptz | no | instant of the fetch |
| `batch_id` | text | yes | the batch the page produced, NULL for rate_limited and cursor_loop rows |

### `model_definitions`
**Grain:** one row per model version (12 models over three layers). **Origin:** loaded from `model_definitions.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `model_id` | text | no | key, e.g. `m-stg-orders` |
| `model_name` | text | no | model name |
| `grain` | text | no | the model's grain |
| `version_number` | integer | no | version of the model |
| `definition` | text | no | the SQL text |
| `definition_hash` | text | no | sha256 of the definition text (checked by the database) |

### `backfill_requests`
**Grain:** one row per ACCEPTED backfill request (13); the 2 refused are kept in rejected_records. **Origin:** loaded from `backfill_requests.json` (15 published rows, 2 refused by the import).

| Column | Type | Null | Meaning |
|---|---|---|---|
| `backfill_id` | text | no | key, `bf-NNN`; a refused request consumes its id |
| `source_id` | text | no | FK source_contracts |
| `start_at` | timestamptz | no | UTC midnight, half-open range start |
| `end_at` | timestamptz | no | UTC midnight, half-open range end |
| `status` | text | no | `requested`, `running`, `complete` or `partial` |
| `partitions` | jsonb | no | jsonb list of `{partition, verified}` |
| `requested_by` | text | yes | `seed` in the world |
| `requested_at` | timestamptz | yes | when it was requested (what was running then is judged from this) |
| `settled_at` | timestamptz | yes | when it settled (NULL while requested or running) |

### `pipeline_runs`
**Grain:** one row per hourly run (1,343). **Origin:** loaded from `pipeline_runs.json`; `included_batch_ids` from the run's publication.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `run_id` | text | no | key, `run-NNNN` |
| `started_at` | timestamptz | no | hh:15 UTC |
| `finished_at` | timestamptz | yes | set at publication or failure |
| `status` | text | no | `running`, `success`, `failed` |
| `code_sha` | text | no | the code revision stamped on the run |
| `backfill_id` | text | yes | FK backfill_requests: the request an accepted backfill rides on |
| `included_batch_ids` | text[] | no | the scope the transform consumed |
| `scope_from` | timestamptz | yes | start of the run's scope (the gate's scope_complete judges every batch committed in [scope_from, started_at)) |

### `task_runs`
**Grain:** one row per attempt of a task (5,462); a task is (run, task_name). **Origin:** loaded from `task_runs.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `task_run_id` | text | no | key, `tr-NNNN-N` |
| `run_id` | text | no | FK pipeline_runs |
| `task_name` | text | no | ingest, transform, quality_gate, publish |
| `status` | text | no | running, success, failed |
| `attempt` | integer | no | 1.. consecutive (unique with run and task name); an attempt is not a task |

### `quality_results`
**Grain:** one row per check result (9,296 = 1,328 gates x 7 checks). **Origin:** loaded from `quality_results.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `quality_result_id` | text | no | key, `qr-NNNN-NN` |
| `task_run_id` | text | no | FK task_runs (the quality_gate attempt) |
| `rule_name` | text | no | keys_unique, relationships_intact, reconciliation_residual_zero, freshness_within_target, scope_complete, late_events_included (critical); completeness_vs_expectation (warning) |
| `severity` | text | no | critical or warning |
| `eligible_count` | integer | no | population checked |
| `failure_count` | integer | no | failures; the result passes iff 0 |

### `publications`
**Grain:** one row per publication (1,318), immutable. **Origin:** loaded from `publications.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `publication_id` | text | no | key, `pub-NNNN` |
| `run_id` | text | no | FK pipeline_runs, unique |
| `dataset_name` | text | no | `sales_daily` |
| `published_at` | timestamptz | no | the run's finished_at |
| `watermark` | timestamptz | no | disclosed with every publication; never in the future, never before the previous publication's |
| `source_ids` | text[] | no | every source contract |
| `included_batch_ids` | text[] | no | committed batches in the publication's scope |
| `content_hash` | text | no | sha256 of the sorted included payload hashes joined with a newline (D-P8-10) |

### `publication_pointer`
**Grain:** exactly one row: the current publication. **Origin:** set by the seeder to the domain's current publication / by C06 in the publication's transaction.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | integer | no | always 1 |
| `publication_id` | text | no | FK publications: moves only to a successful run with an allowed gate (trigger) |
| `updated_at` | timestamptz | no | when the pointer moved |

### `incidents`
**Grain:** one row per incident (25). **Origin:** loaded from `incidents.json`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `incident_id` | text | no | key, `inc-NNN` |
| `run_id` | text | no | FK pipeline_runs: the failed or blocked run (detection = opened_at) |
| `severity` | text | no | medium, high, critical |
| `status` | text | no | open or closed |
| `opened_at` | timestamptz | no | detection instant |
| `closed_at` | timestamptz | yes | the verified recovery instant (the recovery publication's published_at) |
| `recovery_run_id` | text | yes | FK pipeline_runs: the first verified run |
| `reason` | text | yes | e.g. GATE_BLOCKED (runtime) |

### `model_outputs`
**Grain:** the analytical table the transform builds (runtime; empty in the loaded world). **Origin:** written by C04 (not a published file; the stored candidate totals are `model_output_totals.json`).

| Column | Type | Null | Meaning |
|---|---|---|---|
| `output_id` | bigint | no | surrogate key |
| `run_id` | text | no | FK pipeline_runs |
| `model_name` | text | no | model |
| `source_id` | text | no | source |
| `record_key` | text | no | business key (not unique on purpose: the key test must be able to fail) |
| `batch_id` | text | no | batch |
| `day` | text | no | UTC date |
| `amount` | numeric | no | NUMERIC(20,6) since migration 0003 |
| `payload_hash` | text | no | payload hash |

### `processing_measurements`
**Grain:** one synthetic measurement (the observed processing rate). **Origin:** from `manifest.json` config.processing_measurement (batch b-1121).

| Column | Type | Null | Meaning |
|---|---|---|---|
| `measurement_id` | bigint | no | surrogate key |
| `source_id` | text | no | FK source_contracts |
| `batch_id` | text | no | FK ingestion_batches: the measured batch |
| `measured_seconds` | numeric | no | NUMERIC without a scale (`2.573`) |
| `hardware` | text | no | disclosed: a synthetic value, not a benchmark |
| `cache_state` | text | no | cold or warm |
| `recorded_at` | timestamptz | no | the as-of |

### `rejected_records`
**Grain:** every import row the domain refused, kept with its raw row (2 in the world: bf-006 and bf-012). **Origin:** written by the seeder / C08 / C02.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `batch_id` | text | no | `seed` for the loader |
| `entity` | text | no | entity name |
| `id` | text | no | the row's id |
| `reason_code` | text | no | e.g. BACKFILL_OVERLAP |
| `raw_row` | jsonb | no | the refused row as received |
| `ordinal` | integer | no | occurrence number of an id |
| `created_at` | timestamptz | no | insert instant |

### `fault_injections`
**Grain:** sandbox fault injections (runtime; empty in the world). **Origin:** written by C07 only when PIPELINE_ENVIRONMENT = sandbox.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `fault_id` | text | no | key |
| `fault_type` | text | no | duplicate_key, task_failure, crash_before_checkpoint |
| `target_id` | text | no | the target |
| `injected_by` | text | no | actor |
| `injected_at` | timestamptz | no | instant |
| `armed` | boolean | no | one-shot flag |
| `consumed_at` | timestamptz | yes | when consumed |
| `note` | text | yes | free text |

### `evidence_archives`
**Grain:** one manifest per archived run (runtime; empty in the world). **Origin:** written by C10.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `archive_id` | text | no | key |
| `run_id` | text | no | FK pipeline_runs, unique |
| `created_at` | timestamptz | no | instant |
| `created_by` | text | no | actor |
| `manifest` | jsonb | no | jsonb: a sha256 per item |
| `manifest_hash` | text | no | sha256 of the manifest |
| `retention` | jsonb | no | jsonb retention mapping |

### `audit_events`
**Grain:** append-only audit of every command (runtime). **Origin:** written by every command.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `event_id` | text | no | key |
| `entity_type` | text | no | type |
| `entity_id` | text | no | id |
| `action` | text | no | action |
| `actor_id` | text | no | asserted actor |
| `actor_role` | text | yes | asserted role (header-asserted identity, no authentication) |
| `occurred_at` | timestamptz | no | instant |
| `before_version` | integer | yes | version before |
| `after_version` | integer | yes | version after |
| `reason` | text | yes | reason |
| `request_id` | text | yes | request id |
| `details` | jsonb | no | jsonb |

### `command_results`
**Grain:** idempotency store of the commands (runtime). **Origin:** written by every command.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `idempotency_key` | text | no | key; bound to actor, role and payload hash |
| `payload_hash` | text | no | hash of command, dataset_version and input |
| `actor_id` | text | no | actor |
| `actor_role` | text | no | role |
| `command_id` | text | no | command id |
| `status` | text | no | status |
| `result` | jsonb | no | the stored response |
| `created_at` | timestamptz | no | instant |

### `dataset_versions`
**Grain:** one row per load (the loaded world: `po-20261026-20261026`). **Origin:** written by the loader.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `dataset_version` | text | no | key |
| `dataset_hash` | text | no | sha256 over the sixteen entity files |
| `contract_version` | text | no | `1` |
| `as_of` | timestamptz | yes | the as-of 2026-10-05T00:00:00Z |
| `created_at` | timestamptz | no | insert instant |

### `schema_migrations`
**Grain:** applied migrations with their checksums. **Origin:** written by data/migrate.py.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `version` | text | no | migration file name |
| `checksum` | text | no | sha256 of the file |
| `applied_at` | timestamptz | no | instant |

## Foreign keys (from the migrations)
| Child | Column | Parent |
|---|---|---|

| `accepted_records` | `batch_id` | `ingestion_batches.batch_id` |
| `accepted_records` | `deleted_in_batch` | `ingestion_batches.batch_id` |
| `accepted_records` | `raw_record_id` | `raw_records.raw_record_id` |
| `accepted_records` | `source_id` | `source_contracts.source_id` |
| `backfill_requests` | `source_id` | `source_contracts.source_id` |
| `checkpoints` | `batch_id` | `ingestion_batches.batch_id` |
| `checkpoints` | `source_id` | `source_contracts.source_id` |
| `evidence_archives` | `run_id` | `pipeline_runs.run_id` |
| `fetch_log` | `source_id` | `source_contracts.source_id` |
| `incidents` | `recovery_run_id` | `pipeline_runs.run_id` |
| `incidents` | `run_id` | `pipeline_runs.run_id` |
| `ingestion_batches` | `source_id` | `source_contracts.source_id` |
| `model_outputs` | `run_id` | `pipeline_runs.run_id` |
| `pipeline_runs` | `backfill_id` | `backfill_requests.backfill_id` |
| `processing_measurements` | `batch_id` | `ingestion_batches.batch_id` |
| `processing_measurements` | `source_id` | `source_contracts.source_id` |
| `publication_pointer` | `publication_id` | `publications.publication_id` |
| `publications` | `run_id` | `pipeline_runs.run_id` |
| `quality_results` | `task_run_id` | `task_runs.task_run_id` |
| `quarantine_records` | `batch_id` | `ingestion_batches.batch_id` |
| `raw_records` | `batch_id` | `ingestion_batches.batch_id` |
| `source_expectations` | `source_id` | `source_contracts.source_id` |
| `task_runs` | `run_id` | `pipeline_runs.run_id` |

Keys without a foreign-key constraint: `quality_results` to a run is through its task run; `publications.included_batch_ids`, `pipeline_runs.included_batch_ids` and `publications.source_ids` are arrays of ids; `fetch_log.batch_id` and `model_outputs.batch_id` are plain ids.

## Database guards (migrations 0002, 0003)
* `accepted_records` primary key `(source_id, source_key)`: a key is accepted once per source, whatever the batch (the idempotency boundary).
* `checkpoints`: version = previous + 1 per source (trigger `po_checkpoint_guard`); a committed batch has its checkpoint and a checkpoint's batch is committed (deferred pairing triggers).
* Append-only evidence: `checkpoints`, `quarantine_records`, `publications`, `quality_results`, `model_definitions`, `audit_events`, `command_results`, `evidence_archives` refuse UPDATE and DELETE; `task_runs` and `fetch_log` refuse DELETE.
* `publication_pointer` and `publications`: a pointer moves only to a successful run whose gate was allowed; no publication exists for a failed or blocked run.
* No floating-point column: counts are integers, instants are `timestamptz`, money lives in payload strings and `NUMERIC(20,6)` (`model_outputs.amount`).

## Source-to-target mapping (published files to tables)
| Published file (`web/public/data/`) | Rows | Target | Notes |
|---|---|---|---|
| `source_contracts.json` | 6 | `source_contracts` | |
| `source_expectations.json` | 336 | `source_expectations` | |
| `ingestion_batches.json` | 1,311 | `ingestion_batches` | `next_cursor` taken from the batch's checkpoint (`committed_cursor`) |
| `raw_records.json` | 2,000 (sample) | `raw_records`, `accepted_records` | `source_key` = `payload_json.record_id`; disposition, reason and the accepted keys are the domain's classification of the SAMPLE |
| `quarantine_records.json` | 446 | `quarantine_records` | |
| `checkpoints.json` | 1,302 | `checkpoints` | loaded in version order |
| `model_definitions.json` | 12 | `model_definitions` | `layer` and `depends_on` are published but not columns |
| `pipeline_runs.json` | 1,343 | `pipeline_runs` | `included_batch_ids` from the run's publication |
| `task_runs.json` | 5,462 | `task_runs` | |
| `quality_results.json` | 9,296 | `quality_results` | |
| `publications.json` | 1,318 | `publications`, `publication_pointer` | the pointer is the domain's current publication (`pub-1343`) |
| `incidents.json` | 25 | `incidents` | |
| `backfill_requests.json` | 15 | `backfill_requests` (13), `rejected_records` (2) | bf-006 and bf-012 are refused by the import as BACKFILL_OVERLAP and kept with their raw rows |
| `fetch_log.json` | 1,361 | `fetch_log` | loaded by `prepare_snapshot.py`, not by the seeder |
| `batch_summaries.json` | 1,311 | `artifact_batch_summaries` (scratch only) | the per-batch counts over ALL raw rows; not a schema table |
| `model_output_totals.json` | 1,331 | `artifact_model_output_totals` (scratch only) | the stored candidate total per run |
| `manifest.json` | 1 | `dataset_versions`, `processing_measurements`, `artifact_recorded_*` (scratch only) | config, the as-of, the processing measurement and the recorded freshness and residual |
| `injection-manifest.json` | 1 | not loaded | the twelve injected defects with how each must be handled |

The `artifact_*` tables are created by `data/sql/analysis/artifact_tables.sql` in the scratch databases only (`artifacts08_*`); the application never reads or writes them.
