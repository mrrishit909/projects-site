-- P09-ART-06 fact: the dated net cash flow, one row per scenario x initiative x period (the benefit window of each scenario's horizon). The four classes that enter the flow are separate columns;
-- amounts are exact decimals. discounted_cash_flow is rounded to 2 places for display only: an NPV is recomputed from the exact net_cash_flow and the scenario's period_rate, never from the rounded column.
-- Needs 00_portfolio_model.sql.
SELECT f.scenario_id, f.initiative_id, f.t AS period_index, f.costs::text AS costs, f.cash::text AS cash, f.revenue::text AS revenue, f.avoided_cost_realised::text AS avoided_cost_realised,
       f.capacity_converted::text AS capacity_converted, f.net::text AS net_cash_flow, f.cumulative::text AS cumulative, round(f.net / p.qp, 2)::text AS discounted_cash_flow
FROM cw_flow f JOIN cw_qpow p ON p.scenario_id = f.scenario_id AND p.k = f.t
ORDER BY f.scenario_id COLLATE "C", f.initiative_id COLLATE "C", f.t
