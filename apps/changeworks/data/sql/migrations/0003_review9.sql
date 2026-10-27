-- ChangeWorks review-9 changes (contract D-09), idempotent.
--
-- * R9-01  plan rows carry the server instant they were recorded (cost_items, benefit_items: ``recorded_at``; NULL: part of the loaded world); a scenario seals the
--          size of its initiative and pin sets (``initiatives_expected``, ``pins_expected``) and no row can be added to either set once they are complete; a proposal
--          stores the hash of the inputs its figures were resolved from (``snapshot_hash``).
-- * R9-04  an evidence reference, when present, is not blank.
-- * R9-05  one cost key is one kind of cost for an initiative and a basis (COST_KEY_BASIS_CONFLICT).
-- * R9-11  observations carry the server instant they were recorded (adoption_observations and benefit_observations: ``recorded_at``; training_completions:
--          ``entered_at``), apart from the instant the event happened.
-- * R9-14  the period start is a day of 28 or less, so every month has it.

ALTER TABLE cost_items ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ;
ALTER TABLE benefit_items ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ;
ALTER TABLE adoption_observations ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ;
ALTER TABLE benefit_observations ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ;
ALTER TABLE training_completions ADD COLUMN IF NOT EXISTS entered_at TIMESTAMPTZ;
ALTER TABLE scenario_versions ADD COLUMN IF NOT EXISTS initiatives_expected INT;
ALTER TABLE scenario_versions ADD COLUMN IF NOT EXISTS pins_expected INT;
ALTER TABLE scenario_versions ADD COLUMN IF NOT EXISTS snapshot_hash TEXT;

-- scenarios that exist already are sealed at the size they have
UPDATE scenario_versions s SET initiatives_expected = (SELECT count(*) FROM scenario_initiatives i WHERE i.scenario_id = s.scenario_id) WHERE initiatives_expected IS NULL;
UPDATE scenario_versions s SET pins_expected = (SELECT count(*) FROM scenario_pins p WHERE p.scenario_id = s.scenario_id) WHERE pins_expected IS NULL;
ALTER TABLE scenario_versions ALTER COLUMN initiatives_expected SET NOT NULL;
ALTER TABLE scenario_versions ALTER COLUMN pins_expected SET NOT NULL;

DO $$
DECLARE c record;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('dataset_config_day_ck',   'dataset_config',       $c$CHECK (extract(day FROM period_start) <= 28)$c$),
        ('scenarios_sealed_ck',     'scenario_versions',    'CHECK (initiatives_expected >= 1 AND pins_expected >= 0)'),
        ('scenarios_snapshot_ck',   'scenario_versions',    $c$CHECK (snapshot_hash IS NULL OR (status = 'proposed' AND snapshot_hash ~ '^[0-9a-f]{64}$'))$c$),
        ('benefit_items_evidence_ck', 'benefit_items',      $c$CHECK (evidence_ref IS NULL OR evidence_ref ~ '[^ \t\r\n\f\v]')$c$),
        ('assumptions_evidence_ck', 'assumption_versions',  $c$CHECK ((evidence_ref IS NULL OR evidence_ref ~ '[^ \t\r\n\f\v]') AND (staffing_change_evidence_ref IS NULL OR staffing_change_evidence_ref ~ '[^ \t\r\n\f\v]'))$c$),
        ('benefit_obs_evidence_ck', 'benefit_observations', $c$CHECK (evidence_ref ~ '[^ \t\r\n\f\v]')$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

-- A cost key is one kind of cost (one_time or recurring) for an initiative and a basis.
CREATE OR REPLACE FUNCTION cw_cost_key_guard() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM cost_items c WHERE c.initiative_id = NEW.initiative_id AND c.cost_key = NEW.cost_key AND c.cost_basis = NEW.cost_basis AND c.cost_type <> NEW.cost_type) THEN
        RAISE EXCEPTION 'COST_KEY_BASIS_CONFLICT: cost key % of % is already used as another kind of cost for the % basis', NEW.cost_key, NEW.initiative_id, NEW.cost_basis
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- The initiatives and the pinned assumptions of a scenario are frozen once the scenario exists: a row beyond the sealed size is refused.
CREATE OR REPLACE FUNCTION cw_scenario_sets_guard() RETURNS trigger AS $$
DECLARE have INT; want INT;
BEGIN
    IF TG_TABLE_NAME = 'scenario_pins' THEN
        SELECT pins_expected INTO want FROM scenario_versions WHERE scenario_id = NEW.scenario_id;
        SELECT count(*) INTO have FROM scenario_pins WHERE scenario_id = NEW.scenario_id;
    ELSE
        SELECT initiatives_expected INTO want FROM scenario_versions WHERE scenario_id = NEW.scenario_id;
        SELECT count(*) INTO have FROM scenario_initiatives WHERE scenario_id = NEW.scenario_id;
    END IF;
    IF have >= want THEN
        RAISE EXCEPTION 'SCENARIO_IMMUTABLE: the % of scenario % are sealed; an edit creates a new scenario_id', CASE WHEN TG_TABLE_NAME = 'scenario_pins' THEN 'pinned assumptions' ELSE 'initiatives' END, NEW.scenario_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION cw_scenario_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SCENARIO_IMMUTABLE: scenario versions are never deleted' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.scenario_id, NEW.baseline_version, NEW.discount_rate, NEW.rate_basis, NEW.rate_conversion_assumption_id, NEW.horizon_periods,
        NEW.created_at, NEW.created_by, NEW.initiatives_expected, NEW.pins_expected)
       IS DISTINCT FROM (OLD.scenario_id, OLD.baseline_version, OLD.discount_rate, OLD.rate_basis, OLD.rate_conversion_assumption_id, OLD.horizon_periods,
                         OLD.created_at, OLD.created_by, OLD.initiatives_expected, OLD.pins_expected) THEN
        RAISE EXCEPTION 'SCENARIO_IMMUTABLE: a scenario version never changes; an edit creates a new scenario_id' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'proposed' AND (NEW.status, NEW.proposed_at, NEW.proposed_by, NEW.comparison, NEW.residual_explanation, NEW.snapshot_hash)
                                    IS DISTINCT FROM (OLD.status, OLD.proposed_at, OLD.proposed_by, OLD.comparison, OLD.residual_explanation, OLD.snapshot_hash) THEN
        RAISE EXCEPTION 'SCENARIO_IMMUTABLE: a proposal is final; there is no funded status and no way back' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'cost_items_key_guard') THEN
        CREATE TRIGGER cost_items_key_guard BEFORE INSERT ON cost_items FOR EACH ROW EXECUTE FUNCTION cw_cost_key_guard();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'scenario_pins_sealed') THEN
        CREATE TRIGGER scenario_pins_sealed BEFORE INSERT ON scenario_pins FOR EACH ROW EXECUTE FUNCTION cw_scenario_sets_guard();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'scenario_initiatives_sealed') THEN
        CREATE TRIGGER scenario_initiatives_sealed BEFORE INSERT ON scenario_initiatives FOR EACH ROW EXECUTE FUNCTION cw_scenario_sets_guard();
    END IF;
END
$$;
