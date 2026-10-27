-- P09-ART-04 investigation 06: cost variance and benefit realisation on matured periods, with the baseline trend beside the raw change (D-02, D-05 D-P9-05, D-P9-12, D-09 R9-11, R9-13, DR-06, INJ-10).
-- Question: how are the initiatives doing against plan, and how much of an observed improvement can be read as the initiative's? A period is matured when its end (the start of the next one) is on or
-- before the as-of 2026-10-05, so periods 0..8 are matured (September ends on 2026-10-01) and period 9 is not. Cost variance = actual cost minus the approved baseline's planned cost over the matured window
-- [0, min(horizon, 9)); null when there is no approved baseline, no matured period or no actuals. Benefit realisation = observed comparable / planned comparable within ONE benefit type, matured
-- periods with an observation only (an unobserved matured row is listed, never counted as 0). The recorded baseline trend (the sum of baseline_trend_per_period over the compared rows) is shown beside the raw observed
-- change, and the result is always "observed, not attributed". Scope: scn-025.

-- @@ matured
SELECT p.as_of, p.period_basis, p.matured AS matured_periods, p.matured - 1 AS last_matured_period, p.matured AS first_unmatured_period,
       (p.period_start + p.matured * CASE WHEN p.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::date AS first_unmatured_period_starts,
       (p.period_start + (p.matured + 1) * CASE WHEN p.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::date AS first_unmatured_period_ends
FROM cw_p p

-- @@ cost_variance_scn025
SELECT v.initiative_id, v.wend AS window_to_period, v.approved_version AS approved_baseline_version,
       CASE WHEN v.approved_version IS NOT NULL AND v.wend > 0 THEN round(coalesce(v.planned_cost, 0), 2) END AS approved_baseline_cost,
       CASE WHEN v.approved_version IS NOT NULL AND v.wend > 0 AND v.actual_rows > 0 THEN round(v.actual_cost, 2) END AS actual_cost,
       CASE WHEN v.approved_version IS NOT NULL AND v.wend > 0 AND v.actual_rows > 0 THEN round(v.actual_cost - coalesce(v.planned_cost, 0), 2) END AS variance,
       CASE WHEN v.approved_version IS NULL THEN 'NO_APPROVED_BASELINE' WHEN v.wend = 0 THEN 'NO_MATURED_PERIOD' WHEN v.actual_rows = 0 THEN 'NO_ACTUALS' END AS reason
FROM cw_var v WHERE v.scenario_id = 'scn-025'
ORDER BY v.initiative_id COLLATE "C"

-- @@ variance_summary_scn025
SELECT count(*) FILTER (WHERE v.approved_version IS NOT NULL AND v.actual_rows > 0) AS initiatives_with_a_variance,
       count(*) FILTER (WHERE v.approved_version IS NOT NULL AND v.actual_rows > 0 AND v.actual_cost > coalesce(v.planned_cost, 0)) AS over_baseline,
       count(*) FILTER (WHERE v.approved_version IS NOT NULL AND v.actual_rows > 0 AND v.actual_cost < coalesce(v.planned_cost, 0)) AS under_baseline,
       count(*) FILTER (WHERE v.approved_version IS NOT NULL AND v.actual_rows > 0 AND v.actual_cost = coalesce(v.planned_cost, 0)) AS on_baseline,
       count(*) FILTER (WHERE v.approved_version IS NULL OR v.actual_rows = 0) AS initiatives_with_no_variance,
       round(sum(v.actual_cost - coalesce(v.planned_cost, 0)) FILTER (WHERE v.approved_version IS NOT NULL AND v.actual_rows > 0), 2) AS net_variance
FROM cw_var v WHERE v.scenario_id = 'scn-025'

-- @@ realisation_scn025
SELECT r.initiative_id, r.benefit_type, CASE WHEN r.benefit_type = 'capacity' THEN 'hours' ELSE 'USD' END AS unit, r.compared AS compared_rows, r.unobserved AS matured_unobserved_rows,
       CASE WHEN r.compared > 0 THEN round(r.planned, 2) END AS planned_comparable, CASE WHEN r.compared > 0 THEN round(r.observed, 2) END AS observed_comparable,
       CASE WHEN r.compared > 0 AND r.planned <> 0 THEN round(r.observed / r.planned, 6) END AS realisation,
       CASE WHEN r.trend_rows > 0 THEN round(r.trend, 2) END AS baseline_trend,
       CASE WHEN r.trend_rows > 0 AND r.compared > 0 AND r.trend_rows = r.compared THEN round(r.observed - r.trend, 2) END AS observed_above_trend,
       CASE WHEN r.trend_rows > 0 AND r.compared > 0 AND r.observed <> 0 THEN round(r.trend / r.observed, 6) END AS trend_share_of_observed,
       'observed, not attributed' AS attribution
FROM cw_real r WHERE r.scenario_id = 'scn-025' AND (r.compared > 0 OR r.unobserved > 0)
ORDER BY r.initiative_id COLLATE "C", r.benefit_type COLLATE "C"

-- @@ trend_beside_raw
-- DR-06: the cash benefit of init-008 is close to plan, and most of the raw change is the trend recorded before deployment. The five cash comparisons with the largest trend share:
SELECT r.initiative_id, round(r.observed, 2) AS observed_comparable, round(r.trend, 2) AS baseline_trend, round(r.observed - r.trend, 2) AS observed_above_trend,
       round(r.trend / r.observed, 6) AS trend_share_of_observed, round(r.observed / r.planned, 6) AS realisation
FROM cw_real r WHERE r.scenario_id = 'scn-025' AND r.benefit_type = 'cash' AND r.compared > 0 AND r.trend_rows = r.compared AND r.observed <> 0 AND r.planned <> 0
ORDER BY r.trend / r.observed DESC, r.initiative_id COLLATE "C"
LIMIT 5

-- @@ coverage
-- R9-13: observed_above_trend is published only when every compared row carries a recorded trend; here every compared row does, so the warning PARTIAL_TREND_COVERAGE never fires.
SELECT count(*) AS comparisons, count(*) FILTER (WHERE r.trend_rows = r.compared) AS with_complete_trend_coverage, count(*) FILTER (WHERE r.trend_rows < r.compared) AS with_partial_trend_coverage,
       sum(r.compared) AS rows_compared, sum(r.unobserved) AS matured_rows_with_no_observation
FROM cw_real r WHERE r.scenario_id = 'scn-025' AND r.compared > 0
