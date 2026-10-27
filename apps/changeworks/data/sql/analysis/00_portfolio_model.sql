-- P09-ART-04 setup: the portfolio model measured from the loaded facts, into temporary tables (D-01..D-09; the investigations read these tables and nothing else is stored).
-- Written for this package from the contracts (docs/contracts.md D-01..D-09), not copied from data/sql/reference_metrics.sql: it reads facts only (initiatives, baselines, assumptions,
-- scenarios and their pins, costs, benefits, observations, dependencies, allocations, the configuration) and no stored result (no expanded_costs, audit or command result).
--
-- Exactness. Money and hours are NUMERIC; no float is used anywhere. A discount factor is never divided early: with q = 1 + r (the per-period rate, a declared 6-place decimal) the powers
-- q^k are built by multiplication only (cw_qpow, exact in NUMERIC) and the cumulative discounted flow of period t is   D_t / q^t   with   D_t = sum over s <= t of net_s * q^(t-s)   (cw_dnum, exact).
-- The NPV is D_(h-1) / q^(h-1): ONE division, at the end, and its exact rational (reduced by gcd) is published beside the 2-place figure. A total is the sum of the exact amounts, rounded once
-- by round() (half away from zero = ROUND_HALF_UP), never the sum of rounded rows (R9-07).
--
-- Rules (D-09): a scenario uses the cost and benefit rows recorded by its created_at (a row with no recorded_at belongs to the loaded world) and the pinned assumption version, else the latest
-- created by then (R9-01); an avoided cost enters the cash flow only with cash_realisation and a non-blank evidence_ref; capacity hours never, unless the pinned capacity_hourly_rate has a
-- non-blank staffing_change_evidence_ref, when each row is a derived cash item (D-01); a recurring cost is expanded over the half-open range [start_period, end_period) and a one-time cost sits in
-- exactly its own period; payback is the last crossing from below zero, with the reasons NO_INVESTMENT, NOT_RECOVERED and NO_FLOWS (R9-12).

-- @@ cw_p
CREATE TEMP TABLE cw_p AS
SELECT c.period_basis, c.period_start, c.as_of,
       (SELECT count(*) FROM generate_series(0, (SELECT coalesce(max(horizon_periods), 1) FROM scenario_versions) - 1) AS g(t)
        WHERE ((c.period_start + (g.t + 1) * CASE WHEN c.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::timestamp AT TIME ZONE 'UTC') <= c.as_of) AS matured
FROM dataset_config c WHERE c.id = 1

-- @@ cw_scn
CREATE TEMP TABLE cw_scn AS
SELECT x.*, 1 + x.r AS q
FROM (SELECT s.scenario_id, s.created_at, s.horizon_periods AS h, s.baseline_version, s.status, s.rate_basis, s.discount_rate AS declared_rate,
             CASE WHEN s.rate_basis = p.period_basis THEN s.discount_rate ELSE conv.value::numeric END AS r,
             CASE WHEN s.rate_basis = p.period_basis THEN 'declared' ELSE 'conversion:' || s.rate_conversion_assumption_id END AS rate_source
      FROM scenario_versions s CROSS JOIN cw_p p LEFT JOIN assumption_versions conv ON conv.assumption_id = s.rate_conversion_assumption_id) x

-- @@ cw_si
CREATE TEMP TABLE cw_si AS
SELECT si.scenario_id, si.initiative_id FROM scenario_initiatives si

-- @@ cw_pick
CREATE TEMP TABLE cw_pick AS
SELECT z.scenario_id, z.initiative_id, z.name, z.assumption_id, z.value, z.value_list, z.staffing_change_evidence_ref
FROM (SELECT si.scenario_id, si.initiative_id, a.name, a.assumption_id, a.value, a.value_list, a.staffing_change_evidence_ref,
             row_number() OVER (PARTITION BY si.scenario_id, si.initiative_id, a.name ORDER BY (sp.assumption_id IS NULL), a.version_number DESC) AS rn
      FROM cw_si si JOIN cw_scn s ON s.scenario_id = si.scenario_id
      JOIN assumption_versions a ON a.initiative_id = si.initiative_id
      LEFT JOIN scenario_pins sp ON sp.scenario_id = si.scenario_id AND sp.assumption_id = a.assumption_id
      WHERE sp.assumption_id IS NOT NULL OR a.created_at <= s.created_at) z
WHERE z.rn = 1

-- @@ cw_model
CREATE TEMP TABLE cw_model AS
SELECT si.scenario_id, si.initiative_id,
       (SELECT k.value_list FROM cw_pick k WHERE k.scenario_id = si.scenario_id AND k.initiative_id = si.initiative_id AND k.name = 'adoption_ramp' AND k.value_list IS NOT NULL) AS ramp,
       (SELECT k.assumption_id FROM cw_pick k WHERE k.scenario_id = si.scenario_id AND k.initiative_id = si.initiative_id AND k.name = 'adoption_ramp' AND k.value_list IS NOT NULL) AS ramp_id,
       (SELECT k.value::numeric FROM cw_pick k WHERE k.scenario_id = si.scenario_id AND k.initiative_id = si.initiative_id AND k.name = 'capacity_hourly_rate' AND k.value IS NOT NULL
          AND btrim(coalesce(k.staffing_change_evidence_ref, ''), E' \t\n\r\f\v') <> '') AS rate_cap,
       (SELECT k.assumption_id FROM cw_pick k WHERE k.scenario_id = si.scenario_id AND k.initiative_id = si.initiative_id AND k.name = 'target_minutes_per_case') AS target_id,
       (SELECT k.value::numeric FROM cw_pick k WHERE k.scenario_id = si.scenario_id AND k.initiative_id = si.initiative_id AND k.name = 'target_minutes_per_case' AND k.value IS NOT NULL) AS target_minutes
FROM cw_si si

-- @@ cw_cost
CREATE TEMP TABLE cw_cost AS
SELECT s.scenario_id, c.initiative_id, c.cost_id, c.cost_key, c.cost_type, c.cost_basis, c.baseline_version, c.amount, g.t
FROM cw_si si JOIN cw_scn s ON s.scenario_id = si.scenario_id
JOIN cost_items c ON c.initiative_id = si.initiative_id AND (c.recorded_at IS NULL OR c.recorded_at <= s.created_at)
CROSS JOIN LATERAL generate_series(CASE WHEN c.cost_type = 'one_time' THEN c.period_index ELSE c.start_period END,
                                   CASE WHEN c.cost_type = 'one_time' THEN c.period_index ELSE c.end_period - 1 END) AS g(t)
WHERE g.t < s.h

-- @@ cw_ben
CREATE TEMP TABLE cw_ben AS
SELECT y.*,
       CASE WHEN y.class = 'capacity_hours' THEN NULL WHEN y.class = 'capacity_converted' THEN y.ramped * y.rate_cap ELSE y.ramped END AS money,
       (y.class IN ('cash', 'revenue', 'avoided_cost_realised', 'capacity_converted')) AS enters
FROM (SELECT x.*,
             CASE WHEN x.benefit_type IN ('cash', 'revenue') THEN x.benefit_type
                  WHEN x.benefit_type = 'avoided_cost' AND x.realised THEN 'avoided_cost_realised'
                  WHEN x.benefit_type = 'avoided_cost' THEN 'avoided_cost_beside'
                  WHEN x.rate_cap IS NOT NULL THEN 'capacity_converted'
                  ELSE 'capacity_hours' END AS class
      FROM (SELECT si.scenario_id, b.initiative_id, b.benefit_id, b.benefit_type, b.period_index, b.starts_period, b.benefit_source_key, b.baseline_trend_per_period, b.amount,
                   m.rate_cap, m.ramp,
                   (b.cash_realisation IS TRUE AND btrim(coalesce(b.evidence_ref, ''), E' \t\n\r\f\v') <> '') AS realised,
                   b.amount * coalesce((m.ramp ->> least(greatest(b.period_index - b.starts_period, 0), jsonb_array_length(m.ramp) - 1))::numeric, 1) AS ramped
            FROM cw_si si JOIN cw_scn s ON s.scenario_id = si.scenario_id
            JOIN cw_model m ON m.scenario_id = si.scenario_id AND m.initiative_id = si.initiative_id
            JOIN benefit_items b ON b.initiative_id = si.initiative_id AND b.period_index < s.h AND (b.recorded_at IS NULL OR b.recorded_at <= s.created_at)) x) y

-- @@ cw_flow
CREATE TEMP TABLE cw_flow AS
WITH per AS (
    SELECT si.scenario_id, si.initiative_id, s.h, s.q, g.t
    FROM cw_si si JOIN cw_scn s ON s.scenario_id = si.scenario_id CROSS JOIN LATERAL generate_series(0, s.h - 1) AS g(t)),
cst AS (SELECT scenario_id, initiative_id, t, sum(amount) AS costs FROM cw_cost WHERE cost_basis = 'planned' GROUP BY scenario_id, initiative_id, t),
bn AS (
    SELECT scenario_id, initiative_id, period_index AS t,
           sum(money) FILTER (WHERE class = 'cash') AS cash, sum(money) FILTER (WHERE class = 'revenue') AS revenue,
           sum(money) FILTER (WHERE class = 'avoided_cost_realised') AS avoided_cost_realised, sum(money) FILTER (WHERE class = 'capacity_converted') AS capacity_converted
    FROM cw_ben GROUP BY scenario_id, initiative_id, period_index)
SELECT z.*, z.cash + z.revenue + z.avoided_cost_realised + z.capacity_converted AS benefits, z.cash + z.revenue + z.avoided_cost_realised + z.capacity_converted - z.costs AS net,
       sum(z.cash + z.revenue + z.avoided_cost_realised + z.capacity_converted - z.costs) OVER (PARTITION BY z.scenario_id, z.initiative_id ORDER BY z.t) AS cumulative
FROM (SELECT per.scenario_id, per.initiative_id, per.h, per.q, per.t, coalesce(cst.costs, 0) AS costs, coalesce(bn.cash, 0) AS cash, coalesce(bn.revenue, 0) AS revenue,
             coalesce(bn.avoided_cost_realised, 0) AS avoided_cost_realised, coalesce(bn.capacity_converted, 0) AS capacity_converted
      FROM per LEFT JOIN cst ON cst.scenario_id = per.scenario_id AND cst.initiative_id = per.initiative_id AND cst.t = per.t
               LEFT JOIN bn ON bn.scenario_id = per.scenario_id AND bn.initiative_id = per.initiative_id AND bn.t = per.t) z

-- @@ cw_qpow
CREATE TEMP TABLE cw_qpow AS
WITH RECURSIVE r AS (
    SELECT scenario_id, 0 AS k, 1::numeric AS qp, q, h FROM cw_scn
    UNION ALL
    SELECT scenario_id, k + 1, qp * q, q, h FROM r WHERE k + 1 < h)
SELECT scenario_id, k, qp FROM r

-- @@ cw_dnum
CREATE TEMP TABLE cw_dnum AS
SELECT f.scenario_id, f.initiative_id, f.t, f.net, f.cumulative, sum(g.net * p.qp) AS dnum
FROM cw_flow f
JOIN cw_flow g ON g.scenario_id = f.scenario_id AND g.initiative_id = f.initiative_id AND g.t <= f.t
JOIN cw_qpow p ON p.scenario_id = f.scenario_id AND p.k = f.t - g.t
GROUP BY f.scenario_id, f.initiative_id, f.t, f.net, f.cumulative

-- @@ cw_index
CREATE INDEX cw_dnum_ix ON cw_dnum (scenario_id, initiative_id, t);
CREATE INDEX cw_cost_ix ON cw_cost (scenario_id, initiative_id, cost_basis);
CREATE INDEX cw_ben_ix ON cw_ben (scenario_id, initiative_id);
CREATE INDEX cw_qpow_ix ON cw_qpow (scenario_id, k);
ANALYZE cw_dnum;
ANALYZE cw_cost;
ANALYZE cw_ben;
ANALYZE cw_qpow;
ANALYZE cw_flow

-- @@ cw_init
CREATE TEMP TABLE cw_init AS
SELECT w.*,
       CASE WHEN w.has_rows THEN w.npv_num / w.npv_den END AS npv,
       CASE WHEN NOT w.has_rows THEN 'NO_FLOWS' WHEN w.last_neg IS NULL THEN 'NO_INVESTMENT' WHEN w.last_neg = w.h - 1 THEN 'NOT_RECOVERED' END AS simple_reason,
       CASE WHEN NOT w.has_rows THEN 'NO_FLOWS' WHEN w.last_neg_d IS NULL THEN 'NO_INVESTMENT' WHEN w.last_neg_d = w.h - 1 THEN 'NOT_RECOVERED' END AS disc_reason,
       CASE WHEN w.has_rows AND w.last_neg IS NOT NULL AND w.last_neg < w.h - 1 THEN w.last_neg + 1 END AS simple_t,
       CASE WHEN w.has_rows AND w.last_neg_d IS NOT NULL AND w.last_neg_d < w.h - 1 THEN w.last_neg_d + 1 END AS disc_t,
       CASE WHEN w.has_rows AND w.last_neg IS NOT NULL AND w.last_neg < w.h - 1
            THEN w.last_neg + (-w.c0) / (w.c1 - w.c0) END AS simple_i,
       CASE WHEN w.has_rows AND w.last_neg_d IS NOT NULL AND w.last_neg_d < w.h - 1
            THEN w.last_neg_d + (-w.d0 * w.q) / (w.d1 - w.d0 * w.q) END AS disc_i
FROM (SELECT v.*,
             (SELECT x.cumulative FROM cw_dnum x WHERE x.scenario_id = v.scenario_id AND x.initiative_id = v.initiative_id AND x.t = v.last_neg) AS c0,
             (SELECT x.cumulative FROM cw_dnum x WHERE x.scenario_id = v.scenario_id AND x.initiative_id = v.initiative_id AND x.t = v.last_neg + 1) AS c1,
             (SELECT x.dnum FROM cw_dnum x WHERE x.scenario_id = v.scenario_id AND x.initiative_id = v.initiative_id AND x.t = v.last_neg_d) AS d0,
             (SELECT x.dnum FROM cw_dnum x WHERE x.scenario_id = v.scenario_id AND x.initiative_id = v.initiative_id AND x.t = v.last_neg_d + 1) AS d1
      FROM (SELECT si.scenario_id, si.initiative_id, s.h, s.q,
                   (EXISTS (SELECT 1 FROM cw_cost c WHERE c.scenario_id = si.scenario_id AND c.initiative_id = si.initiative_id AND c.cost_basis = 'planned')
                    OR EXISTS (SELECT 1 FROM cw_ben b WHERE b.scenario_id = si.scenario_id AND b.initiative_id = si.initiative_id AND b.enters)) AS has_rows,
                   (SELECT max(x.t) FROM cw_dnum x WHERE x.scenario_id = si.scenario_id AND x.initiative_id = si.initiative_id AND x.cumulative < 0) AS last_neg,
                   (SELECT max(x.t) FROM cw_dnum x WHERE x.scenario_id = si.scenario_id AND x.initiative_id = si.initiative_id AND x.dnum < 0) AS last_neg_d,
                   (SELECT x.dnum FROM cw_dnum x WHERE x.scenario_id = si.scenario_id AND x.initiative_id = si.initiative_id AND x.t = s.h - 1) AS npv_num,
                   (SELECT p.qp FROM cw_qpow p WHERE p.scenario_id = si.scenario_id AND p.k = s.h - 1) AS npv_den
            FROM cw_si si JOIN cw_scn s ON s.scenario_id = si.scenario_id) v) w

-- @@ cw_exact
-- The exact rational of each initiative's NPV, reduced: the numerator and the denominator are scaled to integers by their decimal text (no power()) and divided by their gcd.
CREATE TEMP TABLE cw_exact AS
SELECT i.scenario_id, i.initiative_id,
       CASE WHEN i.has_rows THEN
           (CASE WHEN x.n_int < 0 THEN '-' ELSE '' END) || div(abs(x.n_int), gcd(x.n_int, x.d_int))::text ||
           CASE WHEN div(x.d_int, gcd(x.n_int, x.d_int)) = 1 THEN '' ELSE '/' || div(x.d_int, gcd(x.n_int, x.d_int))::text END
       END AS npv_exact
FROM cw_init i
CROSS JOIN LATERAL (SELECT (replace(i.npv_num::text, '.', '') || repeat('0', greatest(scale(i.npv_den) - scale(i.npv_num), 0)))::numeric AS n_int,
                           (replace(i.npv_den::text, '.', '') || repeat('0', greatest(scale(i.npv_num) - scale(i.npv_den), 0)))::numeric AS d_int) x

-- @@ cw_claim
CREATE TEMP TABLE cw_claim AS
SELECT b.scenario_id, b.benefit_source_key, b.period_index, b.initiative_id, b.benefit_id, b.class, b.enters, b.money AS claim,
       row_number() OVER (PARTITION BY b.scenario_id, b.benefit_source_key, b.period_index
                          ORDER BY b.money DESC, (NOT b.enters), b.initiative_id COLLATE "C", b.benefit_id COLLATE "C") AS rn,
       g.initiatives_in_key
FROM cw_ben b
JOIN (SELECT scenario_id, benefit_source_key, period_index, count(DISTINCT initiative_id) AS initiatives_in_key
      FROM cw_ben WHERE money IS NOT NULL AND benefit_source_key IS NOT NULL GROUP BY scenario_id, benefit_source_key, period_index) g
  ON g.scenario_id = b.scenario_id AND g.benefit_source_key = b.benefit_source_key AND g.period_index = b.period_index
WHERE b.money IS NOT NULL AND b.benefit_source_key IS NOT NULL

-- @@ cw_hours
CREATE TEMP TABLE cw_hours AS
SELECT b.scenario_id, b.benefit_source_key, b.period_index, b.initiative_id, b.benefit_id, b.ramped AS hours,
       row_number() OVER (PARTITION BY b.scenario_id, b.benefit_source_key, b.period_index ORDER BY b.ramped DESC, b.initiative_id COLLATE "C", b.benefit_id COLLATE "C") AS rn,
       g.initiatives_in_key
FROM cw_ben b
JOIN (SELECT scenario_id, benefit_source_key, period_index, count(DISTINCT initiative_id) AS initiatives_in_key
      FROM cw_ben WHERE benefit_type = 'capacity' AND benefit_source_key IS NOT NULL GROUP BY scenario_id, benefit_source_key, period_index) g
  ON g.scenario_id = b.scenario_id AND g.benefit_source_key = b.benefit_source_key AND g.period_index = b.period_index
WHERE b.benefit_type = 'capacity' AND b.benefit_source_key IS NOT NULL

-- @@ cw_dc
CREATE TEMP TABLE cw_dc AS
SELECT s.scenario_id, s.h,
       coalesce((SELECT sum(b.money) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.money IS NOT NULL), 0) AS planned,
       coalesce((SELECT sum(c.claim) FROM cw_claim c WHERE c.scenario_id = s.scenario_id AND c.initiatives_in_key >= 2 AND c.rn > 1), 0) AS removed,
       coalesce((SELECT sum(c.claim * p.qp) FROM cw_claim c JOIN cw_qpow p ON p.scenario_id = c.scenario_id AND p.k = s.h - 1 - c.period_index
                 WHERE c.scenario_id = s.scenario_id AND c.initiatives_in_key >= 2 AND c.rn > 1 AND c.enters), 0) AS pv_num,
       (SELECT p.qp FROM cw_qpow p WHERE p.scenario_id = s.scenario_id AND p.k = s.h - 1) AS pv_den,
       coalesce((SELECT sum(b.ramped) FROM cw_ben b WHERE b.scenario_id = s.scenario_id AND b.benefit_type = 'capacity'), 0) AS hours_planned,
       coalesce((SELECT sum(x.hours) FROM cw_hours x WHERE x.scenario_id = s.scenario_id AND x.initiatives_in_key >= 2 AND x.rn > 1), 0) AS hours_removed
FROM cw_scn s

-- @@ cw_scn_npv
CREATE TEMP TABLE cw_scn_npv AS
SELECT d.scenario_id, d.pv_den AS den, d.pv_num,
       (SELECT sum(i.npv_num) FROM cw_init i WHERE i.scenario_id = d.scenario_id AND i.has_rows) AS sum_num,
       (SELECT count(*) FROM cw_init i WHERE i.scenario_id = d.scenario_id AND i.has_rows) AS with_flows
FROM cw_dc d

-- @@ cw_cap
CREATE TEMP TABLE cw_cap AS
SELECT m.scenario_id, m.initiative_id, i.baseline_version AS approved_version, b.volume, b.minutes_per_case, m.target_minutes,
       CASE WHEN b.baseline_id IS NULL THEN 'NO_APPROVED_BASELINE' WHEN m.target_minutes IS NULL THEN 'NO_TARGET_ASSUMPTION' END AS reason,
       CASE WHEN b.baseline_id IS NOT NULL AND m.target_minutes IS NOT NULL THEN b.volume::numeric * (b.minutes_per_case - m.target_minutes) / 60 END AS hours
FROM cw_model m JOIN initiatives i ON i.initiative_id = m.initiative_id
LEFT JOIN process_baselines b ON b.initiative_id = i.initiative_id AND b.baseline_version = i.baseline_version

-- @@ cw_var
CREATE TEMP TABLE cw_var AS
SELECT si.scenario_id, si.initiative_id, i.baseline_version AS approved_version, least(s.h, p.matured) AS wend,
       (SELECT sum(c.amount) FROM cw_cost c WHERE c.scenario_id = si.scenario_id AND c.initiative_id = si.initiative_id AND c.cost_basis = 'planned'
          AND c.baseline_version = i.baseline_version AND c.t < least(s.h, p.matured)) AS planned_cost,
       (SELECT sum(c.amount) FROM cw_cost c WHERE c.scenario_id = si.scenario_id AND c.initiative_id = si.initiative_id AND c.cost_basis = 'actual' AND c.t < least(s.h, p.matured)) AS actual_cost,
       (SELECT count(*) FROM cw_cost c WHERE c.scenario_id = si.scenario_id AND c.initiative_id = si.initiative_id AND c.cost_basis = 'actual' AND c.t < least(s.h, p.matured)) AS actual_rows
FROM cw_si si JOIN cw_scn s ON s.scenario_id = si.scenario_id JOIN initiatives i ON i.initiative_id = si.initiative_id CROSS JOIN cw_p p

-- @@ cw_obs
CREATE TEMP TABLE cw_obs AS
SELECT z.benefit_id, z.measured_value
FROM (SELECT o.benefit_id, o.measured_value,
             row_number() OVER (PARTITION BY o.benefit_id ORDER BY o.observed_at DESC, coalesce(o.recorded_at, o.observed_at) DESC, o.benefit_observation_id COLLATE "C" DESC) AS rn
      FROM benefit_observations o CROSS JOIN cw_p p
      WHERE o.observed_at <= p.as_of AND coalesce(o.recorded_at, o.observed_at) <= p.as_of) z
WHERE z.rn = 1

-- @@ cw_real
CREATE TEMP TABLE cw_real AS
SELECT b.scenario_id, b.initiative_id, b.benefit_type,
       count(*) FILTER (WHERE b.period_index < p.matured AND o.benefit_id IS NOT NULL) AS compared,
       count(*) FILTER (WHERE b.period_index < p.matured AND o.benefit_id IS NULL) AS unobserved,
       sum(b.ramped) FILTER (WHERE b.period_index < p.matured AND o.benefit_id IS NOT NULL) AS planned,
       sum(o.measured_value) FILTER (WHERE b.period_index < p.matured AND o.benefit_id IS NOT NULL) AS observed,
       sum(b.baseline_trend_per_period) FILTER (WHERE b.period_index < p.matured AND o.benefit_id IS NOT NULL) AS trend,
       count(b.baseline_trend_per_period) FILTER (WHERE b.period_index < p.matured AND o.benefit_id IS NOT NULL) AS trend_rows
FROM cw_ben b CROSS JOIN cw_p p LEFT JOIN cw_obs o ON o.benefit_id = b.benefit_id
GROUP BY b.scenario_id, b.initiative_id, b.benefit_type

-- @@ cw_roadmap
CREATE TEMP TABLE cw_roadmap AS
WITH RECURSIVE chain(initiative_id, start_val, depth) AS (
    SELECT i.initiative_id, i.requested_start_period, 0 FROM initiatives i
    UNION ALL
    SELECT d.initiative_id, c.start_val + CASE WHEN d.dependency_type = 'finish_to_start' THEN pre.duration_periods ELSE 0 END + d.lag_periods, c.depth + 1
    FROM chain c JOIN dependencies d ON d.prerequisite_id = c.initiative_id JOIN initiatives pre ON pre.initiative_id = c.initiative_id
    WHERE c.depth < 100),
feas AS (SELECT initiative_id, max(start_val) AS feasible_start FROM chain GROUP BY initiative_id)
SELECT i.initiative_id, i.requested_start_period AS requested_start, i.duration_periods, i.deployment_period, f.feasible_start, f.feasible_start - i.requested_start_period AS delay,
       (SELECT min(d.dependency_id COLLATE "C")
        FROM dependencies d JOIN feas fp ON fp.initiative_id = d.prerequisite_id JOIN initiatives pre ON pre.initiative_id = d.prerequisite_id
        WHERE d.initiative_id = i.initiative_id AND f.feasible_start > i.requested_start_period
          AND fp.feasible_start + CASE WHEN d.dependency_type = 'finish_to_start' THEN pre.duration_periods ELSE 0 END + d.lag_periods = f.feasible_start) AS binding_dependency_id
FROM initiatives i JOIN feas f ON f.initiative_id = i.initiative_id

-- @@ cw_adopt
CREATE TEMP TABLE cw_adopt AS
SELECT z.initiative_id, z.observation_id, z.eligible_count, z.adopted_count
FROM (SELECT a.initiative_id, a.observation_id, a.eligible_count, a.adopted_count,
             row_number() OVER (PARTITION BY a.initiative_id ORDER BY a.observed_at DESC, coalesce(a.recorded_at, a.observed_at) DESC, a.observation_id COLLATE "C" DESC) AS rn
      FROM adoption_observations a CROSS JOIN cw_p p WHERE a.observed_at <= p.as_of AND coalesce(a.recorded_at, a.observed_at) <= p.as_of) z
WHERE z.rn = 1

-- @@ cw_train
CREATE TEMP TABLE cw_train AS
SELECT z.initiative_id, z.training_id, z.eligible_trainees, z.completed
FROM (SELECT t.initiative_id, t.training_id, t.eligible_trainees, t.completed,
             row_number() OVER (PARTITION BY t.initiative_id ORDER BY t.recorded_at DESC, coalesce(t.entered_at, t.recorded_at) DESC, t.training_id COLLATE "C" DESC) AS rn
      FROM training_completions t CROSS JOIN cw_p p WHERE t.recorded_at <= p.as_of AND coalesce(t.entered_at, t.recorded_at) <= p.as_of) z
WHERE z.rn = 1
