# Onboard Studio data layer

* `migrations/0001_schema.sql` tables for every entity (TIMESTAMPTZ everywhere, `business_minutes` NUMERIC) plus
  `workflow_requirements` (D-05's required document types, until now a block), `document_reviews`, and the operational
  tables `raw_batches`, `rejected_records`, `quarantined_records`, `audit_events`, `command_results`,
  `dataset_versions`. `calendar_intervals.kind` is `working` (default) or `holiday`. `cases.linked_case_id` links a
  correction to the completed case it corrects; `cases.version` is the command concurrency counter.
* `migrations/0002_constraints.sql` CHECKs and triggers: `document_versions`, `document_reviews` and `audit_events`
  are append-only; a `workflow_versions` row is immutable once `published_at` is set (and so are its steps,
  dependencies and required document types); a completed case cannot be reopened or re-dated;
  `approvals UNIQUE (step_instance_id, version_number)` is the `DECISION_CONFLICT` guard; open assignments have
  `ended_at IS NULL`.
* `migrate.py [--reset]` applies the files in order, records checksums in `schema_migrations`, refuses a changed file.
* `seed.py <inputs.json>` loads a fixture through the domain's `validate_batch`: workflow versions go in as drafts, get
  their steps, dependencies and requirements, and are published last (the one change the immutability trigger allows).
  Rejected rows are kept in `rejected_records` under one `raw_batches` row. Running it twice inserts nothing.
* `sql/reference_metrics.sql` recomputes calendar, business, paused, paused-business and active hours of the
  completed cases with plain interval-overlap arithmetic over `calendar_intervals` (no `generate_series`, no shared code
  with the domain). Pause eligibility comes from `sla_rules.pause_policy`. Assumes non-overlapping working intervals,
  non-overlapping holidays and non-overlapping eligible waiting intervals per case.
