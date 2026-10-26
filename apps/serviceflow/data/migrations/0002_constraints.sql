-- ServiceFlow constraints, triggers and indexes (idempotent).
--
-- Deliberately NOT a trigger: "no two overlapping in-service intervals for one agent beyond max_concurrent".
-- Intervals are derived from the event log, and late arrivals are preserved with their own occurred_at (P04-FLOW-01),
-- so a closing event may be inserted AFTER the next start it precedes in time; a row trigger would reject a valid
-- out-of-order load. The rule is enforced by the application (domain ingest and commands C01/C03, serialised per agent
-- by a row lock) and by tests/test_adversarial.py (P04-TEST-04).

DO $$
DECLARE c record;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('queues_policy_ck',        'queues',        $c$CHECK (priority_policy IN ('fifo_within_priority', 'fifo'))$c$),
        ('agents_employment_ck',    'agents',        $c$CHECK (employment_type IN ('full_time', 'part_time', 'contractor'))$c$),
        ('agents_concurrency_ck',   'agents',        'CHECK (max_concurrent >= 1)'),
        ('agent_skills_prof_ck',    'agent_skills',  'CHECK (proficiency BETWEEN 1 AND 5)'),
        ('shifts_order_ck',         'shifts',        'CHECK (ends_at > starts_at)'),
        ('shifts_break_ck',         'shifts',        'CHECK (break_minutes >= 0)'),
        ('shifts_break_fit_ck',     'shifts',        'CHECK (break_minutes * 60 <= extract(epoch FROM (ends_at - starts_at)))'),
        ('shift_breaks_order_ck',   'shift_breaks',  'CHECK (ends_at > starts_at)'),
        ('sla_priority_ck',         'sla_policies',  $c$CHECK (priority IN ('P1', 'P2', 'P3'))$c$),
        ('sla_minutes_ck',          'sla_policies',  'CHECK (first_response_minutes > 0 AND resolution_minutes > 0)'),
        ('tickets_priority_ck',     'tickets',       $c$CHECK (priority IN ('P1', 'P2', 'P3'))$c$),
        ('events_type_ck',          'ticket_events', $c$CHECK (event_type IN ('created', 'queued', 'acknowledged_bot', 'service_started', 'replied_human', 'paused', 'resumed', 'transferred', 'resolved', 'reopened', 'abandoned'))$c$),
        ('events_agent_ck',         'ticket_events', $c$CHECK (event_type <> 'service_started' OR agent_id IS NOT NULL)$c$),
        -- D-02 / P04-TEST-01: automation is never a human reply.
        ('events_bot_reply_ck',     'ticket_events', $c$CHECK (event_type <> 'replied_human' OR (actor_id IS NOT NULL AND left(actor_id, 4) <> 'bot-'))$c$),
        ('surveys_score_ck',        'surveys',       'CHECK (score IS NULL OR score BETWEEN 1 AND 5)'),
        ('surveys_pair_ck',         'surveys',       'CHECK ((score IS NULL) = (response_at IS NULL))'),
        ('sim_runs_ck',             'simulation_runs', 'CHECK (warmup_minutes >= 0 AND horizon_minutes > 0 AND replications >= 1)'),
        ('sim_events_type_ck',      'simulation_events', $c$CHECK (event_type IN ('service_started', 'resolved'))$c$),
        ('raw_batches_status_ck',   'raw_batches',   $c$CHECK (status IN ('accepted', 'partial', 'rejected'))$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

-- Immutable and append-only: an event and an audit event are never edited or deleted (P04-FLOW-01).
CREATE OR REPLACE FUNCTION sf_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ticket_events_immutable ON ticket_events;
CREATE TRIGGER ticket_events_immutable BEFORE UPDATE OR DELETE ON ticket_events
    FOR EACH ROW EXECUTE FUNCTION sf_forbid_mutation();
DROP TRIGGER IF EXISTS ticket_events_no_truncate ON ticket_events;
CREATE TRIGGER ticket_events_no_truncate BEFORE TRUNCATE ON ticket_events
    FOR EACH STATEMENT EXECUTE FUNCTION sf_forbid_mutation();
DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION sf_forbid_mutation();
DROP TRIGGER IF EXISTS simulation_events_append_only ON simulation_events;
CREATE TRIGGER simulation_events_append_only BEFORE UPDATE OR DELETE ON simulation_events
    FOR EACH ROW EXECUTE FUNCTION sf_forbid_mutation();

-- P04-FLOW-04 / P04-TEST-08: the arrival instant survives every transfer; only the queue may change.
CREATE OR REPLACE FUNCTION sf_arrival_fixed() RETURNS trigger AS $$
BEGIN
    IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'ARRIVAL_IMMUTABLE: ticket % keeps its arrival instant', OLD.ticket_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tickets_arrival_fixed ON tickets;
CREATE TRIGGER tickets_arrival_fixed BEFORE UPDATE OF created_at ON tickets
    FOR EACH ROW EXECUTE FUNCTION sf_arrival_fixed();
