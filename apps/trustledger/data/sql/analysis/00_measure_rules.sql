-- P07-ART-04 setup: the as-of, the active rules, their row-level measurement and the issue classes, into TEMPORARY tables for investigations 01..10.
-- Read only: it creates temporary tables in the session and writes nothing to the loaded schema. Run by data/sql/analysis/run_all.py (blocks marked `-- @@ name`,
-- one statement each). This is the analysis's OWN formulation of the D-01..D-10 measurement; it shares no text with data/sql/reference_metrics.sql, and
-- run_all.py reconciles every figure taken from these tables with that reference, with the Python domain and with the published manifests.
--
-- Population. The as-of is the loaded dataset version's as_of (dataset_versions.as_of). Datasets registered after it, rules disabled before it, runs and issues
-- after it do not exist yet. The loaded rows carry no row corrections (C11) and no recorded refreshes (C12); run_all.py asserts that, so "the row" is the
-- row as loaded. Cells are compared as exact text; a value is missing when it is null or, after trimming the whitespace policy's characters, empty (D-06).

-- @@ p
CREATE TEMP TABLE tl_p AS
SELECT v.as_of, c.chars, c.checklist_version,
       (SELECT w.weight_version FROM rule_weight_versions w WHERE w.valid_from <= v.as_of ORDER BY w.valid_from DESC, w.weight_version DESC LIMIT 1) AS wv_in_force
FROM (SELECT as_of FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1) v,
     (SELECT coalesce(whitespace_policy ->> 'trim_characters', E' \t\r\n') AS chars, checklist_version FROM ledger_config WHERE id = 1) c

-- @@ rows
CREATE TEMP TABLE tl_rows AS
SELECT DISTINCT ON (x.dataset_id, x.row_id) x.dataset_id, x.row_id, x.ordinal, x.data
FROM dataset_rows x, tl_p
WHERE x.recorded_at IS NULL OR x.recorded_at <= tl_p.as_of
ORDER BY x.dataset_id, x.row_id, x.row_version DESC

-- @@ rules
CREATE TEMP TABLE tl_rules AS
SELECT r.rule_id, r.dataset_id, r.rule_type, r.severity, r.version_number, r.status, r.disabled_at, r.definition
FROM quality_rules r JOIN datasets d ON d.dataset_id = r.dataset_id, tl_p
WHERE d.registered_at <= tl_p.as_of AND (r.status = 'active' OR r.disabled_at > tl_p.as_of)
  AND NOT (r.rule_type = 'validity' AND coalesce(r.definition ->> 'pattern', '') = '')

-- @@ cells
CREATE TEMP TABLE tl_cells AS
SELECT r.rule_id, r.rule_type, x.row_id, x.ordinal, jsonb_typeof(x.data -> (r.definition ->> 'field')) AS typ,
       x.data ->> (r.definition ->> 'field') AS v,
       (x.data ->> (r.definition ->> 'field')) IS NULL OR btrim(x.data ->> (r.definition ->> 'field'), tl_p.chars) = '' AS is_missing
FROM tl_rules r JOIN tl_rows x ON x.dataset_id = r.dataset_id, tl_p
WHERE r.rule_type IN ('completeness', 'validity', 'uniqueness', 'relationship')
  AND (r.definition -> 'filter' IS NULL OR (x.data ->> (r.definition -> 'filter' ->> 'field')) IS NOT DISTINCT FROM (r.definition -> 'filter' ->> 'equals'))

-- @@ probes
-- The instants at which timeliness is judged: the as-of first, then three probes the same facts are read at (investigation 08). A probe after the as-of reads the
-- loaded refreshes not after it; nothing else (runs, issues) is read at a probe.
CREATE TEMP TABLE tl_probes AS
SELECT 0 AS seq, 'as-of'::text AS label, as_of AS at FROM tl_p
UNION ALL SELECT 1, 'as-of + 10h30m', as_of + interval '10 hours 30 minutes' FROM tl_p
UNION ALL SELECT 2, 'as-of + 13h', as_of + interval '13 hours' FROM tl_p
UNION ALL SELECT 3, 'as-of + 25h', as_of + interval '25 hours' FROM tl_p

-- @@ timeliness
-- The latest daily occurrence (the dataset's local time in its IANA zone) that has STARTED by the probe; on time when a refresh not after the probe lies in
-- [occurrence, occurrence + grace); otherwise pending while the deadline is in the future; otherwise late. A local time that occurs twice is the later instant.
CREATE TEMP TABLE tl_tstate AS
SELECT DISTINCT ON (pr.seq, d.dataset_id) pr.seq, pr.label, pr.at, d.dataset_id, d.refresh_timezone AS tz, d.refresh_local_time AS local_time, d.refresh_grace_minutes AS grace,
       occ.s AS occurrence, occ.s + make_interval(mins => d.refresh_grace_minutes) AS deadline, lr.t AS last_refresh,
       CASE WHEN lr.t IS NOT NULL AND lr.t >= occ.s AND lr.t < occ.s + make_interval(mins => d.refresh_grace_minutes) THEN 'on_time'
            WHEN occ.s + make_interval(mins => d.refresh_grace_minutes) > pr.at THEN 'pending' ELSE 'late' END AS state
FROM tl_probes pr
JOIN datasets d ON d.monitored AND d.registered_at <= (SELECT as_of FROM tl_p)
CROSS JOIN LATERAL generate_series(0, 6) AS back
CROSS JOIN LATERAL (SELECT (((pr.at AT TIME ZONE d.refresh_timezone)::date - back) + d.refresh_local_time::time) AT TIME ZONE d.refresh_timezone AS s) occ
CROSS JOIN LATERAL (SELECT max(t) AS t FROM (SELECT d.last_refreshed_at AS t UNION ALL SELECT f.refreshed_at FROM dataset_refreshes f WHERE f.dataset_id = d.dataset_id) z
                    WHERE z.t <= pr.at) lr
WHERE occ.s <= pr.at
ORDER BY pr.seq, d.dataset_id, occ.s DESC

-- @@ measure
-- One row per active rule: what it measured at the as-of, the failing count (the contract's: missing, not passing, null-key plus duplicate rows, unmatched, late)
-- and the score it contributes to its dimension (null when it measures nothing: no eligible value, an unmonitored or pending dataset).
CREATE TEMP TABLE tl_rule_measure AS
WITH comp AS (
    SELECT rule_id, count(*) AS el, count(*) FILTER (WHERE is_missing) AS miss FROM tl_cells WHERE rule_type = 'completeness' GROUP BY rule_id),
val AS (
    SELECT c.rule_id, count(*) AS el, count(*) FILTER (WHERE NOT c.is_missing) AS pop,
           count(*) FILTER (WHERE NOT c.is_missing AND c.typ = 'string' AND c.v ~ (r.definition ->> 'pattern')) AS pass
    FROM tl_cells c JOIN tl_rules r USING (rule_id) WHERE c.rule_type = 'validity' GROUP BY c.rule_id),
keyfreq AS (
    SELECT rule_id, v, count(*) AS n FROM tl_cells WHERE rule_type = 'uniqueness' AND NOT is_missing GROUP BY rule_id, v),
uni AS (
    SELECT c.rule_id, count(*) AS el, count(*) FILTER (WHERE c.is_missing) AS nulls,
           coalesce((SELECT sum(k.n - 1) FROM keyfreq k WHERE k.rule_id = c.rule_id AND k.n > 1), 0) AS dups
    FROM tl_cells c WHERE c.rule_type = 'uniqueness' GROUP BY c.rule_id),
parent AS (
    SELECT DISTINCT r.rule_id, p.data ->> (r.definition ->> 'parent_field') AS v
    FROM tl_rules r JOIN tl_rows p ON p.dataset_id = r.definition ->> 'parent_dataset_id', tl_p
    WHERE r.rule_type = 'relationship' AND p.data ->> (r.definition ->> 'parent_field') IS NOT NULL
      AND btrim(p.data ->> (r.definition ->> 'parent_field'), tl_p.chars) <> ''),
rel AS (
    SELECT c.rule_id, count(*) AS total, count(*) FILTER (WHERE c.is_missing) AS nulls,
           count(*) FILTER (WHERE NOT c.is_missing AND EXISTS (SELECT 1 FROM parent q WHERE q.rule_id = c.rule_id AND q.v = c.v)) AS matched
    FROM tl_cells c WHERE c.rule_type = 'relationship' GROUP BY c.rule_id)
SELECT r.rule_id, r.dataset_id, r.rule_type AS dimension, r.severity, r.version_number,
       CASE r.rule_type WHEN 'completeness' THEN coalesce(comp.el, 0)
                        WHEN 'validity' THEN coalesce(val.el, 0)
                        WHEN 'uniqueness' THEN coalesce(uni.el, 0)
                        WHEN 'relationship' THEN coalesce(rel.total, 0) - coalesce(rel.nulls, 0)
                        ELSE CASE WHEN t.state IS NULL OR t.state = 'pending' THEN 0 ELSE 1 END END AS eligible,
       CASE r.rule_type WHEN 'completeness' THEN coalesce(comp.el, 0) - coalesce(comp.miss, 0)
                        WHEN 'validity' THEN coalesce(val.pop, 0)
                        ELSE NULL END AS populated,
       CASE r.rule_type WHEN 'completeness' THEN coalesce(comp.miss, 0)
                        WHEN 'validity' THEN coalesce(val.el, 0) - coalesce(val.pass, 0)
                        WHEN 'uniqueness' THEN coalesce(uni.nulls, 0) + coalesce(uni.dups, 0)
                        WHEN 'relationship' THEN coalesce(rel.total, 0) - coalesce(rel.nulls, 0) - coalesce(rel.matched, 0)
                        ELSE CASE WHEN t.state = 'late' THEN 1 ELSE 0 END END AS failing,
       CASE r.rule_type WHEN 'completeness' THEN CASE WHEN comp.el > 0 THEN (comp.el - comp.miss)::numeric / comp.el END
                        WHEN 'validity' THEN CASE WHEN val.pop > 0 THEN val.pass::numeric / val.pop END
                        WHEN 'uniqueness' THEN CASE WHEN uni.el > 0 THEN (uni.el - uni.nulls - uni.dups)::numeric / uni.el END
                        WHEN 'relationship' THEN CASE WHEN rel.total - rel.nulls > 0 THEN rel.matched::numeric / (rel.total - rel.nulls) END
                        ELSE CASE t.state WHEN 'on_time' THEN 1::numeric WHEN 'late' THEN 0::numeric END END AS score
FROM tl_rules r
LEFT JOIN comp USING (rule_id) LEFT JOIN val USING (rule_id) LEFT JOIN uni USING (rule_id) LEFT JOIN rel USING (rule_id)
LEFT JOIN tl_tstate t ON t.seq = 0 AND t.dataset_id = r.dataset_id AND r.rule_type = 'timeliness'

-- @@ dimension
-- A dimension's score on a dataset is the plain mean of the scores of its measured rules (D-07 assumption 5).
CREATE TEMP TABLE tl_dim AS
SELECT dataset_id, dimension, count(*) AS rules, avg(score) AS score
FROM tl_rule_measure WHERE score IS NOT NULL GROUP BY dataset_id, dimension

-- @@ issue
-- The issue classes (D-03): `resolved` only when the issue is closed AND its verification run is a successful rerun (failure count 0) of the SAME rule at the SAME
-- rule version, made for this issue, not before its detection and not before its latest reopen; `claimed` when closed without that; `open` otherwise (open,
-- investigating, reopened). Hours: resolved = verifying rerun - first detected_at; claimed = close - detected_at; open = as-of - detected_at.
CREATE TEMP TABLE tl_issue AS
WITH b AS (
    SELECT i.issue_id, i.rule_run_id, i.severity, i.status, i.owner_id, i.detected_at, i.due_at, i.closed_at, i.reopened_at, i.verification_run_id,
           br.rule_id, br.rule_version AS base_version, r.dataset_id, d.owner_id AS dataset_owner_id,
           v.run_at AS ver_at, v.kind AS ver_kind, v.rerun_for_issue AS ver_for, v.rule_id AS ver_rule, v.rule_version AS ver_version, v.failure_count AS ver_fail,
           (SELECT count(*) FROM unnest(i.reopened_at) t WHERE t <= tl_p.as_of) AS cycles,
           (SELECT max(t) FROM unnest(i.reopened_at) t WHERE t <= tl_p.as_of) AS last_reopen,
           tl_p.as_of
    FROM issues i
    JOIN rule_runs br ON br.rule_run_id = i.rule_run_id
    JOIN quality_rules r ON r.rule_id = br.rule_id
    JOIN datasets d ON d.dataset_id = r.dataset_id
    LEFT JOIN rule_runs v ON v.rule_run_id = i.verification_run_id, tl_p
    WHERE i.detected_at <= tl_p.as_of AND br.run_at <= tl_p.as_of AND d.registered_at <= tl_p.as_of),
c AS (
    SELECT b.*, (b.status = 'closed' AND b.closed_at <= b.as_of) AS closed_eff,
           (b.ver_at IS NOT NULL AND b.ver_at <= b.as_of AND b.ver_kind = 'rerun' AND b.ver_for = b.issue_id AND b.ver_rule = b.rule_id
            AND b.ver_version = b.base_version AND b.ver_fail = 0 AND b.ver_at >= b.detected_at AND (b.last_reopen IS NULL OR b.ver_at >= b.last_reopen)) AS verified
    FROM b)
SELECT c.*, CASE WHEN closed_eff AND verified THEN 'resolved' WHEN closed_eff THEN 'claimed' ELSE 'open' END AS class,
       extract(epoch FROM (CASE WHEN closed_eff AND verified THEN ver_at WHEN closed_eff THEN closed_at ELSE as_of END) - detected_at)::numeric / 3600 AS hours
FROM c
