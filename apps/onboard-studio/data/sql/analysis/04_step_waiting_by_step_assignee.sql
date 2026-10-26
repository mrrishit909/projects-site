-- 04: step waiting time by step and by person, business hours (P02-MET-09, P02-GOLD-05, D-04, D-05).
-- Step waiting (wait_bh) = business hours from ready_at to started_at (steps never started are excluded).
-- started_to_decision_bh is the business time from started_at to the approval decision and started_to_decision_cal_h the
-- same on the wall clock; both only for decided steps and, for customer-facing steps, they include customer waiting. Three lenses on the same step instances:
--   step      one row per step name (v1 and v2 definitions of the same name pooled);
--   assignee  approve_account by the assignee holding the step when it started (assignments is the work owner);
--   reviewer  approve_account by the approving reviewer (approvals is the decision owner). 'undecided' = still open.
-- The generator planted a bottleneck at approve_account for reviewer rev-004 (data/injection-manifest.json); the
-- assignee lens is here to show whether it would be visible if only assignments were analysed.
WITH s AS (
    SELECT sd.step_name, si.step_instance_id,
           os_business_seconds(si.ready_at, si.started_at, cf.calendar_id) AS wait_s,
           CASE WHEN ap.decided_at IS NOT NULL
                THEN os_business_seconds(si.started_at, ap.decided_at, cf.calendar_id) END AS review_s,
           EXTRACT(EPOCH FROM (ap.decided_at - si.started_at)) AS decision_cal_s,
           a.assignee_id AS assignee, COALESCE(ap.reviewer_id, 'undecided') AS reviewer
      FROM step_instances si
      JOIN step_definitions sd USING (step_definition_id)
      JOIN os_case_facts cf USING (case_id)
      LEFT JOIN approvals ap ON ap.step_instance_id = si.step_instance_id
      LEFT JOIN LATERAL (SELECT assignee_id FROM assignments x
                          WHERE x.step_instance_id = si.step_instance_id AND x.assigned_at <= si.started_at
                          ORDER BY x.assigned_at DESC LIMIT 1) a ON true
     WHERE si.started_at IS NOT NULL AND si.ready_at IS NOT NULL),
lens AS (
    SELECT 'step' AS lens, 0 AS lo, step_name, 'ALL' AS who, wait_s, review_s, decision_cal_s FROM s
    UNION ALL SELECT 'assignee', 1, step_name, assignee, wait_s, review_s, decision_cal_s FROM s WHERE step_name = 'approve_account'
    UNION ALL SELECT 'reviewer', 2, step_name, reviewer, wait_s, review_s, decision_cal_s FROM s WHERE step_name = 'approve_account')
SELECT lens, step_name, who,
       count(*)::int                                    AS step_instances,
       round(avg(wait_s) / 3600, 4)                     AS wait_bh,
       round(avg(review_s) / 3600, 4)                   AS started_to_decision_bh,
       round(avg(decision_cal_s) / 3600, 4)             AS started_to_decision_cal_h
  FROM lens
 GROUP BY lo, lens, step_name, who
 ORDER BY lo, wait_bh DESC, who;
