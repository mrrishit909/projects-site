-- 00_event_views.sql: the views every investigation reads (ServiceFlow, contract v1, D-01..D-09).
-- Re-runnable (CREATE OR REPLACE). Read-only over the base tables; nothing here is a result.
--
--   sf_window    the three analysis windows, half-open [w0, w1): the whole twelve weeks, the training weeks 1-8 and the
--                holdout weeks 9-12 (web/public/data/manifest.json training_weeks; D-08)
--   sf_ev        the canonical event log with its replay order (occurred_at, event_id) as reference_metrics.sql orders it
--   sf_ticket    one row per accepted ticket: the instants the metrics need and the counts of transfers / reopens / pauses
--   sf_interval  one row per service interval: it opens at service_started / resumed (the first of a run of openers) and
--                ends at the next paused / transferred / resolved / abandoned (NULL while still open); the agent is the one
--                named on the opening event
-- Durations are never computed here; each investigation takes epoch seconds and divides by 60 once, at the end.

CREATE OR REPLACE VIEW sf_window AS
SELECT * FROM (VALUES
    ('full',     '2026-07-06T00:00:00Z'::timestamptz, '2026-09-28T00:00:00Z'::timestamptz),
    ('training', '2026-07-06T00:00:00Z'::timestamptz, '2026-08-31T00:00:00Z'::timestamptz),
    ('holdout',  '2026-08-31T00:00:00Z'::timestamptz, '2026-09-28T00:00:00Z'::timestamptz)
) AS w (window_name, w0, w1);

CREATE OR REPLACE VIEW sf_ev AS
SELECT e.ticket_id, e.event_type, e.occurred_at, e.event_id, e.agent_id, e.actor_id, e.queue_id,
       row_number() OVER (PARTITION BY e.ticket_id ORDER BY e.occurred_at, e.event_id) AS seq
  FROM ticket_events e;

CREATE OR REPLACE VIEW sf_ticket AS
WITH agg AS (
    SELECT t.ticket_id,
           min(ev.occurred_at) FILTER (WHERE ev.event_type = 'replied_human' AND left(ev.actor_id, 4) <> 'bot-') AS first_human,
           min(ev.occurred_at) FILTER (WHERE ev.event_type = 'service_started') AS first_start,
           min(ev.occurred_at) FILTER (WHERE ev.event_type = 'abandoned') AS abandoned_at,
           count(*) FILTER (WHERE ev.event_type = 'reopened') AS n_reopened,
           count(*) FILTER (WHERE ev.event_type = 'transferred') AS n_transferred,
           count(*) FILTER (WHERE ev.event_type = 'paused') AS n_paused
      FROM tickets t LEFT JOIN sf_ev ev ON ev.ticket_id = t.ticket_id
     GROUP BY t.ticket_id
),
lastcl AS (   -- the last resolved / reopened by (occurred_at, event_id): a ticket is closed only if the last of the two is a resolve
    SELECT DISTINCT ON (ticket_id) ticket_id, event_type AS last_kind, occurred_at AS last_at
      FROM sf_ev WHERE event_type IN ('resolved', 'reopened')
     ORDER BY ticket_id, occurred_at DESC, event_id DESC
),
firstq AS (
    SELECT DISTINCT ON (ticket_id) ticket_id, queue_id AS first_queue_id
      FROM sf_ev WHERE event_type = 'created' ORDER BY ticket_id, occurred_at, event_id
)
SELECT t.ticket_id, t.customer_id, t.priority, t.channel, t.created_at,
       coalesce(fq.first_queue_id, t.queue_id) AS first_queue_id, t.queue_id AS final_queue_id,
       a.first_human, a.first_start, a.abandoned_at,
       CASE WHEN lc.last_kind = 'resolved' THEN lc.last_at END AS final_resolved,
       a.n_reopened, a.n_transferred, a.n_paused
  FROM tickets t
  JOIN agg a ON a.ticket_id = t.ticket_id
  LEFT JOIN lastcl lc ON lc.ticket_id = t.ticket_id
  LEFT JOIN firstq fq ON fq.ticket_id = t.ticket_id;

CREATE OR REPLACE VIEW sf_interval AS
WITH rows_ AS (
    SELECT ev.*, event_type IN ('service_started', 'resumed') AS is_open,
           event_type IN ('paused', 'transferred', 'resolved', 'abandoned') AS is_close
      FROM sf_ev ev
     WHERE event_type IN ('service_started', 'resumed', 'paused', 'transferred', 'resolved', 'abandoned')
),
marked AS (
    SELECT rows_.*,
           lag(is_open) OVER (PARTITION BY ticket_id ORDER BY seq) AS prev_open,
           min(occurred_at) FILTER (WHERE is_close)
               OVER (PARTITION BY ticket_id ORDER BY seq ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS next_close
      FROM rows_
)
SELECT ticket_id, agent_id, occurred_at AS started_at, next_close AS ended_at
  FROM marked WHERE is_open AND coalesce(NOT prev_open, true);
