-- 03_sla_compliance_and_open_overdue.sql: SLA compliance per priority and window, and the open overdue tickets kept apart.
-- Decision link: which priority or window misses its target, and what the compliance rate leaves out (P04-MET-08, P04-TEST-06).
-- Targets (sla_policies, wall clock, the 24x7 calendar cal-001; D-07): P1 15 / 240, P2 60 / 1440, P3 240 / 4320 minutes.
-- Compliance = eligible tickets within target / eligible tickets. First-response eligibility = arrivals in the window with a human
-- reply; resolution eligibility = tickets whose final resolution is in the window, measured from the ORIGINAL arrival (a reopened
-- ticket is charged its dormant gap, D-09 R4-09). Open overdue tickets are NEVER in either denominator; they are counted apart.
-- Windows are half-open: full = weeks 1-12, training = weeks 1-8, holdout = weeks 9-12 (the holdout arrives about 20 % harder).
-- @@ compliance_by_priority_and_window
WITH pol AS (SELECT priority, first_response_minutes AS fr_t, resolution_minutes AS rs_t FROM sla_policies),
base AS (
    SELECT w.window_name, w.w0, w.w1, t.ticket_id, t.priority, t.created_at, t.first_human, t.final_resolved, t.n_reopened,
           p.fr_t, p.rs_t
      FROM sf_window w CROSS JOIN sf_ticket t JOIN pol p ON p.priority = t.priority
),
per AS (
    SELECT window_name, priority,
           count(*) FILTER (WHERE created_at >= w0 AND created_at < w1) AS arrivals,
           count(*) FILTER (WHERE created_at >= w0 AND created_at < w1 AND first_human IS NOT NULL) AS fr_eligible,
           count(*) FILTER (WHERE created_at >= w0 AND created_at < w1 AND first_human IS NOT NULL
                              AND extract(epoch FROM (first_human - created_at)) <= fr_t * 60) AS fr_within,
           count(*) FILTER (WHERE final_resolved >= w0 AND final_resolved < w1) AS rs_eligible,
           count(*) FILTER (WHERE final_resolved >= w0 AND final_resolved < w1
                              AND extract(epoch FROM (final_resolved - created_at)) <= rs_t * 60) AS rs_within,
           count(*) FILTER (WHERE final_resolved >= w0 AND final_resolved < w1
                              AND extract(epoch FROM (final_resolved - created_at)) > rs_t * 60 AND n_reopened > 0) AS rs_missed_reopened
      FROM base GROUP BY window_name, priority
),
allp AS (
    SELECT window_name, 'ALL'::text AS priority, sum(arrivals) AS arrivals, sum(fr_eligible) AS fr_eligible, sum(fr_within) AS fr_within,
           sum(rs_eligible) AS rs_eligible, sum(rs_within) AS rs_within, sum(rs_missed_reopened) AS rs_missed_reopened
      FROM per GROUP BY window_name
)
SELECT window_name, priority, arrivals::int, fr_within::int AS first_response_within, fr_eligible::int AS first_response_eligible,
       round(fr_within::numeric / nullif(fr_eligible, 0), 6) AS first_response_compliance,
       (arrivals - fr_eligible)::int AS arrivals_without_human_reply,
       round(fr_within::numeric / nullif(arrivals, 0), 6) AS if_no_reply_counted_as_miss,
       rs_within::int AS resolution_within, rs_eligible::int AS resolution_eligible,
       round(rs_within::numeric / nullif(rs_eligible, 0), 6) AS resolution_compliance,
       (rs_eligible - rs_within)::int AS resolution_misses, rs_missed_reopened::int AS misses_that_were_reopened
  FROM (SELECT * FROM per UNION ALL SELECT * FROM allp) u
 ORDER BY CASE window_name WHEN 'full' THEN 1 WHEN 'training' THEN 2 ELSE 3 END, (priority = 'ALL'), priority;
-- @@ compliance_by_queue_and_priority
-- Where the misses are: the whole window, by the ticket's FINAL queue and priority (priority 'ALL' is the queue subtotal). Same
-- eligibility as the first block: first-response eligible = arrivals with a human reply; resolution eligible = completions in the window.
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
pol AS (SELECT priority, first_response_minutes AS fr_t, resolution_minutes AS rs_t FROM sla_policies),
base AS (
    SELECT t.final_queue_id AS queue_id, t.priority,
           (t.created_at >= w.w0 AND t.created_at < w.w1 AND t.first_human IS NOT NULL) AS fr_elig,
           (t.created_at >= w.w0 AND t.created_at < w.w1 AND t.first_human IS NOT NULL
              AND extract(epoch FROM (t.first_human - t.created_at)) <= p.fr_t * 60) AS fr_ok,
           (t.final_resolved >= w.w0 AND t.final_resolved < w.w1) AS rs_elig,
           (t.final_resolved >= w.w0 AND t.final_resolved < w.w1 AND extract(epoch FROM (t.final_resolved - t.created_at)) <= p.rs_t * 60) AS rs_ok
      FROM sf_ticket t CROSS JOIN win w JOIN pol p ON p.priority = t.priority
),
grp AS (SELECT queue_id, priority, fr_elig, fr_ok, rs_elig, rs_ok FROM base
        UNION ALL SELECT queue_id, 'ALL', fr_elig, fr_ok, rs_elig, rs_ok FROM base)
SELECT queue_id, priority,
       count(*) FILTER (WHERE fr_ok)::int AS first_response_within, count(*) FILTER (WHERE fr_elig)::int AS first_response_eligible,
       round(count(*) FILTER (WHERE fr_ok)::numeric / nullif(count(*) FILTER (WHERE fr_elig), 0), 6) AS first_response_compliance,
       count(*) FILTER (WHERE rs_ok)::int AS resolution_within, count(*) FILTER (WHERE rs_elig)::int AS resolution_eligible,
       round(count(*) FILTER (WHERE rs_ok)::numeric / nullif(count(*) FILTER (WHERE rs_elig), 0), 6) AS resolution_compliance
  FROM grp GROUP BY queue_id, priority ORDER BY queue_id, (priority = 'ALL'), priority;
-- @@ open_overdue_at_monday_cutoffs
-- Backlog and open overdue at 10:30 UTC on each of the twelve Mondays (the capacity bind). Open = arrived by the cutoff and not
-- closed: the latest of resolved / reopened / abandoned up to the cutoff, by (occurred_at, event_id), is not a resolve or an
-- abandonment (a ticket in service is open). Overdue = open and older than its resolution target.
WITH cut AS (SELECT n + 1 AS week, ('2026-07-06T10:30:00Z'::timestamptz + n * interval '7 days') AS c FROM generate_series(0, 11) n),
st AS (
    SELECT cut.week, cut.c, t.ticket_id, t.priority, t.created_at,
           coalesce((SELECT x.event_type IN ('resolved', 'abandoned') FROM ticket_events x
                      WHERE x.ticket_id = t.ticket_id AND x.occurred_at <= cut.c
                        AND x.event_type IN ('resolved', 'reopened', 'abandoned')
                      ORDER BY x.occurred_at DESC, x.event_id DESC LIMIT 1), false) AS closed
      FROM cut JOIN sf_ticket t ON t.created_at <= cut.c
)
SELECT week, to_char(c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_utc,
       count(*) FILTER (WHERE NOT closed)::int AS backlog,
       count(*) FILTER (WHERE NOT closed AND extract(epoch FROM (c - created_at)) > sp.resolution_minutes * 60)::int AS open_overdue
  FROM st JOIN sla_policies sp ON sp.priority = st.priority
 GROUP BY week, c ORDER BY week;
-- @@ overdue_exposure_by_priority
-- What a point-in-time count misses: sample the open-overdue state every hour on the hour across the twelve weeks (2,016 cutoffs).
-- Only tickets that could ever be open and overdue are examined: those whose last closure came after created_at + target, or that
-- never closed, or whose latest state change is a reopen.
-- tickets_open_overdue_at_a_sample = distinct tickets seen open and overdue at least once; hours_with_any = sampled hours in which
-- at least one was; peak = the largest number open and overdue at one sampled hour. Priority 'ALL' counts across priorities.
WITH cand AS (
    SELECT t.ticket_id, t.priority, t.created_at, sp.resolution_minutes
      FROM sf_ticket t JOIN sla_policies sp ON sp.priority = t.priority
      LEFT JOIN LATERAL (SELECT max(occurred_at) FILTER (WHERE event_type IN ('resolved', 'abandoned')) AS last_close,
                                (array_agg(event_type ORDER BY occurred_at DESC, event_id DESC))[1] AS last_kind
                           FROM ticket_events x
                          WHERE x.ticket_id = t.ticket_id AND x.event_type IN ('resolved', 'reopened', 'abandoned')) lc ON true
     WHERE lc.last_close IS NULL OR lc.last_kind = 'reopened'
        OR extract(epoch FROM (lc.last_close - t.created_at)) > sp.resolution_minutes * 60
),
cut AS (SELECT g AS c FROM generate_series('2026-07-06T00:00:00Z'::timestamptz, '2026-09-27T23:00:00Z'::timestamptz, interval '1 hour') g),
st AS (
    SELECT cut.c, cand.ticket_id, cand.priority
      FROM cut JOIN cand ON cand.created_at <= cut.c
     WHERE extract(epoch FROM (cut.c - cand.created_at)) > cand.resolution_minutes * 60
       AND NOT coalesce((SELECT x.event_type IN ('resolved', 'abandoned') FROM ticket_events x
                          WHERE x.ticket_id = cand.ticket_id AND x.occurred_at <= cut.c
                            AND x.event_type IN ('resolved', 'reopened', 'abandoned')
                          ORDER BY x.occurred_at DESC, x.event_id DESC LIMIT 1), false)
),
per_hour AS (
    SELECT priority, c, count(*) AS n FROM st GROUP BY priority, c
    UNION ALL SELECT 'ALL', c, count(*) FROM st GROUP BY c
),
tk AS (
    SELECT priority, count(DISTINCT ticket_id) AS tickets FROM st GROUP BY priority
    UNION ALL SELECT 'ALL', count(DISTINCT ticket_id) FROM st
),
pri AS (SELECT unnest(ARRAY['P1', 'P2', 'P3', 'ALL']) AS priority)
SELECT p.priority,
       (SELECT count(*) FROM cand c2 WHERE p.priority = 'ALL' OR c2.priority = p.priority)::int AS could_be_overdue,
       coalesce((SELECT tickets FROM tk WHERE tk.priority = p.priority), 0)::int AS tickets_open_overdue_at_a_sample,
       (SELECT count(*) FROM per_hour h WHERE h.priority = p.priority)::int AS hours_with_any,
       coalesce((SELECT max(n) FROM per_hour h WHERE h.priority = p.priority), 0)::int AS peak_open_overdue_at_one_hour
  FROM pri p ORDER BY (p.priority = 'ALL'), p.priority;
