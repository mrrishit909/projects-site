-- Independent SQL recomputation of the golden duration metrics (P02-GOLD-01, contract D-01).
-- Shares no code with the Python domain: plain interval-overlap arithmetic over calendar_intervals,
-- with no generate_series. One output row, hours as text with 4 decimals, means over completed cases that
-- have an SLA rule.
--
--   overlap(range, interval)  = max(0, min(range_end, interval_end) - max(range_start, interval_start))
--   business(range)           = sum over 'working' intervals of overlap
--                               - sum over (working, holiday) pairs of the three-way overlap
--                                 (a holiday that touches no working interval subtracts nothing)
--
-- Assumes the 'working' intervals of a calendar do not overlap each other, nor do its 'holiday' intervals,
-- and that eligible waiting intervals of one case do not overlap each other (the Python domain merges them).
-- Pause eligibility is read from sla_rules.pause_policy; to test the "not eligible" state, set it to '{}'.
-- Waiting intervals are clipped to the case's [opened_at, completed_at) like the domain does.
WITH done AS (
    SELECT c.case_id, c.opened_at AS lo, c.completed_at AS hi,
           r.business_minutes, r.calendar_id, r.pause_policy
      FROM cases c
      JOIN sla_rules r ON r.workflow_version_id = c.workflow_version_id
     WHERE c.completed_at IS NOT NULL
),
pauses AS (
    SELECT d.case_id, d.calendar_id,
           GREATEST(w.starts_at, d.lo) AS lo,
           LEAST(COALESCE(w.ends_at, d.hi), d.hi) AS hi
      FROM done d
      JOIN waiting_intervals w ON w.case_id = d.case_id AND w.reason_code = ANY (d.pause_policy)
),
ranges AS (
    SELECT case_id, 'case'::text AS kind, lo, hi, calendar_id FROM done
    UNION ALL
    SELECT case_id, 'pause'::text, lo, hi, calendar_id FROM pauses WHERE hi > lo
),
secs AS (
    SELECT r.case_id, r.kind,
           EXTRACT(EPOCH FROM (r.hi - r.lo)) AS cal_s,
           COALESCE((SELECT SUM(GREATEST(0, EXTRACT(EPOCH FROM (LEAST(r.hi, w.ends_at) - GREATEST(r.lo, w.starts_at)))))
                       FROM calendar_intervals w
                      WHERE w.calendar_id = r.calendar_id AND w.kind = 'working'), 0)
         - COALESCE((SELECT SUM(GREATEST(0, EXTRACT(EPOCH FROM (LEAST(r.hi, w.ends_at, h.ends_at)
                                                                 - GREATEST(r.lo, w.starts_at, h.starts_at)))))
                       FROM calendar_intervals w
                       JOIN calendar_intervals h ON h.calendar_id = w.calendar_id AND h.kind = 'holiday'
                      WHERE w.calendar_id = r.calendar_id AND w.kind = 'working'), 0) AS bus_s
      FROM ranges r
),
per_case AS (
    SELECT d.case_id, d.business_minutes,
           cs.cal_s / 3600 AS calendar_h,
           cs.bus_s / 3600 AS business_h,
           COALESCE(SUM(p.cal_s), 0) / 3600 AS paused_h,
           COALESCE(SUM(p.bus_s), 0) / 3600 AS paused_business_h
      FROM done d
      JOIN secs cs ON cs.case_id = d.case_id AND cs.kind = 'case'
      LEFT JOIN secs p ON p.case_id = d.case_id AND p.kind = 'pause'
     GROUP BY d.case_id, d.business_minutes, cs.cal_s, cs.bus_s
),
active AS (
    SELECT *, GREATEST(0, business_h - paused_business_h) AS active_h FROM per_case
)
SELECT count(*)::int                                          AS completed_eligible_cases,
       round(avg(calendar_h), 4)::text                        AS calendar_cycle_time_hours,
       round(avg(business_h), 4)::text                        AS business_cycle_time_hours,
       round(avg(paused_h), 4)::text                          AS paused_time_hours,
       round(avg(paused_business_h), 4)::text                 AS paused_business_overlap_hours,
       round(avg(active_h), 4)::text                          AS active_elapsed_hours,
       (count(*) FILTER (WHERE active_h * 60 <= business_minutes))::int AS within_sla_cases
  FROM active;
