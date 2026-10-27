-- Pipeline Observatory, constraints that need functions or triggers. The database refuses what the domain refuses, so a bug in the
-- application cannot create a ninth record, a regressing checkpoint, a half-committed batch or a pointer to a failed run.
-- Idempotent (CREATE OR REPLACE, drop-then-create triggers).

CREATE OR REPLACE FUNCTION po_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'APPEND_ONLY: % on % is not allowed (evidence is immutable)', TG_OP, TG_TABLE_NAME USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

-- A checkpoint commits previous + 1 of its source, in commit order (D-01, D-P8-11).
CREATE OR REPLACE FUNCTION po_checkpoint_guard() RETURNS trigger AS $$
DECLARE prev INT;
BEGIN
    SELECT coalesce(max(version_number), 0) INTO prev FROM checkpoints WHERE source_id = NEW.source_id;
    IF NEW.version_number <= prev THEN
        RAISE EXCEPTION 'CHECKPOINT_REGRESSION: version % is not after committed version %', NEW.version_number, prev USING ERRCODE = '23514';
    ELSIF NEW.version_number <> prev + 1 THEN
        RAISE EXCEPTION 'CHECKPOINT_GAP: version % skips %', NEW.version_number, prev + 1 USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM ingestion_batches b WHERE b.batch_id = NEW.batch_id AND b.source_id = NEW.source_id) THEN
        RAISE EXCEPTION 'UNKNOWN_BATCH: checkpoint % names a batch of another source', NEW.checkpoint_id USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- A batch commits atomically with its checkpoint: at COMMIT time a committed batch has its checkpoint and every checkpoint's batch is committed.
CREATE OR REPLACE FUNCTION po_commit_pairing() RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'ingestion_batches' THEN
        IF NEW.status = 'committed' AND NOT EXISTS (SELECT 1 FROM checkpoints c WHERE c.batch_id = NEW.batch_id) THEN
            RAISE EXCEPTION 'COMMIT_WITHOUT_CHECKPOINT: batch % is committed without its checkpoint', NEW.batch_id USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NOT EXISTS (SELECT 1 FROM ingestion_batches b WHERE b.batch_id = NEW.batch_id AND b.status = 'committed') THEN
            RAISE EXCEPTION 'CHECKPOINT_WITHOUT_COMMIT: checkpoint % belongs to a batch that is not committed', NEW.checkpoint_id USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- A committed batch is final: its status never changes and its rows are never reclassified.
CREATE OR REPLACE FUNCTION po_batch_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'committed' AND (NEW.status <> 'committed' OR NEW.source_id <> OLD.source_id OR NEW.source_cursor <> OLD.source_cursor) THEN
        RAISE EXCEPTION 'APPEND_ONLY: committed batch % cannot change', OLD.batch_id USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION po_raw_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' OR NEW.payload_json IS DISTINCT FROM OLD.payload_json OR NEW.payload_hash <> OLD.payload_hash
       OR NEW.source_key IS DISTINCT FROM OLD.source_key OR NEW.batch_id <> OLD.batch_id THEN
        RAISE EXCEPTION 'APPEND_ONLY: raw record % is evidence and cannot change', OLD.raw_record_id USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM ingestion_batches b WHERE b.batch_id = OLD.batch_id AND b.status = 'committed')
       AND (NEW.disposition IS DISTINCT FROM OLD.disposition OR NEW.reason_code IS DISTINCT FROM OLD.reason_code) THEN
        RAISE EXCEPTION 'APPEND_ONLY: raw record % belongs to a committed batch', OLD.raw_record_id USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION po_accepted_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' OR (to_jsonb(NEW) - 'deleted_in_batch') IS DISTINCT FROM (to_jsonb(OLD) - 'deleted_in_batch') OR OLD.deleted_in_batch IS NOT NULL THEN
        RAISE EXCEPTION 'APPEND_ONLY: accepted record %/% cannot change (only a delete event may mark it)', OLD.source_id, OLD.source_key USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- The gate of a run (D-P8-08): the LATEST result of each rule counts; allowed iff at least one critical result exists and none failed.
CREATE OR REPLACE FUNCTION po_gate_allowed(p_run TEXT) RETURNS BOOLEAN AS $$
    WITH latest AS (
        SELECT DISTINCT ON (q.rule_name) q.severity, q.failure_count
        FROM quality_results q JOIN task_runs t ON t.task_run_id = q.task_run_id
        WHERE t.run_id = p_run
        ORDER BY q.rule_name, q.quality_result_id DESC
    )
    SELECT coalesce(bool_or(severity = 'critical'), false) AND NOT coalesce(bool_or(severity = 'critical' AND failure_count > 0), false) FROM latest;
$$ LANGUAGE sql STABLE;

-- The pointer moves only to a passed candidate: its run succeeded and its gate is allowed (P08-TEST-07).
CREATE OR REPLACE FUNCTION po_pointer_guard() RETURNS trigger AS $$
DECLARE r pipeline_runs%ROWTYPE;
BEGIN
    SELECT pr.* INTO r FROM pipeline_runs pr JOIN publications p ON p.run_id = pr.run_id WHERE p.publication_id = NEW.publication_id;
    IF r.run_id IS NULL OR r.status <> 'success' THEN
        RAISE EXCEPTION 'POINTER_REQUIRES_SUCCESS: publication % does not belong to a successful run', NEW.publication_id USING ERRCODE = '23514';
    END IF;
    IF NOT po_gate_allowed(r.run_id) THEN
        RAISE EXCEPTION 'POINTER_REQUIRES_GATE: the gate of run % is blocked', r.run_id USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- A publication's run must have passed the same test before the publication exists at all.
CREATE OR REPLACE FUNCTION po_publication_guard() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pipeline_runs r WHERE r.run_id = NEW.run_id AND r.status = 'success') THEN
        RAISE EXCEPTION 'PUBLICATION_REQUIRES_SUCCESS: run % has not succeeded', NEW.run_id USING ERRCODE = '23514';
    END IF;
    IF NOT po_gate_allowed(NEW.run_id) THEN
        RAISE EXCEPTION 'PUBLICATION_REQUIRES_GATE: the gate of run % is blocked', NEW.run_id USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION po_incident_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'closed' THEN
        RAISE EXCEPTION 'APPEND_ONLY: closed incident % cannot change', OLD.incident_id USING ERRCODE = '23514';
    END IF;
    IF NEW.opened_at <> OLD.opened_at OR NEW.run_id <> OLD.run_id THEN
        RAISE EXCEPTION 'APPEND_ONLY: the detection of incident % cannot change', OLD.incident_id USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['checkpoints', 'quarantine_records', 'publications', 'quality_results', 'model_definitions', 'audit_events',
                             'command_results', 'task_runs', 'fetch_log', 'evidence_archives'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_immutable', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE DELETE ON %I FOR EACH ROW EXECUTE FUNCTION po_forbid_mutation()', t || '_immutable', t);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_no_truncate', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION po_forbid_mutation()', t || '_no_truncate', t);
    END LOOP;
    -- tables whose rows are never updated either (task_runs and fetch_log keep their status; the others are pure facts)
    FOREACH t IN ARRAY ARRAY['checkpoints', 'quarantine_records', 'publications', 'quality_results', 'model_definitions', 'audit_events',
                             'command_results', 'evidence_archives'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_no_update', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION po_forbid_mutation()', t || '_no_update', t);
    END LOOP;
END $$;

DROP TRIGGER IF EXISTS checkpoints_guard ON checkpoints;
CREATE TRIGGER checkpoints_guard BEFORE INSERT ON checkpoints FOR EACH ROW EXECUTE FUNCTION po_checkpoint_guard();
DROP TRIGGER IF EXISTS checkpoints_pairing ON checkpoints;
CREATE CONSTRAINT TRIGGER checkpoints_pairing AFTER INSERT ON checkpoints DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION po_commit_pairing();
DROP TRIGGER IF EXISTS batches_pairing ON ingestion_batches;
CREATE CONSTRAINT TRIGGER batches_pairing AFTER INSERT OR UPDATE ON ingestion_batches DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION po_commit_pairing();
DROP TRIGGER IF EXISTS batches_guard ON ingestion_batches;
CREATE TRIGGER batches_guard BEFORE UPDATE ON ingestion_batches FOR EACH ROW EXECUTE FUNCTION po_batch_guard();
DROP TRIGGER IF EXISTS batches_no_delete ON ingestion_batches;
CREATE TRIGGER batches_no_delete BEFORE DELETE ON ingestion_batches FOR EACH ROW EXECUTE FUNCTION po_forbid_mutation();
DROP TRIGGER IF EXISTS raw_records_guard ON raw_records;
CREATE TRIGGER raw_records_guard BEFORE UPDATE OR DELETE ON raw_records FOR EACH ROW EXECUTE FUNCTION po_raw_guard();
DROP TRIGGER IF EXISTS accepted_guard ON accepted_records;
CREATE TRIGGER accepted_guard BEFORE UPDATE OR DELETE ON accepted_records FOR EACH ROW EXECUTE FUNCTION po_accepted_guard();
DROP TRIGGER IF EXISTS publications_guard ON publications;
CREATE TRIGGER publications_guard BEFORE INSERT ON publications FOR EACH ROW EXECUTE FUNCTION po_publication_guard();
DROP TRIGGER IF EXISTS pointer_guard ON publication_pointer;
CREATE TRIGGER pointer_guard BEFORE INSERT OR UPDATE ON publication_pointer FOR EACH ROW EXECUTE FUNCTION po_pointer_guard();
DROP TRIGGER IF EXISTS incidents_guard ON incidents;
CREATE TRIGGER incidents_guard BEFORE UPDATE ON incidents FOR EACH ROW EXECUTE FUNCTION po_incident_guard();
DROP TRIGGER IF EXISTS incidents_no_delete ON incidents;
CREATE TRIGGER incidents_no_delete BEFORE DELETE ON incidents FOR EACH ROW EXECUTE FUNCTION po_forbid_mutation();
