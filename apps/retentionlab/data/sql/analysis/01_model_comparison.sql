-- P10-ART-04 investigation 01: model comparison on the held-out test population (D-03 average precision and Brier, D-07 designed relationship DR-01).
-- Question: how do the four models rank and score the 1,513 mature eligible rows of the test range (cutoffs 2026-02-01 .. 2026-05-01, FULL world)?
-- Source: art_test_table (test_cohort.json). Average precision is the scikit-learn step form over DISTINCT probabilities (tied probabilities are one threshold);
-- Brier = mean((p - y)^2); both exact NUMERIC, rounded once, half away from zero, to 6 places. The Platt-calibrated logistic column stands for the logistic model;
-- the uncalibrated column is listed beside it. Rows are not accounts (D-09 R10-06): the row counts and the distinct accounts are both shown.
-- @@ models
WITH m AS (
    SELECT 1 AS ord, 'random_baseline' AS model, row_no, account_id, p_random_baseline AS p, churned AS y FROM art_test_table
    UNION ALL SELECT 2, 'business_rule', row_no, account_id, p_business_rule, churned FROM art_test_table
    UNION ALL SELECT 3, 'logistic_regression (Platt)', row_no, account_id, p_logistic_calibrated, churned FROM art_test_table
    UNION ALL SELECT 4, 'prevalence_baseline', row_no, account_id, p_prevalence_baseline, churned FROM art_test_table
    UNION ALL SELECT 5, 'logistic_regression (before Platt)', row_no, account_id, p_logistic_uncalibrated, churned FROM art_test_table
),
g AS (SELECT ord, model, p, sum(y) AS tp_g, count(*) AS n_g FROM m GROUP BY ord, model, p),
c AS (
    SELECT g.*, sum(tp_g) OVER (PARTITION BY ord ORDER BY p DESC) AS tp, sum(n_g) OVER (PARTITION BY ord ORDER BY p DESC) AS n_cum,
           sum(tp_g) OVER (PARTITION BY ord) AS pos
    FROM g
),
ap AS (SELECT ord, round(sum(tp_g::numeric / pos * tp / n_cum), 6) AS average_precision FROM c GROUP BY ord),
s AS (
    SELECT ord, model, count(*) AS test_rows, count(DISTINCT account_id) AS accounts, sum(y) AS positive_rows,
           count(DISTINCT account_id) FILTER (WHERE y = 1) AS positive_accounts,
           round(sum(y)::numeric / count(*), 6) AS prevalence, round(sum((p - y) ^ 2)::numeric / count(*), 6) AS brier_score,
           round(avg(p), 6) AS mean_probability
    FROM m GROUP BY ord, model
)
SELECT s.model, s.test_rows, s.accounts, s.positive_rows, s.positive_accounts, s.prevalence, ap.average_precision, s.brier_score, s.mean_probability
FROM s JOIN ap USING (ord) ORDER BY s.ord;
-- @@ per_cutoff
SELECT prediction_at, count(*) AS test_rows, sum(churned) AS positive_rows, round(sum(churned)::numeric / count(*), 6) AS prevalence,
       round(sum((p_logistic_calibrated - churned) ^ 2)::numeric / count(*), 6) AS logistic_brier
FROM art_test_table GROUP BY prediction_at ORDER BY prediction_at;
