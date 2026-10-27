-- P08-ART-06 fact_freshness: one row per source at the as-of: ingestion age (complete_world, from the checkpoints), freshness (recorded: the generator's latest accepted event, the seconds
-- recomputed from it), the declared target and cadence, completeness over all partitions (complete_world). The two scope columns say which figure is which.
WITH cad AS (
    SELECT source_id, freshness_target_seconds, CASE WHEN expected_frequency = 'daily' THEN 86400 ELSE (regexp_match(expected_frequency, '^every ([0-9]+) hours$'))[1]::int * 3600 END AS cadence_seconds
    FROM source_contracts
)
SELECT f.source_id, to_char(p.as_of AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS as_of,
       to_char(f.latest_accepted_event_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS latest_accepted_event_at, floor(extract(epoch FROM p.as_of - f.latest_accepted_event_at))::bigint AS freshness_seconds,
       'recorded' AS freshness_scope,
       (SELECT floor(extract(epoch FROM p.as_of - max(c.committed_at)))::bigint FROM checkpoints c JOIN ingestion_batches b ON b.batch_id = c.batch_id AND b.status = 'committed' WHERE c.source_id = f.source_id) AS ingestion_age_seconds,
       'complete_world' AS ingestion_age_scope, cad.freshness_target_seconds, cad.cadence_seconds,
       floor(extract(epoch FROM p.as_of - f.latest_accepted_event_at)) > cad.freshness_target_seconds AS over_target, floor(extract(epoch FROM p.as_of - f.latest_accepted_event_at)) > 2 * cad.cadence_seconds AS silent,
       (SELECT sum(e.expected_records) FROM source_expectations e WHERE e.source_id = f.source_id) AS expected_records,
       (SELECT sum(y.accepted_unique) FROM artifact_batch_summaries y WHERE y.source_id = f.source_id AND y.status = 'committed') AS accepted_records, 'complete_world' AS completeness_scope
FROM artifact_recorded_freshness f JOIN cad ON cad.source_id = f.source_id, po_p p ORDER BY f.source_id COLLATE "C"
