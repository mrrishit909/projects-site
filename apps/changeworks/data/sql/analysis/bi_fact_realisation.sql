-- P09-ART-06 fact: benefit realisation inputs, one row per scenario x initiative x benefit type that has a matured row (periods 0..8 at the as-of): compared rows, matured rows with no observation (never counted
-- as 0), the exact planned and observed sums and the recorded baseline trend beside them. Always "observed, not attributed". Needs 00_portfolio_model.sql.
SELECT r.scenario_id, r.initiative_id, r.benefit_type, CASE WHEN r.benefit_type = 'capacity' THEN 'hours' ELSE 'USD' END AS unit, r.compared AS compared_rows, r.unobserved AS matured_unobserved_rows,
       r.trend_rows AS compared_rows_with_a_trend, coalesce(r.planned::text, '') AS planned_comparable, coalesce(r.observed::text, '') AS observed_comparable, CASE WHEN r.trend_rows > 0 THEN r.trend::text ELSE '' END AS baseline_trend,
       CASE WHEN r.compared = 0 THEN 'NO_COMPARABLE_ROW' WHEN r.trend_rows < r.compared THEN 'PARTIAL_TREND_COVERAGE' ELSE 'observed, not attributed' END AS status
FROM cw_real r WHERE r.compared > 0 OR r.unobserved > 0
ORDER BY r.scenario_id COLLATE "C", r.initiative_id COLLATE "C", r.benefit_type COLLATE "C"
