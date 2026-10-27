# Data dictionary: RetentionLab relational model (P10-ART-03)

**Everything is synthetic** (`accounts.synthetic` is always true; D-04). Dataset `rl-20261026-20261026` (seed 20261026, `dataset_hash` `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`), contract v1, code revision `ce96e65` (the app content of the lab branch at the R10 fixes; the published `code_sha` is the lab HEAD at republish time).

**How to read it:** this file needs nothing installed; every table of `data/migrations/0001_schema.sql`, `0002_constraints.sql` and `0003_prevalence_model.sql` is listed with grain, every column with type, nullability, key and meaning. The column lists were produced from the migrated database (25 tables, 150 columns) and are checked against it by `tests/test_artifacts.py`. Section 5 maps the published files to the tables; section 6 adds the verification-layer tables that exist only in the scratch databases of the artifact package.

Result kinds are kept apart: **simulated** (a property of one draw of the synthetic world) and **hypothetical** (an assumption-based economic value). Proportions and scores are 6-place decimal strings in the API and NUMERIC(20,6) in the database; money has 2 places in reports; no column is a floating-point type (D-04, `tests/test_migrations.py`).

## 1. Tables, grain, keys and update semantics

| Table | Kind | Grain (one row is) | Primary key | Source contract |
|---|---|---|---|---|
| `label_versions` | reference | one row per label definition (lv-1: horizon 90 days, grace 14 days) | `label_version_id` | D-01 label |
| `feature_versions` | reference | one row per feature set (fv-1: 90-day observation window) | `feature_version` | D-01 feature registry |
| `feature_registry` | reference | one row per (feature_version, feature_name): 12 rows, 4 usable features and 8 refused fields (post-outcome, latent, identifier-derived) | `feature_version, feature_name` | D-01, P10-TEST-01/08/12 |
| `accounts` | entity | one row per synthetic account (200 in the published cohort; 2,400 in the world) | `account_id` | D-04 synthetic always true |
| `subscription_events` | event, append-only | one row per start / renew / cancel event, with the instant it became available | `subscription_event_id` | D-01 |
| `billing_events` | event, append-only | one row per billing amount (USD) with its availability instant | `billing_event_id` | D-01 |
| `usage_events` | event, append-only | one row per usage event with its availability instant | `usage_event_id` | D-01 |
| `support_events` | event, append-only | one row per support case event (low / medium / high) with its availability instant | `support_event_id` | D-01 |
| `prediction_cutoffs` | entity, append-only | one row per (account, monthly cutoff): the prediction instant, the label horizon and the observation start | `cutoff_id` | D-01 |
| `feature_rows` | derived, append-only | one row per ELIGIBLE cutoff: the four point-in-time features and the largest available_at used (proved before the cutoff by trigger) | `feature_row_id` | D-01 |
| `labels` | derived | one row per eligible cutoff: churned (NULL while censored), mature flag, label_end; a censored label may mature once | `label_id` | D-01 censoring |
| `training_runs` | entity | one row per training run: split boundaries, frozen configuration and its SHA-256 | `training_run_id` | D-02 |
| `model_preprocessing` | artefact | fitted median / mean / std / missing-in-fit per feature (training rows only) | `training_run_id, feature_name` | D-02 |
| `model_coefficients` | artefact | frozen coefficients, rates, seed or prevalence of each model | `training_run_id, model_name, term` | D-02, D-09 R10-14 |
| `calibration_maps` | artefact | the Platt mapping (a, b) and the number of validation rows it was fitted on | `training_run_id` | D-02 |
| `split_assignments` | derived, append-only | one row per (run, cutoff): range, retained or dropped, and the drop reason | `assignment_id` | D-02 purge |
| `predictions` | fact, append-only | one row per (run, cutoff, model): the frozen probability citing the run's config hash, feature version and label version | `prediction_id` | D-02 |
| `scoring_publications` | fact, append-only | one row per scoring publication (run, model, cutoff): completed when every eligible account has a prediction | `publication_id` | D-02 P10-MET-12 |
| `intervention_scenarios` | assumption, append-only | capacity, contact cost, assumed effect and margin of a what-if (immutable; an edit is a new id) | `scenario_id` | D-03 |
| `outreach_events` | fact, append-only | one DRAFT queue row per selected account (status draft only; nothing is sent) | `outreach_event_id` | D-03 |
| `rejected_records` | audit, append-only | every row refused at import with its raw JSON and reason code (4 CENSORED_LABEL rows in the snapshot) | `batch_id, entity, id, reason_code, ordinal` | D-P10-15 |
| `audit_events` | audit, append-only | who did what to which entity (written by the API) | `event_id` | API |
| `command_results` | audit, append-only | idempotency records of the commands C01..C10 | `idempotency_key` | API |
| `dataset_versions` | reference | dataset version, hash, contract version and as-of of each load | `dataset_version` | D-06 |
| `schema_migrations` | system | applied migrations and their checksums | `version` | data/migrate.py |

Append-only means a trigger (`rl_forbid_mutation`) refuses UPDATE, DELETE and TRUNCATE (`0002`). Exceptions: `labels` (a censored label may mature exactly once), `training_runs` (config and hash change only while no prediction cites the run) and the three artefact tables (rewritten only while the run is not frozen).

## 2. Columns


### accounts

Grain: one row per synthetic account (200 in the published cohort; 2,400 in the world).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `account_id` | BIGINT | no | PK | Account identifier (BIGINT); never a feature (ID_FEATURE). |
| `created_at` | TIMESTAMPTZ | no |  | Creation instant, UTC (strictly before observation_start for eligibility). |
| `segment` | TEXT | no |  | Plan segment: starter, smb, mid or enterprise. |
| `region` | TEXT | no |  | Region: amer, anz, apac, emea or latam. |
| `synthetic` | BOOLEAN | no |  | Always true (CHECK): every account is synthetic. |

### audit_events

Grain: who did what to which entity (written by the API).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `event_id` | TEXT | no | PK | Audit event identifier. |
| `entity_type` | TEXT | no |  | Audited entity type. |
| `entity_id` | TEXT | no |  | Audited entity id. |
| `action` | TEXT | no |  | What was done: a command name, or <command>-refused for a refused request. |
| `actor_id` | TEXT | no |  | Header-asserted actor. |
| `actor_role` | TEXT | yes |  | scientist, analyst or admin. |
| `occurred_at` | TIMESTAMPTZ | no |  | Audit instant. |
| `before_version` | INT | yes |  | Version before. |
| `after_version` | INT | yes |  | Version after. |
| `reason` | TEXT | yes |  | Reason text. |
| `request_id` | TEXT | yes |  | Client request id. |
| `details` | JSONB | no |  | JSONB details. |

### billing_events

Grain: one row per billing amount (USD) with its availability instant.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `billing_event_id` | TEXT | no | PK | Event identifier. |
| `account_id` | BIGINT | no | FK -> accounts.account_id | Account identifier (BIGINT); never a feature (ID_FEATURE). |
| `amount` | NUMERIC(20,6) | no |  | Billed amount, USD, NUMERIC(20,6). |
| `event_at` | TIMESTAMPTZ | no |  | When the event happened, UTC. |
| `available_at` | TIMESTAMPTZ | no |  | When it became available to the warehouse, UTC; never before event_at (CHECK). A feature uses it only if available_at is before the cutoff. |

### calibration_maps

Grain: the Platt mapping (a, b) and the number of validation rows it was fitted on.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `training_run_id` | TEXT | no | PK; FK -> training_runs.training_run_id | Training run identifier (tr-001). |
| `method` | TEXT | no |  | platt (CHECK). |
| `a` | NUMERIC(20,6) | no |  | Platt slope on the logit. |
| `b` | NUMERIC(20,6) | no |  | Platt intercept. |
| `fit_rows` | INT | no |  | Retained mature validation rows the mapping was fitted on. |

### command_results

Grain: idempotency records of the commands C01..C10.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `idempotency_key` | TEXT | no | PK | Client idempotency key. |
| `payload_hash` | TEXT | no |  | Hash of the request payload bound to actor, role and dataset version. |
| `actor_id` | TEXT | no |  | Header-asserted actor. |
| `actor_role` | TEXT | no |  | scientist, analyst or admin. |
| `command_id` | TEXT | no |  | Command id. |
| `status` | TEXT | no |  | Command status. |
| `result` | JSONB | no |  | JSONB stored result. |
| `created_at` | TIMESTAMPTZ | no |  | Stored at. |

### dataset_versions

Grain: dataset version, hash, contract version and as-of of each load.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `dataset_version` | TEXT | no | PK | Dataset version name (rl-20261026-20261026). |
| `dataset_hash` | TEXT | no |  | SHA-256 of the canonical inputs (9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c). |
| `contract_version` | TEXT | no |  | Contract version (1). |
| `as_of` | TIMESTAMPTZ | yes |  | Snapshot instant 2026-10-05T00:00:00Z. |
| `created_at` | TIMESTAMPTZ | no |  | Load instant. |

### feature_registry

Grain: one row per (feature_version, feature_name): 12 rows, 4 usable features and 8 refused fields (post-outcome, latent, identifier-derived).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `feature_name` | TEXT | no | PK | Feature name. |
| `feature_version` | TEXT | no | PK; FK -> feature_versions.feature_version | Feature set cited (fv-1). |
| `source_entity` | TEXT | no |  | Event table the feature is built from. |
| `window_days` | INT | yes |  | Feature window in days (30 or 90), NULL for the whole observation window. |
| `post_outcome` | BOOLEAN | no |  | True: only exists after the outcome; refused POST_OUTCOME_FIELD. |
| `latent` | BOOLEAN | no |  | True: generator truth; refused LATENT_TRUTH. |
| `id_derived` | BOOLEAN | no |  | True: derived from an identifier; refused ID_FEATURE. |
| `lineage` | TEXT | no |  | Where the field comes from. |

### feature_rows

Grain: one row per ELIGIBLE cutoff: the four point-in-time features and the largest available_at used (proved before the cutoff by trigger).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `feature_row_id` | TEXT | no | PK | Feature row identifier. |
| `cutoff_id` | TEXT | no | FK -> prediction_cutoffs.cutoff_id | Prediction cutoff identifier. |
| `feature_version` | TEXT | no | FK -> feature_versions.feature_version | Feature set cited (fv-1). |
| `features_json` | JSONB | no |  | JSONB of the four features; NULL values are unknown, never 0. |
| `max_available_at` | TIMESTAMPTZ | yes |  | Largest available_at used by any feature of the row; trigger-proved to be before prediction_at. |

### feature_versions

Grain: one row per feature set (fv-1: 90-day observation window).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `feature_version` | TEXT | no | PK | Feature set cited (fv-1). |
| `observation_days` | INT | no |  | Observation window in days (90). |

### intervention_scenarios

Grain: capacity, contact cost, assumed effect and margin of a what-if (immutable; an edit is a new id).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `scenario_id` | TEXT | no | PK | Scenario identifier (sc-001..sc-003). |
| `capacity` | INT | no |  | Capacity K: contacts per cycle (>= 1). |
| `contact_cost` | NUMERIC(20,6) | no |  | Cost per contact, USD. |
| `assumed_effect` | NUMERIC(20,6) | no |  | ASSUMED share of an account's churn risk an intervention removes, in [0, 1]; not an estimate. |
| `margin_value` | NUMERIC(20,6) | no |  | USD retained per retained account (assumption). |
| `selected_on` | TEXT | no |  | validation only (CHECK): a capacity chosen on test is refused THRESHOLD_ON_TEST. |
| `created_at` | TIMESTAMPTZ | yes |  | Creation instant (API). |
| `created_by` | TEXT | yes |  | Actor that created the row (API). |

### label_versions

Grain: one row per label definition (lv-1: horizon 90 days, grace 14 days).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `label_version_id` | TEXT | no | PK | Label version identifier. |
| `horizon_days` | INT | no |  | Label horizon in days (90). |
| `grace_days` | INT | no |  | Label grace in days (14). |

### labels

Grain: one row per eligible cutoff: churned (NULL while censored), mature flag, label_end; a censored label may mature once.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `label_id` | TEXT | no | PK | Label identifier. |
| `cutoff_id` | TEXT | no | FK -> prediction_cutoffs.cutoff_id | Prediction cutoff identifier. |
| `churned` | BOOLEAN | yes |  | True or false once mature; NULL while censored (CHECK). |
| `label_end` | TIMESTAMPTZ | no |  | horizon_end + 14 days of grace. |
| `mature` | BOOLEAN | no |  | True when label_end is at or before the as-of; a censored row is excluded from every evaluation. |

### model_coefficients

Grain: frozen coefficients, rates, seed or prevalence of each model.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `training_run_id` | TEXT | no | PK; FK -> training_runs.training_run_id | Training run identifier (tr-001). |
| `model_name` | TEXT | no | PK | random_baseline, business_rule, logistic_regression or prevalence_baseline (CHECK widened by 0003). |
| `term` | TEXT | no | PK | Coefficient or parameter name (intercept, a feature, seed, flagged, unflagged, prevalence). |
| `value` | NUMERIC(20,6) | no |  | Parameter value, NUMERIC(20,6). |

### model_preprocessing

Grain: fitted median / mean / std / missing-in-fit per feature (training rows only).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `training_run_id` | TEXT | no | PK; FK -> training_runs.training_run_id | Training run identifier (tr-001). |
| `feature_name` | TEXT | no | PK | Feature name. |
| `median` | NUMERIC(20,6) | no |  | Fitted median (training rows only), 6 places. |
| `mean` | NUMERIC(20,6) | no |  | Fitted mean, 6 places. |
| `std` | NUMERIC(20,6) | no |  | Population standard deviation, 6 places (zero replaced by 1). |
| `missing_in_fit` | INT | no |  | Rows with a missing value among the fit rows. |
| `missing_indicator` | BOOLEAN | no |  | True when a missing-value indicator column exists for this feature. |

### outreach_events

Grain: one DRAFT queue row per selected account (status draft only; nothing is sent).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `outreach_event_id` | TEXT | no | PK | Outreach row identifier. |
| `account_id` | BIGINT | no | FK -> accounts.account_id | Account identifier (BIGINT); never a feature (ID_FEATURE). |
| `scenario_id` | TEXT | no | FK -> intervention_scenarios.scenario_id | Scenario identifier (sc-001..sc-003). |
| `action` | TEXT | no |  | Proposed action (propose_contact); a draft, never sent. |
| `status` | TEXT | no |  | draft only (CHECK); nothing is sent. |
| `training_run_id` | TEXT | yes | FK -> training_runs.training_run_id | Run that ranked the queue (set by C08). |
| `prediction_at` | TIMESTAMPTZ | yes |  | Cutoff of the queue (set by C08). |
| `queue_rank` | INT | yes |  | Rank in the draft queue (1 = highest risk). |
| `created_at` | TIMESTAMPTZ | yes |  | Draft creation instant (API). |

### prediction_cutoffs

Grain: one row per (account, monthly cutoff): the prediction instant, the label horizon and the observation start.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `cutoff_id` | TEXT | no | PK | Prediction cutoff identifier. |
| `account_id` | BIGINT | no | FK -> accounts.account_id | Account identifier (BIGINT); never a feature (ID_FEATURE). |
| `prediction_at` | TIMESTAMPTZ | no |  | The cutoff instant: only data available before it may be used. |
| `horizon_end` | TIMESTAMPTZ | no |  | prediction_at + 90 days; a cancel in [prediction_at, horizon_end) is churn. |
| `observation_start` | TIMESTAMPTZ | no |  | prediction_at - 90 days; the feature window starts here (inclusive). |

### predictions

Grain: one row per (run, cutoff, model): the frozen probability citing the run's config hash, feature version and label version.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `prediction_id` | TEXT | no | PK | Prediction identifier. |
| `training_run_id` | TEXT | no | FK -> training_runs.training_run_id | Training run identifier (tr-001). |
| `cutoff_id` | TEXT | no | FK -> prediction_cutoffs.cutoff_id | Prediction cutoff identifier. |
| `model_name` | TEXT | no |  | random_baseline, business_rule, logistic_regression or prevalence_baseline (CHECK widened by 0003). |
| `probability` | NUMERIC(20,6) | no |  | Frozen probability in [0, 1], 6 places. |
| `scored_at` | TIMESTAMPTZ | no |  | Scoring instant (server-stamped in the API; a generator choice in the snapshot). |
| `config_hash` | TEXT | no |  | SHA-256 of the canonical JSON of config; every prediction cites it. |
| `feature_version` | TEXT | no | FK -> feature_versions.feature_version | Feature set cited (fv-1). |
| `label_version` | TEXT | no | FK -> label_versions.label_version_id | Label definition cited (lv-1). |

### rejected_records

Grain: every row refused at import with its raw JSON and reason code (4 CENSORED_LABEL rows in the snapshot).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `batch_id` | TEXT | no | PK | Import batch. |
| `entity` | TEXT | no | PK | Entity the rejected row belongs to. |
| `id` | TEXT | no | PK | Identifier of the rejected row. |
| `reason_code` | TEXT | no | PK | Why it was refused (e.g. CENSORED_LABEL). |
| `raw_row` | JSONB | no |  | The refused row, raw JSONB. |
| `ordinal` | INT | no | PK | Disambiguates repeated ids. |
| `created_at` | TIMESTAMPTZ | no |  | Import instant. |

### schema_migrations

Grain: applied migrations and their checksums.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `version` | TEXT | no | PK | Migration file name. |
| `checksum` | TEXT | no |  | SHA-256 of the migration text. |
| `applied_at` | TIMESTAMPTZ | no |  | When it was applied. |

### scoring_publications

Grain: one row per scoring publication (run, model, cutoff): completed when every eligible account has a prediction.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `publication_id` | TEXT | no | PK | Publication identifier. |
| `training_run_id` | TEXT | no | FK -> training_runs.training_run_id | Training run identifier (tr-001). |
| `model_name` | TEXT | no |  | random_baseline, business_rule, logistic_regression or prevalence_baseline (CHECK widened by 0003). |
| `prediction_at` | TIMESTAMPTZ | no |  | Cutoff the publication covers. |
| `published_at` | TIMESTAMPTZ | no |  | Publication instant. |
| `status` | TEXT | no |  | completed or incomplete (derived). |

### split_assignments

Grain: one row per (run, cutoff): range, retained or dropped, and the drop reason.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `assignment_id` | TEXT | no | PK | Split assignment identifier. |
| `training_run_id` | TEXT | no | FK -> training_runs.training_run_id | Training run identifier (tr-001). |
| `cutoff_id` | TEXT | no | FK -> prediction_cutoffs.cutoff_id | Prediction cutoff identifier. |
| `split` | TEXT | no |  | train, validation, test or outside (CHECK). |
| `status` | TEXT | no |  | retained or dropped for split_assignments; completed or incomplete for publications; draft only for outreach; the command status for command_results. |
| `drop_reason` | TEXT | yes |  | LABEL_WINDOW, GROUP_TEST or GROUP_VALIDATION when dropped, NULL when retained (CHECK). |

### subscription_events

Grain: one row per start / renew / cancel event, with the instant it became available.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `subscription_event_id` | TEXT | no | PK | Event identifier. |
| `account_id` | BIGINT | no | FK -> accounts.account_id | Account identifier (BIGINT); never a feature (ID_FEATURE). |
| `event_type` | TEXT | no |  | start, renew or cancel. |
| `event_at` | TIMESTAMPTZ | no |  | When the event happened, UTC. |
| `available_at` | TIMESTAMPTZ | no |  | When it became available to the warehouse, UTC; never before event_at (CHECK). A feature uses it only if available_at is before the cutoff. |

### support_events

Grain: one row per support case event (low / medium / high) with its availability instant.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `support_event_id` | TEXT | no | PK | Event identifier. |
| `account_id` | BIGINT | no | FK -> accounts.account_id | Account identifier (BIGINT); never a feature (ID_FEATURE). |
| `severity` | TEXT | no |  | low, medium or high; a high-severity event feeds the support feature. |
| `event_at` | TIMESTAMPTZ | no |  | When the event happened, UTC. |
| `available_at` | TIMESTAMPTZ | no |  | When it became available to the warehouse, UTC; never before event_at (CHECK). A feature uses it only if available_at is before the cutoff. |

### training_runs

Grain: one row per training run: split boundaries, frozen configuration and its SHA-256.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `training_run_id` | TEXT | no | PK | Training run identifier (tr-001). |
| `train_end` | TIMESTAMPTZ | no |  | Train range is [.., train_end). |
| `validation_end` | TIMESTAMPTZ | no |  | Validation range is [train_end, validation_end). |
| `test_end` | TIMESTAMPTZ | no |  | Test range is [validation_end, test_end); later rows are outside. |
| `config` | JSONB | no |  | JSONB frozen run configuration (strings only, no float). |
| `config_hash` | TEXT | no |  | SHA-256 of the canonical JSON of config; every prediction cites it. |
| `created_at` | TIMESTAMPTZ | yes |  | Run creation instant (API). |
| `created_by` | TEXT | yes |  | Actor that created the row (API). |

### usage_events

Grain: one row per usage event with its availability instant.

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `usage_event_id` | TEXT | no | PK | Event identifier. |
| `account_id` | BIGINT | no | FK -> accounts.account_id | Account identifier (BIGINT); never a feature (ID_FEATURE). |
| `event_name` | TEXT | no |  | Usage event name (carries no information in the synthetic world). |
| `event_at` | TIMESTAMPTZ | no |  | When the event happened, UTC. |
| `available_at` | TIMESTAMPTZ | no |  | When it became available to the warehouse, UTC; never before event_at (CHECK). A feature uses it only if available_at is before the cutoff. |

## 3. Foreign keys

| From | To |
|---|---|
| `billing_events.account_id` | `accounts.account_id` |
| `calibration_maps.training_run_id` | `training_runs.training_run_id` |
| `feature_registry.feature_version` | `feature_versions.feature_version` |
| `feature_rows.cutoff_id` | `prediction_cutoffs.cutoff_id` |
| `feature_rows.feature_version` | `feature_versions.feature_version` |
| `labels.cutoff_id` | `prediction_cutoffs.cutoff_id` |
| `model_coefficients.training_run_id` | `training_runs.training_run_id` |
| `model_preprocessing.training_run_id` | `training_runs.training_run_id` |
| `outreach_events.account_id` | `accounts.account_id` |
| `outreach_events.scenario_id` | `intervention_scenarios.scenario_id` |
| `outreach_events.training_run_id` | `training_runs.training_run_id` |
| `prediction_cutoffs.account_id` | `accounts.account_id` |
| `predictions.cutoff_id` | `prediction_cutoffs.cutoff_id` |
| `predictions.feature_version` | `feature_versions.feature_version` |
| `predictions.label_version` | `label_versions.label_version_id` |
| `predictions.training_run_id` | `training_runs.training_run_id` |
| `scoring_publications.training_run_id` | `training_runs.training_run_id` |
| `split_assignments.cutoff_id` | `prediction_cutoffs.cutoff_id` |
| `split_assignments.training_run_id` | `training_runs.training_run_id` |
| `subscription_events.account_id` | `accounts.account_id` |
| `support_events.account_id` | `accounts.account_id` |
| `usage_events.account_id` | `accounts.account_id` |

## 4. Constraints and triggers (`0001`, `0002`, `0003`)

| Table | Constraint | Definition |
|---|---|---|
| `accounts` | `accounts_synthetic_check` | `CHECK ((synthetic IS TRUE))` |
| `art_drift_published` | `art_drift_published_grp_check` | `CHECK ((grp = ANY (ARRAY['all_accounts'::text, 'apac'::text, 'other_regions'::text])))` |
| `art_test_table` | `art_test_table_account_id_cutoff_index_key` | `UNIQUE (account_id, cutoff_index)` |
| `art_test_table` | `art_test_table_churned_check` | `CHECK ((churned = ANY (ARRAY[0, 1])))` |
| `billing_events` | `billing_events_availability` | `CHECK ((available_at >= event_at))` |
| `calibration_maps` | `calibration_maps_fit_rows_check` | `CHECK ((fit_rows > 0))` |
| `calibration_maps` | `calibration_maps_method_check` | `CHECK ((method = 'platt'::text))` |
| `command_results` | `command_results_actor_role_check` | `CHECK ((actor_role = ANY (ARRAY['scientist'::text, 'analyst'::text, 'admin'::text])))` |
| `feature_registry` | `feature_registry_window_days_check` | `CHECK (((window_days IS NULL) OR (window_days > 0)))` |
| `feature_rows` | `feature_rows_cutoff_version_uq` | `UNIQUE (cutoff_id, feature_version)` |
| `feature_versions` | `feature_versions_observation_days_check` | `CHECK ((observation_days > 0))` |
| `intervention_scenarios` | `intervention_scenarios_assumed_effect_check` | `CHECK (((assumed_effect >= (0)::numeric) AND (assumed_effect <= (1)::numeric)))` |
| `intervention_scenarios` | `intervention_scenarios_capacity_check` | `CHECK ((capacity >= 1))` |
| `intervention_scenarios` | `intervention_scenarios_contact_cost_check` | `CHECK ((contact_cost >= (0)::numeric))` |
| `intervention_scenarios` | `intervention_scenarios_margin_value_check` | `CHECK ((margin_value >= (0)::numeric))` |
| `intervention_scenarios` | `intervention_scenarios_selected_on_check` | `CHECK ((selected_on = 'validation'::text))` |
| `label_versions` | `label_versions_grace_days_check` | `CHECK ((grace_days >= 0))` |
| `label_versions` | `label_versions_horizon_days_check` | `CHECK ((horizon_days > 0))` |
| `labels` | `labels_censored_is_null` | `CHECK ((mature OR (churned IS NULL)))` |
| `labels` | `labels_cutoff_id_key` | `UNIQUE (cutoff_id)` |
| `labels` | `labels_mature_is_known` | `CHECK (((NOT mature) OR (churned IS NOT NULL)))` |
| `model_coefficients` | `model_coefficients_model_name_check` | `CHECK ((model_name = ANY (ARRAY['random_baseline'::text, 'business_rule'::text, 'logistic_regression'::text, 'prevalence_baseline'::text])))` |
| `model_preprocessing` | `model_preprocessing_missing_in_fit_check` | `CHECK ((missing_in_fit >= 0))` |
| `model_preprocessing` | `model_preprocessing_std_check` | `CHECK ((std > (0)::numeric))` |
| `outreach_events` | `outreach_events_queue_rank_check` | `CHECK (((queue_rank IS NULL) OR (queue_rank >= 1)))` |
| `outreach_events` | `outreach_events_status_check` | `CHECK ((status = 'draft'::text))` |
| `outreach_events` | `outreach_scenario_account_uq` | `UNIQUE (scenario_id, account_id)` |
| `prediction_cutoffs` | `cutoff_account_instant_uq` | `UNIQUE (account_id, prediction_at)` |
| `prediction_cutoffs` | `cutoff_order` | `CHECK (((observation_start < prediction_at) AND (prediction_at < horizon_end)))` |
| `predictions` | `predictions_model_name_check` | `CHECK ((model_name = ANY (ARRAY['random_baseline'::text, 'business_rule'::text, 'logistic_regression'::text, 'prevalence_baseline'::text])))` |
| `predictions` | `predictions_probability_check` | `CHECK (((probability >= (0)::numeric) AND (probability <= (1)::numeric)))` |
| `predictions` | `predictions_run_cutoff_model_uq` | `UNIQUE (training_run_id, cutoff_id, model_name)` |
| `scoring_publications` | `scoring_publications_model_name_check` | `CHECK ((model_name = ANY (ARRAY['random_baseline'::text, 'business_rule'::text, 'logistic_regression'::text, 'prevalence_baseline'::text])))` |
| `scoring_publications` | `scoring_publications_status_check` | `CHECK ((status = ANY (ARRAY['completed'::text, 'incomplete'::text])))` |
| `split_assignments` | `split_assignment_uq` | `UNIQUE (training_run_id, cutoff_id)` |
| `split_assignments` | `split_assignments_drop_reason_check` | `CHECK ((drop_reason = ANY (ARRAY['LABEL_WINDOW'::text, 'GROUP_TEST'::text, 'GROUP_VALIDATION'::text])))` |
| `split_assignments` | `split_assignments_split_check` | `CHECK ((split = ANY (ARRAY['train'::text, 'validation'::text, 'test'::text, 'outside'::text])))` |
| `split_assignments` | `split_assignments_status_check` | `CHECK ((status = ANY (ARRAY['retained'::text, 'dropped'::text])))` |
| `split_assignments` | `split_drop_reason` | `CHECK (((status = 'dropped'::text) = (drop_reason IS NOT NULL)))` |
| `subscription_events` | `subscription_events_availability` | `CHECK ((available_at >= event_at))` |
| `subscription_events` | `subscription_events_event_type_check` | `CHECK ((event_type = ANY (ARRAY['start'::text, 'renew'::text, 'cancel'::text])))` |
| `support_events` | `support_events_availability` | `CHECK ((available_at >= event_at))` |
| `support_events` | `support_events_severity_check` | `CHECK ((severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])))` |
| `training_runs` | `training_runs_config_hash_check` | `CHECK ((config_hash ~ '^[0-9a-f]{64}$'::text))` |
| `training_runs` | `training_runs_order` | `CHECK (((train_end < validation_end) AND (validation_end < test_end)))` |
| `usage_events` | `usage_events_availability` | `CHECK ((available_at >= event_at))` |

Triggers (`0002`): `*_immutable` and `*_no_truncate` on 18 append-only tables; `feature_rows_guard` (AVAILABILITY_AFTER_CUTOFF: max_available_at must precede the cutoff); `labels_guard` (LABEL_WINDOW_INVALID, LABEL_IMMUTABLE: only a censored label matures, once); `training_runs_guard` (RUN_IMMUTABLE, RUN_FROZEN); `predictions_guard` (CITATION_MISMATCH: config hash, feature version and label version must equal the run's); `model_preprocessing_guard`, `model_coefficients_guard`, `calibration_maps_guard` (RUN_FROZEN once a prediction cites the run). `0003` widens the `model_name` checks of `model_coefficients`, `predictions` and `scoring_publications` to the fourth model, `prevalence_baseline` (D-09 R10-14). Indexes: the four event tables by (account, event instant), `prediction_cutoffs` by (prediction_at, account), `predictions` by (run, cutoff), `audit_events` by (entity, instant).

## 5. Source-to-target mapping

| Published file (`web/public/data/`) | Target | Rows | Rule |
|---|---|---|---|
| `accounts.json` | `accounts` | 200 | validated by `retentionlab.validate` (D-P10-15), inserted `ON CONFLICT DO NOTHING` |
| `subscription_events.json` | `subscription_events` | 1646 | as accounts |
| `billing_events.json` | `billing_events` | 1567 | as accounts |
| `usage_events.json` | `usage_events` | 13329 | as accounts |
| `support_events.json` | `support_events` | 322 | as accounts |
| `prediction_cutoffs.json` | `prediction_cutoffs` | 970 | as accounts |
| `feature_rows.json` | `feature_rows` | 765 | trigger proves max_available_at < prediction_at |
| `labels.json` | `labels` | 769 published, 765 loaded | 4 injected labels of false for an open window are refused CENSORED_LABEL (INJ-07) and kept raw in `rejected_records` |
| `training_runs.json` | `training_runs + model_preprocessing + model_coefficients + calibration_maps` | 1 | `data/artefacts.py` projects the frozen config into NUMERIC tables |
| `split_assignments.json` | `split_assignments` | 970 | as accounts |
| `predictions.json` | `predictions` | 2456 (614 per model) | trigger checks the citations |
| `scoring_publications.json` | `scoring_publications` | 48 | as accounts |
| `intervention_scenarios.json` | `intervention_scenarios` | 3 | as accounts |
| `outreach_events.json` | `outreach_events` | 35 | draft only |
| `feature_registry.json` | `feature_registry + feature_versions + label_versions` | 12 | versions from manifest config |
| `manifest.json` | `dataset_versions` | 1 | dataset_version, dataset_hash and as_of of the generator |

Nothing is transformed on load: the seeder inserts the published values. The stored `feature_rows` and `labels` are NOT trusted by the analysis: investigation 05 recomputes all 765 feature rows from the events and investigation 04 re-derives maturity from the cutoff windows; both agree with the stored rows.

## 6. Verification-layer tables (`data/sql/verification_layer.sql`, scratch databases only)

These are NOT migrations: the domain, the API and the seeder never read or load them. `data/sql/analysis/prepare_snapshot.py` creates and fills them in a database named `artifacts10_*` after the seed. They hold the full-world figures the 200-account cohort cannot reproduce.

| Table | Grain | Filled from | Rows |
|---|---|---|---|
| `art_test_table` | one row per mature eligible test-range row of the full world (account x test cutoff): four features, outcome, five probability columns | `test_cohort.json` | 1,513 |
| `art_cutoff_aggregate` | one row per monthly cutoff of the full world: rows, eligible, mature, censored, churned, scored, late events | `cutoff_aggregates.json` cutoffs | 21 |
| `art_drift_published` | one row per (cutoff, group) of the usage_events_30d stability series: apac, other regions, all accounts | `cutoff_aggregates.json` drift.by_cutoff | 63 |
| `art_economics_full_world` | one row per scenario: scored accounts, contact budget, expected value (hypothetical) of the whole world at 2026-09-01 | `cutoff_aggregates.json` economics_full_world | 3 |
| `art_split_population` | one row per range: total, retained, label-window, group-test, group-validation counts of the whole world | `split_summary.json` population | 4 |
| `art_published_claim` | one row per published figure used as a second source (hash, late shares, censored share, naive rates, flipped-feature counts) | `manifest.json` | 18 |

## 7. Known gaps and disclosures

* The cohort has 200 of 2,400 accounts; every full-world figure (1,241 scored accounts, the test table's 442 accounts, the aggregates) comes from the verification layer and is published, not recomputable from the entity tables.
* `art_published_claim` values are text; they are second sources, never inputs to a figure.
* `scoring_publications` and `outreach_events` of the snapshot carry generator-chosen instants; `outreach_events.prediction_at` and `queue_rank` are NULL in the snapshot load (the published rows carry them, the seeder does not store them), so the analysis derives the queue cutoff from the latest scored cutoff.
* No table stores a latent propensity: the generator's truth lives only in the manifest (`synthetic_truth`), and no feature, prediction or metric reads it.
* The key space of `cutoff_id` and the opaque pagination cursors of the API are not bound to a `dataset_version` (README gap).

