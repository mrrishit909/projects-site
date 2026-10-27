-- P10-ART-04 investigation 07: population drift of usage_events_30d by region, with the floored bins flagged (D-03 P10-MET-11, D-P10-10, D-07 DR-03, D-09 R10-07).
-- Question: from the 2026-03-31 change in how logins are recorded, which region's usage distribution moves away from its own 2026-02-01 cohort, and which exceedances of
-- the 0.2 threshold are artefacts of the 0.0001 floor?
-- PSI = sum over the declared half-open bins [0,1), [1,3), [3,inf) of (actual - expected) x ln(actual / expected), a zero proportion replaced by 0.0001 WITHOUT renormalising;
-- exact NUMERIC with PostgreSQL's numeric ln() (the domain uses Decimal.ln at 60 digits; both round half away from zero to 6 places). A bin with a zero reference or current
-- count is FLOORED; the threshold 0.2 is a diagnostic, not proof. Two sources: (a) the four test-range cutoffs recomputed here from the 1,513-row test table for every
-- region (its 2026-02-01 rows ARE the eligible reference cohort of the full world); (b) the 21-cutoff series of the full world as published (art_drift_published).
-- @@ psi_test_range
WITH g AS (
    SELECT 'all_accounts' AS grp, 1 AS ord, cutoff_index, prediction_at, usage_events_30d AS u FROM art_test_table
    UNION ALL SELECT region, 3, cutoff_index, prediction_at, usage_events_30d FROM art_test_table
    UNION ALL SELECT 'other_regions', 2, cutoff_index, prediction_at, usage_events_30d FROM art_test_table WHERE region <> 'apac'
),
grid AS (SELECT DISTINCT grp, ord, cutoff_index, prediction_at, b FROM g, generate_series(0, 2) AS b),
cnt AS (
    SELECT grid.grp, grid.ord, grid.cutoff_index, grid.prediction_at, grid.b,
           count(g.u) FILTER (WHERE (grid.b = 0 AND g.u < 1) OR (grid.b = 1 AND g.u >= 1 AND g.u < 3) OR (grid.b = 2 AND g.u >= 3)) AS n
    FROM grid LEFT JOIN g ON g.grp = grid.grp AND g.cutoff_index = grid.cutoff_index GROUP BY grid.grp, grid.ord, grid.cutoff_index, grid.prediction_at, grid.b
),
p AS (
    SELECT c.grp, c.ord, c.cutoff_index, c.prediction_at, c.b, c.n AS cur_n, r.n AS ref_n,
           sum(c.n) OVER (PARTITION BY c.grp, c.cutoff_index) AS cur_total, sum(r.n) OVER (PARTITION BY c.grp, c.cutoff_index) AS ref_total
    FROM cnt c JOIN cnt r ON r.grp = c.grp AND r.b = c.b AND r.cutoff_index = 0
),
t AS (
    SELECT p.*, cur_n::numeric / cur_total AS a, ref_n::numeric / ref_total AS e FROM p
),
f AS (
    SELECT t.*, CASE WHEN a = 0 THEN 0.0001 ELSE a END AS a_f, CASE WHEN e = 0 THEN 0.0001 ELSE e END AS e_f FROM t
)
SELECT grp AS grp, prediction_at, max(ref_total) AS reference_rows, max(cur_total) AS current_rows,
       round(sum((a_f - e_f) * ln(a_f / e_f)), 6) AS psi, count(*) FILTER (WHERE ref_n = 0 OR cur_n = 0) AS floored_bins,
       (sum((a_f - e_f) * ln(a_f / e_f)) > 0.2) AS exceeds_threshold
FROM f GROUP BY grp, ord, cutoff_index, prediction_at ORDER BY ord, grp COLLATE "C", cutoff_index;
-- @@ published_series_apac
SELECT d.prediction_at, d.psi, d.current_rows, d.reference_rows, d.floored_bins, d.exceeds_threshold,
       (d.prediction_at < timestamptz '2026-03-31' AND d.prediction_at <> timestamptz '2026-02-01') AS comparison_before_the_change, (d.exceeds_threshold AND d.floored_bins > 0) AS exceeds_with_a_floored_bin,
       a.psi AS all_accounts_psi, o.psi AS other_regions_psi
FROM art_drift_published d JOIN art_drift_published a ON a.prediction_at = d.prediction_at AND a.grp = 'all_accounts'
JOIN art_drift_published o ON o.prediction_at = d.prediction_at AND o.grp = 'other_regions'
WHERE d.grp = 'apac' ORDER BY d.prediction_at;
-- @@ published_summary
-- the false-positive reading of the apac series (D-09 R10-07). The reference cohort is the 2026-02-01 cutoff (its own PSI is 0 by construction and is not a comparison);
-- "before the reference" = the 13 cutoffs 2025-01-01 .. 2026-01-01; "before the change" = every comparison cutoff earlier than 2026-03-31 (those 13 plus 2026-03-01)
WITH s AS (
    SELECT d.*, (d.prediction_at < timestamptz '2026-02-01') AS before_reference, (d.prediction_at < timestamptz '2026-03-31' AND d.prediction_at <> timestamptz '2026-02-01') AS pre
    FROM art_drift_published d WHERE d.grp = 'apac'
)
SELECT count(*) FILTER (WHERE before_reference) AS cutoffs_before_the_reference, count(*) FILTER (WHERE before_reference AND exceeds_threshold) AS exceedances_before_the_reference,
       count(*) FILTER (WHERE pre) AS comparison_cutoffs_before_the_change, count(*) FILTER (WHERE pre AND exceeds_threshold) AS exceedances_before_the_change,
       count(*) FILTER (WHERE pre AND exceeds_threshold AND floored_bins > 0) AS exceedances_before_the_change_with_a_floored_bin,
       count(*) FILTER (WHERE pre AND exceeds_threshold AND floored_bins = 0) AS exceedances_before_the_change_without_a_floored_bin,
       max(psi) FILTER (WHERE pre) AS max_psi_before_the_change,
       count(*) FILTER (WHERE prediction_at >= timestamptz '2026-04-01' AND exceeds_threshold) AS exceedances_from_the_change, min(prediction_at) FILTER (WHERE prediction_at >= timestamptz '2026-04-01' AND exceeds_threshold) AS first_exceedance_from_the_change,
       min(psi) FILTER (WHERE prediction_at >= timestamptz '2026-05-01') AS shift_min_psi, max(psi) FILTER (WHERE prediction_at >= timestamptz '2026-05-01') AS shift_max_psi,
       (SELECT max(psi) FROM art_drift_published WHERE grp = 'all_accounts') AS all_accounts_max_psi,
       (SELECT psi FROM art_drift_published WHERE grp = 'all_accounts' AND prediction_at = timestamptz '2026-05-01') AS all_accounts_psi_2026_05,
       (SELECT psi FROM art_drift_published WHERE grp = 'all_accounts' ORDER BY prediction_at DESC LIMIT 1) AS all_accounts_psi_latest,
       (SELECT max(psi) FROM art_drift_published WHERE grp = 'other_regions') AS other_regions_max_psi
FROM s;
