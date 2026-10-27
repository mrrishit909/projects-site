-- P07-ART-04 investigation 06: definition coverage under checklist version cl-1 (D-02, D-06, INJ-11).
-- Definition coverage = PUBLISHED metrics whose contract checklist (definition, grain, source_fields, owner, refresh) is complete / published metrics. Only the effective
-- published version of each metric at the as-of counts; a draft or superseded version does not. An item is complete when a text is non-blank after trimming, the field list
-- is non-empty with no blank entry, and the owner exists in the owners register (existence, not activity: ownership coverage is investigation 02).
-- Observed on the loaded snapshot at its as-of.

-- @@ summary
WITH eff AS (
    SELECT DISTINCT ON (m.metric_id) m.* FROM metric_versions m, tl_p WHERE m.valid_from <= tl_p.as_of AND m.status = 'published'
    ORDER BY m.metric_id, m.valid_from DESC, m.version_number DESC),
gap AS (
    SELECT e.metric_id,
           (e.definition IS NULL OR btrim(e.definition, tl_p.chars) = '') AS no_definition, (e.grain IS NULL OR btrim(e.grain, tl_p.chars) = '') AS no_grain,
           (e.refresh IS NULL OR btrim(e.refresh, tl_p.chars) = '') AS no_refresh,
           (e.source_fields IS NULL OR jsonb_typeof(e.source_fields) <> 'array' OR jsonb_array_length(e.source_fields) = 0
            OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(e.source_fields) f WHERE btrim(f, tl_p.chars) = '')) AS no_source_fields,
           NOT EXISTS (SELECT 1 FROM owners o WHERE o.owner_id = e.owner_id) AS no_owner
    FROM eff e, tl_p)
SELECT (SELECT checklist_version FROM tl_p) AS checklist_version, count(*) AS published_metrics,
       count(*) FILTER (WHERE NOT (no_definition OR no_grain OR no_refresh OR no_source_fields OR no_owner)) AS complete_metrics,
       count(*) FILTER (WHERE no_definition OR no_grain OR no_refresh OR no_source_fields OR no_owner) AS incomplete_metrics,
       round(count(*) FILTER (WHERE NOT (no_definition OR no_grain OR no_refresh OR no_source_fields OR no_owner))::numeric / count(*), 6) AS coverage
FROM gap

-- @@ incomplete
-- Each incomplete published metric, the checklist item missing, who owns it, and whether the PREVIOUS version was complete (a change that broke a definition) or the
-- metric never was.
WITH v AS (
    SELECT m.metric_version_id, m.metric_id, m.metric_name, m.version_number, m.status, m.owner_id, m.valid_from,
           concat_ws(',',
               CASE WHEN m.definition IS NULL OR btrim(m.definition, tl_p.chars) = '' THEN 'definition' END,
               CASE WHEN m.grain IS NULL OR btrim(m.grain, tl_p.chars) = '' THEN 'grain' END,
               CASE WHEN m.source_fields IS NULL OR jsonb_typeof(m.source_fields) <> 'array' OR jsonb_array_length(m.source_fields) = 0
                         OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.source_fields) f WHERE btrim(f, tl_p.chars) = '') THEN 'source_fields' END,
               CASE WHEN NOT EXISTS (SELECT 1 FROM owners o WHERE o.owner_id = m.owner_id) THEN 'owner' END,
               CASE WHEN m.refresh IS NULL OR btrim(m.refresh, tl_p.chars) = '' THEN 'refresh' END) AS missing
    FROM metric_versions m, tl_p WHERE m.valid_from <= tl_p.as_of),
eff AS (SELECT DISTINCT ON (metric_id) * FROM v WHERE status = 'published' ORDER BY metric_id, valid_from DESC, version_number DESC)
SELECT e.metric_id, e.metric_name, e.version_number, e.missing AS missing_items, coalesce(e.owner_id, '(none)') AS owner_id,
       CASE WHEN p.metric_version_id IS NULL THEN 'single version'
            WHEN p.missing = '' THEN 'broken by version ' || e.version_number ELSE 'previous version incomplete too' END AS history
FROM eff e LEFT JOIN v p ON p.metric_id = e.metric_id AND p.version_number = e.version_number - 1
WHERE e.missing <> '' ORDER BY e.metric_id COLLATE "C"

-- @@ versions
-- Version history: 15 metrics have a second version, each created with a change record (reason and approver); a published definition is never rewritten.
SELECT count(DISTINCT metric_id) AS metrics, count(*) AS versions, count(DISTINCT metric_id) FILTER (WHERE version_number >= 2) AS metrics_with_more_than_one_version,
       (SELECT count(*) FROM definition_changes) AS change_records,
       (SELECT count(*) FROM metric_versions m WHERE m.version_number >= 2 AND NOT EXISTS (SELECT 1 FROM definition_changes c WHERE c.metric_version_id = m.metric_version_id)) AS versions_without_change_record,
       count(*) FILTER (WHERE status = 'published') AS published_versions, count(*) FILTER (WHERE status = 'superseded') AS superseded_versions
FROM metric_versions

-- @@ regressions
-- Change records whose new version has a checklist item missing that the version it replaced had: a reviewed change that made a definition worse.
WITH v AS (
    SELECT m.*, concat_ws(',',
               CASE WHEN m.definition IS NULL OR btrim(m.definition, tl_p.chars) = '' THEN 'definition' END,
               CASE WHEN m.grain IS NULL OR btrim(m.grain, tl_p.chars) = '' THEN 'grain' END,
               CASE WHEN m.source_fields IS NULL OR jsonb_typeof(m.source_fields) <> 'array' OR jsonb_array_length(m.source_fields) = 0
                         OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.source_fields) f WHERE btrim(f, tl_p.chars) = '') THEN 'source_fields' END,
               CASE WHEN NOT EXISTS (SELECT 1 FROM owners o WHERE o.owner_id = m.owner_id) THEN 'owner' END,
               CASE WHEN m.refresh IS NULL OR btrim(m.refresh, tl_p.chars) = '' THEN 'refresh' END) AS missing
    FROM metric_versions m, tl_p)
SELECT c.change_id, n.metric_id, n.version_number, n.missing AS missing_after, c.approved_by, tl_iso(c.changed_at) AS changed_at
FROM definition_changes c JOIN v n ON n.metric_version_id = c.metric_version_id JOIN v o ON o.metric_version_id = c.previous_metric_version_id
WHERE o.missing = '' AND n.missing <> '' ORDER BY c.change_id COLLATE "C"
