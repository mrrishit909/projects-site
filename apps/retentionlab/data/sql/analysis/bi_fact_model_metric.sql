-- P10-ART-06 fact: average precision and Brier score per model on the test population (grain: model); the margins are met BY CONSTRUCTION (D-G02).
WITH m AS (
    SELECT 'random_baseline' AS model_key, account_id, p_random_baseline AS p, churned AS y FROM art_test_table
    UNION ALL SELECT 'business_rule', account_id, p_business_rule, churned FROM art_test_table
    UNION ALL SELECT 'logistic_regression', account_id, p_logistic_calibrated, churned FROM art_test_table
    UNION ALL SELECT 'prevalence_baseline', account_id, p_prevalence_baseline, churned FROM art_test_table
    UNION ALL SELECT 'logistic_uncalibrated', account_id, p_logistic_uncalibrated, churned FROM art_test_table
),
g AS (SELECT model_key, p, sum(y) AS tp_g, count(*) AS n_g FROM m GROUP BY model_key, p),
c AS (SELECT g.*, sum(tp_g) OVER (PARTITION BY model_key ORDER BY p DESC) AS tp, sum(n_g) OVER (PARTITION BY model_key ORDER BY p DESC) AS n_cum, sum(tp_g) OVER (PARTITION BY model_key) AS pos FROM g),
ap AS (SELECT model_key, round(sum(tp_g::numeric / pos * tp / n_cum), 6) AS average_precision FROM c GROUP BY model_key)
SELECT 'test_world' AS population_key, m.model_key, count(*) AS evaluated_rows, count(DISTINCT m.account_id) AS distinct_accounts, sum(m.y) AS positive_rows,
       round(sum(m.y)::numeric / count(*), 6) AS prevalence, ap.average_precision, round(sum((m.p - m.y) ^ 2) / count(*), 6) AS brier_score, round(avg(m.p), 6) AS mean_probability,
       'met by construction (D-G02): a property of the synthetic world, not evidence about real accounts' AS interpretation
FROM m JOIN ap USING (model_key) GROUP BY m.model_key, ap.average_precision
ORDER BY CASE m.model_key WHEN 'random_baseline' THEN 1 WHEN 'business_rule' THEN 2 WHEN 'logistic_regression' THEN 3 WHEN 'prevalence_baseline' THEN 4 ELSE 5 END;
