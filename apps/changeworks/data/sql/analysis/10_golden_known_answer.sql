-- P09-ART-04 investigation 10: the golden known answer, NPV 5000/121 = 41.32 with both paybacks (D-01, P09-GOLD-01; run on the golden database loaded from tests/fixtures/golden/inputs.json).
-- The specification's own case: cost 1000 at period 0, net inflows 600 at periods 1 and 2, annual rate 10 % on annual periods (init-001 in scn-001, horizon 3). NPV = -1000 + 600/1.1 + 600/1.1^2 = 5000/121 = 41.322314...,
-- shown as 41.32 with the exact rational beside it; simple payback 2 (interpolated 1.6667), discounted payback 2 (interpolated 1.9167), the two labelled separately; the 800.00 capacity hours stay out of
-- the cash flow because no conversion exists. The other two initiatives and the attributable portfolio NPV (-8300/11 = -754.55, which gives back the present value 61.98 of the 75.00 claimed twice) are the
-- rest of the golden world's hand-worked figures (tests/fixtures/golden/CALCULATION.md parts a-h).

-- @@ cash_flow_init001
SELECT f.t AS period_index, round(f.costs, 2) AS costs, round(f.benefits, 2) AS cash_benefits, round(f.net, 2) AS net_cash_flow, round(f.cumulative, 2) AS cumulative,
       round(1 / p.qp, 6) AS discount_factor, round(f.net / p.qp, 2) AS discounted_cash_flow, round(d.dnum / p.qp, 2) AS cumulative_discounted
FROM cw_flow f JOIN cw_dnum d ON d.scenario_id = f.scenario_id AND d.initiative_id = f.initiative_id AND d.t = f.t
JOIN cw_qpow p ON p.scenario_id = f.scenario_id AND p.k = f.t
WHERE f.scenario_id = 'scn-001' AND f.initiative_id = 'init-001'
ORDER BY f.t

-- @@ init001_answer
SELECT i.initiative_id, round(i.npv, 2) AS npv,
       e.npv_exact,
       i.simple_t AS simple_payback_period, round(i.simple_i, 4) AS simple_payback_interpolated, i.disc_t AS discounted_payback_period, round(i.disc_i, 4) AS discounted_payback_interpolated,
       round(coalesce((SELECT sum(b.ramped) FROM cw_ben b WHERE b.scenario_id = i.scenario_id AND b.initiative_id = i.initiative_id AND b.class = 'capacity_hours'), 0), 2) AS capacity_hours_excluded
FROM cw_init i JOIN cw_exact e ON e.scenario_id = i.scenario_id AND e.initiative_id = i.initiative_id
WHERE i.scenario_id = 'scn-001' AND i.initiative_id = 'init-001'

-- @@ initiatives
SELECT i.initiative_id, round(i.npv, 2) AS npv,
       e.npv_exact,
       i.simple_t AS simple_payback_period, round(i.simple_i, 4) AS simple_payback_interpolated, i.simple_reason,
       i.disc_t AS discounted_payback_period, round(i.disc_i, 4) AS discounted_payback_interpolated, i.disc_reason AS discounted_reason
FROM cw_init i JOIN cw_exact e ON e.scenario_id = i.scenario_id AND e.initiative_id = i.initiative_id
WHERE i.scenario_id = 'scn-001'
ORDER BY i.initiative_id COLLATE "C"

-- @@ portfolio
SELECT n.scenario_id, round(n.sum_num / n.den, 2) AS sum_of_initiatives, round(n.pv_num / n.den, 2) AS double_counted_pv, round((n.sum_num - n.pv_num) / n.den, 2) AS attributable_npv,
       (CASE WHEN x.n_int < 0 THEN '-' ELSE '' END) || div(abs(x.n_int), gcd(x.n_int, x.d_int))::text ||
         CASE WHEN div(x.d_int, gcd(x.n_int, x.d_int)) = 1 THEN '' ELSE '/' || div(x.d_int, gcd(x.n_int, x.d_int))::text END AS attributable_exact,
       round(d.planned, 2) AS planned_benefits, round(d.removed, 2) AS residual, round(d.planned - d.removed, 2) AS attributable_benefits,
       round(d.hours_planned, 2) AS planned_hours, round(d.hours_removed, 2) AS hours_residual
FROM cw_scn_npv n JOIN cw_dc d ON d.scenario_id = n.scenario_id
CROSS JOIN LATERAL (SELECT (replace((n.sum_num - n.pv_num)::text, '.', '') || repeat('0', greatest(scale(n.den) - scale(n.sum_num - n.pv_num), 0)))::numeric AS n_int,
                           (replace(n.den::text, '.', '') || repeat('0', greatest(scale(n.sum_num - n.pv_num) - scale(n.den), 0)))::numeric AS d_int) x
WHERE n.scenario_id = 'scn-001'
