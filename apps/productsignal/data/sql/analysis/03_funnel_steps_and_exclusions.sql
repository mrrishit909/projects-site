-- 03_funnel_steps_and_exclusions.sql: the visitor funnel with its strict order and gap, signup conversion, and what each step excludes (P06-ART-04, P06-MET-01, P06-MET-03, D-01, D-05).
-- Question: how many visitors reach each onboarding step, how sensitive is that to the maximum gap, which events never reach any figure and why, and how
-- much does one late batch of events move the funnel?
-- Needs 00_canonical_events.sql (ps_ev). The funnel definition is the stored `fun-001` (visit, signup, onboarding_step_1, activated; maximum gap 48 h, window
-- 2026-09-28 to 2026-10-05, half open): the unit is the visitor key (the anonymous id, else the user's earliest linked anonymous id, else the user), the
-- window applies to the FIRST step only, a unit reaches step k only after step k-1 and within the gap (inclusive) and there is no re-anchoring. Only analysed
-- events count: duplicates, unknown identities, bots and internal accounts are excluded first and counted in `exclusions_by_event`.

-- @@ funnel_steps
WITH RECURSIVE fd AS (SELECT steps, max_gap_hours, window_from, window_to FROM funnel_definitions ORDER BY created_at DESC, definition_id DESC, version DESC LIMIT 1),
chain AS (
    SELECT ev.vk, 1 AS k, min(ev.at) AS at FROM ps_ev ev, fd
    WHERE ev.c = '2026-10-05T00:00:00Z' AND ev.cls = 'analysed' AND ev.name = fd.steps[1] AND ev.at >= fd.window_from AND ev.at < fd.window_to GROUP BY ev.vk
  UNION ALL
    SELECT c.vk, c.k + 1,
           (SELECT min(e2.at) FROM ps_ev e2 WHERE e2.c = '2026-10-05T00:00:00Z' AND e2.cls = 'analysed' AND e2.vk = c.vk AND e2.name = fd.steps[c.k + 1]
              AND e2.at > c.at AND e2.at <= c.at + make_interval(hours => fd.max_gap_hours))
    FROM chain c, fd WHERE c.k < cardinality(fd.steps) AND c.at IS NOT NULL
),
st AS (
    SELECT s.ord, s.name, (SELECT count(*) FROM chain c WHERE c.k = s.ord AND c.at IS NOT NULL) AS units FROM fd, unnest(fd.steps) WITH ORDINALITY AS s (name, ord)
)
SELECT s.ord AS step_number, s.name AS step, s.units,
       CASE WHEN s.ord = 1 THEN NULL WHEN p.units = 0 THEN NULL ELSE round(s.units::numeric / p.units, 6) END AS conversion_from_previous,
       CASE WHEN f.units = 0 THEN NULL ELSE round(s.units::numeric / f.units, 6) END AS conversion_from_first,
       CASE WHEN s.ord = 1 THEN NULL ELSE p.units - s.units END AS lost_at_this_step
FROM st s LEFT JOIN st p ON p.ord = s.ord - 1, (SELECT units FROM st WHERE ord = 1) f ORDER BY s.ord;

-- @@ funnel_gap_sensitivity
-- The same funnel and window at a maximum gap of 24, 48 (the stored definition) and 72 hours: a step conversion that moves with the gap is a definition
-- choice, not a finding. Units per step; the 48 h row equals funnel_steps.
WITH RECURSIVE fd AS (SELECT steps, window_from, window_to FROM funnel_definitions ORDER BY created_at DESC, definition_id DESC, version DESC LIMIT 1),
gaps(g) AS (VALUES (24), (48), (72)),
chain AS (
    SELECT g.g, ev.vk, 1 AS k, min(ev.at) AS at FROM ps_ev ev, fd, gaps g
    WHERE ev.c = '2026-10-05T00:00:00Z' AND ev.cls = 'analysed' AND ev.name = fd.steps[1] AND ev.at >= fd.window_from AND ev.at < fd.window_to GROUP BY g.g, ev.vk
  UNION ALL
    SELECT c.g, c.vk, c.k + 1,
           (SELECT min(e2.at) FROM ps_ev e2 WHERE e2.c = '2026-10-05T00:00:00Z' AND e2.cls = 'analysed' AND e2.vk = c.vk AND e2.name = fd.steps[c.k + 1]
              AND e2.at > c.at AND e2.at <= c.at + make_interval(hours => c.g))
    FROM chain c, fd WHERE c.k < cardinality(fd.steps) AND c.at IS NOT NULL
)
SELECT g.g AS max_gap_hours,
       count(*) FILTER (WHERE c.k = 1 AND c.at IS NOT NULL) AS visit, count(*) FILTER (WHERE c.k = 2 AND c.at IS NOT NULL) AS signup,
       count(*) FILTER (WHERE c.k = 3 AND c.at IS NOT NULL) AS onboarding_step_1, count(*) FILTER (WHERE c.k = 4 AND c.at IS NOT NULL) AS activated,
       round((count(*) FILTER (WHERE c.k = 4 AND c.at IS NOT NULL))::numeric / count(*) FILTER (WHERE c.k = 1 AND c.at IS NOT NULL), 6) AS overall_conversion
FROM gaps g LEFT JOIN chain c ON c.g = g.g GROUP BY g.g ORDER BY g.g;

-- @@ signup_conversion
-- P06-MET-01 on the visitor unit: distinct anonymous ids with a `visit` in the window are the denominator, those with a `signup` of the same anonymous id
-- in the same window the numerator (the stored signup_conversion window, 2026-09-28 to 2026-10-05). No gap; it may differ from the funnel's first step.
WITH cfg AS (SELECT (windows->'signup_conversion'->>'from')::timestamptz AS w_from, (windows->'signup_conversion'->>'to')::timestamptz AS w_to FROM metric_config WHERE id = 1),
visitors AS (
    SELECT DISTINCT e.anonymous_id FROM ps_ev e, cfg
    WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.name = 'visit' AND e.anonymous_id IS NOT NULL AND e.at >= cfg.w_from AND e.at < cfg.w_to
),
signed AS (
    SELECT DISTINCT e.anonymous_id FROM ps_ev e, cfg
    WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.name = 'signup' AND e.anonymous_id IN (SELECT anonymous_id FROM visitors)
      AND e.at >= cfg.w_from AND e.at < cfg.w_to
)
SELECT (SELECT count(*) FROM visitors) AS visitors, (SELECT count(*) FROM signed) AS signed_up,
       round((SELECT count(*) FROM signed)::numeric / (SELECT count(*) FROM visitors), 6) AS signup_conversion;

-- @@ exclusions_by_event
-- Every event row of the log at the as-of, by event name, and the class it ended in: analysed (counted), duplicate (re-sent, earliest received wins),
-- unknown (no user and no link, or a user that does not exist), bot, internal. Nothing is dropped silently: the classes add up to the rows received.
SELECT coalesce(r.name, 'ALL') AS event_name, count(*) AS rows_received,
       count(*) FILTER (WHERE r.cls = 'duplicate') AS duplicates_dropped, count(*) FILTER (WHERE r.cls = 'unknown') AS unknown_identity,
       count(*) FILTER (WHERE r.cls = 'bot') AS bot_excluded, count(*) FILTER (WHERE r.cls = 'internal') AS internal_excluded,
       count(*) FILTER (WHERE r.cls = 'analysed') AS analysed
FROM ps_ev r WHERE r.c = '2026-10-05T00:00:00Z' GROUP BY ROLLUP (r.name) ORDER BY r.name COLLATE "C" NULLS LAST;

-- @@ late_batch_effect
-- INJ-06 (P06-TEST-06): the same funnel over the same events-by-instant, read two ways at 2026-10-02T12:00Z. `known_at_the_read` is the log as that run saw it
-- (events received by then); `in_hindsight` is the as-of log restricted to events that HAPPENED by then (event_at <= the read). The difference is EVERY event
-- that happened by the read and arrived after it: the 8 designed INJ-06 `onboarding_step_1` events (received days late, 4 of their visitors also activated) and
-- the ordinary delayed events of the log (one more `visit` and its `signup`, one more `onboarding_step_1`). run_all.py isolates the 8 designed events against
-- the injection manifest (+8 step-1 units, +4 activated). The earlier published read is never rewritten: the later one is a disclosed revision.
WITH RECURSIVE fd AS (SELECT steps, max_gap_hours, window_from, window_to FROM funnel_definitions ORDER BY created_at DESC, definition_id DESC, version DESC LIMIT 1),
base AS (
    SELECT 'known_at_the_read' AS scn, ev.vk, ev.name, ev.at FROM ps_ev ev WHERE ev.c = '2026-10-02T12:00:00Z' AND ev.cls = 'analysed'
  UNION ALL
    SELECT 'in_hindsight', ev.vk, ev.name, ev.at FROM ps_ev ev WHERE ev.c = '2026-10-05T00:00:00Z' AND ev.cls = 'analysed' AND ev.at <= '2026-10-02T12:00:00Z'
),
chain AS (
    SELECT b.scn, b.vk, 1 AS k, min(b.at) AS at FROM base b, fd WHERE b.name = fd.steps[1] AND b.at >= fd.window_from AND b.at < fd.window_to GROUP BY b.scn, b.vk
  UNION ALL
    SELECT c.scn, c.vk, c.k + 1,
           (SELECT min(b2.at) FROM base b2 WHERE b2.scn = c.scn AND b2.vk = c.vk AND b2.name = fd.steps[c.k + 1] AND b2.at > c.at AND b2.at <= c.at + make_interval(hours => fd.max_gap_hours))
    FROM chain c, fd WHERE c.k < cardinality(fd.steps) AND c.at IS NOT NULL
),
tot AS (
    SELECT c.scn, count(*) FILTER (WHERE c.k = 1 AND c.at IS NOT NULL) AS visit, count(*) FILTER (WHERE c.k = 2 AND c.at IS NOT NULL) AS signup,
           count(*) FILTER (WHERE c.k = 3 AND c.at IS NOT NULL) AS onboarding_step_1, count(*) FILTER (WHERE c.k = 4 AND c.at IS NOT NULL) AS activated
    FROM chain c GROUP BY c.scn
)
SELECT scn AS reading, visit, signup, onboarding_step_1, activated FROM tot
UNION ALL
SELECT 'late batch (hindsight - known)', h.visit - k.visit, h.signup - k.signup, h.onboarding_step_1 - k.onboarding_step_1, h.activated - k.activated
FROM tot h, tot k WHERE h.scn = 'in_hindsight' AND k.scn = 'known_at_the_read'
ORDER BY 1 DESC;
