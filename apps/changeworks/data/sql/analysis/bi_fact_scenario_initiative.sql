-- P09-ART-06 fact: one row per scenario x initiative (210): the four benefit classes apart, NPV (2 places, with its exact rational), both paybacks with their reasons (null with a reason, never 0), the capacity released,
-- and the cost variance on the matured window. Needs 00_portfolio_model.sql.
SELECT i.scenario_id, i.initiative_id,
       coalesce((SELECT sum(c.amount) FROM cw_cost c WHERE c.scenario_id = i.scenario_id AND c.initiative_id = i.initiative_id AND c.cost_basis = 'planned'), 0)::text AS planned_costs,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = i.scenario_id AND b.initiative_id = i.initiative_id AND b.class = 'cash'), 0)::text AS cash,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = i.scenario_id AND b.initiative_id = i.initiative_id AND b.class = 'revenue'), 0)::text AS revenue,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = i.scenario_id AND b.initiative_id = i.initiative_id AND b.class = 'avoided_cost_realised'), 0)::text AS avoided_cost_realised,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = i.scenario_id AND b.initiative_id = i.initiative_id AND b.class = 'capacity_converted'), 0)::text AS capacity_converted,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = i.scenario_id AND b.initiative_id = i.initiative_id AND b.class = 'avoided_cost_beside'), 0)::text AS avoided_cost_beside,
       coalesce((SELECT sum(b.ramped) FROM cw_ben b WHERE b.scenario_id = i.scenario_id AND b.initiative_id = i.initiative_id AND b.class = 'capacity_hours'), 0)::text AS capacity_hours_not_converted,
       i.has_rows::int AS has_flows, coalesce(round(i.npv, 2)::text, '') AS npv,
       coalesce(e.npv_exact, '') AS npv_exact,
       coalesce(i.simple_t::text, '') AS simple_payback_period, coalesce(round(i.simple_i, 4)::text, '') AS simple_payback_interpolated, coalesce(i.simple_reason, '') AS simple_payback_reason,
       coalesce(i.disc_t::text, '') AS discounted_payback_period, coalesce(round(i.disc_i, 4)::text, '') AS discounted_payback_interpolated, coalesce(i.disc_reason, '') AS discounted_payback_reason,
       coalesce(round(c.hours, 4)::text, '') AS capacity_released_hours, coalesce(c.reason, '') AS capacity_released_reason,
       coalesce(round(v.planned_cost, 2)::text, '') AS approved_baseline_cost, coalesce(round(v.actual_cost, 2)::text, '') AS actual_cost,
       CASE WHEN v.approved_version IS NOT NULL AND v.wend > 0 AND v.actual_rows > 0 THEN round(v.actual_cost - coalesce(v.planned_cost, 0), 2)::text ELSE '' END AS cost_variance,
       CASE WHEN v.approved_version IS NULL THEN 'NO_APPROVED_BASELINE' WHEN v.wend = 0 THEN 'NO_MATURED_PERIOD' WHEN v.actual_rows = 0 THEN 'NO_ACTUALS' ELSE '' END AS cost_variance_reason
FROM cw_init i
JOIN cw_exact e ON e.scenario_id = i.scenario_id AND e.initiative_id = i.initiative_id
JOIN cw_cap c ON c.scenario_id = i.scenario_id AND c.initiative_id = i.initiative_id
JOIN cw_var v ON v.scenario_id = i.scenario_id AND v.initiative_id = i.initiative_id
ORDER BY i.scenario_id COLLATE "C", i.initiative_id COLLATE "C"
