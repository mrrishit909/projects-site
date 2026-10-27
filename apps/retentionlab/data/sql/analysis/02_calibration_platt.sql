-- P10-ART-04 investigation 02: calibration bins with their counts, and the effect of the Platt scaling (D-03 calibration gap, D-09 R10-08).
-- Question: on the 1,513 test rows, how far is the mean predicted risk from the observed churn rate in each of the ten equal-width bins, and did the Platt mapping
-- (fitted on the 289 retained mature validation rows of ONE cutoff) help or hurt on the test rows it never saw?
-- Bin index = floor(10 p) with p = 1 in the last bin (closed); gap = (mean predicted - observed) x 100 percentage points, 2 places; an empty bin has no mean, no rate and
-- no gap (null, never 0) and is listed, not dropped. Source: art_test_table; the fitted mapping (a, b, fit rows) is read from calibration_maps of the loaded cohort database.
-- @@ bins
WITH v AS (
    SELECT 'logistic_regression (Platt)' AS model, 1 AS ord, p_logistic_calibrated AS p, churned AS y FROM art_test_table
    UNION ALL SELECT 'logistic_regression (before Platt)', 2, p_logistic_uncalibrated, churned FROM art_test_table
),
b AS (SELECT ord, model, least(floor(p * 10)::int, 9) AS bin_index, count(*) AS n, sum(y) AS pos, sum(p) AS sp FROM v GROUP BY ord, model, least(floor(p * 10)::int, 9)),
grid AS (SELECT DISTINCT ord, model, g AS bin_index FROM v, generate_series(0, 9) AS g)
SELECT grid.model, grid.bin_index, round(grid.bin_index / 10.0, 6) AS lower_bound, round((grid.bin_index + 1) / 10.0, 6) AS upper_bound,
       coalesce(b.n, 0) AS rows_in_bin, coalesce(b.pos, 0) AS churned_rows, (b.n IS NULL) AS empty_bin,
       round(b.sp / b.n, 6) AS mean_predicted, round(b.pos::numeric / b.n, 6) AS observed_rate, round((b.sp / b.n - b.pos::numeric / b.n) * 100, 2) AS gap_pp
FROM grid LEFT JOIN b USING (ord, model, bin_index) ORDER BY grid.ord, grid.bin_index;
-- @@ platt_effect
WITH o AS (
    SELECT sum((p_logistic_uncalibrated - churned) ^ 2) / count(*) AS brier_u, sum((p_logistic_calibrated - churned) ^ 2) / count(*) AS brier_c,
           avg(p_logistic_uncalibrated) - avg(churned) AS gap_u, avg(p_logistic_calibrated) - avg(churned) AS gap_c, count(*) AS n
    FROM art_test_table
)
SELECT o.n AS test_rows, cm.a AS platt_a, cm.b AS platt_b, cm.fit_rows,
       round(o.brier_u, 6) AS brier_before, round(o.brier_c, 6) AS brier_after, round(o.brier_c - o.brier_u, 6) AS brier_change,
       round(o.gap_u * 100, 2) AS overall_gap_pp_before, round(o.gap_c * 100, 2) AS overall_gap_pp_after,
       (round(o.brier_c, 6) > round(o.brier_u, 6)) AS made_the_brier_worse
FROM o, calibration_maps cm;
-- @@ fit_rows_by_cutoff
SELECT pc.prediction_at, count(*) AS retained_mature_validation_rows_of_the_cohort
FROM split_assignments sa JOIN prediction_cutoffs pc USING (cutoff_id) JOIN labels l USING (cutoff_id) JOIN feature_rows fr USING (cutoff_id)
WHERE sa.split = 'validation' AND sa.status = 'retained' AND l.mature GROUP BY pc.prediction_at ORDER BY pc.prediction_at;
-- @@ platt_reproduced
-- the frozen mapping p' = sigmoid(a * logit(p) + b), p clamped to [1e-6, 1 - 1e-6] (D-06), applied in SQL to the uncalibrated column and compared with the stored column at 6 places
WITH x AS (
    SELECT t.row_no, t.p_logistic_calibrated AS stored,
           1 / (1 + exp(-(cm.a * ln(least(greatest(t.p_logistic_uncalibrated, 0.000001), 0.999999) / (1 - least(greatest(t.p_logistic_uncalibrated, 0.000001), 0.999999))) + cm.b))) AS raw
    FROM art_test_table t, calibration_maps cm
)
SELECT count(*) AS rows_compared, count(*) FILTER (WHERE round(raw, 6) = stored) AS equal_at_6_places,
       count(*) FILTER (WHERE abs(round(raw, 6) - stored) <= 0.000001) AS within_one_unit_in_the_6th_place,
       count(*) FILTER (WHERE abs(round(raw, 6) - stored) > 0.000001) AS further_apart
FROM x;
