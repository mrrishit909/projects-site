-- 05_experiment_v1_at_each_run_cutoff.sql: the onboarding experiment v1 (xv-001) read at each of its four logged runs and at the as-of (P06-ART-04, P06-MET-07..10, D-03, D-08, D-10).
-- Question: what did the run of 2026-05-18, 2026-06-15, 2026-07-13 and 2026-08-02 (planned_end) see, and does the final read stand?
-- Needs 00_canonical_events.sql (ps_ev, ps_signup). THE CUTOFF RULE (D-08): a run at cutoff C sees only the facts that existed by C: assignments with assigned_at <= C,
-- exposures with exposed_at <= C, events received by C (ps_ev at C). The unit is the ACCOUNT; analysis is intention to treat: every assigned MATURE account counts in its
-- assigned arm, exposed or not (exposure is reported beside it). MATURE = signup + 7 x 24 h <= C; an account that is not mature is counted apart and is in no rate.
-- ACTIVATED (D-10, R6-09) = an analysed `activated` event in [max(signup, assigned_at), signup + 7 x 24 h): an activation before the assignment is not a treatment effect.
-- Intervals (z = 1.959964 from the frozen plan): Wilson per arm; Newcombe hybrid score for treatment minus control, square roots at 40 decimals, rounded once, half up.
-- SRM: chi-square of the assignment counts against the plan's allocation (df 1), p = erfc(sqrt(stat / 2)) by the Maclaurin series of erf in NUMERIC (as the reference SQL).
-- CONCLUSIVE (D-10) = the Newcombe interval excludes 0 AND a final run (C >= planned_end) AND a valid plan hash AND the plan frozen at or before the first logged run of the
-- version AND an SRM verdict OK. All intervals added to timestamps are hour-based (24 h per day), so the result is independent of the session TimeZone (R6-03).
-- The five reads: the four v1 runs (an-001..an-004) and the as-of 2026-10-05T00:00:00Z (no run was logged there: prior_runs is empty).

-- @@ arms_by_cutoff
WITH pl AS (SELECT plan AS j, (plan->>'z')::numeric AS z, (plan->>'planned_end')::timestamptz AS planned_end FROM analysis_plans WHERE experiment_version_id = 'xv-001'),
reads AS (
    SELECT c, label FROM ps_cuts WHERE label IN ('an-001', 'an-002', 'an-003', 'an-004', 'as-of')
),
asg AS (
    SELECT r.c, r.label, a.assignment_id, a.variant,
           (sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= r.c) AS mature,
           (sg.at IS NOT NULL AND EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = r.c AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = a.unit_id
                                          AND e.at >= greatest(sg.at, a.assigned_at) AND e.at < sg.at + make_interval(hours => 168))) AS activated,
           EXISTS (SELECT 1 FROM exposures x WHERE x.assignment_id = a.assignment_id AND x.exposed_at <= r.c) AS exposed
    FROM reads r JOIN assignments a ON a.experiment_version_id = 'xv-001' AND a.assigned_at <= r.c
         LEFT JOIN ps_signup sg ON sg.c = r.c AND sg.acct = a.unit_id
),
agg AS (
    SELECT c, label, variant, count(*) AS assigned, count(*) FILTER (WHERE mature) AS mature, count(*) FILTER (WHERE mature AND activated) AS activated,
           count(*) FILTER (WHERE mature AND exposed) AS exposed
    FROM asg GROUP BY c, label, variant
)
SELECT a.label AS run, to_char(a.c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_at, a.variant AS arm, a.assigned, a.assigned - a.mature AS immature_or_unobserved,
       a.mature, a.activated,
       CASE WHEN a.mature > 0 THEN round(a.activated::numeric / a.mature, 6) END AS conversion,
       CASE WHEN a.mature > 0 THEN round((a.activated::numeric / a.mature + pl.z ^ 2 / (2 * a.mature)
            - pl.z * sqrt(round((a.activated::numeric / a.mature) * (1 - a.activated::numeric / a.mature) / a.mature + pl.z ^ 2 / (4 * a.mature::numeric * a.mature), 40)))
            / (1 + pl.z ^ 2 / a.mature), 6) END AS wilson_low,
       CASE WHEN a.mature > 0 THEN round((a.activated::numeric / a.mature + pl.z ^ 2 / (2 * a.mature)
            + pl.z * sqrt(round((a.activated::numeric / a.mature) * (1 - a.activated::numeric / a.mature) / a.mature + pl.z ^ 2 / (4 * a.mature::numeric * a.mature), 40)))
            / (1 + pl.z ^ 2 / a.mature), 6) END AS wilson_high,
       a.exposed, CASE WHEN a.mature > 0 THEN round(a.exposed::numeric / a.mature, 6) END AS exposure_rate
FROM agg a, pl ORDER BY a.c, a.variant COLLATE "C";

-- @@ lift_by_cutoff
WITH RECURSIVE pl AS (SELECT plan AS j, config_hash, (plan->>'z')::numeric AS z, (plan->>'planned_end')::timestamptz AS planned_end, (plan->>'frozen_at')::timestamptz AS frozen_at,
                   (plan->'srm'->>'p_threshold')::numeric AS p_threshold, (plan->'srm'->>'min_expected_cell')::numeric AS min_cell,
                   (plan->'allocation'->>'control')::numeric AS share_c, (plan->'allocation'->>'treatment')::numeric AS share_t,
                   encode(sha256(convert_to(ps_canonical_json(plan), 'UTF8')), 'hex') = config_hash AS hash_ok
            FROM analysis_plans WHERE experiment_version_id = 'xv-001'),
runs AS (SELECT * FROM analysis_runs WHERE experiment_version_id = 'xv-001'),
reads AS (SELECT c, label FROM ps_cuts WHERE label IN ('an-001', 'an-002', 'an-003', 'an-004', 'as-of')),
asg AS (
    SELECT r.c, r.label, a.variant,
           (sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= r.c) AS mature,
           (sg.at IS NOT NULL AND EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = r.c AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = a.unit_id
                                          AND e.at >= greatest(sg.at, a.assigned_at) AND e.at < sg.at + make_interval(hours => 168))) AS activated
    FROM reads r JOIN assignments a ON a.experiment_version_id = 'xv-001' AND a.assigned_at <= r.c
         LEFT JOIN ps_signup sg ON sg.c = r.c AND sg.acct = a.unit_id
),
cnt AS (
    SELECT r.c, r.label,
           count(*) FILTER (WHERE a.variant = 'control') AS asg_c, count(*) FILTER (WHERE a.variant = 'treatment') AS asg_t,
           count(*) FILTER (WHERE a.variant = 'control' AND a.mature) AS n_c, count(*) FILTER (WHERE a.variant = 'treatment' AND a.mature) AS n_t,
           count(*) FILTER (WHERE a.variant = 'control' AND a.mature AND a.activated) AS x_c, count(*) FILTER (WHERE a.variant = 'treatment' AND a.mature AND a.activated) AS x_t
    FROM reads r LEFT JOIN asg a ON a.c = r.c GROUP BY r.c, r.label
),
chi AS (
    SELECT cnt.*, pl.z, pl.share_c, pl.share_t, pl.p_threshold, pl.min_cell, pl.planned_end, pl.hash_ok, pl.frozen_at,
           (asg_c + asg_t) AS n_all,
           ((asg_c - (asg_c + asg_t) * pl.share_c) ^ 2 / ((asg_c + asg_t) * pl.share_c) + (asg_t - (asg_c + asg_t) * pl.share_t) ^ 2 / ((asg_c + asg_t) * pl.share_t)) AS stat
    FROM cnt, pl
),
erf_in AS (SELECT c, CASE WHEN stat > 0 AND stat <= 100 THEN sqrt(round(stat / 2, 90)) END AS x FROM chi),
erf_series (c, n, term, s, x) AS (
    SELECT c, 0, round(x, 90), 0::numeric, round(x, 90) FROM erf_in WHERE x IS NOT NULL
  UNION ALL
    SELECT c, n + 1, round(-term * x * x / (n + 1), 90), s + round(term / (2 * n + 1), 90), x FROM erf_series WHERE abs(term) > 1e-70
),
pval AS (
    SELECT chi.c, CASE WHEN chi.stat <= 0 THEN 1::numeric WHEN chi.stat > 100 THEN 0::numeric
                       ELSE 1 - 2 * (SELECT s FROM erf_series e WHERE e.c = chi.c ORDER BY n DESC LIMIT 1)
                                 / sqrt(3.14159265358979323846264338327950288419716939937510582097494459230781640628620899862803482534211706798::numeric(110,100)) END AS p
    FROM chi
),
wil AS (
    SELECT chi.*, pval.p,
           x_c::numeric / n_c AS pr_c, x_t::numeric / n_t AS pr_t,
           (x_c::numeric / n_c + z ^ 2 / (2 * n_c) - z * sqrt(round((x_c::numeric / n_c) * (1 - x_c::numeric / n_c) / n_c + z ^ 2 / (4 * n_c::numeric * n_c), 40))) / (1 + z ^ 2 / n_c) AS lo_c,
           (x_c::numeric / n_c + z ^ 2 / (2 * n_c) + z * sqrt(round((x_c::numeric / n_c) * (1 - x_c::numeric / n_c) / n_c + z ^ 2 / (4 * n_c::numeric * n_c), 40))) / (1 + z ^ 2 / n_c) AS hi_c,
           (x_t::numeric / n_t + z ^ 2 / (2 * n_t) - z * sqrt(round((x_t::numeric / n_t) * (1 - x_t::numeric / n_t) / n_t + z ^ 2 / (4 * n_t::numeric * n_t), 40))) / (1 + z ^ 2 / n_t) AS lo_t,
           (x_t::numeric / n_t + z ^ 2 / (2 * n_t) + z * sqrt(round((x_t::numeric / n_t) * (1 - x_t::numeric / n_t) / n_t + z ^ 2 / (4 * n_t::numeric * n_t), 40))) / (1 + z ^ 2 / n_t) AS hi_t
    FROM chi JOIN pval ON pval.c = chi.c WHERE n_c > 0 AND n_t > 0
),
nc AS (
    SELECT w.*, (pr_t - pr_c) AS d,
           (pr_t - pr_c) - sqrt(round((pr_t - lo_t) ^ 2 + (hi_c - pr_c) ^ 2, 40)) AS lo,
           (pr_t - pr_c) + sqrt(round((hi_t - pr_t) ^ 2 + (pr_c - lo_c) ^ 2, 40)) AS hi,
           CASE WHEN w.min_cell > (asg_c + asg_t) * LEAST(share_c, share_t) THEN 'INSUFFICIENT' WHEN w.p < w.p_threshold THEN 'MISMATCH' ELSE 'OK' END AS srm_verdict
    FROM wil w
),
fin AS (
    SELECT nc.*, rn.analysis_id, rn.created_at,
           CASE WHEN rn.analysis_id IS NULL THEN NULL ELSE (SELECT count(*) FROM runs r2 WHERE r2.created_at < rn.created_at) END AS prior_runs,
           (SELECT count(*) FROM runs) > 0 AND nc.frozen_at <= (SELECT min(created_at) FROM runs) AS plan_frozen
    FROM nc LEFT JOIN runs rn ON rn.cutoff_at = nc.c
)
SELECT f.label AS run, to_char(f.c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_at, (f.c < f.planned_end) AS interim, f.prior_runs,
       f.asg_c AS assigned_control, f.asg_t AS assigned_treatment, f.n_c AS mature_control, f.n_t AS mature_treatment, f.x_c AS activated_control, f.x_t AS activated_treatment,
       round(f.pr_c, 6) AS conversion_control, round(f.pr_t, 6) AS conversion_treatment, round(f.d * 100, 2) AS absolute_lift_pp,
       CASE WHEN f.pr_c > 0 THEN round(f.d / f.pr_c, 6) END AS relative_lift, round(f.lo, 6) AS newcombe_low, round(f.hi, 6) AS newcombe_high,
       (f.lo <= 0 AND f.hi >= 0) AS interval_includes_zero,
       round(f.stat, 6) AS srm_statistic, round(f.p, 6) AS srm_p_value, f.srm_verdict, f.hash_ok AS plan_hash_valid, f.plan_frozen,
       (NOT (f.lo <= 0 AND f.hi >= 0) AND NOT (f.c < f.planned_end) AND f.hash_ok AND f.plan_frozen AND f.srm_verdict = 'OK') AS conclusive
FROM fin f ORDER BY f.c;

-- @@ gap_accounts
-- INJ-10 / R6-08 (P06-TEST-10): `activated` was not instrumented for signups before 2026-04-08 (both arms alike). It reaches the v1 accounts that are mature at
-- the as-of: they count as not activated in the published figures. The SQL can see WHO is inside the gap (signup before 2026-04-08), not what they would have
-- done: the DRAWN activations of those accounts live only in the generator's manifest (a constructed fact, not an observation). run_all.py reconciles this block
-- to the manifest's disclosure: published +9.50 pp, drawn +11.50 pp, +9.96 pp with the gap accounts excluded from both arms.
WITH asg AS (
    SELECT a.variant, sg.at AS signup_at,
           EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = a.unit_id
                   AND e.at >= greatest(sg.at, a.assigned_at) AND e.at < sg.at + make_interval(hours => 168)) AS activated
    FROM assignments a JOIN ps_signup sg ON sg.c = '2026-10-05T00:00:00Z' AND sg.acct = a.unit_id
    WHERE a.experiment_version_id = 'xv-001' AND a.assigned_at <= '2026-10-05T00:00:00Z' AND sg.at + make_interval(hours => 168) <= '2026-10-05T00:00:00Z'::timestamptz
),
g AS (
    SELECT variant, count(*) AS mature, count(*) FILTER (WHERE activated) AS activated,
           count(*) FILTER (WHERE signup_at < '2026-04-08T00:00:00Z') AS gap_accounts,
           count(*) FILTER (WHERE signup_at < '2026-04-08T00:00:00Z' AND activated) AS gap_published_activations,
           count(*) FILTER (WHERE signup_at >= '2026-04-08T00:00:00Z') AS mature_excluding_gap,
           count(*) FILTER (WHERE signup_at >= '2026-04-08T00:00:00Z' AND activated) AS activated_excluding_gap
    FROM asg GROUP BY variant
)
SELECT variant AS arm, mature, activated, round(activated::numeric / mature, 6) AS published_conversion, gap_accounts, gap_published_activations, mature_excluding_gap,
       activated_excluding_gap, round(activated_excluding_gap::numeric / mature_excluding_gap, 6) AS conversion_excluding_gap
FROM g ORDER BY variant COLLATE "C";

-- @@ gap_lift
-- The three figures side by side. `published` and `excluding_gap` are computed here from the facts; `drawn` (+11.50 pp) is the generator's manifest value (the published
-- treatment count 82 plus the 4 drawn-but-suppressed activations = 86 of 200 against 63 of 200) and is read from the manifest by run_all.py, not from this database.
WITH asg AS (
    SELECT a.variant, sg.at AS signup_at,
           EXISTS (SELECT 1 FROM ps_ev e WHERE e.c = '2026-10-05T00:00:00Z' AND e.cls = 'analysed' AND e.name = 'activated' AND e.acct = a.unit_id
                   AND e.at >= greatest(sg.at, a.assigned_at) AND e.at < sg.at + make_interval(hours => 168)) AS activated
    FROM assignments a JOIN ps_signup sg ON sg.c = '2026-10-05T00:00:00Z' AND sg.acct = a.unit_id
    WHERE a.experiment_version_id = 'xv-001' AND a.assigned_at <= '2026-10-05T00:00:00Z' AND sg.at + make_interval(hours => 168) <= '2026-10-05T00:00:00Z'::timestamptz
),
f AS (
    SELECT 'published (all mature accounts)' AS reading, 1 AS ord,
           count(*) FILTER (WHERE variant = 'control') AS n_c, count(*) FILTER (WHERE variant = 'control' AND activated) AS x_c,
           count(*) FILTER (WHERE variant = 'treatment') AS n_t, count(*) FILTER (WHERE variant = 'treatment' AND activated) AS x_t FROM asg
    UNION ALL
    SELECT 'excluding the gap accounts from both arms', 2,
           count(*) FILTER (WHERE variant = 'control' AND signup_at >= '2026-04-08T00:00:00Z'), count(*) FILTER (WHERE variant = 'control' AND signup_at >= '2026-04-08T00:00:00Z' AND activated),
           count(*) FILTER (WHERE variant = 'treatment' AND signup_at >= '2026-04-08T00:00:00Z'), count(*) FILTER (WHERE variant = 'treatment' AND signup_at >= '2026-04-08T00:00:00Z' AND activated)
    FROM asg
)
SELECT reading, n_c AS mature_control, x_c AS activated_control, n_t AS mature_treatment, x_t AS activated_treatment,
       round(x_c::numeric / n_c, 6) AS conversion_control, round(x_t::numeric / n_t, 6) AS conversion_treatment,
       round((x_t::numeric / n_t - x_c::numeric / n_c) * 100, 2) AS absolute_lift_pp
FROM f ORDER BY ord;
