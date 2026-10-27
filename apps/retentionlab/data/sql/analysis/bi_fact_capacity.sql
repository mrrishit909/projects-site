-- P10-ART-06 fact: the three capacities (grain: population x model x scenario). Ranking metrics exist only where outcomes are known (the test population); the economics exist
-- only for the 2026-09-01 queue (cohort_200 computed here, world_2400 as published), whose outcomes are censored. Every economics value is HYPOTHETICAL and assumption-based.
WITH m AS (
    SELECT 'random_baseline' AS model_key, account_id, cutoff_index, p_random_baseline AS p, churned AS y FROM art_test_table
    UNION ALL SELECT 'business_rule', account_id, cutoff_index, p_business_rule, churned FROM art_test_table
    UNION ALL SELECT 'logistic_regression', account_id, cutoff_index, p_logistic_calibrated, churned FROM art_test_table
    UNION ALL SELECT 'prevalence_baseline', account_id, cutoff_index, p_prevalence_baseline, churned FROM art_test_table
),
r AS (SELECT m.*, row_number() OVER (PARTITION BY model_key ORDER BY p DESC, account_id ASC, cutoff_index ASC) AS rk FROM m),
tot AS (SELECT model_key, sum(y) AS pos, count(*) AS n FROM m GROUP BY model_key),
sc AS (SELECT * FROM intervention_scenarios),
scored AS (
    SELECT pc.account_id, pr.probability AS p FROM predictions pr JOIN prediction_cutoffs pc USING (cutoff_id)
    WHERE pr.model_name = 'logistic_regression' AND pc.prediction_at = (SELECT max(pc2.prediction_at) FROM predictions p2 JOIN prediction_cutoffs pc2 USING (cutoff_id))
),
rq AS (SELECT s.*, row_number() OVER (ORDER BY p DESC, account_id ASC) AS rk FROM scored s),
test_rows AS (
    SELECT 'test_world' AS population_key, r.model_key, sc.scenario_id, sc.capacity, tot.n AS evaluated_rows, tot.pos AS positives, sum(r.y) FILTER (WHERE r.rk <= sc.capacity) AS churners_in_top_k,
           round(sum(r.y) FILTER (WHERE r.rk <= sc.capacity)::numeric / sc.capacity, 6) AS precision_at_k, round(sum(r.y) FILTER (WHERE r.rk <= sc.capacity)::numeric / tot.pos, 6) AS recall_at_k,
           round((sum(r.y) FILTER (WHERE r.rk <= sc.capacity)::numeric / sc.capacity) / (tot.pos::numeric / tot.n), 6) AS risk_lift_at_k,
           NULL::numeric AS contact_budget, NULL::numeric AS expected_value, 'outcomes known; economics not computed on this population' AS status
    FROM r JOIN tot USING (model_key) CROSS JOIN sc GROUP BY r.model_key, sc.scenario_id, sc.capacity, tot.n, tot.pos
),
cohort_rows AS (
    SELECT 'cohort_200' AS population_key, 'logistic_regression' AS model_key, sc.scenario_id, sc.capacity, (SELECT count(*) FROM scored) AS evaluated_rows, NULL::bigint AS positives, NULL::bigint AS churners_in_top_k,
           NULL::numeric AS precision_at_k, NULL::numeric AS recall_at_k, NULL::numeric AS risk_lift_at_k, round(sc.contact_cost * sc.capacity, 2) AS contact_budget,
           round(sum(rq.p * sc.assumed_effect * sc.margin_value - sc.contact_cost) FILTER (WHERE rq.rk <= sc.capacity), 2) AS expected_value,
           'HYPOTHETICAL expected value on the 97 scored accounts of the published cohort at 2026-09-01; outcomes censored, so precision and recall are not available' AS status
    FROM sc CROSS JOIN rq GROUP BY sc.scenario_id, sc.capacity, sc.contact_cost
),
world_rows AS (
    SELECT 'world_2400', 'logistic_regression', w.scenario_id, w.capacity, w.scored_accounts::bigint, NULL::bigint, NULL::bigint, NULL::numeric, NULL::numeric, NULL::numeric, round(w.contact_budget, 2), w.expected_value,
           'HYPOTHETICAL expected value on the 1,241 scored accounts of the whole synthetic world at 2026-09-01 (published aggregate); outcomes censored' FROM art_economics_full_world w
)
SELECT * FROM (SELECT * FROM test_rows UNION ALL SELECT * FROM cohort_rows UNION ALL SELECT * FROM world_rows) x
ORDER BY CASE population_key WHEN 'test_world' THEN 1 WHEN 'cohort_200' THEN 2 ELSE 3 END, CASE model_key WHEN 'random_baseline' THEN 1 WHEN 'business_rule' THEN 2 WHEN 'logistic_regression' THEN 3 ELSE 4 END, capacity;
