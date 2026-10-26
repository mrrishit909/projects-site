-- BI export 2 of 2: fact_step_instance, one row per step instance (P02-ART-06; docs/bi-package.md). Run after 00_case_facts.sql.
-- assignee_id = the assignee holding the step when it started; reviewer_id = who decided it (NULL while undecided).
-- Seconds are exact integers; steps never started have NULL started_at and NULL wait/decision seconds (the contract's null).
SELECT si.step_instance_id, si.case_id, si.step_definition_id, si.status, si.version_number,
       to_char(si.ready_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS ready_at,
       to_char(si.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at,
       to_char(ap.decided_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS decided_at,
       a.assignee_id, ap.reviewer_id,
       CASE WHEN si.started_at IS NOT NULL AND si.ready_at IS NOT NULL
            THEN os_business_seconds(si.ready_at, si.started_at, f.calendar_id)::bigint END AS wait_business_seconds,
       CASE WHEN ap.decided_at IS NOT NULL AND si.started_at IS NOT NULL THEN os_business_seconds(si.started_at, ap.decided_at, f.calendar_id)::bigint END AS started_to_decision_business_seconds,
       CASE WHEN ap.decided_at IS NOT NULL AND si.started_at IS NOT NULL THEN EXTRACT(EPOCH FROM (ap.decided_at - si.started_at))::bigint END AS started_to_decision_calendar_seconds,
       (SELECT count(DISTINCT (x.assignee_id, x.assigned_at)) - 1 FROM assignments x WHERE x.step_instance_id = si.step_instance_id)::int AS handoffs
  FROM step_instances si
  JOIN os_case_facts f USING (case_id)
  LEFT JOIN approvals ap ON ap.step_instance_id = si.step_instance_id
  LEFT JOIN LATERAL (SELECT assignee_id FROM assignments x WHERE x.step_instance_id = si.step_instance_id
                      AND x.assigned_at <= si.started_at ORDER BY x.assigned_at DESC LIMIT 1) a ON true
 ORDER BY si.step_instance_id;
