-- TrustLedger reference metrics: an independent recomputation, in SQL, of every metric key of expected.json
-- (completeness, validity, uniqueness, relationship_integrity, timeliness, weighted_score, critical_failures, resolution_time,
-- ownership_coverage, definition_coverage, match_precision, lineage_coverage) plus empty_population.
--
-- Independent of the Python domain: it reads only facts (dataset rows, rules, runs, issues, edges, metric versions, owners,
-- candidates, decisions, weight versions, the configuration) and no stored result. One statement, one row, one jsonb column per metric.
-- Helper functions from 0002_constraints.sql: tl_cell (the exact text of a cell) and tl_iso (an instant as published).
--
-- Parameters (psycopg): %(as_of)s timestamptz; %(wv)s weight version or NULL (the version in force at as_of).
-- Match precision reads the verification layer's table ``verification_truth`` (data/sql/verification_truth.sql), which only a test
-- loads; the table must exist. If a decided record has no truth row, the correct counts and shares are NULL (unknown), never 0.
--
-- Exactness: counts are integers; ratios are NUMERIC rounded once by round() (half away from zero = ROUND_HALF_UP on these
-- non-negative values); hours are epoch seconds / 3600 rounded to 4 places. The local daily schedule uses ``timestamp AT TIME ZONE``:
-- a local time that occurs twice is the later instant, one that does not exist uses the earlier offset (the same as the domain).
WITH
p AS (SELECT %(as_of)s::timestamptz AS as_of),
cfg AS (
    SELECT coalesce((SELECT whitespace_policy ->> 'trim_characters' FROM ledger_config WHERE id = 1), E' \t\r\n') AS chars,
           coalesce((SELECT checklist_version FROM ledger_config WHERE id = 1), 'cl-1') AS checklist_version,
           (SELECT (probes ->> 'definition_at')::timestamptz FROM ledger_config WHERE id = 1) AS probe
),
wv AS (
    SELECT coalesce(%(wv)s::text,
                    (SELECT w.weight_version FROM rule_weight_versions w, p WHERE w.valid_from <= p.as_of
                     ORDER BY w.valid_from DESC, w.weight_version DESC LIMIT 1)) AS v
),
ds AS (SELECT d.* FROM datasets d, p WHERE d.registered_at <= p.as_of),
rules_a AS (
    SELECT r.* FROM quality_rules r JOIN ds ON ds.dataset_id = r.dataset_id, p
    WHERE (r.status = 'active' OR r.disabled_at > p.as_of)
      AND NOT (r.rule_type = 'validity' AND coalesce(r.definition ->> 'pattern', '') = '')      -- a validity rule with no pattern is not measured
),

-- ---- cells of the row-based rules; eligible rows are all rows unless the rule declares a filter {field, equals} ---------------
cells AS (
    SELECT r.rule_id, r.dataset_id, r.severity, r.rule_type AS rt, r.definition AS def, x.ordinal,
           jsonb_typeof(x.data -> (r.definition ->> 'field')) AS typ,
           tl_cell(x.data -> (r.definition ->> 'field')) AS v
    FROM rules_a r
    LEFT JOIN dataset_rows x ON x.dataset_id = r.dataset_id
         AND (r.definition -> 'filter' IS NULL
              OR tl_cell(x.data -> (r.definition -> 'filter' ->> 'field')) IS NOT DISTINCT FROM (r.definition -> 'filter' ->> 'equals'))
    WHERE r.rule_type <> 'timeliness'
),
fl AS (
    SELECT c.*, (c.ordinal IS NOT NULL) AS present,
           (c.ordinal IS NOT NULL AND (c.v IS NULL OR btrim(c.v, cfg.chars) = '')) AS miss
    FROM cells c, cfg
),
comp AS (
    SELECT rule_id, dataset_id, severity, count(*) FILTER (WHERE present) AS el, count(*) FILTER (WHERE miss) AS miss,
           count(*) FILTER (WHERE miss AND v <> '') AS ws
    FROM fl WHERE rt = 'completeness' GROUP BY rule_id, dataset_id, severity
),
val AS (
    SELECT rule_id, dataset_id, severity, count(*) FILTER (WHERE present) AS el, count(*) FILTER (WHERE present AND NOT miss) AS pop,
           count(*) FILTER (WHERE present AND NOT miss AND typ = 'string' AND v ~ (def ->> 'pattern')) AS pass
    FROM fl WHERE rt = 'validity' GROUP BY rule_id, dataset_id, severity
),
freq AS (
    SELECT rule_id, v, count(*) AS n FROM fl WHERE rt = 'uniqueness' AND present AND NOT miss GROUP BY rule_id, v
),
uni AS (
    SELECT f.rule_id, f.dataset_id, f.severity, count(*) FILTER (WHERE f.present) AS el, count(*) FILTER (WHERE f.miss) AS nulls,
           coalesce((SELECT count(*) FROM freq q WHERE q.rule_id = f.rule_id), 0) AS distinct_keys,
           coalesce((SELECT count(*) FROM freq q WHERE q.rule_id = f.rule_id AND q.n > 1), 0) AS groups,
           coalesce((SELECT sum(q.n - 1) FROM freq q WHERE q.rule_id = f.rule_id AND q.n > 1), 0) AS dup_rows
    FROM fl f WHERE f.rt = 'uniqueness' GROUP BY f.rule_id, f.dataset_id, f.severity
),
parent AS (
    SELECT DISTINCT r.rule_id, tl_cell(px.data -> (r.definition ->> 'parent_field')) AS v
    FROM rules_a r
    JOIN dataset_rows px ON px.dataset_id = r.definition ->> 'parent_dataset_id', cfg
    WHERE r.rule_type = 'relationship' AND tl_cell(px.data -> (r.definition ->> 'parent_field')) IS NOT NULL
      AND btrim(tl_cell(px.data -> (r.definition ->> 'parent_field')), cfg.chars) <> ''
),
rel AS (
    SELECT f.rule_id, f.dataset_id, f.severity, count(*) FILTER (WHERE f.present) AS total, count(*) FILTER (WHERE f.miss) AS nulls,
           count(*) FILTER (WHERE f.present AND NOT f.miss AND pr.v IS NOT NULL) AS matched
    FROM fl f LEFT JOIN parent pr ON pr.rule_id = f.rule_id AND pr.v = f.v
    WHERE f.rt = 'relationship' GROUP BY f.rule_id, f.dataset_id, f.severity
),

-- ---- timeliness: the latest daily occurrence (local time in the dataset's IANA zone) whose grace has closed by as_of ---------
tl AS (
    SELECT DISTINCT ON (d.dataset_id) d.dataset_id, d.refresh_timezone AS tz, d.refresh_local_time AS lt, d.refresh_grace_minutes AS gr,
           d.last_refreshed_at AS lr, c.s, c.s + make_interval(mins => d.refresh_grace_minutes) AS dl
    FROM ds d CROSS JOIN p
    CROSS JOIN LATERAL generate_series(-1, 4) AS back
    CROSS JOIN LATERAL (
        SELECT (((p.as_of AT TIME ZONE d.refresh_timezone)::date - back) + d.refresh_local_time::time) AT TIME ZONE d.refresh_timezone AS s
    ) c
    WHERE d.monitored AND c.s + make_interval(mins => d.refresh_grace_minutes) <= p.as_of
    ORDER BY d.dataset_id, back
),
tl2 AS (SELECT tl.*, (lr IS NOT NULL AND s <= lr AND lr < dl) AS on_time FROM tl),

-- ---- one row per active rule: eligible, failing, and the dimension score it contributes ------------------------------------
rm AS (
    SELECT rule_id, dataset_id, severity, 'completeness' AS dim, el, miss AS fail,
           CASE WHEN el = 0 THEN NULL ELSE (el - miss)::numeric / el END AS score FROM comp
    UNION ALL
    SELECT rule_id, dataset_id, severity, 'validity', el, el - pass, CASE WHEN pop = 0 THEN NULL ELSE pass::numeric / pop END FROM val
    UNION ALL
    SELECT rule_id, dataset_id, severity, 'uniqueness', el, nulls + dup_rows, CASE WHEN el = 0 THEN NULL ELSE 1 - dup_rows::numeric / el END FROM uni
    UNION ALL
    SELECT rule_id, dataset_id, severity, 'relationship', total - nulls, (total - nulls) - matched,
           CASE WHEN total - nulls = 0 THEN NULL ELSE matched::numeric / (total - nulls) END FROM rel
    UNION ALL
    SELECT r.rule_id, r.dataset_id, r.severity, 'timeliness', CASE WHEN t.dataset_id IS NULL THEN 0 ELSE 1 END,
           CASE WHEN t.dataset_id IS NOT NULL AND NOT t.on_time THEN 1 ELSE 0 END,
           CASE WHEN t.dataset_id IS NULL THEN NULL WHEN t.on_time THEN 1::numeric ELSE 0::numeric END
    FROM rules_a r LEFT JOIN tl2 t ON t.dataset_id = r.dataset_id WHERE r.rule_type = 'timeliness'
),
dim AS (
    SELECT dataset_id, dim, avg(score) AS score,
           CASE dim WHEN 'completeness' THEN 1 WHEN 'validity' THEN 2 WHEN 'uniqueness' THEN 3 WHEN 'relationship' THEN 4 ELSE 5 END AS idx
    FROM rm WHERE score IS NOT NULL GROUP BY dataset_id, dim
),

-- ---- issues: resolved only by a successful rerun of the same rule version ---------------------------------------------------
iss AS (
    SELECT i.issue_id, r.rule_id, r.severity, r.dataset_id, i.detected_at, i.closed_at, ver.run_at AS ver_at,
           (i.status = 'closed' AND i.closed_at <= p.as_of) AS closed_eff,
           (ver.rule_run_id IS NOT NULL AND ver.run_at <= p.as_of AND ver.kind = 'rerun' AND ver.rerun_for_issue = i.issue_id
            AND ver.rule_id = br.rule_id AND ver.rule_version = br.rule_version AND ver.failure_count = 0
            AND ver.run_at >= i.detected_at
            AND ver.run_at >= coalesce((SELECT max(t) FROM unnest(i.reopened_at) t WHERE t <= p.as_of), ver.run_at)) AS verified,
           (SELECT count(*) FROM unnest(i.reopened_at) t WHERE t <= p.as_of) AS cycles
    FROM issues i
    JOIN rule_runs br ON br.rule_run_id = i.rule_run_id
    JOIN quality_rules r ON r.rule_id = br.rule_id
    JOIN ds ON ds.dataset_id = r.dataset_id
    LEFT JOIN rule_runs ver ON ver.rule_run_id = i.verification_run_id, p
    WHERE i.detected_at <= p.as_of AND br.run_at <= p.as_of
),
iss2 AS (
    SELECT iss.*, CASE WHEN closed_eff AND verified THEN 'resolved' WHEN closed_eff THEN 'claimed' ELSE 'open' END AS cls FROM iss
),
iss3 AS (
    SELECT iss2.*, extract(epoch FROM (CASE cls WHEN 'resolved' THEN ver_at WHEN 'claimed' THEN closed_at ELSE p.as_of END - detected_at))::numeric / 3600 AS hrs
    FROM iss2, p
),

-- ---- ownership, definitions, lineage, matching -----------------------------------------------------------------------------
own AS (
    SELECT d.dataset_id, (o.owner_id IS NOT NULL AND CASE WHEN o.deactivated_at IS NOT NULL THEN p.as_of < o.deactivated_at ELSE o.active END) AS covered
    FROM ds d LEFT JOIN owners o ON o.owner_id = d.owner_id, p
),
mv AS (SELECT m.* FROM metric_versions m, p WHERE m.valid_from <= p.as_of),
eff AS (
    SELECT DISTINCT ON (metric_id) * FROM mv WHERE status IN ('published', 'superseded') ORDER BY metric_id, valid_from DESC, version_number DESC
),
chk AS (
    SELECT coalesce((SELECT items FROM checklist_versions c WHERE c.checklist_version = cfg.checklist_version),
                    '["definition","grain","source_fields","owner","refresh"]'::jsonb) AS items
    FROM cfg
),
gaps AS (
    SELECT e.metric_id, e.metric_version_id,
           coalesce(jsonb_agg(it.item ORDER BY it.ord) FILTER (WHERE NOT coalesce(CASE it.item
               WHEN 'definition' THEN e.definition IS NOT NULL AND btrim(e.definition, cfg.chars) <> ''
               WHEN 'grain' THEN e.grain IS NOT NULL AND btrim(e.grain, cfg.chars) <> ''
               WHEN 'refresh' THEN e.refresh IS NOT NULL AND btrim(e.refresh, cfg.chars) <> ''
               WHEN 'source_fields' THEN jsonb_typeof(e.source_fields) = 'array' AND jsonb_array_length(e.source_fields) > 0
                    AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(e.source_fields) s WHERE btrim(s #>> '{}', cfg.chars) = '')
               WHEN 'owner' THEN EXISTS (SELECT 1 FROM owners o WHERE o.owner_id = e.owner_id)
               ELSE false END, false)), '[]'::jsonb) AS missing
    FROM eff e CROSS JOIN cfg CROSS JOIN chk
    CROSS JOIN LATERAL jsonb_array_elements_text(chk.items) WITH ORDINALITY AS it (item, ord)
    WHERE e.status = 'published' GROUP BY e.metric_id, e.metric_version_id
),
le AS (SELECT e.* FROM lineage_edges e, p WHERE e.observed_at IS NULL OR e.observed_at <= p.as_of),
dec AS (SELECT DISTINCT source_dataset_id AS s, target_dataset_id AS t FROM le WHERE evidence_type = 'declared'),
obs AS (SELECT DISTINCT source_dataset_id AS s, target_dataset_id AS t FROM le WHERE evidence_type = 'observed'),
inf AS (SELECT DISTINCT source_dataset_id AS s, target_dataset_id AS t FROM le WHERE evidence_type = 'inferred'),
cand AS (SELECT c.* FROM match_candidates c, p WHERE c.proposed_at <= p.as_of),
mdec AS (SELECT m.* FROM merge_decisions m JOIN cand c ON c.candidate_id = m.candidate_id, p WHERE m.decided_at <= p.as_of),
appr AS (SELECT DISTINCT c.candidate_id, c.left_record_id AS l, c.right_record_id AS r FROM mdec m JOIN cand c ON c.candidate_id = m.candidate_id WHERE m.decision = 'approve'),
revd AS (
    SELECT DISTINCT c.candidate_id, c.left_record_id AS l, c.right_record_id AS r
    FROM mdec m JOIN cand c ON c.candidate_id = m.candidate_id WHERE m.decision IN ('approve', 'reject')
),
known AS (
    SELECT NOT EXISTS (SELECT 1 FROM revd x CROSS JOIN LATERAL (VALUES (x.l), (x.r)) AS rec (id)
                       WHERE NOT EXISTS (SELECT 1 FROM verification_truth t WHERE t.record_id = rec.id)) AS ok
),
same AS (
    SELECT x.candidate_id FROM revd x
    JOIN verification_truth tl_ ON tl_.record_id = x.l JOIN verification_truth tr ON tr.record_id = x.r WHERE tl_.true_entity = tr.true_entity
)
SELECT
    -- completeness
    (SELECT coalesce(jsonb_object_agg(rule_id, jsonb_build_object(
        'dataset_id', dataset_id, 'eligible_count', el, 'missing_count', miss, 'whitespace_only_count', ws, 'populated_count', el - miss,
        'value', round((el - miss)::numeric / NULLIF(el, 0), 6)::text)), '{}'::jsonb) FROM comp) AS completeness,
    -- validity (all-eligible and populated-only, both labelled)
    (SELECT coalesce(jsonb_object_agg(rule_id, jsonb_build_object(
        'dataset_id', dataset_id, 'eligible_count', el, 'populated_count', pop, 'passing_count', pass,
        'all_eligible', jsonb_build_object('label', 'validity_all_eligible', 'value', round(pass::numeric / NULLIF(el, 0), 6)::text),
        'populated_only', jsonb_build_object('label', 'validity_populated_only', 'value', round(pass::numeric / NULLIF(pop, 0), 6)::text))),
        '{}'::jsonb) FROM val) AS validity,
    -- uniqueness (group share and row share)
    (SELECT coalesce(jsonb_object_agg(rule_id, jsonb_build_object(
        'dataset_id', dataset_id, 'eligible_count', el, 'null_key_count', nulls, 'distinct_keys', distinct_keys,
        'duplicate_groups', groups, 'duplicate_rows', dup_rows,
        'group_share', jsonb_build_object('label', 'duplicate_group_share', 'value', round(groups::numeric / NULLIF(distinct_keys, 0), 6)::text),
        'row_share', jsonb_build_object('label', 'duplicate_row_share', 'value', round(dup_rows::numeric / NULLIF(el, 0), 6)::text))),
        '{}'::jsonb) FROM uni) AS uniqueness,
    -- relationship integrity (null foreign keys counted separately)
    (SELECT coalesce(jsonb_object_agg(rule_id, jsonb_build_object(
        'dataset_id', dataset_id, 'total_fk_count', total, 'null_fk_count', nulls, 'eligible_count', total - nulls,
        'matched_count', matched, 'unmatched_count', (total - nulls) - matched,
        'value', round(matched::numeric / NULLIF(total - nulls, 0), 6)::text)), '{}'::jsonb) FROM rel) AS relationship_integrity,
    -- timeliness
    jsonb_build_object(
        'monitored_datasets', (SELECT count(*) FROM tl2), 'on_time_count', (SELECT count(*) FROM tl2 WHERE on_time),
        'value', (SELECT round(count(*) FILTER (WHERE on_time)::numeric / NULLIF(count(*), 0), 6)::text FROM tl2),
        'datasets', (SELECT coalesce(jsonb_object_agg(dataset_id, jsonb_build_object(
            'timezone', tz, 'scheduled_local', lt, 'grace_minutes', gr, 'evaluated_occurrence_utc', tl_iso(s), 'deadline_utc', tl_iso(dl),
            'last_refreshed_at', tl_iso(lr), 'on_time', on_time)), '{}'::jsonb) FROM tl2)) AS timeliness,
    -- weighted score under the named weight version, per dataset, and under every version
    (SELECT jsonb_build_object(
        'datasets', (SELECT coalesce(jsonb_object_agg(d.dataset_id, jsonb_build_object(
            'weight_version', wv.v,
            'dimension_scores', (SELECT coalesce(jsonb_object_agg(x.dim, round(x.score, 6)::text), '{}'::jsonb) FROM dim x WHERE x.dataset_id = d.dataset_id),
            'measured_dimensions', (SELECT coalesce(jsonb_agg(x.dim ORDER BY x.idx), '[]'::jsonb) FROM dim x WHERE x.dataset_id = d.dataset_id),
            'weight_sum', round(coalesce((SELECT sum((w.weights ->> x.dim)::numeric) FROM dim x JOIN rule_weight_versions w ON w.weight_version = wv.v
                                          WHERE x.dataset_id = d.dataset_id), 0), 6)::text,
            'value', (SELECT round(sum((w.weights ->> x.dim)::numeric * x.score) / NULLIF(sum((w.weights ->> x.dim)::numeric), 0), 6)::text
                      FROM dim x JOIN rule_weight_versions w ON w.weight_version = wv.v WHERE x.dataset_id = d.dataset_id),
            'critical_failures', coalesce((SELECT sum(m.fail) FROM rm m WHERE m.dataset_id = d.dataset_id AND m.severity = 'critical'), 0),
            'critical_open_issues', (SELECT count(*) FROM iss2 i WHERE i.dataset_id = d.dataset_id AND i.severity = 'critical' AND i.cls <> 'resolved'),
            'critical_override', coalesce((SELECT sum(m.fail) FROM rm m WHERE m.dataset_id = d.dataset_id AND m.severity = 'critical'), 0) > 0
                OR EXISTS (SELECT 1 FROM iss2 i WHERE i.dataset_id = d.dataset_id AND i.severity = 'critical' AND i.cls <> 'resolved'))),
            '{}'::jsonb) FROM ds d, wv),
        'by_weight_version', (SELECT coalesce(jsonb_object_agg(w.weight_version, (
            SELECT coalesce(jsonb_object_agg(d.dataset_id, (
                SELECT round(sum((w.weights ->> x.dim)::numeric * x.score) / NULLIF(sum((w.weights ->> x.dim)::numeric), 0), 6)::text
                FROM dim x WHERE x.dataset_id = d.dataset_id)), '{}'::jsonb) FROM ds d)), '{}'::jsonb) FROM rule_weight_versions w))) AS weighted_score,
    -- critical failures and open critical issues, counted apart from any score
    jsonb_build_object(
        'failures', coalesce((SELECT sum(fail) FROM rm WHERE severity = 'critical'), 0),
        'open_issues', (SELECT count(*) FROM iss2 WHERE severity = 'critical' AND cls <> 'resolved'),
        'datasets_overridden', (SELECT count(*) FROM ds d WHERE coalesce((SELECT sum(m.fail) FROM rm m WHERE m.dataset_id = d.dataset_id AND m.severity = 'critical'), 0) > 0
            OR EXISTS (SELECT 1 FROM iss2 i WHERE i.dataset_id = d.dataset_id AND i.severity = 'critical' AND i.cls <> 'resolved'))) AS critical_failures,
    -- resolution time
    jsonb_build_object(
        'resolved_count', (SELECT count(*) FROM iss3 WHERE cls = 'resolved'), 'claimed_count', (SELECT count(*) FROM iss3 WHERE cls = 'claimed'),
        'open_count', (SELECT count(*) FROM iss3 WHERE cls = 'open'), 'reopened_count', (SELECT count(*) FROM iss3 WHERE cycles > 0),
        'reopen_cycles_total', (SELECT coalesce(sum(cycles), 0) FROM iss3),
        'mean_hours', (SELECT round(avg(hrs), 4)::text FROM iss3 WHERE cls = 'resolved'),
        'issues', (SELECT coalesce(jsonb_object_agg(issue_id, jsonb_build_object(
            'rule_id', rule_id, 'severity', severity, 'class', cls,
            'resolution_hours', CASE WHEN cls = 'resolved' THEN round(hrs, 4)::text END,
            'claimed_hours', CASE WHEN cls = 'claimed' THEN round(hrs, 4)::text END,
            'age_hours', CASE WHEN cls = 'open' THEN round(hrs, 4)::text END, 'reopen_cycles', cycles)), '{}'::jsonb) FROM iss3)) AS resolution_time,
    -- ownership coverage (an inactive owner leaves the dataset uncovered)
    jsonb_build_object(
        'datasets', (SELECT count(*) FROM own), 'covered', (SELECT count(*) FROM own WHERE covered),
        'value', (SELECT round(count(*) FILTER (WHERE covered)::numeric / NULLIF(count(*), 0), 6)::text FROM own),
        'uncovered', (SELECT coalesce(jsonb_agg(dataset_id ORDER BY dataset_id COLLATE "C"), '[]'::jsonb) FROM own WHERE NOT covered)) AS ownership_coverage,
    -- definition coverage under the named checklist version
    jsonb_build_object(
        'checklist_version', (SELECT checklist_version FROM cfg),
        'published_metrics', (SELECT count(*) FROM eff WHERE status = 'published'),
        'complete_metrics', (SELECT count(*) FROM gaps WHERE jsonb_array_length(missing) = 0),
        'value', (SELECT round(count(*) FILTER (WHERE jsonb_array_length(missing) = 0)::numeric / NULLIF(count(*), 0), 6)::text FROM gaps),
        'incomplete', (SELECT coalesce(jsonb_object_agg(metric_id, missing), '{}'::jsonb) FROM gaps WHERE jsonb_array_length(missing) > 0)) AS definition_coverage,
    -- match precision: approved decisions confirmed by the verification layer's truth / approved decisions
    jsonb_build_object(
        'approved_decisions', (SELECT count(*) FROM appr),
        'approved_correct', (SELECT CASE WHEN ok THEN (SELECT count(*) FROM appr WHERE candidate_id IN (SELECT candidate_id FROM same)) END FROM known),
        'precision', (SELECT CASE WHEN ok THEN round((SELECT count(*) FROM appr WHERE candidate_id IN (SELECT candidate_id FROM same))::numeric
                                                     / NULLIF((SELECT count(*) FROM appr), 0), 6)::text END FROM known),
        'reviewed', (SELECT count(*) FROM revd),
        'reviewed_correct', (SELECT CASE WHEN ok THEN (SELECT count(*) FROM same) END FROM known),
        'reviewed_correct_share', (SELECT CASE WHEN ok THEN round((SELECT count(*) FROM same)::numeric / NULLIF((SELECT count(*) FROM revd), 0), 6)::text END FROM known)
    ) AS match_precision,
    -- lineage coverage over distinct pairs; undeclared observed pairs are listed
    jsonb_build_object(
        'declared_edges', (SELECT count(*) FROM dec), 'observed_rows', (SELECT count(*) FROM le WHERE evidence_type = 'observed'),
        'observed_distinct', (SELECT count(*) FROM obs),
        'observed_matching_declared', (SELECT count(*) FROM dec JOIN obs USING (s, t)),
        'value', (SELECT round((SELECT count(*) FROM dec JOIN obs USING (s, t))::numeric / NULLIF(count(*), 0), 6)::text FROM dec),
        'undeclared_observed', (SELECT coalesce(jsonb_agg(jsonb_build_object('source_dataset_id', s, 'target_dataset_id', t)
                                ORDER BY s COLLATE "C", t COLLATE "C"), '[]'::jsonb) FROM obs WHERE NOT EXISTS (SELECT 1 FROM dec WHERE dec.s = obs.s AND dec.t = obs.t)),
        'declared_not_observed', (SELECT coalesce(jsonb_agg(jsonb_build_object('source_dataset_id', s, 'target_dataset_id', t)
                                  ORDER BY s COLLATE "C", t COLLATE "C"), '[]'::jsonb) FROM dec WHERE NOT EXISTS (SELECT 1 FROM obs WHERE dec.s = obs.s AND dec.t = obs.t)),
        'inferred_edges', (SELECT coalesce(jsonb_agg(jsonb_build_object('source_dataset_id', s, 'target_dataset_id', t)
                           ORDER BY s COLLATE "C", t COLLATE "C"), '[]'::jsonb) FROM inf)) AS lineage_coverage,
    (0 = (SELECT count(*) FROM owners) + (SELECT count(*) FROM datasets) + (SELECT count(*) FROM fields) + (SELECT count(*) FROM quality_rules)
       + (SELECT count(*) FROM rule_runs) + (SELECT count(*) FROM issues) + (SELECT count(*) FROM lineage_edges)
       + (SELECT count(*) FROM metric_versions) + (SELECT count(*) FROM definition_changes) + (SELECT count(*) FROM customer_records)
       + (SELECT count(*) FROM match_candidates) + (SELECT count(*) FROM merge_decisions) + (SELECT count(*) FROM dataset_rows)) AS empty_population
