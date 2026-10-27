-- 08_identity_attribution_and_late_events.sql: how identity links attribute anonymous events (forward only) and how late events reach a run (P06-ART-04, D-01, P06-FLOW-02, P06-TEST-06, P06-TEST-07).
-- Question: how many anonymous events does a link attribute, which ones must stay anonymous, and how much would a run have changed if the events that arrived after it had been there?
-- Needs 00_canonical_events.sql (ps_ev at every cutoff, ps_signup). IDENTITY: the EARLIEST link of an anonymous id fixes its user; it attributes an event only when event_at >= linked_at, so
-- an earlier visit stays anonymous and is never re-attributed backward (INJ-07, P06-TEST-07). LATE: an event is late for a run when it happened by the run's cutoff and was received after
-- it (event_at <= C < received_at); a run at C never sees it, and the published result is never rewritten (a later run includes it as a disclosed revision, P06-TEST-06).
-- HINDSIGHT in the last block is the as-of log restricted to events that happened by C, the same rules otherwise: the difference between a run and its hindsight is the late events' effect.

-- @@ attribution_by_event
-- Analysed events with no user id (the anonymous ones) at the as-of, by event name and what the link state did to them.
WITH anon AS (
    SELECT e.name, e.at, e.anonymous_id, e.u, fl.linked_at
    FROM ps_ev e LEFT JOIN (SELECT DISTINCT ON (anonymous_id) anonymous_id, linked_at FROM identity_links ORDER BY anonymous_id, linked_at, identity_link_id) fl ON fl.anonymous_id = e.anonymous_id
    WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.user_id IS NULL
)
SELECT coalesce(name, 'ALL') AS event_name, count(*) AS anonymous_events,
       count(*) FILTER (WHERE linked_at IS NOT NULL AND at >= linked_at) AS attributed_by_link,
       count(*) FILTER (WHERE linked_at IS NOT NULL AND at < linked_at) AS before_the_link_stays_anonymous,
       count(*) FILTER (WHERE linked_at IS NULL) AS no_link_stays_anonymous,
       count(*) FILTER (WHERE u IS NULL) AS remain_anonymous
FROM anon GROUP BY ROLLUP (name) ORDER BY name COLLATE "C" NULLS LAST;

-- @@ links_by_timing
-- Links by when the user's signup happened relative to the link: a link made at or after the signup attributes the visitor's later events; the events before it stay anonymous.
-- Per anonymous id with a link: its anonymous analysed events before and at/after the link, summarised by how many anonymous ids have each pattern.
WITH links AS (SELECT DISTINCT ON (anonymous_id) anonymous_id, user_id, linked_at FROM identity_links ORDER BY anonymous_id, linked_at, identity_link_id),
per AS (
    SELECT l.anonymous_id,
           count(*) FILTER (WHERE e.at < l.linked_at) AS before_link, count(*) FILTER (WHERE e.at >= l.linked_at) AS after_link
    FROM links l LEFT JOIN ps_ev e ON e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.user_id IS NULL AND e.anonymous_id = l.anonymous_id GROUP BY l.anonymous_id
)
SELECT pattern, count(*) AS anonymous_ids, sum(before_link)::int AS events_before_link, sum(after_link)::int AS events_after_link
FROM (SELECT per.*, CASE WHEN before_link > 0 AND after_link > 0 THEN 'both: earlier events stay anonymous, later ones are attributed'
                         WHEN before_link > 0 THEN 'only before the link: all stay anonymous'
                         WHEN after_link > 0 THEN 'only at or after the link: all attributed'
                         ELSE 'no anonymous event' END AS pattern FROM per) z
GROUP BY pattern ORDER BY pattern COLLATE "C";

-- @@ late_events_by_cutoff
-- For each analysis cutoff: the canonical events (the as-of log) that happened by the cutoff and arrived after it, by the names that move a figure. The as-of itself has none.
WITH c AS (SELECT c AS cutoff, label FROM ps_cuts)
SELECT c.label AS read, to_char(c.cutoff AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_at,
       count(e.event_id) AS late_events,
       count(*) FILTER (WHERE e.name = 'signup') AS signup, count(*) FILTER (WHERE e.name = 'activated') AS activated,
       count(*) FILTER (WHERE e.name = 'product_error') AS product_error, count(*) FILTER (WHERE e.name IN ('visit', 'onboarding_step_1', 'onboarding_step_2', 'onboarding_step_3', 'feature_used')) AS other
FROM c LEFT JOIN ps_ev e ON e.c = '2026-10-05T00:00:00Z' AND e.rn = 1 AND e.at <= c.cutoff AND e.received_at > c.cutoff
GROUP BY c.label, c.cutoff ORDER BY c.cutoff;

-- @@ late_activations_by_run
-- v1's activation per arm at each run, as the run saw it (events received by C: the published read) and in hindsight (events that happened by C, from the as-of log): what a
-- late event would have changed, without rewriting anything. Same rules as 05: ITT, mature, activation at or after max(signup, assigned_at) inside the 7-day window.
WITH reads AS (SELECT c, label FROM ps_cuts WHERE label IN ('an-001', 'an-002', 'an-003', 'an-004')),
base AS (
    SELECT 'known' AS scn, r.c AS rc, e.c, e.acct, e.name, e.at, e.cls FROM reads r JOIN ps_ev e ON e.c = r.c
  UNION ALL
    SELECT 'hindsight', r.c, e.c, e.acct, e.name, e.at, e.cls FROM reads r JOIN ps_ev e ON e.c = '2026-10-05T00:00:00Z' AND e.at <= r.c
),
sg AS (SELECT scn, rc, acct, min(at) AS at FROM base WHERE cls = 'analysed' AND name = 'signup' AND acct IS NOT NULL GROUP BY scn, rc, acct),
asg AS (
    SELECT s.scn, r.c AS rc, r.label, a.variant,
           (sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= r.c) AS mature,
           (sg.at IS NOT NULL AND EXISTS (SELECT 1 FROM base b WHERE b.scn = s.scn AND b.rc = r.c AND b.cls = 'analysed' AND b.name = 'activated' AND b.acct = a.unit_id
                                          AND b.at >= greatest(sg.at, a.assigned_at) AND b.at < sg.at + make_interval(hours => 168))) AS activated
    FROM reads r CROSS JOIN (VALUES ('known'), ('hindsight')) AS s (scn) JOIN assignments a ON a.experiment_version_id = 'xv-001' AND a.assigned_at <= r.c
         LEFT JOIN sg ON sg.scn = s.scn AND sg.rc = r.c AND sg.acct = a.unit_id
),
agg AS (
    SELECT label, rc, variant, scn, count(*) FILTER (WHERE mature) AS mature, count(*) FILTER (WHERE mature AND activated) AS activated FROM asg GROUP BY label, rc, variant, scn
)
SELECT k.label AS run, k.variant AS arm, k.mature AS mature_known, k.activated AS activated_known, h.mature AS mature_hindsight, h.activated AS activated_hindsight,
       h.activated - k.activated AS activations_changed_by_late_events
FROM agg k JOIN agg h ON h.label = k.label AND h.variant = k.variant AND h.scn = 'hindsight' WHERE k.scn = 'known' ORDER BY k.rc, k.variant COLLATE "C";
