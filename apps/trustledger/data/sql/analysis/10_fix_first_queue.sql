-- P07-ART-04 investigation 10: which data issues should be fixed first, and who is accountable? (P07-GOAL-01; D-03 issue classes, D-02 ownership.)
-- The queue is every UNRESOLVED issue (open, investigating, reopened or claimed: a claim is not a resolution) ordered by a stated rule, never by a hidden score:
--   1. severity (critical, high, medium, low);   2. an issue whose accountable owner is no longer active comes before one that has an active owner (nobody can act on it);
--   3. the older detection first;   4. the issue id (code-point order) to make the order total.
-- The ordering is a recommendation rule of this analysis, not a contract metric; the counts it ranks are the contract's. Observed on the loaded snapshot at its as-of.

-- @@ unresolved_by_severity_and_class
SELECT severity, count(*) FILTER (WHERE class = 'open') AS open, count(*) FILTER (WHERE class = 'claimed') AS claimed, count(*) AS unresolved
FROM tl_issue WHERE class <> 'resolved' GROUP BY severity ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END

-- @@ accountability
-- Who can act: unresolved issues by the state of the issue's owner and of the dataset's owner at the as-of.
SELECT count(*) AS unresolved,
       count(*) FILTER (WHERE NOT io.active) AS issue_owner_inactive,
       count(*) FILTER (WHERE NOT dow.active) AS dataset_owner_inactive,
       count(*) FILTER (WHERE NOT io.active OR NOT dow.active) AS either_owner_inactive,
       count(*) FILTER (WHERE i.severity IN ('critical', 'high')) AS critical_or_high,
       count(*) FILTER (WHERE i.severity IN ('critical', 'high') AND (NOT io.active OR NOT dow.active)) AS critical_or_high_with_an_inactive_owner
FROM tl_issue i JOIN owners io ON io.owner_id = i.owner_id JOIN owners dow ON dow.owner_id = i.dataset_owner_id WHERE i.class <> 'resolved'

-- @@ by_team
-- The accountable team of an unresolved issue is its owner's team.
SELECT o.team, count(*) AS unresolved, count(*) FILTER (WHERE i.class = 'claimed') AS claimed, count(*) FILTER (WHERE i.severity IN ('critical', 'high')) AS critical_or_high,
       count(*) FILTER (WHERE NOT o.active) AS owner_inactive, tl_iso(min(i.detected_at)) AS oldest_detected_at
FROM tl_issue i JOIN owners o ON o.owner_id = i.owner_id WHERE i.class <> 'resolved' GROUP BY o.team ORDER BY unresolved DESC, o.team COLLATE "C"

-- @@ queue_top
SELECT row_number() OVER w AS rank, i.issue_id, i.dataset_id, i.rule_id, i.severity, i.class, i.status, round(i.hours / 24, 1) AS age_days, i.owner_id, o.team AS owner_team,
       o.active AS owner_active, dow.active AS dataset_owner_active
FROM tl_issue i JOIN owners o ON o.owner_id = i.owner_id JOIN owners dow ON dow.owner_id = i.dataset_owner_id WHERE i.class <> 'resolved'
WINDOW w AS (ORDER BY CASE i.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, (CASE WHEN o.active THEN 1 ELSE 0 END), i.detected_at, i.issue_id COLLATE "C")
ORDER BY rank LIMIT 15

-- @@ datasets_with_the_most_unresolved_serious_issues
-- Critical and high issues unresolved, by dataset: where a fix removes the most serious work.
SELECT i.dataset_id, count(*) AS unresolved_critical_or_high, count(*) FILTER (WHERE i.class = 'claimed') AS claimed, dow.team AS dataset_owner_team, dow.active AS dataset_owner_active
FROM tl_issue i JOIN owners dow ON dow.owner_id = i.dataset_owner_id WHERE i.class <> 'resolved' AND i.severity IN ('critical', 'high')
GROUP BY i.dataset_id, dow.team, dow.active ORDER BY unresolved_critical_or_high DESC, i.dataset_id COLLATE "C" LIMIT 10

-- @@ ordering_sensitivity
-- How much the stated rule matters: the first 15 of the stated order against two simpler orders (severity then age; age alone), by overlap, and how many of each first 15 have an inactive owner.
WITH u AS (
    SELECT i.issue_id, i.severity, i.detected_at, o.active,
           row_number() OVER (ORDER BY CASE i.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, (CASE WHEN o.active THEN 1 ELSE 0 END), i.detected_at, i.issue_id COLLATE "C") AS r_stated,
           row_number() OVER (ORDER BY CASE i.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, i.detected_at, i.issue_id COLLATE "C") AS r_sev_age,
           row_number() OVER (ORDER BY i.detected_at, i.issue_id COLLATE "C") AS r_age
    FROM tl_issue i JOIN owners o ON o.owner_id = i.owner_id WHERE i.class <> 'resolved')
SELECT 15 AS first_n,
       count(*) FILTER (WHERE r_stated <= 15 AND r_sev_age <= 15) AS overlap_with_severity_then_age,
       count(*) FILTER (WHERE r_stated <= 15 AND r_age <= 15) AS overlap_with_age_only,
       count(*) FILTER (WHERE r_stated <= 15 AND NOT active) AS stated_with_an_inactive_owner,
       count(*) FILTER (WHERE r_sev_age <= 15 AND NOT active) AS severity_then_age_with_an_inactive_owner,
       count(*) FILTER (WHERE r_age <= 15 AND NOT active) AS age_only_with_an_inactive_owner
FROM u
