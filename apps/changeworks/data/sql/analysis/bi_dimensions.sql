-- P09-ART-06 BI dimensions (a star schema over the loaded snapshot). Read only; needs 00_portfolio_model.sql (cw_p, cw_scn, cw_roadmap, cw_init).
-- Booleans are 0/1, instants are UTC ISO text, rates are exact decimals, nothing is dropped silently: a scenario with no flows or an initiative with no adoption record still has a row in its fact with a status.

-- @@ dim_initiative
SELECT i.initiative_id, i.title, i.sponsor_id, i.status, coalesce(i.baseline_version, '') AS approved_baseline_version, i.requested_start_period, i.duration_periods, i.deployment_period,
       i.eligibility_rule_version, r.feasible_start AS dependency_feasible_start, r.delay AS dependency_delay, coalesce(r.binding_dependency_id, '') AS binding_dependency_id,
       (r.deployment_period < r.feasible_start)::int AS deployment_before_feasible_start
FROM initiatives i JOIN cw_roadmap r ON r.initiative_id = i.initiative_id
ORDER BY i.initiative_id COLLATE "C"

-- @@ dim_scenario
SELECT s.scenario_id, s.status, s.baseline_version, s.rate_basis, s.declared_rate::text AS declared_rate, s.r::text AS period_rate, s.rate_source, s.h AS horizon_periods,
       to_char(s.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at, (SELECT count(*) FROM cw_si i WHERE i.scenario_id = s.scenario_id) AS initiatives
FROM cw_scn s
ORDER BY s.scenario_id COLLATE "C"

-- @@ dim_benefit_class
SELECT v.class_code, v.label, v.unit, v.enters_cash_flow, v.rule
FROM (VALUES ('cash', 'Cash', 'USD', 1, 'enters the net cash flow'),
             ('revenue', 'Revenue', 'USD', 1, 'enters the net cash flow'),
             ('avoided_cost_realised', 'Avoided cost, realised', 'USD', 1, 'cash_realisation true and a non-blank evidence_ref'),
             ('capacity_converted', 'Capacity, converted to money', 'USD', 1, 'a capacity_hourly_rate with a non-blank staffing_change_evidence_ref: a separate derived cash item'),
             ('avoided_cost_beside', 'Avoided cost, beside the cash flow', 'USD', 0, 'not cash-realised or no evidence: reported beside, never in the flow'),
             ('capacity_hours', 'Capacity hours, not converted', 'hours', 0, 'never enters the cash flow and is never added to dollars')) AS v (class_code, label, unit, enters_cash_flow, rule)
ORDER BY v.class_code COLLATE "C"

-- @@ dim_period
SELECT g.t AS period_index, (p.period_start + g.t * CASE WHEN p.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::date AS period_start,
       (p.period_start + (g.t + 1) * CASE WHEN p.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::date AS period_end_exclusive,
       (g.t < p.matured)::int AS matured_at_as_of,
       extract(year FROM p.period_start + g.t * CASE WHEN p.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::int AS year,
       extract(month FROM p.period_start + g.t * CASE WHEN p.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::int AS month
FROM cw_p p CROSS JOIN generate_series(0, (SELECT max(h) - 1 FROM cw_scn)) AS g(t)
ORDER BY g.t

-- @@ dim_resource
SELECT r.resource_id, r.name, r.capacity_per_period::numeric(20,2)::text AS capacity, r.unit
FROM resources r
ORDER BY r.resource_id COLLATE "C"
