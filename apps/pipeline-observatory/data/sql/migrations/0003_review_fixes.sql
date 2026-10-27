-- Pipeline Observatory, schema v1 amendments of the review round R8 (docs/contracts.md D-09). Idempotent: every statement can run twice.

-- R8-02: the scope a run declares. The gate's scope_complete check judges every batch committed in [scope_from, run start); NULL = from the beginning.
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS scope_from TIMESTAMPTZ;

-- R8-12: overlap is judged against requests that are still requested or running; a settled request carries the instant it settled, and a request
-- the instant it was made, so a history can say what was running at the time.
ALTER TABLE backfill_requests ADD COLUMN IF NOT EXISTS requested_at TIMESTAMPTZ;
ALTER TABLE backfill_requests ADD COLUMN IF NOT EXISTS settled_at TIMESTAMPTZ;

-- R8-06: a page fetched again in a NEW session is recorded as 'refetch' (not 'ok', not 'cursor_loop').
ALTER TABLE fetch_log DROP CONSTRAINT IF EXISTS fetch_log_status_check;
ALTER TABLE fetch_log ADD CONSTRAINT fetch_log_status_check CHECK (status IN ('ok', 'rate_limited', 'refetch', 'cursor_loop'));

-- R8-15 (section 11): money columns carry six decimal places; the published form stays two (rounded half up when it is rendered).
ALTER TABLE model_outputs ALTER COLUMN amount TYPE NUMERIC(20, 6);
