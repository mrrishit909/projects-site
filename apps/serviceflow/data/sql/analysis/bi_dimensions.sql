-- bi_dimensions.sql: the small dimensions of the BI package, one result set per block (run_all.py writes each as a CSV).
-- @@ dim_queue
SELECT queue_id, queue_name, priority_policy, calendar_id, active::int AS active FROM queues ORDER BY queue_id;
-- @@ dim_agent
SELECT agent_id, agent_name, timezone, employment_type, active::int AS active, max_concurrent FROM agents ORDER BY agent_id;
-- @@ dim_priority
SELECT priority, first_response_minutes AS sla_first_response_minutes, resolution_minutes AS sla_resolution_minutes, calendar_id
  FROM sla_policies ORDER BY priority;
-- @@ dim_channel
SELECT channel, (channel IN ('chat', 'phone'))::int AS can_abandon
  FROM (SELECT DISTINCT channel FROM tickets) c ORDER BY channel;
-- @@ dim_date
-- One row per UTC calendar day of the twelve weeks (84): weeks 1-8 are the training period, 9-12 the holdout period (D-08).
SELECT to_char(d, 'YYYYMMDD')::int AS date_key, to_char(d, 'YYYY-MM-DD') AS date,
       extract(isodow FROM d)::int AS iso_weekday, to_char(d, 'Dy') AS weekday_name,
       ((d - date '2026-07-06') / 7 + 1) AS week_number,
       CASE WHEN d < date '2026-08-31' THEN 'training' ELSE 'holdout' END AS period,
       (extract(isodow FROM d) >= 6)::int AS is_weekend
  FROM (SELECT g::date AS d FROM generate_series(date '2026-07-06', date '2026-09-27', interval '1 day') g) days ORDER BY 1;
