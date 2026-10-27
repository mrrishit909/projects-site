-- P08-ART-04 investigation 10: the sample-scope reconciliation (D-07, D-08, D-09 R8-09/R8-10): the published raw_records is a 2,000-row SAMPLE of 62 whole batches (50 of which carry
-- rows) of a world of 40,191 raw rows. Every metric the application computes over the loaded database that needs raw rows describes the sample, not the world.
-- Question: which figures may a reader take from the loaded database, which only from the generator's record, and how far apart are the two?
-- SCOPE. This investigation compares scopes on purpose: complete world (batch_summaries, checkpoints, runs ... published in full), 2,000-row sample (raw_records, and what the seeder and the
-- domain derive from it), recorded (the manifest's statement about the complete world).

-- @@ scope_rows
-- How much of the world the sample holds, per source: batches, batches sampled, sampled batches that carry rows, rows written in the world and rows in the sample.
SELECT b.source_id, count(*) AS batches, count(*) FILTER (WHERE s.sampled) AS sampled_batches, count(*) FILTER (WHERE s.sampled AND s.written_rows > 0) AS sampled_batches_with_rows,
       sum(s.written_rows) AS world_rows, (SELECT count(*) FROM raw_records r JOIN ingestion_batches b2 ON b2.batch_id = r.batch_id WHERE b2.source_id = b.source_id) AS sample_rows,
       round((SELECT count(*) FROM raw_records r JOIN ingestion_batches b2 ON b2.batch_id = r.batch_id WHERE b2.source_id = b.source_id)::numeric / sum(s.written_rows), 6) AS sample_share
FROM ingestion_batches b JOIN artifact_batch_summaries s ON s.batch_id = b.batch_id GROUP BY b.source_id ORDER BY b.source_id COLLATE "C"

-- @@ scope_total
SELECT count(*) AS batches, count(*) FILTER (WHERE s.sampled) AS sampled_batches, count(*) FILTER (WHERE s.sampled AND s.written_rows > 0) AS sampled_batches_with_rows,
       sum(s.written_rows) AS world_rows, (SELECT count(*) FROM raw_records) AS sample_rows, round((SELECT count(*) FROM raw_records)::numeric / sum(s.written_rows), 6) AS sample_share,
       (SELECT count(*) FROM raw_records r JOIN ingestion_batches b2 ON b2.batch_id = r.batch_id WHERE b2.status <> 'committed') AS sample_rows_in_uncounted_batches
FROM artifact_batch_summaries s

-- @@ classes_by_source
-- The same 1,878 rows of the sampled committed batches, classified twice. world: the generator's domain run over every raw row (key history complete). sample: the domain over the
-- loaded rows only (a key whose first copy sits in an unsampled batch looks new). The sample overstates accepted and understates duplicates; nothing else moves much.
SELECT b.source_id, sum(s.received) AS received, sum(s.accepted_unique) AS world_accepted, sum(s.duplicate) AS world_duplicate, sum(s.quarantined) AS world_quarantined, sum(s.deleted) AS world_deleted,
       (SELECT count(*) FROM raw_records r JOIN ingestion_batches b2 ON b2.batch_id = r.batch_id WHERE b2.source_id = b.source_id AND b2.status = 'committed' AND r.disposition = 'accepted') AS sample_accepted,
       (SELECT count(*) FROM raw_records r JOIN ingestion_batches b2 ON b2.batch_id = r.batch_id WHERE b2.source_id = b.source_id AND b2.status = 'committed' AND r.disposition = 'duplicate') AS sample_duplicate,
       (SELECT count(*) FROM raw_records r JOIN ingestion_batches b2 ON b2.batch_id = r.batch_id WHERE b2.source_id = b.source_id AND b2.status = 'committed' AND r.disposition = 'quarantined') AS sample_quarantined,
       (SELECT count(*) FROM raw_records r JOIN ingestion_batches b2 ON b2.batch_id = r.batch_id WHERE b2.source_id = b.source_id AND b2.status = 'committed' AND r.disposition = 'deleted') AS sample_deleted
FROM ingestion_batches b JOIN artifact_batch_summaries s ON s.batch_id = b.batch_id WHERE b.status = 'committed' AND s.sampled GROUP BY b.source_id ORDER BY b.source_id COLLATE "C"

-- @@ rates_by_scope
-- The headline rates under three scopes. A rate carries its scope: the sample's duplicate rate (0.012247) is the sample's, not the pipeline's (0.052655).
SELECT 'complete world, 1,302 committed batches' AS scope, sum(s.received) AS received, sum(s.accepted_unique) AS accepted_unique, sum(s.duplicate) AS duplicate, sum(s.quarantined) AS quarantined,
       round(sum(s.quarantined)::numeric / nullif(sum(s.received), 0), 6) AS rejection_rate, round(sum(s.duplicate)::numeric / nullif(sum(s.received), 0), 6) AS duplicate_rate
FROM artifact_batch_summaries s WHERE s.status = 'committed'
UNION ALL
SELECT 'the sampled committed batches, classified with the full key history', sum(s.received), sum(s.accepted_unique), sum(s.duplicate), sum(s.quarantined),
       round(sum(s.quarantined)::numeric / nullif(sum(s.received), 0), 6), round(sum(s.duplicate)::numeric / nullif(sum(s.received), 0), 6)
FROM artifact_batch_summaries s WHERE s.status = 'committed' AND s.sampled
UNION ALL
SELECT 'the 2,000-row sample, classified from the loaded rows only', count(*), count(*) FILTER (WHERE r.disposition = 'accepted'), count(*) FILTER (WHERE r.disposition = 'duplicate'),
       count(*) FILTER (WHERE r.disposition = 'quarantined'), round(count(*) FILTER (WHERE r.disposition = 'quarantined')::numeric / nullif(count(*), 0), 6),
       round(count(*) FILTER (WHERE r.disposition = 'duplicate')::numeric / nullif(count(*), 0), 6)
FROM raw_records r JOIN ingestion_batches b ON b.batch_id = r.batch_id WHERE b.status = 'committed'

-- @@ quarantine_rows
-- The quarantine rows are published in full (446), but only the rows of sampled batches have raw rows to compare with: the rest can be listed, not re-derived.
SELECT count(*) AS quarantine_rows, count(*) FILTER (WHERE s.sampled) AS in_sampled_batches, count(*) FILTER (WHERE NOT s.sampled) AS in_unsampled_batches,
       count(*) FILTER (WHERE NOT s.sampled AND b.status = 'committed') AS unsampled_in_committed_batches, count(*) FILTER (WHERE b.status = 'quarantined') AS in_the_schema_quarantined_batch
FROM quarantine_records q JOIN ingestion_batches b ON b.batch_id = q.batch_id JOIN artifact_batch_summaries s ON s.batch_id = q.batch_id

-- @@ publications
-- A publication's content hash is the hash of the sorted payload hashes of its included records (D-P8-10). The sample can verify one only when it holds every included batch. None does,
-- so the recomputed content-hash check is false on the sample for every publication; the generator records it as true for all 1,318.
WITH inc AS (
    SELECT p.publication_id, count(*) AS included_batches, count(*) FILTER (WHERE s.sampled AND s.written_rows > 0) AS included_in_sample
    FROM publications p CROSS JOIN LATERAL unnest(p.included_batch_ids) AS bid JOIN artifact_batch_summaries s ON s.batch_id = bid GROUP BY p.publication_id
)
SELECT (SELECT count(*) FROM publications) AS publications, count(*) FILTER (WHERE included_batches = included_in_sample) AS verifiable_from_the_sample,
       count(*) FILTER (WHERE included_in_sample > 0 AND included_batches > included_in_sample) AS partly_in_the_sample, count(*) FILTER (WHERE included_in_sample = 0) AS none_in_the_sample
FROM inc

-- @@ freshness_on_the_sample
-- Freshness over the sample is meaningless: the latest event of an accepted SAMPLED row is not the latest event of the source. Recorded: the generator's latest accepted event.
SELECT a.source_id, to_char(max((r.payload_json ->> 'event_ts')::timestamptz) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS sample_latest_accepted_event_at,
       floor(extract(epoch FROM p.as_of - max((r.payload_json ->> 'event_ts')::timestamptz)))::bigint AS sample_freshness_seconds, f.recorded_freshness_seconds
FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id JOIN artifact_recorded_freshness f ON f.source_id = a.source_id, po_p p
GROUP BY a.source_id, p.as_of, f.recorded_freshness_seconds ORDER BY a.source_id COLLATE "C"

-- @@ processing_batch
-- The observed processing rate = accepted records of the measured batch / measured seconds: one synthetic batch, disclosed (not a benchmark). The sample classifies the batch's rows
-- without the history of the world and calls one duplicate accepted: 102 / 2.573 s instead of 101 / 2.573 s.
SELECT pm.batch_id, pm.measured_seconds, pm.cache_state, s.received, s.accepted_unique AS world_accepted, (SELECT count(*) FROM accepted_records a WHERE a.batch_id = pm.batch_id) AS sample_accepted,
       round(s.accepted_unique::numeric / pm.measured_seconds, 6) AS world_records_per_second,
       round((SELECT count(*) FROM accepted_records a WHERE a.batch_id = pm.batch_id)::numeric / pm.measured_seconds, 6) AS sample_records_per_second
FROM processing_measurements pm JOIN artifact_batch_summaries s ON s.batch_id = pm.batch_id
