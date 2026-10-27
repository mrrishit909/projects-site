-- P09-ART-04 leaves: the analysis model's own figures (D-01..D-09) in the leaf-path form of expected.json (path, val), so that run_all.py can compare every leaf with the reference SQL, the Python domain and
-- the golden expected.json. Read only; needs 00_portfolio_model.sql. The values are rounded once, in SQL, half away from zero (money 2 places, paybacks / hours 4, proportions 6); NULL stays NULL.
-- Not covered here (the reference SQL and the domain cover them): risk exposure, readiness and the summary pools of risk and capacity released.
SELECT path, val FROM (
    SELECT 'metrics.scenarios.' || f.scenario_id || '.initiatives.' || f.initiative_id || '.cash_flow[' || f.t || '].' || x.k AS path, x.v AS val
    FROM cw_flow f JOIN cw_qpow p ON p.scenario_id = f.scenario_id AND p.k = f.t JOIN cw_dnum d ON d.scenario_id = f.scenario_id AND d.initiative_id = f.initiative_id AND d.t = f.t,
         LATERAL (VALUES ('costs', round(f.costs, 2)::text), ('cash_benefits', round(f.benefits, 2)::text), ('net_cash_flow', round(f.net, 2)::text), ('cumulative', round(f.cumulative, 2)::text),
                         ('discounted_cash_flow', round(f.net / p.qp, 2)::text), ('cumulative_discounted', round(d.dnum / p.qp, 2)::text)) x(k, v)
    UNION ALL
    SELECT 'metrics.scenarios.' || i.scenario_id || '.initiatives.' || i.initiative_id || '.npv.value', round(i.npv, 2)::text FROM cw_init i
    UNION ALL
    SELECT 'metrics.scenarios.' || i.scenario_id || '.initiatives.' || i.initiative_id || '.payback.' || k, v
    FROM cw_init i, LATERAL (VALUES ('simple.period', i.simple_t::text), ('simple.interpolated', round(i.simple_i, 4)::text), ('simple.reason', i.simple_reason),
                                    ('discounted.period', i.disc_t::text), ('discounted.interpolated', round(i.disc_i, 4)::text), ('discounted.reason', i.disc_reason)) x(k, v)
    UNION ALL
    SELECT 'metrics.scenarios.' || si.scenario_id || '.initiatives.' || si.initiative_id || '.excluded_from_cash_flow.' || k, v
    FROM cw_si si, LATERAL (VALUES
        ('capacity_hours_not_converted', (SELECT round(sum(b.ramped), 2)::text FROM cw_ben b WHERE b.scenario_id = si.scenario_id AND b.initiative_id = si.initiative_id AND b.class = 'capacity_hours')),
        ('avoided_cost_beside_total', (SELECT round(sum(b.money), 2)::text FROM cw_ben b WHERE b.scenario_id = si.scenario_id AND b.initiative_id = si.initiative_id AND b.class = 'avoided_cost_beside'))) x(k, v)
    UNION ALL
    SELECT 'metrics.scenarios.' || c.scenario_id || '.initiatives.' || c.initiative_id || '.capacity_released.' || k, v
    FROM cw_cap c, LATERAL (VALUES ('hours', round(c.hours, 4)::text), ('reason', c.reason)) x(k, v)
    UNION ALL
    SELECT 'metrics.scenarios.' || v.scenario_id || '.initiatives.' || v.initiative_id || '.cost_variance.' || k, val
    FROM cw_var v, LATERAL (VALUES
        ('window.to_period', v.wend::text),
        ('approved_baseline_cost', CASE WHEN v.approved_version IS NOT NULL AND v.wend > 0 THEN round(coalesce(v.planned_cost, 0), 2)::text END),
        ('actual_cost', CASE WHEN v.approved_version IS NOT NULL AND v.wend > 0 AND v.actual_rows > 0 THEN round(v.actual_cost, 2)::text END),
        ('variance', CASE WHEN v.approved_version IS NOT NULL AND v.wend > 0 AND v.actual_rows > 0 THEN round(v.actual_cost - coalesce(v.planned_cost, 0), 2)::text END),
        ('reason', CASE WHEN v.approved_version IS NULL THEN 'NO_APPROVED_BASELINE' WHEN v.wend = 0 THEN 'NO_MATURED_PERIOD' WHEN v.actual_rows = 0 THEN 'NO_ACTUALS' END)) x(k, val)
    UNION ALL
    SELECT 'metrics.scenarios.' || r.scenario_id || '.initiatives.' || r.initiative_id || '.benefit_realization.' || r.benefit_type || '.' || k, val
    FROM cw_real r, LATERAL (VALUES
        ('planned_comparable', CASE WHEN r.compared > 0 THEN round(r.planned, 2)::text END),
        ('observed_comparable', CASE WHEN r.compared > 0 THEN round(r.observed, 2)::text END),
        ('realization', CASE WHEN r.compared > 0 AND r.planned <> 0 THEN round(r.observed / r.planned, 6)::text END),
        ('baseline_trend', CASE WHEN r.trend_rows > 0 THEN round(r.trend, 2)::text END),
        ('observed_above_trend', CASE WHEN r.trend_rows > 0 AND r.compared > 0 AND r.trend_rows = r.compared THEN round(r.observed - r.trend, 2)::text END)) x(k, val)
    WHERE r.compared > 0 OR r.unobserved > 0
    UNION ALL
    SELECT 'metrics.scenarios.' || d.scenario_id || '.double_count.' || k, val
    FROM cw_dc d, LATERAL (VALUES ('planned_benefits', round(d.planned, 2)::text), ('attributable_benefits', round(d.planned - d.removed, 2)::text), ('residual', round(d.removed, 2)::text),
                                  ('double_counted_amount', round(d.removed, 2)::text), ('double_counted_pv', round(d.pv_num / d.pv_den, 2)::text), ('planned_hours', round(d.hours_planned, 2)::text),
                                  ('attributable_hours', round(d.hours_planned - d.hours_removed, 2)::text), ('hours_residual', round(d.hours_removed, 2)::text)) x(k, val)
    UNION ALL
    SELECT 'metrics.scenarios.' || n.scenario_id || '.npv_total.' || k, val
    FROM cw_scn_npv n, LATERAL (VALUES ('value', round((n.sum_num - n.pv_num) / n.den, 2)::text), ('sum_of_initiatives', round(n.sum_num / n.den, 2)::text)) x(k, val)
    WHERE n.with_flows > 0
    UNION ALL
    SELECT 'metrics.initiatives.' || i.initiative_id || '.adoption.' || k, val
    FROM initiatives i LEFT JOIN cw_adopt a ON a.initiative_id = i.initiative_id,
         LATERAL (VALUES ('adoption_rate', CASE WHEN a.eligible_count > 0 THEN round(a.adopted_count::numeric / a.eligible_count, 6)::text END), ('eligible_count', a.eligible_count::text),
                         ('adopted_count', a.adopted_count::text)) x(k, val)
    UNION ALL
    SELECT 'metrics.initiatives.' || i.initiative_id || '.training.' || k, val
    FROM initiatives i LEFT JOIN cw_train t ON t.initiative_id = i.initiative_id,
         LATERAL (VALUES ('training_completion', CASE WHEN t.eligible_trainees > 0 THEN round(t.completed::numeric / t.eligible_trainees, 6)::text END), ('eligible_trainees', t.eligible_trainees::text),
                         ('completed', t.completed::text)) x(k, val)
    UNION ALL
    SELECT 'metrics.initiatives.' || r.initiative_id || '.roadmap.' || k, val
    FROM cw_roadmap r, LATERAL (VALUES ('dependency_feasible_start', r.feasible_start::text), ('dependency_delay', r.delay::text), ('binding_dependency_id', r.binding_dependency_id)) x(k, val)
    UNION ALL
    SELECT 'metrics.summary.' || k, val
    FROM (SELECT s.scenario_id FROM cw_scn s ORDER BY s.scenario_id COLLATE "C" LIMIT 1) fs
    JOIN cw_dc d ON d.scenario_id = fs.scenario_id JOIN cw_scn_npv n ON n.scenario_id = fs.scenario_id,
         LATERAL (VALUES ('npv_total', round((n.sum_num - n.pv_num) / n.den, 2)::text), ('npv_sum_of_initiatives', round(n.sum_num / n.den, 2)::text), ('double_counted_amount', round(d.removed, 2)::text),
                         ('double_counted_pv', round(d.pv_num / d.pv_den, 2)::text), ('double_count_residual', round(d.removed, 2)::text), ('hours_residual', round(d.hours_removed, 2)::text)) x(k, val)
    WHERE n.with_flows > 0
    UNION ALL
    SELECT 'metrics.summary.adoption_rate', round(sum(a.adopted_count)::numeric / sum(a.eligible_count), 6)::text FROM cw_adopt a WHERE a.eligible_count > 0
    UNION ALL
    SELECT 'metrics.summary.training_completion', round(sum(t.completed)::numeric / sum(t.eligible_trainees), 6)::text FROM cw_train t WHERE t.eligible_trainees > 0
) u
ORDER BY path COLLATE "C"
