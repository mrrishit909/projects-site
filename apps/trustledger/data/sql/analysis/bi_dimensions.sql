-- P07-ART-06 BI dimensions (a star schema over the loaded snapshot at its as-of). Read only; needs 00_measure_rules.sql (tl_p, tl_dim, tl_rule_measure).
-- Booleans are 0/1, instants are UTC ISO text, nothing is dropped silently: a dataset with no measured dimension still has a row in fact_dataset_score with a status.

-- @@ dim_owner
SELECT o.owner_id, o.owner_name, o.team, o.role, o.active::int AS active, tl_iso(o.deactivated_at) AS deactivated_at,
       (CASE WHEN o.deactivated_at IS NOT NULL THEN tl_p.as_of < o.deactivated_at ELSE o.active END)::int AS accountable_at_as_of
FROM owners o, tl_p ORDER BY o.owner_id COLLATE "C"

-- @@ dim_dataset
SELECT d.dataset_id, d.dataset_name, d.source_system, d.classification, d.owner_id, d.monitored::int AS monitored, d.registered_at::date AS registered_date,
       (EXISTS (SELECT 1 FROM tl_rows r WHERE r.dataset_id = d.dataset_id))::int AS has_rows,
       (SELECT count(*) FROM tl_rules r WHERE r.dataset_id = d.dataset_id) AS active_rules,
       (o.owner_id IS NOT NULL AND CASE WHEN o.deactivated_at IS NOT NULL THEN tl_p.as_of < o.deactivated_at ELSE o.active END)::int AS owner_covered
FROM datasets d LEFT JOIN owners o ON o.owner_id = d.owner_id, tl_p WHERE d.registered_at <= tl_p.as_of ORDER BY d.dataset_id COLLATE "C"

-- @@ dim_rule
SELECT r.rule_id, r.dataset_id, r.rule_type AS dimension, r.severity, r.version_number, r.status, tl_iso(r.disabled_at) AS disabled_at,
       (r.status = 'active' OR r.disabled_at > tl_p.as_of)::int AS active_at_as_of
FROM quality_rules r, tl_p ORDER BY r.rule_id COLLATE "C"

-- @@ dim_weight_version
SELECT weight_version, tl_iso(valid_from) AS valid_from, weights ->> 'completeness' AS w_completeness, weights ->> 'validity' AS w_validity, weights ->> 'uniqueness' AS w_uniqueness,
       weights ->> 'relationship' AS w_relationship, weights ->> 'timeliness' AS w_timeliness
FROM rule_weight_versions ORDER BY valid_from

-- @@ dim_date
SELECT d::date AS date, extract(year FROM d)::int AS year, extract(month FROM d)::int AS month, to_char(d, 'IYYY-"W"IW') AS iso_week, to_char(d, 'Dy') AS weekday
FROM generate_series((SELECT min(detected_at)::date FROM issues), (SELECT as_of::date FROM tl_p), interval '1 day') d ORDER BY 1

-- @@ dim_metric
-- The effective published version of each metric at the as-of and its checklist result (cl-1): the missing items are listed, never hidden.
WITH eff AS (
    SELECT DISTINCT ON (m.metric_id) m.* FROM metric_versions m, tl_p WHERE m.valid_from <= tl_p.as_of AND m.status = 'published'
    ORDER BY m.metric_id, m.valid_from DESC, m.version_number DESC),
g AS (
    SELECT e.*, concat_ws(',',
               CASE WHEN e.definition IS NULL OR btrim(e.definition, tl_p.chars) = '' THEN 'definition' END,
               CASE WHEN e.grain IS NULL OR btrim(e.grain, tl_p.chars) = '' THEN 'grain' END,
               CASE WHEN e.source_fields IS NULL OR jsonb_typeof(e.source_fields) <> 'array' OR jsonb_array_length(e.source_fields) = 0
                         OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(e.source_fields) f WHERE btrim(f, tl_p.chars) = '') THEN 'source_fields' END,
               CASE WHEN NOT EXISTS (SELECT 1 FROM owners o WHERE o.owner_id = e.owner_id) THEN 'owner' END,
               CASE WHEN e.refresh IS NULL OR btrim(e.refresh, tl_p.chars) = '' THEN 'refresh' END) AS missing
    FROM eff e, tl_p)
SELECT metric_id, metric_name, version_number AS effective_version, (SELECT count(*) FROM metric_versions v WHERE v.metric_id = g.metric_id) AS versions,
       coalesce(owner_id, '') AS owner_id, tl_iso(valid_from) AS valid_from, (missing = '')::int AS checklist_complete, missing AS missing_items
FROM g ORDER BY metric_id COLLATE "C"
