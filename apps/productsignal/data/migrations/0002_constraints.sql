-- ProductSignal constraints, helper functions and triggers (idempotent).
--
-- * Assignments are unique per (experiment_version_id, unit_id): the first assignment fixes the variant (D-03); one exposure per
--   assignment, never before it; one observation per (assignment, metric); one plan per experiment version; one decision per
--   analysis run; one guardrail review per analysis run.
-- * Append-only: events, event_properties, identity_links, sessions, assignments, exposures, metric_observations, analysis_plans,
--   analysis_runs, funnel_definitions, guardrail_reviews, decisions, audit_events, rejected_records. Nothing is edited or deleted.
-- * ps_valid_tz and ps_canonical_json are helpers (also used by data/sql/reference_metrics.sql, which stays independent of Python).

CREATE OR REPLACE FUNCTION ps_valid_tz(tz TEXT) RETURNS BOOLEAN AS $$
    SELECT EXISTS (SELECT 1 FROM ps_timezones WHERE name = tz)
$$ LANGUAGE sql STABLE;

-- Compact JSON with keys sorted by code point, the form the plan hash is taken over (json.dumps(sort_keys, separators=(",", ":"))).
CREATE OR REPLACE FUNCTION ps_canonical_json(j JSONB) RETURNS TEXT AS $$
DECLARE out TEXT;
BEGIN
    CASE jsonb_typeof(j)
        WHEN 'object' THEN
            SELECT '{' || coalesce(string_agg(to_jsonb(k)::text || ':' || ps_canonical_json(j -> k), ',' ORDER BY k COLLATE "C"), '') || '}'
              INTO out FROM jsonb_object_keys(j) AS k;
        WHEN 'array' THEN
            SELECT '[' || coalesce(string_agg(ps_canonical_json(e), ',' ORDER BY ord), '') || ']'
              INTO out FROM jsonb_array_elements(j) WITH ORDINALITY AS t (e, ord);
        ELSE
            out := j::text;
    END CASE;
    RETURN out;
END
$$ LANGUAGE plpgsql IMMUTABLE;

DO $$
DECLARE c record;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('accounts_tz_ck',         'accounts',            'CHECK (ps_valid_tz(timezone))'),
        ('users_tz_ck',            'users',               'CHECK (ps_valid_tz(timezone))'),
        ('links_anon_uq',          'identity_links',      'UNIQUE (anonymous_id)'),
        ('events_name_ck',         'events',              $c$CHECK (event_name ~ '^[a-z][a-z0-9_]{0,63}$')$c$),
        ('events_ident_ck',        'events',              $c$CHECK (user_id IS NULL OR length(user_id) > 0)$c$),
        ('event_props_uq',         'event_properties',    'UNIQUE (event_id, property_key)'),
        ('event_props_type_ck',    'event_properties',    $c$CHECK (value_type = 'string')$c$),
        ('subscriptions_amt_ck',   'subscriptions',       'CHECK (amount_usd >= 0 AND (ends_at IS NULL OR ends_at >= starts_at))'),
        ('sessions_interval_ck',   'sessions',            'CHECK (ended_at IS NULL OR ended_at >= started_at)'),
        ('versions_unit_ck',       'experiment_versions', $c$CHECK (unit_type = 'account')$c$),
        ('assignments_unit_uq',    'assignments',         'UNIQUE (experiment_version_id, unit_id)'),
        ('exposures_asg_uq',       'exposures',           'UNIQUE (assignment_id)'),
        ('observations_uq',        'metric_observations', 'UNIQUE (assignment_id, metric_name)'),
        ('observations_value_ck',  'metric_observations', $c$CHECK (value IN ('0', '1'))$c$),
        ('plans_hash_ck',          'analysis_plans',      $c$CHECK (config_hash ~ '^[0-9a-f]{64}$')$c$),
        ('runs_hash_ck',           'analysis_runs',       $c$CHECK (config_hash ~ '^[0-9a-f]{64}$')$c$),
        ('runs_srm_ck',            'analysis_runs',       $c$CHECK (srm_verdict IS NULL OR srm_verdict IN ('OK', 'MISMATCH', 'INSUFFICIENT'))$c$),
        ('funnel_steps_ck',        'funnel_definitions',  'CHECK (cardinality(steps) >= 2 AND version >= 1 AND max_gap_hours >= 1 AND window_from < window_to)'),
        ('metric_config_ck',       'metric_config',       'CHECK (id = 1)'),
        ('reviews_uq',             'guardrail_reviews',   'UNIQUE (analysis_id)'),
        ('reviews_verdict_ck',     'guardrail_reviews',   $c$CHECK (verdict IN ('OK', 'HARMFUL', 'INSUFFICIENT'))$c$),
        ('decisions_uq',           'decisions',           'UNIQUE (analysis_id)'),
        ('decisions_kind_ck',      'decisions',           $c$CHECK (decision IN ('ship', 'stop', 'inconclusive') AND basis = 'primary' AND length(btrim(rationale)) > 0)$c$),
        ('decisions_role_ck',      'decisions',           $c$CHECK (decided_role IN ('experimenter', 'admin'))$c$),
        ('command_results_role_ck','command_results',     $c$CHECK (actor_role IN ('analyst', 'experimenter', 'admin'))$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION ps_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

-- An exposure never precedes its assignment (D-03, P06-TEST-11).
CREATE OR REPLACE FUNCTION ps_exposure_not_early() RETURNS trigger AS $$
DECLARE at TIMESTAMPTZ;
BEGIN
    SELECT assigned_at INTO at FROM assignments WHERE assignment_id = NEW.assignment_id;
    IF at IS NOT NULL AND NEW.exposed_at < at THEN
        RAISE EXCEPTION 'EXPOSURE_BEFORE_ASSIGNMENT: exposure % is before its assignment', NEW.exposure_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- Eligibility is decided from pre-assignment facts only: internal accounts are never randomised.
CREATE OR REPLACE FUNCTION ps_assignment_eligible() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM accounts WHERE account_id = NEW.unit_id AND internal) THEN
        RAISE EXCEPTION 'INELIGIBLE_UNIT: internal account % is not randomised', NEW.unit_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['events', 'event_properties', 'identity_links', 'sessions', 'assignments', 'exposures',
                             'metric_observations', 'analysis_plans', 'analysis_runs', 'funnel_definitions',
                             'guardrail_reviews', 'decisions', 'audit_events', 'rejected_records']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_immutable') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION ps_forbid_mutation()',
                           t || '_immutable', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION ps_forbid_mutation()',
                           t || '_no_truncate', t);
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'exposures_not_early') THEN
        CREATE TRIGGER exposures_not_early BEFORE INSERT ON exposures
            FOR EACH ROW EXECUTE FUNCTION ps_exposure_not_early();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'assignments_eligible') THEN
        CREATE TRIGGER assignments_eligible BEFORE INSERT ON assignments
            FOR EACH ROW EXECUTE FUNCTION ps_assignment_eligible();
    END IF;
END
$$;
