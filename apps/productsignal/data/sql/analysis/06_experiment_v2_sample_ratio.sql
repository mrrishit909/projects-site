-- 06_experiment_v2_sample_ratio.sql: the sample ratio of experiment v2 (xv-002) beside v1's, checked before any lift (P06-ART-04, P06-MET-10, D-03, P06-TEST-08, P06-DOMAIN-04).
-- Question: do the assignments follow the allocation the plan froze, and what does that allow us to say about v2?
-- Needs 00_canonical_events.sql (ps_signup, for maturity only). v1 was planned 0.50 / 0.50 and v2 (the re-plan after v1) 0.60 / 0.40. SRM = chi-square goodness of fit
-- of the observed assignment counts (assigned_at <= the cutoff, D-08) against n x allocation, df 1; p = erfc(sqrt(stat / 2)) by the Maclaurin series of erf in NUMERIC at
-- 90 decimals (as the reference SQL). Verdict order: INSUFFICIENT (an expected cell below the plan's minimum of 5), MISMATCH (p below the plan's 0.001), OK. A MISMATCH is
-- shown BEFORE any lift and blocks both ship and stop (D-06); this file therefore reports v2's COUNTS and never a v2 activation figure.
-- CONSTRUCTED: v2's mismatch is a designed defect (INJ-08, DR-06): its randomiser sends 3 of every 5 accounts to treatment while the plan says 0.40. The mismatch is a
-- property of the generator, not a finding about a real randomiser; v1 passes by construction too (permuted blocks of four, chosen after seeing a fair-coin draw gave
-- 223 / 177, p 0.021: one of the four outcome-informed choices disclosed in the manifest).

-- @@ srm_by_read
WITH RECURSIVE reads (xv, c, label) AS (
    SELECT 'xv-001', c, label FROM ps_cuts WHERE label IN ('an-001', 'an-002', 'an-003', 'an-004', 'as-of')
  UNION ALL
    SELECT 'xv-002', c, label FROM ps_cuts WHERE label IN ('an-005', 'as-of')
),
pl AS (SELECT experiment_version_id AS xv, (plan->'allocation'->>'control')::numeric AS share_c, (plan->'allocation'->>'treatment')::numeric AS share_t,
              (plan->'srm'->>'p_threshold')::numeric AS p_threshold, (plan->'srm'->>'min_expected_cell')::numeric AS min_cell FROM analysis_plans),
cnt AS (
    SELECT r.xv, r.c, r.label, pl.share_c, pl.share_t, pl.p_threshold, pl.min_cell,
           count(*) FILTER (WHERE a.variant = 'control') AS n_c, count(*) FILTER (WHERE a.variant = 'treatment') AS n_t
    FROM reads r JOIN pl ON pl.xv = r.xv LEFT JOIN assignments a ON a.experiment_version_id = r.xv AND a.assigned_at <= r.c GROUP BY r.xv, r.c, r.label, pl.share_c, pl.share_t, pl.p_threshold, pl.min_cell
),
chi AS (
    SELECT cnt.*, (n_c + n_t) AS n,
           ((n_c - (n_c + n_t) * share_c) ^ 2 / ((n_c + n_t) * share_c) + (n_t - (n_c + n_t) * share_t) ^ 2 / ((n_c + n_t) * share_t)) AS stat
    FROM cnt WHERE n_c + n_t > 0
),
erf_in AS (SELECT xv, c, CASE WHEN stat > 0 AND stat <= 100 THEN sqrt(round(stat / 2, 90)) END AS x FROM chi),
erf_series (xv, c, n, term, s, x) AS (
    SELECT xv, c, 0, round(x, 90), 0::numeric, round(x, 90) FROM erf_in WHERE x IS NOT NULL
  UNION ALL
    SELECT xv, c, n + 1, round(-term * x * x / (n + 1), 90), s + round(term / (2 * n + 1), 90), x FROM erf_series WHERE abs(term) > 1e-70
),
pval AS (
    SELECT chi.xv, chi.c, CASE WHEN chi.stat <= 0 THEN 1::numeric WHEN chi.stat > 100 THEN 0::numeric
                               ELSE 1 - 2 * (SELECT s FROM erf_series e WHERE e.xv = chi.xv AND e.c = chi.c ORDER BY n DESC LIMIT 1)
                                         / sqrt(3.14159265358979323846264338327950288419716939937510582097494459230781640628620899862803482534211706798::numeric(110,100)) END AS p
    FROM chi
)
SELECT chi.xv AS experiment_version, chi.label AS run, to_char(chi.c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS cutoff_at,
       chi.share_c AS planned_control, chi.share_t AS planned_treatment, chi.n_c AS observed_control, chi.n_t AS observed_treatment,
       round(chi.n * chi.share_c, 2) AS expected_control, round(chi.n * chi.share_t, 2) AS expected_treatment,
       round(chi.n_t::numeric / chi.n, 6) AS treatment_share, round(chi.stat, 6) AS statistic, round(pv.p, 6) AS p_value, 1 AS df,
       CASE WHEN chi.min_cell > chi.n * LEAST(chi.share_c, chi.share_t) THEN 'INSUFFICIENT' WHEN pv.p < chi.p_threshold THEN 'MISMATCH' ELSE 'OK' END AS verdict
FROM chi JOIN pval pv ON pv.xv = chi.xv AND pv.c = chi.c ORDER BY chi.xv, chi.c;

-- @@ v2_assignment_by_week
-- v2's assignments by the UTC week of assigned_at: the surplus of treatment is there in every week of enrolment (2026-08-05 to 2026-09-30), not a burst.
SELECT to_char(date_trunc('week', a.assigned_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD') AS week_start,
       count(*) FILTER (WHERE a.variant = 'control') AS control, count(*) FILTER (WHERE a.variant = 'treatment') AS treatment, count(*) AS assigned,
       round(count(*) FILTER (WHERE a.variant = 'treatment')::numeric / count(*), 6) AS treatment_share
FROM assignments a WHERE a.experiment_version_id = 'xv-002' GROUP BY date_trunc('week', a.assigned_at AT TIME ZONE 'UTC') ORDER BY 1;

-- @@ v2_population
-- What v2 has at the as-of 2026-10-05, in counts only (no outcome is shown for an experiment whose sample ratio is a MISMATCH): assigned, mature (signup + 7 x 24 h <= the as-of),
-- the accounts still immature (INJ-04's v2 share: 10) and exposures recorded by then, per arm.
SELECT a.variant AS arm, count(*) AS assigned,
       count(*) FILTER (WHERE sg.at IS NOT NULL AND sg.at + make_interval(hours => 168) <= '2026-10-05T00:00:00Z'::timestamptz) AS mature,
       count(*) FILTER (WHERE sg.at IS NULL OR sg.at + make_interval(hours => 168) > '2026-10-05T00:00:00Z'::timestamptz) AS immature_or_unobserved,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM exposures x WHERE x.assignment_id = a.assignment_id AND x.exposed_at <= '2026-10-05T00:00:00Z')) AS exposed
FROM assignments a LEFT JOIN ps_signup sg ON sg.c = '2026-10-05T00:00:00Z' AND sg.acct = a.unit_id
WHERE a.experiment_version_id = 'xv-002' AND a.assigned_at <= '2026-10-05T00:00:00Z' GROUP BY a.variant ORDER BY a.variant COLLATE "C";
