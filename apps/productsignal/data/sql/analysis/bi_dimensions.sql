-- bi_dimensions.sql: the dimension tables of the BI package (docs/bi-package.md, P06-ART-06). Needs 00_canonical_events.sql for none of them: dimensions read the reference tables only.
-- Written as CSV by run_all.py --bi-out. Instants are UTC with a Z; booleans are 0/1; no stored result, verdict or status is read.

-- @@ dim_account
SELECT account_id, plan, segment, timezone, CASE WHEN internal THEN 1 ELSE 0 END AS is_internal, to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
FROM accounts ORDER BY account_id COLLATE "C";

-- @@ dim_date
-- One row per UTC calendar date of the observation window (the generator's 26 weeks plus the as-of date): 2026-04-06 to 2026-10-05.
SELECT to_char(d, 'YYYYMMDD') AS date_key, d::date::text AS date, to_char(date_trunc('week', d), 'YYYY-MM-DD') AS week_start, to_char(d, 'YYYY-MM') AS month,
       to_char(d, 'FMDay') AS weekday, extract(isodow FROM d)::int AS iso_weekday
FROM generate_series('2026-04-06'::timestamp, '2026-10-05'::timestamp, interval '1 day') AS g (d) ORDER BY d;

-- @@ dim_experiment_version
SELECT v.experiment_version_id, v.name, v.unit_type, v.primary_metric, to_char(v.planned_end AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS planned_end,
       p.plan->'allocation'->>'control' AS allocation_control, p.plan->'allocation'->>'treatment' AS allocation_treatment, p.plan->>'z' AS z, p.plan->>'confidence' AS confidence,
       p.plan->'srm'->>'p_threshold' AS srm_p_threshold, p.plan->'srm'->>'min_expected_cell' AS srm_min_expected_cell, p.plan->'guardrail'->>'metric' AS guardrail_metric, (p.plan->'guardrail'->>'window_days')::int AS guardrail_window_days,
       to_char((p.plan->>'frozen_at')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS plan_frozen_at, p.config_hash
FROM experiment_versions v JOIN analysis_plans p ON p.experiment_version_id = v.experiment_version_id ORDER BY v.experiment_version_id COLLATE "C";

-- @@ dim_run
-- The five logged runs and the as-of read of each version (a read, not a logged run: prior_runs is empty). run_key is the slicer of the BI model.
SELECT run_key, experiment_version_id, run_kind, to_char(cutoff_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_at, (cutoff_at < planned_end)::int AS is_interim, prior_runs
FROM (
    SELECT r.analysis_id AS run_key, r.experiment_version_id, 'logged run' AS run_kind, r.cutoff_at, v.planned_end,
           (SELECT count(*) FROM analysis_runs r2 WHERE r2.experiment_version_id = r.experiment_version_id AND r2.created_at < r.created_at) AS prior_runs
    FROM analysis_runs r JOIN experiment_versions v ON v.experiment_version_id = r.experiment_version_id
  UNION ALL
    SELECT 'asof-' || v.experiment_version_id, v.experiment_version_id, 'as-of read', '2026-10-05T00:00:00Z'::timestamptz, v.planned_end, NULL FROM experiment_versions v
) z ORDER BY experiment_version_id COLLATE "C", cutoff_at, run_key COLLATE "C";

-- @@ dim_event_name
SELECT event_name, count(*) AS rows_in_log FROM events GROUP BY event_name ORDER BY event_name COLLATE "C";
