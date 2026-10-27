-- 07_guardrail_and_revenue_per_arm.sql: the prespecified guardrail, revenue per assigned account and week-4 retention per arm of experiment v1 (P06-ART-04, P06-MET-05, P06-MET-11, P06-MET-12, D-03, D-08, D-10).
-- Question: does the treatment that lifts activation cost us anything we said we would watch, and does it move anything else?
-- Needs 00_canonical_events.sql (ps_ev, ps_signup, ps_cuts). Reads: the four v1 runs and the as-of; every read applies the cutoff rule (D-08): assignments with assigned_at <= C,
-- events received by C, subscriptions with starts_at <= C. Population = the assigned MATURE accounts (signup + 7 x 24 h <= C), intention to treat.
-- GUARDRAIL (the plan's `product_error_rate`, window 7 days): eligible = mature accounts whose guardrail window is complete (assigned_at + 7 x 24 h <= C, D-10); a unit counts when an
-- analysed `product_error` event lies in [assigned_at, assigned_at + 7 x 24 h). Difference = treatment minus control with the Newcombe interval at the plan's z; the verdict is HARMFUL
-- when the whole interval lies above 0 (more errors under treatment), INSUFFICIENT when an arm has no eligible unit, else OK.
-- REVENUE per assigned account (USD): subscriptions with status active or ended (trial and refunded carry none) whose starts_at is inside the plan's revenue window and <= C, summed per
-- account over ALL mature assigned accounts (zeros included), divided by the accounts; the per-arm interval is a Student t interval over account-level values (df = n - 1, quantile from
-- t_critical_975, the Python-generated table, the one number SQL cannot derive); the difference of means uses the Welch interval with t at the Welch-Satterthwaite df rounded DOWN.
-- WEEK-4 RETENTION: a session on one of the local calendar days 28-34 of the account's timezone, over the accounts whose day 35 has begun at the as-of (D-02).
-- OBSERVED, one draw: the generator designed the guardrail and revenue to be equal across arms and the revenue to be noisy; nothing here is selected after the fact.

-- @@ guardrail_by_cutoff
WITH pl AS (SELECT (plan->>'z')::numeric AS z, (plan->'guardrail'->>'window_days')::int AS g_days FROM analysis_plans WHERE experiment_version_id = 'xv-001'),
reads AS (SELECT c, label FROM ps_cuts WHERE label IN ('an-001', 'an-002', 'an-003', 'an-004', 'as-of')),
asg AS (
    SELECT r.c, r.label, a.variant,
           (sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= r.c) AS mature,
           (a.assigned_at + make_interval(hours => 24 * pl.g_days) <= r.c) AS g_elig,
           EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = r.c AND e.cls = 'analysed' AND e.name = 'product_error' AND e.acct = a.unit_id AND e.at >= a.assigned_at
                   AND e.at < a.assigned_at + make_interval(hours => 24 * pl.g_days)) AS errored
    FROM reads r CROSS JOIN pl JOIN assignments a ON a.experiment_version_id = 'xv-001' AND a.assigned_at <= r.c LEFT JOIN ps_signup sg ON sg.c = r.c AND sg.acct = a.unit_id
),
cnt AS (
    SELECT r.c, r.label,
           count(*) FILTER (WHERE a.variant = 'control' AND a.mature AND a.g_elig) AS n_c, count(*) FILTER (WHERE a.variant = 'treatment' AND a.mature AND a.g_elig) AS n_t,
           count(*) FILTER (WHERE a.variant = 'control' AND a.mature AND a.g_elig AND a.errored) AS x_c, count(*) FILTER (WHERE a.variant = 'treatment' AND a.mature AND a.g_elig AND a.errored) AS x_t
    FROM reads r LEFT JOIN asg a ON a.c = r.c GROUP BY r.c, r.label
),
wil AS (
    SELECT cnt.*, pl.z, x_c::numeric / n_c AS pr_c, x_t::numeric / n_t AS pr_t,
           (x_c::numeric / n_c + pl.z ^ 2 / (2 * n_c) - pl.z * sqrt(round((x_c::numeric / n_c) * (1 - x_c::numeric / n_c) / n_c + pl.z ^ 2 / (4 * n_c::numeric * n_c), 40))) / (1 + pl.z ^ 2 / n_c) AS lo_c,
           (x_c::numeric / n_c + pl.z ^ 2 / (2 * n_c) + pl.z * sqrt(round((x_c::numeric / n_c) * (1 - x_c::numeric / n_c) / n_c + pl.z ^ 2 / (4 * n_c::numeric * n_c), 40))) / (1 + pl.z ^ 2 / n_c) AS hi_c,
           (x_t::numeric / n_t + pl.z ^ 2 / (2 * n_t) - pl.z * sqrt(round((x_t::numeric / n_t) * (1 - x_t::numeric / n_t) / n_t + pl.z ^ 2 / (4 * n_t::numeric * n_t), 40))) / (1 + pl.z ^ 2 / n_t) AS lo_t,
           (x_t::numeric / n_t + pl.z ^ 2 / (2 * n_t) + pl.z * sqrt(round((x_t::numeric / n_t) * (1 - x_t::numeric / n_t) / n_t + pl.z ^ 2 / (4 * n_t::numeric * n_t), 40))) / (1 + pl.z ^ 2 / n_t) AS hi_t
    FROM cnt, pl WHERE n_c > 0 AND n_t > 0
),
nc AS (
    SELECT w.*, (pr_t - pr_c) AS d, (pr_t - pr_c) - sqrt(round((pr_t - lo_t) ^ 2 + (hi_c - pr_c) ^ 2, 40)) AS lo, (pr_t - pr_c) + sqrt(round((hi_t - pr_t) ^ 2 + (pr_c - lo_c) ^ 2, 40)) AS hi FROM wil w
)
SELECT nc.label AS run, to_char(nc.c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_at, nc.n_c AS eligible_control, nc.n_t AS eligible_treatment,
       nc.x_c AS errors_control, nc.x_t AS errors_treatment, round(nc.pr_c, 6) AS error_rate_control, round(nc.pr_t, 6) AS error_rate_treatment,
       round(nc.d * 100, 2) AS difference_pp, round(nc.lo, 6) AS newcombe_low, round(nc.hi, 6) AS newcombe_high, (nc.lo <= 0 AND nc.hi >= 0) AS interval_includes_zero,
       CASE WHEN nc.lo > 0 THEN 'HARMFUL' ELSE 'OK' END AS verdict
FROM nc ORDER BY nc.c;

-- @@ revenue_by_arm
WITH pl AS (SELECT (plan->'revenue_window'->>'from')::timestamptz AS rev_from, (plan->'revenue_window'->>'to')::timestamptz AS rev_to, plan->>'confidence' AS confidence
            FROM analysis_plans WHERE experiment_version_id = 'xv-001'),
reads AS (SELECT c, label FROM ps_cuts WHERE label IN ('an-001', 'an-002', 'an-003', 'an-004', 'as-of')),
asg AS (
    SELECT r.c, r.label, a.variant,
           coalesce((SELECT sum(s.amount_usd) FROM subscriptions s WHERE s.account_id = a.unit_id AND s.status IN ('active', 'ended') AND s.starts_at >= pl.rev_from
                     AND s.starts_at < pl.rev_to AND s.starts_at <= r.c), 0) AS revenue
    FROM reads r CROSS JOIN pl JOIN assignments a ON a.experiment_version_id = 'xv-001' AND a.assigned_at <= r.c JOIN ps_signup sg ON sg.c = r.c AND sg.acct = a.unit_id
    WHERE sg.at + make_interval(hours => 168) <= r.c
),
st AS (
    SELECT c, label, variant, count(*) AS n, sum(revenue) AS total, round(sum(revenue) / count(*), 40) AS mean40,
           CASE WHEN count(*) > 1 THEN sum((revenue - round((SELECT sum(b.revenue) / count(*) FROM asg b WHERE b.c = asg.c AND b.variant = asg.variant), 40)) ^ 2) / (count(*) - 1) END AS var
    FROM asg GROUP BY c, label, variant
)
SELECT st.label AS run, to_char(st.c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_at, st.variant AS arm, st.n AS units, round(st.total, 2) AS total_usd,
       round(st.mean40, 2) AS mean_usd, st.n - 1 AS df, round(t.t, 6) AS t_quantile,
       round(st.mean40 - t.t * sqrt(round(st.var / st.n, 40)), 2) AS interval_low, round(st.mean40 + t.t * sqrt(round(st.var / st.n, 40)), 2) AS interval_high
FROM st LEFT JOIN t_critical_975 t ON t.df = st.n - 1 AND (SELECT confidence FROM pl) = '0.95' ORDER BY st.c, st.variant COLLATE "C";

-- @@ revenue_difference
WITH pl AS (SELECT (plan->'revenue_window'->>'from')::timestamptz AS rev_from, (plan->'revenue_window'->>'to')::timestamptz AS rev_to, plan->>'confidence' AS confidence
            FROM analysis_plans WHERE experiment_version_id = 'xv-001'),
reads AS (SELECT c, label FROM ps_cuts WHERE label IN ('an-001', 'an-002', 'an-003', 'an-004', 'as-of')),
asg AS (
    SELECT r.c, r.label, a.variant,
           coalesce((SELECT sum(s.amount_usd) FROM subscriptions s WHERE s.account_id = a.unit_id AND s.status IN ('active', 'ended') AND s.starts_at >= pl.rev_from
                     AND s.starts_at < pl.rev_to AND s.starts_at <= r.c), 0) AS revenue
    FROM reads r CROSS JOIN pl JOIN assignments a ON a.experiment_version_id = 'xv-001' AND a.assigned_at <= r.c JOIN ps_signup sg ON sg.c = r.c AND sg.acct = a.unit_id
    WHERE sg.at + make_interval(hours => 168) <= r.c
),
mean AS (SELECT c, label, variant, count(*) AS n, sum(revenue) / count(*) AS m FROM asg GROUP BY c, label, variant),
st AS (
    SELECT m.c, m.label, m.variant, m.n, round(m.m, 40) AS m40, (SELECT sum((b.revenue - round(m.m, 40)) ^ 2) FROM asg b WHERE b.c = m.c AND b.variant = m.variant) / (m.n - 1) AS var
    FROM mean m
),
w AS (
    SELECT t.c, t.label, t.m40 - ct.m40 AS diff, t.var / t.n AS a, ct.var / ct.n AS b, t.n AS n_t, ct.n AS n_c
    FROM st t JOIN st ct ON ct.c = t.c AND ct.variant = 'control' WHERE t.variant = 'treatment'
),
d AS (SELECT w.*, floor((w.a + w.b) ^ 2 / (w.a ^ 2 / (w.n_t - 1) + w.b ^ 2 / (w.n_c - 1)))::int AS df FROM w)
SELECT d.label AS run, to_char(d.c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_at, round(d.diff, 2) AS difference_usd, d.df AS welch_df, round(t.t, 6) AS t_quantile,
       round(d.diff - t.t * sqrt(round(d.a + d.b, 40)), 2) AS interval_low, round(d.diff + t.t * sqrt(round(d.a + d.b, 40)), 2) AS interval_high,
       (d.diff - t.t * sqrt(round(d.a + d.b, 40)) <= 0 AND d.diff + t.t * sqrt(round(d.a + d.b, 40)) >= 0) AS interval_includes_zero
FROM d LEFT JOIN t_critical_975 t ON t.df = d.df ORDER BY d.c;

-- @@ week4_by_arm
-- Week-4 retention of v1 at the as-of (intention to treat; local day 35 has begun; sessions of bots and internal accounts ignored): DR-02, the treatment does not lift week-4 retention.
-- Difference = treatment minus control with the Newcombe interval at the plan's z.
WITH pl AS (SELECT (plan->>'z')::numeric AS z FROM analysis_plans WHERE experiment_version_id = 'xv-001'),
sess AS (
    SELECT u.account_id AS acct, (s.started_at AT TIME ZONE a.timezone)::date AS d FROM sessions s JOIN users u ON u.user_id = s.user_id JOIN accounts a ON a.account_id = u.account_id
    WHERE NOT u.bot_flag AND NOT a.internal AND s.started_at < '2026-10-05T00:00:00Z'::timestamptz
),
asg AS (
    SELECT a.variant, (sg.at AT TIME ZONE ac.timezone)::date AS d0, ('2026-10-05T00:00:00Z'::timestamptz AT TIME ZONE ac.timezone)::date AS dc, a.unit_id
    FROM assignments a JOIN ps_signup sg ON sg.c = '2026-10-05T00:00:00Z' AND sg.acct = a.unit_id JOIN accounts ac ON ac.account_id = a.unit_id
    WHERE a.experiment_version_id = 'xv-001' AND a.assigned_at <= '2026-10-05T00:00:00Z'
),
flags AS (
    SELECT variant, (d0 + 35 <= dc) AS m35, EXISTS (SELECT 1 FROM sess WHERE sess.acct = asg.unit_id AND sess.d - asg.d0 BETWEEN 28 AND 34) AS w4 FROM asg
),
cnt AS (
    SELECT count(*) FILTER (WHERE variant = 'control' AND m35) AS n_c, count(*) FILTER (WHERE variant = 'treatment' AND m35) AS n_t,
           count(*) FILTER (WHERE variant = 'control' AND m35 AND w4) AS x_c, count(*) FILTER (WHERE variant = 'treatment' AND m35 AND w4) AS x_t FROM flags
),
wil AS (
    SELECT cnt.*, pl.z, x_c::numeric / n_c AS pr_c, x_t::numeric / n_t AS pr_t,
           (x_c::numeric / n_c + pl.z ^ 2 / (2 * n_c) - pl.z * sqrt(round((x_c::numeric / n_c) * (1 - x_c::numeric / n_c) / n_c + pl.z ^ 2 / (4 * n_c::numeric * n_c), 40))) / (1 + pl.z ^ 2 / n_c) AS lo_c,
           (x_c::numeric / n_c + pl.z ^ 2 / (2 * n_c) + pl.z * sqrt(round((x_c::numeric / n_c) * (1 - x_c::numeric / n_c) / n_c + pl.z ^ 2 / (4 * n_c::numeric * n_c), 40))) / (1 + pl.z ^ 2 / n_c) AS hi_c,
           (x_t::numeric / n_t + pl.z ^ 2 / (2 * n_t) - pl.z * sqrt(round((x_t::numeric / n_t) * (1 - x_t::numeric / n_t) / n_t + pl.z ^ 2 / (4 * n_t::numeric * n_t), 40))) / (1 + pl.z ^ 2 / n_t) AS lo_t,
           (x_t::numeric / n_t + pl.z ^ 2 / (2 * n_t) + pl.z * sqrt(round((x_t::numeric / n_t) * (1 - x_t::numeric / n_t) / n_t + pl.z ^ 2 / (4 * n_t::numeric * n_t), 40))) / (1 + pl.z ^ 2 / n_t) AS hi_t
    FROM cnt, pl
)
SELECT n_c AS mature_control, n_t AS mature_treatment, x_c AS retained_control, x_t AS retained_treatment, round(pr_c, 6) AS rate_control, round(pr_t, 6) AS rate_treatment,
       round((pr_t - pr_c) * 100, 2) AS difference_pp,
       round((pr_t - pr_c) - sqrt(round((pr_t - lo_t) ^ 2 + (hi_c - pr_c) ^ 2, 40)), 6) AS newcombe_low, round((pr_t - pr_c) + sqrt(round((hi_t - pr_t) ^ 2 + (pr_c - lo_c) ^ 2, 40)), 6) AS newcombe_high,
       ((pr_t - pr_c) - sqrt(round((pr_t - lo_t) ^ 2 + (hi_c - pr_c) ^ 2, 40)) <= 0 AND (pr_t - pr_c) + sqrt(round((hi_t - pr_t) ^ 2 + (pr_c - lo_c) ^ 2, 40)) >= 0) AS interval_includes_zero
FROM wil;
