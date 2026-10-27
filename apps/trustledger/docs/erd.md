# Entity-relationship diagram (P07-ART-03)

Dataset `tl-20261026-20261026` (generator hash `a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff`), contract v1, code revision `0b5d686`. **Synthetic data only.** The diagram is the physical model of `data/migrations/0001_schema.sql`, `0002_constraints.sql` and `0003_review_r7.sql` plus `verification_truth` (`data/sql/verification_truth.sql`, loaded only by a test or reviewer) and `schema_migrations` (created by `data/migrate.py`): 26 tables. Cardinalities are the foreign keys of `data-dictionary.md` section 3. Read the text lists below the diagram if your viewer does not render Mermaid.

```mermaid
erDiagram
    owners ||--o{ datasets : "accountable owner"
    datasets ||--o{ fields : "has"
    datasets ||--o{ dataset_rows : "measured rows"
    datasets ||--o{ quality_rules : "measured by"
    fields |o--o{ quality_rules : "target of"
    quality_rules ||--o{ quality_rule_versions : "versions"
    quality_rules ||--o{ rule_runs : "runs"
    rule_weight_versions ||--o{ rule_runs : "in force at run"
    rule_runs ||--o| issues : "opens (failing scheduled run)"
    rule_runs |o--o{ issues : "verifies (passing rerun)"
    owners ||--o{ issues : "owns"
    issues ||--o{ issue_events : "lifecycle"
    datasets ||--o{ lineage_edges : "source"
    datasets ||--o{ lineage_edges : "target"
    metric_versions ||--o| definition_changes : "created by"
    metric_versions |o--o{ definition_changes : "replaced by"
    customer_records ||--o{ match_candidates : "left"
    customer_records ||--o{ match_candidates : "right"
    match_candidates ||--o{ merge_decisions : "decided"
    merge_decisions |o--o| merge_decisions : "reverses"
    datasets ||--o{ dataset_refreshes : "refreshes"
    customer_records ||--o| verification_truth : "true entity (verification only)"

    tl_timezones {
        text name PK
    }
    owners {
        text owner_id PK
        text owner_name
        text team
        text role
        boolean active
        timestamptz deactivated_at
    }
    datasets {
        text dataset_id PK
        text dataset_name
        text source_system
        text owner_id FK
        text classification
        timestamptz registered_at
        boolean monitored
        text refresh_timezone
        text refresh_local_time
        int refresh_grace_minutes
        timestamptz last_refreshed_at
        text registered_by
    }
    fields {
        text field_id PK
        text dataset_id FK
        text field_name
        text data_type
        boolean nullable
    }
    dataset_rows {
        text dataset_id PK,FK
        int ordinal PK
        text row_id
        jsonb data
        int row_version
        text supersedes_row_id
        text reason
        text corrected_by
        timestamptz recorded_at
    }
    quality_rules {
        text rule_id PK
        text dataset_id FK
        text field_id FK
        text rule_type
        text severity
        int version_number
        text status
        timestamptz disabled_at
        text disabled_reason
        jsonb definition
    }
    quality_rule_versions {
        text rule_id PK,FK
        int version_number PK
        text rule_type
        text severity
        jsonb definition
        timestamptz valid_from
    }
    rule_weight_versions {
        text weight_version PK
        timestamptz valid_from
        jsonb weights
    }
    checklist_versions {
        text checklist_version PK
        jsonb items
    }
    ledger_config {
        int id PK
        jsonb whitespace_policy
        text checklist_version
        jsonb probes
    }
    rule_runs {
        text rule_run_id PK
        text rule_id FK
        int rule_version
        text weight_version FK
        text kind
        timestamptz run_at
        int eligible_count
        int failure_count
        text rerun_for_issue
        jsonb details
        text run_by
    }
    issues {
        text issue_id PK
        text rule_run_id FK
        text severity
        text owner_id FK
        text status
        timestamptz detected_at
        timestamptz due_at
        timestamptz closed_at
        text verification_run_id FK
        timestamptz_array reopened_at
        jsonb record_ids
        int version
    }
    issue_events {
        text event_id PK
        text issue_id FK
        text event_type
        timestamptz occurred_at
        text actor_id
        jsonb details
    }
    lineage_edges {
        text edge_id PK
        text source_dataset_id FK
        text target_dataset_id FK
        text evidence_type
        timestamptz observed_at
    }
    metric_versions {
        text metric_version_id PK
        text metric_id
        text metric_name
        int version_number
        text definition
        text grain
        jsonb source_fields
        text owner_id
        text refresh
        timestamptz valid_from
        text status
        text published_by
    }
    definition_changes {
        text change_id PK
        text metric_version_id FK
        text previous_metric_version_id FK
        text reason
        text approved_by
        timestamptz changed_at
    }
    customer_records {
        text record_id PK
        text source_system
        text source_customer_id
        text normalized_name
        text address_key
    }
    match_candidates {
        text candidate_id PK
        text left_record_id FK
        text right_record_id FK
        numeric score
        jsonb features
        text explanation
        text uncertainty
        text proposed_by
        timestamptz proposed_at
    }
    merge_decisions {
        text merge_id PK
        text candidate_id FK
        text reviewer_id
        text decision
        timestamptz decided_at
        text reverses_merge_id FK
        text reason
    }
    dataset_refreshes {
        text dataset_id PK,FK
        timestamptz refreshed_at PK
        timestamptz recorded_at
        text recorded_by
    }
    rejected_records {
        text batch_id PK
        text entity PK
        text id PK
        text reason_code PK
        jsonb raw_row
        int ordinal PK
        timestamptz created_at
    }
    audit_events {
        text event_id PK
        text entity_type
        text entity_id
        text action
        text actor_id
        text actor_role
        timestamptz occurred_at
        int before_version
        int after_version
        text reason
        text request_id
        jsonb details
    }
    command_results {
        text idempotency_key PK
        text payload_hash
        text actor_id
        text actor_role
        text command_id
        text status
        jsonb result
        timestamptz created_at
    }
    dataset_versions {
        text dataset_version PK
        text dataset_hash
        text contract_version
        timestamptz as_of
        timestamptz created_at
    }
    verification_truth {
        text record_id PK
        text true_entity
    }
    schema_migrations {
        text version PK
        text checksum
        timestamptz applied_at
    }
```

## Field lists
Each table's columns are in `data-dictionary.md` section 2 with type, nullability and meaning. The grouping below is the reading order for the decision (P07-GOAL-01: which data issues should be fixed first and who is accountable?):

* **Who is accountable:** `owners` -> `datasets` (the accountable owner), `issues.owner_id`.
* **What is measured:** `datasets` -> `fields`, `dataset_rows`, `quality_rules` (+ `quality_rule_versions`), `rule_weight_versions`, `checklist_versions`, `ledger_config`.
* **What failed and what happened next:** `rule_runs` -> `issues` -> `issue_events`; the verification of an issue is a second link from `issues` to `rule_runs`.
* **Where data comes from:** `lineage_edges` (declared, observed, inferred), `metric_versions` -> `definition_changes`.
* **Who is the same person:** `customer_records` -> `match_candidates` -> `merge_decisions` (approve, reject, reverse); `verification_truth` stands outside it.
* **What the system did:** `rejected_records`, `audit_events`, `command_results`, `dataset_versions`, `dataset_refreshes`, `schema_migrations`.

## Logical joins (not enforced by the database)
* `rule_runs.rerun_for_issue` -> `issues.issue_id`: a rerun re-checks one issue; `issues_guard` accepts a verification only if that rerun is of the same rule and version, passes, and is not before the detection or the latest reopen.
* `quality_rules.definition.parent_dataset_id` -> `datasets`: the parent of a relationship rule.
* `match_candidates.proposed_by` and `merge_decisions.reviewer_id` -> `owners.owner_id`: separation of duties.
* `metric_versions.owner_id` and `definition_changes.approved_by` -> `owners.owner_id`: not a foreign key, so a definition can name an owner that does not exist (the checklist then fails on `owner`; investigation 06 finds one).
* `verification_truth.record_id` -> `customer_records.record_id`: the synthetic truth for match precision.

## Reading the diagram for the decision
An issue is a row of `issues` joined to the failing run (`rule_runs`), its rule (`quality_rules`), the dataset and its accountable owner; "resolved" additionally needs the verification run, so a claim (a closed issue with no passing rerun of the same rule version) is visible as an issue whose `verification_run_id` does not satisfy the guard. Ownership coverage is `datasets` joined to `owners` on the active flag at the as-of; lineage coverage is `lineage_edges` self-joined on (source, target) across evidence kinds; definition coverage is the effective published `metric_versions` row tested against the checklist; match precision joins `merge_decisions` to `match_candidates` to `verification_truth` twice (left and right record). See `sql-analysis.md` for each as a numbered investigation.
