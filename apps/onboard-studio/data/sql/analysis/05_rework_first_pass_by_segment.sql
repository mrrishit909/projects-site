-- 05: rework and first-pass approval by segment (P02-MET-06, P02-MET-07; D-04).
--   rework rate     = cases with at least one rejected document version / cases with at least one submission
--   first-pass rate = first submissions (version 1 of a case and document type) accepted / first submissions reviewed
--                     (pending first submissions are excluded from the denominator).
-- Rates are ratios of the printed counts, never averages of per-case rates. Cases of every status are included, as in
-- the contract. The 'document_type' rows show where first submissions fail; the 'segment' rows are the case-level view.
WITH cases_docs AS (
    SELECT c.case_id, o.segment,
           count(d.*) AS docs, count(d.*) FILTER (WHERE d.review_status = 'rejected') AS rejected_docs
      FROM cases c JOIN organizations o USING (organization_id)
      LEFT JOIN document_versions d USING (case_id)
     GROUP BY c.case_id, o.segment),
firsts AS (
    SELECT DISTINCT ON (d.case_id, d.document_type) d.case_id, o.segment, d.document_type, d.review_status
      FROM document_versions d JOIN cases c USING (case_id) JOIN organizations o USING (organization_id)
     ORDER BY d.case_id, d.document_type, d.version_number),
case_lens AS (
    SELECT 'segment' AS lens, segment, 'ALL' AS document_type,
           count(*) FILTER (WHERE docs > 0)::int AS cases_with_submission,
           count(*) FILTER (WHERE rejected_docs > 0)::int AS cases_reworked
      FROM cases_docs GROUP BY GROUPING SETS ((segment), ())),
doc_lens AS (
    SELECT CASE WHEN document_type IS NULL THEN 'segment' ELSE 'document_type' END AS lens, segment,
           COALESCE(document_type, 'ALL') AS document_type,
           count(*) FILTER (WHERE review_status IN ('accepted', 'rejected'))::int AS first_reviewed,
           count(*) FILTER (WHERE review_status = 'accepted')::int AS first_accepted
      FROM firsts GROUP BY GROUPING SETS ((segment, document_type), (segment), (document_type), ()))
SELECT COALESCE(d.lens, c.lens) AS lens, COALESCE(d.segment, c.segment, 'ALL') AS segment,
       COALESCE(d.document_type, c.document_type) AS document_type,
       c.cases_with_submission, c.cases_reworked,
       round(c.cases_reworked::numeric / NULLIF(c.cases_with_submission, 0), 6) AS rework_rate,
       d.first_reviewed, d.first_accepted,
       round(d.first_accepted::numeric / NULLIF(d.first_reviewed, 0), 6) AS first_pass_rate
  FROM doc_lens d
  FULL JOIN case_lens c ON c.lens = d.lens AND c.segment IS NOT DISTINCT FROM d.segment AND c.document_type = d.document_type
 ORDER BY (COALESCE(d.lens, c.lens) <> 'segment'), COALESCE(d.document_type, c.document_type),
          (COALESCE(d.segment, c.segment) IS NULL), COALESCE(d.segment, c.segment);
