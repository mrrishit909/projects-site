-- P09-ART-06 fact: one row per scenario (30). Money is USD, capacity is hours; every amount is the exact decimal of the sum of the exact rows (never a sum of rounded rows) and is rounded only where a column says so.
-- The portfolio ledger keeps the four benefit classes apart and puts the attributable totals beside the plain sums (D-09 R9-02, R9-03). Needs 00_portfolio_model.sql.
SELECT s.scenario_id,
       coalesce((SELECT sum(c.amount) FROM cw_cost c WHERE c.scenario_id = s.scenario_id AND c.cost_basis = 'planned'), 0)::text AS planned_costs,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'cash'), 0)::text AS cash,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'revenue'), 0)::text AS revenue,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'avoided_cost_realised'), 0)::text AS avoided_cost_realised,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'capacity_converted'), 0)::text AS capacity_converted,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'avoided_cost_beside'), 0)::text AS avoided_cost_beside,
       coalesce((SELECT sum(b.ramped) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.class = 'capacity_hours'), 0)::text AS capacity_hours_not_converted,
       d.planned::text AS planned_benefits, d.removed::text AS double_counted_amount, (d.planned - d.removed)::text AS attributable_benefits,
       d.hours_planned::text AS capacity_hours_planned, d.hours_removed::text AS hours_residual,
       n.with_flows AS initiatives_with_flows, round(n.sum_num / n.den, 2)::text AS npv_sum_of_initiatives, round(n.pv_num / n.den, 2)::text AS double_counted_pv,
       round((n.sum_num - n.pv_num) / n.den, 2)::text AS npv_attributable
FROM cw_scn s JOIN cw_dc d ON d.scenario_id = s.scenario_id JOIN cw_scn_npv n ON n.scenario_id = s.scenario_id
ORDER BY s.scenario_id COLLATE "C"
