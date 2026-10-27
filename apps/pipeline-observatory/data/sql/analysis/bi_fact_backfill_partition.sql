-- P08-ART-06 fact_backfill_partition: one row per requested partition of every request, accepted and refused (15 + 4 = 19). `in_coverage` is true for the accepted requests only: the
-- refused partitions are beside the coverage and never inside it (D-09 R8-11). Scope: complete_world.
WITH acc AS (
    SELECT b.backfill_id, b.source_id, 'accepted' AS outcome, b.status, e ->> 'partition' AS partition, (e ->> 'verified')::boolean AS verified
    FROM backfill_requests b, jsonb_array_elements(b.partitions) e
), ref AS (
    SELECT r.id AS backfill_id, r.raw_row ->> 'source_id' AS source_id, 'refused' AS outcome, r.raw_row ->> 'status' AS status, e ->> 'partition' AS partition, false AS verified
    FROM rejected_records r, jsonb_array_elements(r.raw_row -> 'partitions') e WHERE r.entity = 'backfill_requests' AND r.reason_code = 'BACKFILL_OVERLAP'
)
SELECT u.backfill_id, u.source_id, u.outcome, u.status AS request_status, u.partition AS date_key, u.verified, u.outcome = 'accepted' AS in_coverage, 'complete_world' AS scope
FROM (SELECT * FROM acc UNION ALL SELECT * FROM ref) u ORDER BY u.backfill_id COLLATE "C", u.partition COLLATE "C"
