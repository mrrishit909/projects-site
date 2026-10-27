-- P08-ART-06 fact_fetch: one row per fetch-log row (1,361). For a rate-limited response: the wait until the next fetch of the same cursor in the same session and whether it honoured the hint.
-- Scope: complete_world.
SELECT f.fetch_id, f.source_id, to_char(f.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS date_key, f.session_id, f.cursor_value, f.status, f.retry_after_seconds, f.batch_id,
       coalesce(s.kind, 'no batch') AS batch_kind, floor(extract(epoch FROM n.fetched_at - f.fetched_at))::bigint AS retry_waited_seconds,
       CASE WHEN f.status = 'rate_limited' THEN n.fetched_at >= f.fetched_at + f.retry_after_seconds * interval '1 second' END AS retry_honoured, 'complete_world' AS scope
FROM fetch_log f LEFT JOIN artifact_batch_summaries s ON s.batch_id = f.batch_id
LEFT JOIN LATERAL (SELECT x.fetched_at FROM fetch_log x WHERE f.status = 'rate_limited' AND x.source_id = f.source_id AND x.session_id = f.session_id AND x.cursor_value = f.cursor_value
                    AND (x.fetched_at, x.fetch_id) > (f.fetched_at, f.fetch_id) ORDER BY x.fetched_at, x.fetch_id LIMIT 1) n ON true
ORDER BY f.fetch_id
