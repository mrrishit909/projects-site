-- Independent SQL recomputation of the golden duration metrics (P02-GOLD-01, contract D-01, D-09).
-- Shares no code with the Python domain: plain interval-overlap arithmetic over calendar_intervals,
-- with no generate_series. One output row, hours as text with 4 decimals, means over completed cases that
-- have an SLA rule whose calendar has at least one working interval (D-09; the others are counted in
-- sla_unevaluated_cases and left out of every mean and of the SLA denominator).
--
--   overlap(range, interval)  = max(0, min(range_end, interval_end) - max(range_start, interval_start))
--   business(range)           = sum over 'working' intervals of overlap
--                               - sum over (working, holiday) pairs of the three-way overlap
--                                 (a holiday that touches no working interval subtracts nothing)
--
-- Exactness (Q-03): every per-case figure is kept in exact SECONDS; a metric is SUM(seconds) divided ONCE by
-- (3600 * cases) in numeric and rounded half-up to 4 decimals, so a mean that lands exactly on a tie
-- (0.00005 h -> 0.0001) rounds like the domain. Nothing is divided per case before averaging.
-- Merge rule (D-06): the pause-eligible waiting intervals of a case are clipped to [opened_at, completed_at) and
-- merged (gaps and islands: a row starts a new island when it begins after every earlier row ended; touching
-- intervals join) before deduction, so overlapping waits are never counted twice.
-- Assumes the 'working' intervals of a calendar do not overlap each other, nor do its 'holiday' intervals.
-- Pause eligibility is read from sla_rules.pause_policy; to test the "not eligible" state, set it to '{}'.
WITH rated AS (
    SELECT c.case_id, c.opened_at AS lo, c.completed_at AS hi,
           r.business_minutes, r.calendar_id, r.pause_policy,
           EXISTS (SELECT 1 FROM calendar_intervals k
                    WHERE k.calendar_id = r.calendar_id AND k.kind = 'working') AS has_working
      FROM cases c
      JOIN sla_rules r ON r.workflow_version_id = c.workflow_version_id
     WHERE c.completed_at IS NOT NULL
),
done AS (SELECT * FROM rated WHERE has_working),
pauses AS (
    SELECT d.case_id, d.calendar_id,
           GREATEST(w.starts_at, d.lo) AS lo,
           LEAST(COALESCE(w.ends_at, d.hi), d.hi) AS hi
      FROM done d
      JOIN waiting_intervals w ON w.case_id = d.case_id AND w.reason_code = ANY (d.pause_policy)
),
live AS (SELECT * FROM pauses WHERE hi > lo),
marked AS (
    SELECT *,
           CASE WHEN lo <= MAX(hi) OVER (PARTITION BY case_id ORDER BY lo, hi
                                         ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
                THEN 0 ELSE 1 END AS new_island
      FROM live
),
numbered AS (
    SELECT *, SUM(new_island) OVER (PARTITION BY case_id ORDER BY lo, hi ROWS UNBOUNDED PRECEDING) AS island
      FROM marked
),
islands AS (
    SELECT case_id, calendar_id, island, MIN(lo) AS lo, MAX(hi) AS hi
      FROM numbered
     GROUP BY case_id, calendar_id, island
),
ranges AS (
    SELECT case_id, 'case'::text AS kind, lo, hi, calendar_id FROM done
    UNION ALL
    SELECT case_id, 'pause'::text, lo, hi, calendar_id FROM islands
),
secs AS (
    SELECT r.case_id, r.kind,
           EXTRACT(EPOCH FROM (r.hi - r.lo))::numeric AS cal_s,
           (COALESCE((SELECT SUM(GREATEST(0, EXTRACT(EPOCH FROM (LEAST(r.hi, w.ends_at) - GREATEST(r.lo, w.starts_at)))))
                        FROM calendar_intervals w
                       WHERE w.calendar_id = r.calendar_id AND w.kind = 'working'), 0)
          - COALESCE((SELECT SUM(GREATEST(0, EXTRACT(EPOCH FROM (LEAST(r.hi, w.ends_at, h.ends_at)
                                                                  - GREATEST(r.lo, w.starts_at, h.starts_at)))))
                        FROM calendar_intervals w
                        JOIN calendar_intervals h ON h.calendar_id = w.calendar_id AND h.kind = 'holiday'
                       WHERE w.calendar_id = r.calendar_id AND w.kind = 'working'), 0))::numeric AS bus_s
      FROM ranges r
),
per_case AS (
    SELECT d.case_id, d.business_minutes,
           cs.cal_s, cs.bus_s,
           COALESCE(SUM(p.cal_s), 0) AS paused_s,
           COALESCE(SUM(p.bus_s), 0) AS paused_business_s
      FROM done d
      JOIN secs cs ON cs.case_id = d.case_id AND cs.kind = 'case'
      LEFT JOIN secs p ON p.case_id = d.case_id AND p.kind = 'pause'
     GROUP BY d.case_id, d.business_minutes, cs.cal_s, cs.bus_s
),
active AS (
    SELECT *, GREATEST(0, bus_s - paused_business_s) AS active_s FROM per_case
)
SELECT count(*)::int                                                              AS completed_eligible_cases,
       round(SUM(cal_s) / NULLIF(3600 * count(*), 0), 4)::text                     AS calendar_cycle_time_hours,
       round(SUM(bus_s) / NULLIF(3600 * count(*), 0), 4)::text                     AS business_cycle_time_hours,
       round(SUM(paused_s) / NULLIF(3600 * count(*), 0), 4)::text                  AS paused_time_hours,
       round(SUM(paused_business_s) / NULLIF(3600 * count(*), 0), 4)::text         AS paused_business_overlap_hours,
       round(SUM(active_s) / NULLIF(3600 * count(*), 0), 4)::text                  AS active_elapsed_hours,
       (count(*) FILTER (WHERE active_s <= business_minutes * 60))::int            AS within_sla_cases,
       (SELECT count(*)::int FROM rated WHERE NOT has_working)                     AS sla_unevaluated_cases
  FROM active;
