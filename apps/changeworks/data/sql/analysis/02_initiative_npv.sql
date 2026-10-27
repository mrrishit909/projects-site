-- P09-ART-04 investigation 02: the NPV of every initiative in scn-025, and the attributable portfolio NPV beside the plain sum (D-01, D-09 R9-02, R9-07).
-- Question: what is each initiative worth, and what is the portfolio worth once a claim shared by two initiatives counts once? NPV = sum of net_t / (1 + r)^t over the scenario's horizon, exact in
-- NUMERIC (the single division is at the end; the reduced exact rational is published beside the 2-place figure). The portfolio NPV is attributable: the sum of the initiative NPVs less the present
-- value of the shared claims that count twice (double_counted_pv). Scope: scn-025 (24 initiatives, 36 monthly periods, 8 % annual converted to 0.006434 per month) and all 30 scenarios.

-- @@ scn025
SELECT i.initiative_id,
       round((SELECT sum(f.costs) FROM cw_flow f WHERE f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id), 2) AS planned_costs,
       round((SELECT sum(f.benefits) FROM cw_flow f WHERE f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id), 2) AS cash_benefits_entering,
       round((SELECT sum(f.net) FROM cw_flow f WHERE f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id), 2) AS undiscounted_net,
       i.has_rows AS has_flows, round(i.npv, 2) AS npv
FROM cw_init i WHERE i.scenario_id = 'scn-025'
ORDER BY i.initiative_id COLLATE "C"

-- @@ scn025_exact
-- The exact rational of each NPV, reduced (cw_exact in 00_portfolio_model.sql): numerator and denominator are scaled to integers by their decimal text, then divided by their gcd.
SELECT e.initiative_id, e.npv_exact FROM cw_exact e WHERE e.scenario_id = 'scn-025' ORDER BY e.initiative_id COLLATE "C"

-- @@ portfolio_scn025
SELECT n.scenario_id, n.with_flows AS initiatives_with_flows, round(n.sum_num / n.den, 2) AS sum_of_initiatives, round(n.pv_num / n.den, 2) AS double_counted_pv,
       round((n.sum_num - n.pv_num) / n.den, 2) AS attributable_npv, round(n.pv_num / n.den, 2) AS plain_sum_overstates_by
FROM cw_scn_npv n WHERE n.scenario_id = 'scn-025'

-- @@ by_scenario
SELECT n.scenario_id, n.with_flows AS initiatives_with_flows, round(n.sum_num / n.den, 2) AS sum_of_initiatives, round(n.pv_num / n.den, 2) AS double_counted_pv,
       round((n.sum_num - n.pv_num) / n.den, 2) AS attributable_npv
FROM cw_scn_npv n
ORDER BY n.scenario_id COLLATE "C"

-- @@ by_scenario_exact
SELECT n.scenario_id,
       (CASE WHEN x.n_int < 0 THEN '-' ELSE '' END) || div(abs(x.n_int), gcd(x.n_int, x.d_int))::text ||
       CASE WHEN div(x.d_int, gcd(x.n_int, x.d_int)) = 1 THEN '' ELSE '/' || div(x.d_int, gcd(x.n_int, x.d_int))::text END AS attributable_exact
FROM cw_scn_npv n
CROSS JOIN LATERAL (SELECT (replace((n.sum_num - n.pv_num)::text, '.', '') || repeat('0', greatest(scale(n.den) - scale(n.sum_num - n.pv_num), 0)))::numeric AS n_int,
                           (replace(n.den::text, '.', '') || repeat('0', greatest(scale(n.sum_num - n.pv_num) - scale(n.den), 0)))::numeric AS d_int) x
WHERE n.with_flows > 0
ORDER BY n.scenario_id COLLATE "C"
