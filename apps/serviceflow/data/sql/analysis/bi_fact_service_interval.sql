-- bi_fact_service_interval.sql: fact_service_interval of the BI package. Grain: one service interval (opens at service_started /
-- resumed, ends at the next paused / transferred / resolved / abandoned). 4,976 rows in the snapshot, none open. Requires 00_event_views.sql.
SELECT 'iv-' || lpad(row_number() OVER (ORDER BY i.started_at, i.ticket_id, i.agent_id)::text, 5, '0') AS interval_id,
       i.ticket_id, i.agent_id,
       to_char(i.started_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS start_date_key,
       to_char(i.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at,
       to_char(i.ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS ended_at,
       extract(epoch FROM (i.ended_at - i.started_at))::int AS handling_seconds
  FROM sf_interval i
 ORDER BY 1;
