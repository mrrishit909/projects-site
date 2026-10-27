-- P09-ART-04 investigation 01: the portfolio ledger per scenario, the four benefit classes kept apart (D-01, D-09 R9-02, R9-03, R9-07).
-- Question: for each of the 30 scenarios, what does the portfolio cost, and what does it claim in each benefit class? Cash, revenue, avoided cost (realised, and beside the cash flow) and capacity
-- (converted money, and hours not converted) are never added into one number; the plain sum of the money claims sits beside the attributable total, which counts a claim shared across initiatives once.
-- Every figure is an exact sum rounded once (half away from zero), never a sum of rounded rows. Money is USD, capacity is hours. Scope: the benefit window of each scenario's own horizon.

-- @@ by_scenario
SELECT s.scenario_id, (SELECT count(*) FROM cw_si i WHERE i.scenario_id = s.scenario_id) AS initiatives, s.h AS horizon_periods, s.rate_basis,
       s.declared_rate::numeric(7,6) AS declared_rate, round(s.r, 6) AS period_rate,
       round(coalesce((SELECT sum(c.amount) FROM cw_cost c WHERE c.scenario_id = s.scenario_id AND c.cost_basis = 'planned'), 0), 2) AS planned_costs,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'cash'), 0), 2) AS cash,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'revenue'), 0), 2) AS revenue,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'avoided_cost_realised'), 0), 2) AS avoided_cost_realised,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'capacity_converted'), 0), 2) AS capacity_converted,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'avoided_cost_beside'), 0), 2) AS avoided_cost_beside,
       round(d.planned, 2) AS planned_benefits, round(d.removed, 2) AS double_counted_amount, round(d.planned - d.removed, 2) AS attributable_benefits,
       round(d.hours_planned, 2) AS capacity_hours_planned, round(d.hours_removed, 2) AS hours_residual, round(d.hours_planned - d.hours_removed, 2) AS capacity_hours_attributable,
       round(coalesce((SELECT sum(b.ramped) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'capacity_hours'), 0), 2) AS capacity_hours_not_converted
FROM cw_scn s JOIN cw_dc d ON d.scenario_id = s.scenario_id
ORDER BY s.scenario_id COLLATE "C"

-- @@ class_identity
-- The classes add up to the plain sum only in the way the contract says: the four classes that enter the cash flow plus the avoided cost beside it are the money claims; hours are a separate unit.
SELECT s.scenario_id,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.enters), 0), 2) AS entering_the_cash_flow,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'avoided_cost_beside'), 0), 2) AS beside_the_cash_flow,
       round(d.planned, 2) AS planned_benefits,
       (d.planned = coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.enters), 0)
                    + coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'avoided_cost_beside'), 0)) AS identity_holds_exactly,
       (SELECT count(*) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'capacity_hours') AS hour_rows_never_added_to_dollars
FROM cw_scn s JOIN cw_dc d ON d.scenario_id = s.scenario_id
ORDER BY s.scenario_id COLLATE "C"

-- @@ scn025_by_initiative
-- The shared scenario of the designed relationships (scn-025, all 24 initiatives): each initiative's costs and its four classes.
SELECT i.initiative_id,
       round(coalesce((SELECT sum(c.amount) FROM cw_cost c WHERE c.scenario_id = 'scn-025' AND c.initiative_id = i.initiative_id AND c.cost_basis = 'planned'), 0), 2) AS planned_costs,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = 'scn-025' AND b.initiative_id = i.initiative_id AND b.class = 'cash'), 0), 2) AS cash,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = 'scn-025' AND b.initiative_id = i.initiative_id AND b.class = 'revenue'), 0), 2) AS revenue,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = 'scn-025' AND b.initiative_id = i.initiative_id AND b.class = 'avoided_cost_realised'), 0), 2) AS avoided_cost_realised,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = 'scn-025' AND b.initiative_id = i.initiative_id AND b.class = 'capacity_converted'), 0), 2) AS capacity_converted,
       round(coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = 'scn-025' AND b.initiative_id = i.initiative_id AND b.class = 'avoided_cost_beside'), 0), 2) AS avoided_cost_beside,
       round(coalesce((SELECT sum(b.ramped) FROM cw_ben b WHERE b.scenario_id = 'scn-025' AND b.initiative_id = i.initiative_id AND b.class = 'capacity_hours'), 0), 2) AS capacity_hours_not_converted
FROM initiatives i
ORDER BY i.initiative_id COLLATE "C"
