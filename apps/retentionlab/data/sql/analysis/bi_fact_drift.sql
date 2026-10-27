-- P10-ART-06 fact: PSI of usage_events_30d against the 2026-02-01 cohort (grain: source x group x cutoff). 'published full world' rows are the 21-cutoff series (apac, other regions,
-- all accounts); 'recomputed from the test table' rows are the four test cutoffs for every region. A floored bin (a zero proportion replaced by 0.0001) is flagged; the 0.2 threshold is a diagnostic.
WITH g AS (
    SELECT 'all_accounts' AS grp, cutoff_index, prediction_at, usage_events_30d AS u FROM art_test_table
    UNION ALL SELECT 'other_regions', cutoff_index, prediction_at, usage_events_30d FROM art_test_table WHERE region <> 'apac'
    UNION ALL SELECT region, cutoff_index, prediction_at, usage_events_30d FROM art_test_table
),
grid AS (SELECT DISTINCT grp, cutoff_index, prediction_at, b FROM g, generate_series(0, 2) AS b),
cnt AS (
    SELECT grid.grp, grid.cutoff_index, grid.prediction_at, grid.b,
           count(g.u) FILTER (WHERE (grid.b = 0 AND g.u < 1) OR (grid.b = 1 AND g.u >= 1 AND g.u < 3) OR (grid.b = 2 AND g.u >= 3)) AS n
    FROM grid LEFT JOIN g ON g.grp = grid.grp AND g.cutoff_index = grid.cutoff_index GROUP BY grid.grp, grid.cutoff_index, grid.prediction_at, grid.b
),
p AS (SELECT c.*, r.n AS ref_n, sum(c.n) OVER (PARTITION BY c.grp, c.cutoff_index) AS cur_total, sum(r.n) OVER (PARTITION BY c.grp, c.cutoff_index) AS ref_total FROM cnt c JOIN cnt r ON r.grp = c.grp AND r.b = c.b AND r.cutoff_index = 0),
f AS (SELECT p.*, CASE WHEN n = 0 THEN 0.0001 ELSE n::numeric / cur_total END AS a_f, CASE WHEN ref_n = 0 THEN 0.0001 ELSE ref_n::numeric / ref_total END AS e_f FROM p),
rec AS (
    SELECT 'recomputed from the test table' AS source, grp, prediction_at, max(ref_total)::int AS reference_rows, max(cur_total)::int AS current_rows, round(sum((a_f - e_f) * ln(a_f / e_f)), 6) AS psi,
           (count(*) FILTER (WHERE ref_n = 0 OR n = 0))::int AS floored_bins, (sum((a_f - e_f) * ln(a_f / e_f)) > 0.2) AS exceeds_threshold
    FROM f GROUP BY grp, prediction_at
),
pub AS (SELECT 'published full world' AS source, grp, prediction_at, reference_rows, current_rows, psi, floored_bins, exceeds_threshold FROM art_drift_published)
SELECT * FROM (SELECT * FROM pub UNION ALL SELECT * FROM rec) x
ORDER BY CASE source WHEN 'published full world' THEN 1 ELSE 2 END, grp COLLATE "C", prediction_at;
