-- 02: active elapsed time, handoffs, SLA, rework and first pass by workflow version, on comparable windows
-- (P02-MET-04, P02-MET-06..08, P02-MET-10; D-04).
-- v2 (wfv-002) was published 2025-10-01, so the 'all' window compares v1 over 18 months with v2 over 12. The
-- 'overlap' window keeps only cases opened in [2025-10-01, 2026-10-01), when both versions ran side by side.
-- active_h = business_h - paused_business_h (pause-eligible waiting is deducted). business_h is therefore also the
-- active time and sla_if_no_pause the attainment when no waiting reason is pause-eligible (the contract's other state).
-- active_sd_h is the sample standard deviation of active hours per case (for a rough interval on a difference of means).
-- active_h, handoffs_per_case and sla_attainment are over completed cases (open_cases are listed and excluded);
-- rework_rate and first_pass_rate are over every case of the cell as in the contract. pct_enterprise and
-- pct_reg_north (shares of completed cases) show whether the two populations are alike.
WITH docs AS (
    SELECT c.case_id,
           (count(d.*) > 0) AS has_submission,
           (count(d.*) FILTER (WHERE d.review_status = 'rejected') > 0) AS has_rejection
      FROM cases c LEFT JOIN document_versions d USING (case_id) GROUP BY c.case_id),
firsts AS (
    SELECT case_id,
           count(*) FILTER (WHERE review_status IN ('accepted', 'rejected')) AS first_reviewed,
           count(*) FILTER (WHERE review_status = 'accepted') AS first_accepted
      FROM (SELECT DISTINCT ON (case_id, document_type) case_id, review_status
              FROM document_versions ORDER BY case_id, document_type, version_number) x
     GROUP BY case_id),
f AS (
    SELECT cf.*, dc.has_submission, dc.has_rejection, COALESCE(fi.first_reviewed, 0) AS first_reviewed,
           COALESCE(fi.first_accepted, 0) AS first_accepted,
           (cf.opened_at >= TIMESTAMPTZ '2025-10-01 00:00:00+00' AND cf.opened_at < TIMESTAMPTZ '2026-10-01 00:00:00+00') AS in_overlap
      FROM os_case_facts cf JOIN docs dc USING (case_id) LEFT JOIN firsts fi USING (case_id)),
w AS (
    SELECT 'all (2025-04..2026-09)' AS win, 0 AS wo, * FROM f
    UNION ALL
    SELECT 'overlap (2025-10..2026-09)', 1, * FROM f WHERE in_overlap)
SELECT win AS window, workflow_version_id AS version,
       count(*) FILTER (WHERE completed_at IS NOT NULL)::int                         AS completed_cases,
       count(*) FILTER (WHERE completed_at IS NULL)::int                             AS open_cases,
       round(avg(business_s) / 3600, 4)                                              AS business_h,
       round(avg(paused_business_s) / 3600, 4)                                       AS paused_business_h,
       round(avg(active_s) / 3600, 4)                                                AS active_h,
       round(stddev_samp(active_s) / 3600, 4)                                        AS active_sd_h,
       round(avg(handoffs) FILTER (WHERE completed_at IS NOT NULL), 4)               AS handoffs_per_case,
       round(count(*) FILTER (WHERE within_sla)::numeric / NULLIF(count(within_sla), 0), 6) AS sla_attainment,
       round(count(*) FILTER (WHERE business_s <= business_minutes * 60)::numeric
             / NULLIF(count(business_s), 0), 6)                                      AS sla_if_no_pause,
       round(count(*) FILTER (WHERE has_rejection)::numeric / NULLIF(count(*) FILTER (WHERE has_submission), 0), 6) AS rework_rate,
       round(sum(first_accepted)::numeric / NULLIF(sum(first_reviewed), 0), 6)       AS first_pass_rate,
       round(100.0 * count(*) FILTER (WHERE segment = 'enterprise' AND completed_at IS NOT NULL)
             / NULLIF(count(*) FILTER (WHERE completed_at IS NOT NULL), 0), 1)       AS pct_enterprise,
       round(100.0 * count(*) FILTER (WHERE region = 'reg-north' AND completed_at IS NOT NULL)
             / NULLIF(count(*) FILTER (WHERE completed_at IS NOT NULL), 0), 1)       AS pct_reg_north
  FROM w
 GROUP BY wo, win, workflow_version_id
 ORDER BY wo, workflow_version_id;
