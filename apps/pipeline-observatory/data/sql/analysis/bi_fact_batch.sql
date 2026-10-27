-- P08-ART-06 fact_batch: one row per ingestion batch (1,311), the grain of every ingestion measure. Scope: complete_world (checkpoints and batches are published in full; the per-batch counts
-- are the generator's domain run over all raw rows). `counted` is true only for a committed batch; the schema-quarantined batch is counted nowhere and carries its refused rows apart.
SELECT b.batch_id, b.source_id, to_char(b.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS date_key, to_char(b.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at,
       s.kind, b.status, b.status = 'committed' AS counted, s.sampled, s.written_rows, s.received, s.accepted_unique, s.duplicate, s.quarantined, s.deleted,
       (SELECT count(*) FROM quarantine_records q WHERE q.batch_id = b.batch_id AND q.reason_code = 'SCHEMA_CHANGED') AS schema_quarantined_rows,
       c.version_number AS checkpoint_version, 'complete_world' AS scope
FROM ingestion_batches b JOIN artifact_batch_summaries s ON s.batch_id = b.batch_id LEFT JOIN checkpoints c ON c.batch_id = b.batch_id
ORDER BY b.batch_id COLLATE "C"
