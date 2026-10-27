-- 00_canonical_events.sql: the canonical event log and the account signups at every analysis cutoff, recomputed from facts (P06-ART-04, D-01, D-05, D-08).
-- Needs the loaded snapshot (events, event_properties, identity_links, users, accounts). Creates three TEMPORARY tables (ps_cuts, ps_ev, ps_signup) used by 01..08; reads nothing
-- the commands store (no run result, no verdict, no status): only the immutable facts. It repeats the canonical-event common table expressions of
-- data/sql/reference_metrics.sql (first_link, recv, ranked, resolved, classified) with the cutoff as a column instead of a parameter, so one
-- table holds the log as every run saw it. tests/test_artifacts.py checks that the repeated text is still there line for line.
-- Cutoffs (ps_cuts): the four v1 runs an-001..an-004, v2's run an-005 (2026-10-04), the as-of 2026-10-05 and 2026-10-02T12:00Z (INJ-06's earlier read).
-- A run at cutoff C uses only events with received_at <= C (D-01); a re-sent event (same actor, name, instant and properties) is a duplicate and the
-- earliest received_at wins; an identity link attributes an anonymous event only when event_at >= linked_at (forward only).
-- Interval arithmetic is hour-based elsewhere (R6-03): nothing here adds an interval to a timestamp.

-- @@ cuts
CREATE TEMP TABLE ps_cuts AS
SELECT c, label FROM (VALUES
    ('2026-05-18T00:00:00Z'::timestamptz, 'an-001'),
    ('2026-06-15T00:00:00Z'::timestamptz, 'an-002'),
    ('2026-07-13T00:00:00Z'::timestamptz, 'an-003'),
    ('2026-08-02T00:00:00Z'::timestamptz, 'an-004'),
    ('2026-10-02T12:00:00Z'::timestamptz, 'inj-06 earlier read'),
    ('2026-10-04T00:00:00Z'::timestamptz, 'an-005'),
    ('2026-10-05T00:00:00Z'::timestamptz, 'as-of')) AS t (c, label);

-- @@ events
CREATE TEMP TABLE ps_ev AS
WITH first_link AS (
    SELECT DISTINCT ON (anonymous_id) anonymous_id, user_id, linked_at FROM identity_links
    ORDER BY anonymous_id, linked_at, identity_link_id
),
anon_of_user AS (
    SELECT DISTINCT ON (user_id) user_id, anonymous_id FROM identity_links ORDER BY user_id, linked_at, identity_link_id
),
recv AS (
    SELECT p.c, e.*, coalesce(e.user_id, e.anonymous_id) AS actor,
           coalesce((SELECT jsonb_object_agg(ep.property_key, ep.property_value) FROM event_properties ep
                     WHERE ep.event_id = e.event_id), '{}'::jsonb) AS props
    FROM events e, ps_cuts p WHERE e.received_at <= p.c
),
ranked AS (
    SELECT recv.*, row_number() OVER (PARTITION BY c, actor, event_name, event_at, props ORDER BY received_at, event_id) AS rn FROM recv
),
resolved AS (
    SELECT c0.*, CASE WHEN c0.user_id IS NOT NULL THEN c0.user_id WHEN fl.linked_at <= c0.event_at THEN fl.user_id END AS u
    FROM ranked c0 LEFT JOIN first_link fl ON fl.anonymous_id = c0.anonymous_id
),
classified AS (
    SELECT r.*, u2.account_id AS acct,
           CASE WHEN r.rn > 1 THEN 'duplicate'
                WHEN (r.user_id IS NULL AND r.anonymous_id IS NULL) OR (r.u IS NOT NULL AND u2.user_id IS NULL) THEN 'unknown'
                WHEN r.u IS NOT NULL AND u2.bot_flag THEN 'bot'
                WHEN r.u IS NOT NULL AND a2.internal THEN 'internal'
                ELSE 'analysed' END AS cls
    FROM resolved r LEFT JOIN users u2 ON u2.user_id = r.u LEFT JOIN accounts a2 ON a2.account_id = u2.account_id
)
SELECT c.c, c.event_id, c.user_id, c.anonymous_id, c.event_name AS name, c.event_at AS at, c.received_at, c.rn, c.u, c.acct, c.cls,
       coalesce(c.anonymous_id, (SELECT anonymous_id FROM anon_of_user WHERE user_id = c.user_id), 'user:' || c.user_id) AS vk, c.props
FROM classified c;
CREATE INDEX ps_ev_idx ON ps_ev (c, cls, name);

-- @@ signups
-- The signup of an account is the earliest analysed `signup` event of its non-bot users (D-02), per cutoff.
CREATE TEMP TABLE ps_signup AS
SELECT c, acct, min(at) AS at FROM ps_ev WHERE cls = 'analysed' AND name = 'signup' AND acct IS NOT NULL GROUP BY c, acct;
CREATE INDEX ps_signup_idx ON ps_signup (c, acct);
