-- 08_rejections_and_defects_by_reason.sql: what the ingest refused, why, and which injected defects each check finds.
-- Decision link: how much of the published history the metrics could not use, and whether each defect planted in the data
-- (data/injection-manifest.json, INJ-01..INJ-09) is found, so that a number is never trusted because a defect went unseen.
-- rejected_records holds every refused raw row with its reason code (data/seed.py through the domain's validate_batch, as the API does).
-- A rejected TICKET takes its events and surveys with it (reason TICKET_REJECTED, D-05).
-- @@ rejected_by_reason
SELECT entity, reason_code,
       CASE reason_code WHEN 'BOT_AS_HUMAN_REPLY' THEN 'INJ-01' WHEN 'AGENT_NOT_QUALIFIED' THEN 'INJ-03'
                        WHEN 'CONCURRENCY_EXCEEDED' THEN 'INJ-04' WHEN 'TRANSFER_RESETS_ARRIVAL' THEN 'INJ-06'
                        WHEN 'TICKET_REJECTED' THEN 'dependants of INJ-03 / INJ-04 / INJ-06' END AS injected_defect,
       count(*)::int AS rejected_rows, count(DISTINCT id)::int AS distinct_ids,
       (array_agg(id ORDER BY id))[1] || ' .. ' || (array_agg(id ORDER BY id))[count(*)] AS first_and_last_id
  FROM rejected_records GROUP BY entity, reason_code
 ORDER BY entity DESC, reason_code;
-- @@ injected_defects_found
-- One row per injected defect and the SQL check that finds it. INJ-01, 03, 04 and 06 are refused by ingest (found = rows in
-- rejected_records). INJ-02 is not detectable by the domain; the check here is the analyst's: a customer record created at the very
-- instant of its first ticket (the generator's ordinary customers predate the twelve weeks). INJ-05 and INJ-08 read the shifts.
-- INJ-07 is replay-only, so the table has no cold-start run by design. INJ-09 is the unanswered invitations after a poor experience
-- in query 07's definition (a poor experience = a missed target, a transfer or a reopen).
SELECT 'INJ-01' AS injection_id, 'bot acknowledgement typed as a human reply' AS defect,
       'rejected_records BOT_AS_HUMAN_REPLY' AS sql_check, count(*)::int AS found
  FROM rejected_records WHERE reason_code = 'BOT_AS_HUMAN_REPLY'
UNION ALL SELECT 'INJ-02', 'reopen recorded as a new ticket from a new customer',
       'customers whose created_at equals the created_at of their earliest ticket', count(*)::int
  FROM customers c WHERE c.created_at = (SELECT min(t.created_at) FROM tickets t WHERE t.customer_id = c.customer_id)
UNION ALL SELECT 'INJ-03', 'service by an agent without the queue skill', 'rejected_records AGENT_NOT_QUALIFIED', count(*)::int
  FROM rejected_records WHERE reason_code = 'AGENT_NOT_QUALIFIED'
UNION ALL SELECT 'INJ-04', 'two simultaneous services for one agent', 'rejected_records CONCURRENCY_EXCEEDED', count(*)::int
  FROM rejected_records WHERE reason_code = 'CONCURRENCY_EXCEEDED'
UNION ALL SELECT 'INJ-05', 'shift whose break is counted as available time', 'shifts with break_minutes 0 and a recorded break', count(*)::int
  FROM shifts s WHERE s.break_minutes = 0 AND EXISTS (SELECT 1 FROM shift_breaks b WHERE b.shift_id = s.shift_id)
UNION ALL SELECT 'INJ-06', 'transfer that resets the arrival', 'rejected_records TRANSFER_RESETS_ARRIVAL', count(*)::int
  FROM rejected_records WHERE reason_code = 'TRANSFER_RESETS_ARRIVAL'
UNION ALL SELECT 'INJ-07', 'simulation run with its warm-up included (replay-only)', 'simulation_runs rows with warmup_minutes = 0', count(*)::int
  FROM simulation_runs WHERE warmup_minutes = 0
UNION ALL SELECT 'INJ-08', 'shift across the clock change built with naive wall-clock arithmetic',
       'shifts that cross a UTC-offset change of the agent zone and last 480 real minutes (a crossing shift of 8 wall-clock hours is 420)', count(*)::int
  FROM shifts s JOIN agents a ON a.agent_id = s.agent_id
 WHERE (s.ends_at AT TIME ZONE a.timezone) - (s.starts_at AT TIME ZONE a.timezone) <> s.ends_at - s.starts_at
   AND s.ends_at - s.starts_at = interval '480 minutes'
UNION ALL SELECT 'INJ-09', 'survey nonresponse skewed by a poor experience', 'invitations without a valid response after a poor experience (completed tickets)', count(*)::int
  FROM surveys s JOIN sf_ticket t ON t.ticket_id = s.ticket_id JOIN sla_policies p ON p.priority = t.priority
 WHERE s.invited_at IS NOT NULL AND (s.score IS NULL OR s.response_at IS NULL) AND t.final_resolved IS NOT NULL
   AND t.final_resolved >= '2026-07-06T00:00:00Z' AND t.final_resolved < '2026-09-28T00:00:00Z'
   AND ((t.first_human IS NOT NULL AND extract(epoch FROM (t.first_human - t.created_at)) > p.first_response_minutes * 60)
        OR extract(epoch FROM (t.final_resolved - t.created_at)) > p.resolution_minutes * 60
        OR t.n_transferred > 0 OR t.n_reopened > 0)
ORDER BY 1;
-- @@ published_vs_loaded
-- Accepted rows in the tables plus the rows kept in rejected_records (by entity) = the rows of the published entity files.
WITH rej AS (SELECT entity, count(*) AS n FROM rejected_records GROUP BY entity),
tot AS (
    SELECT 'tickets' AS entity, (SELECT count(*) FROM tickets) AS loaded
    UNION ALL SELECT 'ticket_events', (SELECT count(*) FROM ticket_events)
    UNION ALL SELECT 'surveys', (SELECT count(*) FROM surveys)
)
SELECT tot.entity, tot.loaded::int AS loaded_rows, coalesce(rej.n, 0)::int AS rejected_rows, (tot.loaded + coalesce(rej.n, 0))::int AS published_rows
  FROM tot LEFT JOIN rej ON rej.entity = tot.entity ORDER BY tot.entity DESC;
