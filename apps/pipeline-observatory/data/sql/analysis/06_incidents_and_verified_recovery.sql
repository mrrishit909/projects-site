-- P08-ART-04 investigation 06: incidents and verified recovery minutes (D-03, D-P8-06, P08-FLOW-09, P08-MET-10, DR-02, DR-05): an incident opens on a failed run or a blocked gate and
-- closes only on a VERIFIED recovery: the first run at or after the detection that succeeded, was allowed by its gate, published, and passed the reconciliation check. Recovery
-- time = the verified instant (that publication's published_at) minus the detection (the incident's opened_at); never a process restart.
-- Question: how long are readers on an older snapshot after a failure, and is every closure honest?
-- SCOPE. complete world: incidents, runs and publications are published in full. The residual of the one unexplained candidate is RECORDED (manifest DR-05); its stored candidate
-- total is the published model_output_totals row, and the recorded parts are loaded as artifact_recorded_residual.

-- @@ incidents
SELECT v.incident_id, v.run_id, r.failure_kind, v.severity, v.status, to_char(v.opened_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS detected_at,
       v.recovery_run_id, v.first_verified_run, v.recovery_run_id = v.first_verified_run AS recovery_is_first_verified,
       to_char(v.verified_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS verified_at, v.closed_at = v.verified_at AS closed_at_is_verified_instant,
       v.recovery_seconds, round(v.recovery_seconds::numeric / 60, 4) AS recovery_minutes
FROM po_incident v JOIN po_run r ON r.run_id = v.run_id ORDER BY v.incident_id COLLATE "C"

-- @@ summary
SELECT count(*) AS incidents, count(*) FILTER (WHERE status = 'open') AS open, count(*) FILTER (WHERE status = 'closed') AS closed,
       count(*) FILTER (WHERE status = 'closed' AND recovery_run_id = first_verified_run) AS verified,
       count(*) FILTER (WHERE closed_at = verified_at AND recovery_run_id = first_verified_run) AS closures_consistent,
       round(avg(recovery_seconds) / 60, 4) AS mean_recovery_minutes, round(min(recovery_seconds)::numeric / 60, 4) AS min_recovery_minutes,
       round(max(recovery_seconds)::numeric / 60, 4) AS max_recovery_minutes
FROM po_incident

-- @@ by_failure_kind
-- Recovery by what failed: a failure the next hourly run can fix recovers in about an hour; the spread is the wait for the next run plus its duration.
SELECT r.failure_kind, r.stage, count(*) AS incidents, round(avg(v.recovery_seconds) / 60, 4) AS mean_recovery_minutes, round(min(v.recovery_seconds)::numeric / 60, 4) AS min_recovery_minutes,
       round(max(v.recovery_seconds)::numeric / 60, 4) AS max_recovery_minutes
FROM po_incident v JOIN po_run r ON r.run_id = v.run_id GROUP BY r.failure_kind, r.stage ORDER BY r.failure_kind COLLATE "C"

-- @@ residual_candidate
-- DR-05: every publication reconciles to 0.00 and ONE candidate did not. Its residual = source total - published total - explained exclusions, from the recorded parts and the
-- stored candidate total; the run was blocked on reconciliation_residual_zero, opened an incident and was recovered by the next run. No cause is recorded: no quarantine,
-- duplicate or delete accounts for the amount.
SELECT x.run_id, x.day, x.source_total, x.exclusions_total, t.total_amount AS stored_candidate_total, x.published_total AS recorded_published_total,
       x.source_total - t.total_amount - x.exclusions_total AS residual, x.residual AS recorded_residual, r.stage, r.failure_kind, i.incident_id,
       (SELECT count(*) FROM publications p WHERE p.run_id = x.run_id) AS publications_of_the_run
FROM artifact_recorded_residual x JOIN artifact_model_output_totals t ON t.run_id = x.run_id JOIN po_run r ON r.run_id = x.run_id LEFT JOIN incidents i ON i.run_id = x.run_id
ORDER BY x.run_id COLLATE "C"
