-- 06: paused time by reason and region (P02-MET-03, P02-DOMAIN-03; D-01, D-06).
-- Lens 'reason_region': every waiting interval of a completed case, clipped to the case span. waits = interval count,
-- wait_h = mean wall-clock hours per wait, wait_business_h = mean business hours per wait. 'in_pause_policy' says whether
-- the case's SLA rule lists the reason (both reasons are listed in the snapshot, so all are deducted from active time).
-- Lens 'region': the contract's paused_time_hours per completed case, i.e. eligible waits merged per case first (D-06),
-- averaged over the region's completed cases; cases_with_wait counts cases that have at least one eligible wait.
WITH done AS (SELECT * FROM os_case_facts WHERE completed_at IS NOT NULL),
w AS (
    SELECT d.region, x.reason_code, (x.reason_code = ANY (d.pause_policy)) AS in_pause_policy, d.calendar_id,
           GREATEST(x.starts_at, d.opened_at) AS lo, LEAST(COALESCE(x.ends_at, d.completed_at), d.completed_at) AS hi
      FROM done d JOIN waiting_intervals x USING (case_id)),
wc AS (SELECT *, EXTRACT(EPOCH FROM (hi - lo)) AS s, os_business_seconds(lo, hi, calendar_id) AS bs FROM w WHERE hi > lo),
rr AS (
    SELECT 'reason_region' AS lens, reason_code AS reason, region, in_pause_policy::text AS in_pause_policy,
           count(*)::int AS waits, NULL::int AS completed_cases, NULL::int AS cases_with_wait,
           round(avg(s) / 3600, 4) AS wait_h, round(avg(bs) / 3600, 4) AS wait_business_h, NULL::numeric AS paused_h_per_case
      FROM wc GROUP BY reason_code, region, in_pause_policy
    UNION ALL
    SELECT 'region', 'ALL eligible', region, 'true', NULL, count(*)::int,
           count(*) FILTER (WHERE paused_s > 0)::int, NULL, NULL, round(avg(paused_s) / 3600, 4)
      FROM done GROUP BY region
    UNION ALL
    SELECT 'region', 'ALL eligible', 'ALL', 'true', NULL, count(*)::int,
           count(*) FILTER (WHERE paused_s > 0)::int, NULL, NULL, round(avg(paused_s) / 3600, 4)
      FROM done)
SELECT * FROM rr ORDER BY lens DESC, reason, (region = 'ALL'), region;
