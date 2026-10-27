-- bi_fact_run_assignment.sql: the experiment fact of the BI package (docs/bi-package.md): one row per (read, assignment) for the facts that existed by that read (D-08).
-- Needs 00_canonical_events.sql. Grain: ONE ROW PER ASSIGNMENT PER READ, where a read is a run_key of dim_run: the four v1 runs (an-001..an-004), v2's run (an-005) and the as-of
-- read of each version. An assignment is in a read when assigned_at <= the cutoff, so the first interim run has 155 rows and the cutoff slicer of the model is the D-08 rule.
-- Flags: mature_7d (signup + 7 x 24 h <= cutoff), activated_7d (an analysed `activated` at or after max(signup, assigned_at) inside the window, events received by the cutoff; empty when
-- not mature), exposed (exposed_at <= cutoff), guardrail_eligible (assigned_at + 7 x 24 h <= cutoff and mature), errored (an analysed `product_error` in [assigned_at, +7 x 24 h);
-- empty when not eligible), revenue_usd (subscriptions active or ended with starts_at inside the plan's revenue window and <= the cutoff; empty when not mature).
-- @@ fact_run_assignment
WITH reads (run_key, xv, c) AS (
    SELECT analysis_id, experiment_version_id, cutoff_at FROM analysis_runs
  UNION ALL
    SELECT 'asof-' || experiment_version_id, experiment_version_id, '2026-10-05T00:00:00Z'::timestamptz FROM experiment_versions
),
lbl AS (SELECT r.run_key, r.xv, r.c, p.label FROM reads r JOIN ps_cuts p ON p.c = r.c AND (p.label = r.run_key OR (r.run_key LIKE 'asof-%' AND p.label = 'as-of'))),
pl AS (SELECT experiment_version_id AS xv, (plan->'guardrail'->>'window_days')::int AS g_days, (plan->'revenue_window'->>'from')::timestamptz AS rev_from,
              (plan->'revenue_window'->>'to')::timestamptz AS rev_to FROM analysis_plans)
SELECT l.run_key, a.assignment_id, a.unit_id AS account_id, a.experiment_version_id, a.variant AS arm,
       to_char(a.assigned_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS assigned_at, to_char(sg.at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS signup_at,
       CASE WHEN sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= l.c THEN 1 ELSE 0 END AS mature_7d,
       CASE WHEN sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= l.c THEN
            CASE WHEN EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = l.c AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = a.unit_id AND e.at >= greatest(sg.at, a.assigned_at)
                              AND e.at < sg.at + make_interval(hours => 168)) THEN 1 ELSE 0 END END AS activated_7d,
       CASE WHEN EXISTS (SELECT 1 FROM exposures x WHERE x.assignment_id = a.assignment_id AND x.exposed_at <= l.c) THEN 1 ELSE 0 END AS exposed,
       CASE WHEN sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= l.c AND a.assigned_at + make_interval(hours => 24 * pl.g_days) <= l.c THEN 1 ELSE 0 END AS guardrail_eligible,
       CASE WHEN sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= l.c AND a.assigned_at + make_interval(hours => 24 * pl.g_days) <= l.c THEN
            CASE WHEN EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = l.c AND e.cls = 'analysed' AND e.name = 'product_error' AND e.acct = a.unit_id AND e.at >= a.assigned_at
                              AND e.at < a.assigned_at + make_interval(hours => 24 * pl.g_days)) THEN 1 ELSE 0 END END AS errored,
       CASE WHEN sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= l.c THEN
            coalesce((SELECT sum(s.amount_usd) FROM subscriptions s WHERE s.account_id = a.unit_id AND s.status IN ('active', 'ended') AND s.starts_at >= pl.rev_from AND s.starts_at < pl.rev_to
                      AND s.starts_at <= l.c), 0)::numeric(14,2) END AS revenue_usd
FROM lbl l JOIN pl ON pl.xv = l.xv JOIN assignments a ON a.experiment_version_id = l.xv AND a.assigned_at <= l.c LEFT JOIN ps_signup sg ON sg.c = l.c AND sg.acct = a.unit_id
ORDER BY l.run_key COLLATE "C", a.assignment_id COLLATE "C";
