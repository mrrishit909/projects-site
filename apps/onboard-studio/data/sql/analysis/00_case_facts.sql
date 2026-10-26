-- 00: shared views and helper functions for the analysis queries (P02-ART-04). Run first; idempotent.
--
-- Method (contract D-01, D-05, D-06), deliberately different from data/sql/reference_metrics.sql:
--   * the effective working set of a calendar is a multirange: range_agg(working) minus range_agg(holiday)
--     (PostgreSQL 14+ tstzmultirange), so a weekend holiday subtracts nothing without a special case;
--   * business time of any instant range is the total length of (range * effective working set);
--   * eligible waiting intervals of a case are clipped to [opened_at, completed_at) and merged with range_agg
--     BEFORE they are measured or intersected (D-06), so overlapping waits are never double counted;
--   * seconds are exact numeric; hours = seconds / 3600 only when a result is displayed.
-- Population: the rows that survived ingest (rejected cases and their child rows are not in the tables; they are in
-- rejected_records, see 08). Cases are open when completed_at IS NULL; completed-case metrics ignore them.

CREATE OR REPLACE VIEW os_calendar_effective AS
SELECT calendar_id,
       COALESCE(range_agg(tstzrange(starts_at, ends_at)) FILTER (WHERE kind = 'working'), '{}'::tstzmultirange)
     - COALESCE(range_agg(tstzrange(starts_at, ends_at)) FILTER (WHERE kind = 'holiday'), '{}'::tstzmultirange) AS eff
  FROM calendar_intervals
 GROUP BY calendar_id;

-- Seconds of a multirange that fall inside the calendar's effective working set.
CREATE OR REPLACE FUNCTION os_overlap_seconds(mr tstzmultirange, cal text) RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(sum(EXTRACT(EPOCH FROM (upper(r) - lower(r)))), 0)
      FROM unnest(mr * (SELECT eff FROM os_calendar_effective WHERE calendar_id = cal)) AS r
$$;

-- Business seconds between two instants (0 when hi <= lo or either is NULL).
CREATE OR REPLACE FUNCTION os_business_seconds(lo timestamptz, hi timestamptz, cal text) RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN lo IS NULL OR hi IS NULL OR hi <= lo THEN 0
                ELSE os_overlap_seconds(tstzmultirange(tstzrange(lo, hi)), cal) END
$$;

-- One row per case. *_s columns are exact seconds; NULL for open cases (no completion instant).
CREATE OR REPLACE VIEW os_case_facts AS
WITH base AS (
    SELECT c.case_id, c.organization_id, o.segment, o.region, c.workflow_version_id, wv.version_number,
           c.status, c.opened_at, c.completed_at, r.business_minutes, r.pause_policy, r.calendar_id
      FROM cases c
      JOIN organizations o USING (organization_id)
      JOIN workflow_versions wv USING (workflow_version_id)
      JOIN sla_rules r USING (workflow_version_id)
), clipped AS (
    SELECT b.case_id, w.reason_code,
           GREATEST(w.starts_at, b.opened_at) AS lo,
           LEAST(COALESCE(w.ends_at, b.completed_at), b.completed_at) AS hi
      FROM base b
      JOIN waiting_intervals w ON w.case_id = b.case_id AND w.reason_code = ANY (b.pause_policy)
     WHERE b.completed_at IS NOT NULL
), pauses AS (
    SELECT case_id, range_agg(tstzrange(lo, hi)) AS mr
      FROM clipped WHERE hi > lo GROUP BY case_id
), handoffs AS (
    SELECT si.case_id, sum(a.n - 1) AS handoffs
      FROM (SELECT step_instance_id, count(DISTINCT (assignee_id, assigned_at)) AS n
              FROM assignments GROUP BY step_instance_id) a
      JOIN step_instances si USING (step_instance_id)
     GROUP BY si.case_id
), measured AS (
    SELECT b.*, COALESCE(h.handoffs, 0) AS handoffs, p.mr AS pause_mr,
           CASE WHEN b.completed_at IS NOT NULL THEN EXTRACT(EPOCH FROM (b.completed_at - b.opened_at)) END AS calendar_s,
           CASE WHEN b.completed_at IS NOT NULL
                THEN os_overlap_seconds(tstzmultirange(tstzrange(b.opened_at, b.completed_at)), b.calendar_id) END AS business_s,
           CASE WHEN b.completed_at IS NOT NULL THEN
                COALESCE((SELECT sum(EXTRACT(EPOCH FROM (upper(r) - lower(r)))) FROM unnest(p.mr) r), 0) END AS paused_s,
           CASE WHEN b.completed_at IS NOT NULL AND p.mr IS NOT NULL THEN os_overlap_seconds(p.mr, b.calendar_id)
                WHEN b.completed_at IS NOT NULL THEN 0 END AS paused_business_s
      FROM base b
      LEFT JOIN pauses p USING (case_id)
      LEFT JOIN handoffs h USING (case_id)
)
SELECT case_id, organization_id, segment, region, workflow_version_id, version_number, status, opened_at, completed_at,
       date_trunc('month', opened_at AT TIME ZONE 'UTC')::date AS opened_month,
       business_minutes, pause_policy, calendar_id, handoffs,
       calendar_s, business_s, paused_s, paused_business_s,
       CASE WHEN completed_at IS NOT NULL THEN GREATEST(0, business_s - paused_business_s) END AS active_s,
       CASE WHEN completed_at IS NOT NULL THEN GREATEST(0, business_s - paused_business_s) <= business_minutes * 60 END AS within_sla
  FROM measured;
