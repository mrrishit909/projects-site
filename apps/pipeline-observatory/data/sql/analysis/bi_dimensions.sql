-- P08-ART-06 BI dimensions, exported by run_all.py --bi-out as artifacts/bi/dim_*.csv (one block, one statement, one CSV). Read only. Scope of every dimension: complete world (the contract
-- tables are published in full); dim_scope and dim_measure are the vocabulary of the SCOPE columns of the facts and of measures_recomputed.csv (D-08, D-09 R8-09).

-- @@ dim_source
SELECT c.source_id, c.source_name, c.expected_frequency, CASE WHEN c.expected_frequency = 'daily' THEN 86400 ELSE (regexp_match(c.expected_frequency, '^every ([0-9]+) hours$'))[1]::int * 3600 END AS cadence_seconds,
       c.schema_version, c.freshness_target_seconds, c.owner_id,
       (SELECT count(*) FROM source_expectations e WHERE e.source_id = c.source_id) AS partitions, (SELECT sum(e.expected_records) FROM source_expectations e WHERE e.source_id = c.source_id) AS expected_records
FROM source_contracts c ORDER BY c.source_id COLLATE "C"

-- @@ dim_date
SELECT to_char(d.day, 'YYYY-MM-DD') AS date_key, extract(year FROM d.day)::int AS year, extract(month FROM d.day)::int AS month, to_char(date_trunc('week', d.day), 'YYYY-MM-DD') AS week_start,
       extract(isodow FROM d.day)::int AS iso_weekday, to_char(d.day, 'FMDay') AS weekday_name
FROM (SELECT generate_series(min(partition::date), max(partition::date), interval '1 day')::date AS day FROM source_expectations) d ORDER BY d.day

-- @@ dim_failure_kind
-- The failure kinds of a failed run and the stage they stop at: blocked at the gate (the gate saw it) or failed before the gate (a task failed and the gate never ran).
SELECT k.failure_kind, k.stage, k.description FROM (VALUES
    ('freshness', 'blocked_at_gate', 'freshness_within_target failed: a source was older than its declared target'),
    ('relationships', 'blocked_at_gate', 'relationships_intact failed: a candidate row had no parent'),
    ('residual', 'blocked_at_gate', 'reconciliation_residual_zero failed: source total, published total and explained exclusions did not balance'),
    ('ingest', 'failed_before_gate', 'the ingest task failed on all three attempts'),
    ('transform', 'failed_before_gate', 'the transform task failed on all three attempts'),
    ('gate_infra', 'failed_before_gate', 'the quality_gate task itself failed on all three attempts: no check result exists')) AS k(failure_kind, stage, description)
ORDER BY k.failure_kind COLLATE "C"

-- @@ dim_check
SELECT g.rule_name, min(g.severity COLLATE "C") AS severity, count(*) AS gates FROM po_gate_result g GROUP BY g.rule_name ORDER BY g.rule_name COLLATE "C"

-- @@ dim_scope
SELECT s.scope, s.meaning FROM (VALUES
    ('complete_world', 'computed here from tables the published files carry in full (batches, checkpoints, runs, tasks, quality results, publications, incidents, backfills, quarantine rows, fetch log, batch summaries)'),
    ('sample', 'computed here from the 2,000-row raw_records sample (62 whole batches, 50 carrying rows): it describes the sample and not the world'),
    ('recorded', 'a statement of the generator about the complete world that the published files cannot recompute (manifest stats and designed relationships); read, not found')) AS s(scope, meaning)
ORDER BY s.scope COLLATE "C"

-- @@ dim_measure
SELECT m.measure, m.definition, m.default_scope, m.contract FROM (VALUES
    ('received', 'rows of committed batches (accepted + duplicate + quarantined + deleted)', 'complete_world', 'D-01'),
    ('accepted_unique', 'rows whose source key was not yet accepted and that satisfy the contract', 'complete_world', 'D-01, D-P8-01'),
    ('duplicate', 'rows whose source key was already accepted, whatever the payload', 'complete_world', 'D-01, D-P8-01'),
    ('quarantined', 'rows that fail the contract, one quarantine row per occurrence; the schema-quarantined batch is not in this count', 'complete_world', 'D-01, D-09 R8-10'),
    ('deleted', 'removal markers that took an accepted key out of the snapshot (an exclusion with its reason, never silently lost)', 'complete_world', 'D-06'),
    ('rejection_rate', 'quarantined / received; null for a zero denominator', 'complete_world', 'P08-MET-04'),
    ('duplicate_rate', 'duplicate / received; null for a zero denominator', 'complete_world', 'P08-MET-05'),
    ('schema_quarantined_rows', 'rows of the batch refused whole for a schema change, listed apart from every rate', 'complete_world', 'D-01 P08-TEST-04'),
    ('runs', 'hourly pipeline runs', 'complete_world', 'D-09 R8-07'),
    ('reached_gate', 'runs that have quality results', 'complete_world', 'D-09 R8-07'),
    ('allowed', 'runs the gate allowed (a critical result exists and none failed)', 'complete_world', 'D-P8-08'),
    ('blocked_at_gate', 'runs the gate blocked', 'complete_world', 'D-P8-08'),
    ('failed_before_gate', 'runs that failed in a task before the gate ran', 'complete_world', 'D-09 R8-07'),
    ('failed_runs', 'failed runs of one failure kind', 'complete_world', 'D-09 R8-07'),
    ('fetches', 'rows of the fetch log of one status', 'complete_world', 'D-09 R8-06'),
    ('silent_sources', 'sources whose freshness is above two declared cadences', 'recorded', 'D-08'),
    ('task_success_rate', 'successful terminal tasks / terminal tasks (attempts are not tasks)', 'complete_world', 'P08-MET-06'),
    ('attempt_success_rate', 'successful attempts / attempts', 'complete_world', 'P08-MET-06'),
    ('ingestion_age_seconds', 'as-of minus the last committed batch, whole seconds', 'complete_world', 'P08-MET-02'),
    ('freshness_seconds', 'as-of minus the latest accepted event, whole seconds (the generator records the event)', 'recorded', 'P08-MET-01'),
    ('silent', 'freshness above two declared cadences (a display rule, not a contract rule)', 'recorded', 'D-08'),
    ('completeness', 'accepted unique / expected records over all partitions of a source', 'complete_world', 'P08-MET-03'),
    ('incidents', 'incidents opened by a failed or blocked run', 'complete_world', 'D-03'),
    ('mean_recovery_minutes', 'mean of (verified recovery - detection), minutes to 4 places', 'complete_world', 'P08-MET-10'),
    ('backfill_coverage', 'verified partitions / requested partitions of the accepted requests', 'complete_world', 'P08-MET-11, D-09 R8-11'),
    ('refused_backfill_partitions', 'partitions of requests refused for overlap, beside the coverage and never inside it', 'complete_world', 'D-09 R8-11'),
    ('retries_honoured', 'retries after a 429 that waited at least the retry-after hint / retries', 'complete_world', 'P08-TEST-03'),
    ('late_events', 'accepted events that arrived behind the watermark of an earlier publication', 'recorded', 'P08-MET-08'),
    ('reconciliation_residual', 'source total - published total - explained exclusions of a publication', 'recorded', 'P08-MET-09'),
    ('publication_content_hash_ok', 'a publication whose recomputed content hash equals the stored one', 'recorded', 'D-P8-10')) AS m(measure, definition, default_scope, contract)
ORDER BY m.measure COLLATE "C"
