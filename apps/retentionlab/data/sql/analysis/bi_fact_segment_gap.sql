-- P10-ART-06 fact: calibration gap by plan segment and region on the test population (grain: dimension x group); negative = churn under-predicted. The apac gap is not a designed relationship (D-09 R10-09).
SELECT * FROM (SELECT 'test_world' AS population_key, 'segment' AS dimension, segment AS group_key, count(*) AS test_rows, sum(churned) AS churning_rows, round(avg(p_logistic_calibrated), 6) AS mean_predicted,
       round(sum(churned)::numeric / count(*), 6) AS observed_rate, round((avg(p_logistic_calibrated) - sum(churned)::numeric / count(*)) * 100, 2) AS gap_pp
FROM art_test_table GROUP BY segment
UNION ALL SELECT 'test_world', 'region', region, count(*), sum(churned), round(avg(p_logistic_calibrated), 6), round(sum(churned)::numeric / count(*), 6),
       round((avg(p_logistic_calibrated) - sum(churned)::numeric / count(*)) * 100, 2) FROM art_test_table GROUP BY region) x
ORDER BY dimension COLLATE "C", group_key COLLATE "C";
