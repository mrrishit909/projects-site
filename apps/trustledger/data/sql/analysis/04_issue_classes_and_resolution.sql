-- P07-ART-04 investigation 04: issue classes and resolution time (D-03, DR-04, DR-05, INJ-09).
-- Questions: how many issues are really resolved, how many were only claimed, and which team resolves fastest? An issue is `resolved` only after a successful rerun of the same
-- rule version; closed without one it is `claimed` and never counted as resolved. Mean resolution = (verifying rerun - first detected_at) in hours over resolved issues, 4 places.
-- The team of an issue is its OWNER's team (issues.owner_id -> owners.team). Observed on the loaded snapshot at its as-of.

-- @@ classes
SELECT class, count(*) AS issues, round(count(*)::numeric / sum(count(*)) OVER (), 6) AS share_of_issues, count(*) FILTER (WHERE cycles > 0) AS reopened
FROM tl_issue GROUP BY class ORDER BY CASE class WHEN 'resolved' THEN 1 WHEN 'claimed' THEN 2 ELSE 3 END

-- @@ class_by_severity
SELECT severity, count(*) FILTER (WHERE class = 'resolved') AS resolved, count(*) FILTER (WHERE class = 'claimed') AS claimed, count(*) FILTER (WHERE class = 'open') AS open,
       count(*) AS issues, count(*) FILTER (WHERE class <> 'resolved') AS unresolved
FROM tl_issue GROUP BY severity ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END

-- @@ claimed_split
-- The 99 claimed issues: closed after a rerun that did not pass (a verification was tried and failed; the failed rerun is not stored as the issue's verification run) or closed
-- with no rerun at all; and how old the unresolved are.
SELECT (SELECT count(*) FROM tl_issue WHERE class = 'claimed') AS claimed,
       (SELECT count(*) FROM tl_issue i WHERE i.class = 'claimed' AND EXISTS (SELECT 1 FROM rule_runs r WHERE r.rerun_for_issue = i.issue_id AND r.kind = 'rerun' AND r.failure_count > 0)) AS claimed_with_a_failed_rerun,
       (SELECT count(*) FROM tl_issue i WHERE i.class = 'claimed' AND NOT EXISTS (SELECT 1 FROM rule_runs r WHERE r.rerun_for_issue = i.issue_id AND r.kind = 'rerun')) AS claimed_without_a_rerun,
       (SELECT count(*) FROM tl_issue WHERE class <> 'resolved') AS unresolved,
       (SELECT tl_iso(min(detected_at)) FROM tl_issue WHERE class <> 'resolved') AS oldest_unresolved_detected_at,
       (SELECT issue_id FROM tl_issue WHERE class <> 'resolved' ORDER BY detected_at, issue_id COLLATE "C" LIMIT 1) AS oldest_unresolved_issue,
       (SELECT count(*) FROM (SELECT class FROM tl_issue WHERE class <> 'resolved' ORDER BY detected_at, issue_id COLLATE "C" LIMIT 25) x WHERE class = 'claimed') AS claimed_among_the_oldest_25_unresolved,
       (SELECT count(*) - 1 FROM (SELECT class, row_number() OVER (ORDER BY detected_at, issue_id COLLATE "C") AS rn FROM tl_issue WHERE class <> 'resolved') u
         WHERE rn <= (SELECT min(rn) FROM (SELECT class, row_number() OVER (ORDER BY detected_at, issue_id COLLATE "C") AS rn FROM tl_issue WHERE class <> 'resolved') v WHERE class <> 'claimed')) AS leading_claimed_run,
       (SELECT issue_id FROM (SELECT issue_id, class, detected_at FROM tl_issue WHERE class <> 'resolved' ORDER BY detected_at, issue_id COLLATE "C") w WHERE class <> 'claimed' LIMIT 1) AS first_not_claimed

-- @@ resolution_by_team
-- Resolved issues only; claimed and open issues are NOT in the mean (they have no verified resolution).
SELECT o.team, count(*) AS resolved, round(avg(i.hours), 4) AS mean_hours
FROM tl_issue i JOIN owners o ON o.owner_id = i.owner_id WHERE i.class = 'resolved' GROUP BY o.team ORDER BY o.team COLLATE "C"

-- @@ fast_team_vs_others
SELECT CASE WHEN o.team = 'Data Platform' THEN 'Data Platform' ELSE 'all other teams' END AS group_name, count(*) AS resolved, round(avg(i.hours), 4) AS mean_hours
FROM tl_issue i JOIN owners o ON o.owner_id = i.owner_id WHERE i.class = 'resolved' GROUP BY 1 ORDER BY 1 COLLATE "C"

-- @@ resolution_overall
SELECT count(*) AS resolved, round(avg(hours), 4) AS mean_hours,
       round((SELECT avg(hours) FROM tl_issue i JOIN owners o ON o.owner_id = i.owner_id WHERE i.class = 'resolved' AND o.team = 'Data Platform')
             / (SELECT avg(hours) FROM tl_issue i JOIN owners o ON o.owner_id = i.owner_id WHERE i.class = 'resolved' AND o.team <> 'Data Platform'), 6) AS fast_team_ratio,
       (SELECT count(*) FROM tl_issue WHERE class = 'open') AS open_count, (SELECT count(*) FROM tl_issue WHERE cycles > 0) AS reopened_issues,
       (SELECT coalesce(sum(cycles), 0) FROM tl_issue) AS reopen_cycles
FROM tl_issue WHERE class = 'resolved'

-- @@ disabled_rules
-- Disabling a rule is not repair: the five disabled rules keep their runs and issues readable and the issues stay unresolved (P07-FLOW-09, P07-TEST-02, INJ-02).
SELECT r.rule_id, r.dataset_id, tl_iso(r.disabled_at) AS disabled_at, r.disabled_reason,
       (SELECT count(*) FROM rule_runs x WHERE x.rule_id = r.rule_id) AS runs_retained,
       (SELECT count(*) FROM tl_issue i WHERE i.rule_id = r.rule_id) AS issues_retained,
       (SELECT count(*) FROM tl_issue i WHERE i.rule_id = r.rule_id AND i.class <> 'resolved') AS issues_still_unresolved
FROM quality_rules r WHERE r.status = 'disabled' ORDER BY r.rule_id COLLATE "C"
