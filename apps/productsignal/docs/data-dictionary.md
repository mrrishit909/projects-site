# Data dictionary: ProductSignal relational model (P06-ART-03)

All data in this model is **synthetic**: the golden fixture (`tests/fixtures/golden/inputs.json`) and the generated snapshot `ps-20261026-20261026` (seed 20261026, generator `dataset_hash` `12672f9c39402517083bbbbe9164cbefe3435361dff086eb0d9e16e60f9b66f8`, contract v1, code revision `fdf911a`). The accounts, users, events and experiment are generated; nothing describes a real product, customer or measurement. The question the model serves: **should an onboarding change ship, stop, or receive more investigation?**

**How to read this without installing anything:** section 1 is one row per table (grain, key, rows, update semantics), section 2 one table per table with every column, section 3 the foreign keys, section 4 the constraints and triggers, section 5 the source-to-target mapping, section 6 the known gaps. `erd.md` draws the same model.

Row counts are `SELECT count(*)` on scratch PostgreSQL 16 databases prepared by `data/sql/analysis/prepare_snapshot.py` (migrate, then `seed.py` through the domain's `validate_batch` over `web/public/data`, both plans from the manifest). The snapshot database holds the 12 entity files as published (no row is rejected: `rejected_records` is empty); the golden database holds the fixture's inputs.

Conventions: all instants are `TIMESTAMPTZ` read as UTC (D-01, D-04); money is `NUMERIC(14,2)` USD and nothing is ever a float; proportions are never stored (they are derived and published as decimal strings with six places); ids are `TEXT` keys supplied by the source; absence is NULL (never an empty string, 0 or NaN). "FK" means a foreign key the database enforces. **Observed, constructed and hypothetical** are kept apart: a column holds what the log recorded; the designed relationships of the generator (DR-01 .. DR-07) and the injected defects are described in `sql-analysis.md` and are constructed, not properties of a real product.

## 1. Tables, grain, keys and update semantics

| Table | Kind | Grain | Primary key | Rows (snapshot DB) | Rows (golden DB) | Update semantics |
|---|---|---|---|---|---|---|
| `ps_timezones` | reference | one IANA zone name this server knows | `name` | 499 | 499 | Loaded by `0001_schema.sql` from `pg_timezone_names` (a copy, because the view rescans the zone files on every read and a CHECK on it is far too slow for a bulk load). `ps_valid_tz()` looks a name up here; the count depends on the server's tzdata (499 on the scratch PostgreSQL 16). |
| `accounts` | source | one account (the unit of randomisation, retention and every ratio) | `account_id` | 600 | 235 | Insert-only through the seed. 12 are `internal` (never assigned, never counted); `plan` is free (264), team (248) or business (88); `segment` smb, mid or enterprise; `timezone` is the account's calendar for day-7 and week-4 retention. Reference rows may be corrected outside the append-only set. |
| `users` | source | one user of one account | `user_id` | 1,824 | 236 | Insert-only through the seed. 18 of the 1,824 are bots (`bot_flag`) and are excluded everywhere; 1,806 are real users. |
| `identity_links` | source (append-only) | one anonymous id linked to one user at one instant | `identity_link_id` | 1,264 | 11 | **Append-only** (`identity_links_immutable`); `UNIQUE (anonymous_id)` (`links_anon_uq`) so the earliest link of an anonymous id fixes its user. It attributes only events with `event_at >= linked_at`, never backward. All 1,264 carry `rule_version` `v1`. |
| `sessions` | source (append-only) | one session of one user | `session_id` | 3,420 | 30 | **Append-only** (`sessions_immutable`). 2,589 web and 831 mobile. Sessions of bots and internal accounts are ignored; a session counts for a run only when `started_at` is before the cutoff. |
| `events` | source (append-only) | one event row as the log accepted it, duplicates and late rows included | `event_id` | 12,552 | 529 | **Append-only** (`events_immutable`, `events_no_truncate`): the immutable log. `event_at` is the business instant, `received_at` when the log accepted it. `user_id` and `anonymous_id` carry no foreign key: an event of an unknown identity is logged and excluded from every figure. A re-sent event under another id is a duplicate per run, dropped and counted (124 at the as-of). 5,446 rows have no `user_id` (anonymous visits). |
| `event_properties` | source (append-only) | one property of one event | `property_id` | 2,561 | 379 | **Append-only**; `UNIQUE (event_id, property_key)` and `value_type = 'string'`. 2,197 `feature` properties (every `feature_used` event) and 364 `error_code` properties (every `product_error` event). |
| `subscriptions` | source | one subscription of one account | `subscription_id` | 207 | 10 | Insert-only through the seed. Only `active` (156) and `ended` (35) carry revenue; `trial` (5) and `refunded` (11) do not (D-03); `amount_usd` is USD and `NUMERIC(14,2)`, never a float. |
| `experiment_versions` | source | one version of one experiment | `experiment_version_id` | 2 | 1 | Insert-only through the seed. `unit_type` is always `account` (`versions_unit_ck`). v1 `xv-001` (planned end 2026-08-02) and v2 `xv-002` (re-plan, planned end 2026-10-04). |
| `analysis_plans` | configuration (append-only) | one frozen analysis plan per experiment version | `experiment_version_id` | 2 | 1 | **Append-only** (`analysis_plans_immutable`): written once by C06 (or the seed), before any outcome is read; refused after any run exists (409 `OUTCOME_ALREADY_READ`). `config_hash` is the sha256 of the key-sorted compact JSON of `plan` (`ps_canonical_json`). No foreign key: a plan is configuration and may exist before the version has data. |
| `assignments` | source (append-only) | one account assigned to one variant of one experiment version | `assignment_id` | 554 | 200 | **Append-only**; `UNIQUE (experiment_version_id, unit_id)` (`assignments_unit_uq`): the first assignment fixes the variant, a second variant is 409 `ASSIGNMENT_CONFLICT`. Trigger `assignments_eligible` refuses an internal account. v1 holds 400 (200 and 200), v2 154 (62 control and 92 treatment). `assigned_at` is stamped by the server clock (D-10). |
| `exposures` | source (append-only) | one exposure of one assignment | `exposure_id` | 484 | 180 | **Append-only**; `UNIQUE (assignment_id)`; trigger `exposures_not_early` refuses `exposed_at` before the assignment. 484 exposures on surface `onboarding_checklist`, `event_id` NULL on every row. `exposed_at` is stamped by the server clock. |
| `metric_observations` | derived (append-only) | one eligible activation observation of one assignment | `observation_id` | 544 | 200 | **Append-only**; `UNIQUE (assignment_id, metric_name)`; `value` is `'0'` or `'1'`. Written once by C07 `check-maturity` (544 in the snapshot, all `activation_7d`); the SQL reference and the metrics read events, not these rows, and count the rows that match the events. |
| `analysis_runs` | log (append-only) | one logged analysis run of one experiment version | `analysis_id` | 5 | 2 | **Append-only**: every run is logged by C08 and never rewritten; a late event changes only a later run. The five seeded runs carry the core columns (the four v1 runs and v2's); a run made by the API also stores the result it published. `created_at >= cutoff_at` always holds (a future cutoff is 422). |
| `funnel_definitions` | configuration (append-only) | one version of one funnel definition | `(definition_id, version)` | 1 | 1 | **Append-only**; versions are never edited (C03 adds a new one). `fun-001` v1: visit, signup, onboarding_step_1, activated, maximum gap 48 hours, window 2026-09-28 to 2026-10-05. |
| `metric_config` | configuration | the metric windows the dataset travels with | `id` (always 1) | 1 | 1 | One row, upserted by the seed (`metric_config_ck`): the windows of signup conversion, activation, retention and feature adoption; the funnel's window lives on its definition. |
| `guardrail_reviews` | log (append-only) | one guardrail review of one analysis run | `review_id` | 0 | 0 | **Append-only**; `UNIQUE (analysis_id)` (one per run); verdict OK, HARMFUL or INSUFFICIENT (C09). Empty in a seeded database. |
| `decisions` | log (append-only) | one decision on one analysis run | `decision_id` | 0 | 0 | **Append-only**; `UNIQUE (analysis_id)` (409 `DECISION_ALREADY_RECORDED`); `decision` is ship, stop or inconclusive, `basis` is always `primary` (a segment is never a basis), `decided_role` experimenter or admin. Writes no product state. Empty in a seeded database. |
| `rejected_records` | operational (append-only) | one raw row refused at ingest, with its reason | `(batch_id, entity, id, reason_code, ordinal)` | 0 | 0 | **Append-only**. `raw_row` keeps the row as it arrived; `ordinal` separates two refused occurrences of one id. Empty on the snapshot (0 rows rejected) and on the golden fixture. |
| `audit_events` | operational (append-only) | one audit line per accepted command and per refused decision | `event_id` | 0 | 0 | **Append-only** (`audit_events_immutable`). Written in the SAME transaction as the command it records; C10 refusals leave a `record-decision-refused` row in their own transaction (D-10). `occurred_at` is the server clock. Empty in a seeded database. |
| `command_results` | operational | one stored result per idempotency key | `idempotency_key` | 0 | 0 | Insert-only. The same key, payload (which includes `dataset_version`), actor and role replays the stored result; another payload, actor or role is 409 `IDEMPOTENCY_KEY_REUSED`. Empty in a seeded database. |
| `dataset_versions` | operational | one seeded dataset | `dataset_version` | 1 | 1 | Insert-only. The snapshot database names the generator's `ps-20261026-20261026` and its hash `12672f9c...9b66f8`; a command with another value is 409 `STALE_DATASET_VERSION`. The golden database names `ds-` + 12 hex of the hash of its inputs. |
| `t_critical_975` | reference | one two-sided 95% Student t quantile | `df` | 2,000 | 2,000 | Generated by `data/sql/generate_t_quantiles.py` (df 1 to 2000) and loaded from `data/sql/t_quantiles.csv`: the SQL reference cannot reproduce the quantile series, so it reads this table; beyond df 2000, or for another confidence, the SQL interval is NULL rather than wrong. |
| `schema_migrations` | operational | one applied migration (created by `data/migrate.py`, not by the SQL files) | `version` | 2 | 2 | Holds the sha256 of each applied file; a migration that changed after it was applied is refused. |

**Deletion policy.** Nothing in the application deletes a row: no command issues a `DELETE`. Fourteen tables refuse UPDATE, DELETE and TRUNCATE by trigger (`events`, `event_properties`, `identity_links`, `sessions`, `assignments`, `exposures`, `metric_observations`, `analysis_plans`, `analysis_runs`, `funnel_definitions`, `guardrail_reviews`, `decisions`, `audit_events`, `rejected_records`; each `<table>_immutable` and `<table>_no_truncate`). The reference tables (`accounts`, `users`, `subscriptions`, `experiment_versions`) and the operational tables `command_results`, `dataset_versions`, `metric_config` and `ps_timezones` may be inserted into or corrected only through their own columns.

**Append-only events and versioned plans.** The event log is the immutable record of what the tracking delivered: a late event is a new row with a later `received_at`, a re-sent event a new row dropped as a duplicate per run, so a run at an earlier cutoff never sees what arrived later and the published result of a run is never rewritten (D-01, D-08). A plan is frozen once and a funnel definition is versioned (`(definition_id, version)`): a change is a new row, never an edit, and every run cites the `config_hash` of the plan it used.

**Grain of the analysis.** The unit of randomisation, retention and every ratio is the **account**: user-level events roll up to the account before any ratio (a metric over accounts never counts users). The visitor funnel and signup conversion are measured on the visitor key (the anonymous id, else the user's earliest linked anonymous id, else the user).

## 2. Columns

Type is the PostgreSQL type of `0001_schema.sql`; Null is whether the column accepts NULL; Source is the entity-file field the seed loads it from (`web/public/data/<entity>.json`, same field names as `tests/fixtures/golden/inputs.json`) or how it is produced (`API` = written by a command, `default` = a column default, `not loaded` = NULL on every seeded row).

### ps_timezones
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `name` | TEXT | no | IANA zone name; the CHECK helper `ps_valid_tz(tz)` looks a timezone up here | pg_timezone_names |

### accounts
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `account_id` | TEXT | no | Key (`acc-0001` .. `acc-0600`) | accounts.account_id |
| `plan` | TEXT | no | `free`, `team` or `business` (no CHECK; the domain validates) | accounts.plan |
| `segment` | TEXT | no | `smb`, `mid` or `enterprise`; exploratory only (P06-DOMAIN-06) | accounts.segment |
| `created_at` | TIMESTAMPTZ | no | When the account was created (UTC) | accounts.created_at |
| `internal` | BOOLEAN | no | TRUE for the 12 internal accounts: never randomised (trigger `assignments_eligible`), their events and sessions excluded and counted apart | accounts.internal |
| `timezone` | TEXT | no | IANA name (`accounts_tz_ck`): the account's calendar for day-7 and week-4 retention; America/New_York, America/Los_Angeles or Europe/London | accounts.timezone |

### users
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `user_id` | TEXT | no | Key (`u-00001` ..) | users.user_id |
| `account_id` | TEXT | no | FK to `accounts`: users roll up to the account before any ratio | users.account_id |
| `created_at` | TIMESTAMPTZ | no | When the user was created (UTC) | users.created_at |
| `timezone` | TEXT | no | IANA name (`users_tz_ck`); informational (retention uses the account's) | users.timezone |
| `bot_flag` | BOOLEAN | no | TRUE for the 18 bot users, excluded everywhere | users.bot_flag |

### identity_links
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `identity_link_id` | TEXT | no | Key | identity_links.identity_link_id |
| `anonymous_id` | TEXT | no | The anonymous id (`a-00001` ..); unique, so the earliest link fixes the user | identity_links.anonymous_id |
| `user_id` | TEXT | no | FK to `users` | identity_links.user_id |
| `linked_at` | TIMESTAMPTZ | no | The instant of the link: it attributes events with `event_at >= linked_at` only | identity_links.linked_at |
| `rule_version` | TEXT | no | Identity-resolution rule version, `v1` | identity_links.rule_version |
| `created_by` | TEXT | yes | Actor of a C02 link; NULL on every seeded row | not loaded |

### sessions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `session_id` | TEXT | no | Key | sessions.session_id |
| `user_id` | TEXT | no | FK to `users` | sessions.user_id |
| `started_at` | TIMESTAMPTZ | no | Start (UTC); the account's local date of this instant is the retention day | sessions.started_at |
| `ended_at` | TIMESTAMPTZ | yes | End; NULL when unknown; not before the start (`sessions_interval_ck`) | sessions.ended_at |
| `device_type` | TEXT | no | `web` or `mobile` | sessions.device_type |

### events
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `event_id` | TEXT | no | Key (`ev-000001` ..); a re-sent id with identical content is idempotent, with different content rejected | events.event_id |
| `user_id` | TEXT | yes | The user, or NULL for an anonymous event; no foreign key (unknown users are logged and excluded) | events.user_id |
| `anonymous_id` | TEXT | yes | The anonymous id, or NULL; an event with neither is an unknown identity | events.anonymous_id |
| `event_name` | TEXT | no | `visit`, `signup`, `onboarding_step_1..3`, `activated`, `feature_used` or `product_error` (`^[a-z][a-z0-9_]{0,63}$`, `events_name_ck`) | events.event_name |
| `event_at` | TIMESTAMPTZ | no | The business instant (UTC) | events.event_at |
| `received_at` | TIMESTAMPTZ | no | When the log accepted it; a run at cutoff C uses `received_at <= C`; stamped by the server clock (an admin may backfill) | events.received_at |
| `ingested_by` | TEXT | yes | Actor of a C01 ingest; NULL on every seeded row | not loaded |

### event_properties
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `property_id` | TEXT | no | Key | event_properties.property_id |
| `event_id` | TEXT | no | FK to `events` | event_properties.event_id |
| `property_key` | TEXT | no | `feature` or `error_code`; unique per event | event_properties.property_key |
| `property_value` | TEXT | no | The value as a string | event_properties.property_value |
| `value_type` | TEXT | no | Always `string` (`event_props_type_ck`) | event_properties.value_type |

### subscriptions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `subscription_id` | TEXT | no | Key | subscriptions.subscription_id |
| `account_id` | TEXT | no | FK to `accounts` | subscriptions.account_id |
| `starts_at` | TIMESTAMPTZ | no | Start (UTC); revenue counts when it lies in the plan's half-open revenue window and is not after the cutoff | subscriptions.starts_at |
| `ends_at` | TIMESTAMPTZ | yes | End; NULL when open; not before the start (`subscriptions_amt_ck`) | subscriptions.ends_at |
| `status` | TEXT | no | `active`, `ended`, `trial` or `refunded`; only active and ended carry revenue | subscriptions.status |
| `amount_usd` | NUMERIC(14,2) | no | USD, exact, not negative | subscriptions.amount_usd |

### experiment_versions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `experiment_version_id` | TEXT | no | Key (`xv-001`, `xv-002`) | experiment_versions.experiment_version_id |
| `name` | TEXT | no | Display name | experiment_versions.name |
| `unit_type` | TEXT | no | `account` (`versions_unit_ck`) | experiment_versions.unit_type |
| `primary_metric` | TEXT | no | `activation_7d` | experiment_versions.primary_metric |
| `planned_end` | TIMESTAMPTZ | no | The horizon: a run with `cutoff_at` before it is interim | experiment_versions.planned_end |

### analysis_plans
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `experiment_version_id` | TEXT | no | Key; one plan per version (no foreign key, see above) | manifest analysis_plans |
| `plan` | JSONB | no | The plan as frozen without its hash: allocation, activation window, confidence, guardrail, planned_end, primary_metric, revenue window, srm thresholds, unit_type, z, frozen_at | manifest analysis_plans |
| `config_hash` | TEXT | no | sha256 hex of the key-sorted compact JSON of `plan` (`plans_hash_ck`) | manifest analysis_plans.config_hash |
| `frozen_at` | TIMESTAMPTZ | no | When the plan was frozen; `plan_frozen` requires it at or before the first logged run (D-10) | manifest analysis_plans.frozen_at |
| `frozen_by` | TEXT | yes | Actor of a C06 freeze; `seed` on seeded rows | seed |

### assignments
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `assignment_id` | TEXT | no | Key (`as-0001` ..) | assignments.assignment_id |
| `experiment_version_id` | TEXT | no | FK to `experiment_versions` | assignments.experiment_version_id |
| `unit_id` | TEXT | no | FK to `accounts`: the account is the unit | assignments.unit_id |
| `variant` | TEXT | no | `control` or `treatment`; fixed by the first assignment | assignments.variant |
| `assigned_at` | TIMESTAMPTZ | no | When the account was assigned; a run sees it only when `assigned_at <= cutoff` (D-08) | assignments.assigned_at |
| `created_by` | TEXT | yes | Actor of a C04 assignment; NULL on seeded rows | not loaded |

### exposures
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `exposure_id` | TEXT | no | Key | exposures.exposure_id |
| `assignment_id` | TEXT | no | FK to `assignments`; one exposure per assignment | exposures.assignment_id |
| `exposed_at` | TIMESTAMPTZ | no | When the account saw the change; not before `assigned_at` (trigger `exposures_not_early`) | exposures.exposed_at |
| `surface` | TEXT | no | `onboarding_checklist` | exposures.surface |
| `event_id` | TEXT | yes | Optional link to an exposure event; NULL on every row | exposures.event_id |
| `created_by` | TEXT | yes | Actor of a C05 exposure; NULL on seeded rows | not loaded |

### metric_observations
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `observation_id` | TEXT | no | Key | metric_observations.observation_id |
| `assignment_id` | TEXT | no | FK to `assignments` | metric_observations.assignment_id |
| `metric_name` | TEXT | no | `activation_7d`; unique per assignment | metric_observations.metric_name |
| `value` | TEXT | no | `'0'` or `'1'` (`observations_value_ck`) | metric_observations.value |
| `window_end` | TIMESTAMPTZ | no | signup + 7 x 24 h; the observation exists for a run only when `window_end <= cutoff` | metric_observations.window_end |

### analysis_runs
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `analysis_id` | TEXT | no | Key (`an-001` ..) | analysis_runs.analysis_id |
| `experiment_version_id` | TEXT | no | FK to `experiment_versions` | analysis_runs.experiment_version_id |
| `cutoff_at` | TIMESTAMPTZ | no | The cutoff of the run: it sees only facts that existed by then | analysis_runs.cutoff_at |
| `config_hash` | TEXT | no | The plan hash the run cites (`runs_hash_ck`) | analysis_runs.config_hash |
| `created_at` | TIMESTAMPTZ | no | When the run was logged (five minutes after its cutoff in the snapshot); orders runs for `prior_runs` | analysis_runs.created_at |
| `created_by` | TEXT | yes | `seed` on seeded rows, the actor on C08 runs | seed |
| `interim` | BOOLEAN | yes | Stored copy of the interim flag of a C08 run; NULL on seeded rows (the metrics derive it: `cutoff_at < planned_end`) | C08 |
| `srm_verdict` | TEXT | yes | OK, MISMATCH or INSUFFICIENT of a C08 run (`runs_srm_ck`); NULL on seeded rows | C08 |
| `conclusive` | BOOLEAN | yes | Stored copy of the D-10 conclusive flag of a C08 run; NULL on seeded rows; never read by the SQL reference | C08 |
| `prior_runs` | INT | yes | Runs of the version logged before this one (C08); NULL on seeded rows | C08 |
| `result` | JSONB | yes | The result a C08 run published (never recomputed on read); NULL on seeded rows | C08 |

### funnel_definitions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `definition_id` | TEXT | no | Part of the key (`fun-001`) | metric_windows.funnel.definition_id |
| `version` | INT | no | Part of the key; versions are never edited | metric_windows.funnel.version |
| `steps` | TEXT[] | no | Ordered event names, at least two (`funnel_steps_ck`) | metric_windows.funnel.steps |
| `max_gap_hours` | INT | no | Maximum gap between steps in hours, inclusive | metric_windows.funnel.max_gap_hours |
| `window_from` | TIMESTAMPTZ | no | Window start (the first step only), half open | metric_windows.funnel.from |
| `window_to` | TIMESTAMPTZ | no | Window end, after `window_from` | metric_windows.funnel.to |
| `created_by` | TEXT | yes | Actor; `seed` on the seeded row | seed |
| `created_at` | TIMESTAMPTZ | no | Default now(); orders versions | default |

### metric_config
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `id` | INT | no | Always 1 | seed |
| `windows` | JSONB | no | JSON: signup_conversion, activation (with window_days), retention (local dates), feature_adoption (feature, eligible plans) | manifest metric_windows |

### guardrail_reviews
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `review_id` | TEXT | no | Key | C09 |
| `analysis_id` | TEXT | no | FK to `analysis_runs`; one review per run | C09 |
| `experiment_version_id` | TEXT | no | FK to `experiment_versions` | C09 |
| `verdict` | TEXT | no | OK, HARMFUL or INSUFFICIENT (`reviews_verdict_ck`) | C09 |
| `result` | JSONB | no | The review as computed: error rates, difference, Newcombe interval | C09 |
| `reviewed_by` | TEXT | no | Actor | C09 |
| `reviewed_at` | TIMESTAMPTZ | no | Default now() | default |

### decisions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `decision_id` | TEXT | no | Key | C10 |
| `experiment_version_id` | TEXT | no | FK to `experiment_versions` | C10 |
| `analysis_id` | TEXT | no | FK to `analysis_runs`; one decision per run | C10 |
| `review_id` | TEXT | no | FK to `guardrail_reviews`; must belong to the run | C10 |
| `decision` | TEXT | no | ship, stop or inconclusive (`decisions_kind_ck`) | C10 |
| `basis` | TEXT | no | Always `primary`: a segment is never a decision basis | C10 |
| `rationale` | TEXT | no | Non-empty text (`decisions_kind_ck`) | C10 |
| `decided_by` | TEXT | no | Actor | C10 |
| `decided_role` | TEXT | no | experimenter or admin (`decisions_role_ck`) | C10 |
| `decided_at` | TIMESTAMPTZ | no | Server clock; an admin with `backfill: true` may state it, never before the run | C10 |
| `evidence` | JSONB | no | JSON: the run, the review, the warnings | C10 |

### rejected_records
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `batch_id` | TEXT | no | Part of the key: the load or request that refused the row | ingest |
| `entity` | TEXT | no | The entity of the row | ingest |
| `id` | TEXT | no | The row's own id | ingest |
| `reason_code` | TEXT | no | MALFORMED_RECORD, DUPLICATE_ID, UNKNOWN_ACCOUNT, UNKNOWN_USER, UNKNOWN_EVENT, UNKNOWN_EXPERIMENT_VERSION, UNKNOWN_UNIT, UNKNOWN_VARIANT, INELIGIBLE_UNIT, INVALID_INTERVAL, IDENTITY_CONFLICT, UNSUPPORTED_UNIT_TYPE, ASSIGNMENT_CONFLICT, EXPOSURE_BEFORE_ASSIGNMENT, DEPENDENT_REJECTED, UNKNOWN_ASSIGNMENT, EVENT_IN_FUTURE, RECEIVED_BEFORE_EVENT | ingest |
| `raw_row` | JSONB | no | The row as it arrived | ingest |
| `ordinal` | INT | no | Separates two refused occurrences of one id | ingest |
| `created_at` | TIMESTAMPTZ | no | Default now() | default |

### audit_events
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `event_id` | TEXT | no | Key | API |
| `entity_type` | TEXT | no | What the command touched | API |
| `entity_id` | TEXT | no | Which one | API |
| `experiment_version_id` | TEXT | yes | The version, when the command has one (used for the audit read and the backdating rule) | API |
| `action` | TEXT | no | The command or `record-decision-refused` | API |
| `actor_id` | TEXT | no | Who | API |
| `occurred_at` | TIMESTAMPTZ | no | Server clock | API |
| `before_version` | INT | yes | Version before the effect | API |
| `after_version` | INT | yes | Version after the effect | API |
| `reason` | TEXT | yes | Reason or rule id | API |
| `request_id` | TEXT | yes | The caller's request id | API |
| `details` | JSONB | no | JSON: the effect, `backfill` and the stated instant when an admin backfilled | API |

### command_results
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `idempotency_key` | TEXT | no | Key | API |
| `payload_hash` | TEXT | no | Hash of the payload including `dataset_version` | API |
| `actor_id` | TEXT | no | Bound to the key | API |
| `actor_role` | TEXT | no | analyst, experimenter or admin (`command_results_role_ck`) | API |
| `command_id` | TEXT | no | The command's id | API |
| `status` | TEXT | no | The stored status | API |
| `result` | JSONB | no | The stored response replayed for the same key | API |
| `created_at` | TIMESTAMPTZ | no | Default now() | default |

### dataset_versions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `dataset_version` | TEXT | no | Key; the version a command must carry | manifest.dataset_version |
| `dataset_hash` | TEXT | no | sha256 of the generator's entity files (snapshot) or of the canonical inputs (golden) | manifest.dataset_hash |
| `contract_version` | TEXT | no | `1` | seed |
| `created_at` | TIMESTAMPTZ | no | Default now() | default |

### t_critical_975
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `df` | INT | no | Degrees of freedom, 1 to 2000 | t_quantiles.csv |
| `t` | NUMERIC(30,20) | no | The two-sided 95% quantile to 20 decimals | t_quantiles.csv |

## 3. Foreign keys

Enforced in `0001` (default `NO ACTION`): `users.account_id` to `accounts`; `identity_links.user_id` to `users`; `sessions.user_id` to `users`; `event_properties.event_id` to `events`; `subscriptions.account_id` to `accounts`; `assignments.experiment_version_id` to `experiment_versions`; `assignments.unit_id` to `accounts`; `exposures.assignment_id` to `assignments`; `metric_observations.assignment_id` to `assignments`; `analysis_runs.experiment_version_id` to `experiment_versions`; `guardrail_reviews.analysis_id` to `analysis_runs`; `guardrail_reviews.experiment_version_id` to `experiment_versions`; `decisions.experiment_version_id` to `experiment_versions`, `decisions.analysis_id` to `analysis_runs`, `decisions.review_id` to `guardrail_reviews`.
Logical joins the contract relies on and the database does not enforce: `events.user_id` to `users` and `events.anonymous_id` to `identity_links.anonymous_id` (an event of an unknown identity is logged and excluded, not a load error); `analysis_plans.experiment_version_id` to `experiment_versions` (a plan is configuration; C06 checks the version exists); `exposures.event_id` to `events` (NULL on every row); `audit_events.entity_id` to the entity named by `entity_type`.

## 4. Constraints and triggers (`0002`)

* **Checks:** timezones are known IANA names (`ps_valid_tz`, on `accounts` and `users`); event names match `^[a-z][a-z0-9_]{0,63}$`; property types are `string`; `subscriptions.amount_usd >= 0` and `ends_at >= starts_at`; session intervals are ordered; the experiment unit type is `account`; observation values are `'0'` or `'1'`; plan and run hashes are 64 lower-case hex; the SRM verdict vocabulary; funnel definitions have at least two steps, a positive gap and an ordered window; `metric_config.id = 1`; guardrail verdicts OK, HARMFUL, INSUFFICIENT; decisions ship, stop, inconclusive with `basis = 'primary'` and a non-empty rationale; decision roles experimenter or admin; command roles analyst, experimenter, admin.
* **Uniqueness:** `identity_links (anonymous_id)`; `event_properties (event_id, property_key)`; `assignments (experiment_version_id, unit_id)` (the first assignment fixes the variant); `exposures (assignment_id)`; `metric_observations (assignment_id, metric_name)`; `guardrail_reviews (analysis_id)`; `decisions (analysis_id)`; every primary key.
* **Triggers:** `<table>_immutable` and `<table>_no_truncate` on the fourteen append-only tables; `exposures_not_early` (an exposure never precedes its assignment); `assignments_eligible` (an internal account is never randomised).
* **Helper functions:** `ps_valid_tz(text)` and `ps_canonical_json(jsonb)` (compact JSON with keys sorted by code point, the form the plan hash is taken over; also used by `data/sql/reference_metrics.sql`).
* **Not enforced by the database (application rules):** exactly two arms named control and treatment (`VARIANTS_NOT_TWO`), the server-stamped instants and their admin backfill, the refusal of a future cutoff, the freeze-before-first-run order, the conclusive rule, the sample-ratio verdict, the blocking rules of C10 and idempotency are decided by the domain and the API inside one transaction; the database cannot see them.

## 5. Source-to-target mapping

| Source (`web/public/data/` or fixture) | Target | How |
|---|---|---|
| `accounts`, `users`, `sessions`, `subscriptions`, `experiment_versions` | same-named tables | `seed.py`, `ON CONFLICT DO NOTHING`; the reference entities |
| `identity_links`, `events`, `event_properties` | same-named tables | through the domain's `validate_batch`; every well-formed event row is logged (duplicates and late rows included); `created_by` / `ingested_by` stay NULL |
| `assignments`, `exposures`, `metric_observations`, `analysis_runs` | same-named tables | `created_by` stays NULL; runs are inserted with `created_by = 'seed'` and the core columns only |
| manifest `analysis_plans` (both versions) | `analysis_plans` | one row per plan; `frozen_by = 'seed'`; `config_hash` as published |
| manifest `metric_windows` | `metric_config`, `funnel_definitions` | one `metric_config` row (without the funnel) and one funnel definition `fun-001` v1 |
| ingest rejections | `rejected_records` | none on the snapshot or the golden fixture |
| the generator's `manifest.json` | `dataset_versions` | version `ps-20261026-20261026` and hash `12672f9c39402517083bbbbe9164cbefe3435361dff086eb0d9e16e60f9b66f8` (`seed(..., dataset_version=, dataset_hash=)`) |
| `data/sql/t_quantiles.csv` | `t_critical_975` | 2,000 rows, one statement |
| `pg_timezone_names` | `ps_timezones` | copied by the migration |

The published files and their generator hash are the source of truth for the dataset; the database is a derived, rebuildable copy. Reconciliation: `data/sql/analysis/run_all.py` loads exactly this mapping into scratch databases and compares what the SQL finds with the Python domain (`sql-analysis.md`).

## 6. Known gaps and disclosures

* **The D-10 rules sit in the application, not in the schema.** Server-stamped instants, the two-arm rule, the freeze order and the conclusive rule are enforced by the API and the domain; a direct SQL insert would bypass them (the triggers cover only exposures before assignments and internal accounts).
* **Stored results are copies.** `analysis_runs.interim`, `srm_verdict`, `conclusive`, `prior_runs` and `result` are what a C08 run published; they are NULL on the five seeded runs and the SQL reference never reads them (it recomputes from facts).
* **No decision exists in a seeded database.** `guardrail_reviews`, `decisions`, `audit_events` and `command_results` are empty until the API writes them; the decision screen of the public site simulates them in browser memory.
* **`created_by` / `ingested_by` columns are NULL on every seeded row** because the generated files do not carry them; the columns exist for the API.
* **`exposures.event_id` is NULL on every row** (exposure is recorded by C05, not by an event).
* **The instrumentation gap (INJ-10) is in the data, not the schema.** `events` has no `activated` row for signups before 2026-04-08; 11 mature v1 accounts are affected and the published lift (+9.50 pp) sits inside it (drawn +11.50, +9.96 excluding them). The domain cannot see it.
* **Two hashes.** The generator's `dataset_hash` (over the entity files) is stored in `dataset_versions` for the snapshot; the golden database stores the sha256 of its canonical inputs instead. Both are deterministic.
* **Row counts** are those of the scratch databases named above; the shared development database and the hosted `postgres:16` service hold whatever the tests last loaded. `ps_timezones` has 499 rows on the scratch server and depends on its tzdata.
