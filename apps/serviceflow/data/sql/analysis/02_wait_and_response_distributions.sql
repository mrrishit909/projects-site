-- 02_wait_and_response_distributions.sql: first response, wait to first service and resolution by queue and priority, mean and P90.
-- Decision link: an average hides the tail (P04-TEST-10, P04-DOMAIN-04): every mean is printed beside its nearest-rank P90.
-- Window: the whole twelve weeks [2026-07-06, 2026-09-28). Arrivals are tickets created in the window (first response, wait);
-- completions are tickets whose FINAL resolution is in the window (resolution). Queue = the ticket's FINAL queue (group_by=queue
-- basis of D-09 R4-10: a transferred ticket counts where it ended). Rows 'ALL' are the subtotals.
-- First response = first human reply (an actor with prefix 'bot-' never counts) minus created_at; wait = first service_started
-- minus created_at; resolution = final resolved minus the ORIGINAL created_at (a reopened ticket is charged its dormant gap, D-09 R4-09).
-- Negative differences clamp to 0 (a late-arriving reply). Mean = exact sum of seconds / (60 n) rounded half-up once;
-- P90 = nearest rank, the value at 1-based index ceil(0.9 n) = (9n + 9) / 10 in integers.
-- @@ first_response_and_wait
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
pop AS (
    SELECT t.ticket_id, t.final_queue_id AS queue_id, t.priority,
           CASE WHEN t.first_human IS NOT NULL THEN greatest(0, extract(epoch FROM (t.first_human - t.created_at)))::numeric END AS fr,   -- greatest() ignores NULL: guard it
           CASE WHEN t.first_start IS NOT NULL THEN greatest(0, extract(epoch FROM (t.first_start - t.created_at)))::numeric END AS wt
      FROM sf_ticket t, win WHERE t.created_at >= win.w0 AND t.created_at < win.w1
),
grp AS (
    SELECT queue_id, priority, ticket_id, fr, wt FROM pop
    UNION ALL SELECT queue_id, 'ALL', ticket_id, fr, wt FROM pop
    UNION ALL SELECT 'ALL', priority, ticket_id, fr, wt FROM pop
    UNION ALL SELECT 'ALL', 'ALL', ticket_id, fr, wt FROM pop
),
rk AS (
    SELECT g.*,
           CASE WHEN fr IS NOT NULL THEN row_number() OVER (PARTITION BY queue_id, priority ORDER BY fr, ticket_id) END AS fr_rn,
           count(fr) OVER (PARTITION BY queue_id, priority) AS fr_n,
           CASE WHEN wt IS NOT NULL THEN row_number() OVER (PARTITION BY queue_id, priority ORDER BY wt, ticket_id) END AS wt_rn,
           count(wt) OVER (PARTITION BY queue_id, priority) AS wt_n
      FROM grp g
)
SELECT queue_id, priority, count(*)::int AS arrivals,
       max(fr_n)::int AS with_human_reply,
       round(sum(fr) / (60 * nullif(max(fr_n), 0)), 4) AS mean_first_response_min,
       round(max(fr) FILTER (WHERE fr_rn = (9 * fr_n + 9) / 10) / 60, 4) AS p90_first_response_min,
       max(wt_n)::int AS served,
       round(sum(wt) / (60 * nullif(max(wt_n), 0)), 4) AS mean_wait_min,
       round(max(wt) FILTER (WHERE wt_rn = (9 * wt_n + 9) / 10) / 60, 4) AS p90_wait_min
  FROM rk
 GROUP BY queue_id, priority
 ORDER BY (queue_id = 'ALL'), queue_id, (priority = 'ALL'), priority;
-- @@ resolution_tail
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
pop AS (
    SELECT t.ticket_id, t.final_queue_id AS queue_id, t.priority,
           greatest(0, extract(epoch FROM (t.final_resolved - t.created_at)))::numeric AS rs
      FROM sf_ticket t, win WHERE t.final_resolved >= win.w0 AND t.final_resolved < win.w1
),
grp AS (
    SELECT queue_id, priority, ticket_id, rs FROM pop
    UNION ALL SELECT queue_id, 'ALL', ticket_id, rs FROM pop
    UNION ALL SELECT 'ALL', priority, ticket_id, rs FROM pop
    UNION ALL SELECT 'ALL', 'ALL', ticket_id, rs FROM pop
),
rk AS (
    SELECT g.*, row_number() OVER (PARTITION BY queue_id, priority ORDER BY rs, ticket_id) AS rn,
           count(*) OVER (PARTITION BY queue_id, priority) AS n
      FROM grp g
)
SELECT queue_id, priority, max(n)::int AS completions,
       round(sum(rs) / (60 * max(n)), 4) AS mean_resolution_min,
       round(max(rs) FILTER (WHERE rn = (9 * n + 9) / 10) / 60, 4) AS p90_resolution_min,
       round((max(rs) FILTER (WHERE rn = (9 * n + 9) / 10) / 60) / (sum(rs) / (60 * max(n))), 3) AS p90_over_mean
  FROM rk
 GROUP BY queue_id, priority
 ORDER BY (queue_id = 'ALL'), queue_id, (priority = 'ALL'), priority;
