-- 08: rejections and flags by reason (P02-TEST-01, -02, -03, -09, -10; contract D-03, D-05).
-- 'rejection' rows come from rejected_records (the raw rows ingest refused, kept under one raw_batches row): a rejected
-- case drags its child rows with it under the same reason, DECISION_CONFLICT rejects only the later approval.
-- 'flag' rows are accepted data that the contract marks: an eligible waiting interval, clipped to its completed case,
-- with zero business time (PAUSE_OUTSIDE_WORKING_INTERVAL). It deducts 0 business hours and is counted, never hidden.
-- ids lists the rejected cases (or, for DECISION_CONFLICT, approvals; for the flag, waiting intervals).
WITH rej AS (
    SELECT reason_code AS reason,
           count(*) FILTER (WHERE entity = 'cases')::int                                   AS cases,
           count(*) FILTER (WHERE entity = 'approvals')::int                               AS approvals,
           count(*) FILTER (WHERE entity NOT IN ('cases', 'approvals'))::int               AS other_child_rows,
           count(*)::int                                                                   AS total_rows,
           string_agg(id, ', ' ORDER BY id) FILTER (WHERE entity = 'cases'
                OR (reason_code = 'DECISION_CONFLICT' AND entity = 'approvals'))           AS ids
      FROM rejected_records GROUP BY reason_code),
flag AS (
    SELECT 'PAUSE_OUTSIDE_WORKING_INTERVAL' AS reason, count(*)::int AS cases, 0 AS approvals, 0 AS other_child_rows,
           count(*)::int AS total_rows, string_agg(waiting_interval_id, ', ' ORDER BY waiting_interval_id) AS ids
      FROM (SELECT w.waiting_interval_id
              FROM os_case_facts f
              JOIN waiting_intervals w ON w.case_id = f.case_id AND w.reason_code = ANY (f.pause_policy)
             WHERE f.completed_at IS NOT NULL
               AND LEAST(COALESCE(w.ends_at, f.completed_at), f.completed_at) > GREATEST(w.starts_at, f.opened_at)
               AND os_business_seconds(GREATEST(w.starts_at, f.opened_at),
                                       LEAST(COALESCE(w.ends_at, f.completed_at), f.completed_at), f.calendar_id) = 0) x)
SELECT 'rejection' AS lens, * FROM rej
UNION ALL SELECT 'flag', * FROM flag
ORDER BY 1 DESC, 2;
