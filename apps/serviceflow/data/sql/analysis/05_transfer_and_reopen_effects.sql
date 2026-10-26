-- 05_transfer_and_reopen_effects.sql: what a transfer and a reopen do to resolution time, wait and handling.
-- Decision link: whether routing (transfers) and rework (reopens) explain the long resolution tail, so that a routing change can be
-- weighed against a staffing change (P04-FLOW-04, P04-FLOW-06, P04-TEST-02, P04-TEST-08).
-- Population: tickets whose FINAL resolution is in the whole window [2026-07-06, 2026-09-28) (completions). A reopened ticket is ONE
-- customer contact and ONE completion (its last resolution). Resolution = final resolved minus the ORIGINAL created_at: a transfer
-- never moves the arrival and a reopen charges the dormant gap (the time between a resolution and the next reopen, D-09 R4-09).
-- Wait = first service_started minus created_at (D-09 R4-10). Handling = the sum of the ticket's service intervals (not clipped).
-- Mean = exact sum of seconds / (60 n) rounded half-up once; P90 = nearest rank, index ceil(0.9 n) = (9n + 9) / 10.
-- @@ by_transfer_and_reopen
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
gap AS (   -- dormant time: a reopened event minus the resolved event just before it, per ticket
    SELECT ticket_id, sum(extract(epoch FROM (occurred_at - prev_at))) AS dormant
      FROM (SELECT ticket_id, event_type, occurred_at,
                   lag(event_type) OVER (PARTITION BY ticket_id ORDER BY seq) AS prev_type,
                   lag(occurred_at) OVER (PARTITION BY ticket_id ORDER BY seq) AS prev_at
              FROM sf_ev WHERE event_type IN ('resolved', 'reopened')) x
     WHERE event_type = 'reopened' AND prev_type = 'resolved' GROUP BY ticket_id
),
hd AS (SELECT ticket_id, sum(extract(epoch FROM (ended_at - started_at))) AS secs FROM sf_interval GROUP BY ticket_id),
pop AS (
    SELECT t.ticket_id,
           CASE WHEN t.n_transferred > 0 AND t.n_reopened > 0 THEN 'transferred and reopened'
                WHEN t.n_transferred > 0 THEN 'transferred only'
                WHEN t.n_reopened > 0 THEN 'reopened only'
                ELSE 'neither' END AS grp,
           greatest(0, extract(epoch FROM (t.final_resolved - t.created_at)))::numeric AS rs,
           CASE WHEN t.first_start IS NOT NULL THEN greatest(0, extract(epoch FROM (t.first_start - t.created_at)))::numeric END AS wt,
           coalesce(hd.secs, 0)::numeric AS hs, coalesce(gap.dormant, 0)::numeric AS dormant
      FROM sf_ticket t JOIN win ON t.final_resolved >= win.w0 AND t.final_resolved < win.w1
      LEFT JOIN hd ON hd.ticket_id = t.ticket_id LEFT JOIN gap ON gap.ticket_id = t.ticket_id
),
grp AS (SELECT * FROM pop UNION ALL SELECT ticket_id, 'ALL', rs, wt, hs, dormant FROM pop),
rk AS (SELECT g.*, row_number() OVER (PARTITION BY grp ORDER BY rs, ticket_id) AS rn, count(*) OVER (PARTITION BY grp) AS n FROM grp g)
SELECT grp AS ticket_group, max(n)::int AS completions,
       round(100 * max(n)::numeric / (SELECT count(*) FROM pop), 1) AS share_of_completions_pct,
       round(sum(rs) / (60 * max(n)), 4) AS mean_resolution_min,
       round(max(rs) FILTER (WHERE rn = (9 * n + 9) / 10) / 60, 4) AS p90_resolution_min,
       round(sum(wt) / (60 * nullif(count(wt), 0)), 4) AS mean_wait_to_first_service_min,
       round(sum(hs) / (60 * max(n)), 4) AS mean_handling_min,
       round(sum(dormant) / (60 * max(n)), 4) AS mean_dormant_gap_min
  FROM rk GROUP BY grp
 ORDER BY (grp = 'ALL'), CASE grp WHEN 'neither' THEN 1 WHEN 'transferred only' THEN 2 WHEN 'reopened only' THEN 3 ELSE 4 END;
-- @@ transfer_routes
-- One row per transfer route (the queue the ticket left and the queue it entered). The queue a ticket left is the queue named by the
-- latest created / queued / transferred event before the transfer. Time to transfer = transfer minus created_at; time to the next
-- service = the next service_started or resumed after the transfer minus the transfer (the per-queue wait restarts in the new queue,
-- the arrival does not move). A transfer with no later service has no such time (counted separately).
WITH q AS (
    SELECT ticket_id, event_type, occurred_at, queue_id, seq,
           lag(queue_id) OVER (PARTITION BY ticket_id ORDER BY seq) AS prev_queue
      FROM sf_ev WHERE event_type IN ('created', 'queued', 'transferred') AND queue_id IS NOT NULL
),
tr AS (
    SELECT q.ticket_id, q.occurred_at AS at, q.prev_queue AS from_queue, q.queue_id AS to_queue, t.created_at
      FROM q JOIN tickets t ON t.ticket_id = q.ticket_id WHERE q.event_type = 'transferred'
),
nxt AS (
    SELECT tr.*, (SELECT min(e.occurred_at) FROM sf_ev e WHERE e.ticket_id = tr.ticket_id AND e.event_type IN ('service_started', 'resumed')
                     AND e.occurred_at >= tr.at) AS next_service
      FROM tr
)
SELECT from_queue, to_queue, count(*)::int AS transfers,
       round(avg(extract(epoch FROM (at - created_at)) / 60)::numeric, 4) AS mean_min_arrival_to_transfer,
       count(next_service)::int AS with_a_later_service,
       round(avg(extract(epoch FROM (next_service - at)) / 60)::numeric, 4) AS mean_min_transfer_to_next_service
  FROM nxt GROUP BY from_queue, to_queue ORDER BY from_queue, to_queue;
