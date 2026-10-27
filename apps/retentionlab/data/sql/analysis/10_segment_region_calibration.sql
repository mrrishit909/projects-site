-- P10-ART-04 investigation 10: calibration gaps by plan segment and by region on the test population (D-03 P10-MET-06, D-07 DR-02, D-09 R10-09).
-- Question: where does the Platt-calibrated logistic model under-predict churn most? Designed: the starter segment (an unobserved repricing on 2026-02-01 that no feature sees,
-- DR-02). NOT designed: the apac region's larger gap (-10.68 pp), a one-draw realisation of this seed (D-09 R10-09) - the instrumentation change was designed to move apac's usage
-- distribution, not its calibration. gap = (mean predicted - observed churn rate) x 100 percentage points, 2 places; negative = churn under-predicted.
-- Source: art_test_table (1,513 rows of the full world); small groups carry few churning rows, so no group gap is a precise estimate and no interval is given.
-- @@ by_segment
SELECT 'segment' AS dimension, segment AS grp, count(*) AS test_rows, sum(churned) AS churning_rows, round(avg(p_logistic_calibrated), 6) AS mean_predicted,
       round(sum(churned)::numeric / count(*), 6) AS observed_rate, round((avg(p_logistic_calibrated) - sum(churned)::numeric / count(*)) * 100, 2) AS gap_pp,
       round((avg(p_logistic_uncalibrated) - sum(churned)::numeric / count(*)) * 100, 2) AS gap_pp_before_platt
FROM art_test_table GROUP BY segment ORDER BY segment COLLATE "C";
-- @@ by_region
SELECT 'region' AS dimension, region AS grp, count(*) AS test_rows, sum(churned) AS churning_rows, round(avg(p_logistic_calibrated), 6) AS mean_predicted,
       round(sum(churned)::numeric / count(*), 6) AS observed_rate, round((avg(p_logistic_calibrated) - sum(churned)::numeric / count(*)) * 100, 2) AS gap_pp,
       round((avg(p_logistic_uncalibrated) - sum(churned)::numeric / count(*)) * 100, 2) AS gap_pp_before_platt
FROM art_test_table GROUP BY region ORDER BY region COLLATE "C";
-- @@ largest_gaps
WITH x AS (
    SELECT 'segment' AS dimension, segment AS grp, count(*) AS n, (avg(p_logistic_calibrated) - sum(churned)::numeric / count(*)) * 100 AS gap FROM art_test_table GROUP BY segment
    UNION ALL SELECT 'region', region, count(*), (avg(p_logistic_calibrated) - sum(churned)::numeric / count(*)) * 100 FROM art_test_table GROUP BY region
    UNION ALL SELECT 'overall', 'all test rows', count(*), (avg(p_logistic_calibrated) - avg(churned::numeric)) * 100 FROM art_test_table
),
r AS (SELECT x.*, row_number() OVER (PARTITION BY dimension ORDER BY gap ASC, grp COLLATE "C") AS rk FROM x)
SELECT dimension, grp AS most_negative_gap_group, n AS test_rows, round(gap, 2) AS gap_pp FROM r WHERE rk = 1 ORDER BY CASE dimension WHEN 'overall' THEN 1 WHEN 'segment' THEN 2 ELSE 3 END;
-- @@ starter_after_the_repricing
-- the starter gap by test cutoff (17 to 27 churning rows per cutoff: small groups, so each month's gap is noisy and no interval is given)
SELECT prediction_at, count(*) AS starter_rows, sum(churned) AS churning_rows, round(avg(p_logistic_calibrated), 6) AS mean_predicted,
       round(sum(churned)::numeric / count(*), 6) AS observed_rate, round((avg(p_logistic_calibrated) - sum(churned)::numeric / count(*)) * 100, 2) AS gap_pp
FROM art_test_table WHERE segment = 'starter' GROUP BY prediction_at ORDER BY prediction_at;
