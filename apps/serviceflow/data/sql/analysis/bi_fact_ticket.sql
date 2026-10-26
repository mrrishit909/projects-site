-- bi_fact_ticket.sql: fact_ticket of the BI package (docs/bi-package.md). Grain: one row per ACCEPTED ticket (the ticket of the table
-- `tickets`; a rejected ticket is not here, see 08). Requires 00_event_views.sql. Timestamps are UTC ISO text with a Z; durations are
-- integer seconds (the measures divide by 60 once). Flags are 1 / 0, or empty when the question does not apply (no human reply, not
-- completed). Two date keys (yyyymmdd, UTC) make dim_date a role-playing dimension: created (the arrival) and resolved (the completion).
SELECT t.ticket_id,
       t.customer_id,
       to_char(t.created_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS created_date_key,
       extract(hour FROM t.created_at AT TIME ZONE 'UTC')::int AS created_hour_utc,
       to_char(t.final_resolved AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS resolved_date_key,
       t.first_queue_id,
       t.final_queue_id,
       t.priority,
       t.channel,
       (t.channel IN ('chat', 'phone'))::int AS can_abandon,
       to_char(t.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at,
       to_char(t.first_human AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS first_human_reply_at,
       to_char(t.first_start AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS first_service_at,
       to_char(t.final_resolved AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS final_resolved_at,
       to_char(t.abandoned_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS abandoned_at,
       CASE WHEN t.first_human IS NOT NULL THEN greatest(0, extract(epoch FROM (t.first_human - t.created_at)))::int END AS first_response_seconds,
       CASE WHEN t.first_start IS NOT NULL THEN greatest(0, extract(epoch FROM (t.first_start - t.created_at)))::int END AS wait_seconds,
       CASE WHEN t.final_resolved IS NOT NULL THEN greatest(0, extract(epoch FROM (t.final_resolved - t.created_at)))::int END AS resolution_seconds,
       coalesce((SELECT sum(extract(epoch FROM (i.ended_at - i.started_at))) FROM sf_interval i WHERE i.ticket_id = t.ticket_id), 0)::int AS handling_seconds,
       t.n_reopened AS reopen_count,
       t.n_transferred AS transfer_count,
       t.n_paused AS pause_count,
       p.first_response_minutes AS sla_first_response_minutes,
       p.resolution_minutes AS sla_resolution_minutes,
       CASE WHEN t.first_human IS NOT NULL
            THEN (extract(epoch FROM (t.first_human - t.created_at)) <= p.first_response_minutes * 60)::int END AS met_first_response,
       CASE WHEN t.final_resolved IS NOT NULL
            THEN (extract(epoch FROM (t.final_resolved - t.created_at)) <= p.resolution_minutes * 60)::int END AS met_resolution,
       (t.final_resolved IS NOT NULL)::int AS is_completed,
       (t.abandoned_at IS NOT NULL)::int AS is_abandoned
  FROM sf_ticket t JOIN sla_policies p ON p.priority = t.priority
 ORDER BY t.ticket_id;
