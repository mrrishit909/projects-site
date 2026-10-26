-- Independent SQL recomputation of the ServiceFlow metrics (P04-GOLD-01, contract D-02, D-03, D-05).
-- Shares no code with the Python domain: it replays the event log with window functions.
--
-- Parameters (psycopg named style):  %(w0)s, %(w1)s  the half-open window [w0, w1)
--                                    %(cutoffs)s      timestamptz[] backlog instants
--                                    %(abandonable)s  text[] channels that can abandon
-- One output row; every column is a key of expected.json "metrics". Durations: text with 4 decimals in minutes,
-- rates: text with 6 decimals, counts: integers, maps: jsonb. There is no percent sign in this file (psycopg params).
--
-- Rules replayed here
--   first response  = first replied_human whose actor is not a bot (actor prefix 'bot-'), minus created_at
--   wait            = first service_started minus created_at
--   final resolve   = last 'resolved' that is not followed by a later 'reopened' (a reopen reopens the ticket)
--   resolution      = final resolve minus the ORIGINAL created_at
--   handling        = service intervals clipped to the window; an interval opens at service_started / resumed (the
--                     first of a run of openers) and ends at the next paused / transferred / resolved / abandoned
--   P90             = nearest rank: the value at 1-based index ceil(0.9 n) of the ascending list, ceil(9n/10) in integers
--   staffed         = shift overlap with the window, break deducted only when the window covers the whole shift
--   exact means     = SUM(seconds) / (60 * n) in numeric, rounded half-up once at the end
WITH params AS (
    SELECT %(w0)s::timestamptz AS w0, %(w1)s::timestamptz AS w1,
           extract(epoch FROM (%(w1)s::timestamptz - %(w0)s::timestamptz)) / 3600 AS hours
),
-- ordered event log with the type classes
ev AS (
    SELECT e.ticket_id, e.event_type, e.occurred_at, e.event_id, e.agent_id, e.actor_id,
           row_number() OVER (PARTITION BY e.ticket_id ORDER BY e.occurred_at, e.event_id) AS seq
      FROM ticket_events e
),
-- one row per ticket: the instants the metrics need
tk AS (
    SELECT t.ticket_id, t.priority, t.channel, t.created_at,
           min(ev.occurred_at) FILTER (WHERE ev.event_type = 'replied_human' AND left(ev.actor_id, 4) <> 'bot-') AS first_human,
           min(ev.occurred_at) FILTER (WHERE ev.event_type = 'service_started') AS first_start,
           max(ev.occurred_at) FILTER (WHERE ev.event_type = 'resolved') AS last_resolved,
           max(ev.occurred_at) FILTER (WHERE ev.event_type = 'reopened') AS last_reopened,
           bool_or(ev.event_type = 'abandoned') AS abandoned
      FROM tickets t LEFT JOIN ev ON ev.ticket_id = t.ticket_id
     GROUP BY t.ticket_id, t.priority, t.channel, t.created_at
),
tf AS (
    SELECT tk.*,
           CASE WHEN last_resolved IS NOT NULL AND (last_reopened IS NULL OR last_resolved > last_reopened)
                THEN last_resolved END AS final_resolved
      FROM tk
),
-- service intervals: only opener / closer rows, an opener preceded by an opener belongs to the same run
iv_rows AS (
    SELECT ev.*, event_type IN ('service_started', 'resumed') AS is_open,
           event_type IN ('paused', 'transferred', 'resolved', 'abandoned') AS is_close
      FROM ev WHERE event_type IN ('service_started', 'resumed', 'paused', 'transferred', 'resolved', 'abandoned')
),
iv_marked AS (
    SELECT iv_rows.*,
           lag(is_open) OVER (PARTITION BY ticket_id ORDER BY seq) AS prev_open,
           min(occurred_at) FILTER (WHERE is_close)
               OVER (PARTITION BY ticket_id ORDER BY seq ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS next_close
      FROM iv_rows
),
iv AS (
    SELECT ticket_id, occurred_at AS s, next_close AS e FROM iv_marked WHERE is_open AND coalesce(NOT prev_open, true)
),
handling AS (
    SELECT coalesce(sum(greatest(0, extract(epoch FROM (least(coalesce(iv.e, p.w1), p.w1) - greatest(iv.s, p.w0))))), 0) AS secs
      FROM iv, params p
),
arr AS (SELECT tf.* FROM tf, params p WHERE tf.created_at >= p.w0 AND tf.created_at < p.w1),
cmp AS (SELECT tf.* FROM tf, params p WHERE tf.final_resolved >= p.w0 AND tf.final_resolved < p.w1),
-- per-ticket durations in exact seconds
fr AS (
    SELECT a.ticket_id, a.priority, greatest(0, extract(epoch FROM (a.first_human - a.created_at)))::numeric AS secs,
           row_number() OVER (ORDER BY greatest(0, extract(epoch FROM (a.first_human - a.created_at))), a.ticket_id) AS rn
      FROM arr a WHERE a.first_human IS NOT NULL
),
fr_n AS (SELECT count(*) AS n FROM fr),
wt AS (
    SELECT a.ticket_id, greatest(0, extract(epoch FROM (a.first_start - a.created_at)))::numeric AS secs
      FROM arr a WHERE a.first_start IS NOT NULL
),
rs AS (
    SELECT c.ticket_id, c.priority, greatest(0, extract(epoch FROM (c.final_resolved - c.created_at)))::numeric AS secs
      FROM cmp c
),
-- state at each cutoff: arrived, and the latest of resolved / reopened / abandoned up to the cutoff is not a closure
bl AS (
    SELECT cut AS c,
           count(*) FILTER (
               WHERE t.ticket_id IS NOT NULL AND t.created_at <= cut
                 AND coalesce((SELECT x.event_type IN ('resolved', 'abandoned') FROM ticket_events x
                                WHERE x.ticket_id = t.ticket_id AND x.occurred_at <= cut
                                  AND x.event_type IN ('resolved', 'reopened', 'abandoned')
                                ORDER BY x.occurred_at DESC, x.event_id DESC LIMIT 1), false) = false) AS n
      FROM unnest(%(cutoffs)s::timestamptz[]) AS cut LEFT JOIN tickets t ON true
     GROUP BY cut
),
overdue AS (
    SELECT count(*) AS n
      FROM tf JOIN sla_policies sp ON sp.priority = tf.priority, params p
     WHERE tf.created_at <= p.w1
       AND coalesce((SELECT x.event_type IN ('resolved', 'abandoned') FROM ticket_events x
                      WHERE x.ticket_id = tf.ticket_id AND x.occurred_at <= p.w1
                        AND x.event_type IN ('resolved', 'reopened', 'abandoned')
                      ORDER BY x.occurred_at DESC, x.event_id DESC LIMIT 1), false) = false
       AND extract(epoch FROM (p.w1 - tf.created_at)) > sp.resolution_minutes * 60
),
sla AS (
    SELECT (SELECT count(*) FROM fr JOIN sla_policies sp ON sp.priority = fr.priority) AS fr_elig,
           (SELECT count(*) FROM fr JOIN sla_policies sp ON sp.priority = fr.priority
             WHERE fr.secs <= sp.first_response_minutes * 60) AS fr_ok,
           (SELECT count(*) FROM rs JOIN sla_policies sp ON sp.priority = rs.priority) AS rs_elig,
           (SELECT count(*) FROM rs JOIN sla_policies sp ON sp.priority = rs.priority
             WHERE rs.secs <= sp.resolution_minutes * 60) AS rs_ok
),
staff AS (
    SELECT coalesce(sum(extract(epoch FROM (least(s.ends_at, p.w1) - greatest(s.starts_at, p.w0))) / 60
                        - CASE WHEN s.starts_at >= p.w0 AND s.ends_at <= p.w1 THEN s.break_minutes ELSE 0 END), 0) AS avail_min,
           (SELECT coalesce(sum(extract(epoch FROM (ends_at - starts_at)) / 60 - break_minutes), 0) FROM shifts) AS whole_min
      FROM params p LEFT JOIN shifts s ON least(s.ends_at, p.w1) > greatest(s.starts_at, p.w0)
),
ab AS (
    SELECT count(*) AS n, count(*) FILTER (WHERE abandoned) AS gone
      FROM arr WHERE channel = ANY (%(abandonable)s::text[])
),
sv AS (
    SELECT count(*) FILTER (WHERE s.invited_at IS NOT NULL) AS invited,
           count(*) FILTER (WHERE s.invited_at IS NOT NULL AND s.score IS NOT NULL AND s.response_at IS NOT NULL) AS responded,
           count(*) FILTER (WHERE s.invited_at IS NOT NULL AND s.score >= 4 AND s.response_at IS NOT NULL) AS positive
      FROM surveys s JOIN cmp ON cmp.ticket_id = s.ticket_id
)
SELECT
    (SELECT count(*) FROM arr)::int AS arrival_count,
    (SELECT count(*) FROM cmp)::int AS completion_count,
    round((SELECT count(*) FROM arr)::numeric / p.hours::numeric, 6)::text AS arrival_rate_per_hour,
    round((SELECT count(*) FROM cmp)::numeric / p.hours::numeric, 6)::text AS completion_rate_per_hour,
    coalesce((SELECT jsonb_object_agg(to_char(bl.c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), bl.n) FROM bl), '{}'::jsonb) AS backlog,
    coalesce((SELECT jsonb_object_agg(fr.ticket_id, round(fr.secs / 60, 4)::text) FROM fr), '{}'::jsonb) AS first_response_minutes,
    (SELECT round(sum(secs) / (60 * count(*)), 4)::text FROM fr) AS mean_first_response_minutes,
    (SELECT round(fr.secs / 60, 4)::text FROM fr, fr_n WHERE fr.rn = (9 * fr_n.n + 9) / 10) AS p90_first_response_minutes,
    coalesce((SELECT jsonb_object_agg(wt.ticket_id, round(wt.secs / 60, 4)::text) FROM wt), '{}'::jsonb) AS wait_minutes,
    (SELECT round(sum(secs) / (60 * count(*)), 4)::text FROM wt) AS mean_wait_minutes,
    coalesce((SELECT jsonb_object_agg(rs.ticket_id, round(rs.secs / 60, 4)::text) FROM rs), '{}'::jsonb) AS resolution_minutes,
    (SELECT round(sum(secs) / (60 * count(*)), 4)::text FROM rs) AS mean_resolution_minutes,
    round(h.secs::numeric / 60, 4)::text AS handling_minutes_total,
    (SELECT round(fr_ok::numeric / nullif(fr_elig, 0), 6)::text FROM sla) AS sla_first_response_compliance,
    (SELECT fr_ok FROM sla)::int AS sla_first_response_within,
    (SELECT fr_elig FROM sla)::int AS sla_first_response_eligible,
    (SELECT round(rs_ok::numeric / nullif(rs_elig, 0), 6)::text FROM sla) AS sla_resolution_compliance,
    (SELECT rs_ok FROM sla)::int AS sla_resolution_within,
    (SELECT rs_elig FROM sla)::int AS sla_resolution_eligible,
    (SELECT n FROM overdue)::int AS open_overdue_at_cutoff,
    round(st.avail_min::numeric, 4)::text AS staffed_available_minutes,
    round(st.whole_min::numeric, 4)::text AS staffed_shift_minutes_whole,
    round((h.secs::numeric / 60) / nullif(st.avail_min::numeric, 0), 6)::text AS agent_occupancy,
    (SELECT round(gone::numeric / nullif(n, 0), 6)::text FROM ab) AS abandonment_rate,
    (SELECT round(positive::numeric / nullif(responded, 0), 6)::text FROM sv) AS csat,
    (SELECT round(invited::numeric / nullif((SELECT count(*) FROM cmp), 0), 6)::text FROM sv) AS survey_invitation_rate,
    (SELECT round(responded::numeric / nullif(invited, 0), 6)::text FROM sv) AS survey_response_rate,
    NOT EXISTS (SELECT 1 FROM tickets) AS empty_population
  FROM params p, handling h, staff st;
