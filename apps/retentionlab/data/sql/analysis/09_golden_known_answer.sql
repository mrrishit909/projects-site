-- P10-ART-04 investigation 09: the golden known answer (runs on the GOLDEN database, tests/fixtures/golden/inputs.json; D-03 and tests/fixtures/golden/CALCULATION.md; P10-GOLD-01).
-- Four mature eligible accounts with frozen risks .8, .6, .4, .1 and outcomes 1, 0, 1, 0 (cutoff set 2026-01-01, scenario sc-001: capacity 2, contact cost 5.00, assumed effect
-- 0.1, margin 131.75) give churn 2/4 = 0.500000, precision and recall at K = 2 of 0.500000, Brier 0.77/4 = 0.192500, average precision 1/2 + 1/3 = 5/6 = 0.833333, risk lift 1.000000, a
-- contact budget of 10.00 and an expected intervention value of 8.445 -> 8.45 (hypothetical; ROUND_HALF_UP once at the end). Eligibility and the outcome are derived here from the
-- subscription events (not read from the stored label), so the SQL is an independent statement of D-01; reference_metrics.sql and the domain are compared by run_all.py.
-- @@ ranking
WITH cx AS (
    SELECT pc.cutoff_id, pc.account_id, pc.prediction_at, pc.observation_start, pc.horizon_end, pc.horizon_end + interval '14 days' AS label_end, a.created_at
    FROM prediction_cutoffs pc JOIN accounts a USING (account_id) WHERE pc.prediction_at = timestamptz '2026-01-01'
),
el AS (
    SELECT cx.*, (cx.created_at < cx.observation_start AND (SELECT s.event_type FROM subscription_events s WHERE s.account_id = cx.account_id AND s.event_at < cx.prediction_at
                  AND s.available_at < cx.prediction_at ORDER BY s.event_at DESC, s.subscription_event_id COLLATE "C" DESC LIMIT 1) IN ('start', 'renew')) AS eligible
    FROM cx
),
lab AS (
    SELECT el.*, EXISTS (SELECT 1 FROM subscription_events s WHERE s.account_id = el.account_id AND s.event_type = 'cancel' AND s.event_at >= el.prediction_at AND s.event_at < el.horizon_end
                         AND s.available_at < el.label_end) AS churned
    FROM el WHERE el.eligible
)
SELECT row_number() OVER (ORDER BY p.probability DESC, lab.account_id ASC) AS rank, lab.account_id, p.probability AS risk, lab.churned::int AS outcome,
       round((p.probability - lab.churned::int) ^ 2, 6) AS squared_error
FROM lab JOIN predictions p USING (cutoff_id) ORDER BY 1;
-- @@ known_answer
WITH cx AS (
    SELECT pc.cutoff_id, pc.account_id, pc.prediction_at, pc.observation_start, pc.horizon_end, pc.horizon_end + interval '14 days' AS label_end, a.created_at
    FROM prediction_cutoffs pc JOIN accounts a USING (account_id) WHERE pc.prediction_at = timestamptz '2026-01-01'
),
el AS (
    SELECT cx.*, (cx.created_at < cx.observation_start AND (SELECT s.event_type FROM subscription_events s WHERE s.account_id = cx.account_id AND s.event_at < cx.prediction_at
                  AND s.available_at < cx.prediction_at ORDER BY s.event_at DESC, s.subscription_event_id COLLATE "C" DESC LIMIT 1) IN ('start', 'renew')) AS eligible
    FROM cx
),
lab AS (
    SELECT el.*, EXISTS (SELECT 1 FROM subscription_events s WHERE s.account_id = el.account_id AND s.event_type = 'cancel' AND s.event_at >= el.prediction_at AND s.event_at < el.horizon_end
                         AND s.available_at < el.label_end) AS churned
    FROM el WHERE el.eligible
),
r AS (SELECT row_number() OVER (ORDER BY p.probability DESC, lab.account_id ASC) AS rk, lab.account_id, p.probability AS pr, lab.churned::int AS y FROM lab JOIN predictions p USING (cutoff_id)),
g AS (SELECT pr, sum(y) AS tp_g, count(*) AS n_g FROM r GROUP BY pr),
c AS (SELECT g.*, sum(tp_g) OVER (ORDER BY pr DESC) AS tp, sum(n_g) OVER (ORDER BY pr DESC) AS n_cum, sum(tp_g) OVER () AS pos FROM g),
sc AS (SELECT * FROM intervention_scenarios WHERE scenario_id = 'sc-001')
SELECT (SELECT count(*) FROM cx) AS cutoff_rows, (SELECT count(*) FROM el WHERE eligible) AS eligible_rows,
       (SELECT count(*) FROM el WHERE NOT eligible AND created_at >= observation_start) AS ineligible_created_on_or_after_observation_start,
       (SELECT count(*) FROM el WHERE NOT eligible AND created_at < observation_start) AS ineligible_not_active,
       (SELECT count(*) FROM lab) AS mature_eligible, (SELECT sum(y) FROM r) AS churned,
       round((SELECT sum(y) FROM r)::numeric / (SELECT count(*) FROM r), 6) AS churn_rate,
       sc.capacity,
       round((SELECT sum(y) FROM r WHERE rk <= sc.capacity)::numeric / sc.capacity, 6) AS precision_at_k,
       round((SELECT sum(y) FROM r WHERE rk <= sc.capacity)::numeric / (SELECT sum(y) FROM r), 6) AS recall_at_k,
       round(((SELECT sum(y) FROM r WHERE rk <= sc.capacity)::numeric / sc.capacity) / ((SELECT sum(y) FROM r)::numeric / (SELECT count(*) FROM r)), 6) AS risk_lift_at_k,
       round((SELECT sum((pr - y) ^ 2) FROM r) / (SELECT count(*) FROM r), 6) AS brier_score,
       (SELECT round(sum(tp_g::numeric / pos * tp / n_cum), 6) FROM c) AS average_precision,
       round(sc.contact_cost * sc.capacity, 2) AS contact_budget,
       round((SELECT sum(pr * sc.assumed_effect * sc.margin_value - sc.contact_cost) FROM r WHERE rk <= sc.capacity), 2) AS expected_intervention_value,
       'hypothetical' AS label
FROM sc;
-- @@ average_precision_terms
WITH cx AS (
    SELECT pc.cutoff_id, pc.account_id, pc.prediction_at, pc.observation_start, pc.horizon_end, pc.horizon_end + interval '14 days' AS label_end, a.created_at
    FROM prediction_cutoffs pc JOIN accounts a USING (account_id) WHERE pc.prediction_at = timestamptz '2026-01-01'
),
lab AS (
    SELECT cx.*, EXISTS (SELECT 1 FROM subscription_events s WHERE s.account_id = cx.account_id AND s.event_type = 'cancel' AND s.event_at >= cx.prediction_at AND s.event_at < cx.horizon_end
                         AND s.available_at < cx.label_end) AS churned
    FROM cx WHERE cx.created_at < cx.observation_start AND (SELECT s.event_type FROM subscription_events s WHERE s.account_id = cx.account_id AND s.event_at < cx.prediction_at
                  AND s.available_at < cx.prediction_at ORDER BY s.event_at DESC, s.subscription_event_id COLLATE "C" DESC LIMIT 1) IN ('start', 'renew')
),
r AS (SELECT p.probability AS pr, lab.churned::int AS y FROM lab JOIN predictions p USING (cutoff_id)),
g AS (SELECT pr, sum(y) AS tp_g, count(*) AS n_g FROM r GROUP BY pr),
c AS (SELECT g.*, sum(tp_g) OVER (ORDER BY pr DESC) AS tp, sum(n_g) OVER (ORDER BY pr DESC) AS n_cum, sum(tp_g) OVER () AS pos FROM g)
SELECT pr AS threshold, tp AS true_positives, n_cum - tp AS false_positives, round(tp::numeric / n_cum, 6) AS precision, round(tp::numeric / pos, 6) AS recall,
       round(tp_g::numeric / pos, 6) AS delta_recall, round(tp_g::numeric / pos * tp / n_cum, 6) AS term
FROM c ORDER BY pr DESC;
-- @@ arrived_late
-- events inside the observation window that happened before the cutoff but arrived at or after it: counted and never used (P10-TEST-02); only eligible cutoff rows of the set
SELECT 'usage_events' AS source, count(*) AS arrived_late FROM prediction_cutoffs pc JOIN feature_rows fr USING (cutoff_id) JOIN usage_events e ON e.account_id = pc.account_id
 WHERE pc.prediction_at = timestamptz '2026-01-01' AND e.event_at >= pc.observation_start AND e.event_at < pc.prediction_at AND e.available_at >= pc.prediction_at
UNION ALL SELECT 'support_events', count(*) FROM prediction_cutoffs pc JOIN feature_rows fr USING (cutoff_id) JOIN support_events e ON e.account_id = pc.account_id
 WHERE pc.prediction_at = timestamptz '2026-01-01' AND e.event_at >= pc.observation_start AND e.event_at < pc.prediction_at AND e.available_at >= pc.prediction_at
UNION ALL SELECT 'billing_events', count(*) FROM prediction_cutoffs pc JOIN feature_rows fr USING (cutoff_id) JOIN billing_events e ON e.account_id = pc.account_id
 WHERE pc.prediction_at = timestamptz '2026-01-01' AND e.event_at >= pc.observation_start AND e.event_at < pc.prediction_at AND e.available_at >= pc.prediction_at
UNION ALL SELECT 'subscription_events', count(*) FROM prediction_cutoffs pc JOIN feature_rows fr USING (cutoff_id) JOIN subscription_events e ON e.account_id = pc.account_id
 WHERE pc.prediction_at = timestamptz '2026-01-01' AND e.event_at < pc.prediction_at AND e.available_at >= pc.prediction_at;
-- @@ censored_cohort
-- the 2026-02-01 cohort: label_end 2026-05-16 is after the as-of 2026-05-01, so every eligible row is censored and the ranking metrics are NULL (never 0)
SELECT pc.prediction_at, count(*) AS eligible_rows, count(*) FILTER (WHERE l.mature) AS mature_rows, count(*) FILTER (WHERE NOT l.mature) AS censored_rows,
       count(*) FILTER (WHERE l.churned IS NOT NULL) AS rows_with_an_outcome,
       round(count(*) FILTER (WHERE l.churned)::numeric / NULLIF(count(*) FILTER (WHERE l.mature), 0), 6) AS churn_rate
FROM prediction_cutoffs pc JOIN feature_rows fr USING (cutoff_id) JOIN labels l USING (cutoff_id) WHERE pc.prediction_at = timestamptz '2026-02-01' GROUP BY pc.prediction_at;
-- @@ purge_counts
SELECT sa.split AS split_range, count(*) AS cutoff_rows, count(*) FILTER (WHERE sa.status = 'retained') AS retained, count(*) FILTER (WHERE sa.drop_reason = 'LABEL_WINDOW') AS label_window,
       count(*) FILTER (WHERE sa.drop_reason = 'GROUP_TEST') AS group_test, count(*) FILTER (WHERE sa.drop_reason = 'GROUP_VALIDATION') AS group_validation
FROM split_assignments sa GROUP BY sa.split ORDER BY CASE sa.split WHEN 'train' THEN 1 WHEN 'validation' THEN 2 WHEN 'test' THEN 3 ELSE 4 END;
-- @@ calibration_bins
WITH lab AS (
    SELECT p.probability AS pr, (SELECT EXISTS (SELECT 1 FROM subscription_events s WHERE s.account_id = pc.account_id AND s.event_type = 'cancel' AND s.event_at >= pc.prediction_at
                                                  AND s.event_at < pc.horizon_end AND s.available_at < pc.horizon_end + interval '14 days'))::int AS y
    FROM predictions p JOIN prediction_cutoffs pc USING (cutoff_id) JOIN feature_rows fr USING (cutoff_id) WHERE pc.prediction_at = timestamptz '2026-01-01'
),
b AS (SELECT least(floor(pr * 10)::int, 9) AS bin_index, count(*) AS n, sum(y) AS pos, sum(pr) AS sp FROM lab GROUP BY 1)
SELECT grid.g AS bin_index, coalesce(b.n, 0) AS rows_in_bin, (b.n IS NULL) AS empty_bin, round(b.sp / b.n, 6) AS mean_predicted, round(b.pos::numeric / b.n, 6) AS observed_rate,
       round((b.sp / b.n - b.pos::numeric / b.n) * 100, 2) AS gap_pp
FROM generate_series(0, 9) AS grid(g) LEFT JOIN b ON b.bin_index = grid.g ORDER BY grid.g;
-- @@ psi_against_the_march_2025_cohort
WITH f AS (
    SELECT pc.prediction_at, (fr.features_json ->> 'usage_events_30d')::int AS u FROM feature_rows fr JOIN prediction_cutoffs pc USING (cutoff_id)
    WHERE pc.prediction_at IN (timestamptz '2025-03-01', timestamptz '2026-01-01', timestamptz '2026-02-01')
),
grid AS (SELECT s.prediction_at, b FROM (SELECT DISTINCT prediction_at FROM f WHERE prediction_at <> timestamptz '2025-03-01') s, generate_series(0, 2) AS b),
cnt AS (
    SELECT grid.prediction_at, grid.b, count(f.u) FILTER (WHERE (grid.b = 0 AND f.u < 1) OR (grid.b = 1 AND f.u >= 1 AND f.u < 3) OR (grid.b = 2 AND f.u >= 3)) AS cur_n,
           (SELECT count(*) FROM f r WHERE r.prediction_at = timestamptz '2025-03-01' AND ((grid.b = 0 AND r.u < 1) OR (grid.b = 1 AND r.u >= 1 AND r.u < 3) OR (grid.b = 2 AND r.u >= 3))) AS ref_n
    FROM grid LEFT JOIN f ON f.prediction_at = grid.prediction_at GROUP BY grid.prediction_at, grid.b
),
p AS (SELECT cnt.*, sum(cur_n) OVER (PARTITION BY prediction_at) AS cur_total, sum(ref_n) OVER (PARTITION BY prediction_at) AS ref_total FROM cnt),
t AS (SELECT p.*, CASE WHEN cur_n = 0 THEN 0.0001 ELSE cur_n::numeric / cur_total END AS a_f, CASE WHEN ref_n = 0 THEN 0.0001 ELSE ref_n::numeric / ref_total END AS e_f FROM p)
SELECT prediction_at, max(ref_total) AS reference_rows, max(cur_total) AS current_rows, round(sum((a_f - e_f) * ln(a_f / e_f)), 6) AS psi,
       count(*) FILTER (WHERE ref_n = 0 OR cur_n = 0) AS floored_bins, (sum((a_f - e_f) * ln(a_f / e_f)) > 0.2) AS exceeds_threshold
FROM t GROUP BY prediction_at ORDER BY prediction_at;
