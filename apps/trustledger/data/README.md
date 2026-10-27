# TrustLedger data layer

* `python data/migrate.py [--reset]` applies `migrations/*.sql` in order (idempotent; each applied file's hash is recorded and a changed applied file is
  refused; `--reset` drops only this project's tables and functions). `python data/seed.py tests/fixtures/golden/inputs.json [--dataset-version NAME]`
  loads a fixture through the domain's `validate_batch` (rejected records go to `rejected_records` with the raw row and reason code and are not loaded),
  loads the weight versions, checklist versions and configuration, and records a `dataset_versions` row (`ds-<hash>` by default, or the name given; the hash is
  the sha256 of the canonical JSON of the inputs WITHOUT `synthetic_truth`). Loading twice changes nothing. A directory with one `<entity>.json` per entity, a
  `dataset_rows.json` and a `config.json` loads too. **The seeder never loads the synthetic truth.**
* **Schema** (`0001`): the twelve entities `owners`, `datasets`, `fields`, `quality_rules`, `rule_runs`, `issues`, `lineage_edges`, `metric_versions`,
  `definition_changes`, `customer_records`, `match_candidates`, `merge_decisions`; plus `dataset_rows` (the measured rows, one JSON object each),
  `rule_weight_versions`, `checklist_versions`, `ledger_config`, `issue_events`, `rejected_records`, `audit_events`, `command_results` (actor-bound
  idempotency), `dataset_versions` and `tl_timezones` (a copy of the server's IANA names). Instants are `TIMESTAMPTZ`; the only numeric column is
  `match_candidates.score NUMERIC(7,6)`; proportions are never stored.
* **Constraints** (`0002`): append-only (UPDATE, DELETE and TRUNCATE refused by trigger) for `dataset_rows`, `rule_runs`, `rule_weight_versions`,
  `checklist_versions`, `metric_versions`, `definition_changes`, `customer_records`, `match_candidates`, `merge_decisions`, `lineage_edges`, `issue_events`,
  `audit_events`, `rejected_records`, `command_results`, so a weight change, a definition rewrite and a run edit are refused by the database;
  `quality_rules` change only active to disabled, once, with a reason and a date; `issues` keep `detected_at`, the run and the severity, only add reopen cycles, and
  accept a verification run only if it is a successful rerun of the same rule and rule version for that issue; `match_candidates` are unique per pair and
  canonical (`left < right` in code-point order); `merge_decisions` refuse a reviewer who proposed the candidate, a second approve/reject of a candidate (also under
  a race), a reversal of anything but an approval of the same candidate and a second reversal; datasets need an owner, a classification and a valid schedule; weight
  versions need the five dimensions summing to 1. Helper functions `tl_cell` (the exact text of a cell) and `tl_iso` (an instant as published) are used by the
  SQL reference.
* **`sql/reference_metrics.sql`** recomputes every metric key of `expected.json` (and `empty_population`) from the FACTS in one statement, with no stored
  result (`%(as_of)s`, `%(wv)s`). NUMERIC throughout, rounded once. Match precision reads the verification layer's table `verification_truth`
  (`sql/verification_truth.sql`), which exists only where a test (or a reviewer) creates and fills it; the file requires the table. Known limits: it uses PostgreSQL
  regular expressions (`~`), so validity patterns must be in the subset common with Python `re`; IANA zone rules come from the server's tz database.
* `tests/test_sql_reference.py` checks the SQL against the three fixtures key by key, the domain on the golden population at other times, on 160 seeded random
  populations (`tests/worlds.py`: every rule type, filters, whitespace, null keys, clock-change days, inactive owners, issues in every state, reopens, lineage of
  all three evidence types, versioned definitions, reversals, a partial truth) and on every half hour of six clock-change days; it also shows that scrambling the stored
  results changes nothing.
