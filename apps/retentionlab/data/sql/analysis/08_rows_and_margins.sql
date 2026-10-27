-- P10-ART-04 investigation 08: rows are not accounts, and the margins are met by construction (D-09 R10-06, R10-14; D-07 and D-G02 disclosures; P10-DOMAIN-04/05).
-- Question: how many distinct accounts stand behind the 1,513 test rows, and what are the model's margins over the baselines on the test population against the margins
-- DECLARED before the first run (D-G01: ap_over_rule 0.03, ap_over_random 0.05, brier_under_rule 0.002, brier_under_random 0.05)? D-G02 discloses that the engagement signal was
-- strengthened until those margins were met, so every "met" below is met BY CONSTRUCTION and is not evidence that such a model beats a simple rule on real accounts; the Brier margin
-- over the random baseline is uninformative (a uniform random score cannot do better than about one third) and the honest reference is the prevalence constant.
-- Source: art_test_table. Average precision as in investigation 01.
-- @@ rows_and_accounts
WITH per_account AS (SELECT account_id, count(*) AS rows_n, sum(churned) AS churned_rows FROM art_test_table GROUP BY account_id)
SELECT (SELECT count(*) FROM art_test_table) AS test_rows, count(*) AS distinct_accounts, (SELECT sum(churned) FROM art_test_table) AS churning_rows,
       count(*) FILTER (WHERE churned_rows > 0) AS churning_accounts,
       count(*) FILTER (WHERE rows_n = 1) AS accounts_with_1_row, count(*) FILTER (WHERE rows_n = 2) AS accounts_with_2_rows,
       count(*) FILTER (WHERE rows_n = 3) AS accounts_with_3_rows, count(*) FILTER (WHERE rows_n = 4) AS accounts_with_4_rows,
       count(*) FILTER (WHERE churned_rows > 1) AS accounts_churning_in_more_than_one_row,
       round((SELECT sum(churned) FROM art_test_table)::numeric / (SELECT count(*) FROM art_test_table), 6) AS prevalence_of_rows,
       round(count(*) FILTER (WHERE churned_rows > 0)::numeric / count(*), 6) AS share_of_accounts_with_a_churning_row
FROM per_account;
-- @@ margins
WITH m AS (
    SELECT 'random_baseline' AS model, p_random_baseline AS p, churned AS y FROM art_test_table
    UNION ALL SELECT 'business_rule', p_business_rule, churned FROM art_test_table
    UNION ALL SELECT 'logistic_regression', p_logistic_calibrated, churned FROM art_test_table
    UNION ALL SELECT 'prevalence_baseline', p_prevalence_baseline, churned FROM art_test_table
),
g AS (SELECT model, p, sum(y) AS tp_g, count(*) AS n_g FROM m GROUP BY model, p),
c AS (SELECT g.*, sum(tp_g) OVER (PARTITION BY model ORDER BY p DESC) AS tp, sum(n_g) OVER (PARTITION BY model ORDER BY p DESC) AS n_cum, sum(tp_g) OVER (PARTITION BY model) AS pos FROM g),
ap AS (SELECT model, sum(tp_g::numeric / pos * tp / n_cum) AS ap FROM c GROUP BY model),
br AS (SELECT model, sum((p - y) ^ 2) / count(*) AS brier FROM m GROUP BY model),
x AS (SELECT ap.model, round(ap.ap, 6) AS ap, round(br.brier, 6) AS brier FROM ap JOIN br USING (model)),
l AS (SELECT * FROM x WHERE model = 'logistic_regression')
SELECT d.margin, d.declared_before_the_first_run, d.against,
       CASE d.margin WHEN 'ap_over_rule' THEN l.ap - (SELECT ap FROM x WHERE model = 'business_rule')
                     WHEN 'ap_over_random' THEN l.ap - (SELECT ap FROM x WHERE model = 'random_baseline')
                     WHEN 'brier_under_rule' THEN (SELECT brier FROM x WHERE model = 'business_rule') - l.brier
                     WHEN 'brier_under_random' THEN (SELECT brier FROM x WHERE model = 'random_baseline') - l.brier
                     WHEN 'ap_over_prevalence_constant (reference)' THEN l.ap - (SELECT ap FROM x WHERE model = 'prevalence_baseline')
                     WHEN 'brier_under_prevalence_constant (reference)' THEN (SELECT brier FROM x WHERE model = 'prevalence_baseline') - l.brier END AS realised_margin,
       d.status
FROM l CROSS JOIN (VALUES (1, 'ap_over_rule', 0.030000, 'business_rule', 'met, by construction (D-G02)'),
                          (2, 'ap_over_random', 0.050000, 'random_baseline', 'met, by construction (D-G02)'),
                          (3, 'brier_under_rule', 0.002000, 'business_rule', 'met, by construction (D-G02)'),
                          (4, 'brier_under_random', 0.050000, 'random_baseline', 'met, by construction (D-G02); uninformative: a uniform random score cannot beat about 0.33'),
                          (5, 'ap_over_prevalence_constant (reference)', NULL, 'prevalence_baseline', 'reference, not a target'),
                          (6, 'brier_under_prevalence_constant (reference)', NULL, 'prevalence_baseline', 'reference, not a target')) AS d(ord, margin, declared_before_the_first_run, against, status)
ORDER BY d.ord;
-- @@ random_brier_is_uninformative
SELECT round(sum((p_random_baseline - churned) ^ 2) / count(*), 6) AS random_baseline_brier,
       round(sum((p_prevalence_baseline - churned) ^ 2) / count(*), 6) AS prevalence_constant_brier,
       round(avg(p_random_baseline), 6) AS random_baseline_mean_probability, round(avg(churned::numeric), 6) AS prevalence
FROM art_test_table;
