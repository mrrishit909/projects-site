-- Onboard Studio constraints, triggers and indexes (idempotent).

DO $$
DECLARE c record;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('workflow_versions_number_ck',  'workflow_versions',  'CHECK (version_number >= 1)'),
        ('workflow_versions_hash_ck',    'workflow_versions',  'CHECK (published_at IS NULL OR definition_hash IS NOT NULL)'),
        ('step_definitions_seq_ck',      'step_definitions',   'CHECK (sequence >= 0)'),
        ('dependencies_type_ck',         'dependencies',       $c$CHECK (dependency_type IN ('mandatory', 'optional'))$c$),
        ('dependencies_self_ck',         'dependencies',       'CHECK (step_definition_id <> prerequisite_id)'),
        ('sla_rules_minutes_ck',         'sla_rules',          'CHECK (business_minutes > 0)'),
        ('calendar_intervals_range_ck',  'calendar_intervals', 'CHECK (ends_at > starts_at)'),
        ('calendar_intervals_kind_ck',   'calendar_intervals', $c$CHECK (kind IN ('working', 'holiday'))$c$),
        ('cases_status_ck',              'cases',              $c$CHECK (status IN ('open', 'completed'))$c$),
        ('cases_completion_ck',          'cases',              $c$CHECK ((status = 'completed') = (completed_at IS NOT NULL))$c$),
        ('cases_range_ck',               'cases',              'CHECK (completed_at IS NULL OR completed_at >= opened_at)'),
        ('step_instances_status_ck',     'step_instances',     $c$CHECK (status IN ('blocked', 'ready', 'in_progress', 'in_review', 'approved', 'changes_requested'))$c$),
        ('step_instances_version_ck',    'step_instances',     'CHECK (version_number >= 1)'),
        ('assignments_range_ck',         'assignments',        'CHECK (ended_at IS NULL OR ended_at >= assigned_at)'),
        ('document_versions_status_ck',  'document_versions',  $c$CHECK (review_status IN ('submitted', 'accepted', 'rejected'))$c$),
        ('document_versions_version_ck', 'document_versions',  'CHECK (version_number >= 1)'),
        ('document_reviews_decision_ck', 'document_reviews',   $c$CHECK (decision IN ('accepted', 'rejected'))$c$),
        ('approvals_version_ck',         'approvals',          'CHECK (version_number >= 1)'),
        ('approvals_decision_ck',        'approvals',          $c$CHECK (decision IN ('approved', 'rejected', 'changes_requested'))$c$),
        ('waiting_intervals_range_ck',   'waiting_intervals',  'CHECK (ends_at IS NULL OR ends_at >= starts_at)'),
        ('raw_batches_status_ck',        'raw_batches',        $c$CHECK (status IN ('accepted', 'partial'))$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

-- Append-only tables: an audit event, a document version and a document review are never edited (P02-TEST-06).
CREATE OR REPLACE FUNCTION os_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS document_versions_append_only ON document_versions;
CREATE TRIGGER document_versions_append_only BEFORE UPDATE OR DELETE ON document_versions
    FOR EACH ROW EXECUTE FUNCTION os_forbid_mutation();
DROP TRIGGER IF EXISTS document_reviews_append_only ON document_reviews;
CREATE TRIGGER document_reviews_append_only BEFORE UPDATE OR DELETE ON document_reviews
    FOR EACH ROW EXECUTE FUNCTION os_forbid_mutation();
DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION os_forbid_mutation();

-- D-02: a workflow version is immutable once published_at is set (publishing itself is the NULL -> value update).
CREATE OR REPLACE FUNCTION os_workflow_version_immutable() RETURNS trigger AS $$
BEGIN
    IF OLD.published_at IS NOT NULL THEN
        RAISE EXCEPTION 'workflow version % is published and immutable', OLD.workflow_version_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS workflow_versions_immutable ON workflow_versions;
CREATE TRIGGER workflow_versions_immutable BEFORE UPDATE OR DELETE ON workflow_versions
    FOR EACH ROW EXECUTE FUNCTION os_workflow_version_immutable();

-- The steps and dependencies of a published version are immutable too.
CREATE OR REPLACE FUNCTION os_definition_immutable() RETURNS trigger AS $$
DECLARE wv TEXT; pub TIMESTAMPTZ;
BEGIN
    IF TG_TABLE_NAME = 'step_definitions' THEN
        wv := CASE WHEN TG_OP = 'INSERT' THEN NEW.workflow_version_id ELSE OLD.workflow_version_id END;
    ELSIF TG_TABLE_NAME = 'workflow_requirements' THEN
        wv := CASE WHEN TG_OP = 'INSERT' THEN NEW.workflow_version_id ELSE OLD.workflow_version_id END;
    ELSE
        SELECT workflow_version_id INTO wv FROM step_definitions
         WHERE step_definition_id = CASE WHEN TG_OP = 'INSERT' THEN NEW.step_definition_id ELSE OLD.step_definition_id END;
    END IF;
    SELECT published_at INTO pub FROM workflow_versions WHERE workflow_version_id = wv;
    IF pub IS NOT NULL THEN
        RAISE EXCEPTION 'workflow version % is published and immutable', wv
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS step_definitions_immutable ON step_definitions;
CREATE TRIGGER step_definitions_immutable BEFORE INSERT OR UPDATE OR DELETE ON step_definitions
    FOR EACH ROW EXECUTE FUNCTION os_definition_immutable();
DROP TRIGGER IF EXISTS dependencies_immutable ON dependencies;
CREATE TRIGGER dependencies_immutable BEFORE INSERT OR UPDATE OR DELETE ON dependencies
    FOR EACH ROW EXECUTE FUNCTION os_definition_immutable();
DROP TRIGGER IF EXISTS workflow_requirements_immutable ON workflow_requirements;
CREATE TRIGGER workflow_requirements_immutable BEFORE INSERT OR UPDATE OR DELETE ON workflow_requirements
    FOR EACH ROW EXECUTE FUNCTION os_definition_immutable();

-- D-03 / P02-TEST-11: a completed case cannot be reopened or re-dated; a correction opens a linked new case.
CREATE OR REPLACE FUNCTION os_case_no_reopen() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'completed' AND (NEW.status <> OLD.status OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
                                     OR NEW.workflow_version_id <> OLD.workflow_version_id) THEN
        RAISE EXCEPTION 'case % is completed and cannot be reopened', OLD.case_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.workflow_version_id <> OLD.workflow_version_id THEN
        RAISE EXCEPTION 'case % keeps its workflow version', OLD.case_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cases_no_reopen ON cases;
CREATE TRIGGER cases_no_reopen BEFORE UPDATE ON cases
    FOR EACH ROW EXECUTE FUNCTION os_case_no_reopen();

CREATE INDEX IF NOT EXISTS cases_opened_idx ON cases (opened_at);
CREATE INDEX IF NOT EXISTS cases_org_idx ON cases (organization_id);
CREATE INDEX IF NOT EXISTS step_instances_case_idx ON step_instances (case_id);
CREATE INDEX IF NOT EXISTS assignments_step_idx ON assignments (step_instance_id);
CREATE INDEX IF NOT EXISTS document_versions_case_idx ON document_versions (case_id, document_type);
CREATE INDEX IF NOT EXISTS waiting_intervals_case_idx ON waiting_intervals (case_id);
CREATE INDEX IF NOT EXISTS case_events_case_idx ON case_events (case_id, occurred_at);
CREATE INDEX IF NOT EXISTS calendar_intervals_cal_idx ON calendar_intervals (calendar_id, starts_at);
