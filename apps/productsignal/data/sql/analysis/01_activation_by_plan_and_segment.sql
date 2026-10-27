-- 01_activation_by_plan_and_segment.sql: signups and seven-day activation by plan and segment, with maturity kept visible (P06-ART-04, P06-MET-02, D-02).
-- Question: who activates, how much of the population is old enough to be judged, and does the "business activates faster" relationship show up?
-- Needs 00_canonical_events.sql (ps_ev, ps_signup at the as-of 2026-10-05T00:00:00Z). Population: the 588 non-internal accounts of the 600 (12 internal
-- accounts are never counted); an account has a signup when an analysed `signup` event of a non-bot user exists. Activation: an analysed `activated` event
-- in [signup, signup + 7 x 24 h); MATURE when signup + 7 x 24 h <= the as-of (a signup that is not mature is counted apart and never in a rate).
-- Observed, not experimental: these are all accounts, assigned or not, so none of it is the treatment effect (that is 05). Hour-based intervals only.

-- @@ plan_segment
WITH main AS (SELECT * FROM ps_signup WHERE c = '2026-10-05T00:00:00Z'),
acc AS (
    SELECT a.account_id, a.plan, a.segment, m.at AS signup_at,
           (m.at IS NOT NULL AND m.at + make_interval(hours => 168) <= '2026-10-05T00:00:00Z'::timestamptz) AS mature,
           EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = a.account_id
                   AND e.at >= m.at AND e.at < m.at + make_interval(hours => 168)) AS activated
    FROM accounts a LEFT JOIN main m ON m.acct = a.account_id WHERE NOT a.internal
)
SELECT coalesce(plan, 'ALL') AS plan, coalesce(segment, 'ALL') AS segment,
       count(*) AS accounts, count(signup_at) AS signed_up,
       count(*) FILTER (WHERE signup_at IS NOT NULL AND NOT mature) AS immature,
       count(*) FILTER (WHERE mature) AS mature,
       count(*) FILTER (WHERE mature AND activated) AS activated,
       CASE WHEN count(*) FILTER (WHERE mature) = 0 THEN NULL
            ELSE round((count(*) FILTER (WHERE mature AND activated))::numeric / count(*) FILTER (WHERE mature), 6) END AS activation_rate
FROM acc GROUP BY GROUPING SETS ((plan, segment), (plan), (segment), ())
ORDER BY GROUPING(plan), plan COLLATE "C", GROUPING(segment), segment COLLATE "C";

-- @@ by_signup_month
-- Maturity by calendar month of the signup (UTC): the last month is mostly immature at the as-of, which is why no rate is shown for the immature.
WITH main AS (SELECT * FROM ps_signup WHERE c = '2026-10-05T00:00:00Z'),
acc AS (
    SELECT to_char(m.at AT TIME ZONE 'UTC', 'YYYY-MM') AS signup_month,
           (m.at + make_interval(hours => 168) <= '2026-10-05T00:00:00Z'::timestamptz) AS mature,
           EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = m.acct
                   AND e.at >= m.at AND e.at < m.at + make_interval(hours => 168)) AS activated
    FROM main m JOIN accounts a ON a.account_id = m.acct WHERE NOT a.internal
)
SELECT signup_month, count(*) AS signups, count(*) FILTER (WHERE NOT mature) AS immature, count(*) FILTER (WHERE mature) AS mature,
       count(*) FILTER (WHERE mature AND activated) AS activated,
       CASE WHEN count(*) FILTER (WHERE mature) = 0 THEN NULL
            ELSE round((count(*) FILTER (WHERE mature AND activated))::numeric / count(*) FILTER (WHERE mature), 6) END AS activation_rate
FROM acc GROUP BY signup_month ORDER BY signup_month;

-- @@ window_check
-- The configured activation window of the dataset (metric_config: signups from 2026-09-07 to 2026-10-05): the same population rule as the
-- published `activation` metric. 76 signups, 17 immature, 59 mature, 21 activated (reconciled to the reference SQL and the domain in run_all.py).
WITH cfg AS (SELECT (windows->'activation'->>'from')::timestamptz AS w_from, (windows->'activation'->>'to')::timestamptz AS w_to,
                    (windows->'activation'->>'window_days')::int AS days FROM metric_config WHERE id = 1),
pop AS (
    SELECT s.acct, s.at, (s.at + make_interval(hours => 24 * cfg.days) <= '2026-10-05T00:00:00Z'::timestamptz) AS mature,
           EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = s.c AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = s.acct AND e.at >= s.at
                   AND e.at < s.at + make_interval(hours => 24 * cfg.days)) AS activated
    FROM ps_signup s, cfg WHERE s.c = '2026-10-05T00:00:00Z' AND s.at >= cfg.w_from AND s.at < cfg.w_to
)
SELECT count(*) AS signups, count(*) FILTER (WHERE NOT mature) AS immature, count(*) FILTER (WHERE mature) AS mature,
       count(*) FILTER (WHERE mature AND activated) AS activated,
       round((count(*) FILTER (WHERE mature AND activated))::numeric / count(*) FILTER (WHERE mature), 6) AS activation_rate
FROM pop;

-- @@ time_to_activation_by_plan
-- DESIGNED relationship DR-03 (the generator's manifest) read from the facts: accounts never assigned to the treatment in any experiment version
-- (control, v2 control and unassigned), mature at the as-of, so the experiment's effect does not mix in. median_hours is the element n // 2 of the
-- sorted waits in whole seconds (the upper median for an even count, the generator's own rule), in hours at 2 places, half up.
WITH main AS (SELECT * FROM ps_signup WHERE c = '2026-10-05T00:00:00Z'),
acc AS (
    SELECT a.plan, m.acct,
           (SELECT min(e.at) FROM ps_ev e WHERE e.c = m.c AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = m.acct
                   AND e.at >= m.at AND e.at < m.at + make_interval(hours => 168)) AS first_activation, m.at AS signup_at
    FROM main m JOIN accounts a ON a.account_id = m.acct
    WHERE NOT a.internal AND m.at + make_interval(hours => 168) <= '2026-10-05T00:00:00Z'::timestamptz
      AND NOT EXISTS (SELECT 1 FROM assignments s WHERE s.unit_id = m.acct AND s.variant = 'treatment')
),
waits AS (
    SELECT plan, extract(epoch FROM first_activation - signup_at)::bigint AS secs FROM acc WHERE first_activation IS NOT NULL
),
med AS (
    SELECT plan, (array_agg(secs ORDER BY secs))[count(*) / 2 + 1] AS median_secs FROM waits GROUP BY plan
)
SELECT acc.plan, count(*) AS accounts, count(acc.first_activation) AS activated,
       round(count(acc.first_activation)::numeric / count(*), 6) AS activation_rate,
       round(med.median_secs::numeric / 3600, 2) AS median_hours_to_activate
FROM acc LEFT JOIN med ON med.plan = acc.plan GROUP BY acc.plan, med.median_secs ORDER BY acc.plan COLLATE "C";
