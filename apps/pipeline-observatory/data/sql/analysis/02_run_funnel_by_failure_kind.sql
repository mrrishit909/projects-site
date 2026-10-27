-- P08-ART-04 investigation 02: the run funnel by failure kind (D-09 R8-07, D-03, P08-MET-06): 1,343 hourly runs, 1,328 reached the quality gate, 1,318 were allowed, 10 were
-- blocked at the gate and 15 failed in a task before it. "25 failed" is true; "25 blocked" is not (the review finding R8-07).
-- Question: how often does the pipeline fail, where does it fail, and which failures can a gate see?
-- SCOPE. complete world: runs, tasks and quality results are published in full. The failure kind is derived (00_definitions.sql) from the failed critical check or the failed task.

-- @@ funnel
SELECT count(*) AS runs, count(*) FILTER (WHERE reached_gate) AS reached_gate, count(*) FILTER (WHERE gate_decision = 'allowed') AS allowed,
       count(*) FILTER (WHERE gate_decision = 'blocked') AS blocked_at_gate, count(*) FILTER (WHERE stage = 'failed_before_gate') AS failed_before_gate,
       count(*) FILTER (WHERE status = 'success') AS succeeded, count(*) FILTER (WHERE status = 'failed') AS failed, count(*) FILTER (WHERE published) AS published,
       count(*) FILTER (WHERE backfill_id IS NOT NULL) AS backfill_runs
FROM po_run

-- @@ by_failure_kind
-- The 25 failed runs by stage and kind, with the incident each opened and how long the run ran before it failed (whole seconds, mean in minutes to 4 places).
SELECT r.stage, r.failure_kind, count(*) AS runs, count(i.incident_id) AS incidents, round(avg(r.duration_seconds) / 60, 4) AS mean_duration_minutes,
       min(r.run_id COLLATE "C") AS first_run, max(r.run_id COLLATE "C") AS last_run
FROM po_run r LEFT JOIN incidents i ON i.run_id = r.run_id
WHERE r.status = 'failed' GROUP BY r.stage, r.failure_kind ORDER BY r.stage COLLATE "C", r.failure_kind COLLATE "C"

-- @@ gate_checks
-- What the gate asked of the 1,328 runs that reached it: seven checks each (D-09 added scope_complete and late_events_included). completeness_vs_expectation is a WARNING that
-- fails in most gates and so carries little signal; only the critical checks block.
SELECT g.rule_name, min(g.severity COLLATE "C") AS severity, count(*) AS gates, count(*) FILTER (WHERE g.failure_count > 0) AS failed,
       round(count(*) FILTER (WHERE g.failure_count > 0)::numeric / count(*), 6) AS failed_share, sum(g.eligible_count) AS eligible_total, sum(g.failure_count) AS failure_total
FROM po_gate_result g GROUP BY g.rule_name ORDER BY min(g.severity COLLATE "C"), g.rule_name COLLATE "C"

-- @@ durations
-- Run duration = finished_at - started_at in whole seconds; failed and successful runs are kept apart (P08-MET-07).
SELECT status, count(*) AS runs, min(duration_seconds) AS min_seconds, max(duration_seconds) AS max_seconds, round(avg(duration_seconds) / 60, 4) AS mean_minutes
FROM po_run GROUP BY status ORDER BY status COLLATE "C"

-- @@ failures_by_week
-- When the failures happened (UTC weeks starting Monday): not clustered by design, planned for the whole window.
SELECT to_char(w.week, 'YYYY-MM-DD') AS week_start, count(*) AS runs, count(*) FILTER (WHERE r.status = 'failed') AS failed,
       count(*) FILTER (WHERE r.gate_decision = 'blocked') AS blocked_at_gate, count(*) FILTER (WHERE r.stage = 'failed_before_gate') AS failed_before_gate
FROM po_run r CROSS JOIN LATERAL (SELECT date_trunc('week', r.started_at AT TIME ZONE 'UTC') AS week) w
GROUP BY w.week ORDER BY w.week
