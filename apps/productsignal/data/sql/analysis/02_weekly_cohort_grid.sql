-- 02_weekly_cohort_grid.sql: the weekly signup cohort grid in each account's own calendar (P06-ART-04, P06-MET-04, P06-MET-05, D-02, P06-TEST-12).
-- Question: of the accounts that signed up in a week, how many came back on exactly day 1, 7, 14 or 28, on or after day 7, or in days 28-34, counting only
-- the accounts whose day has completed at the as-of 2026-10-05T00:00:00Z?
-- Needs 00_canonical_events.sql (ps_signup). Day 0 is the account's LOCAL signup date (its IANA timezone, `timestamptz AT TIME ZONE tz`); a session's day
-- index is its local date minus that date. MATURE for a column that needs day N: local signup date + N + 1 <= the cutoff's local date (day 7: day 8 has begun;
-- week 4 needs day 34). Sessions of bots and internal accounts are ignored and a session counts only when it started before the cutoff. The week is the
-- Monday of the local signup date. Cells with no mature account are blank (status), cells with some are partial, the rest complete: no immature account
-- is ever in a rate. Exact day 7 and "on or after day 7" are separate columns and never mixed.

-- @@ cohort_grid
WITH signup AS (
    SELECT s.acct, a.timezone AS tz, (s.at AT TIME ZONE a.timezone)::date AS d0, ('2026-10-05T00:00:00Z'::timestamptz AT TIME ZONE a.timezone)::date AS dc
    FROM ps_signup s JOIN accounts a ON a.account_id = s.acct WHERE s.c = '2026-10-05T00:00:00Z' AND NOT a.internal
),
sess AS (
    SELECT u.account_id AS acct, (s.started_at AT TIME ZONE a.timezone)::date AS d FROM sessions s
    JOIN users u ON u.user_id = s.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE NOT u.bot_flag AND NOT a.internal AND s.started_at < '2026-10-05T00:00:00Z'::timestamptz
),
flags AS (
    SELECT g.acct, date_trunc('week', g.d0)::date AS week_start,
           (g.d0 + 2 <= g.dc) AS m1, (g.d0 + 8 <= g.dc) AS m7, (g.d0 + 15 <= g.dc) AS m14, (g.d0 + 29 <= g.dc) AS m28, (g.d0 + 35 <= g.dc) AS m35,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 = 1) AS r1,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 = 7) AS r7,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 = 14) AS r14,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 = 28) AS r28,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 >= 7) AS r7plus,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 BETWEEN 28 AND 34) AS r4w
    FROM signup g
)
SELECT coalesce(week_start::text, 'ALL') AS week_start, count(*) AS accounts,
       count(*) FILTER (WHERE m1) AS day1_mature, count(*) FILTER (WHERE m1 AND r1) AS day1_retained,
       count(*) FILTER (WHERE m7) AS day7_mature, count(*) FILTER (WHERE m7 AND r7) AS day7_retained,
       count(*) FILTER (WHERE m14) AS day14_mature, count(*) FILTER (WHERE m14 AND r14) AS day14_retained,
       count(*) FILTER (WHERE m28) AS day28_mature, count(*) FILTER (WHERE m28 AND r28) AS day28_retained,
       count(*) FILTER (WHERE m7) AS on_or_after_day7_mature, count(*) FILTER (WHERE m7 AND r7plus) AS on_or_after_day7_retained,
       count(*) FILTER (WHERE m35) AS week4_mature, count(*) FILTER (WHERE m35 AND r4w) AS week4_retained,
       CASE WHEN count(*) FILTER (WHERE m7) = 0 THEN 'blank' WHEN count(*) FILTER (WHERE m7) < count(*) THEN 'partial' ELSE 'complete' END AS day7_status,
       CASE WHEN count(*) FILTER (WHERE m35) = 0 THEN 'blank' WHEN count(*) FILTER (WHERE m35) < count(*) THEN 'partial' ELSE 'complete' END AS week4_status
FROM flags GROUP BY ROLLUP (week_start) ORDER BY week_start NULLS LAST;

-- @@ window_check
-- The configured retention cohort (metric_config: local signup dates 2026-08-24 to 2026-08-31, half open) as the published `retention` metric counts it:
-- cohort 16, exact day 7 retained 5 of 16 mature, on or after day 7 11 of 16, week 4 7 of 16; one internal account excluded and counted apart.
WITH cfg AS (SELECT (windows->'retention'->>'signup_from')::date AS d_from, (windows->'retention'->>'signup_to')::date AS d_to FROM metric_config WHERE id = 1),
signup AS (
    SELECT s.acct, a.timezone AS tz, (s.at AT TIME ZONE a.timezone)::date AS d0, ('2026-10-05T00:00:00Z'::timestamptz AT TIME ZONE a.timezone)::date AS dc
    FROM ps_signup s JOIN accounts a ON a.account_id = s.acct, cfg
    WHERE s.c = '2026-10-05T00:00:00Z' AND NOT a.internal AND (s.at AT TIME ZONE a.timezone)::date >= cfg.d_from AND (s.at AT TIME ZONE a.timezone)::date < cfg.d_to
),
sess AS (
    SELECT u.account_id AS acct, (s.started_at AT TIME ZONE a.timezone)::date AS d FROM sessions s
    JOIN users u ON u.user_id = s.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE NOT u.bot_flag AND NOT a.internal AND s.started_at < '2026-10-05T00:00:00Z'::timestamptz
),
flags AS (
    SELECT g.acct, (g.d0 + 8 <= g.dc) AS m7, (g.d0 + 35 <= g.dc) AS m35,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 = 7) AS r7,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 >= 7) AS r7plus,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND sess.d - g.d0 BETWEEN 28 AND 34) AS r4w
    FROM signup g
)
SELECT count(*) AS cohort_accounts, count(*) FILTER (WHERE m7) AS day7_mature, count(*) FILTER (WHERE m7 AND r7) AS day7_retained,
       round((count(*) FILTER (WHERE m7 AND r7))::numeric / count(*) FILTER (WHERE m7), 6) AS day7_rate,
       count(*) FILTER (WHERE m7 AND r7plus) AS on_or_after_day7_retained,
       round((count(*) FILTER (WHERE m7 AND r7plus))::numeric / count(*) FILTER (WHERE m7), 6) AS on_or_after_day7_rate,
       count(*) FILTER (WHERE m35) AS week4_mature, count(*) FILTER (WHERE m35 AND r4w) AS week4_retained,
       round((count(*) FILTER (WHERE m35 AND r4w))::numeric / count(*) FILTER (WHERE m35), 6) AS week4_rate,
       (SELECT count(DISTINCT e.acct) FROM ps_ev e JOIN accounts a ON a.account_id = e.acct, cfg
         WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'internal' AND e.name = 'signup'
           AND (e.at AT TIME ZONE a.timezone)::date >= cfg.d_from AND (e.at AT TIME ZONE a.timezone)::date < cfg.d_to) AS excluded_internal_accounts
FROM flags;

-- @@ timezone_effect
-- Why the account's calendar matters (INJ-12, P06-TEST-12): among the accounts mature on day 7, those with a session on exact day 7 by the account's local
-- calendar, those with one by the UTC calendar, and those that are day 7 in only one of the two. The UTC reading is NOT the contract figure.
WITH signup AS (
    SELECT s.acct, a.timezone AS tz, s.at, (s.at AT TIME ZONE a.timezone)::date AS d0, ('2026-10-05T00:00:00Z'::timestamptz AT TIME ZONE a.timezone)::date AS dc
    FROM ps_signup s JOIN accounts a ON a.account_id = s.acct WHERE s.c = '2026-10-05T00:00:00Z' AND NOT a.internal
),
sess AS (
    SELECT u.account_id AS acct, s.started_at FROM sessions s JOIN users u ON u.user_id = s.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE NOT u.bot_flag AND NOT a.internal AND s.started_at < '2026-10-05T00:00:00Z'::timestamptz
),
flags AS (
    SELECT g.tz, (g.d0 + 8 <= g.dc) AS m7,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND (sess.started_at AT TIME ZONE g.tz)::date - g.d0 = 7) AS local7,
           EXISTS (SELECT 1 FROM sess WHERE sess.acct = g.acct AND (sess.started_at AT TIME ZONE 'UTC')::date - (g.at AT TIME ZONE 'UTC')::date = 7) AS utc7
    FROM signup g
)
SELECT coalesce(tz, 'ALL') AS timezone, count(*) FILTER (WHERE m7) AS mature_accounts, count(*) FILTER (WHERE m7 AND local7) AS exact_day7_local,
       count(*) FILTER (WHERE m7 AND utc7) AS exact_day7_utc,
       count(*) FILTER (WHERE m7 AND local7 AND NOT utc7) AS local_only, count(*) FILTER (WHERE m7 AND utc7 AND NOT local7) AS utc_only
FROM flags GROUP BY ROLLUP (tz) ORDER BY tz COLLATE "C" NULLS LAST;
