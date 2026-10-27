-- 09_golden_known_answer.sql: the known answer of the golden fixture, recomputed from the raw tables of the golden database (P06-ART-04, P06-GOLD-01, D-02, D-03).
-- Run against a database loaded with tests/fixtures/golden/inputs.json (prepare_snapshot.py --golden); the fixture's cutoff is 2026-10-26T00:00:00Z.
-- NOT the canonical-event machinery of 00: a deliberately plain recomputation from the base tables (distinct accounts, so a re-sent event cannot count twice), the hand-checkable
-- version of the answer in tests/fixtures/golden/CALCULATION.md: control 20 of 100 and treatment 30 of 100 mature assigned accounts activate within seven days (0.200000 and 0.300000,
-- +10.00 percentage points, relative lift 0.500000), and 5 of the 20 mature accounts of the retention cohort return on exact day 7 of their own calendar (0.250000).
-- run_all.py then checks, key by key, that data/sql/reference_metrics.sql on the same database equals expected.json and the Python domain. Hour-based intervals only.

-- @@ golden_arms
WITH ev AS (
    SELECT e.event_name AS name, e.event_at AS at, u.account_id AS acct FROM events e JOIN users u ON u.user_id = e.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE e.received_at <= '2026-10-26T00:00:00Z'::timestamptz AND NOT u.bot_flag AND NOT a.internal
),
sg AS (SELECT acct, min(at) AS at FROM ev WHERE name = 'signup' GROUP BY acct),
asg AS (
    SELECT a.variant, (sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= '2026-10-26T00:00:00Z'::timestamptz) AS mature,
           EXISTS (SELECT 1 FROM ev WHERE ev.acct = a.unit_id AND ev.name = 'activated' AND ev.at >= greatest(sg.at, a.assigned_at) AND ev.at < sg.at + make_interval(hours => 168)) AS activated
    FROM assignments a LEFT JOIN sg ON sg.acct = a.unit_id WHERE a.experiment_version_id = 'xv-001' AND a.assigned_at <= '2026-10-26T00:00:00Z'::timestamptz
)
SELECT variant AS arm, count(*) AS assigned, count(*) FILTER (WHERE mature) AS mature, count(*) FILTER (WHERE mature AND activated) AS activated,
       round((count(*) FILTER (WHERE mature AND activated))::numeric / count(*) FILTER (WHERE mature), 6) AS conversion
FROM asg GROUP BY variant ORDER BY variant COLLATE "C";

-- @@ golden_lift
-- The lift from the two plain conversions: 30/100 - 20/100 in percentage points (10.00) and divided by the control conversion (0.500000).
WITH ev AS (
    SELECT e.event_name AS name, e.event_at AS at, u.account_id AS acct FROM events e JOIN users u ON u.user_id = e.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE e.received_at <= '2026-10-26T00:00:00Z'::timestamptz AND NOT u.bot_flag AND NOT a.internal
),
sg AS (SELECT acct, min(at) AS at FROM ev WHERE name = 'signup' GROUP BY acct),
asg AS (
    SELECT a.variant, (sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= '2026-10-26T00:00:00Z'::timestamptz) AS mature,
           EXISTS (SELECT 1 FROM ev WHERE ev.acct = a.unit_id AND ev.name = 'activated' AND ev.at >= greatest(sg.at, a.assigned_at) AND ev.at < sg.at + make_interval(hours => 168)) AS activated
    FROM assignments a LEFT JOIN sg ON sg.acct = a.unit_id WHERE a.experiment_version_id = 'xv-001' AND a.assigned_at <= '2026-10-26T00:00:00Z'::timestamptz
),
r AS (
    SELECT (count(*) FILTER (WHERE variant = 'control' AND mature AND activated))::numeric / count(*) FILTER (WHERE variant = 'control' AND mature) AS c,
           (count(*) FILTER (WHERE variant = 'treatment' AND mature AND activated))::numeric / count(*) FILTER (WHERE variant = 'treatment' AND mature) AS t FROM asg
)
SELECT round(c, 6) AS control_conversion, round(t, 6) AS treatment_conversion, round((t - c) * 100, 2) AS absolute_lift_pp, round((t - c) / c, 6) AS relative_lift FROM r;

-- @@ golden_retention
-- The retention cohort (local signup dates 2026-09-14 to 2026-09-21, half open, internal accounts excluded): exact day 7 on each account's own calendar, on or after day 7, and week 4.
WITH sg AS (
    SELECT u.account_id AS acct, min(e.event_at) AS at FROM events e JOIN users u ON u.user_id = e.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE e.event_name = 'signup' AND e.received_at <= '2026-10-26T00:00:00Z'::timestamptz AND NOT u.bot_flag AND NOT a.internal GROUP BY u.account_id
),
cohort AS (
    SELECT sg.acct, a.timezone AS tz, (sg.at AT TIME ZONE a.timezone)::date AS d0, ('2026-10-26T00:00:00Z'::timestamptz AT TIME ZONE a.timezone)::date AS dc
    FROM sg JOIN accounts a ON a.account_id = sg.acct WHERE (sg.at AT TIME ZONE a.timezone)::date >= DATE '2026-09-14' AND (sg.at AT TIME ZONE a.timezone)::date < DATE '2026-09-21'
),
sess AS (
    SELECT u.account_id AS acct, (s.started_at AT TIME ZONE a.timezone)::date AS d FROM sessions s JOIN users u ON u.user_id = s.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE NOT u.bot_flag AND NOT a.internal AND s.started_at < '2026-10-26T00:00:00Z'::timestamptz
),
f AS (
    SELECT c.acct, (c.d0 + 8 <= c.dc) AS m7, (c.d0 + 35 <= c.dc) AS m35,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = c.acct AND sess.d - c.d0 = 7) AS r7,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = c.acct AND sess.d - c.d0 >= 7) AS r7plus,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = c.acct AND sess.d - c.d0 BETWEEN 28 AND 34) AS r4w
    FROM cohort c
)
SELECT count(*) AS cohort_accounts, count(*) FILTER (WHERE m7) AS day7_mature, count(*) FILTER (WHERE m7 AND r7) AS day7_retained,
       round((count(*) FILTER (WHERE m7 AND r7))::numeric / count(*) FILTER (WHERE m7), 6) AS day7_rate,
       count(*) FILTER (WHERE m7 AND r7plus) AS on_or_after_day7_retained, count(*) FILTER (WHERE m35 AND r4w) AS week4_retained
FROM f;
