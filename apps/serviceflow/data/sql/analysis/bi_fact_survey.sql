-- bi_fact_survey.sql: fact_survey of the BI package. Grain: one survey row (at most one per ticket; 2,147 in the snapshot, all invited).
-- Requires 00_event_views.sql. resolved_date_key is the date of the ticket's FINAL resolution (the CSAT population is the tickets
-- completed in the selected dates, D-05); empty when the ticket is not completed.
SELECT s.survey_id, s.ticket_id,
       to_char(t.final_resolved AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS resolved_date_key,
       (s.invited_at IS NOT NULL)::int AS is_invited,
       (s.invited_at IS NOT NULL AND s.score IS NOT NULL AND s.response_at IS NOT NULL)::int AS is_valid_response,
       s.score,
       (s.invited_at IS NOT NULL AND s.score >= 4 AND s.response_at IS NOT NULL)::int AS is_positive
  FROM surveys s JOIN sf_ticket t ON t.ticket_id = s.ticket_id
 ORDER BY s.survey_id;
