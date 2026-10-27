-- bi_fact_account.sql: the account fact of the BI package (docs/bi-package.md): one row per account (600), the as-of read (2026-10-05T00:00:00Z).
-- Needs 00_canonical_events.sql. Grain: ONE ROW PER ACCOUNT, internal accounts included with is_internal = 1 and no signup. Signup = the earliest analysed `signup` of a
-- non-bot user; maturity and retention flags are per the contract (D-02): activation window [signup, signup + 7 x 24 h), retention on the account's local calendar. Flags are 0/1
-- and EMPTY (not 0) when the account has no signup or is not mature, so a rate over the fact never counts an immature account.
-- @@ fact_account
WITH sess AS (
    SELECT u.account_id AS acct, (s.started_at AT TIME ZONE a.timezone)::date AS d FROM sessions s JOIN users u ON u.user_id = s.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE NOT u.bot_flag AND NOT a.internal AND s.started_at < '2026-10-05T00:00:00Z'::timestamptz
),
base AS (
    SELECT a.account_id, a.internal, sg.at AS signup_at, (sg.at AT TIME ZONE a.timezone)::date AS d0, ('2026-10-05T00:00:00Z'::timestamptz AT TIME ZONE a.timezone)::date AS dc,
           (sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= '2026-10-05T00:00:00Z'::timestamptz) AS mature7,
           EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = a.account_id AND e.at >= sg.at
                   AND e.at < sg.at + make_interval(hours => 168)) AS activated
    FROM accounts a LEFT JOIN ps_signup sg ON sg.c = '2026-10-05T00:00:00Z' AND sg.acct = a.account_id
)
SELECT b.account_id, CASE WHEN b.internal THEN 1 ELSE 0 END AS is_internal, to_char(b.signup_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS signup_at,
       to_char(b.signup_at AT TIME ZONE 'UTC', 'YYYYMMDD') AS signup_date_key, to_char(date_trunc('week', b.d0), 'YYYY-MM-DD') AS signup_week_local,
       CASE WHEN b.signup_at IS NOT NULL THEN CASE WHEN b.mature7 THEN 1 ELSE 0 END END AS mature_7d,
       CASE WHEN b.mature7 THEN CASE WHEN b.activated THEN 1 ELSE 0 END END AS activated_7d,
       CASE WHEN b.signup_at IS NOT NULL THEN CASE WHEN b.d0 + 8 <= b.dc THEN 1 ELSE 0 END END AS mature_day7,
       CASE WHEN b.d0 + 8 <= b.dc THEN CASE WHEN EXISTS (SELECT 1 FROM sess WHERE sess.acct = b.account_id AND sess.d - b.d0 = 7) THEN 1 ELSE 0 END END AS retained_day7,
       CASE WHEN b.d0 + 8 <= b.dc THEN CASE WHEN EXISTS (SELECT 1 FROM sess WHERE sess.acct = b.account_id AND sess.d - b.d0 >= 7) THEN 1 ELSE 0 END END AS retained_on_or_after_day7,
       CASE WHEN b.signup_at IS NOT NULL THEN CASE WHEN b.d0 + 35 <= b.dc THEN 1 ELSE 0 END END AS mature_week4,
       CASE WHEN b.d0 + 35 <= b.dc THEN CASE WHEN EXISTS (SELECT 1 FROM sess WHERE sess.acct = b.account_id AND sess.d - b.d0 BETWEEN 28 AND 34) THEN 1 ELSE 0 END END AS retained_week4
FROM base b ORDER BY b.account_id COLLATE "C";
