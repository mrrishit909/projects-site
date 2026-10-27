-- P09-ART-04 investigation 11: the screen behind the proposal, which initiatives carry a cash case, which wait for evidence (D-01, D-03, D-09; P09-GOAL-01, P09-FLOW-07).
-- Question: which initiatives (and which scenario) should be PROPOSED for funding, and what would establish success? Nothing here funds anything: a selected scenario is a proposal. The screen reads
-- the estimates of scn-025 beside what has been observed. An initiative CARRIES a cash case when its NPV in scn-025 is above zero and it recovers its investment inside the window (both paybacks found);
-- it WAITS when it does not. Observed evidence (adoption, cash realisation on matured periods, cost variance) is shown beside each, never folded into the NPV, and every observed improvement is "observed,
-- not attributed". The constructed option (the carrying initiatives only) is exact arithmetic over the stored NPVs and is labelled constructed: it is not a stored scenario and would have to be built with
-- C03 and proposed with C07. Scope: scn-025 (8 % annual converted to 0.006434 per month, 36 periods), as-of 2026-10-05.

-- @@ initiative_screen
SELECT i.initiative_id, round(i.npv, 2) AS npv, i.simple_t AS simple_payback_period, i.disc_t AS discounted_payback_period,
       round(f.benefits / f.costs, 6) AS cash_benefit_to_cost,
       round(coalesce(h.hours, 0), 2) AS capacity_hours_not_converted, round(coalesce(bs.beside, 0), 2) AS avoided_cost_beside,
       round(ad.adopted_count::numeric / ad.eligible_count, 6) AS adoption_rate,
       CASE WHEN rc.compared > 0 AND rc.planned <> 0 THEN round(rc.observed / rc.planned, 6) END AS cash_realisation,
       CASE WHEN v.approved_version IS NOT NULL AND v.actual_rows > 0 THEN round(v.actual_cost - coalesce(v.planned_cost, 0), 2) END AS cost_variance,
       round(rk.exposure, 2) AS risk_exposure, rd.delay AS dependency_delay,
       CASE WHEN i.npv > 0 AND i.simple_t IS NOT NULL AND i.disc_t IS NOT NULL THEN 'CARRIES' ELSE 'WAITS' END AS screen
FROM cw_init i
JOIN (SELECT scenario_id, initiative_id, sum(benefits) AS benefits, sum(costs) AS costs FROM cw_flow GROUP BY scenario_id, initiative_id) f ON f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id
LEFT JOIN (SELECT scenario_id, initiative_id, sum(ramped) AS hours FROM cw_ben WHERE class = 'capacity_hours' GROUP BY scenario_id, initiative_id) h ON h.scenario_id = i.scenario_id AND h.initiative_id = i.initiative_id
LEFT JOIN (SELECT scenario_id, initiative_id, sum(money) AS beside FROM cw_ben WHERE class = 'avoided_cost_beside' GROUP BY scenario_id, initiative_id) bs ON bs.scenario_id = i.scenario_id AND bs.initiative_id = i.initiative_id
LEFT JOIN cw_adopt ad ON ad.initiative_id = i.initiative_id AND ad.eligible_count > 0
LEFT JOIN cw_real rc ON rc.scenario_id = i.scenario_id AND rc.initiative_id = i.initiative_id AND rc.benefit_type = 'cash'
LEFT JOIN cw_var v ON v.scenario_id = i.scenario_id AND v.initiative_id = i.initiative_id
LEFT JOIN (SELECT initiative_id, sum(probability * impact) AS exposure FROM risk_items GROUP BY initiative_id) rk ON rk.initiative_id = i.initiative_id
JOIN cw_roadmap rd ON rd.initiative_id = i.initiative_id
WHERE i.scenario_id = 'scn-025'
ORDER BY i.initiative_id COLLATE "C"

-- @@ waiting
-- Why the six that wait do not carry a cash case in scn-025: their benefits do not enter the cash flow (avoided cost beside it, or capacity hours with no conversion evidence), or they enter and stay below cost.
SELECT i.initiative_id, round(i.npv, 2) AS npv,
       round(f.benefits / f.costs, 6) AS cash_benefit_to_cost, round(f.costs, 2) AS planned_costs, round(coalesce(h.hours, 0), 2) AS capacity_hours_not_converted, round(coalesce(bs.beside, 0), 2) AS avoided_cost_beside,
       CASE WHEN f.benefits = 0 THEN 'NO_BENEFIT_ENTERS_THE_CASH_FLOW' ELSE 'BENEFITS_ENTER_BUT_STAY_BELOW_COST' END AS reason
FROM cw_init i
JOIN (SELECT scenario_id, initiative_id, sum(benefits) AS benefits, sum(costs) AS costs FROM cw_flow GROUP BY scenario_id, initiative_id) f ON f.scenario_id = i.scenario_id AND f.initiative_id = i.initiative_id
LEFT JOIN (SELECT scenario_id, initiative_id, sum(ramped) AS hours FROM cw_ben WHERE class = 'capacity_hours' GROUP BY scenario_id, initiative_id) h ON h.scenario_id = i.scenario_id AND h.initiative_id = i.initiative_id
LEFT JOIN (SELECT scenario_id, initiative_id, sum(money) AS beside FROM cw_ben WHERE class = 'avoided_cost_beside' GROUP BY scenario_id, initiative_id) bs ON bs.scenario_id = i.scenario_id AND bs.initiative_id = i.initiative_id
WHERE i.scenario_id = 'scn-025' AND NOT (i.npv > 0 AND i.simple_t IS NOT NULL AND i.disc_t IS NOT NULL)
ORDER BY i.initiative_id COLLATE "C"

-- @@ options
-- A is the stored scenario. B, C and D are constructed from the stored NPVs of scn-025 (initiative NPVs add within a scenario: one rate, one set of pins): B keeps the initiatives that carry a cash case;
-- C adds the prerequisites they depend on; D keeps the carrying initiatives whose every prerequisite (transitively) also carries, so it needs no waiting initiative. The attributable NPV gives back the present
-- value of the shared claims that count twice among the members; prerequisites_outside_the_option > 0 means the roadmap would have to be re-planned, because a dependency leads to an initiative left out.
WITH RECURSIVE scr AS (SELECT i.initiative_id, i.npv_num, (i.npv > 0 AND i.simple_t IS NOT NULL AND i.disc_t IS NOT NULL) AS carries FROM cw_init i WHERE i.scenario_id = 'scn-025'),
anc(initiative_id, ancestor) AS (
    SELECT d.initiative_id, d.prerequisite_id FROM dependencies d
    UNION
    SELECT a.initiative_id, d.prerequisite_id FROM anc a JOIN dependencies d ON d.initiative_id = a.ancestor),
member(option_id, initiative_id) AS (
    SELECT 'A', s.initiative_id FROM scr s
    UNION ALL SELECT 'B', s.initiative_id FROM scr s WHERE s.carries
    UNION ALL SELECT 'C', x.initiative_id FROM (SELECT s.initiative_id FROM scr s WHERE s.carries UNION SELECT a.ancestor FROM anc a JOIN scr s ON s.initiative_id = a.initiative_id WHERE s.carries) x
    UNION ALL SELECT 'D', s.initiative_id FROM scr s WHERE s.carries AND NOT EXISTS (SELECT 1 FROM anc a JOIN scr p ON p.initiative_id = a.ancestor WHERE a.initiative_id = s.initiative_id AND NOT p.carries)),
opt(option_id, label, kind) AS (VALUES ('A', 'all 24 initiatives of scn-025', 'stored scenario'), ('B', 'the initiatives that carry a cash case', 'constructed'),
                                       ('C', 'the carrying initiatives and the prerequisites they depend on', 'constructed'), ('D', 'the carrying initiatives that need no waiting prerequisite', 'constructed')),
sc AS (SELECT den, h - 1 AS last FROM cw_scn_npv n JOIN cw_scn s USING (scenario_id) WHERE scenario_id = 'scn-025')
SELECT o.option_id, o.label, o.kind, (SELECT count(*) FROM member m WHERE m.option_id = o.option_id) AS initiatives,
       round((SELECT sum(f.costs) FROM cw_flow f JOIN member m ON m.initiative_id = f.initiative_id AND m.option_id = o.option_id WHERE f.scenario_id = 'scn-025'), 2) AS planned_costs,
       round((SELECT sum(x.npv_num) FROM scr x JOIN member m ON m.initiative_id = x.initiative_id AND m.option_id = o.option_id) / (SELECT den FROM sc), 2) AS sum_of_initiatives,
       round(coalesce((SELECT sum(c.claim * p.qp) FROM cw_claim c JOIN cw_qpow p ON p.scenario_id = c.scenario_id AND p.k = (SELECT last FROM sc) - c.period_index
                       JOIN member m ON m.initiative_id = c.initiative_id AND m.option_id = o.option_id
                       WHERE c.scenario_id = 'scn-025' AND c.initiatives_in_key >= 2 AND c.rn > 1 AND c.enters), 0) / (SELECT den FROM sc), 2) AS double_counted_pv,
       round(((SELECT sum(x.npv_num) FROM scr x JOIN member m ON m.initiative_id = x.initiative_id AND m.option_id = o.option_id)
              - coalesce((SELECT sum(c.claim * p.qp) FROM cw_claim c JOIN cw_qpow p ON p.scenario_id = c.scenario_id AND p.k = (SELECT last FROM sc) - c.period_index
                          JOIN member m ON m.initiative_id = c.initiative_id AND m.option_id = o.option_id
                          WHERE c.scenario_id = 'scn-025' AND c.initiatives_in_key >= 2 AND c.rn > 1 AND c.enters), 0)) / (SELECT den FROM sc), 2) AS attributable_npv,
       (SELECT count(*) FROM dependencies d WHERE d.initiative_id IN (SELECT initiative_id FROM member WHERE option_id = o.option_id)
          AND d.prerequisite_id NOT IN (SELECT initiative_id FROM member WHERE option_id = o.option_id)) AS prerequisites_outside_the_option,
       (SELECT count(*) FROM (SELECT c.benefit_source_key, c.period_index FROM cw_claim c WHERE c.scenario_id = 'scn-025' AND c.initiatives_in_key >= 2
                              GROUP BY c.benefit_source_key, c.period_index
                              HAVING count(*) FILTER (WHERE c.initiative_id IN (SELECT initiative_id FROM member WHERE option_id = o.option_id)) BETWEEN 1 AND count(*) - 1) k) AS shared_claims_crossing_the_boundary,
       (SELECT count(*) FROM scr x JOIN member m ON m.initiative_id = x.initiative_id AND m.option_id = o.option_id WHERE x.npv_num < 0) AS initiatives_with_a_negative_npv,
       (SELECT string_agg(m.initiative_id, ',' ORDER BY m.initiative_id COLLATE "C") FROM member m WHERE m.option_id = o.option_id AND o.option_id <> 'A') AS members
FROM opt o
ORDER BY o.option_id COLLATE "C"

-- @@ dependency_ties
-- The dependencies that lead from an initiative that carries a cash case to one that waits: the reason option B cannot be delivered as the plan stands.
SELECT d.dependency_id, d.initiative_id, d.prerequisite_id, d.dependency_type, d.lag_periods,
       round(a.npv, 2) AS initiative_npv, round(b.npv, 2) AS prerequisite_npv
FROM dependencies d JOIN cw_init a ON a.scenario_id = 'scn-025' AND a.initiative_id = d.initiative_id JOIN cw_init b ON b.scenario_id = 'scn-025' AND b.initiative_id = d.prerequisite_id
WHERE a.npv > 0 AND a.simple_t IS NOT NULL AND a.disc_t IS NOT NULL AND NOT (b.npv > 0 AND b.simple_t IS NOT NULL AND b.disc_t IS NOT NULL)
ORDER BY d.dependency_id COLLATE "C"
