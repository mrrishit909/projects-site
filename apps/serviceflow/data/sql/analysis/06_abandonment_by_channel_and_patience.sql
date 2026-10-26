-- 06_abandonment_by_channel_and_patience.sql: who abandons, where, and how long they waited first.
-- Decision link: how much waiting the live channels tolerate before the customer leaves (P04-MET-10), so that a queue-wait target for
-- chat and phone can be set from evidence rather than from the mean wait.
-- Population: tickets created in the whole window [2026-07-06, 2026-09-28). The abandonment RATE exists only on the channels that can
-- abandon (chat, phone: the inputs' abandonable_channels, D-05); email and web_form tickets are reported but have no rate (NULL), never 0.
-- An abandonment is a ticket with an 'abandoned' event. Patience = created_at to the abandoned event; the time at risk of a ticket is
-- created_at to the EARLIER of its first service_started and its abandonment (tickets still waiting at the end of the data have none here).
-- @@ abandonment_by_channel
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
pop AS (
    SELECT t.ticket_id, t.channel, t.priority, t.abandoned_at, t.first_start, t.n_transferred,
           (t.channel IN ('chat', 'phone')) AS can_abandon,
           extract(epoch FROM (t.abandoned_at - t.created_at))::numeric AS patience,
           (t.abandoned_at IS NOT NULL AND (t.first_start IS NULL OR t.abandoned_at < t.first_start)) AS gone_before_service
      FROM sf_ticket t, win WHERE t.created_at >= win.w0 AND t.created_at < win.w1
),
grp AS (SELECT channel, ticket_id, can_abandon, abandoned_at, gone_before_service, patience, n_transferred FROM pop
        UNION ALL SELECT 'ALL abandonable', ticket_id, can_abandon, abandoned_at, gone_before_service, patience, n_transferred FROM pop WHERE can_abandon),
rk AS (
    SELECT g.*, CASE WHEN abandoned_at IS NOT NULL THEN row_number() OVER (PARTITION BY channel ORDER BY patience, ticket_id) END AS rn,
           count(abandoned_at) OVER (PARTITION BY channel) AS na
      FROM grp g
)
SELECT channel, bool_or(can_abandon) AS can_abandon, count(*)::int AS arrivals, count(abandoned_at)::int AS abandoned,
       round(count(abandoned_at)::numeric / nullif(count(*) FILTER (WHERE can_abandon), 0), 6) AS abandonment_rate,
       count(*) FILTER (WHERE gone_before_service)::int AS abandoned_before_first_service,
       (count(abandoned_at) - count(*) FILTER (WHERE gone_before_service))::int AS abandoned_after_service_began,
       count(*) FILTER (WHERE abandoned_at IS NOT NULL AND NOT gone_before_service AND n_transferred > 0)::int AS of_which_transferred,
       round(sum(patience) / (60 * nullif(count(abandoned_at), 0)), 4) AS mean_patience_min,
       round(max(patience) FILTER (WHERE rn = (9 * na + 9) / 10) / 60, 4) AS p90_patience_min
  FROM rk GROUP BY channel
 ORDER BY (channel = 'ALL abandonable'), channel;
-- @@ abandonment_hazard_by_wait
-- A discrete hazard: for each channel that can abandon and each band of time spent waiting, the tickets still waiting at the start of
-- the band (at risk), how many left inside the band, how many were taken into service inside it, and abandoned / at risk. The bands
-- are [0,5) [5,10) [10,20) [20,40) [40,80) [80,inf) minutes. A ticket that is never served nor abandoned has no time at risk.
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
bands AS (SELECT * FROM (VALUES (1, 0, 5), (2, 5, 10), (3, 10, 20), (4, 20, 40), (5, 40, 80), (6, 80, 100000)) b (band, lo, hi)),
pop AS (
    SELECT t.ticket_id, t.channel,
           extract(epoch FROM (least(coalesce(t.abandoned_at, 'infinity'), coalesce(t.first_start, 'infinity')) - t.created_at)) / 60 AS at_risk_min,
           (t.abandoned_at IS NOT NULL AND (t.first_start IS NULL OR t.abandoned_at < t.first_start)) AS left_queue
      FROM sf_ticket t, win
     WHERE t.created_at >= win.w0 AND t.created_at < win.w1 AND t.channel IN ('chat', 'phone')
       AND (t.abandoned_at IS NOT NULL OR t.first_start IS NOT NULL)
)
SELECT p.channel, b.lo || '-' || (CASE WHEN b.hi >= 100000 THEN 'more' ELSE b.hi::text END) AS wait_band_min,
       count(*) FILTER (WHERE p.at_risk_min >= b.lo)::int AS at_risk,
       count(*) FILTER (WHERE p.left_queue AND p.at_risk_min >= b.lo AND p.at_risk_min < b.hi)::int AS abandoned_in_band,
       count(*) FILTER (WHERE NOT p.left_queue AND p.at_risk_min >= b.lo AND p.at_risk_min < b.hi)::int AS served_in_band,
       round(count(*) FILTER (WHERE p.left_queue AND p.at_risk_min >= b.lo AND p.at_risk_min < b.hi)::numeric
             / nullif(count(*) FILTER (WHERE p.at_risk_min >= b.lo), 0), 6) AS abandonment_hazard
  FROM pop p CROSS JOIN bands b GROUP BY p.channel, b.band, b.lo, b.hi ORDER BY p.channel, b.band;
