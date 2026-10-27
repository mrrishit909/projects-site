-- P10-ART-04 investigation 03: precision, recall and risk lift at the three declared capacities, contact budgets, and the HYPOTHETICAL expected values on both populations
-- (D-03 P10-MET-02/03/07/08/09; D-09 R10-04). Capacities K = 5, 10, 20 (scenarios sc-001..sc-003) were fixed on validation before any outcome (D-G08).
-- Two populations, never mixed: (a) the 1,513-row TEST table of the full world, where outcomes are known, ranked by probability descending, then account_id ascending,
-- then the earlier cutoff (the union rule of D-08); (b) the 2026-09-01 cutoff, where every outcome is still censored: the 97 scored accounts of the published
-- 200-account cohort (computed here from predictions) and the 1,241 scored accounts of the whole 2,400-account world (published in cutoff_aggregates.json,
-- art_economics_full_world; it cannot be recomputed from the cohort). A risk ranking is not a treatment effect: every expected value is assumption-based and labelled hypothetical.
-- @@ test_population_at_k
WITH m AS (
    SELECT 1 AS ord, 'random_baseline' AS model, account_id, cutoff_index, p_random_baseline AS p, churned AS y FROM art_test_table
    UNION ALL SELECT 2, 'business_rule', account_id, cutoff_index, p_business_rule, churned FROM art_test_table
    UNION ALL SELECT 3, 'logistic_regression (Platt)', account_id, cutoff_index, p_logistic_calibrated, churned FROM art_test_table
    UNION ALL SELECT 4, 'prevalence_baseline', account_id, cutoff_index, p_prevalence_baseline, churned FROM art_test_table
),
r AS (SELECT m.*, row_number() OVER (PARTITION BY ord ORDER BY p DESC, account_id ASC, cutoff_index ASC) AS rk FROM m),
ties AS (SELECT r.ord, k2.capacity, (SELECT count(*) FROM r r2 WHERE r2.ord = r.ord AND r2.p = r.p) > 1 AS tie_group_has_more_than_one_row,
                (SELECT count(*) FROM r r3 WHERE r3.ord = r.ord AND r3.p = r.p AND r3.rk <= k2.capacity) <> (SELECT count(*) FROM r r4 WHERE r4.ord = r.ord AND r4.p = r.p) AS tie_split_at_k
         FROM r JOIN (VALUES (5), (10), (20)) AS k2(capacity) ON r.rk = k2.capacity),
tot AS (SELECT ord, sum(y) AS pos, count(*) AS n FROM m GROUP BY ord),
k AS (SELECT * FROM (VALUES ('sc-001', 5), ('sc-002', 10), ('sc-003', 20)) AS v(scenario_id, capacity))
SELECT r.model, k.scenario_id, k.capacity, tot.n AS evaluated_rows, tot.pos AS positives,
       sum(r.y) FILTER (WHERE r.rk <= k.capacity) AS churners_in_top_k,
       round(sum(r.y) FILTER (WHERE r.rk <= k.capacity)::numeric / k.capacity, 6) AS precision_at_k,
       round(sum(r.y) FILTER (WHERE r.rk <= k.capacity)::numeric / tot.pos, 6) AS recall_at_k,
       round((sum(r.y) FILTER (WHERE r.rk <= k.capacity)::numeric / k.capacity) / (tot.pos::numeric / tot.n), 6) AS risk_lift_at_k,
       (SELECT t.tie_split_at_k FROM ties t WHERE t.ord = r.ord AND t.capacity = k.capacity) AS tie_split_at_k,
       'test table: 1,513 mature eligible rows of the full world (outcomes known)' AS population
FROM r JOIN tot USING (ord) CROSS JOIN k GROUP BY r.ord, r.model, k.scenario_id, k.capacity, tot.n, tot.pos ORDER BY r.ord, k.capacity;
-- @@ cohort_economics
WITH sc AS (SELECT * FROM intervention_scenarios),
pa AS (SELECT max(pc.prediction_at) AS prediction_at FROM predictions pr JOIN prediction_cutoffs pc USING (cutoff_id)),   -- the latest scored cutoff: the queue's cutoff (the stored draft rows carry no instant)
scored AS (
    SELECT pc.account_id, pr.probability AS p
    FROM predictions pr JOIN prediction_cutoffs pc USING (cutoff_id), pa
    WHERE pr.model_name = 'logistic_regression' AND pc.prediction_at = pa.prediction_at
),
ranked AS (SELECT s.*, row_number() OVER (ORDER BY p DESC, account_id ASC) AS rk FROM scored s),
tot AS (SELECT count(*) AS n FROM scored)
SELECT sc.scenario_id, sc.capacity, tot.n AS scored_accounts, sc.contact_cost, sc.assumed_effect, sc.margin_value,
       count(*) FILTER (WHERE r.rk <= sc.capacity) AS selected_accounts,
       round(sc.contact_cost * sc.capacity, 2) AS contact_budget,
       round(sum(r.p * sc.assumed_effect * sc.margin_value - sc.contact_cost) FILTER (WHERE r.rk <= sc.capacity), 2) AS expected_value,
       (SELECT count(*) FROM outreach_events o WHERE o.scenario_id = sc.scenario_id) AS stored_draft_queue_rows,
       (SELECT count(*) FROM outreach_events o JOIN ranked r2 USING (account_id) WHERE o.scenario_id = sc.scenario_id AND r2.rk <= sc.capacity) AS stored_rows_in_my_top_k,
       'hypothetical' AS label, '97 scored accounts of the published cohort at 2026-09-01 (outcomes censored)' AS population
FROM sc CROSS JOIN tot JOIN ranked r ON true GROUP BY sc.scenario_id, sc.capacity, tot.n, sc.contact_cost, sc.assumed_effect, sc.margin_value ORDER BY sc.capacity;
-- @@ both_populations
WITH sc AS (SELECT * FROM intervention_scenarios),
scored AS (
    SELECT pc.account_id, pr.probability AS p
    FROM predictions pr JOIN prediction_cutoffs pc USING (cutoff_id)
    WHERE pr.model_name = 'logistic_regression' AND pc.prediction_at = (SELECT max(pc2.prediction_at) FROM predictions p2 JOIN prediction_cutoffs pc2 USING (cutoff_id))
),
ranked AS (SELECT s.*, row_number() OVER (ORDER BY p DESC, account_id ASC) AS rk FROM scored s),
coh AS (
    SELECT sc.scenario_id, count(DISTINCT r.account_id) AS scored,
           round(sum(r.p * sc.assumed_effect * sc.margin_value - sc.contact_cost) FILTER (WHERE r.rk <= sc.capacity), 2) AS ev
    FROM sc CROSS JOIN ranked r GROUP BY sc.scenario_id, sc.capacity
)
SELECT sc.scenario_id, sc.capacity, round(sc.contact_cost * sc.capacity, 2) AS contact_budget,
       coh.scored AS cohort_scored_accounts, coh.ev AS cohort_expected_value,
       w.scored_accounts AS world_scored_accounts, w.expected_value AS world_expected_value, round(w.contact_budget, 2) AS world_contact_budget,
       (w.expected_value > 0) AS world_value_positive, (coh.ev > 0) AS cohort_value_positive,
       'hypothetical' AS label, (w.label = 'hypothetical') AS world_label_is_hypothetical
FROM sc JOIN coh USING (scenario_id) JOIN art_economics_full_world w USING (scenario_id) ORDER BY sc.capacity;
-- @@ censored_at_the_queue_cutoff
-- precision and recall of the queues cannot be measured at the cutoff they are drawn for: every row of 2026-09-01 is still censored at the as-of
SELECT pc.prediction_at, count(*) AS cohort_cutoff_rows, count(*) FILTER (WHERE l.mature) AS mature_rows, count(*) FILTER (WHERE NOT l.mature) AS censored_rows
FROM prediction_cutoffs pc JOIN labels l USING (cutoff_id) WHERE pc.prediction_at = (SELECT max(pc2.prediction_at) FROM predictions p2 JOIN prediction_cutoffs pc2 USING (cutoff_id)) GROUP BY pc.prediction_at;
