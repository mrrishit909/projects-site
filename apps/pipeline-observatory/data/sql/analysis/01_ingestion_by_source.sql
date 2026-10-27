-- P08-ART-04 investigation 01: ingestion counts and rates per source (D-01, D-P8-01, D-09 R8-10): received, accepted unique, duplicate, quarantined, deleted, the rejection
-- and duplicate rates, with the ONE batch quarantined whole for a schema change (SCHEMA_CHANGED, P08-TEST-04) listed separately and never inside a rate.
-- Question: of the rows the sources sent, how many entered the dataset, how many were refused and why, and where did the schema-quarantined rows go?
-- SCOPE. complete world: the per-batch counts are the generator's domain run over ALL 40,191 raw rows (batch_summaries, loaded as artifact_batch_summaries); the
-- quarantine rows (446) are published in full. The published raw_records is a 2,000-row sample and is NOT used here (investigation 10 compares the two).

-- @@ by_source
-- Committed batches only (D-P8-04). received = accepted + duplicate + quarantined + deleted (a delete event is none of the three: it is propagated as an exclusion).
-- The rates divide by received; a source with nothing received would show NULL, never 0.
SELECT b.source_id, count(*) AS committed_batches, sum(s.received) AS received, sum(s.accepted_unique) AS accepted_unique, sum(s.duplicate) AS duplicate,
       sum(s.quarantined) AS quarantined, sum(s.deleted) AS deleted,
       round(sum(s.quarantined)::numeric / nullif(sum(s.received), 0), 6) AS rejection_rate,
       round(sum(s.duplicate)::numeric / nullif(sum(s.received), 0), 6) AS duplicate_rate
FROM ingestion_batches b JOIN artifact_batch_summaries s ON s.batch_id = b.batch_id
WHERE b.status = 'committed'
GROUP BY b.source_id ORDER BY b.source_id COLLATE "C"

-- @@ overall
-- The headline: rates from the sums, not the mean of the source rates.
SELECT count(*) AS committed_batches, sum(s.received) AS received, sum(s.accepted_unique) AS accepted_unique, sum(s.duplicate) AS duplicate, sum(s.quarantined) AS quarantined,
       sum(s.deleted) AS deleted, round(sum(s.quarantined)::numeric / nullif(sum(s.received), 0), 6) AS rejection_rate,
       round(sum(s.duplicate)::numeric / nullif(sum(s.received), 0), 6) AS duplicate_rate,
       sum(s.received) - sum(s.accepted_unique) - sum(s.duplicate) - sum(s.quarantined) - sum(s.deleted) AS unclassified
FROM ingestion_batches b JOIN artifact_batch_summaries s ON s.batch_id = b.batch_id WHERE b.status = 'committed'

-- @@ quarantine_distinct_keys
-- Quarantined occurrences against distinct keys (a replayed invalid row is quarantined again, one row per occurrence, D-P8-01); a row with no key has no key to count.
SELECT b.source_id, count(*) AS quarantine_rows, count(DISTINCT q.source_key) AS distinct_keys, count(*) FILTER (WHERE q.source_key IS NULL) AS rows_without_key
FROM quarantine_records q JOIN ingestion_batches b ON b.batch_id = q.batch_id WHERE b.status = 'committed'
GROUP BY b.source_id ORDER BY b.source_id COLLATE "C"

-- @@ quarantine_by_reason
-- Every quarantine row, by reason, split by where it sits: in a committed batch (inside the rate) or in the batch quarantined whole (outside it).
SELECT q.reason_code, count(*) FILTER (WHERE b.status = 'committed') AS in_committed_batches, count(*) FILTER (WHERE b.status = 'quarantined') AS in_schema_quarantined_batch,
       count(*) FILTER (WHERE b.status NOT IN ('committed', 'quarantined')) AS in_other_batches, count(*) AS all_rows
FROM quarantine_records q JOIN ingestion_batches b ON b.batch_id = q.batch_id
GROUP BY q.reason_code ORDER BY q.reason_code COLLATE "C"

-- @@ schema_quarantined
-- Listed separately: the batch refused whole because the page declared a schema version the contract did not expect, its rows, the contract's version now, and the fetch of
-- the same window that was committed after the version was bumped on purpose. The refused rows are in no accepted, duplicate or quarantined count above.
SELECT b.batch_id, b.source_id, b.status, to_char(b.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at, b.source_cursor, s.kind, s.written_rows,
       (SELECT count(*) FROM quarantine_records q WHERE q.batch_id = b.batch_id AND q.reason_code = 'SCHEMA_CHANGED') AS schema_changed_rows,
       (SELECT count(*) FROM checkpoints c WHERE c.batch_id = b.batch_id) AS checkpoints, c.schema_version AS contract_schema_version
FROM ingestion_batches b JOIN artifact_batch_summaries s ON s.batch_id = b.batch_id JOIN source_contracts c ON c.source_id = b.source_id
WHERE b.status = 'quarantined' OR s.kind = 'schema_refetch'
ORDER BY b.started_at, b.batch_id COLLATE "C"

-- @@ by_batch_kind
-- The 1,311 batches by kind and status: aborted ones carry rows but no checkpoint and count for nothing; replays are all duplicates.
SELECT s.kind, b.status, count(*) AS batches, sum(s.written_rows) AS written_rows, sum(s.received) AS received, sum(s.accepted_unique) AS accepted_unique, sum(s.duplicate) AS duplicate,
       (SELECT count(*) FROM checkpoints c JOIN ingestion_batches b2 ON b2.batch_id = c.batch_id JOIN artifact_batch_summaries s2 ON s2.batch_id = b2.batch_id
         WHERE s2.kind = s.kind AND b2.status = b.status) AS checkpoints
FROM ingestion_batches b JOIN artifact_batch_summaries s ON s.batch_id = b.batch_id
GROUP BY s.kind, b.status ORDER BY s.kind COLLATE "C", b.status COLLATE "C"

-- @@ crash_replay
-- The delivery guarantee at the key boundary (D-01, P08-TEST-01), at the scale of the world: every aborted batch (rows written, no checkpoint, counted nowhere) was fetched again
-- from the SAME cursor, committed with the next checkpoint version (previous + 1), and classified by source key against what was already accepted. The rows of an aborted
-- batch are classified exactly once, in its replay: accepted + duplicate + quarantined = the rows the aborted batch had written.
SELECT a.batch_id AS aborted_batch, a.source_id, sa.written_rows AS aborted_rows, (SELECT count(*) FROM checkpoints c WHERE c.batch_id = a.batch_id) AS aborted_checkpoints,
       r.batch_id AS replay_batch, sr.received AS replay_received, sr.accepted_unique AS replay_accepted, sr.duplicate AS replay_duplicate, sr.quarantined AS replay_quarantined,
       pv.version_number AS previous_version, cr.version_number AS replay_version, cr.version_number - pv.version_number AS version_step,
       sr.accepted_unique + sr.duplicate + sr.quarantined = sa.written_rows AS rows_classified_once
FROM ingestion_batches a JOIN artifact_batch_summaries sa ON sa.batch_id = a.batch_id
JOIN LATERAL (SELECT x.batch_id FROM ingestion_batches x WHERE x.source_id = a.source_id AND x.source_cursor = a.source_cursor AND x.status = 'committed' AND x.started_at > a.started_at
              ORDER BY x.started_at, x.batch_id COLLATE "C" LIMIT 1) r ON true
JOIN artifact_batch_summaries sr ON sr.batch_id = r.batch_id JOIN checkpoints cr ON cr.batch_id = r.batch_id
JOIN LATERAL (SELECT c.version_number FROM checkpoints c JOIN ingestion_batches x ON x.batch_id = c.batch_id WHERE c.source_id = a.source_id AND x.started_at < a.started_at
              ORDER BY c.version_number DESC LIMIT 1) pv ON true
WHERE a.status = 'aborted' ORDER BY a.batch_id COLLATE "C"
