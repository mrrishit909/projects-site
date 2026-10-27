-- P08-ART-04 investigation 07: backfill coverage and the refused overlaps (D-03, D-09 R8-11/R8-12, P08-FLOW-08, P08-MET-11, P08-TEST-02, D-P8-11): a backfill covers a half-open range
-- [start, end) of daily UTC partitions; coverage = verified partitions / requested partitions over the ACCEPTED requests; a request that overlaps a request still requested or
-- running is refused (BACKFILL_OVERLAP) and kept in rejected_records, its id consumed; a request that merely touches one is not an overlap.
-- Question: of the history we asked to be re-ingested, how much was verified, and what did the system refuse?
-- SCOPE. complete world: backfill_requests (13 accepted) and the two refused rows (rejected_records) are published in full. "Verified" is the partition flag the pipeline set.

-- @@ requests
-- All 15 requests, accepted and refused, by id. Coverage is a property of the accepted ones only; a refused request has no run and no coverage.
WITH acc AS (
    SELECT b.backfill_id, b.source_id, 'accepted' AS outcome, b.start_at, b.end_at, b.status, b.requested_at, b.settled_at, jsonb_array_length(b.partitions) AS requested_partitions,
           (SELECT count(*) FROM jsonb_array_elements(b.partitions) e WHERE (e ->> 'verified')::boolean) AS verified_partitions,
           (SELECT r.run_id FROM pipeline_runs r WHERE r.backfill_id = b.backfill_id ORDER BY r.started_at LIMIT 1) AS run_id
    FROM backfill_requests b
), ref AS (
    SELECT r.id AS backfill_id, r.raw_row ->> 'source_id' AS source_id, 'refused' AS outcome, (r.raw_row ->> 'start_at')::timestamptz AS start_at, (r.raw_row ->> 'end_at')::timestamptz AS end_at,
           r.raw_row ->> 'status' AS status, (r.raw_row ->> 'requested_at')::timestamptz AS requested_at, (r.raw_row ->> 'settled_at')::timestamptz AS settled_at,
           jsonb_array_length(r.raw_row -> 'partitions') AS requested_partitions, 0 AS verified_partitions, NULL::text AS run_id
    FROM rejected_records r WHERE r.entity = 'backfill_requests' AND r.reason_code = 'BACKFILL_OVERLAP'
), u AS (SELECT * FROM acc UNION ALL SELECT * FROM ref)
SELECT u.backfill_id, u.source_id, u.outcome, to_char(u.start_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS start_day, to_char(u.end_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS end_day,
       u.requested_partitions, u.verified_partitions,
       CASE WHEN u.outcome = 'accepted' THEN round(u.verified_partitions::numeric / nullif(u.requested_partitions, 0), 6) END AS coverage,
       u.status, to_char(u.requested_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS requested_at, to_char(u.settled_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS settled_at, u.run_id
FROM u ORDER BY u.backfill_id COLLATE "C"

-- @@ coverage_summary
-- The metric keeps its D-03 definition (R8-11): verified / requested partitions of the accepted requests. The refused requests are counted beside it, never inside it.
SELECT (SELECT count(*) FROM backfill_requests) AS accepted_requests, (SELECT sum(jsonb_array_length(partitions)) FROM backfill_requests) AS requested_partitions,
       (SELECT count(*) FROM backfill_requests b, jsonb_array_elements(b.partitions) e WHERE (e ->> 'verified')::boolean) AS verified_partitions,
       round((SELECT count(*) FROM backfill_requests b, jsonb_array_elements(b.partitions) e WHERE (e ->> 'verified')::boolean)::numeric
             / nullif((SELECT sum(jsonb_array_length(partitions)) FROM backfill_requests), 0), 6) AS coverage,
       (SELECT count(*) FROM rejected_records WHERE entity = 'backfill_requests' AND reason_code = 'BACKFILL_OVERLAP') AS refused_requests,
       (SELECT sum(jsonb_array_length(raw_row -> 'partitions')) FROM rejected_records WHERE entity = 'backfill_requests' AND reason_code = 'BACKFILL_OVERLAP') AS refused_partitions,
       (SELECT count(*) FROM backfill_requests WHERE status = 'complete') AS requests_complete, (SELECT count(*) FROM backfill_requests WHERE status = 'partial') AS requests_partial,
       (SELECT count(*) FROM pipeline_runs WHERE backfill_id IS NOT NULL) AS backfill_runs

-- @@ by_source
SELECT b.source_id, count(*) AS accepted_requests, sum(jsonb_array_length(b.partitions)) AS requested_partitions,
       sum((SELECT count(*) FROM jsonb_array_elements(b.partitions) e WHERE (e ->> 'verified')::boolean)) AS verified_partitions,
       round(sum((SELECT count(*) FROM jsonb_array_elements(b.partitions) e WHERE (e ->> 'verified')::boolean))::numeric / sum(jsonb_array_length(b.partitions)), 6) AS coverage,
       (SELECT count(*) FROM rejected_records r WHERE r.entity = 'backfill_requests' AND r.reason_code = 'BACKFILL_OVERLAP' AND r.raw_row ->> 'source_id' = b.source_id) AS refused_requests
FROM backfill_requests b GROUP BY b.source_id ORDER BY b.source_id COLLATE "C"

-- @@ unverified_partitions
-- The four partitions an accepted backfill left unverified. A settled request no longer blocks a later one (R8-12), so each could be requested again.
SELECT b.backfill_id, b.source_id, e ->> 'partition' AS partition, b.status
FROM backfill_requests b, jsonb_array_elements(b.partitions) e WHERE NOT (e ->> 'verified')::boolean
ORDER BY b.backfill_id COLLATE "C", e ->> 'partition' COLLATE "C"

-- @@ refused_overlaps
-- Each refused request against the request it overlapped: same source, ranges that intersect (half-open: touching does not count), and that request still requested or running
-- when the refused one arrived (made no later, settled after). One partition is shared in each case; the refusal came before the victim settled.
SELECT r.id AS refused_request, r.raw_row ->> 'source_id' AS source_id, to_char((r.raw_row ->> 'start_at')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS start_day,
       to_char((r.raw_row ->> 'end_at')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS end_day, v.backfill_id AS overlapped_request,
       to_char(v.start_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS overlapped_start_day, to_char(v.end_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS overlapped_end_day,
       floor(extract(epoch FROM least((r.raw_row ->> 'end_at')::timestamptz, v.end_at) - greatest((r.raw_row ->> 'start_at')::timestamptz, v.start_at)) / 86400)::int AS shared_partitions,
       floor(extract(epoch FROM v.settled_at - (r.raw_row ->> 'requested_at')::timestamptz))::bigint AS seconds_before_the_overlapped_request_settled,
       v.status AS overlapped_final_status, r.reason_code
FROM rejected_records r
JOIN LATERAL (SELECT b.* FROM backfill_requests b
              WHERE b.source_id = r.raw_row ->> 'source_id' AND b.start_at < (r.raw_row ->> 'end_at')::timestamptz AND (r.raw_row ->> 'start_at')::timestamptz < b.end_at
                AND b.requested_at <= (r.raw_row ->> 'requested_at')::timestamptz AND (b.settled_at IS NULL OR (r.raw_row ->> 'requested_at')::timestamptz < b.settled_at)
              ORDER BY b.backfill_id COLLATE "C" LIMIT 1) v ON true
WHERE r.entity = 'backfill_requests' AND r.reason_code = 'BACKFILL_OVERLAP' ORDER BY r.id COLLATE "C"

-- @@ accepted_pairs
-- The accepted requests never overlap one another and none touches another: of all pairs of accepted requests of one source, the pairs whose ranges intersect or touch.
SELECT count(*) FILTER (WHERE a.start_at < b.end_at AND b.start_at < a.end_at) AS overlapping_pairs, count(*) FILTER (WHERE a.end_at = b.start_at OR b.end_at = a.start_at) AS touching_pairs,
       count(*) AS pairs_of_one_source
FROM backfill_requests a JOIN backfill_requests b ON b.source_id = a.source_id AND a.backfill_id COLLATE "C" < b.backfill_id COLLATE "C"
