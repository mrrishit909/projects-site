-- P10-ART-06 fact: counts per monthly cutoff and population (grain: population x cutoff). cohort_200 is rebuilt from the loaded entity tables; world_2400 is the published aggregate.
WITH coh AS (
    SELECT 'cohort_200' AS population_key, pc.prediction_at, count(*) AS cutoff_rows, count(fr.feature_row_id) AS eligible,
           count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND l.mature) AS mature, count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND NOT l.mature) AS censored,
           count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND l.churned) AS churned
    FROM prediction_cutoffs pc LEFT JOIN feature_rows fr USING (cutoff_id) LEFT JOIN labels l USING (cutoff_id) GROUP BY pc.prediction_at
),
wld AS (SELECT 'world_2400' AS population_key, prediction_at, cutoff_rows, eligible, mature, censored, churned FROM art_cutoff_aggregate)
SELECT x.population_key, x.prediction_at, x.cutoff_rows, x.eligible, x.mature, x.censored, x.churned, round(x.censored::numeric / NULLIF(x.eligible, 0), 6) AS censored_share,
       round(x.churned::numeric / NULLIF(x.mature, 0), 6) AS mature_churn_rate
FROM (SELECT * FROM coh UNION ALL SELECT * FROM wld) x ORDER BY CASE x.population_key WHEN 'cohort_200' THEN 1 ELSE 2 END, x.prediction_at;
