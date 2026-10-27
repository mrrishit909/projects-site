-- P08-ART-04 investigation 03: task success against attempt success (D-03, P08-MET-06): task success rate = successful terminal tasks / terminal tasks; an attempt is not a task,
-- so a task that failed twice and then passed is ONE successful task and three attempts, two of them failed.
-- Question: how reliable are the jobs when retries are allowed, and how much do the retries hide?
-- SCOPE. complete world: task_runs are published in full (5,462 attempts).

-- @@ overall
-- A task is a (run, task name); its terminal status is the status of its last attempt. Every task in the world is terminal.
WITH t AS (
    SELECT run_id, task_name, count(*) AS attempts, count(*) FILTER (WHERE status = 'success') AS ok_attempts,
           (array_agg(status ORDER BY attempt DESC))[1] AS final_status
    FROM task_runs GROUP BY run_id, task_name
)
SELECT count(*) AS tasks_terminal, count(*) FILTER (WHERE final_status = 'success') AS tasks_successful,
       round(count(*) FILTER (WHERE final_status = 'success')::numeric / count(*), 6) AS task_success_rate,
       sum(attempts) AS attempts, sum(ok_attempts) AS attempts_successful, round(sum(ok_attempts)::numeric / sum(attempts), 6) AS attempt_success_rate,
       count(*) FILTER (WHERE attempts > 1) AS tasks_retried, count(*) FILTER (WHERE attempts > 1 AND final_status = 'success') AS retried_then_succeeded
FROM t

-- @@ by_task
SELECT t.task_name, count(*) AS tasks, count(*) FILTER (WHERE t.final_status = 'success') AS tasks_successful,
       round(count(*) FILTER (WHERE t.final_status = 'success')::numeric / count(*), 6) AS task_success_rate,
       sum(t.attempts) AS attempts, sum(t.ok_attempts) AS attempts_successful, round(sum(t.ok_attempts)::numeric / sum(t.attempts), 6) AS attempt_success_rate,
       count(*) FILTER (WHERE t.attempts > 1) AS tasks_retried
FROM (SELECT run_id, task_name, count(*) AS attempts, count(*) FILTER (WHERE status = 'success') AS ok_attempts, (array_agg(status ORDER BY attempt DESC))[1] AS final_status
      FROM task_runs GROUP BY run_id, task_name) t
GROUP BY t.task_name ORDER BY t.task_name COLLATE "C"

-- @@ retry_depth
-- Tasks by the number of attempts they took and how they ended: every task that reached a third attempt failed (the retry budget is three).
SELECT t.attempts, count(*) AS tasks, count(*) FILTER (WHERE t.final_status = 'success') AS ended_success, count(*) FILTER (WHERE t.final_status = 'failed') AS ended_failed
FROM (SELECT run_id, task_name, count(*) AS attempts, (array_agg(status ORDER BY attempt DESC))[1] AS final_status FROM task_runs GROUP BY run_id, task_name) t
GROUP BY t.attempts ORDER BY t.attempts

-- @@ run_level
-- The same two rates at run level (the golden case reports them per run): a run's task success against its attempt success, summarised for failed and successful runs.
SELECT r.status, count(DISTINCT r.run_id) AS runs, count(*) AS attempts, count(*) FILTER (WHERE t.status = 'success') AS attempts_successful,
       round(count(*) FILTER (WHERE t.status = 'success')::numeric / count(*), 6) AS attempt_success_rate
FROM pipeline_runs r JOIN task_runs t ON t.run_id = r.run_id GROUP BY r.status ORDER BY r.status COLLATE "C"
