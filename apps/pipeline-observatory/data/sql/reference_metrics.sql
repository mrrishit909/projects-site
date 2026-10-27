-- Pipeline Observatory reference metrics: an independent recomputation, in SQL, of the headline metrics of expected.json
-- (ingestion counts and rates, freshness versus ingestion age, completeness against the declared expectation, task versus attempt success,
-- run durations, gate decisions and the publication pointer, publication lag, late events, reconciliation residual with its parts,
-- verified recovery seconds, backfill coverage, observed processing rate) plus empty_population.
--
-- Independent of the Python domain: it reads only facts (raw rows with their payloads, batches, checkpoints, expectations, runs, tasks,
-- quality results, publications, incidents, backfill requests, the measurement) and NEVER the stored columns that record a classification
-- (raw_records.disposition / reason_code, accepted_records): every row is classified here by the rule of D-P8-01. The key check comes
-- before the contract check, so after the first valid row of a key (in checkpoint-version order within its source) every later row of that key
-- is a duplicate, and rows of the key before it are quarantined. Delete events are not modelled here (the domain tests cover them).
--
-- Parameter (psycopg): %(cutoff)s timestamptz. One statement, one row, one jsonb column per metric (same keys and nesting as expected.json).
-- Exactness: counts are integers; ratios are NUMERIC rounded once by round() (half away from zero = ROUND_HALF_UP on these values);
-- money is NUMERIC rounded to 2 places by round(); seconds are floor()ed (as timedelta does), minutes are round(seconds / 60, 4). Text collation is "C" wherever Python sorts strings.
WITH
p AS (SELECT %(cutoff)s::timestamptz AS cutoff),
cb AS (                                                -- committed batches in the order they were applied within their source
    SELECT b.batch_id, b.source_id, b.started_at, b.schema_version AS batch_schema, c.version_number, c.committed_at, c.committed_cursor,
           row_number() OVER (PARTITION BY b.source_id
                              ORDER BY coalesce(c.version_number, 1000000000), b.started_at, b.batch_id COLLATE "C") AS apply_order
    FROM ingestion_batches b LEFT JOIN checkpoints c ON c.batch_id = b.batch_id
    WHERE b.status = 'committed'
),
rw AS (                                                -- every raw row of a committed batch, with its contract verdict
    SELECT r.raw_record_id, r.batch_id, r.source_key, r.payload_hash, r.payload_json AS pj, cb.source_id, cb.apply_order, cb.committed_at,
           cb.started_at AS arrived,
           (cb.batch_schema IS NOT NULL AND cb.batch_schema <> sc.schema_version) AS schema_changed,
           (jsonb_typeof(r.payload_json) = 'object'
            AND r.payload_json ? 'record_id' AND r.payload_json ? 'quantity' AND r.payload_json ? 'unit_price' AND r.payload_json ? 'amount'
            AND r.payload_json ? 'event_ts'
            AND jsonb_typeof(r.payload_json -> 'record_id') <> 'null' AND jsonb_typeof(r.payload_json -> 'quantity') <> 'null'
            AND jsonb_typeof(r.payload_json -> 'unit_price') <> 'null' AND jsonb_typeof(r.payload_json -> 'amount') <> 'null'
            AND jsonb_typeof(r.payload_json -> 'event_ts') <> 'null') AS has_all
    FROM raw_records r JOIN cb ON cb.batch_id = r.batch_id JOIN source_contracts sc ON sc.source_id = cb.source_id
),
-- D-09 patterns (R8-04/05): ASCII digits only, FULL match (\A ... \Z: no newline exception), an instant must be a real calendar instant and its
-- digits beyond microseconds are TRUNCATED, never rounded (PostgreSQL's own cast would round 08:00:00.9999995 up to 08:00:01).
tsp AS (
    SELECT rw.*,
           CASE WHEN jsonb_typeof(rw.pj) = 'object' AND jsonb_typeof(rw.pj -> 'event_ts') = 'string' THEN
               regexp_match(rw.pj ->> 'event_ts', '\A([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})\Z') END AS m
    FROM rw
),
tsv AS (
    SELECT tsp.*,
           (tsp.m IS NOT NULL
            AND (tsp.m[1])::int >= 1 AND (tsp.m[2])::int BETWEEN 1 AND 12
            AND (tsp.m[3])::int BETWEEN 1 AND (CASE (tsp.m[2])::int
                    WHEN 2 THEN CASE WHEN (mod((tsp.m[1])::int, 4) = 0 AND mod((tsp.m[1])::int, 100) <> 0) OR mod((tsp.m[1])::int, 400) = 0 THEN 29 ELSE 28 END
                    WHEN 4 THEN 30 WHEN 6 THEN 30 WHEN 9 THEN 30 WHEN 11 THEN 30 ELSE 31 END)
            AND (tsp.m[4])::int <= 23 AND (tsp.m[5])::int <= 59 AND (tsp.m[6])::int <= 59
            AND (tsp.m[8] = 'Z' OR ((substr(tsp.m[8], 2, 2))::int <= 23 AND (substr(tsp.m[8], 5, 2))::int <= 59))) AS ts_shape
    FROM tsp
),
tsw AS (
    SELECT tsv.*,
           CASE WHEN tsv.ts_shape THEN
               (tsv.m[1] || '-' || tsv.m[2] || '-' || tsv.m[3] || ' ' || tsv.m[4] || ':' || tsv.m[5] || ':' || tsv.m[6] || '.'
                || rpad(substr(coalesce(tsv.m[7], ''), 1, 6), 6, '0') || ' UTC')::timestamptz
               - (CASE WHEN tsv.m[8] = 'Z' THEN 0 ELSE (CASE WHEN left(tsv.m[8], 1) = '-' THEN -1 ELSE 1 END)
                                                         * ((substr(tsv.m[8], 2, 2))::int * 60 + (substr(tsv.m[8], 5, 2))::int) END) * interval '1 minute'
           END AS ev_raw
    FROM tsv
),
rv AS (
    SELECT tsw.*, (tsw.ts_shape AND tsw.ev_raw >= timestamptz '0001-01-01 00:00:00 UTC' AND tsw.ev_raw <= timestamptz '9999-12-31 23:59:59.999999 UTC') AS ts_ok,
           (jsonb_typeof(tsw.pj) = 'object' AND jsonb_typeof(tsw.pj -> 'unit_price') = 'string' AND (tsw.pj ->> 'unit_price') ~ '\A-?[0-9]+(\.[0-9]{1,2})?\Z') AS up_ok,
           (jsonb_typeof(tsw.pj) = 'object' AND jsonb_typeof(tsw.pj -> 'amount') = 'string' AND (tsw.pj ->> 'amount') ~ '\A-?[0-9]+(\.[0-9]{1,2})?\Z') AS am_ok,
           (jsonb_typeof(tsw.pj) = 'object' AND jsonb_typeof(tsw.pj -> 'quantity') = 'number' AND (tsw.pj ->> 'quantity') ~ '\A-?[0-9]+\Z') AS q_int
    FROM tsw
),
rc AS (                                                -- the contract verdict, in the order MISSING, INVALID, NEGATIVE, FUTURE
    SELECT rv.*, p.cutoff,
           CASE WHEN jsonb_typeof(rv.pj) <> 'object' THEN 'INVALID_FIELD'
                WHEN NOT rv.has_all THEN 'MISSING_FIELD'
                WHEN NOT rv.q_int OR abs((rv.pj ->> 'quantity')::numeric) > 9007199254740992 OR NOT rv.up_ok OR NOT rv.am_ok OR NOT rv.ts_ok THEN 'INVALID_FIELD'
                WHEN (rv.pj ->> 'quantity')::numeric < 0 THEN 'NEGATIVE_QUANTITY'
                WHEN rv.ev_raw > least(rv.arrived, p.cutoff) THEN 'EVENT_IN_FUTURE'
           END AS contract_reason
    FROM rv CROSS JOIN p
),
fv AS (                                                -- the first row of each key that satisfies the contract
    SELECT DISTINCT ON (source_id, source_key) source_id, source_key, apply_order AS f_order, raw_record_id AS f_id
    FROM rc WHERE contract_reason IS NULL AND NOT schema_changed AND source_key IS NOT NULL
    ORDER BY source_id, source_key, apply_order, raw_record_id COLLATE "C"
),
cl AS (
    SELECT rc.*,
           CASE WHEN rc.schema_changed THEN 'quarantined'
                WHEN fv.f_id = rc.raw_record_id THEN 'accepted'
                WHEN fv.f_id IS NOT NULL AND (rc.apply_order > fv.f_order OR (rc.apply_order = fv.f_order AND rc.raw_record_id COLLATE "C" > fv.f_id COLLATE "C")) THEN 'duplicate'
                ELSE 'quarantined' END AS kind,
           CASE WHEN rc.schema_changed THEN 'SCHEMA_CHANGED' ELSE coalesce(rc.contract_reason, 'MISSING_FIELD') END AS q_reason,
           CASE WHEN rc.am_ok THEN (rc.pj ->> 'amount')::numeric ELSE 0 END AS amt,
           CASE WHEN rc.ts_ok THEN rc.ev_raw END AS ev
    FROM rc LEFT JOIN fv ON fv.source_id = rc.source_id AND fv.source_key = rc.source_key
),
acc AS (SELECT * FROM cl WHERE kind = 'accepted'),
fmt AS (SELECT 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'::text AS f),               -- microseconds are printed when they are not zero, as iso_z does

-- ------------------------------------------------------------------ ingestion
batch_json AS (
    SELECT b.source_id, b.batch_id,
           CASE WHEN b.status <> 'committed' THEN
               jsonb_build_object('status', b.status, 'counted', false, 'written_rows', (SELECT count(*) FROM raw_records r WHERE r.batch_id = b.batch_id),
                                  'received', 0, 'accepted_unique', 0, 'duplicate', 0, 'quarantined', 0, 'rejection_rate', NULL, 'duplicate_rate', NULL,
                                  'quarantine_rows_match', true)
           ELSE
               jsonb_build_object('status', 'committed', 'counted', true, 'written_rows', x.n, 'received', x.n, 'accepted_unique', x.a, 'duplicate', x.d,
                                  'quarantined', x.q, 'rejection_rate', round(x.q::numeric / nullif(x.n, 0), 6)::text,
                                  'duplicate_rate', round(x.d::numeric / nullif(x.n, 0), 6)::text,
                                  'quarantine_rows_match',
                                  (SELECT coalesce(array_agg(q_reason ORDER BY q_reason COLLATE "C"), '{}') FROM cl WHERE cl.batch_id = b.batch_id AND kind = 'quarantined')
                                  = (SELECT coalesce(array_agg(reason_code ORDER BY reason_code COLLATE "C"), '{}') FROM quarantine_records q WHERE q.batch_id = b.batch_id))
           END AS j
    FROM ingestion_batches b
    LEFT JOIN LATERAL (SELECT count(*) AS n, count(*) FILTER (WHERE kind = 'accepted') AS a, count(*) FILTER (WHERE kind = 'duplicate') AS d,
                              count(*) FILTER (WHERE kind = 'quarantined') AS q FROM cl WHERE cl.batch_id = b.batch_id) x ON true
),
src_json AS (
    SELECT s.source_id,
           jsonb_build_object(
             'batches', coalesce((SELECT jsonb_object_agg(bj.batch_id, bj.j) FROM batch_json bj WHERE bj.source_id = s.source_id), '{}'::jsonb),
             'received', t.n, 'accepted_unique', t.a, 'duplicate', t.d, 'quarantined', t.q,
             'quarantined_distinct_keys', (SELECT count(DISTINCT source_key) FROM cl WHERE cl.source_id = s.source_id AND kind = 'quarantined'),
             'rejection_rate', round(t.q::numeric / nullif(t.n, 0), 6)::text, 'duplicate_rate', round(t.d::numeric / nullif(t.n, 0), 6)::text,
             'quarantine_by_reason', coalesce((SELECT jsonb_object_agg(q_reason, n) FROM (SELECT q_reason, count(*) AS n FROM cl WHERE cl.source_id = s.source_id AND kind = 'quarantined' GROUP BY q_reason) z), '{}'::jsonb),
             'checkpoint', jsonb_build_object(
                 'committed_version', (SELECT max(version_number) FROM cb WHERE cb.source_id = s.source_id),
                 'committed_cursor', (SELECT committed_cursor FROM cb WHERE cb.source_id = s.source_id AND version_number IS NOT NULL ORDER BY version_number DESC LIMIT 1),
                 'committed_batch_id', (SELECT batch_id FROM cb WHERE cb.source_id = s.source_id AND version_number IS NOT NULL ORDER BY version_number DESC LIMIT 1),
                 'uncommitted_batches', coalesce((SELECT jsonb_agg(b.batch_id ORDER BY b.batch_id COLLATE "C") FROM ingestion_batches b WHERE b.source_id = s.source_id AND b.status <> 'committed'), '[]'::jsonb),
                 'uncommitted_batches_with_checkpoint', (SELECT count(*) FROM ingestion_batches b JOIN checkpoints c ON c.batch_id = b.batch_id WHERE b.source_id = s.source_id AND b.status <> 'committed'))
           ) AS j
    FROM source_contracts s
    CROSS JOIN LATERAL (SELECT count(*) AS n, count(*) FILTER (WHERE kind = 'accepted') AS a, count(*) FILTER (WHERE kind = 'duplicate') AS d,
                               count(*) FILTER (WHERE kind = 'quarantined') AS q FROM cl WHERE cl.source_id = s.source_id) t
),
ingestion AS (
    SELECT jsonb_build_object(
        'sources', coalesce((SELECT jsonb_object_agg(source_id, j) FROM src_json), '{}'::jsonb),
        'overall', jsonb_build_object('received', count(*), 'accepted_unique', count(*) FILTER (WHERE kind = 'accepted'),
                                      'duplicate', count(*) FILTER (WHERE kind = 'duplicate'), 'quarantined', count(*) FILTER (WHERE kind = 'quarantined'),
                                      'rejection_rate', round(count(*) FILTER (WHERE kind = 'quarantined')::numeric / nullif(count(*), 0), 6)::text,
                                      'duplicate_rate', round(count(*) FILTER (WHERE kind = 'duplicate')::numeric / nullif(count(*), 0), 6)::text)) AS j
    FROM cl
),

-- ------------------------------------------------------------------ freshness and completeness
freshness AS (
    SELECT coalesce(jsonb_object_agg(s.source_id, jsonb_build_object(
        'latest_accepted_event_at', regexp_replace(to_char(e.ev AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'),
        'freshness_seconds', floor(extract(epoch FROM p.cutoff - e.ev))::bigint,
        'freshness_reason', CASE WHEN e.ev IS NULL THEN 'NO_ACCEPTED_EVENT' END,
        'last_successful_ingestion_at', regexp_replace(to_char(i.at AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'),
        'ingestion_age_seconds', floor(extract(epoch FROM p.cutoff - i.at))::bigint)), '{}'::jsonb) AS j
    FROM source_contracts s CROSS JOIN p CROSS JOIN fmt
    CROSS JOIN LATERAL (SELECT max(ev) AS ev FROM acc WHERE acc.source_id = s.source_id) e
    CROSS JOIN LATERAL (SELECT max(committed_at) AS at FROM cb WHERE cb.source_id = s.source_id AND cb.version_number IS NOT NULL) i
),
completeness AS (
    SELECT coalesce(jsonb_object_agg(source_id, parts), '{}'::jsonb) AS j FROM (
        SELECT x.source_id, jsonb_object_agg(x.partition, jsonb_build_object('expected_records', x.expected_records, 'accepted_records', n.n,
               'value', round(n.n::numeric / nullif(x.expected_records, 0), 6)::text)) AS parts
        FROM source_expectations x
        CROSS JOIN LATERAL (SELECT count(*) AS n FROM acc WHERE acc.source_id = x.source_id AND to_char(acc.ev AT TIME ZONE 'UTC', 'YYYY-MM-DD') = x.partition) n
        GROUP BY x.source_id) z
),

-- ------------------------------------------------------------------ runs, tasks, attempts, durations
last_attempt AS (
    SELECT DISTINCT ON (run_id, task_name) run_id, task_name, status AS final_status, attempt
    FROM task_runs ORDER BY run_id, task_name, attempt DESC
),
run_tasks AS (
    SELECT r.run_id,
           (SELECT count(*) FROM last_attempt l WHERE l.run_id = r.run_id AND l.final_status IN ('success', 'failed')) AS terminal,
           (SELECT count(*) FROM last_attempt l WHERE l.run_id = r.run_id AND l.final_status = 'success') AS ok,
           (SELECT count(*) FROM task_runs t WHERE t.run_id = r.run_id) AS attempts,
           (SELECT count(*) FROM task_runs t WHERE t.run_id = r.run_id AND t.status = 'success') AS attempts_ok,
           floor(extract(epoch FROM r.finished_at - r.started_at))::bigint AS dur, r.status
    FROM pipeline_runs r
),
runs AS (
    SELECT jsonb_build_object(
        'runs', coalesce((SELECT jsonb_object_agg(rt.run_id, jsonb_build_object('status', rt.status, 'duration_seconds', rt.dur,
              'tasks', coalesce((SELECT jsonb_object_agg(l.task_name, jsonb_build_object('attempts', (SELECT count(*) FROM task_runs t WHERE t.run_id = l.run_id AND t.task_name = l.task_name), 'final_status', l.final_status))
                                 FROM last_attempt l WHERE l.run_id = rt.run_id), '{}'::jsonb),
              'tasks_terminal', rt.terminal, 'tasks_successful', rt.ok, 'task_success_rate', round(rt.ok::numeric / nullif(rt.terminal, 0), 6)::text,
              'attempts', rt.attempts, 'attempts_successful', rt.attempts_ok, 'attempt_success_rate', round(rt.attempts_ok::numeric / nullif(rt.attempts, 0), 6)::text)) FROM run_tasks rt), '{}'::jsonb),
        'overall', jsonb_build_object('tasks_terminal', coalesce(sum(terminal), 0), 'tasks_successful', coalesce(sum(ok), 0),
              'task_success_rate', round(sum(ok)::numeric / nullif(sum(terminal), 0), 6)::text, 'attempts', coalesce(sum(attempts), 0),
              'attempts_successful', coalesce(sum(attempts_ok), 0), 'attempt_success_rate', round(sum(attempts_ok)::numeric / nullif(sum(attempts), 0), 6)::text),
        'durations', jsonb_build_object(
            'successful', jsonb_build_object('count', count(*) FILTER (WHERE status = 'success' AND dur IS NOT NULL),
                'durations_seconds', coalesce(jsonb_agg(dur ORDER BY dur) FILTER (WHERE status = 'success' AND dur IS NOT NULL), '[]'::jsonb),
                'mean_minutes', round(sum(dur) FILTER (WHERE status = 'success')::numeric / 60 / nullif(count(*) FILTER (WHERE status = 'success' AND dur IS NOT NULL), 0), 4)::text),
            'failed', jsonb_build_object('count', count(*) FILTER (WHERE status = 'failed' AND dur IS NOT NULL),
                'durations_seconds', coalesce(jsonb_agg(dur ORDER BY dur) FILTER (WHERE status = 'failed' AND dur IS NOT NULL), '[]'::jsonb),
                'mean_minutes', round(sum(dur) FILTER (WHERE status = 'failed')::numeric / 60 / nullif(count(*) FILTER (WHERE status = 'failed' AND dur IS NOT NULL), 0), 4)::text))) AS j
    FROM run_tasks
),

-- ------------------------------------------------------------------ the quality gate and the pointer
latest_q AS (
    SELECT DISTINCT ON (t.run_id, q.rule_name) t.run_id, q.rule_name, q.severity, q.eligible_count, q.failure_count
    FROM quality_results q JOIN task_runs t ON t.task_run_id = q.task_run_id
    ORDER BY t.run_id, q.rule_name, q.quality_result_id COLLATE "C" DESC
),
gate AS (
    SELECT r.run_id,
           coalesce(bool_or(l.severity = 'critical'), false) AS has_crit,
           count(*) FILTER (WHERE l.severity = 'critical' AND l.failure_count > 0) AS crit_fail,
           count(*) FILTER (WHERE l.severity <> 'critical' AND l.failure_count > 0) AS other_fail,
           coalesce(jsonb_object_agg(l.rule_name, jsonb_build_object('severity', l.severity, 'eligible', l.eligible_count, 'failures', l.failure_count,
                                                                 'passed', l.failure_count = 0)) FILTER (WHERE l.rule_name IS NOT NULL), '{}'::jsonb) AS results
    FROM pipeline_runs r LEFT JOIN latest_q l ON l.run_id = r.run_id GROUP BY r.run_id
),
gate_json AS (
    SELECT g.run_id, g.results, g.crit_fail, g.other_fail, (CASE WHEN g.has_crit AND g.crit_fail = 0 THEN 'allowed' ELSE 'blocked' END) AS decision FROM gate g
),
quality_gate AS (
    SELECT coalesce(jsonb_object_agg(run_id, jsonb_build_object('results', results, 'critical_failures', crit_fail, 'noncritical_failures', other_fail, 'decision', decision)), '{}'::jsonb) AS j
    FROM gate_json
),
qual AS (                                              -- runs whose publication moves the pointer
    SELECT r.run_id, coalesce(r.finished_at, r.started_at) AS ord_at, pub.publication_id
    FROM pipeline_runs r JOIN gate_json g ON g.run_id = r.run_id JOIN publications pub ON pub.run_id = r.run_id
    WHERE r.status = 'success' AND g.decision = 'allowed'
),
pointer_hist AS (
    SELECT r.run_id, coalesce(r.finished_at, r.started_at) AS ord_at, g.decision,
           (SELECT q.publication_id FROM qual q WHERE (q.ord_at, q.run_id COLLATE "C") <= (coalesce(r.finished_at, r.started_at), r.run_id COLLATE "C")
            ORDER BY q.ord_at DESC, q.run_id COLLATE "C" DESC LIMIT 1) AS pointer_after
    FROM pipeline_runs r JOIN gate_json g ON g.run_id = r.run_id
),

-- ------------------------------------------------------------------ publications, reconciliation, late events
pub_rows AS (
    SELECT pub.*, (SELECT array_agg(b ORDER BY b COLLATE "C") FROM unnest(pub.included_batch_ids) b WHERE b IN (SELECT batch_id FROM cb)) AS inc
    FROM publications pub
),
pub_stats AS (
    SELECT pr.publication_id, pr.run_id, pr.published_at, pr.watermark, coalesce(pr.inc, '{}') AS inc, pr.content_hash,
           (SELECT count(*) FROM acc WHERE acc.batch_id = ANY (coalesce(pr.inc, '{}'))) AS n_pub,
           (SELECT max(ev) FROM acc WHERE acc.batch_id = ANY (coalesce(pr.inc, '{}'))) AS latest,
           (SELECT encode(sha256(convert_to(coalesce(string_agg(payload_hash, E'\n' ORDER BY payload_hash COLLATE "C"), ''), 'UTF8')), 'hex')
              FROM acc WHERE acc.batch_id = ANY (coalesce(pr.inc, '{}'))) AS h,
           (SELECT coalesce(sum(amt), 0) FROM cl WHERE cl.batch_id = ANY (coalesce(pr.inc, '{}'))) AS src_total,
           (SELECT coalesce(sum(amt), 0) FROM acc WHERE acc.batch_id = ANY (coalesce(pr.inc, '{}'))) AS pub_total,
           (SELECT coalesce(sum(amt), 0) FROM cl WHERE cl.batch_id = ANY (coalesce(pr.inc, '{}')) AND kind = 'quarantined') AS q_total,
           (SELECT coalesce(sum(amt), 0) FROM cl WHERE cl.batch_id = ANY (coalesce(pr.inc, '{}')) AND kind = 'duplicate') AS d_total
    FROM pub_rows pr
),
publications_j AS (
    SELECT jsonb_build_object(
        'current_publication_id', (SELECT pointer_after FROM pointer_hist ORDER BY ord_at DESC, run_id COLLATE "C" DESC LIMIT 1),
        'pointer_history', coalesce((SELECT jsonb_agg(jsonb_build_object('run_id', run_id, 'gate_decision', decision, 'pointer_after', pointer_after)
                                                      ORDER BY ord_at, run_id COLLATE "C") FROM pointer_hist), '[]'::jsonb),
        'publications', coalesce((SELECT jsonb_object_agg(s.publication_id, jsonb_build_object('run_id', s.run_id, 'published_at', regexp_replace(to_char(s.published_at AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'),
              'watermark', regexp_replace(to_char(s.watermark AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'), 'included_batches', to_jsonb(s.inc), 'published_records', s.n_pub,
              'latest_included_event_at', regexp_replace(to_char(s.latest AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'), 'lag_seconds', floor(extract(epoch FROM s.published_at - s.latest))::bigint,
              'content_hash_ok', s.h = s.content_hash)) FROM pub_stats s CROSS JOIN fmt), '{}'::jsonb)) AS j
),
reconciliation AS (
    SELECT coalesce(jsonb_object_agg(publication_id, jsonb_build_object(
        'source_total', round(src_total, 2)::text, 'published_total', round(pub_total, 2)::text,
        'exclusions', jsonb_build_object('quarantined', round(q_total, 2)::text, 'duplicates', round(d_total, 2)::text, 'deletes', '0.00'),
        'exclusions_total', round(q_total + d_total, 2)::text, 'residual', round(src_total - pub_total - (q_total + d_total), 2)::text)), '{}'::jsonb) AS j
    FROM pub_stats
),
late AS (
    SELECT a.source_id, a.source_key, a.batch_id, a.ev, a.committed_at AS arrival, b.publication_id AS behind, b.watermark,
           (SELECT n.publication_id FROM publications n WHERE n.published_at > a.committed_at AND a.batch_id = ANY (n.included_batch_ids)
            ORDER BY n.published_at, n.publication_id COLLATE "C" LIMIT 1) AS nxt
    FROM acc a
    CROSS JOIN LATERAL (SELECT pb.* FROM publications pb WHERE a.source_id = ANY (pb.source_ids) AND pb.published_at < a.committed_at
                        ORDER BY pb.published_at DESC, pb.publication_id COLLATE "C" DESC LIMIT 1) b
    WHERE a.committed_at IS NOT NULL AND a.ev <= b.watermark
),
late_events AS (
    SELECT jsonb_build_object('count', count(*), 'included_in_next_publication', count(*) FILTER (WHERE nxt IS NOT NULL), 'lost', count(*) FILTER (WHERE nxt IS NULL),
        'events', coalesce(jsonb_agg(jsonb_build_object('source_id', source_id, 'source_key', source_key, 'batch_id', batch_id,
            'event_at', regexp_replace(to_char(ev AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'), 'arrival_at', regexp_replace(to_char(arrival AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'), 'behind_publication_id', behind,
            'watermark', regexp_replace(to_char(watermark AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'), 'included_in_publication_id', nxt) ORDER BY arrival, source_key COLLATE "C"), '[]'::jsonb)) AS j
    FROM late CROSS JOIN fmt
),

-- ------------------------------------------------------------------ incidents and verified recovery
verified_run AS (                                      -- per incident, the first later run that succeeded, passed, published and reconciled to 0.00
    SELECT i.incident_id, v.run_id AS vrun, v.published_at AS vat
    FROM incidents i
    LEFT JOIN LATERAL (
        SELECT r.run_id, s.published_at FROM pipeline_runs r JOIN gate_json g ON g.run_id = r.run_id
        JOIN pub_stats s ON s.run_id = r.run_id
        WHERE r.started_at >= i.opened_at AND r.status = 'success' AND g.decision = 'allowed'
          AND (s.src_total - s.pub_total - (s.q_total + s.d_total)) = 0
        ORDER BY r.started_at, r.run_id COLLATE "C" LIMIT 1) v ON true
),
inc_j AS (
    SELECT i.incident_id, i.status, vr.vrun, vr.vat, floor(extract(epoch FROM vr.vat - i.opened_at))::bigint AS sec,
           jsonb_build_object('run_id', i.run_id, 'status', i.status, 'detected_at', regexp_replace(to_char(i.opened_at AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'), 'verified', vr.vrun IS NOT NULL,
              'recovery_run_id', vr.vrun, 'verified_at', regexp_replace(to_char(vr.vat AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'),
              'recovery_seconds', floor(extract(epoch FROM vr.vat - i.opened_at))::bigint,
              'recovery_minutes', round(floor(extract(epoch FROM vr.vat - i.opened_at))::numeric / 60, 4)::text,
              'closure_consistent', i.status <> 'closed' OR (vr.vrun IS NOT NULL AND i.recovery_run_id = vr.vrun AND i.closed_at = vr.vat)) AS j
    FROM incidents i JOIN verified_run vr ON vr.incident_id = i.incident_id CROSS JOIN fmt
),
incidents_j AS (
    SELECT jsonb_build_object('total', count(*), 'open', count(*) FILTER (WHERE status <> 'closed'), 'closed', count(*) FILTER (WHERE status = 'closed'),
        'verified', count(*) FILTER (WHERE vrun IS NOT NULL),
        'mean_recovery_minutes', round(sum(sec)::numeric / 60 / nullif(count(*) FILTER (WHERE vrun IS NOT NULL), 0), 4)::text,
        'incidents', coalesce(jsonb_object_agg(incident_id, j), '{}'::jsonb)) AS j
    FROM inc_j
),

-- ------------------------------------------------------------------ backfills and the processing rate
bf AS (
    SELECT b.backfill_id, b.source_id, b.start_at, b.end_at,
           (SELECT count(*) FROM generate_series(b.start_at, b.end_at - interval '1 day', interval '1 day') g) AS n_req,
           (SELECT count(*) FROM jsonb_array_elements(b.partitions) e
             WHERE (e ->> 'verified')::boolean AND (e ->> 'partition') IN (SELECT to_char(g AT TIME ZONE 'UTC', 'YYYY-MM-DD')
                                                                        FROM generate_series(b.start_at, b.end_at - interval '1 day', interval '1 day') g)) AS n_ver
    FROM backfill_requests b
),
backfills AS (
    SELECT jsonb_build_object(
        'requests', coalesce((SELECT jsonb_object_agg(backfill_id, jsonb_build_object('source_id', source_id, 'start_at', regexp_replace(to_char(start_at AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'),
              'end_at', regexp_replace(to_char(end_at AT TIME ZONE 'UTC', fmt.f), '\.000000Z\Z', 'Z'), 'requested_partitions', n_req, 'verified_partitions', n_ver,
              'coverage', round(n_ver::numeric / nullif(n_req, 0), 6)::text)) FROM bf CROSS JOIN fmt), '{}'::jsonb),
        'refused', coalesce((SELECT jsonb_agg(id ORDER BY id COLLATE "C") FROM rejected_records WHERE entity = 'backfill_requests' AND reason_code = 'BACKFILL_OVERLAP'), '[]'::jsonb),
        'overall', jsonb_build_object('requested_partitions', coalesce(sum(n_req), 0), 'verified_partitions', coalesce(sum(n_ver), 0),
              'coverage', round(sum(n_ver)::numeric / nullif(sum(n_req), 0), 6)::text)) AS j
    FROM bf
),
processing_rate AS (
    SELECT CASE WHEN m.measurement_id IS NULL THEN
        jsonb_build_object('accepted_records', 0, 'measured_seconds', NULL, 'records_per_second', NULL, 'hardware', NULL, 'cache_state', NULL)
    ELSE jsonb_build_object('accepted_records', (SELECT count(*) FROM acc WHERE acc.batch_id = m.batch_id), 'measured_seconds', m.measured_seconds::text,
        'records_per_second', round((SELECT count(*) FROM acc WHERE acc.batch_id = m.batch_id)::numeric / m.measured_seconds, 6)::text,
        'hardware', m.hardware, 'cache_state', m.cache_state) END AS j
    FROM (SELECT 1) one LEFT JOIN LATERAL (SELECT * FROM processing_measurements ORDER BY recorded_at DESC, measurement_id DESC LIMIT 1) m ON true
)
SELECT (SELECT j FROM ingestion) AS ingestion, (SELECT j FROM freshness) AS freshness, (SELECT j FROM completeness) AS completeness,
       (SELECT j FROM runs) AS runs, (SELECT j FROM quality_gate) AS quality_gate, (SELECT j FROM publications_j) AS publications,
       (SELECT j FROM late_events) AS late_events, (SELECT j FROM reconciliation) AS reconciliation, (SELECT j FROM incidents_j) AS incidents,
       (SELECT j FROM backfills) AS backfills, (SELECT j FROM processing_rate) AS processing_rate,
       NOT EXISTS (SELECT 1 FROM raw_records) AS empty_population
