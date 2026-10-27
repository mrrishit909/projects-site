-- P08-ART-06 fact_gate_check: one row per run that reached the gate and check (1,328 x 7 = 9,296): the latest result of each rule. Scope: complete_world.
SELECT g.run_id, g.rule_name, g.severity, g.eligible_count, g.failure_count, g.failure_count = 0 AS passed, 'complete_world' AS scope
FROM po_gate_result g ORDER BY g.run_id COLLATE "C", g.rule_name COLLATE "C"
