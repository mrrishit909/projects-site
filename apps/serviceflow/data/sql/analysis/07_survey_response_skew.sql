-- 07_survey_response_skew.sql: who answers the survey, and what CSAT can and cannot say.
-- Decision link: whether the satisfaction figure can be used as evidence for a staffing or routing change, given that the people who had
-- a poor experience answer much less (P04-MET-11, P04-TEST-11; the injected defect INJ-09 designs this skew into the data).
-- Population: tickets whose FINAL resolution is in the whole window [2026-07-06, 2026-09-28) (the contract's CSAT population, D-05).
-- Invited = a survey row with invited_at; valid response = a score and a response_at; positive = score >= 4 of 5.
-- CSAT = positive / valid responses (D-03). Invitation rate = invited / completions; response rate = valid responses / invited.
-- A POOR experience = the first response or the resolution missed its SLA target (first response measured from the first human reply,
-- resolution from the ORIGINAL arrival), or the ticket was transferred, or it was reopened. This is this file's definition of the
-- generator's skew rule; the realised figures in web/public/data/manifest.json are over all 3,826 published tickets (see docs/sql-analysis.md).
-- @@ response_by_experience
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
pol AS (SELECT priority, first_response_minutes AS fr_t, resolution_minutes AS rs_t FROM sla_policies),
pop AS (
    SELECT t.ticket_id,
           CASE WHEN (t.first_human IS NOT NULL AND extract(epoch FROM (t.first_human - t.created_at)) > p.fr_t * 60)
                  OR extract(epoch FROM (t.final_resolved - t.created_at)) > p.rs_t * 60
                  OR t.n_transferred > 0 OR t.n_reopened > 0
                THEN 'poor experience' ELSE 'good experience' END AS experience
      FROM sf_ticket t JOIN win ON t.final_resolved >= win.w0 AND t.final_resolved < win.w1 JOIN pol p ON p.priority = t.priority
),
sv AS (
    SELECT pop.experience, pop.ticket_id, s.invited_at IS NOT NULL AS invited,
           (s.invited_at IS NOT NULL AND s.score IS NOT NULL AND s.response_at IS NOT NULL) AS responded,
           (s.invited_at IS NOT NULL AND s.score >= 4 AND s.response_at IS NOT NULL) AS positive
      FROM pop LEFT JOIN surveys s ON s.ticket_id = pop.ticket_id
),
grp AS (SELECT * FROM sv UNION ALL SELECT 'ALL', ticket_id, invited, responded, positive FROM sv)
SELECT experience, count(DISTINCT ticket_id)::int AS completions, count(*) FILTER (WHERE invited)::int AS invited,
       round(count(*) FILTER (WHERE invited)::numeric / count(DISTINCT ticket_id), 6) AS invitation_rate,
       count(*) FILTER (WHERE responded)::int AS valid_responses,
       round(count(*) FILTER (WHERE responded)::numeric / nullif(count(*) FILTER (WHERE invited), 0), 6) AS response_rate,
       count(*) FILTER (WHERE positive)::int AS positive,
       round(count(*) FILTER (WHERE positive)::numeric / nullif(count(*) FILTER (WHERE responded), 0), 6) AS csat
  FROM grp GROUP BY experience ORDER BY (experience = 'ALL'), experience;
-- @@ csat_and_its_bounds
-- The reference CSAT is among valid responses only. The two bounds below put every invited non-responder at the lowest and at the
-- highest possible answer; they are the arithmetic limits of what the missing answers could do, NOT estimates (nothing here says how
-- the non-responders would have answered). The width of the gap is the point: it is the room the nonresponse leaves.
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
sv AS (
    SELECT s.*
      FROM surveys s JOIN sf_ticket t ON t.ticket_id = s.ticket_id JOIN win ON t.final_resolved >= win.w0 AND t.final_resolved < win.w1
     WHERE s.invited_at IS NOT NULL
),
c AS (
    SELECT count(*) AS invited, count(*) FILTER (WHERE score IS NOT NULL AND response_at IS NOT NULL) AS responded,
           count(*) FILTER (WHERE score >= 4 AND response_at IS NOT NULL) AS positive FROM sv
)
SELECT 'CSAT among valid responses (the contract figure)' AS reading, positive::int AS positive, responded::int AS denominator,
       round(positive::numeric / responded, 6) AS value FROM c
UNION ALL SELECT 'lower bound: every non-responder not positive', positive::int, invited::int, round(positive::numeric / invited, 6) FROM c
UNION ALL SELECT 'upper bound: every non-responder positive', (positive + invited - responded)::int, invited::int,
       round((positive + invited - responded)::numeric / invited, 6) FROM c;
-- @@ score_distribution_by_queue
-- Valid responses by score and CSAT with the response rate by the ticket's FINAL queue (completions in the window).
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
sv AS (
    SELECT t.final_queue_id AS queue_id, s.score, s.invited_at IS NOT NULL AS invited,
           (s.invited_at IS NOT NULL AND s.score IS NOT NULL AND s.response_at IS NOT NULL) AS responded
      FROM sf_ticket t JOIN win ON t.final_resolved >= win.w0 AND t.final_resolved < win.w1 JOIN surveys s ON s.ticket_id = t.ticket_id
),
grp AS (SELECT * FROM sv UNION ALL SELECT 'ALL', score, invited, responded FROM sv)
SELECT queue_id, count(*) FILTER (WHERE invited)::int AS invited, count(*) FILTER (WHERE responded)::int AS valid_responses,
       round(count(*) FILTER (WHERE responded)::numeric / nullif(count(*) FILTER (WHERE invited), 0), 6) AS response_rate,
       count(*) FILTER (WHERE responded AND score = 1)::int AS score_1, count(*) FILTER (WHERE responded AND score = 2)::int AS score_2,
       count(*) FILTER (WHERE responded AND score = 3)::int AS score_3, count(*) FILTER (WHERE responded AND score = 4)::int AS score_4,
       count(*) FILTER (WHERE responded AND score = 5)::int AS score_5,
       round(count(*) FILTER (WHERE responded AND score >= 4)::numeric / nullif(count(*) FILTER (WHERE responded), 0), 6) AS csat
  FROM grp GROUP BY queue_id ORDER BY (queue_id = 'ALL'), queue_id;
