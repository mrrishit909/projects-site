-- P07-ART-04 investigation 01: ds-customers, the near-perfect score with an open critical key failure, under BOTH weight versions (D-01, DR-01, INJ-01).
-- Question: does the weighted score hide the dataset's critical key failure? Reads the temporary tables of 00_measure_rules.sql.
-- Observed on the loaded snapshot at its as-of; the weight versions are the dataset's own (w1 valid from 2026-01-01, w2 from 2026-09-01).

-- @@ rules
-- Every active rule of ds-customers: what it measured, how many failed, and the score it contributes to its dimension.
SELECT rule_id, dimension, severity, eligible, populated, failing, round(score, 6) AS score
FROM tl_rule_measure WHERE dataset_id = 'ds-customers' ORDER BY rule_id COLLATE "C"

-- @@ dimensions
SELECT dimension, rules, round(score, 6) AS score FROM tl_dim WHERE dataset_id = 'ds-customers'
ORDER BY CASE dimension WHEN 'completeness' THEN 1 WHEN 'validity' THEN 2 WHEN 'uniqueness' THEN 3 WHEN 'relationship' THEN 4 ELSE 5 END

-- @@ weighted
-- Weighted score = sum(dimension score x weight) / sum(weights of the MEASURED dimensions): relationship is not measured on ds-customers, so its weight leaves both sums.
SELECT w.weight_version, w.valid_from::date AS valid_from,
       string_agg(d.dimension, ',' ORDER BY CASE d.dimension WHEN 'completeness' THEN 1 WHEN 'validity' THEN 2 WHEN 'uniqueness' THEN 3 WHEN 'relationship' THEN 4 ELSE 5 END) AS measured_dimensions,
       round(sum((w.weights ->> d.dimension)::numeric), 6) AS weight_sum,
       round(sum((w.weights ->> d.dimension)::numeric * d.score) / sum((w.weights ->> d.dimension)::numeric), 6) AS weighted_score,
       sum((w.weights ->> d.dimension)::numeric * d.score) / sum((w.weights ->> d.dimension)::numeric) > 0.95 AS above_0_95
FROM rule_weight_versions w CROSS JOIN tl_dim d WHERE d.dataset_id = 'ds-customers'
GROUP BY w.weight_version, w.valid_from ORDER BY w.weight_version

-- @@ critical
-- The critical override sits beside the score whatever its value: failing rows of active critical rules, plus critical issues not resolved.
SELECT 'ds-customers' AS dataset_id,
       (SELECT coalesce(sum(failing), 0) FROM tl_rule_measure WHERE dataset_id = 'ds-customers' AND severity = 'critical') AS critical_failures,
       (SELECT count(*) FROM tl_issue WHERE dataset_id = 'ds-customers' AND severity = 'critical' AND class <> 'resolved') AS critical_open_issues,
       (SELECT coalesce(sum(failing), 0) FROM tl_rule_measure WHERE dataset_id = 'ds-customers' AND severity = 'critical') > 0
         OR EXISTS (SELECT 1 FROM tl_issue WHERE dataset_id = 'ds-customers' AND severity = 'critical' AND class <> 'resolved') AS critical_override

-- @@ critical_issue
SELECT issue_id, rule_id, severity, status, class, tl_iso(detected_at) AS detected_at, owner_id, round(hours, 4) AS age_hours
FROM tl_issue WHERE dataset_id = 'ds-customers' AND severity = 'critical' ORDER BY issue_id COLLATE "C"

-- @@ portfolio_override
-- How many datasets carry the override in the whole portfolio (the near-perfect one is the only one).
SELECT count(*) AS datasets_overridden FROM (
    SELECT dataset_id FROM tl_rule_measure WHERE severity = 'critical' GROUP BY dataset_id HAVING sum(failing) > 0
    UNION SELECT dataset_id FROM tl_issue WHERE severity = 'critical' AND class <> 'resolved') x
