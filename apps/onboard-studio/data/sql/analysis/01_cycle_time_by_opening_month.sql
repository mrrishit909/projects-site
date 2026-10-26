-- 01: calendar vs business cycle time by month of opening (P02-MET-01, P02-MET-02, P02-MET-04; contract D-01).
-- Completed cases only, grouped by the UTC month of opened_at. Means are exact (seconds summed, then divided).
-- cal_to_bus = mean calendar hours / mean business hours: how much longer a case looks on a wall clock than on the
-- working calendar. TOTAL is the mean over all completed cases and is reconciled in run_all.py against
-- data/sql/reference_metrics.sql and the Python domain.
WITH done AS (SELECT * FROM os_case_facts WHERE completed_at IS NOT NULL),
rows AS (
    SELECT to_char(opened_month, 'YYYY-MM') AS period, 0 AS ord, calendar_s, business_s, active_s, within_sla FROM done
    UNION ALL
    SELECT 'TOTAL', 1, calendar_s, business_s, active_s, within_sla FROM done)
SELECT period,
       count(*)::int                                          AS completed_cases,
       round(avg(calendar_s) / 3600, 4)                       AS calendar_h,
       round(avg(business_s) / 3600, 4)                       AS business_h,
       round(avg(calendar_s) / NULLIF(avg(business_s), 0), 2) AS cal_to_bus,
       round(avg(active_s) / 3600, 4)                         AS active_h
  FROM rows
 GROUP BY period, ord
 ORDER BY ord, period;
