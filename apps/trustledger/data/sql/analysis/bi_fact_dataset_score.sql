-- P07-ART-06 fact: one row per dataset and weight version (40 x 2): the weighted score, the dimensions measured, the weight sum and the critical override beside it.
-- A dataset with no measured dimension has an EMPTY weighted_score and the status `not_measured: no rule measures a value` (never 0).
SELECT d.dataset_id, w.weight_version,
       coalesce((SELECT string_agg(x.dimension, ',' ORDER BY CASE x.dimension WHEN 'completeness' THEN 1 WHEN 'validity' THEN 2 WHEN 'uniqueness' THEN 3 WHEN 'relationship' THEN 4 ELSE 5 END)
                 FROM tl_dim x WHERE x.dataset_id = d.dataset_id), '') AS measured_dimensions,
       (SELECT round(sum((w.weights ->> x.dimension)::numeric), 6) FROM tl_dim x WHERE x.dataset_id = d.dataset_id) AS weight_sum,
       (SELECT round(sum((w.weights ->> x.dimension)::numeric * x.score) / sum((w.weights ->> x.dimension)::numeric), 6) FROM tl_dim x WHERE x.dataset_id = d.dataset_id) AS weighted_score,
       CASE WHEN EXISTS (SELECT 1 FROM tl_dim x WHERE x.dataset_id = d.dataset_id) THEN 'measured' ELSE 'not_measured: no rule measures a value' END AS score_status,
       coalesce((SELECT sum(m.failing) FROM tl_rule_measure m WHERE m.dataset_id = d.dataset_id AND m.severity = 'critical'), 0) AS critical_failures,
       (SELECT count(*) FROM tl_issue i WHERE i.dataset_id = d.dataset_id AND i.severity = 'critical' AND i.class <> 'resolved') AS critical_open_issues,
       (coalesce((SELECT sum(m.failing) FROM tl_rule_measure m WHERE m.dataset_id = d.dataset_id AND m.severity = 'critical'), 0) > 0
        OR EXISTS (SELECT 1 FROM tl_issue i WHERE i.dataset_id = d.dataset_id AND i.severity = 'critical' AND i.class <> 'resolved'))::int AS critical_override
FROM datasets d CROSS JOIN rule_weight_versions w, tl_p WHERE d.registered_at <= tl_p.as_of ORDER BY d.dataset_id COLLATE "C", w.weight_version
