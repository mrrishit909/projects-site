-- RetentionLab constraints that need functions: append-only tables, the availability proof of a feature row, the citations of a
-- prediction, the immutability of a training run once it has scored, the label maturity transition. Idempotent.

CREATE OR REPLACE FUNCTION rl_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

-- D-01: the builder proves max_available_at < prediction_at on every row.
CREATE OR REPLACE FUNCTION rl_feature_row_guard() RETURNS trigger AS $$
DECLARE pa timestamptz;
BEGIN
    SELECT prediction_at INTO pa FROM prediction_cutoffs WHERE cutoff_id = NEW.cutoff_id;
    IF NEW.max_available_at IS NOT NULL AND NEW.max_available_at >= pa THEN
        RAISE EXCEPTION 'AVAILABILITY_AFTER_CUTOFF: a feature row may use only data available before its cutoff' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- D-01: a label exists for an existing cutoff only, its window ends after the horizon, and an immature label becomes mature exactly
-- once (churned NULL -> known, same label_end); nothing else about a label ever changes.
CREATE OR REPLACE FUNCTION rl_label_guard() RETURNS trigger AS $$
DECLARE he timestamptz;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT horizon_end INTO he FROM prediction_cutoffs WHERE cutoff_id = NEW.cutoff_id;
        IF NEW.label_end < he THEN
            RAISE EXCEPTION 'LABEL_WINDOW_INVALID: label_end cannot precede the horizon end' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    ELSE
        IF NOT (OLD.mature = false AND OLD.churned IS NULL AND NEW.mature = true AND NEW.churned IS NOT NULL
                AND NEW.label_id = OLD.label_id AND NEW.cutoff_id = OLD.cutoff_id AND NEW.label_end = OLD.label_end) THEN
            RAISE EXCEPTION 'LABEL_IMMUTABLE: only a censored label can mature, once' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- A training run keeps its identity and boundaries; its config (and hash) change only while no prediction cites it; it is never deleted.
CREATE OR REPLACE FUNCTION rl_run_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'training_runs is append-only: DELETE is not allowed' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.training_run_id, NEW.train_end, NEW.validation_end, NEW.test_end, NEW.created_at, NEW.created_by)
       IS DISTINCT FROM (OLD.training_run_id, OLD.train_end, OLD.validation_end, OLD.test_end, OLD.created_at, OLD.created_by) THEN
        RAISE EXCEPTION 'RUN_IMMUTABLE: a training run keeps its identity and boundaries' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.config, NEW.config_hash) IS DISTINCT FROM (OLD.config, OLD.config_hash)
       AND EXISTS (SELECT 1 FROM predictions WHERE training_run_id = OLD.training_run_id) THEN
        RAISE EXCEPTION 'RUN_FROZEN: the configuration of a scored run never changes' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- The artefact tables of a run are rewritten only while the run is not frozen.
CREATE OR REPLACE FUNCTION rl_artefact_guard() RETURNS trigger AS $$
DECLARE rid text;
BEGIN
    rid := CASE WHEN TG_OP = 'DELETE' THEN OLD.training_run_id ELSE NEW.training_run_id END;
    IF EXISTS (SELECT 1 FROM predictions WHERE training_run_id = rid) THEN
        RAISE EXCEPTION 'RUN_FROZEN: the artefacts of a scored run never change' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$ LANGUAGE plpgsql;

-- D-02 / D-P10-17: a prediction cites the run's config_hash, feature_version and label_version.
CREATE OR REPLACE FUNCTION rl_prediction_guard() RETURNS trigger AS $$
DECLARE run training_runs;
BEGIN
    SELECT * INTO run FROM training_runs WHERE training_run_id = NEW.training_run_id;
    IF NEW.config_hash IS DISTINCT FROM run.config_hash
       OR NEW.feature_version IS DISTINCT FROM run.config ->> 'feature_version'
       OR NEW.label_version IS DISTINCT FROM run.config ->> 'label_version' THEN
        RAISE EXCEPTION 'CITATION_MISMATCH: a prediction must cite its run''s config_hash, feature_version and label_version' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['accounts', 'subscription_events', 'billing_events', 'usage_events', 'support_events', 'prediction_cutoffs',
                             'feature_rows', 'predictions', 'split_assignments', 'scoring_publications', 'intervention_scenarios',
                             'outreach_events', 'feature_registry', 'label_versions', 'feature_versions', 'audit_events',
                             'rejected_records', 'command_results']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_immutable') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION rl_forbid_mutation()', t || '_immutable', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION rl_forbid_mutation()', t || '_no_truncate', t);
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'feature_rows_guard') THEN
        CREATE TRIGGER feature_rows_guard BEFORE INSERT ON feature_rows FOR EACH ROW EXECUTE FUNCTION rl_feature_row_guard();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'labels_guard') THEN
        CREATE TRIGGER labels_guard BEFORE INSERT OR UPDATE ON labels FOR EACH ROW EXECUTE FUNCTION rl_label_guard();
        CREATE TRIGGER labels_no_delete BEFORE DELETE OR TRUNCATE ON labels FOR EACH STATEMENT EXECUTE FUNCTION rl_forbid_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'training_runs_guard') THEN
        CREATE TRIGGER training_runs_guard BEFORE UPDATE OR DELETE ON training_runs FOR EACH ROW EXECUTE FUNCTION rl_run_guard();
        CREATE TRIGGER training_runs_no_truncate BEFORE TRUNCATE ON training_runs FOR EACH STATEMENT EXECUTE FUNCTION rl_forbid_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'predictions_guard') THEN
        CREATE TRIGGER predictions_guard BEFORE INSERT ON predictions FOR EACH ROW EXECUTE FUNCTION rl_prediction_guard();
    END IF;
    FOREACH t IN ARRAY ARRAY['model_preprocessing', 'model_coefficients', 'calibration_maps']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_guard') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION rl_artefact_guard()', t || '_guard', t);
        END IF;
    END LOOP;
END
$$;
