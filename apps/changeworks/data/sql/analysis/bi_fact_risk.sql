-- P09-ART-06 fact: one row per risk item (120): probability, impact (USD) and the exact expected loss (probability x impact, no rounding); a scenario estimate, not a forecast. Needs no temporary table.
SELECT r.risk_id, r.initiative_id, r.probability::text AS probability, r.impact::numeric(20,2)::text AS impact, (r.probability * r.impact)::text AS expected_loss
FROM risk_items r
ORDER BY r.risk_id COLLATE "C"
