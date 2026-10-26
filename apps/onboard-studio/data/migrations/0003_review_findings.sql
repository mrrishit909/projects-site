-- Review findings Q-01 and Q-05 (docs/contracts.md D-07, D-09). Idempotent.

-- Q-05: calendars are rows; sla_rules and calendar_intervals reference them. Created from the distinct calendar ids
-- already present, so a database migrated from 0001/0002 keeps working.
CREATE TABLE IF NOT EXISTS calendars (
    calendar_id TEXT PRIMARY KEY
);

INSERT INTO calendars (calendar_id)
SELECT calendar_id FROM calendar_intervals
UNION
SELECT calendar_id FROM sla_rules
ON CONFLICT DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sla_rules_calendar_fk') THEN
        ALTER TABLE sla_rules ADD CONSTRAINT sla_rules_calendar_fk
            FOREIGN KEY (calendar_id) REFERENCES calendars (calendar_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'calendar_intervals_calendar_fk') THEN
        ALTER TABLE calendar_intervals ADD CONSTRAINT calendar_intervals_calendar_fk
            FOREIGN KEY (calendar_id) REFERENCES calendars (calendar_id);
    END IF;
END
$$;

-- Q-01 / D-07: a case cannot complete before work recorded on it, and no event can be recorded after completion.
CREATE OR REPLACE FUNCTION os_case_completion_order() RETURNS trigger AS $$
DECLARE latest TIMESTAMPTZ;
BEGIN
    IF NEW.completed_at IS NOT NULL AND (TG_OP = 'INSERT' OR OLD.completed_at IS DISTINCT FROM NEW.completed_at) THEN
        SELECT max(occurred_at) INTO latest FROM case_events WHERE case_id = NEW.case_id;
        IF latest IS NOT NULL AND latest > NEW.completed_at THEN
            RAISE EXCEPTION 'case % cannot complete at % before its latest recorded event at %',
                NEW.case_id, NEW.completed_at, latest USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cases_completion_order ON cases;
CREATE TRIGGER cases_completion_order BEFORE INSERT OR UPDATE ON cases
    FOR EACH ROW EXECUTE FUNCTION os_case_completion_order();

CREATE OR REPLACE FUNCTION os_event_not_after_completion() RETURNS trigger AS $$
DECLARE done TIMESTAMPTZ;
BEGIN
    SELECT completed_at INTO done FROM cases WHERE case_id = NEW.case_id;
    IF done IS NOT NULL AND NEW.occurred_at > done THEN
        RAISE EXCEPTION 'case % completed at %; an event at % cannot follow the completion',
            NEW.case_id, done, NEW.occurred_at USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS case_events_not_after_completion ON case_events;
CREATE TRIGGER case_events_not_after_completion BEFORE INSERT OR UPDATE OF occurred_at, case_id ON case_events
    FOR EACH ROW EXECUTE FUNCTION os_event_not_after_completion();

-- Q-06: an idempotent replay is bound to the actor that first ran the command (NULL on rows from before this change).
ALTER TABLE command_results ADD COLUMN IF NOT EXISTS actor_id TEXT;
