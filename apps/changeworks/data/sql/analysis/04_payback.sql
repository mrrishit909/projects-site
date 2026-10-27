-- P09-ART-04 investigation 04: simple and discounted payback by the last-crossing rule, the initiatives that never pay back, and the reasons (D-01, D-09 R9-12, DR-03, INJ-08).
-- Question: when does each initiative recover its investment, and which never does inside the benefit window? Payback is the first period after the LAST negative cumulative (so a series that dips below
-- zero again after a crossing reports the later crossing); a cumulative of exactly 0 counts as recovered; a series that ends negative is NOT_RECOVERED, one that is never negative is NO_INVESTMENT, one with
-- no rows at all is NO_FLOWS; each is null with its reason, never 0 and never refused. Simple (undiscounted) and discounted paybacks are labelled and computed separately. The interpolation is
-- (t-1) + (-cumulative[t-1]) / (cumulative[t] - cumulative[t-1]) to 4 places. Scope: scn-025 for the table; all 210 scenario-initiative series for the reasons.

-- @@ scn025
SELECT i.initiative_id, round(i.npv, 2) AS npv,
       i.simple_t AS simple_payback_period, round(i.simple_i, 4) AS simple_interpolated, i.simple_reason,
       i.disc_t AS discounted_payback_period, round(i.disc_i, 4) AS discounted_interpolated, i.disc_reason AS discounted_reason
FROM cw_init i WHERE i.scenario_id = 'scn-025'
ORDER BY i.initiative_id COLLATE "C"

-- @@ reasons
SELECT coalesce(i.simple_reason, 'RECOVERED') AS simple, coalesce(i.disc_reason, 'RECOVERED') AS discounted, count(*) AS series
FROM cw_init i
GROUP BY i.simple_reason, i.disc_reason
ORDER BY coalesce(i.simple_reason, 'RECOVERED') COLLATE "C", coalesce(i.disc_reason, 'RECOVERED') COLLATE "C"

-- @@ never_pays_back
SELECT i.initiative_id, count(*) AS scenarios, count(*) FILTER (WHERE i.simple_t IS NULL) AS scenarios_simple_null, count(*) FILTER (WHERE i.disc_t IS NULL) AS scenarios_discounted_null,
       (count(*) FILTER (WHERE i.simple_t IS NULL) = count(*)) AS never_in_any_scenario,
       round(min(i.npv), 2) AS npv_lowest, round(max(i.npv), 2) AS npv_highest,
       string_agg(DISTINCT coalesce(i.simple_reason, 'RECOVERED') COLLATE "C", ',' ORDER BY coalesce(i.simple_reason, 'RECOVERED') COLLATE "C") AS simple_reasons
FROM cw_init i
GROUP BY i.initiative_id
HAVING count(*) FILTER (WHERE i.simple_t IS NULL OR i.disc_t IS NULL) > 0
ORDER BY i.initiative_id COLLATE "C"

-- @@ init015_by_scenario
-- DR-03: init-015 recovers well under its cost over its benefit window, and the ratio depends on the adoption ramp the scenario pins, so each value names its scenario.
SELECT i.scenario_id, m.ramp_id AS ramp_assumption_id,
       round((SELECT sum(f.costs) FROM cw_flow f WHERE f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id), 2) AS planned_cost,
       round((SELECT sum(f.benefits) FROM cw_flow f WHERE f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id), 2) AS benefits_entering_the_cash_flow,
       round((SELECT sum(f.benefits) FROM cw_flow f WHERE f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id)
             / (SELECT sum(f.costs) FROM cw_flow f WHERE f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id), 6) AS benefit_to_cost,
       round(i.npv, 2) AS npv, i.simple_t AS simple_payback_period, i.disc_t AS discounted_payback_period, i.simple_reason
FROM cw_init i JOIN cw_model m ON m.scenario_id = i.scenario_id AND m.initiative_id = i.initiative_id
WHERE i.initiative_id = 'init-015'
ORDER BY i.scenario_id COLLATE "C"

-- @@ last_crossing_rule
-- Where the first period at or above zero after the first negative differs from the last crossing, the rule matters; the count is stated, not assumed.
SELECT count(*) AS series, count(*) FILTER (WHERE x.first_neg IS NOT NULL) AS series_that_went_negative,
       count(*) FILTER (WHERE i.simple_t IS NOT NULL) AS series_that_recovered,
       count(*) FILTER (WHERE i.simple_t IS NOT NULL AND x.first_cross IS DISTINCT FROM i.simple_t) AS recovered_series_where_first_and_last_crossing_differ,
       count(*) FILTER (WHERE i.simple_reason = 'NO_INVESTMENT') AS never_negative, count(*) FILTER (WHERE i.simple_reason = 'NO_FLOWS') AS no_flows
FROM cw_init i
CROSS JOIN LATERAL (SELECT (SELECT min(d.t) FROM cw_dnum d WHERE d.scenario_id = i.scenario_id AND d.initiative_id = i.initiative_id AND d.cumulative < 0) AS first_neg,
                           (SELECT min(d.t) FROM cw_dnum d WHERE d.scenario_id = i.scenario_id AND d.initiative_id = i.initiative_id AND d.cumulative >= 0
                              AND d.t > (SELECT min(e.t) FROM cw_dnum e WHERE e.scenario_id = i.scenario_id AND e.initiative_id = i.initiative_id AND e.cumulative < 0)) AS first_cross) x
