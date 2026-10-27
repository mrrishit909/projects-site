-- P09-ART-06 fact: every claim that shares a benefit_source_key in one period with another initiative's claim (money and hours kept apart), the retained one flagged; amounts are exact decimals.
-- The residual of a scenario is the sum of the claims that are not retained. Needs 00_portfolio_model.sql.
SELECT u.scenario_id, u.rule, u.benefit_source_key, u.period_index, u.initiative_id, u.benefit_id, u.class, u.amount, u.retained, u.enters_cash_flow
FROM (SELECT c.scenario_id, 'money' AS rule, c.benefit_source_key, c.period_index, c.initiative_id, c.benefit_id, c.class, c.claim::text AS amount, (c.rn = 1)::int AS retained, c.enters::int AS enters_cash_flow
      FROM cw_claim c WHERE c.initiatives_in_key >= 2
      UNION ALL
      SELECT h.scenario_id, 'hours', h.benefit_source_key, h.period_index, h.initiative_id, h.benefit_id, 'capacity_hours', h.hours::text, (h.rn = 1)::int, 0
      FROM cw_hours h WHERE h.initiatives_in_key >= 2) u
ORDER BY u.scenario_id COLLATE "C", u.rule COLLATE "C", u.benefit_source_key COLLATE "C", u.period_index, u.initiative_id COLLATE "C", u.benefit_id COLLATE "C"
