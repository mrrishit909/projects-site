-- P07-ART-04 investigation 09: the golden known answer, computed in SQL from the golden fixture loaded into its own scratch database (P07-GOLD-01).
-- 100 eligible customer rows, 5 missing e-mails: completeness 95/100 = 0.950000; of the 95 populated 90 pass the format rule: validity 90/95 = 0.947368 populated-only
-- and 90/100 = 0.900000 over all eligible rows, BOTH labelled; the critical key rule fails on 2 rows so the dataset carries the override beside a score above 0.95.
-- run_all.py compares every figure here with tests/fixtures/golden/expected.json (the hand answer, CALCULATION.md), the Python domain and data/sql/reference_metrics.sql.
-- Runs on the GOLDEN database after 00_measure_rules.sql.

-- @@ completeness_validity
SELECT c.rule_id AS completeness_rule, c.eligible, c.failing AS missing, c.populated, round(c.score, 6) AS completeness,
       v.rule_id AS validity_rule, v.populated AS validity_populated, v.eligible - v.failing AS passing,
       round((v.eligible - v.failing)::numeric / v.eligible, 6) AS validity_all_eligible, round((v.eligible - v.failing)::numeric / v.populated, 6) AS validity_populated_only
FROM tl_rule_measure c JOIN tl_rule_measure v ON v.dataset_id = c.dataset_id AND v.dimension = 'validity'
WHERE c.dataset_id = 'ds-customers' AND c.dimension = 'completeness'

-- @@ uniqueness_relationship
SELECT (SELECT eligible FROM tl_rule_measure WHERE rule_id = 'r-cust-key-unique') AS uniqueness_eligible,
       (SELECT count(DISTINCT v) FROM tl_cells WHERE rule_id = 'r-cust-key-unique' AND NOT is_missing) AS distinct_keys,
       (SELECT count(*) FROM (SELECT v FROM tl_cells WHERE rule_id = 'r-cust-key-unique' AND NOT is_missing GROUP BY v HAVING count(*) > 1) g) AS duplicate_groups,
       (SELECT failing FROM tl_rule_measure WHERE rule_id = 'r-cust-key-unique') AS duplicate_rows,
       round((SELECT count(*) FROM (SELECT v FROM tl_cells WHERE rule_id = 'r-cust-key-unique' AND NOT is_missing GROUP BY v HAVING count(*) > 1) g)::numeric
             / (SELECT count(DISTINCT v) FROM tl_cells WHERE rule_id = 'r-cust-key-unique' AND NOT is_missing), 6) AS group_share,
       round((SELECT failing FROM tl_rule_measure WHERE rule_id = 'r-cust-key-unique')::numeric / (SELECT eligible FROM tl_rule_measure WHERE rule_id = 'r-cust-key-unique'), 6) AS row_share,
       (SELECT count(*) FROM tl_cells WHERE rule_id = 'r-ord-cust-fk') AS fk_total, (SELECT count(*) FROM tl_cells WHERE rule_id = 'r-ord-cust-fk' AND is_missing) AS fk_null_or_empty,
       (SELECT eligible FROM tl_rule_measure WHERE rule_id = 'r-ord-cust-fk') AS fk_eligible,
       (SELECT eligible - failing FROM tl_rule_measure WHERE rule_id = 'r-ord-cust-fk') AS fk_matched,
       (SELECT round(score, 6) FROM tl_rule_measure WHERE rule_id = 'r-ord-cust-fk') AS relationship

-- @@ weighted_scores
SELECT w.weight_version, string_agg(d.dimension, ',' ORDER BY CASE d.dimension WHEN 'completeness' THEN 1 WHEN 'validity' THEN 2 WHEN 'uniqueness' THEN 3 WHEN 'relationship' THEN 4 ELSE 5 END) AS measured_dimensions,
       round(sum((w.weights ->> d.dimension)::numeric), 6) AS weight_sum,
       round(sum((w.weights ->> d.dimension)::numeric * d.score) / sum((w.weights ->> d.dimension)::numeric), 6) AS weighted_score,
       (SELECT coalesce(sum(failing), 0) FROM tl_rule_measure WHERE dataset_id = 'ds-customers' AND severity = 'critical') AS critical_failures,
       (SELECT count(*) FROM tl_issue WHERE dataset_id = 'ds-customers' AND severity = 'critical' AND class <> 'resolved') AS critical_open_issues,
       (SELECT coalesce(sum(failing), 0) FROM tl_rule_measure WHERE dataset_id = 'ds-customers' AND severity = 'critical') > 0
         OR EXISTS (SELECT 1 FROM tl_issue WHERE dataset_id = 'ds-customers' AND severity = 'critical' AND class <> 'resolved') AS critical_override
FROM rule_weight_versions w CROSS JOIN tl_dim d WHERE d.dataset_id = 'ds-customers' GROUP BY w.weight_version ORDER BY w.weight_version

-- @@ portfolio
SELECT (SELECT count(*) FROM tl_tstate WHERE seq = 0) AS timeliness_monitored, (SELECT count(*) FROM tl_tstate WHERE seq = 0 AND state = 'on_time') AS timeliness_on_time,
       (SELECT count(*) FROM datasets) AS datasets,
       (SELECT count(*) FROM datasets d JOIN owners o ON o.owner_id = d.owner_id, tl_p WHERE CASE WHEN o.deactivated_at IS NOT NULL THEN tl_p.as_of < o.deactivated_at ELSE o.active END) AS ownership_covered,
       (SELECT count(*) FROM metric_versions WHERE status = 'published' AND valid_from <= (SELECT as_of FROM tl_p)) AS published_metrics,
       (SELECT count(*) FROM metric_versions m WHERE m.status = 'published' AND m.valid_from <= (SELECT as_of FROM tl_p)
          AND (m.definition IS NULL OR btrim(m.definition, (SELECT chars FROM tl_p)) = '') IS NOT TRUE AND (m.grain IS NULL OR btrim(m.grain, (SELECT chars FROM tl_p)) = '') IS NOT TRUE
          AND (m.refresh IS NULL OR btrim(m.refresh, (SELECT chars FROM tl_p)) = '') IS NOT TRUE AND jsonb_typeof(m.source_fields) = 'array' AND jsonb_array_length(m.source_fields) > 0
          AND EXISTS (SELECT 1 FROM owners o WHERE o.owner_id = m.owner_id)) AS definitions_complete,
       (SELECT count(DISTINCT (source_dataset_id, target_dataset_id)) FROM lineage_edges WHERE evidence_type = 'declared') AS lineage_declared,
       (SELECT count(*) FROM (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM lineage_edges WHERE evidence_type = 'declared') d
          WHERE EXISTS (SELECT 1 FROM lineage_edges o WHERE o.evidence_type = 'observed' AND o.source_dataset_id = d.s AND o.target_dataset_id = d.t)) AS lineage_observed_matching,
       (SELECT count(*) FILTER (WHERE class = 'resolved') FROM tl_issue) AS issues_resolved, (SELECT count(*) FILTER (WHERE class = 'claimed') FROM tl_issue) AS issues_claimed,
       (SELECT count(*) FILTER (WHERE class = 'open') FROM tl_issue) AS issues_open, (SELECT round(avg(hours), 4) FROM tl_issue WHERE class = 'resolved') AS resolution_mean_hours,
       (SELECT count(*) FROM merge_decisions m JOIN match_candidates c USING (candidate_id) JOIN verification_truth a ON a.record_id = c.left_record_id
          JOIN verification_truth b ON b.record_id = c.right_record_id WHERE m.decision = 'approve' AND a.true_entity = b.true_entity) AS approved_correct,
       (SELECT count(*) FROM merge_decisions WHERE decision = 'approve') AS approved
