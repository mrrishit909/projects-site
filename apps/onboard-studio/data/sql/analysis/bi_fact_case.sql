-- BI export 1 of 2: fact_case, one row per case (P02-ART-06; docs/bi-package.md). Run after 00_case_facts.sql.
-- Exact integer seconds (never rounded hours) so that a BI measure divides once, like the contract. Timestamps are UTC ISO-8601.
-- Open cases have NULL completed_at and NULL *_seconds / within_sla / active_seconds (the contract's null, never 0).
WITH docs AS (
    SELECT c.case_id,
           (count(d.*) > 0)::int AS has_submission,
           (count(d.*) FILTER (WHERE d.review_status = 'rejected') > 0)::int AS has_rejection
      FROM cases c LEFT JOIN document_versions d USING (case_id) GROUP BY c.case_id),
firsts AS (
    SELECT case_id,
           count(*) FILTER (WHERE review_status IN ('accepted', 'rejected'))::int AS first_reviewed,
           count(*) FILTER (WHERE review_status = 'accepted')::int AS first_accepted
      FROM (SELECT DISTINCT ON (case_id, document_type) case_id, review_status
              FROM document_versions ORDER BY case_id, document_type, version_number) x GROUP BY case_id),
req AS (
    SELECT c.case_id, count(r.document_type)::int AS required_types,
           count(r.document_type) FILTER (WHERE EXISTS (SELECT 1 FROM document_versions d WHERE d.case_id = c.case_id
                AND d.document_type = r.document_type AND d.review_status = 'accepted'))::int AS required_accepted_types
      FROM cases c LEFT JOIN workflow_requirements r USING (workflow_version_id) GROUP BY c.case_id)
SELECT f.case_id, f.organization_id, f.workflow_version_id, f.status,
       to_char(f.opened_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS opened_at,
       to_char(f.completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS completed_at,
       (f.opened_at AT TIME ZONE 'UTC')::date AS opened_date,
       f.business_minutes::int AS sla_minutes, f.handoffs::int AS handoffs,
       f.calendar_s::bigint AS calendar_seconds, f.business_s::bigint AS business_seconds, f.paused_s::bigint AS paused_seconds,
       f.paused_business_s::bigint AS paused_business_seconds, f.active_s::bigint AS active_seconds, f.within_sla::int AS within_sla,
       d.has_submission, d.has_rejection, COALESCE(fi.first_reviewed, 0) AS first_reviewed, COALESCE(fi.first_accepted, 0) AS first_accepted,
       rq.required_types, rq.required_accepted_types
  FROM os_case_facts f
  JOIN docs d USING (case_id) LEFT JOIN firsts fi USING (case_id) JOIN req rq USING (case_id)
 ORDER BY f.case_id;
