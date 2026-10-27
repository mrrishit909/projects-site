-- TrustLedger constraints, helper functions and triggers (idempotent).
--
-- * Append-only (nothing is edited or deleted): dataset_rows, rule_runs, rule_weight_versions, checklist_versions, metric_versions,
--   definition_changes, customer_records, match_candidates, merge_decisions, lineage_edges, issue_events, audit_events,
--   rejected_records, command_results. A weight change, a definition rewrite and a run edit are therefore refused by the database.
-- * quality_rules: only active -> disabled (once, with a reason and a date); the identity of a rule never changes.
-- * issues: detected_at, rule_run_id and severity never change; reopened_at only grows; a verification run must be a successful
--   rerun of the same rule and rule version for that issue (the database refuses "resolved" without it).
-- * merge_decisions: the reviewer is never the proposer; one approve/reject per candidate; a reversal names an approval of the same
--   candidate, once, with a reason. match_candidates: left < right (code-point order) and unique per pair.
-- * tl_cell / tl_iso are helpers also used by data/sql/reference_metrics.sql.

CREATE OR REPLACE FUNCTION tl_valid_tz(tz TEXT) RETURNS BOOLEAN AS $$
    SELECT EXISTS (SELECT 1 FROM tl_timezones WHERE name = tz)
$$ LANGUAGE sql STABLE;

-- The exact text of a cell: text as is, true/false, numbers as written, null/absent as NULL.
CREATE OR REPLACE FUNCTION tl_cell(j JSONB) RETURNS TEXT AS $$
    SELECT CASE jsonb_typeof(j) WHEN 'string' THEN j #>> '{}' WHEN 'null' THEN NULL ELSE j::text END
$$ LANGUAGE sql IMMUTABLE;

-- UTC instants as published: YYYY-MM-DDTHH:MM:SS[.ffffff]Z
CREATE OR REPLACE FUNCTION tl_iso(t TIMESTAMPTZ) RETURNS TEXT AS $$
    SELECT CASE WHEN t IS NULL THEN NULL ELSE
        to_char(t AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
        || CASE WHEN extract(microseconds FROM t) % 1000000 <> 0 THEN '.' || to_char(t AT TIME ZONE 'UTC', 'US') ELSE '' END || 'Z' END
$$ LANGUAGE sql IMMUTABLE;

-- A weight version names exactly the five dimensions, each a number in [0, 1], summing to 1.
CREATE OR REPLACE FUNCTION tl_valid_weights(w JSONB) RETURNS BOOLEAN AS $$
    SELECT jsonb_typeof(w) = 'object'
       AND (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(w) k) = ARRAY['completeness','relationship','timeliness','uniqueness','validity']
       AND NOT EXISTS (SELECT 1 FROM jsonb_each(w) e WHERE jsonb_typeof(e.value) <> 'string' OR e.value #>> '{}' !~ '^[0-9]+(\.[0-9]+)?$'
                       OR (e.value #>> '{}')::numeric > 1)
       AND (SELECT sum((e.value #>> '{}')::numeric) FROM jsonb_each(w) e) = 1
$$ LANGUAGE sql IMMUTABLE;

DO $$
DECLARE c record;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('owners_role_ck',        'owners',            $c$CHECK (role IN ('analyst', 'steward', 'admin') AND length(btrim(owner_name)) > 0)$c$),
        ('owners_inactive_ck',    'owners',            'CHECK (active OR deactivated_at IS NOT NULL)'),
        ('datasets_class_ck',     'datasets',          'CHECK (length(btrim(classification)) > 0 AND length(btrim(owner_id)) > 0)'),
        ('datasets_schedule_ck',  'datasets',          $c$CHECK ((NOT monitored OR (refresh_timezone IS NOT NULL AND refresh_local_time IS NOT NULL AND refresh_grace_minutes IS NOT NULL))
                                                          AND (refresh_timezone IS NULL OR tl_valid_tz(refresh_timezone))
                                                          AND (refresh_local_time IS NULL OR refresh_local_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
                                                          AND (refresh_grace_minutes IS NULL OR refresh_grace_minutes BETWEEN 0 AND 1439))$c$),
        ('dataset_rows_row_uq',   'dataset_rows',      'UNIQUE (dataset_id, row_id)'),
        ('dataset_rows_obj_ck',   'dataset_rows',      $c$CHECK (jsonb_typeof(data) = 'object' AND length(row_id) > 0)$c$),
        ('rules_type_ck',         'quality_rules',     $c$CHECK (rule_type IN ('completeness', 'validity', 'uniqueness', 'relationship', 'timeliness')
                                                          AND severity IN ('low', 'medium', 'high', 'critical') AND version_number >= 1)$c$),
        ('rules_status_ck',       'quality_rules',     $c$CHECK (status IN ('active', 'disabled')
                                                          AND ((status = 'disabled') = (disabled_at IS NOT NULL))
                                                          AND (status = 'active' OR length(btrim(coalesce(disabled_reason, ''))) > 0))$c$),
        ('weights_valid_ck',      'rule_weight_versions', 'CHECK (tl_valid_weights(weights))'),
        ('runs_kind_ck',          'rule_runs',         $c$CHECK (kind IN ('scheduled', 'rerun') AND (kind = 'rerun') = (rerun_for_issue IS NOT NULL))$c$),
        ('runs_counts_ck',        'rule_runs',         'CHECK (eligible_count >= 0 AND failure_count >= 0 AND failure_count <= eligible_count AND rule_version >= 1)'),
        ('issues_status_ck',      'issues',            $c$CHECK (status IN ('open', 'investigating', 'closed') AND severity IN ('low', 'medium', 'high', 'critical')
                                                          AND (status <> 'closed' OR closed_at IS NOT NULL))$c$),
        ('issues_run_uq',         'issues',            'UNIQUE (rule_run_id)'),
        ('issue_events_type_ck',  'issue_events',      $c$CHECK (event_type IN ('detected', 'triaged', 'claimed', 'verified', 'verification_failed', 'reopened'))$c$),
        ('edges_evidence_ck',     'lineage_edges',     $c$CHECK (evidence_type IN ('declared', 'observed', 'inferred') AND source_dataset_id <> target_dataset_id
                                                          AND ((evidence_type = 'observed') = (observed_at IS NOT NULL)))$c$),
        ('metric_versions_uq',    'metric_versions',   'UNIQUE (metric_id, version_number)'),
        ('metric_versions_ck',    'metric_versions',   $c$CHECK (status IN ('draft', 'published', 'superseded') AND version_number >= 1)$c$),
        ('changes_version_uq',    'definition_changes','UNIQUE (metric_version_id)'),
        ('changes_reason_ck',     'definition_changes','CHECK (length(btrim(reason)) > 0)'),
        ('candidates_canonical_ck','match_candidates', $c$CHECK (left_record_id COLLATE "C" < right_record_id COLLATE "C")$c$),
        ('candidates_pair_uq',    'match_candidates',  'UNIQUE (left_record_id, right_record_id)'),
        ('candidates_score_ck',   'match_candidates',  $c$CHECK (score BETWEEN 0 AND 1 AND jsonb_typeof(features) = 'object' AND features <> '{}'::jsonb
                                                          AND length(btrim(explanation)) > 0)$c$),
        ('decisions_kind_ck',     'merge_decisions',   $c$CHECK (decision IN ('approve', 'reject', 'reverse')
                                                          AND ((decision = 'reverse') = (reverses_merge_id IS NOT NULL))
                                                          AND (decision <> 'reverse' OR length(btrim(coalesce(reason, ''))) > 0))$c$),
        ('decisions_reversal_uq', 'merge_decisions',   'UNIQUE (reverses_merge_id)'),
        ('command_results_role_ck','command_results',  $c$CHECK (actor_role IN ('analyst', 'steward', 'admin'))$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

-- One approve/reject per candidate (a second concurrent approval of one candidate is refused by the database as well).
CREATE UNIQUE INDEX IF NOT EXISTS merge_decisions_review_uq ON merge_decisions (candidate_id) WHERE decision IN ('approve', 'reject');

CREATE OR REPLACE FUNCTION tl_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION tl_rule_guard() RETURNS trigger AS $$
BEGIN
    IF (NEW.rule_id, NEW.dataset_id, NEW.field_id, NEW.rule_type, NEW.severity, NEW.version_number, NEW.definition)
       IS DISTINCT FROM (OLD.rule_id, OLD.dataset_id, OLD.field_id, OLD.rule_type, OLD.severity, OLD.version_number, OLD.definition) THEN
        RAISE EXCEPTION 'RULE_IMMUTABLE: a rule''s identity and definition never change in place; its history is kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'disabled' AND (NEW.status, NEW.disabled_at, NEW.disabled_reason) IS DISTINCT FROM (OLD.status, OLD.disabled_at, OLD.disabled_reason) THEN
        RAISE EXCEPTION 'RULE_DISABLED_IS_FINAL: a disabled rule keeps its reason and date' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION tl_rule_no_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'quality_rules is append-only for rows: DELETE is not allowed (disable the rule instead)' USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

-- Resolved needs a successful rerun of the same rule version (D-03, P07-TEST-09).
CREATE OR REPLACE FUNCTION tl_issue_guard() RETURNS trigger AS $$
DECLARE base rule_runs; ver rule_runs;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.issue_id, NEW.rule_run_id, NEW.severity, NEW.detected_at) IS DISTINCT FROM (OLD.issue_id, OLD.rule_run_id, OLD.severity, OLD.detected_at) THEN
            RAISE EXCEPTION 'ISSUE_IMMUTABLE: detected_at, the run and the severity of an issue never change' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF cardinality(NEW.reopened_at) < cardinality(OLD.reopened_at)
           OR NEW.reopened_at[1:cardinality(OLD.reopened_at)] IS DISTINCT FROM OLD.reopened_at THEN
            RAISE EXCEPTION 'REOPEN_HISTORY: reopen cycles are only ever added' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        -- a verification run is replaced only after a reopen, by a later successful rerun
        IF OLD.verification_run_id IS NOT NULL AND NEW.verification_run_id IS DISTINCT FROM OLD.verification_run_id
           AND (NEW.verification_run_id IS NULL OR cardinality(NEW.reopened_at) = 0
                OR (SELECT run_at FROM rule_runs WHERE rule_run_id = NEW.verification_run_id) < NEW.reopened_at[cardinality(NEW.reopened_at)]) THEN
            RAISE EXCEPTION 'VERIFICATION_IMMUTABLE: a verification run is replaced only after a reopen, by a later rerun' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    IF NEW.verification_run_id IS NOT NULL AND (TG_OP = 'INSERT' OR NEW.verification_run_id IS DISTINCT FROM OLD.verification_run_id) THEN
        SELECT * INTO base FROM rule_runs WHERE rule_run_id = NEW.rule_run_id;
        SELECT * INTO ver FROM rule_runs WHERE rule_run_id = NEW.verification_run_id;
        IF ver.kind IS DISTINCT FROM 'rerun' OR ver.rerun_for_issue IS DISTINCT FROM NEW.issue_id OR ver.rule_id IS DISTINCT FROM base.rule_id
           OR ver.rule_version IS DISTINCT FROM base.rule_version OR ver.failure_count <> 0 OR ver.run_at < NEW.detected_at THEN
            RAISE EXCEPTION 'VERIFICATION_RUN_INVALID: an issue is resolved only by a successful rerun of the same rule version' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION tl_decision_guard() RETURNS trigger AS $$
DECLARE cand match_candidates; tgt merge_decisions;
BEGIN
    SELECT * INTO cand FROM match_candidates WHERE candidate_id = NEW.candidate_id;
    IF cand.proposed_by = NEW.reviewer_id THEN
        RAISE EXCEPTION 'REVIEWER_IS_PROPOSER: % proposed candidate % and cannot decide it', NEW.reviewer_id, NEW.candidate_id USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.decision = 'reverse' THEN
        SELECT * INTO tgt FROM merge_decisions WHERE merge_id = NEW.reverses_merge_id;
        IF tgt.decision IS DISTINCT FROM 'approve' OR tgt.candidate_id IS DISTINCT FROM NEW.candidate_id THEN
            RAISE EXCEPTION 'INVALID_REVERSAL: only an approval of the same candidate can be reversed' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['dataset_rows', 'rule_runs', 'rule_weight_versions', 'checklist_versions', 'metric_versions', 'definition_changes',
                             'customer_records', 'match_candidates', 'merge_decisions', 'lineage_edges', 'issue_events', 'audit_events',
                             'rejected_records', 'command_results']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_immutable') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION tl_forbid_mutation()', t || '_immutable', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION tl_forbid_mutation()', t || '_no_truncate', t);
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'quality_rules_guard') THEN
        CREATE TRIGGER quality_rules_guard BEFORE UPDATE ON quality_rules FOR EACH ROW EXECUTE FUNCTION tl_rule_guard();
        CREATE TRIGGER quality_rules_no_delete BEFORE DELETE ON quality_rules FOR EACH ROW EXECUTE FUNCTION tl_rule_no_delete();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'issues_guard') THEN
        CREATE TRIGGER issues_guard BEFORE INSERT OR UPDATE ON issues FOR EACH ROW EXECUTE FUNCTION tl_issue_guard();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'merge_decisions_guard') THEN
        CREATE TRIGGER merge_decisions_guard BEFORE INSERT ON merge_decisions FOR EACH ROW EXECUTE FUNCTION tl_decision_guard();
    END IF;
END
$$;
