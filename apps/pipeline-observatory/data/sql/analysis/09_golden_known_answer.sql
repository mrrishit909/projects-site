-- P08-ART-04 investigation 09: the golden known answer, computed in SQL from the golden fixture loaded into its own scratch database (P08-GOLD-01, D-01..D-05, D-P8-01..13).
-- Ten rows arrive: 8 valid unique, 1 duplicate of a valid key, 1 negative quantity: received 10, accepted unique 8, duplicate 1, quarantined 1 (rates 0.100000 and 0.100000). Replaying
-- the batch leaves 8; a crash after the data write and before the checkpoint leaves 8 and the checkpoint at version 2; freshness 52,200 s against an ingestion age of 42,900 s;
-- completeness 8 of 9; one retried task (task success 1.000000, attempt success 0.800000); a gate that allows, blocks and allows with the pointer on pub-001, pub-001, pub-003; one
-- late event, none lost; a residual of 0.00 with exclusions of -30.00 and 29.97; a verified recovery of 475.0000 minutes; backfill coverage 2 of 3; 0.666667 records per second.
-- run_all.py compares every figure here with tests/fixtures/golden/expected.json (the hand answer, CALCULATION.md), the Python domain and data/sql/reference_metrics.sql.
-- Runs on the GOLDEN database after 00_definitions.sql. The classification is the one the seeder stored (the domain's); the reference SQL, which never reads it, is the cross-check.
-- SCOPE. The golden fixture is a hand-worked 32-row world: every figure here is complete over it; none of it is a statement about the 2026-10-05 snapshot.

-- @@ batches
SELECT b.batch_id, b.source_id, b.status, count(r.raw_record_id) AS written_rows,
       CASE WHEN b.status = 'committed' THEN count(r.raw_record_id) ELSE 0 END AS received,
       count(*) FILTER (WHERE r.disposition = 'accepted' AND b.status = 'committed') AS accepted_unique, count(*) FILTER (WHERE r.disposition = 'duplicate' AND b.status = 'committed') AS duplicate,
       count(*) FILTER (WHERE r.disposition = 'quarantined' AND b.status = 'committed') AS quarantined,
       round(count(*) FILTER (WHERE r.disposition = 'quarantined' AND b.status = 'committed')::numeric / nullif(CASE WHEN b.status = 'committed' THEN count(r.raw_record_id) ELSE 0 END, 0), 6) AS rejection_rate,
       round(count(*) FILTER (WHERE r.disposition = 'duplicate' AND b.status = 'committed')::numeric / nullif(CASE WHEN b.status = 'committed' THEN count(r.raw_record_id) ELSE 0 END, 0), 6) AS duplicate_rate
FROM ingestion_batches b LEFT JOIN raw_records r ON r.batch_id = b.batch_id GROUP BY b.batch_id, b.source_id, b.status ORDER BY b.batch_id COLLATE "C"

-- @@ sources
SELECT b.source_id, count(DISTINCT b.batch_id) FILTER (WHERE b.status = 'committed') AS committed_batches,
       count(*) FILTER (WHERE b.status = 'committed') AS received, count(*) FILTER (WHERE b.status = 'committed' AND r.disposition = 'accepted') AS accepted_unique,
       count(*) FILTER (WHERE b.status = 'committed' AND r.disposition = 'duplicate') AS duplicate, count(*) FILTER (WHERE b.status = 'committed' AND r.disposition = 'quarantined') AS quarantined,
       count(DISTINCT r.source_key) FILTER (WHERE b.status = 'committed' AND r.disposition = 'quarantined') AS quarantined_distinct_keys,
       round(count(*) FILTER (WHERE b.status = 'committed' AND r.disposition = 'quarantined')::numeric / nullif(count(*) FILTER (WHERE b.status = 'committed'), 0), 6) AS rejection_rate,
       round(count(*) FILTER (WHERE b.status = 'committed' AND r.disposition = 'duplicate')::numeric / nullif(count(*) FILTER (WHERE b.status = 'committed'), 0), 6) AS duplicate_rate,
       (SELECT max(c.version_number) FROM checkpoints c WHERE c.source_id = b.source_id) AS checkpoint_version
FROM ingestion_batches b LEFT JOIN raw_records r ON r.batch_id = b.batch_id GROUP BY b.source_id ORDER BY b.source_id COLLATE "C"

-- @@ replay_and_crash
-- P08-TEST-01 on the fixture: the replay b-002 adds no accepted record; the crashed batch b-003 wrote rows and no checkpoint. Every key of the crashed batch is already accepted or already quarantined (ORD-1009, the negative row), so this
-- fixture alone cannot make a ninth record (the crash case is vacuous here; the backend test crashes a batch with a NEW key). The checkpoint stays at version 2.
SELECT 'src-orders' AS source_id, (SELECT count(*) FROM accepted_records WHERE source_id = 'src-orders') AS accepted_keys,
       (SELECT count(DISTINCT source_key) FROM accepted_records WHERE source_id = 'src-orders') AS distinct_accepted_keys,
       (SELECT count(*) FROM accepted_records WHERE batch_id = 'b-002') AS accepted_by_the_replay,
       (SELECT count(*) FROM raw_records WHERE batch_id = 'b-003') AS rows_written_by_the_crashed_batch,
       (SELECT count(*) FROM checkpoints WHERE batch_id = 'b-003') AS checkpoints_of_the_crashed_batch,
       (SELECT count(DISTINCT r.source_key) FROM raw_records r WHERE r.batch_id = 'b-003' AND r.source_key NOT IN (SELECT source_key FROM accepted_records WHERE source_id = 'src-orders')
           AND r.source_key NOT IN (SELECT q.source_key FROM quarantine_records q WHERE q.source_key IS NOT NULL)) AS new_keys_in_the_crashed_batch,
       (SELECT max(version_number) FROM checkpoints WHERE source_id = 'src-orders') AS checkpoint_version

-- @@ freshness
-- Freshness = as-of minus the latest ACCEPTED event; ingestion age = as-of minus the last committed batch: 52,200 s against 42,900 s for orders (a green job, a stale source).
SELECT a.source_id, to_char(max((r.payload_json ->> 'event_ts')::timestamptz) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS latest_accepted_event_at,
       floor(extract(epoch FROM p.as_of - max((r.payload_json ->> 'event_ts')::timestamptz)))::bigint AS freshness_seconds,
       to_char((SELECT max(c.committed_at) FROM checkpoints c WHERE c.source_id = a.source_id) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS last_successful_ingestion_at,
       floor(extract(epoch FROM p.as_of - (SELECT max(c.committed_at) FROM checkpoints c WHERE c.source_id = a.source_id)))::bigint AS ingestion_age_seconds
FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id, po_p p GROUP BY a.source_id, p.as_of ORDER BY a.source_id COLLATE "C"

-- @@ completeness
-- Completeness = accepted unique of the partition (the UTC date of the event) / the declared expectation (which counts rows that later fail): 8 of 9 = 0.888889.
SELECT e.source_id, e.partition, e.expected_records,
       (SELECT count(*) FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id
         WHERE a.source_id = e.source_id AND to_char((r.payload_json ->> 'event_ts')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD') = e.partition) AS accepted_records,
       round((SELECT count(*) FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id
               WHERE a.source_id = e.source_id AND to_char((r.payload_json ->> 'event_ts')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD') = e.partition)::numeric / nullif(e.expected_records, 0), 6) AS completeness
FROM source_expectations e ORDER BY e.source_id COLLATE "C", e.partition COLLATE "C"

-- @@ runs
-- Tasks against attempts per run: run-001 retried transform once, so four tasks and five attempts: task success 1.000000, attempt success 0.800000.
SELECT r.run_id, r.status, floor(extract(epoch FROM r.finished_at - r.started_at))::bigint AS duration_seconds, count(DISTINCT t.task_name) AS tasks_terminal,
       count(DISTINCT t.task_name) FILTER (WHERE t.status = 'success' AND t.attempt = (SELECT max(x.attempt) FROM task_runs x WHERE x.run_id = t.run_id AND x.task_name = t.task_name)) AS tasks_successful,
       round(count(DISTINCT t.task_name) FILTER (WHERE t.status = 'success' AND t.attempt = (SELECT max(x.attempt) FROM task_runs x WHERE x.run_id = t.run_id AND x.task_name = t.task_name))::numeric
             / count(DISTINCT t.task_name), 6) AS task_success_rate,
       count(*) AS attempts, count(*) FILTER (WHERE t.status = 'success') AS attempts_successful, round(count(*) FILTER (WHERE t.status = 'success')::numeric / count(*), 6) AS attempt_success_rate
FROM pipeline_runs r JOIN task_runs t ON t.run_id = r.run_id GROUP BY r.run_id, r.status, r.started_at, r.finished_at ORDER BY r.run_id COLLATE "C"

-- @@ runs_overall
SELECT count(DISTINCT (t.run_id, t.task_name)) AS tasks_terminal,
       count(DISTINCT (t.run_id, t.task_name)) FILTER (WHERE t.status = 'success' AND t.attempt = (SELECT max(x.attempt) FROM task_runs x WHERE x.run_id = t.run_id AND x.task_name = t.task_name)) AS tasks_successful,
       round(count(DISTINCT (t.run_id, t.task_name)) FILTER (WHERE t.status = 'success' AND t.attempt = (SELECT max(x.attempt) FROM task_runs x WHERE x.run_id = t.run_id AND x.task_name = t.task_name))::numeric
             / count(DISTINCT (t.run_id, t.task_name)), 6) AS task_success_rate,
       count(*) AS attempts, count(*) FILTER (WHERE t.status = 'success') AS attempts_successful, round(count(*) FILTER (WHERE t.status = 'success')::numeric / count(*), 6) AS attempt_success_rate
FROM task_runs t

-- @@ gate_pointer
-- The gate decides, the pointer follows: allowed, blocked, allowed; the pointer moves to pub-001, stays on pub-001, moves to pub-003. A blocked run publishes nothing.
SELECT r.run_id, r.gate_decision, count(g.rule_name) FILTER (WHERE g.severity = 'critical' AND g.failure_count > 0) AS critical_failures,
       count(g.rule_name) FILTER (WHERE g.severity = 'warning' AND g.failure_count > 0) AS noncritical_failures, r.published AS publication_exists,
       (SELECT p.publication_id FROM publications p JOIN pipeline_runs x ON x.run_id = p.run_id WHERE x.started_at <= r.started_at ORDER BY x.started_at DESC LIMIT 1) AS pointer_after
FROM po_run r LEFT JOIN po_gate_result g ON g.run_id = r.run_id GROUP BY r.run_id, r.gate_decision, r.published, r.started_at ORDER BY r.run_id COLLATE "C"

-- @@ publications
-- Lag = published_at minus the latest included event; the watermark is disclosed with the publication (distinct from that event).
WITH inc AS (
    SELECT p.publication_id, p.published_at, p.watermark, p.included_batch_ids,
           (SELECT max((r.payload_json ->> 'event_ts')::timestamptz) FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id WHERE a.batch_id = ANY (p.included_batch_ids)) AS latest_event,
           (SELECT count(*) FROM accepted_records a WHERE a.batch_id = ANY (p.included_batch_ids)) AS published_records
    FROM publications p
)
SELECT publication_id, to_char(published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS published_at, to_char(watermark AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS watermark,
       array_to_string(included_batch_ids, ',') AS included_batches, published_records, to_char(latest_event AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS latest_included_event_at,
       floor(extract(epoch FROM published_at - latest_event))::bigint AS lag_seconds
FROM inc ORDER BY publication_id COLLATE "C"

-- @@ late_event
-- A late event: accepted from a batch committed AFTER the latest earlier publication covering its source, with an event no later than that publication's watermark. REF-2001 arrives
-- at 11:05 behind pub-001 (watermark 10:00, event 09:10) and is included in the next publication, pub-003: counted, included, none lost.
SELECT a.source_id, a.source_key, a.batch_id, to_char((r.payload_json ->> 'event_ts')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS event_at,
       to_char(c.committed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS arrival_at, prev.publication_id AS behind_publication_id,
       to_char(prev.watermark AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS watermark, nxt.publication_id AS included_in_publication_id
FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id JOIN checkpoints c ON c.batch_id = a.batch_id
JOIN LATERAL (SELECT p.publication_id, p.watermark FROM publications p WHERE a.source_id = ANY (p.source_ids) AND p.published_at <= c.committed_at ORDER BY p.published_at DESC LIMIT 1) prev ON true
LEFT JOIN LATERAL (SELECT p.publication_id FROM publications p WHERE p.published_at > c.committed_at AND a.batch_id = ANY (p.included_batch_ids) ORDER BY p.published_at LIMIT 1) nxt ON true
WHERE (r.payload_json ->> 'event_ts')::timestamptz <= prev.watermark ORDER BY a.source_key COLLATE "C"

-- @@ reconciliation
-- Residual = source total - published total - explained exclusions, with its parts. Source = every received row of the included batches; published = the accepted rows; the exclusions
-- are signed (a quarantined negative amount is -30.00, a duplicate adds its amount back): pub-001 289.94 - 289.97 - (-0.03) = 0.00.
WITH amt AS (
    SELECT r.raw_record_id, r.batch_id, r.disposition, CASE WHEN r.payload_json ->> 'amount' ~ '\A-?[0-9]+(\.[0-9]{1,2})?\Z' THEN (r.payload_json ->> 'amount')::numeric ELSE 0 END AS amount
    FROM raw_records r JOIN ingestion_batches b ON b.batch_id = r.batch_id WHERE b.status = 'committed'
)
SELECT p.publication_id, to_char(sum(m.amount), 'FM9999990.00') AS source_total, to_char(sum(m.amount) FILTER (WHERE m.disposition = 'accepted'), 'FM9999990.00') AS published_total,
       to_char(coalesce(sum(m.amount) FILTER (WHERE m.disposition = 'quarantined'), 0), 'FM9999990.00') AS quarantined, to_char(coalesce(sum(m.amount) FILTER (WHERE m.disposition = 'duplicate'), 0), 'FM9999990.00') AS duplicates,
       to_char(sum(m.amount) - sum(m.amount) FILTER (WHERE m.disposition = 'accepted') - coalesce(sum(m.amount) FILTER (WHERE m.disposition IN ('quarantined', 'duplicate', 'deleted')), 0), 'FM9999990.00') AS residual
FROM publications p JOIN amt m ON m.batch_id = ANY (p.included_batch_ids) GROUP BY p.publication_id ORDER BY p.publication_id COLLATE "C"

-- @@ recovery
-- The incident opens when run-002 fails its gate (12:20) and closes on the verified recovery by run-003 (published 20:15): 28,500 s = 475.0000 minutes, never a restart.
SELECT incident_id, run_id, to_char(opened_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS detected_at, recovery_run_id, first_verified_run, recovery_run_id = first_verified_run AS recovery_is_first_verified,
       to_char(verified_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS verified_at, closed_at = verified_at AS closed_at_is_verified_instant, recovery_seconds,
       round(recovery_seconds::numeric / 60, 4) AS recovery_minutes
FROM po_incident ORDER BY incident_id COLLATE "C"

-- @@ backfill_processing
-- Backfill coverage = verified partitions / requested partitions (2 of 3 = 0.666667); processing rate = accepted records of the measured batch / measured seconds, hardware and cache state
-- disclosed (8 / 12 s = 0.666667 on a synthetic value, not a benchmark).
SELECT b.backfill_id, b.source_id, jsonb_array_length(b.partitions) AS requested_partitions, (SELECT count(*) FROM jsonb_array_elements(b.partitions) e WHERE (e ->> 'verified')::boolean) AS verified_partitions,
       round((SELECT count(*) FROM jsonb_array_elements(b.partitions) e WHERE (e ->> 'verified')::boolean)::numeric / jsonb_array_length(b.partitions), 6) AS coverage,
       pm.batch_id AS measured_batch, pm.measured_seconds, (SELECT count(*) FROM accepted_records a WHERE a.batch_id = pm.batch_id) AS accepted_records,
       round((SELECT count(*) FROM accepted_records a WHERE a.batch_id = pm.batch_id)::numeric / pm.measured_seconds, 6) AS records_per_second, pm.cache_state
FROM backfill_requests b CROSS JOIN processing_measurements pm ORDER BY b.backfill_id COLLATE "C"
