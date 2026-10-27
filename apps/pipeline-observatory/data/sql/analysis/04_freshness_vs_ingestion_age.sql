-- P08-ART-04 investigation 04: freshness against ingestion age per source, and the silent source (D-02, D-P8-03, P08-MET-01/02, P08-TEST-06, DR-01): freshness = as-of minus the
-- latest ACCEPTED event; ingestion age = as-of minus the last COMMITTED batch. They are different clocks: a source that keeps committing the same page again is young by the
-- second and old by the first, and every job stays green.
-- Question: which sources are fresh, which are merely running, and what did the gate see?
-- SCOPE. Ingestion age: complete world, recomputed here from the checkpoints (published in full). Freshness: RECORDED. The latest accepted event of each source needs every raw
-- row; the published raw_records is a 2,000-row sample whose latest events are meaningless, so the generator's recorded instants (manifest stats.freshness_at_as_of, loaded as
-- artifact_recorded_freshness) are the input and the seconds are recomputed from them. Expected records: complete world (source_expectations, published in full).

-- @@ ingestion_age
-- Last successful ingestion = the latest checkpoint of a committed batch; seconds are whole (floor), minutes to 4 places.
SELECT c.source_id, to_char(max(c.committed_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS last_successful_ingestion_at,
       floor(extract(epoch FROM p.as_of - max(c.committed_at)))::bigint AS ingestion_age_seconds,
       round(floor(extract(epoch FROM p.as_of - max(c.committed_at)))::numeric / 60, 4) AS ingestion_age_minutes,
       max(c.version_number) AS checkpoint_version, count(*) AS committed_batches
FROM checkpoints c JOIN ingestion_batches b ON b.batch_id = c.batch_id AND b.status = 'committed', po_p p
GROUP BY c.source_id, p.as_of ORDER BY c.source_id COLLATE "C"

-- @@ freshness_vs_age
-- Freshness from the recorded latest accepted event, beside the ingestion age, the declared target and the declared cadence. over_target is what the gate's critical check
-- sees; silent is the display rule of the site (freshness above two declared cadences, D-08), not a contract rule.
WITH cad AS (
    SELECT source_id, expected_frequency, freshness_target_seconds,
           CASE WHEN expected_frequency = 'daily' THEN 86400 ELSE (regexp_match(expected_frequency, '^every ([0-9]+) hours$'))[1]::int * 3600 END AS cadence_seconds
    FROM source_contracts
), age AS (
    SELECT c.source_id, floor(extract(epoch FROM p.as_of - max(c.committed_at)))::bigint AS ingestion_age_seconds
    FROM checkpoints c JOIN ingestion_batches b ON b.batch_id = c.batch_id AND b.status = 'committed', po_p p GROUP BY c.source_id, p.as_of
), fr AS (
    SELECT f.source_id, f.latest_accepted_event_at, f.recorded_freshness_seconds, f.recorded_ingestion_age_seconds,
           floor(extract(epoch FROM p.as_of - f.latest_accepted_event_at))::bigint AS freshness_seconds
    FROM artifact_recorded_freshness f, po_p p
)
SELECT fr.source_id, to_char(fr.latest_accepted_event_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS latest_accepted_event_at, fr.freshness_seconds,
       round(fr.freshness_seconds::numeric / 60, 4) AS freshness_minutes, fr.recorded_freshness_seconds, age.ingestion_age_seconds, fr.recorded_ingestion_age_seconds,
       fr.freshness_seconds - age.ingestion_age_seconds AS gap_seconds, cad.freshness_target_seconds, fr.freshness_seconds > cad.freshness_target_seconds AS over_target,
       cad.cadence_seconds, fr.freshness_seconds > 2 * cad.cadence_seconds AS silent
FROM fr JOIN age ON age.source_id = fr.source_id JOIN cad ON cad.source_id = fr.source_id ORDER BY fr.source_id COLLATE "C"

-- @@ silent_source
-- For each silent source: when it went quiet (the first UTC midnight after its latest accepted event), and what the pipeline did meanwhile: runs kept succeeding, the gate kept
-- allowing, the freshness check kept passing (its target is looser than the silence), batches kept committing and brought nothing new.
WITH cad AS (
    SELECT source_id, CASE WHEN expected_frequency = 'daily' THEN 86400 ELSE (regexp_match(expected_frequency, '^every ([0-9]+) hours$'))[1]::int * 3600 END AS cadence_seconds
    FROM source_contracts
), silent AS (
    SELECT f.source_id, (date_trunc('day', f.latest_accepted_event_at AT TIME ZONE 'UTC') + interval '1 day') AT TIME ZONE 'UTC' AS since
    FROM artifact_recorded_freshness f JOIN cad ON cad.source_id = f.source_id, po_p p
    WHERE floor(extract(epoch FROM p.as_of - f.latest_accepted_event_at)) > 2 * cad.cadence_seconds
)
SELECT s.source_id, to_char(s.since AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS silent_since,
       (SELECT count(*) FROM po_run r WHERE r.started_at >= s.since) AS runs_since,
       (SELECT count(*) FROM po_run r WHERE r.started_at >= s.since AND r.status = 'success') AS runs_succeeded,
       (SELECT count(*) FROM po_run r WHERE r.started_at >= s.since AND r.gate_decision = 'allowed') AS runs_allowed_by_the_gate,
       (SELECT count(*) FROM po_run r JOIN po_gate_result g ON g.run_id = r.run_id AND g.rule_name = 'freshness_within_target' WHERE r.started_at >= s.since AND g.failure_count = 0) AS freshness_checks_passed,
       (SELECT count(*) FROM ingestion_batches b WHERE b.source_id = s.source_id AND b.status = 'committed' AND b.started_at >= s.since) AS committed_batches_since,
       (SELECT count(*) FROM ingestion_batches b JOIN artifact_batch_summaries y ON y.batch_id = b.batch_id
         WHERE b.source_id = s.source_id AND b.status = 'committed' AND b.started_at >= s.since AND y.accepted_unique = 0) AS batches_with_no_accepted_record,
       (SELECT coalesce(sum(y.accepted_unique), 0) FROM ingestion_batches b JOIN artifact_batch_summaries y ON y.batch_id = b.batch_id
         WHERE b.source_id = s.source_id AND b.status = 'committed' AND b.started_at >= s.since) AS accepted_since,
       (SELECT coalesce(sum(y.duplicate), 0) FROM ingestion_batches b JOIN artifact_batch_summaries y ON y.batch_id = b.batch_id
         WHERE b.source_id = s.source_id AND b.status = 'committed' AND b.started_at >= s.since) AS duplicates_since
FROM silent s ORDER BY s.source_id COLLATE "C"

-- @@ silent_partitions
-- The partitions a silent source was expected to fill after it went quiet (the declared expectation, published in full); the generator records completeness 0.000000 on each.
WITH cad AS (
    SELECT source_id, CASE WHEN expected_frequency = 'daily' THEN 86400 ELSE (regexp_match(expected_frequency, '^every ([0-9]+) hours$'))[1]::int * 3600 END AS cadence_seconds
    FROM source_contracts
)
SELECT e.source_id, e.partition, e.expected_records
FROM source_expectations e JOIN artifact_recorded_freshness f ON f.source_id = e.source_id JOIN cad ON cad.source_id = e.source_id, po_p p
WHERE floor(extract(epoch FROM p.as_of - f.latest_accepted_event_at)) > 2 * cad.cadence_seconds
  AND e.partition COLLATE "C" >= to_char(date_trunc('day', f.latest_accepted_event_at AT TIME ZONE 'UTC') + interval '1 day', 'YYYY-MM-DD')
ORDER BY e.source_id COLLATE "C", e.partition COLLATE "C"

-- @@ completeness
-- Completeness against the declared expectation, per source over all 56 partitions: accepted unique / expected (not capped). Expected records: complete world. Accepted records:
-- complete world, from the per-batch summaries. The whole-window ratio hides a stale tail: src-refunds is the lowest source, and its last three days are empty.
SELECT e.source_id, count(*) AS partitions, sum(e.expected_records) AS expected_records,
       (SELECT sum(y.accepted_unique) FROM artifact_batch_summaries y WHERE y.source_id = e.source_id AND y.status = 'committed') AS accepted_records,
       round((SELECT sum(y.accepted_unique) FROM artifact_batch_summaries y WHERE y.source_id = e.source_id AND y.status = 'committed')::numeric / sum(e.expected_records), 6) AS completeness
FROM source_expectations e GROUP BY e.source_id ORDER BY e.source_id COLLATE "C"
