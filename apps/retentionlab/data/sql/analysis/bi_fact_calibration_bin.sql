-- P10-ART-06 fact: the reliability bins of the logistic model on the test population, with counts (grain: model x bin); an empty bin is a row with null measures, never dropped.
WITH v AS (
    SELECT 'logistic_regression' AS model_key, p_logistic_calibrated AS p, churned AS y FROM art_test_table
    UNION ALL SELECT 'logistic_uncalibrated', p_logistic_uncalibrated, churned FROM art_test_table
),
b AS (SELECT model_key, least(floor(p * 10)::int, 9) AS bin_index, count(*) AS n, sum(y) AS pos, sum(p) AS sp FROM v GROUP BY model_key, least(floor(p * 10)::int, 9)),
grid AS (SELECT m.model_key, g.bin_index FROM (VALUES ('logistic_regression'), ('logistic_uncalibrated')) AS m(model_key), generate_series(0, 9) AS g(bin_index))
SELECT 'test_world' AS population_key, grid.model_key, grid.bin_index, coalesce(b.n, 0) AS rows_in_bin, coalesce(b.pos, 0) AS churned_rows, (b.n IS NULL) AS empty_bin,
       round(b.sp / b.n, 6) AS mean_predicted, round(b.pos::numeric / b.n, 6) AS observed_rate, round((b.sp / b.n - b.pos::numeric / b.n) * 100, 2) AS gap_pp
FROM grid LEFT JOIN b USING (model_key, bin_index) ORDER BY CASE grid.model_key WHEN 'logistic_regression' THEN 1 ELSE 2 END, grid.bin_index;
