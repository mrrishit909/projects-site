-- ChangeWorks reference metrics: an independent recomputation, in SQL, of the leaves of expected.json that the business contracts name:
--   net cash flow (costs, benefits, net, cumulative, discounted, cumulative discounted), NPV, simple and discounted payback (integer and interpolated),
--   capacity released, adoption, training completion, cost variance, benefit realization (within a type), risk exposure, readiness, dependency delay
--   (feasible start, delay, binding dependency), the double-count residual, the scenario NPV total and the summary pools.
--
-- Independent of the Python domain and of any stored result: it reads only facts (initiatives, baselines, assumptions, scenarios and their pins, costs,
-- benefits and observations, dependencies, groups and assessments, adoption and training records, risks, allocations, the configuration) and nothing the
-- commands store (audit, results, expanded_costs, scores). One statement; it returns rows (path, value) where ``path`` is the leaf path in expected.json
-- (the nesting of ``flat()``) and ``value`` its text, NULL for null. tests/test_sql_reference.py compares every row with the expected leaf.
--
-- Parameter (psycopg): %(as_of)s timestamptz.   Helpers from 0002_constraints.sql: none are needed (formatting is done here).
-- Run it with ``SET jit = off``: the planner over-estimates the generate_series cross joins, and JIT-compiling that estimate costs seconds for a 10 ms statement.
--
-- Exactness: money and counts are NUMERIC and integers; every figure is rounded ONCE, by round() (half away from zero = ROUND_HALF_UP) at the declared
-- place (2 for money, 4 for paybacks / hours / readiness, 6 for proportions). The discount factor 1/(1+r)^t is never divided early: with q = 1 + r,
--   S_t = sum_{s<=t} net_s * q^(t-s)         (exact: only multiplications; S_t has the sign of the cumulative discounted flow and equals it times q^t)
--   NPV = S_(H-1) / q^(H-1)                  (ONE division, at the end)
--   discounted payback: first t with S_t >= 0, interpolated (t-1) + (-A*q) / (B - A*q) with A = S_(t-1), B = S_t   (= the contract formula, scaled by q^t)
-- q^k comes from power(numeric, integer), which PostgreSQL computes with a bounded number of digits; for the horizons of the fixtures (<= 12 periods at 6
-- decimals) it is exact. The test therefore compares the NPV with TOLERANCE 0.000001 USD against the exact rational (documented in the test); every other
-- figure is compared for equality.
WITH RECURSIVE
p AS (SELECT %(as_of)s::timestamptz AS as_of),
cfg AS (SELECT period_basis, period_start FROM dataset_config WHERE id = 1),
ini AS (SELECT * FROM initiatives),
-- ---- scenarios, rates, pins ---------------------------------------------------------------------------------------------------------------------------
rate AS (
    SELECT s.scenario_id, s.horizon_periods AS h, s.baseline_version,
           CASE WHEN s.rate_basis = (SELECT period_basis FROM cfg) THEN s.discount_rate
                ELSE (SELECT a.value::numeric FROM assumption_versions a WHERE a.assumption_id = s.rate_conversion_assumption_id) END AS r
    FROM scenario_versions s
),
si AS (SELECT si.scenario_id, si.initiative_id, rt.h, 1 + rt.r AS q FROM scenario_initiatives si JOIN rate rt USING (scenario_id)),
pick AS (       -- the assumption version a scenario uses: the pinned one (highest pinned version), otherwise the latest version
    SELECT DISTINCT ON (si.scenario_id, si.initiative_id, a.name) si.scenario_id, si.initiative_id, a.name, a.assumption_id, a.value, a.value_list,
           a.staffing_change_evidence_ref
    FROM si JOIN assumption_versions a ON a.initiative_id = si.initiative_id
    LEFT JOIN scenario_pins sp ON sp.scenario_id = si.scenario_id AND sp.assumption_id = a.assumption_id
    ORDER BY si.scenario_id, si.initiative_id, a.name, (sp.assumption_id IS NOT NULL) DESC, a.version_number DESC
),
ramp AS (SELECT scenario_id, initiative_id, value_list FROM pick WHERE name = 'adoption_ramp' AND value_list IS NOT NULL),
conv AS (SELECT scenario_id, initiative_id, value::numeric AS rate_cap FROM pick
         WHERE name = 'capacity_hourly_rate' AND value IS NOT NULL AND coalesce(staffing_change_evidence_ref, '') <> ''),
per AS (SELECT si.scenario_id, si.initiative_id, si.h, si.q, g AS t FROM si, generate_series(0, si.h - 1) g),
-- ---- costs: one-time as is, recurring expanded into one row per period of the half-open range -----------------------------------------------------------
cost_rows AS (
    SELECT c.initiative_id, c.cost_id, c.cost_basis, c.baseline_version, c.amount, g AS t
    FROM cost_items c, generate_series(CASE WHEN c.cost_type = 'one_time' THEN c.period_index ELSE c.start_period END,
                                       CASE WHEN c.cost_type = 'one_time' THEN c.period_index ELSE c.end_period - 1 END) g
),
-- ---- benefits within the horizon: ramped from each row's own starts_period (the last value held), by class ---------------------------------------------
ben AS (
    SELECT si.scenario_id, si.initiative_id, si.h, b.benefit_id, b.benefit_type, b.period_index, b.cash_realisation, b.evidence_ref, b.benefit_source_key,
           b.baseline_trend_per_period,
           b.amount * coalesce((SELECT (r.value_list ->> least(greatest(b.period_index - b.starts_period, 0), jsonb_array_length(r.value_list) - 1))::numeric
                                FROM ramp r WHERE r.scenario_id = si.scenario_id AND r.initiative_id = si.initiative_id), 1) AS ramped,
           (SELECT c.rate_cap FROM conv c WHERE c.scenario_id = si.scenario_id AND c.initiative_id = si.initiative_id) AS rate_cap
    FROM si JOIN benefit_items b ON b.initiative_id = si.initiative_id AND b.period_index < si.h
),
benc AS (
    SELECT ben.*,
           (benefit_type IN ('cash', 'revenue') OR (benefit_type = 'avoided_cost' AND cash_realisation IS TRUE AND coalesce(evidence_ref, '') <> '')
            OR (benefit_type = 'capacity' AND rate_cap IS NOT NULL)) AS enters,
           CASE WHEN benefit_type IN ('cash', 'revenue') THEN ramped
                WHEN benefit_type = 'avoided_cost' AND cash_realisation IS TRUE AND coalesce(evidence_ref, '') <> '' THEN ramped
                WHEN benefit_type = 'capacity' AND rate_cap IS NOT NULL THEN ramped * rate_cap ELSE 0 END AS cash_amount,
           CASE WHEN benefit_type = 'capacity' THEN CASE WHEN rate_cap IS NOT NULL THEN ramped * rate_cap END ELSE ramped END AS claim     -- money class only
    FROM ben
),
-- ---- the dated flows ---------------------------------------------------------------------------------------------------------------------------------
flow AS (
    SELECT per.scenario_id, per.initiative_id, per.h, per.q, per.t,
           coalesce((SELECT sum(c.amount) FROM cost_rows c WHERE c.initiative_id = per.initiative_id AND c.cost_basis = 'planned' AND c.t = per.t), 0) AS costs,
           coalesce((SELECT sum(b.cash_amount) FROM benc b WHERE b.scenario_id = per.scenario_id AND b.initiative_id = per.initiative_id
                     AND b.period_index = per.t AND b.enters), 0) AS benefits
    FROM per
),
has_rows AS (
    SELECT si.scenario_id, si.initiative_id,
           EXISTS (SELECT 1 FROM cost_rows c WHERE c.initiative_id = si.initiative_id AND c.cost_basis = 'planned' AND c.t < si.h)
           OR EXISTS (SELECT 1 FROM benc b WHERE b.scenario_id = si.scenario_id AND b.initiative_id = si.initiative_id AND b.enters) AS yes
    FROM si
),
cum AS (
    SELECT f.*, f.benefits - f.costs AS net, sum(f.benefits - f.costs) OVER (PARTITION BY f.scenario_id, f.initiative_id ORDER BY f.t) AS cumulative
    FROM flow f
),
sc_t AS (   -- S_t = sum_{s<=t} net_s * q^(t-s)
    SELECT a.scenario_id, a.initiative_id, a.t, a.q, a.h, a.net, a.cumulative, a.costs, a.benefits,
           (SELECT sum(b.net * power(a.q, a.t - b.t)) FROM cum b WHERE b.scenario_id = a.scenario_id AND b.initiative_id = a.initiative_id AND b.t <= a.t) AS s
    FROM cum a
),
pay AS (
    SELECT c.scenario_id, c.initiative_id, c.h,
           min(c.t) FILTER (WHERE c.cumulative >= 0) AS simple_t,
           min(c.t) FILTER (WHERE c.s >= 0) AS disc_t
    FROM sc_t c GROUP BY c.scenario_id, c.initiative_id, c.h
),
pay_i AS (
    SELECT pay.scenario_id, pay.initiative_id, hr.yes, pay.simple_t, pay.disc_t,
           CASE WHEN pay.simple_t = 0 THEN 0::numeric
                ELSE (pay.simple_t - 1) + (-p0.cumulative) / (p1.cumulative - p0.cumulative) END AS simple_i,
           CASE WHEN pay.disc_t = 0 THEN 0::numeric
                ELSE (pay.disc_t - 1) + (-d0.s * d1.q) / (d1.s - d0.s * d1.q) END AS disc_i
    FROM pay
    JOIN has_rows hr USING (scenario_id, initiative_id)
    LEFT JOIN sc_t p0 ON p0.scenario_id = pay.scenario_id AND p0.initiative_id = pay.initiative_id AND p0.t = pay.simple_t - 1
    LEFT JOIN sc_t p1 ON p1.scenario_id = pay.scenario_id AND p1.initiative_id = pay.initiative_id AND p1.t = pay.simple_t
    LEFT JOIN sc_t d0 ON d0.scenario_id = pay.scenario_id AND d0.initiative_id = pay.initiative_id AND d0.t = pay.disc_t - 1
    LEFT JOIN sc_t d1 ON d1.scenario_id = pay.scenario_id AND d1.initiative_id = pay.initiative_id AND d1.t = pay.disc_t
),
npv AS (
    SELECT l.scenario_id, l.initiative_id, hr.yes, l.s / power(l.q, l.h - 1) AS npv, l.s AS s_last, power(l.q, l.h - 1) AS denom
    FROM sc_t l JOIN has_rows hr USING (scenario_id, initiative_id) WHERE l.t = l.h - 1
),
-- ---- calendar: a period is matured when its end (the start of the next period) is <= as_of ----------------------------------------------------------
matured_n AS (
    SELECT si.scenario_id, si.initiative_id,
           (SELECT count(*) FROM generate_series(0, si.h - 1) g, cfg, p
            WHERE ((cfg.period_start + g * CASE WHEN cfg.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END
                    + CASE WHEN cfg.period_basis = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::timestamp AT TIME ZONE 'UTC') <= p.as_of) AS wend
    FROM si
),
is_matured AS (
    SELECT g AS t, (((SELECT period_start FROM cfg) + (g + 1) * CASE WHEN (SELECT period_basis FROM cfg) = 'annual' THEN interval '1 year' ELSE interval '1 month' END)::timestamp
                    AT TIME ZONE 'UTC') <= (SELECT as_of FROM p) AS m
    FROM generate_series(0, (SELECT coalesce(max(horizon_periods), 0) FROM scenario_versions)) g
),
-- ---- capacity released, cost variance -----------------------------------------------------------------------------------------------------------------
cap AS (
    SELECT si.scenario_id, si.initiative_id, i.baseline_version AS ibv, b.volume, b.minutes_per_case, tg.value AS target,
           CASE WHEN i.baseline_version IS NULL OR b.baseline_id IS NULL THEN 'NO_APPROVED_BASELINE'
                WHEN tg.assumption_id IS NULL OR tg.value IS NULL THEN 'NO_TARGET_ASSUMPTION' END AS reason,
           CASE WHEN b.baseline_id IS NOT NULL AND tg.value IS NOT NULL THEN round(b.volume::numeric * (b.minutes_per_case - tg.value::numeric) / 60, 4) END AS hours
    FROM si JOIN ini i ON i.initiative_id = si.initiative_id
    LEFT JOIN process_baselines b ON b.initiative_id = i.initiative_id AND b.baseline_version = i.baseline_version
    LEFT JOIN pick tg ON tg.scenario_id = si.scenario_id AND tg.initiative_id = si.initiative_id AND tg.name = 'target_minutes_per_case'
),
var AS (
    SELECT m.scenario_id, m.initiative_id, i.baseline_version AS bv, m.wend,
           (SELECT sum(c.amount) FROM cost_rows c WHERE c.initiative_id = m.initiative_id AND c.cost_basis = 'planned' AND c.baseline_version = i.baseline_version
            AND c.t < m.wend) AS planned_sum,
           (SELECT sum(c.amount) FROM cost_rows c WHERE c.initiative_id = m.initiative_id AND c.cost_basis = 'actual' AND c.t < m.wend) AS actual_sum,
           (SELECT count(*) FROM cost_rows c WHERE c.initiative_id = m.initiative_id AND c.cost_basis = 'actual' AND c.t < m.wend) AS actual_rows
    FROM matured_n m JOIN ini i ON i.initiative_id = m.initiative_id
),
-- ---- benefit realization within ONE type, matured periods with an observation only ----------------------------------------------------------------------
obs AS (        -- the latest observation of each benefit at or before as_of
    SELECT DISTINCT ON (o.benefit_id) o.benefit_id, o.measured_value
    FROM benefit_observations o, p WHERE o.observed_at <= p.as_of ORDER BY o.benefit_id, o.observed_at DESC, o.benefit_observation_id DESC
),
rz AS (
    SELECT b.scenario_id, b.initiative_id, b.benefit_type,
           count(*) FILTER (WHERE mt.m AND o.benefit_id IS NOT NULL) AS comp,
           count(*) FILTER (WHERE mt.m AND o.benefit_id IS NULL) AS unobs,
           sum(b.ramped) FILTER (WHERE mt.m AND o.benefit_id IS NOT NULL) AS planned,
           sum(o.measured_value) FILTER (WHERE mt.m AND o.benefit_id IS NOT NULL) AS observed,
           sum(b.baseline_trend_per_period) FILTER (WHERE mt.m AND o.benefit_id IS NOT NULL) AS trend,
           count(b.baseline_trend_per_period) FILTER (WHERE mt.m AND o.benefit_id IS NOT NULL) AS trend_rows
    FROM ben b JOIN is_matured mt ON mt.t = b.period_index LEFT JOIN obs o ON o.benefit_id = b.benefit_id
    GROUP BY b.scenario_id, b.initiative_id, b.benefit_type
),
-- ---- adoption, training, risk, readiness ---------------------------------------------------------------------------------------------------------------
ad AS (SELECT DISTINCT ON (a.initiative_id) a.* FROM adoption_observations a, p WHERE a.observed_at <= p.as_of ORDER BY a.initiative_id, a.observed_at DESC, a.observation_id DESC),
tr AS (SELECT DISTINCT ON (t.initiative_id) t.* FROM training_completions t, p WHERE t.recorded_at <= p.as_of ORDER BY t.initiative_id, t.recorded_at DESC, t.training_id DESC),
rk AS (SELECT initiative_id, round(sum(probability * impact), 2) AS exposure FROM risk_items GROUP BY initiative_id),
rd AS (SELECT DISTINCT ON (a.group_id, a.dimension) a.* FROM readiness_assessments a, p WHERE a.assessed_at <= p.as_of
       ORDER BY a.group_id, a.dimension, a.assessed_at DESC, a.assessment_id DESC),
rdg AS (SELECT group_id, round(sum(weight * score) / sum(weight), 4) AS score FROM rd GROUP BY group_id),
-- ---- roadmap: feasible start = the longest chain of (prerequisite start + [duration if finish_to_start] + lag), never earlier than the requested start --------
chains(initiative_id, start_val, depth) AS (
    SELECT initiative_id, requested_start_period, 0 FROM initiatives
    UNION ALL
    SELECT d.initiative_id, c.start_val + CASE WHEN d.dependency_type = 'finish_to_start' THEN pre.duration_periods ELSE 0 END + d.lag_periods, c.depth + 1
    FROM chains c JOIN dependencies d ON d.prerequisite_id = c.initiative_id JOIN initiatives pre ON pre.initiative_id = c.initiative_id
    WHERE c.depth < 100
),
feas AS (SELECT initiative_id, max(start_val) AS fs FROM chains GROUP BY initiative_id),
bind AS (
    SELECT d.initiative_id, min(d.dependency_id COLLATE "C") AS dep_id
    FROM dependencies d JOIN feas fp ON fp.initiative_id = d.prerequisite_id JOIN initiatives pre ON pre.initiative_id = d.prerequisite_id
    JOIN feas fi ON fi.initiative_id = d.initiative_id JOIN initiatives i ON i.initiative_id = d.initiative_id
    WHERE fp.fs + CASE WHEN d.dependency_type = 'finish_to_start' THEN pre.duration_periods ELSE 0 END + d.lag_periods = fi.fs AND fi.fs > i.requested_start_period
    GROUP BY d.initiative_id
),
-- ---- double count: claims sharing a benefit_source_key in one period across >= 2 initiatives count once, at the largest claim -------------------------
dc_g AS (
    SELECT scenario_id, benefit_source_key, period_index, sum(claim) - max(claim) AS removed
    FROM benc WHERE claim IS NOT NULL AND benefit_source_key IS NOT NULL
    GROUP BY scenario_id, benefit_source_key, period_index HAVING count(DISTINCT initiative_id) >= 2
),
dc AS (
    SELECT s.scenario_id, coalesce((SELECT sum(claim) FROM benc b WHERE b.scenario_id = s.scenario_id AND b.claim IS NOT NULL), 0) AS planned,
           coalesce((SELECT sum(removed) FROM dc_g g WHERE g.scenario_id = s.scenario_id), 0) AS removed
    FROM scenario_versions s
),
first_sc AS (SELECT scenario_id FROM scenario_versions ORDER BY scenario_id COLLATE "C" LIMIT 1),
out(path, val) AS (
    SELECT 'empty_population', (NOT EXISTS (SELECT 1 FROM initiatives))::text
    UNION ALL  -- cash flow rows
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.cash_flow[' || t || '].' || k, v
    FROM sc_t, LATERAL (VALUES ('costs', round(costs, 2)::text), ('cash_benefits', round(benefits, 2)::text), ('net_cash_flow', round(net, 2)::text),
                               ('cumulative', round(cumulative, 2)::text), ('discounted_cash_flow', round(net / power(q, t), 2)::text),
                               ('cumulative_discounted', round(s / power(q, t), 2)::text)) x(k, v)
    UNION ALL  -- NPV, paybacks
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.npv.value', CASE WHEN yes THEN round(npv, 2)::text END FROM npv
    UNION ALL
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.npv.value_6dp', CASE WHEN yes THEN round(npv, 6)::text END FROM npv
    UNION ALL
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.payback.' || k, v
    FROM pay_i, LATERAL (VALUES ('simple.period', CASE WHEN yes THEN simple_t::text END), ('simple.interpolated', CASE WHEN yes THEN round(simple_i, 4)::text END),
                                ('discounted.period', CASE WHEN yes THEN disc_t::text END), ('discounted.interpolated', CASE WHEN yes THEN round(disc_i, 4)::text END)) x(k, v)
    UNION ALL  -- capacity released
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.capacity_released.' || k, v
    FROM cap, LATERAL (VALUES ('hours', hours::text), ('reason', reason)) x(k, v)
    UNION ALL  -- cost variance
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.cost_variance.' || k, v
    FROM var, LATERAL (VALUES
        ('window.to_period', wend::text),
        ('approved_baseline_cost', CASE WHEN bv IS NOT NULL AND wend > 0 THEN round(coalesce(planned_sum, 0), 2)::text END),
        ('actual_cost', CASE WHEN bv IS NOT NULL AND wend > 0 AND actual_rows > 0 THEN round(actual_sum, 2)::text END),
        ('variance', CASE WHEN bv IS NOT NULL AND wend > 0 AND actual_rows > 0 THEN round(actual_sum - coalesce(planned_sum, 0), 2)::text END),
        ('reason', CASE WHEN bv IS NULL THEN 'NO_APPROVED_BASELINE' WHEN wend = 0 THEN 'NO_MATURED_PERIOD' WHEN actual_rows = 0 THEN 'NO_ACTUALS' END)) x(k, v)
    UNION ALL  -- benefit realization
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.benefit_realization.' || benefit_type || '.' || k, v
    FROM rz, LATERAL (VALUES
        ('planned_comparable', CASE WHEN comp > 0 THEN round(planned, 2)::text END),
        ('observed_comparable', CASE WHEN comp > 0 THEN round(observed, 2)::text END),
        ('realization', CASE WHEN comp > 0 AND planned <> 0 THEN round(observed / planned, 6)::text END),
        ('baseline_trend', CASE WHEN trend_rows > 0 THEN round(trend, 2)::text END),
        ('observed_above_trend', CASE WHEN trend_rows > 0 AND comp > 0 THEN round(observed - trend, 2)::text END)) x(k, v)
    WHERE comp > 0 OR unobs > 0
    UNION ALL  -- double count and the scenario NPV total
    SELECT 'metrics.scenarios.' || scenario_id || '.double_count.' || k, v
    FROM dc, LATERAL (VALUES ('planned_benefits', round(planned, 2)::text), ('attributable_benefits', round(planned - removed, 2)::text), ('residual', round(removed, 2)::text)) x(k, v)
    UNION ALL
    SELECT 'metrics.scenarios.' || s.scenario_id || '.npv_total.value', (SELECT round(sum(n.s_last) / max(n.denom), 2)::text FROM npv n WHERE n.yes AND n.scenario_id = s.scenario_id)
    FROM scenario_versions s
    UNION ALL  -- adoption, training, risk, roadmap (scenario independent)
    SELECT 'metrics.initiatives.' || i.initiative_id || '.adoption.' || k, v
    FROM ini i LEFT JOIN ad ON ad.initiative_id = i.initiative_id,
         LATERAL (VALUES ('adoption_rate', CASE WHEN ad.eligible_count > 0 THEN round(ad.adopted_count::numeric / ad.eligible_count, 6)::text END),
                         ('eligible_count', ad.eligible_count::text), ('adopted_count', ad.adopted_count::text)) x(k, v)
    UNION ALL
    SELECT 'metrics.initiatives.' || i.initiative_id || '.training.' || k, v
    FROM ini i LEFT JOIN tr ON tr.initiative_id = i.initiative_id,
         LATERAL (VALUES ('training_completion', CASE WHEN tr.eligible_trainees > 0 THEN round(tr.completed::numeric / tr.eligible_trainees, 6)::text END),
                         ('eligible_trainees', tr.eligible_trainees::text), ('completed', tr.completed::text)) x(k, v)
    UNION ALL
    SELECT 'metrics.initiatives.' || i.initiative_id || '.risk.risk_exposure', rk.exposure::text FROM ini i LEFT JOIN rk ON rk.initiative_id = i.initiative_id
    UNION ALL
    SELECT 'metrics.initiatives.' || i.initiative_id || '.roadmap.' || k, v
    FROM ini i JOIN feas f ON f.initiative_id = i.initiative_id LEFT JOIN bind b ON b.initiative_id = i.initiative_id,
         LATERAL (VALUES ('dependency_feasible_start', f.fs::text), ('dependency_delay', (f.fs - i.requested_start_period)::text), ('binding_dependency_id', b.dep_id)) x(k, v)
    UNION ALL  -- readiness
    SELECT 'metrics.groups.' || g.group_id || '.readiness_score', rdg.score::text FROM stakeholder_groups g LEFT JOIN rdg ON rdg.group_id = g.group_id
    UNION ALL  -- summary (pools only what can be pooled)
    SELECT 'metrics.summary.npv_total', (SELECT round(sum(n.s_last) / max(n.denom), 2)::text FROM npv n WHERE n.yes AND n.scenario_id = (SELECT scenario_id FROM first_sc))
    UNION ALL
    SELECT 'metrics.summary.double_count_residual', (SELECT round(removed, 2)::text FROM dc WHERE scenario_id = (SELECT scenario_id FROM first_sc)
                                                    AND EXISTS (SELECT 1 FROM scenario_initiatives si2 WHERE si2.scenario_id = dc.scenario_id))
    UNION ALL
    SELECT 'metrics.summary.adoption_rate', (SELECT round(sum(adopted_count)::numeric / sum(eligible_count), 6)::text FROM ad WHERE eligible_count > 0)
    UNION ALL
    SELECT 'metrics.summary.training_completion', (SELECT round(sum(completed)::numeric / sum(eligible_trainees), 6)::text FROM tr WHERE eligible_trainees > 0)
    UNION ALL
    SELECT 'metrics.summary.risk_exposure_total', (SELECT sum(exposure)::text FROM rk)
    UNION ALL
    SELECT 'metrics.summary.capacity_released_hours_total', (SELECT sum(hours)::text FROM cap WHERE hours IS NOT NULL AND scenario_id = (SELECT scenario_id FROM first_sc))
)
SELECT path, val FROM out ORDER BY path
