-- P10-ART-06 BI dimensions: the small tables a BI model relates to the facts. Every dimension row is derived from the loaded database or states a constant of the contract.
-- @@ dim_population
SELECT * FROM (VALUES
    ('test_world', 'Test table of the full world', 'rows of the test range with a known outcome (4 cutoffs, 2026-02-01 .. 2026-05-01)', 442, 1513, 'known'),
    ('cohort_200', 'Published cohort', '200 uniformly sampled accounts with every record published; the economics queue is drawn from its 97 scored accounts at 2026-09-01', 200, NULL, 'mixed'),
    ('world_2400', 'Whole synthetic world', '2,400 accounts as built by the domain; only published aggregates are available (no row-level data)', 2400, NULL, 'mixed')
) AS v(population_key, population_name, description, accounts, evaluated_rows, outcomes) ORDER BY population_key COLLATE "C";
-- @@ dim_model
SELECT * FROM (VALUES
    ('random_baseline', 'Random baseline', 'baseline', false, 1, 'a seeded SHA-256 of the cutoff id; carries no information'),
    ('business_rule', 'Business rule', 'rule', false, 2, 'flags no usage in 30 days or a high-severity support event in 90 days; two observed rates'),
    ('logistic_regression', 'Logistic regression (Platt-calibrated)', 'learned', true, 3, 'the model whose margins are met by construction (D-G02)'),
    ('prevalence_baseline', 'Prevalence constant', 'baseline', false, 4, 'the training prevalence for every account; its average precision is the prevalence'),
    ('logistic_uncalibrated', 'Logistic regression (before Platt)', 'learned', false, 5, 'the same ranking before the Platt mapping')
) AS v(model_key, model_name, model_kind, is_calibrated, display_order, description) ORDER BY display_order;
-- @@ dim_cutoff
SELECT a.prediction_at, to_char(a.prediction_at, 'YYYY-MM') AS year_month, a.split_range, (a.split_range = 'test') AS is_test_cutoff,
       (a.prediction_at + interval '104 days') AS label_window_closes_at, (a.prediction_at + interval '104 days' <= d.as_of) AS matures_by_the_as_of,
       row_number() OVER (ORDER BY a.prediction_at) AS cutoff_number
FROM art_cutoff_aggregate a, (SELECT as_of FROM dataset_versions ORDER BY as_of DESC LIMIT 1) d ORDER BY a.prediction_at;
-- @@ dim_scenario
SELECT scenario_id, capacity, contact_cost, assumed_effect, margin_value, 'hypothetical' AS label, 'assumption-based: no randomised experiment supports the assumed effect' AS basis
FROM intervention_scenarios ORDER BY capacity;
-- @@ dim_segment
SELECT segment AS segment_key, count(*) AS test_rows FROM art_test_table GROUP BY segment ORDER BY segment COLLATE "C";
-- @@ dim_region
SELECT region AS region_key, count(*) AS test_rows FROM art_test_table GROUP BY region ORDER BY region COLLATE "C";
-- @@ dim_bin
SELECT g AS bin_index, round(g / 10.0, 6) AS lower_bound, round((g + 1) / 10.0, 6) AS upper_bound, (g = 9) AS closed_upper FROM generate_series(0, 9) AS g ORDER BY g;
