-- P08-ART-04 investigation 08: the fetch log, retry-after compliance, and refetch against loop rows (D-01, D-09 R8-06, P08-FLOW-01, P08-TEST-03, P08-TEST-10, DR-03): a 429 page
-- carries a retry-after; a retry never comes sooner; a cursor that repeats INSIDE one fetch session is a loop and stops the fetch; the same cursor fetched again in a NEW session
-- is a refetch (a stale-source poll, a replay of a window, a backfill re-reading the last committed cursor), not a loop.
-- Question: does the fetcher honour the source, and can a loop be told from a harmless re-poll?
-- SCOPE. complete world: fetch_log is published in full (1,361 rows) and loaded into the schema's own fetch_log table (the seeder does not load it).

-- @@ statuses
SELECT status, count(*) AS fetches, count(DISTINCT session_id) AS sessions, count(DISTINCT source_id) AS sources, count(batch_id) AS with_a_batch
FROM fetch_log GROUP BY status ORDER BY status COLLATE "C"

-- @@ by_source
SELECT source_id, count(*) AS fetches, count(*) FILTER (WHERE status = 'ok') AS ok, count(*) FILTER (WHERE status = 'rate_limited') AS rate_limited,
       count(*) FILTER (WHERE status = 'refetch') AS refetch, count(*) FILTER (WHERE status = 'cursor_loop') AS cursor_loop
FROM fetch_log GROUP BY source_id ORDER BY source_id COLLATE "C"

-- @@ retries
-- Every rate-limited response and the next fetch of the same cursor in the same session: the wait and the slack beyond the hint. A retry may itself be rate limited again.
SELECT f.fetch_id, f.source_id, f.session_id, f.cursor_value, f.retry_after_seconds, to_char(f.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS rate_limited_at,
       to_char(n.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS retried_at, floor(extract(epoch FROM n.fetched_at - f.fetched_at))::bigint AS waited_seconds,
       floor(extract(epoch FROM n.fetched_at - f.fetched_at))::bigint - f.retry_after_seconds AS slack_seconds, n.fetched_at >= f.fetched_at + f.retry_after_seconds * interval '1 second' AS honoured,
       n.status AS retry_status
FROM fetch_log f
LEFT JOIN LATERAL (SELECT x.fetched_at, x.status FROM fetch_log x WHERE x.source_id = f.source_id AND x.session_id = f.session_id AND x.cursor_value = f.cursor_value
                    AND (x.fetched_at, x.fetch_id) > (f.fetched_at, f.fetch_id) ORDER BY x.fetched_at, x.fetch_id LIMIT 1) n ON true
WHERE f.status = 'rate_limited' ORDER BY f.fetch_id

-- @@ retry_summary
WITH r AS (
    SELECT f.fetch_id, f.source_id, f.session_id, f.retry_after_seconds, n.fetched_at AS retried_at, f.fetched_at AS limited_at, n.status AS retry_status
    FROM fetch_log f
    LEFT JOIN LATERAL (SELECT x.fetched_at, x.status FROM fetch_log x WHERE x.source_id = f.source_id AND x.session_id = f.session_id AND x.cursor_value = f.cursor_value
                        AND (x.fetched_at, x.fetch_id) > (f.fetched_at, f.fetch_id) ORDER BY x.fetched_at, x.fetch_id LIMIT 1) n ON true
    WHERE f.status = 'rate_limited'
)
SELECT count(*) AS rate_limited_responses, count(retried_at) AS retries, count(*) FILTER (WHERE retried_at >= limited_at + retry_after_seconds * interval '1 second') AS retries_honouring_retry_after,
       count(*) FILTER (WHERE retried_at < limited_at + retry_after_seconds * interval '1 second') AS retries_too_soon,
       min(floor(extract(epoch FROM retried_at - limited_at))::bigint - retry_after_seconds) AS min_slack_seconds, max(floor(extract(epoch FROM retried_at - limited_at))::bigint - retry_after_seconds) AS max_slack_seconds,
       count(DISTINCT session_id) AS sessions_rate_limited, count(DISTINCT source_id) AS sources_rate_limited, min(source_id COLLATE "C") AS source_id,
       count(*) FILTER (WHERE retry_status = 'rate_limited') AS retries_rate_limited_again
FROM r

-- @@ retry_by_hint
SELECT f.retry_after_seconds, count(*) AS responses, min(floor(extract(epoch FROM n.fetched_at - f.fetched_at))::bigint - f.retry_after_seconds) AS min_slack_seconds,
       max(floor(extract(epoch FROM n.fetched_at - f.fetched_at))::bigint - f.retry_after_seconds) AS max_slack_seconds,
       count(*) FILTER (WHERE n.fetched_at >= f.fetched_at + f.retry_after_seconds * interval '1 second') AS honoured
FROM fetch_log f
LEFT JOIN LATERAL (SELECT x.fetched_at FROM fetch_log x WHERE x.source_id = f.source_id AND x.session_id = f.session_id AND x.cursor_value = f.cursor_value
                    AND (x.fetched_at, x.fetch_id) > (f.fetched_at, f.fetch_id) ORDER BY x.fetched_at, x.fetch_id LIMIT 1) n ON true
WHERE f.status = 'rate_limited' GROUP BY f.retry_after_seconds ORDER BY f.retry_after_seconds

-- @@ refetch_vs_loop
-- The two rows that look alike and are not: refetch rows by the kind of batch they produced (each produced one: a refetch is a page that was used), and the loop row (it produced none).
SELECT f.status, coalesce(s.kind, 'no batch') AS batch_kind, count(*) AS fetches, count(*) FILTER (WHERE f.next_cursor = f.cursor_value) AS pointing_at_themselves
FROM fetch_log f LEFT JOIN artifact_batch_summaries s ON s.batch_id = f.batch_id WHERE f.status IN ('refetch', 'cursor_loop')
GROUP BY f.status, coalesce(s.kind, 'no batch') ORDER BY f.status COLLATE "C", coalesce(s.kind, 'no batch') COLLATE "C"

-- @@ refetch_check
-- The rule of the contract on the whole log, stated as counts. A refetch is a page whose cursor another session already served, or the re-poll of the last committed cursor
-- (the page points at itself because the source has nothing new): every refetch row is one or the other. A loop repeats a cursor inside its OWN session: only the one loop row does.
SELECT f.status, count(*) AS fetches,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fetch_log e WHERE e.source_id = f.source_id AND e.session_id <> f.session_id AND e.status IN ('ok', 'refetch')
                                       AND (e.fetched_at, e.fetch_id) < (f.fetched_at, f.fetch_id) AND e.cursor_value = f.cursor_value)) AS cursor_served_before_by_another_session,
       count(*) FILTER (WHERE f.next_cursor = f.cursor_value) AS pointing_at_themselves,
       count(*) FILTER (WHERE f.next_cursor = f.cursor_value OR EXISTS (SELECT 1 FROM fetch_log e WHERE e.source_id = f.source_id AND e.session_id <> f.session_id AND e.status IN ('ok', 'refetch')
                                       AND (e.fetched_at, e.fetch_id) < (f.fetched_at, f.fetch_id) AND e.cursor_value = f.cursor_value)) AS refetch_conditions_met,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fetch_log e WHERE e.source_id = f.source_id AND e.session_id = f.session_id AND e.status IN ('ok', 'refetch')
                                       AND (e.fetched_at, e.fetch_id) < (f.fetched_at, f.fetch_id) AND (e.cursor_value = f.cursor_value OR e.cursor_value = f.next_cursor OR e.next_cursor = f.next_cursor))) AS repeats_inside_its_session
FROM fetch_log f GROUP BY f.status ORDER BY f.status COLLATE "C"

-- @@ cursor_loop
-- The designed loop (DR-03, P08-TEST-10): one session reads a page, then a second page whose next cursor points back at the first. The second page is refused (CURSOR_LOOP), no
-- batch is created from it, and the fetch stops; nothing it carried was committed.
SELECT l.fetch_id AS loop_fetch, l.source_id, l.session_id, l.cursor_value AS looping_cursor, l.next_cursor AS points_back_to, p.fetch_id AS first_page_fetch, p.cursor_value AS first_page_cursor,
       p.next_cursor AS first_page_next, to_char(p.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS first_page_at, to_char(l.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS loop_detected_at,
       l.batch_id IS NULL AS no_batch_created, (SELECT count(*) FROM fetch_log x WHERE x.session_id = l.session_id) AS rows_in_the_session
FROM fetch_log l JOIN fetch_log p ON p.source_id = l.source_id AND p.session_id = l.session_id AND p.cursor_value = l.next_cursor AND p.status = 'ok'
WHERE l.status = 'cursor_loop' ORDER BY l.fetch_id
