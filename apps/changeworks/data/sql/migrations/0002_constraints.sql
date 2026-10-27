-- ChangeWorks constraints, helper functions and triggers (idempotent).
--
-- * Append-only (nothing is edited or deleted, TRUNCATE included): process_baselines, baseline_approvals, assumption_versions, opportunity_scores,
--   resources, scenario_initiatives, scenario_pins, cost_items, expanded_costs, benefit_items, dependencies, stakeholder_groups, impact_mappings,
--   resource_allocations, readiness_assessments, adoption_observations, training_completions, benefit_observations, risk_items, forecast_versions,
--   rejected_records, audit_events, command_results, dataset_versions. A baseline rewrite, a forecast overwrite and an assumption edit are
--   therefore refused by the database itself.
-- * initiatives: identity never changes; every change bumps ``version`` by one; ``baseline_version`` may only name an approved set.
-- * scenario_versions: immutable except draft -> proposed (C07), once, with who and when and the comparison it was chosen from.
-- * cw_dec / cw_iso are helpers also used by data/sql/reference_metrics.sql.

CREATE OR REPLACE FUNCTION cw_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '%: % is append-only: % is not allowed', coalesce(TG_ARGV[0], 'APPEND_ONLY'), TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

-- UTC instants as published: YYYY-MM-DDTHH:MM:SS[.ffffff]Z
CREATE OR REPLACE FUNCTION cw_iso(t TIMESTAMPTZ) RETURNS TEXT AS $$
    SELECT CASE WHEN t IS NULL THEN NULL ELSE
        to_char(t AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
        || CASE WHEN extract(microseconds FROM t) % 1000000 <> 0 THEN '.' || rtrim(to_char(t AT TIME ZONE 'UTC', 'US'), '0') ELSE '' END || 'Z' END
$$ LANGUAGE sql IMMUTABLE;

-- A decimal as published: at least 2 places, no trailing zeros beyond them (1000.000000 -> 1000.00).
CREATE OR REPLACE FUNCTION cw_dec(n NUMERIC) RETURNS TEXT AS $$
    SELECT CASE WHEN n IS NULL THEN NULL ELSE
        CASE WHEN position('.' IN n::text) = 0 THEN n::text || '.00'
             ELSE split_part(n::text, '.', 1) || '.' || CASE WHEN length(rtrim(split_part(n::text, '.', 2), '0')) >= 2 THEN rtrim(split_part(n::text, '.', 2), '0')
                                                              ELSE rpad(rtrim(split_part(n::text, '.', 2), '0'), 2, '0') END END END
$$ LANGUAGE sql IMMUTABLE;

DO $$
DECLARE c record;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('dataset_config_ck',      'dataset_config',     $c$CHECK (id = 1 AND period_basis IN ('annual', 'monthly'))$c$),
        ('initiatives_status_ck',  'initiatives',        $c$CHECK (status IN ('candidate', 'assessed', 'in_delivery', 'adopted', 'closed'))$c$),
        ('initiatives_period_ck',  'initiatives',        'CHECK (requested_start_period >= 0 AND duration_periods >= 1 AND deployment_period >= 0 AND version >= 1)'),
        ('baselines_values_ck',    'process_baselines',  'CHECK (volume >= 0 AND minutes_per_case >= 0 AND error_rate BETWEEN 0 AND 1 AND length(btrim(evidence_ref)) > 0)'),
        ('assumptions_ck',         'assumption_versions',$c$CHECK (version_number >= 1 AND length(btrim(rationale)) > 0 AND length(btrim(author_id)) > 0
                                                          AND (value IS NULL) <> (value_list IS NULL)
                                                          AND (value IS NULL OR value ~ '^-?[0-9]{1,14}(\.[0-9]{1,6})?$')
                                                          AND (value_list IS NULL OR jsonb_typeof(value_list) = 'array'))$c$),
        ('scores_ck',              'opportunity_scores', 'CHECK (version_number >= 1 AND length(btrim(rationale)) > 0 AND jsonb_typeof(criteria) = ''array'')'),
        ('resources_ck',           'resources',          'CHECK (capacity_per_period >= 0)'),
        ('scenarios_ck',           'scenario_versions',  $c$CHECK (status IN ('draft', 'proposed') AND rate_basis IN ('annual', 'monthly') AND discount_rate BETWEEN 0 AND 1
                                                          AND horizon_periods BETWEEN 1 AND 600 AND ((status = 'proposed') = (proposed_at IS NOT NULL)))$c$),
        ('cost_items_ck',          'cost_items',         $c$CHECK (cost_basis IN ('planned', 'actual') AND amount >= 0 AND (
                                                              (cost_type = 'one_time' AND period_index IS NOT NULL AND period_index >= 0 AND start_period IS NULL AND end_period IS NULL) OR
                                                              (cost_type = 'recurring' AND period_index IS NULL AND start_period IS NOT NULL AND end_period IS NOT NULL
                                                               AND start_period >= 0 AND end_period > start_period)))$c$),
        ('expanded_costs_ck',      'expanded_costs',     'CHECK (period_index >= 0 AND amount >= 0)'),
        ('benefit_items_ck',       'benefit_items',      $c$CHECK (benefit_type IN ('cash', 'avoided_cost', 'revenue', 'capacity') AND amount >= 0 AND period_index >= starts_period
                                                          AND starts_period >= 0 AND unit = CASE WHEN benefit_type = 'capacity' THEN 'hours' ELSE 'USD' END
                                                          AND (baseline_trend_per_period IS NULL OR baseline_trend_per_period >= 0))$c$),
        ('dependencies_ck',        'dependencies',       $c$CHECK (dependency_type IN ('finish_to_start', 'start_to_start') AND lag_periods >= 0)$c$),
        ('groups_ck',              'stakeholder_groups', $c$CHECK (impact_level IN ('low', 'medium', 'high') AND affected_count >= 0)$c$),
        ('impact_mappings_ck',     'impact_mappings',    $c$CHECK (impact_level IN ('low', 'medium', 'high') AND length(btrim(operating_change)) > 0)$c$),
        ('allocations_ck',         'resource_allocations','CHECK (amount >= 0 AND period_index >= 0)'),
        ('readiness_ck',           'readiness_assessments',$c$CHECK (dimension IN ('awareness', 'desire', 'knowledge', 'ability', 'reinforcement') AND score BETWEEN 1 AND 5 AND weight > 0)$c$),
        ('adoption_ck',            'adoption_observations','CHECK (eligible_count >= 0 AND adopted_count >= 0 AND adopted_count <= eligible_count)'),
        ('training_ck',            'training_completions','CHECK (eligible_trainees >= 0 AND completed >= 0 AND completed <= eligible_trainees)'),
        ('benefit_obs_ck',         'benefit_observations','CHECK (measured_value >= 0)'),
        ('risk_ck',                'risk_items',         'CHECK (probability BETWEEN 0 AND 1 AND impact >= 0)'),
        ('forecast_ck',            'forecast_versions',  'CHECK (version_number >= 1 AND period_index >= 0 AND amount >= 0 AND length(btrim(reason)) > 0)'),
        ('command_results_role_ck','command_results',    $c$CHECK (actor_role IN ('analyst', 'sponsor', 'admin'))$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

-- One-time costs: a (initiative, cost_key, basis) appears once (ONE_TIME_COST_REPEATED is enforced by the database as well as the domain).
CREATE UNIQUE INDEX IF NOT EXISTS cost_items_one_time_uq ON cost_items (initiative_id, cost_key, cost_basis) WHERE cost_type = 'one_time';
-- A dependency between two initiatives is stored once, and never on itself.
CREATE UNIQUE INDEX IF NOT EXISTS dependencies_pair_uq ON dependencies (initiative_id, prerequisite_id, dependency_type);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dependencies_self_ck') THEN
        ALTER TABLE dependencies ADD CONSTRAINT dependencies_self_ck CHECK (initiative_id <> prerequisite_id);
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION cw_initiative_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'INITIATIVE_IMMUTABLE: initiatives are never deleted (close them)' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.initiative_id, NEW.title, NEW.sponsor_id, NEW.deployment_period, NEW.eligibility_rule_version, NEW.created_at)
       IS DISTINCT FROM (OLD.initiative_id, OLD.title, OLD.sponsor_id, OLD.deployment_period, OLD.eligibility_rule_version, OLD.created_at) THEN
        RAISE EXCEPTION 'INITIATIVE_IMMUTABLE: the identity of an initiative never changes' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'STALE_VERSION: every change of an initiative bumps its version by exactly one' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.baseline_version IS NOT NULL AND NEW.baseline_version IS NULL THEN
        RAISE EXCEPTION 'BASELINE_FROZEN: an approved baseline is never withdrawn; a correction is a new version' USING ERRCODE = 'integrity_constraint_violation';
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
        NEW.created_at, NEW.created_by)
       IS DISTINCT FROM (OLD.scenario_id, OLD.baseline_version, OLD.discount_rate, OLD.rate_basis, OLD.rate_conversion_assumption_id, OLD.horizon_periods,
                         OLD.created_at, OLD.created_by) THEN
        RAISE EXCEPTION 'SCENARIO_IMMUTABLE: a scenario version never changes; an edit creates a new scenario_id' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'proposed' AND (NEW.status, NEW.proposed_at, NEW.proposed_by, NEW.comparison, NEW.residual_explanation)
                                    IS DISTINCT FROM (OLD.status, OLD.proposed_at, OLD.proposed_by, OLD.comparison, OLD.residual_explanation) THEN
        RAISE EXCEPTION 'SCENARIO_IMMUTABLE: a proposal is final; there is no funded status and no way back' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT * FROM (VALUES
        ('process_baselines', 'BASELINE_FROZEN'), ('baseline_approvals', 'APPROVAL_IMMUTABLE'), ('assumption_versions', 'ASSUMPTION_IMMUTABLE'),
        ('opportunity_scores', 'APPEND_ONLY'), ('resources', 'APPEND_ONLY'), ('scenario_initiatives', 'SCENARIO_IMMUTABLE'), ('scenario_pins', 'SCENARIO_IMMUTABLE'),
        ('cost_items', 'APPEND_ONLY'), ('expanded_costs', 'APPEND_ONLY'), ('benefit_items', 'APPEND_ONLY'), ('dependencies', 'APPEND_ONLY'),
        ('stakeholder_groups', 'APPEND_ONLY'), ('impact_mappings', 'APPEND_ONLY'), ('resource_allocations', 'APPEND_ONLY'),
        ('readiness_assessments', 'APPEND_ONLY'), ('adoption_observations', 'APPEND_ONLY'), ('training_completions', 'APPEND_ONLY'),
        ('benefit_observations', 'APPEND_ONLY'), ('risk_items', 'APPEND_ONLY'), ('forecast_versions', 'FORECAST_OVERWRITE'),
        ('rejected_records', 'APPEND_ONLY'), ('audit_events', 'APPEND_ONLY'), ('command_results', 'APPEND_ONLY'), ('dataset_versions', 'APPEND_ONLY')
    ) AS x (tbl, code)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t.tbl || '_immutable') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION cw_forbid_mutation(%L)', t.tbl || '_immutable', t.tbl, t.code);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION cw_forbid_mutation(%L)', t.tbl || '_no_truncate', t.tbl, t.code);
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'initiatives_guard') THEN
        CREATE TRIGGER initiatives_guard BEFORE UPDATE OR DELETE ON initiatives FOR EACH ROW EXECUTE FUNCTION cw_initiative_guard();
        CREATE TRIGGER initiatives_no_truncate BEFORE TRUNCATE ON initiatives FOR EACH STATEMENT EXECUTE FUNCTION cw_forbid_mutation('INITIATIVE_IMMUTABLE');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'scenario_versions_guard') THEN
        CREATE TRIGGER scenario_versions_guard BEFORE UPDATE OR DELETE ON scenario_versions FOR EACH ROW EXECUTE FUNCTION cw_scenario_guard();
        CREATE TRIGGER scenario_versions_no_truncate BEFORE TRUNCATE ON scenario_versions FOR EACH STATEMENT EXECUTE FUNCTION cw_forbid_mutation('SCENARIO_IMMUTABLE');
    END IF;
END
$$;
