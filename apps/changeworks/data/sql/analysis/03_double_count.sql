-- P09-ART-04 investigation 03: the double-count residual and the hours residual by shared source key (D-01, D-09 R9-02, R9-03, DR-02, INJ-02).
-- Question: where do two initiatives claim the same benefit, and by how much would a plain sum overstate the portfolio? Claims that share a benefit_source_key in one period across two or more
-- initiatives count once, at the largest claim (a tie goes to the claim that enters the cash flow, then to the smaller initiative and benefit id); the rest is the residual. Money (USD) and hours are two
-- separate rules and are never added. The residual's present value (the part that enters the cash flow, each claim at its own period's discount factor) is what the attributable NPV gives back.
-- Scope: scn-025 for the key and period detail; every scenario for the outcome. A residual other than 0.00 must be explained before a scenario can be proposed (C07, DOUBLE_COUNT_UNEXPLAINED).

-- @@ by_source_key
SELECT u.* FROM (
SELECT 'money (USD)' AS rule, c.benefit_source_key, count(DISTINCT c.period_index) AS overlapping_periods, min(c.period_index) AS first_period, max(c.period_index) AS last_period,
       (SELECT string_agg(z.i, ',' ORDER BY z.i COLLATE "C") FROM (SELECT DISTINCT x.initiative_id AS i FROM cw_claim x
        WHERE x.scenario_id = 'scn-025' AND x.benefit_source_key = c.benefit_source_key AND x.initiatives_in_key >= 2) z) AS initiatives,
       round(sum(c.claim), 2) AS claimed, round(sum(c.claim) FILTER (WHERE c.rn = 1), 2) AS counted_once, round(sum(c.claim) FILTER (WHERE c.rn > 1), 2) AS residual
FROM cw_claim c WHERE c.scenario_id = 'scn-025' AND c.initiatives_in_key >= 2
GROUP BY c.benefit_source_key
UNION ALL
SELECT 'hours', h.benefit_source_key, count(DISTINCT h.period_index), min(h.period_index), max(h.period_index),
       (SELECT string_agg(z.i, ',' ORDER BY z.i COLLATE "C") FROM (SELECT DISTINCT x.initiative_id AS i FROM cw_hours x
        WHERE x.scenario_id = 'scn-025' AND x.benefit_source_key = h.benefit_source_key AND x.initiatives_in_key >= 2) z),
       round(sum(h.hours), 2), round(sum(h.hours) FILTER (WHERE h.rn = 1), 2), round(sum(h.hours) FILTER (WHERE h.rn > 1), 2)
FROM cw_hours h WHERE h.scenario_id = 'scn-025' AND h.initiatives_in_key >= 2
GROUP BY h.benefit_source_key) u
ORDER BY (u.rule = 'hours'), u.benefit_source_key COLLATE "C"

-- @@ by_period
SELECT c.benefit_source_key, c.period_index,
       string_agg(c.initiative_id || ':' || c.benefit_id, ' + ' ORDER BY c.initiative_id COLLATE "C", c.benefit_id COLLATE "C") AS claims,
       round(sum(c.claim), 2) AS money_claimed, round(sum(c.claim) FILTER (WHERE c.rn = 1), 2) AS money_counted_once, round(sum(c.claim) FILTER (WHERE c.rn > 1), 2) AS money_residual,
       round(h.claimed, 2) AS hours_claimed, round(h.once, 2) AS hours_counted_once, round(h.claimed - h.once, 2) AS hours_residual
FROM cw_claim c
JOIN (SELECT benefit_source_key, period_index, sum(hours) AS claimed, sum(hours) FILTER (WHERE rn = 1) AS once FROM cw_hours WHERE scenario_id = 'scn-025' GROUP BY benefit_source_key, period_index) h
  ON h.benefit_source_key = c.benefit_source_key AND h.period_index = c.period_index
WHERE c.scenario_id = 'scn-025' AND c.initiatives_in_key >= 2
GROUP BY c.benefit_source_key, c.period_index, h.claimed, h.once
ORDER BY c.benefit_source_key COLLATE "C", c.period_index

-- @@ present_value_scn025
-- The residual in dollars, and what it is worth today inside the NPV: the attributable NPV is the plain sum of the initiative NPVs less double_counted_pv.
SELECT d.scenario_id, round(d.removed, 2) AS double_counted_amount, round(d.pv_num / d.pv_den, 2) AS double_counted_pv, round(n.sum_num / n.den, 2) AS npv_sum_of_initiatives,
       round((n.sum_num - n.pv_num) / n.den, 2) AS npv_attributable,
       round(d.planned, 2) AS planned_benefits, round(d.planned - d.removed, 2) AS attributable_benefits,
       round(d.hours_planned, 2) AS planned_hours, round(d.hours_planned - d.hours_removed, 2) AS attributable_hours, round(d.hours_removed, 2) AS hours_residual
FROM cw_dc d JOIN cw_scn_npv n ON n.scenario_id = d.scenario_id WHERE d.scenario_id = 'scn-025'

-- @@ by_scenario
SELECT d.scenario_id, round(d.removed, 2) AS residual, round(d.hours_removed, 2) AS hours_residual, round(d.pv_num / d.pv_den, 2) AS double_counted_pv,
       (d.removed <> 0 OR d.hours_removed <> 0) AS explanation_required,
       CASE WHEN d.removed <> 0 AND d.hours_removed <> 0 THEN 'money,hours' WHEN d.removed <> 0 THEN 'money' WHEN d.hours_removed <> 0 THEN 'hours' ELSE '' END AS explanation_required_for
FROM cw_dc d
ORDER BY d.scenario_id COLLATE "C"

-- @@ outcome
SELECT count(*) FILTER (WHERE d.removed <> 0) AS scenarios_with_a_money_residual, count(*) FILTER (WHERE d.removed = 0) AS scenarios_with_no_money_residual,
       count(*) FILTER (WHERE d.hours_removed <> 0) AS scenarios_with_an_hours_residual,
       string_agg(d.scenario_id, ',' ORDER BY d.scenario_id COLLATE "C") FILTER (WHERE d.removed <> 0) AS money_residual_scenarios,
       string_agg(d.scenario_id, ',' ORDER BY d.scenario_id COLLATE "C") FILTER (WHERE d.hours_removed <> 0) AS hours_residual_scenarios
FROM cw_dc d
