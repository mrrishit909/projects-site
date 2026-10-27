-- P08-ART-06 fact_run: one row per pipeline run (1,343) with its stage, gate decision, failure kind, duration and task counts. Scope: complete_world.
SELECT r.run_id, to_char(r.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS date_key, to_char(r.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at, r.status, r.stage, r.gate_decision,
       r.failure_kind, r.duration_seconds, r.published, r.backfill_id, i.incident_id,
       (SELECT count(*) FROM (SELECT DISTINCT task_name FROM task_runs t WHERE t.run_id = r.run_id) x) AS tasks_terminal,
       (SELECT count(*) FROM task_runs t WHERE t.run_id = r.run_id AND t.status = 'success' AND t.attempt = (SELECT max(y.attempt) FROM task_runs y WHERE y.run_id = t.run_id AND y.task_name = t.task_name)) AS tasks_successful,
       (SELECT count(*) FROM task_runs t WHERE t.run_id = r.run_id) AS attempts, (SELECT count(*) FROM task_runs t WHERE t.run_id = r.run_id AND t.status = 'success') AS attempts_successful,
       'complete_world' AS scope
FROM po_run r LEFT JOIN incidents i ON i.run_id = r.run_id ORDER BY r.run_id COLLATE "C"
