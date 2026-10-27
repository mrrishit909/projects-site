# ChangeWorks: data dictionary (P09-ART-03)

**Synthetic data only.** Every row comes from the seeded generator (`data/generate.py`, seed 20261026); nothing is a record of a real organisation, person or budget.
Dataset `cw-20261026-20261026` (generator `dataset_hash` `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`), contract v1, code revision `29948f9` (`29948f92f0c3839f070e4b6499b99f3810d1361b`), as-of 2026-10-05T00:00:00Z.
The decision the data serves: **which transformation initiative should be funded, and how will success be established?** (P09-GOAL-01).

**How to read it without installing anything:** section 1 lists every table with its grain, row count in the loaded snapshot, source contract and deletion policy; section 2 lists every column with its PostgreSQL type and constraint text, copied from the migrations (`data/sql/migrations/0001_schema.sql`, `0003_review9.sql`); section 3 gives the foreign keys; section 4 the source-to-target mapping from the published JSON files to the tables and on to the analysis (`data/sql/analysis/`), the workbook and the BI files; section 5 the units and absence rules. `erd.md` draws the same tables. Observed (the loaded rows), constructed (the generator's designed relationships and injections) and hypothetical (benefits to a real organisation: not claimed) are kept apart.

## 1. Tables, grain and row counts (the snapshot loaded into `artifacts09_snapshot` by `prepare_snapshot.py`)
| Table | Grain | Rows | Source contract | Source file | Deletion policy |
|---|---|---|---|---|---|
| `dataset_config` | one row: how the dataset counts periods and the as-of it was loaded for | 1 | D-04, D-06 | manifest.json `config` | seeded once; CHECK `dataset_config_day_ck` (period start day <= 28, R9-14) |
| `initiatives` | one transformation initiative | 24 | P09-DATA-01, D-02, D-03 | initiatives.json | mutable operational row: only status, schedule and the approved baseline change, each change bumps `version` |
| `process_baselines` | one measured baseline per (initiative, baseline_version) | 30 | P09-DATA-02, D-02 (evidence, never assumptions) | process_baselines.json | append-only; an approved version is frozen (BASELINE_FROZEN); a correction is a new version with a reason |
| `baseline_approvals` | one approval of one baseline version | 18 | D-02, D-06 | derived by data/seed.py from `initiatives.baseline_version` | append-only |
| `assumption_versions` | one version 1..n of one named assumption of an initiative | 160 | P09-DATA-03, D-02, D-P9-14 | assumption_versions.json | append-only; reserved names adoption_ramp, target_minutes_per_case, capacity_hourly_rate, monthly_rate_conversion |
| `opportunity_scores` | one weighted score version of an initiative (C02) | 0 | D-06 | written by C02 only (0 in the snapshot) | append-only |
| `resources` | one shared resource with a capacity per period | 8 | D-03 | resources.json | append-only |
| `scenario_versions` | one immutable scenario version | 30 | P09-DATA-12, D-02, D-09 R9-01 | scenario_versions.json | immutable; only draft -> proposed (C07), once; never deleted (SCENARIO_IMMUTABLE) |
| `scenario_initiatives` | one initiative of one scenario | 210 | D-02, D-09 R9-01 | scenario_versions.json `initiative_ids` | sealed at `initiatives_expected` (trigger `scenario_initiatives_sealed`) |
| `scenario_pins` | one assumption version pinned by one scenario | 416 | D-P9-14, D-09 R9-01 | scenario_versions.json `pinned_assumption_ids` | sealed at `pins_expected` (trigger `scenario_pins_sealed`) |
| `cost_items` | one cost row: a one-time cost in one period or a recurring cost over [start_period, end_period) | 900 | P09-DATA-04, D-01, D-P9-16, R9-05 | cost_items.json | append-only; trigger `cost_items_key_guard` (COST_KEY_BASIS_CONFLICT) |
| `expanded_costs` | one period of one recurring cost in one scenario (written by C03) | 0 | D-01 | written by C03 only (0 in the snapshot; the analysis expands from `cost_items`) | append-only |
| `benefit_items` | one planned benefit row of one class in one period | 700 | P09-DATA-05, D-01 | benefit_items.json | append-only; CHECK `benefit_items_evidence_ck` (R9-04) |
| `dependencies` | one dependency edge (initiative depends on prerequisite) | 40 | P09-DATA-06, D-03 | dependencies.json | append-only; a cycle is refused DEPENDENCY_CYCLE before the write |
| `stakeholder_groups` | one synthetic stakeholder group | 60 | P09-DATA-07, D-03 | stakeholder_groups.json | append-only; labels must be synthetic (LABEL_NOT_SYNTHETIC) |
| `impact_mappings` | one operating change an initiative causes for a group | 106 | D-03, D-P9-24 | impact_mappings.json | append-only; validated and counted only |
| `resource_allocations` | one allocation of a resource to an initiative in one period | 557 | D-03, D-P9-15 | resource_allocations.json | append-only; a crossing row is refused RESOURCE_OVERALLOCATED |
| `readiness_assessments` | one score of one ADKAR-inspired dimension of one group | 300 | P09-DATA-08, D-03 | readiness_assessments.json | append-only |
| `adoption_observations` | one adoption observation with its denominator | 500 | P09-DATA-09, D-03, R9-11 | adoption_observations.json | append-only |
| `training_completions` | one training completion record (a separate series) | 200 | D-03, R9-11 | training_completions.json | append-only |
| `benefit_observations` | one observed value of one planned benefit | 400 | P09-DATA-10, D-02, R9-11 | benefit_observations.json | append-only; CHECK `benefit_obs_evidence_ck` |
| `risk_items` | one risk with probability and USD impact | 120 | P09-DATA-11, D-02, D-P9-13 | risk_items.json | append-only |
| `forecast_versions` | one period of one forecast version of an initiative | 144 | D-02, D-P9-17, R9-10 | forecast_versions.json | append-only; FORECAST_OVERWRITE / VERSION_EXISTS |
| `rejected_records` | one rejected input row with its reason and raw row | 0 | D-05 D-P9-01 | written by data/seed.py and the commands (0: the snapshot loads clean) | append-only |
| `audit_events` | one audited command or refusal | 0 | D-06 | written by the commands only | append-only |
| `command_results` | one stored command result per idempotency key | 0 | D-06 | written by the commands only | append-only |
| `dataset_versions` | one loaded dataset version and hash | 1 | D-06 | data/seed.py | append-only |
| `schema_migrations` | one applied migration file and its checksum | 3 | data/migrate.py | data/migrate.py | a changed applied file is refused |

Append-only events and versioned definitions: UPDATE, DELETE and TRUNCATE are refused by trigger (`cw_forbid_mutation`, `0002_constraints.sql`) on 24 tables, every table above except `dataset_config`, `schema_migrations`, `initiatives` (guarded by `cw_initiative_guard`: only status, schedule and the approved baseline change) and `scenario_versions` (guarded by `cw_scenario_guard`: only draft -> proposed, once); the refusal names its rule (BASELINE_FROZEN, FORECAST_OVERWRITE, SCENARIO_IMMUTABLE, APPEND_ONLY, ...). Rejected input rows are never dropped silently: they go to `rejected_records` with their raw row and reason (the published snapshot loads with 0 rejected; the rejected variant fixture carries 30).

## 2. Columns (from the migrations; types as declared)

### dataset_config
| Column | Type | Declared |
|---|---|---|
| `id` | INT | PRIMARY KEY |
| `period_basis` | TEXT | NOT NULL |
| `period_start` | DATE | NOT NULL |
| `as_of` | TIMESTAMPTZ | (nullable) |

### initiatives
| Column | Type | Declared |
|---|---|---|
| `initiative_id` | TEXT | PRIMARY KEY |
| `title` | TEXT | NOT NULL |
| `sponsor_id` | TEXT | NOT NULL |
| `status` | TEXT | NOT NULL |
| `baseline_version` | TEXT | (nullable) |
| `requested_start_period` | INT | NOT NULL |
| `duration_periods` | INT | NOT NULL |
| `deployment_period` | INT | NOT NULL |
| `eligibility_rule_version` | TEXT | NOT NULL |
| `version` | INT | NOT NULL DEFAULT 1 |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| `created_by` | TEXT | NOT NULL DEFAULT 'seed' |

### process_baselines
| Column | Type | Declared |
|---|---|---|
| `baseline_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `baseline_version` | TEXT | NOT NULL |
| `volume` | BIGINT | NOT NULL |
| `minutes_per_case` | INT | NOT NULL |
| `error_rate` | NUMERIC(7,6) | NOT NULL |
| `evidence_ref` | TEXT | NOT NULL |
| `measured_at` | TIMESTAMPTZ | NOT NULL |
| `reason` | TEXT | (nullable) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| `created_by` | TEXT | NOT NULL DEFAULT 'seed' |

### baseline_approvals
| Column | Type | Declared |
|---|---|---|
| `approval_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL |
| `baseline_version` | TEXT | NOT NULL |
| `approved_by` | TEXT | NOT NULL |
| `approved_at` | TIMESTAMPTZ | NOT NULL |
| `reason` | TEXT | (nullable) |

### assumption_versions
| Column | Type | Declared |
|---|---|---|
| `assumption_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | REFERENCES initiatives (initiative_id) |
| `name` | TEXT | NOT NULL |
| `version_number` | INT | NOT NULL |
| `value` | TEXT | (nullable) |
| `value_list` | JSONB | (nullable) |
| `unit` | TEXT | (nullable) |
| `rationale` | TEXT | NOT NULL |
| `author_id` | TEXT | NOT NULL |
| `evidence_ref` | TEXT | (nullable) |
| `staffing_change_evidence_ref` | TEXT | (nullable) |
| `created_at` | TIMESTAMPTZ | NOT NULL |

### opportunity_scores
| Column | Type | Declared |
|---|---|---|
| `score_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `version_number` | INT | NOT NULL |
| `criteria` | JSONB | NOT NULL |
| `weighted_score` | NUMERIC(10,4) | NOT NULL |
| `weighted_exact` | TEXT | NOT NULL |
| `rationale` | TEXT | NOT NULL |
| `author_id` | TEXT | NOT NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |

### resources
| Column | Type | Declared |
|---|---|---|
| `resource_id` | TEXT | PRIMARY KEY |
| `name` | TEXT | NOT NULL |
| `capacity_per_period` | NUMERIC(20,6) | NOT NULL |
| `unit` | TEXT | NOT NULL |

### scenario_versions
| Column | Type | Declared |
|---|---|---|
| `scenario_id` | TEXT | PRIMARY KEY |
| `baseline_version` | TEXT | NOT NULL |
| `discount_rate` | NUMERIC(7,6) | NOT NULL |
| `rate_basis` | TEXT | NOT NULL |
| `rate_conversion_assumption_id` | TEXT | REFERENCES assumption_versions (assumption_id) |
| `horizon_periods` | INT | NOT NULL |
| `status` | TEXT | NOT NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `created_by` | TEXT | NOT NULL DEFAULT 'seed' |
| `proposed_at` | TIMESTAMPTZ | (nullable) |
| `proposed_by` | TEXT | (nullable) |
| `comparison` | JSONB | (nullable) |
| `residual_explanation` | TEXT | (nullable) |
| `initiatives_expected` | INT | (0003_review9.sql) |
| `pins_expected` | INT | (0003_review9.sql) |
| `snapshot_hash` | TEXT | (0003_review9.sql) |

### scenario_initiatives
| Column | Type | Declared |
|---|---|---|
| `scenario_id` | TEXT | NOT NULL REFERENCES scenario_versions (scenario_id) |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |

### scenario_pins
| Column | Type | Declared |
|---|---|---|
| `scenario_id` | TEXT | NOT NULL REFERENCES scenario_versions (scenario_id) |
| `assumption_id` | TEXT | NOT NULL REFERENCES assumption_versions (assumption_id) |

### cost_items
| Column | Type | Declared |
|---|---|---|
| `cost_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `cost_key` | TEXT | NOT NULL |
| `cost_type` | TEXT | NOT NULL |
| `cost_basis` | TEXT | NOT NULL |
| `amount` | NUMERIC(20,6) | NOT NULL |
| `period_index` | INT | (nullable) |
| `start_period` | INT | (nullable) |
| `end_period` | INT | (nullable) |
| `baseline_version` | TEXT | (nullable) |
| `recorded_at` | TIMESTAMPTZ | (0003_review9.sql) |

### expanded_costs
| Column | Type | Declared |
|---|---|---|
| `scenario_id` | TEXT | NOT NULL REFERENCES scenario_versions (scenario_id) |
| `cost_id` | TEXT | NOT NULL REFERENCES cost_items (cost_id) |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `period_index` | INT | NOT NULL |
| `amount` | NUMERIC(20,6) | NOT NULL |

### benefit_items
| Column | Type | Declared |
|---|---|---|
| `benefit_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `benefit_type` | TEXT | NOT NULL |
| `amount` | NUMERIC(20,6) | NOT NULL,          -- USD, or hours for capacity |
| `period_index` | INT | NOT NULL |
| `starts_period` | INT | NOT NULL |
| `unit` | TEXT | NOT NULL |
| `cash_realisation` | BOOLEAN | (nullable) |
| `evidence_ref` | TEXT | (nullable) |
| `benefit_source_key` | TEXT | (nullable) |
| `baseline_trend_per_period` | NUMERIC(20,6) | (nullable) |
| `recorded_at` | TIMESTAMPTZ | (0003_review9.sql) |

### dependencies
| Column | Type | Declared |
|---|---|---|
| `dependency_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `prerequisite_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `dependency_type` | TEXT | NOT NULL |
| `lag_periods` | INT | NOT NULL |

### stakeholder_groups
| Column | Type | Declared |
|---|---|---|
| `group_id` | TEXT | PRIMARY KEY |
| `group_name` | TEXT | NOT NULL |
| `owner_id` | TEXT | NOT NULL |
| `affected_count` | INT | NOT NULL |
| `impact_level` | TEXT | NOT NULL |

### impact_mappings
| Column | Type | Declared |
|---|---|---|
| `mapping_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `group_id` | TEXT | NOT NULL REFERENCES stakeholder_groups (group_id) |
| `operating_change` | TEXT | NOT NULL |
| `impact_level` | TEXT | NOT NULL |

### resource_allocations
| Column | Type | Declared |
|---|---|---|
| `allocation_id` | TEXT | PRIMARY KEY |
| `resource_id` | TEXT | NOT NULL REFERENCES resources (resource_id) |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `period_index` | INT | NOT NULL |
| `amount` | NUMERIC(20,6) | NOT NULL |

### readiness_assessments
| Column | Type | Declared |
|---|---|---|
| `assessment_id` | TEXT | PRIMARY KEY |
| `group_id` | TEXT | NOT NULL REFERENCES stakeholder_groups (group_id) |
| `dimension` | TEXT | NOT NULL |
| `score` | INT | NOT NULL |
| `weight` | NUMERIC(20,6) | NOT NULL |
| `assessed_at` | TIMESTAMPTZ | NOT NULL |
| `assessed_by` | TEXT | NOT NULL DEFAULT 'seed' |

### adoption_observations
| Column | Type | Declared |
|---|---|---|
| `observation_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `eligible_count` | INT | NOT NULL |
| `adopted_count` | INT | NOT NULL |
| `observed_at` | TIMESTAMPTZ | NOT NULL |
| `eligibility_rule_version` | TEXT | NOT NULL |
| `recorded_by` | TEXT | NOT NULL DEFAULT 'seed' |
| `recorded_at` | TIMESTAMPTZ | (0003_review9.sql) |

### training_completions
| Column | Type | Declared |
|---|---|---|
| `training_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `eligible_trainees` | INT | NOT NULL |
| `completed` | INT | NOT NULL |
| `recorded_at` | TIMESTAMPTZ | NOT NULL |
| `eligibility_rule_version` | TEXT | NOT NULL |
| `recorded_by` | TEXT | NOT NULL DEFAULT 'seed' |
| `entered_at` | TIMESTAMPTZ | (0003_review9.sql) |

### benefit_observations
| Column | Type | Declared |
|---|---|---|
| `benefit_observation_id` | TEXT | PRIMARY KEY |
| `benefit_id` | TEXT | NOT NULL REFERENCES benefit_items (benefit_id) |
| `measured_value` | NUMERIC(20,6) | NOT NULL |
| `evidence_ref` | TEXT | NOT NULL |
| `observed_at` | TIMESTAMPTZ | NOT NULL |
| `recorded_by` | TEXT | NOT NULL DEFAULT 'seed' |
| `recorded_at` | TIMESTAMPTZ | (0003_review9.sql) |

### risk_items
| Column | Type | Declared |
|---|---|---|
| `risk_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `probability` | NUMERIC(7,6) | NOT NULL |
| `impact` | NUMERIC(20,6) | NOT NULL,                  -- USD (D-P9-13) |
| `mitigation` | TEXT | NOT NULL |

### forecast_versions
| Column | Type | Declared |
|---|---|---|
| `forecast_id` | TEXT | PRIMARY KEY |
| `initiative_id` | TEXT | NOT NULL REFERENCES initiatives (initiative_id) |
| `version_number` | INT | NOT NULL |
| `period_index` | INT | NOT NULL |
| `amount` | NUMERIC(20,6) | NOT NULL |
| `reason` | TEXT | NOT NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `created_by` | TEXT | NOT NULL DEFAULT 'seed' |

### rejected_records
| Column | Type | Declared |
|---|---|---|
| `seq` | BIGINT | GENERATED ALWAYS AS IDENTITY |
| `batch_id` | TEXT | NOT NULL |
| `entity` | TEXT | NOT NULL |
| `id` | TEXT | NOT NULL |
| `reason_code` | TEXT | NOT NULL |
| `details` | JSONB | NOT NULL DEFAULT '{}'::jsonb |
| `raw_row` | JSONB | NOT NULL |
| `ordinal` | INT | NOT NULL DEFAULT 0 |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### audit_events
| Column | Type | Declared |
|---|---|---|
| `event_id` | TEXT | PRIMARY KEY |
| `entity_type` | TEXT | NOT NULL |
| `entity_id` | TEXT | NOT NULL |
| `action` | TEXT | NOT NULL |
| `actor_id` | TEXT | NOT NULL |
| `actor_role` | TEXT | (nullable) |
| `occurred_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| `before_version` | INT | (nullable) |
| `after_version` | INT | (nullable) |
| `reason` | TEXT | (nullable) |
| `request_id` | TEXT | (nullable) |
| `details` | JSONB | NOT NULL DEFAULT '{}'::jsonb |

### command_results
| Column | Type | Declared |
|---|---|---|
| `idempotency_key` | TEXT | PRIMARY KEY |
| `payload_hash` | TEXT | NOT NULL |
| `actor_id` | TEXT | NOT NULL |
| `actor_role` | TEXT | NOT NULL |
| `command_id` | TEXT | NOT NULL |
| `status` | TEXT | NOT NULL |
| `result` | JSONB | NOT NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### dataset_versions
| Column | Type | Declared |
|---|---|---|
| `dataset_version` | TEXT | PRIMARY KEY |
| `dataset_hash` | TEXT | NOT NULL |
| `contract_version` | TEXT | NOT NULL |
| `as_of` | TIMESTAMPTZ | (nullable) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### schema_migrations
| Column | Type | Declared |
|---|---|---|
| `version` | TEXT | PRIMARY KEY |
| `checksum` | TEXT | NOT NULL |
| `applied_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

## 3. Foreign keys
| Table | Foreign key |
|---|---|
| `process_baselines` | initiative_id -> initiatives |
| `baseline_approvals` | (initiative_id, baseline_version) -> process_baselines |
| `initiatives` | (initiative_id, baseline_version) -> baseline_approvals (deferred, checked at commit) |
| `assumption_versions` | initiative_id -> initiatives |
| `opportunity_scores` | initiative_id -> initiatives |
| `scenario_versions` | rate_conversion_assumption_id -> assumption_versions |
| `scenario_initiatives` | scenario_id -> scenario_versions |
| `scenario_initiatives` | initiative_id -> initiatives |
| `scenario_pins` | scenario_id -> scenario_versions |
| `scenario_pins` | assumption_id -> assumption_versions |
| `cost_items` | initiative_id -> initiatives |
| `expanded_costs` | scenario_id -> scenario_versions |
| `expanded_costs` | cost_id -> cost_items |
| `expanded_costs` | initiative_id -> initiatives |
| `benefit_items` | initiative_id -> initiatives |
| `dependencies` | initiative_id -> initiatives |
| `dependencies` | prerequisite_id -> initiatives |
| `impact_mappings` | initiative_id -> initiatives |
| `impact_mappings` | group_id -> stakeholder_groups |
| `resource_allocations` | resource_id -> resources |
| `resource_allocations` | initiative_id -> initiatives |
| `readiness_assessments` | group_id -> stakeholder_groups |
| `adoption_observations` | initiative_id -> initiatives |
| `training_completions` | initiative_id -> initiatives |
| `benefit_observations` | benefit_id -> benefit_items |
| `risk_items` | initiative_id -> initiatives |
| `forecast_versions` | initiative_id -> initiatives |

Keys: every entity has a text primary key (`initiative_id`, `scenario_id`, `cost_id`, ...); composite unique keys: `process_baselines` (initiative_id, baseline_version), `assumption_versions` (initiative_id, name, version_number), `forecast_versions` (initiative_id, version_number, period_index).

## 4. Source-to-target mapping
| Source (published JSON, `web/public/data`) | Target table | Loader | Analysis use (temporary tables of `00_portfolio_model.sql`) | Workbook sheet | BI file |
|---|---|---|---|---|---|
| `manifest.json` `config` | `dataset_config` | `data/seed.py` | `cw_p` (period basis, period start, as-of, matured periods) | `Controls`, `Periods` | `dim_period.csv` |
| `initiatives.json` | `initiatives` (+ `baseline_approvals`) | `data/seed.py` | `cw_roadmap`, `cw_cap`, `cw_var` | `Initiatives` | `dim_initiative.csv` |
| `scenario_versions.json` | `scenario_versions`, `scenario_initiatives`, `scenario_pins` | `data/seed.py` | `cw_scn`, `cw_si`, `cw_pick` | `Scenarios` | `dim_scenario.csv` |
| `assumption_versions.json` | `assumption_versions` | `data/seed.py` | `cw_pick`, `cw_model` (ramp, conversion rate, target minutes) | `Scenario inputs` (typed) | via `dim_scenario.period_rate` |
| `cost_items.json` | `cost_items` | `data/seed.py` | `cw_cost` (expanded over half-open ranges) | `Costs` | `fact_cash_flow.csv`, `fact_scenario_initiative.csv` |
| `benefit_items.json` | `benefit_items` | `data/seed.py` | `cw_ben` (class, ramped amount, money), `cw_claim`, `cw_hours` | `Benefits` | `fact_cash_flow.csv`, `fact_double_count.csv` |
| `benefit_observations.json` | `benefit_observations` | `data/seed.py` | `cw_obs`, `cw_real` | (not in the workbook) | `fact_realisation.csv` |
| `adoption_observations.json`, `training_completions.json` | `adoption_observations`, `training_completions` | `data/seed.py` | `cw_adopt`, `cw_train` | (not in the workbook) | `fact_adoption.csv` |
| `dependencies.json` | `dependencies` | `data/seed.py` | `cw_roadmap` | (not in the workbook) | `dim_initiative.csv` |
| `resources.json`, `resource_allocations.json` | `resources`, `resource_allocations` | `data/seed.py` | investigation 09 | (not in the workbook) | `dim_resource.csv`, `fact_resource.csv` |
| `forecast_versions.json` | `forecast_versions` | `data/seed.py` | investigation 08 | (not in the workbook) | `fact_forecast.csv` |
| `risk_items.json` | `risk_items` | `data/seed.py` | investigation 11 | (not in the workbook) | `fact_risk.csv` |
| `process_baselines.json` | `process_baselines` | `data/seed.py` | `cw_cap` | (not in the workbook) | (not exported) |
| `stakeholder_groups.json`, `readiness_assessments.json`, `impact_mappings.json` | the same tables | `data/seed.py` | (reference SQL and domain only) | (not in the workbook) | (not exported) |

## 5. Units, formats and absence
Money is USD in `NUMERIC(20,6)` (JSON shows 2 places); `benefit_items.amount` is USD except for `benefit_type` `capacity`, whose amount is **hours** per period. Proportions are `NUMERIC(7,6)` in [0, 1]. Instants are `TIMESTAMPTZ` in UTC; periods are integer `period_index` from 0 (monthly from 2026-01-01 in the snapshot; annual from 2026 in the golden fixture); ranges are half-open `[from, to)`. Null means unknown, no approved baseline or a zero denominator, never 0 (D-04). `recorded_at` / `entered_at` (0003_review9.sql) are server instants; no row of the published world carries one, so every row belongs to every scenario created after the world was loaded (R9-01).

