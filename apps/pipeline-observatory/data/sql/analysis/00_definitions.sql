-- P08-ART-04 setup: the as-of, the gate result of every run and the stage and failure kind of every run, into TEMPORARY tables for investigations 01..10.
-- Read only: it creates temporary tables in the session and writes nothing to the loaded schema. Run by data/sql/analysis/run_all.py (blocks marked `-- @@ name`,
-- one statement each). This is the analysis's OWN formulation of D-02, D-03, D-08 and D-09; it shares no text with data/sql/reference_metrics.sql, and run_all.py
-- reconciles every figure taken from these tables with that reference, with the Python domain and with the published manifests.
--
-- Population. The as-of is the loaded dataset version's as_of (dataset_versions.as_of). Gate (D-P8-08, D-06): the latest result of a rule name in a run counts; a run
-- REACHED the gate when it has quality results; its decision is allowed iff at least one critical result exists and none failed, else blocked; a run that did not reach
-- the gate has no decision. Failure kind: a failed run that reached the gate is named for its failed critical check (freshness_within_target = freshness,
-- relationships_intact = relationships, reconciliation_residual_zero = residual); a failed run that did not reach it, for the task that failed last (ingest, transform,
-- quality_gate = gate_infra). Scope: every table read here is the COMPLETE world (runs, tasks and quality results are published in full).

-- @@ p
CREATE TEMP TABLE po_p AS
SELECT as_of FROM dataset_versions ORDER BY created_at DESC, dataset_version COLLATE "C" DESC LIMIT 1

-- @@ gate_result
CREATE TEMP TABLE po_gate_result AS
SELECT run_id, rule_name, severity, eligible_count, failure_count
FROM (SELECT t.run_id, q.rule_name, q.severity, q.eligible_count, q.failure_count,
             row_number() OVER (PARTITION BY t.run_id, q.rule_name ORDER BY q.quality_result_id COLLATE "C" DESC) AS rn
      FROM quality_results q JOIN task_runs t ON t.task_run_id = q.task_run_id) x
WHERE rn = 1

-- @@ run
CREATE TEMP TABLE po_run AS
WITH g AS (
    SELECT run_id, count(*) AS checks, count(*) FILTER (WHERE severity = 'critical') AS critical_checks,
           count(*) FILTER (WHERE severity = 'critical' AND failure_count > 0) AS critical_failed,
           min(rule_name COLLATE "C") FILTER (WHERE severity = 'critical' AND failure_count > 0) AS first_failed_critical
    FROM po_gate_result GROUP BY run_id
), last_attempt AS (
    SELECT run_id, task_name, status, row_number() OVER (PARTITION BY run_id, task_name ORDER BY attempt DESC) AS rn FROM task_runs
), ft AS (
    SELECT run_id, string_agg(task_name, ',' ORDER BY task_name COLLATE "C") AS failed_tasks FROM last_attempt WHERE rn = 1 AND status = 'failed' GROUP BY run_id
)
SELECT r.run_id, r.started_at, r.finished_at, r.status, r.backfill_id,
       floor(extract(epoch FROM r.finished_at - r.started_at))::bigint AS duration_seconds,
       coalesce(g.checks, 0) > 0 AS reached_gate,
       CASE WHEN coalesce(g.checks, 0) = 0 THEN 'not_reached'
            WHEN g.critical_checks > 0 AND g.critical_failed = 0 THEN 'allowed' ELSE 'blocked' END AS gate_decision,
       p.run_id IS NOT NULL AS published,
       CASE WHEN r.status = 'success' THEN 'published' WHEN coalesce(g.checks, 0) > 0 THEN 'blocked_at_gate' ELSE 'failed_before_gate' END AS stage,
       CASE WHEN r.status <> 'failed' THEN NULL
            WHEN g.checks > 0 THEN CASE g.first_failed_critical WHEN 'freshness_within_target' THEN 'freshness' WHEN 'relationships_intact' THEN 'relationships'
                                                                WHEN 'reconciliation_residual_zero' THEN 'residual' ELSE g.first_failed_critical END
            ELSE CASE ft.failed_tasks WHEN 'quality_gate' THEN 'gate_infra' ELSE ft.failed_tasks END END AS failure_kind
FROM pipeline_runs r LEFT JOIN g ON g.run_id = r.run_id LEFT JOIN ft ON ft.run_id = r.run_id LEFT JOIN publications p ON p.run_id = r.run_id

-- @@ incident
-- Verified recovery (D-P8-06): the first run at or after the detection (the incident's opened_at) that succeeded, was allowed by its gate, published, and passed the
-- reconciliation check; the verified instant is that run's publication. Nothing is read from the incident's own recovery_run_id or closed_at here: they are compared with this.
CREATE TEMP TABLE po_incident AS
SELECT i.incident_id, i.run_id, i.severity, i.status, i.opened_at, i.closed_at, i.recovery_run_id,
       v.run_id AS first_verified_run, p.published_at AS verified_at,
       floor(extract(epoch FROM p.published_at - i.opened_at))::bigint AS recovery_seconds
FROM incidents i
LEFT JOIN LATERAL (SELECT r.run_id FROM po_run r JOIN po_gate_result g ON g.run_id = r.run_id AND g.rule_name = 'reconciliation_residual_zero' AND g.failure_count = 0
                    WHERE r.started_at >= i.opened_at AND r.status = 'success' AND r.gate_decision = 'allowed' AND r.published
                    ORDER BY r.started_at, r.run_id COLLATE "C" LIMIT 1) v ON true
LEFT JOIN publications p ON p.run_id = v.run_id
