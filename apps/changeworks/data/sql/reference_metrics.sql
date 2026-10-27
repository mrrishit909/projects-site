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
-- place (2 for money, 4 for paybacks / hours / readiness, 6 for proportions); a total is the sum of the exact amounts, never of rounded rows (R9-07). The
-- discount factor 1/(1+r)^t is never divided early: with q = 1 + r, built by multiplication only (S_t and q^t are recursive products, exact in NUMERIC),
--   S_t = S_(t-1) * q + net_t                (S_t has the sign of the cumulative discounted flow and equals it times q^t)
--   NPV = S_(H-1) / q^(H-1)                  (ONE division, at the end)
--   discounted payback: the last crossing of S (see below), interpolated (t-1) + (-A*q) / (B - A*q) with A = S_(t-1), B = S_t   (= the contract formula, scaled by q^t)
-- The only inexact step is the final division, which PostgreSQL carries to at least 16 significant digits; the documented bound is: the 6-place NPV is within
-- 0.000001 USD of the exact rational for horizons up to 36 periods and amounts of up to 14 integer digits (tests/test_sql_reference.py checks the world's 36
-- periods and a 14-digit case), and the test compares the NPV with that TOLERANCE; every other figure is compared for equality.
--
-- Review-9 rules (contract D-09): a scenario uses the cost and benefit rows recorded by its created_at and the pinned assumption versions, else the latest
-- created by then (R9-01); evidence is non-blank text (R9-04); payback is the last crossing with the reasons NO_INVESTMENT / NOT_RECOVERED / NO_FLOWS (R9-12);
-- observations count when recorded by as_of (R9-11); observed_above_trend needs a trend on every compared row (R9-13); the portfolio NPV is attributable:
-- the sum of the initiative NPVs less the present value of the shared claims that count twice (R9-02); hours are a second double-count rule (R9-03).
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
pick AS (       -- the assumption version a scenario uses: the pinned one (highest pinned version), otherwise the latest version created by the scenario's created_at
    SELECT DISTINCT ON (si.scenario_id, si.initiative_id, a.name) si.scenario_id, si.initiative_id, a.name, a.assumption_id, a.value, a.value_list,
           a.staffing_change_evidence_ref
    FROM si JOIN scenario_versions sv ON sv.scenario_id = si.scenario_id
    JOIN assumption_versions a ON a.initiative_id = si.initiative_id
    LEFT JOIN scenario_pins sp ON sp.scenario_id = si.scenario_id AND sp.assumption_id = a.assumption_id
    WHERE sp.assumption_id IS NOT NULL OR a.created_at <= sv.created_at
    ORDER BY si.scenario_id, si.initiative_id, a.name, (sp.assumption_id IS NOT NULL) DESC, a.version_number DESC
),
ramp AS (SELECT scenario_id, initiative_id, value_list FROM pick WHERE name = 'adoption_ramp' AND value_list IS NOT NULL),
conv AS (SELECT scenario_id, initiative_id, value::numeric AS rate_cap FROM pick
         WHERE name = 'capacity_hourly_rate' AND value IS NOT NULL AND btrim(coalesce(staffing_change_evidence_ref, ''), E' \t\n\r\f\v') <> ''),
per AS (SELECT si.scenario_id, si.initiative_id, si.h, si.q, g AS t FROM si, generate_series(0, si.h - 1) g),
-- ---- costs: one-time as is, recurring expanded into one row per period of the half-open range -----------------------------------------------------------
cost_rows AS (      -- only the rows recorded by the scenario's created_at (rows with no recorded_at belong to the loaded world)
    SELECT si.scenario_id, c.initiative_id, c.cost_id, c.cost_basis, c.baseline_version, c.amount, g AS t
    FROM si JOIN scenario_versions sv ON sv.scenario_id = si.scenario_id
    JOIN cost_items c ON c.initiative_id = si.initiative_id AND (c.recorded_at IS NULL OR c.recorded_at <= sv.created_at),
         generate_series(CASE WHEN c.cost_type = 'one_time' THEN c.period_index ELSE c.start_period END,
                         CASE WHEN c.cost_type = 'one_time' THEN c.period_index ELSE c.end_period - 1 END) g
),
-- ---- benefits within the horizon: ramped from each row's own starts_period (the last value held), by class ---------------------------------------------
ben AS (
    SELECT si.scenario_id, si.initiative_id, si.h, b.benefit_id, b.benefit_type, b.period_index, b.cash_realisation, b.evidence_ref, b.benefit_source_key,
           b.baseline_trend_per_period,
           b.amount * coalesce((SELECT (r.value_list ->> least(greatest(b.period_index - b.starts_period, 0), jsonb_array_length(r.value_list) - 1))::numeric
                                FROM ramp r WHERE r.scenario_id = si.scenario_id AND r.initiative_id = si.initiative_id), 1) AS ramped,
           (SELECT c.rate_cap FROM conv c WHERE c.scenario_id = si.scenario_id AND c.initiative_id = si.initiative_id) AS rate_cap
    FROM si JOIN scenario_versions sv ON sv.scenario_id = si.scenario_id
    JOIN benefit_items b ON b.initiative_id = si.initiative_id AND b.period_index < si.h AND (b.recorded_at IS NULL OR b.recorded_at <= sv.created_at)
),
benc AS (
    SELECT ben.*,
           (benefit_type IN ('cash', 'revenue') OR (benefit_type = 'avoided_cost' AND cash_realisation IS TRUE AND btrim(coalesce(evidence_ref, ''), E' \t\n\r\f\v') <> '')
            OR (benefit_type = 'capacity' AND rate_cap IS NOT NULL)) AS enters,
           CASE WHEN benefit_type IN ('cash', 'revenue') THEN ramped
                WHEN benefit_type = 'avoided_cost' AND cash_realisation IS TRUE AND btrim(coalesce(evidence_ref, ''), E' \t\n\r\f\v') <> '' THEN ramped
                WHEN benefit_type = 'capacity' AND rate_cap IS NOT NULL THEN ramped * rate_cap ELSE 0 END AS cash_amount,
           CASE WHEN benefit_type = 'capacity' THEN CASE WHEN rate_cap IS NOT NULL THEN ramped * rate_cap END ELSE ramped END AS claim     -- money class only
    FROM ben
),
-- ---- the dated flows ---------------------------------------------------------------------------------------------------------------------------------
cost_t AS (SELECT scenario_id, initiative_id, t, sum(amount) AS amt FROM cost_rows WHERE cost_basis = 'planned' GROUP BY scenario_id, initiative_id, t),
ben_t AS (SELECT scenario_id, initiative_id, period_index AS t, sum(cash_amount) AS amt FROM benc WHERE enters GROUP BY scenario_id, initiative_id, period_index),
flow AS (
    SELECT per.scenario_id, per.initiative_id, per.h, per.q, per.t, coalesce(c.amt, 0) AS costs, coalesce(b.amt, 0) AS benefits
    FROM per LEFT JOIN cost_t c ON c.scenario_id = per.scenario_id AND c.initiative_id = per.initiative_id AND c.t = per.t
             LEFT JOIN ben_t b ON b.scenario_id = per.scenario_id AND b.initiative_id = per.initiative_id AND b.t = per.t
),
has_rows AS (
    SELECT si.scenario_id, si.initiative_id,
           EXISTS (SELECT 1 FROM cost_rows c WHERE c.scenario_id = si.scenario_id AND c.initiative_id = si.initiative_id AND c.cost_basis = 'planned' AND c.t < si.h)
           OR EXISTS (SELECT 1 FROM benc b WHERE b.scenario_id = si.scenario_id AND b.initiative_id = si.initiative_id AND b.enters) AS yes
    FROM si
),
cum AS (
    SELECT f.*, f.benefits - f.costs AS net, sum(f.benefits - f.costs) OVER (PARTITION BY f.scenario_id, f.initiative_id ORDER BY f.t) AS cumulative
    FROM flow f
),
sc_t AS (   -- S_t = S_(t-1) * q + net_t and q^t, by multiplication only (exact); the cumulative discounted flow is S_t / q^t
    WITH RECURSIVE r AS (
        SELECT c.scenario_id, c.initiative_id, c.t, c.q, c.h, c.net, c.cumulative, c.costs, c.benefits, c.net AS s, 1::numeric AS qp
        FROM cum c WHERE c.t = 0
        UNION ALL
        SELECT c.scenario_id, c.initiative_id, c.t, c.q, c.h, c.net, c.cumulative, c.costs, c.benefits, r.s * c.q + c.net, r.qp * c.q
        FROM r JOIN cum c ON c.scenario_id = r.scenario_id AND c.initiative_id = r.initiative_id AND c.t = r.t + 1
    )
    SELECT * FROM r
),
pay AS (    -- R9-12: the last crossing: the first period after the last negative cumulative, if the series does not end negative; never negative: no investment
    SELECT c.scenario_id, c.initiative_id, c.h,
           max(c.t) FILTER (WHERE c.cumulative < 0) AS last_neg,
           max(c.t) FILTER (WHERE c.s < 0) AS last_neg_d
    FROM sc_t c GROUP BY c.scenario_id, c.initiative_id, c.h
),
pay_i AS (
    SELECT pay.scenario_id, pay.initiative_id, hr.yes,
           CASE WHEN pay.last_neg IS NOT NULL AND pay.last_neg < pay.h - 1 THEN pay.last_neg + 1 END AS simple_t,
           CASE WHEN pay.last_neg_d IS NOT NULL AND pay.last_neg_d < pay.h - 1 THEN pay.last_neg_d + 1 END AS disc_t,
           CASE WHEN NOT hr.yes THEN 'NO_FLOWS' WHEN pay.last_neg IS NULL THEN 'NO_INVESTMENT' WHEN pay.last_neg = pay.h - 1 THEN 'NOT_RECOVERED' END AS simple_reason,
           CASE WHEN NOT hr.yes THEN 'NO_FLOWS' WHEN pay.last_neg_d IS NULL THEN 'NO_INVESTMENT' WHEN pay.last_neg_d = pay.h - 1 THEN 'NOT_RECOVERED' END AS disc_reason,
           (pay.last_neg) + (-p0.cumulative) / (p1.cumulative - p0.cumulative) AS simple_i,
           (pay.last_neg_d) + (-d0.s * d1.q) / (d1.s - d0.s * d1.q) AS disc_i
    FROM pay
    JOIN has_rows hr USING (scenario_id, initiative_id)
    LEFT JOIN sc_t p0 ON p0.scenario_id = pay.scenario_id AND p0.initiative_id = pay.initiative_id AND p0.t = pay.last_neg
    LEFT JOIN sc_t p1 ON p1.scenario_id = pay.scenario_id AND p1.initiative_id = pay.initiative_id AND p1.t = pay.last_neg + 1
    LEFT JOIN sc_t d0 ON d0.scenario_id = pay.scenario_id AND d0.initiative_id = pay.initiative_id AND d0.t = pay.last_neg_d
    LEFT JOIN sc_t d1 ON d1.scenario_id = pay.scenario_id AND d1.initiative_id = pay.initiative_id AND d1.t = pay.last_neg_d + 1
),
npv AS (
    SELECT l.scenario_id, l.initiative_id, hr.yes, l.s / l.qp AS npv, l.s AS s_last, l.qp AS denom
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
           CASE WHEN b.baseline_id IS NOT NULL AND tg.value IS NOT NULL THEN round(b.volume::numeric * (b.minutes_per_case - tg.value::numeric) / 60, 4) END AS hours,
           CASE WHEN b.baseline_id IS NOT NULL AND tg.value IS NOT NULL THEN b.volume::numeric * (b.minutes_per_case - tg.value::numeric) / 60 END AS hours_x
    FROM si JOIN ini i ON i.initiative_id = si.initiative_id
    LEFT JOIN process_baselines b ON b.initiative_id = i.initiative_id AND b.baseline_version = i.baseline_version
    LEFT JOIN pick tg ON tg.scenario_id = si.scenario_id AND tg.initiative_id = si.initiative_id AND tg.name = 'target_minutes_per_case'
),
var AS (
    SELECT m.scenario_id, m.initiative_id, i.baseline_version AS bv, m.wend,
           (SELECT sum(c.amount) FROM cost_rows c WHERE c.scenario_id = m.scenario_id AND c.initiative_id = m.initiative_id AND c.cost_basis = 'planned'
            AND c.baseline_version = i.baseline_version AND c.t < m.wend) AS planned_sum,
           (SELECT sum(c.amount) FROM cost_rows c WHERE c.scenario_id = m.scenario_id AND c.initiative_id = m.initiative_id AND c.cost_basis = 'actual' AND c.t < m.wend) AS actual_sum,
           (SELECT count(*) FROM cost_rows c WHERE c.scenario_id = m.scenario_id AND c.initiative_id = m.initiative_id AND c.cost_basis = 'actual' AND c.t < m.wend) AS actual_rows
    FROM matured_n m JOIN ini i ON i.initiative_id = m.initiative_id
),
-- ---- benefit realization within ONE type, matured periods with an observation only ----------------------------------------------------------------------
obs AS (        -- the latest observation of each benefit at or before as_of
    SELECT DISTINCT ON (o.benefit_id) o.benefit_id, o.measured_value
    FROM benefit_observations o, p WHERE o.observed_at <= p.as_of AND coalesce(o.recorded_at, o.observed_at) <= p.as_of
    ORDER BY o.benefit_id, o.observed_at DESC, coalesce(o.recorded_at, o.observed_at) DESC, o.benefit_observation_id DESC
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
ad AS (SELECT DISTINCT ON (a.initiative_id) a.* FROM adoption_observations a, p WHERE a.observed_at <= p.as_of AND coalesce(a.recorded_at, a.observed_at) <= p.as_of
       ORDER BY a.initiative_id, a.observed_at DESC, coalesce(a.recorded_at, a.observed_at) DESC, a.observation_id DESC),
tr AS (SELECT DISTINCT ON (t.initiative_id) t.* FROM training_completions t, p WHERE t.recorded_at <= p.as_of AND coalesce(t.entered_at, t.recorded_at) <= p.as_of
       ORDER BY t.initiative_id, t.recorded_at DESC, coalesce(t.entered_at, t.recorded_at) DESC, t.training_id DESC),
rk AS (SELECT initiative_id, round(sum(probability * impact), 2) AS exposure, sum(probability * impact) AS exposure_x FROM risk_items GROUP BY initiative_id),
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
first_sc AS (SELECT scenario_id FROM scenario_versions ORDER BY scenario_id COLLATE "C" LIMIT 1),
-- ---- double count (R9-02, R9-03): claims sharing a benefit_source_key in one period across >= 2 initiatives count once, at the largest claim (among equals: the one
-- that enters the cash flow, then the smaller initiative and benefit id). Money and hours are two separate rules, never added. -------------------------------
dc_keys AS (
    SELECT scenario_id, benefit_source_key, period_index FROM benc WHERE claim IS NOT NULL AND benefit_source_key IS NOT NULL
    GROUP BY scenario_id, benefit_source_key, period_index HAVING count(DISTINCT initiative_id) >= 2
),
dc_rank AS (
    SELECT b.scenario_id, b.benefit_source_key, b.period_index, b.initiative_id, b.claim, b.enters,
           row_number() OVER (PARTITION BY b.scenario_id, b.benefit_source_key, b.period_index
                              ORDER BY b.claim DESC, (NOT b.enters), b.initiative_id COLLATE "C", b.benefit_id COLLATE "C") AS rn
    FROM benc b JOIN dc_keys k ON k.scenario_id = b.scenario_id AND k.benefit_source_key = b.benefit_source_key AND k.period_index = b.period_index
    WHERE b.claim IS NOT NULL
),
dc_g AS (SELECT scenario_id, benefit_source_key, period_index, sum(claim) - max(claim) AS removed FROM dc_rank GROUP BY scenario_id, benefit_source_key, period_index),
dc_pv AS (      -- the removed claims that enter the cash flow, each at its own period's discount factor
    SELECT r.scenario_id, sum(r.claim / x.qp) AS pv
    FROM dc_rank r JOIN sc_t x ON x.scenario_id = r.scenario_id AND x.initiative_id = r.initiative_id AND x.t = r.period_index
    WHERE r.rn > 1 AND r.enters GROUP BY r.scenario_id
),
hcl AS (SELECT scenario_id, initiative_id, benefit_source_key, period_index, ramped AS hrs FROM ben WHERE benefit_type = 'capacity'),
hkeys AS (
    SELECT scenario_id, benefit_source_key, period_index FROM hcl WHERE benefit_source_key IS NOT NULL
    GROUP BY scenario_id, benefit_source_key, period_index HAVING count(DISTINCT initiative_id) >= 2
),
hg AS (
    SELECT h.scenario_id, h.benefit_source_key, h.period_index, sum(h.hrs) - max(h.hrs) AS removed
    FROM hcl h JOIN hkeys k ON k.scenario_id = h.scenario_id AND k.benefit_source_key = h.benefit_source_key AND k.period_index = h.period_index
    GROUP BY h.scenario_id, h.benefit_source_key, h.period_index
),
dc AS (
    SELECT s.scenario_id, coalesce((SELECT sum(claim) FROM benc b WHERE b.scenario_id = s.scenario_id AND b.claim IS NOT NULL), 0) AS planned,
           coalesce((SELECT sum(removed) FROM dc_g g WHERE g.scenario_id = s.scenario_id), 0) AS removed,
           coalesce((SELECT pv FROM dc_pv v WHERE v.scenario_id = s.scenario_id), 0) AS pv,
           coalesce((SELECT sum(hrs) FROM hcl h WHERE h.scenario_id = s.scenario_id), 0) AS hplanned,
           coalesce((SELECT sum(removed) FROM hg g WHERE g.scenario_id = s.scenario_id), 0) AS hremoved
    FROM scenario_versions s
),
-- the attributable NPV of a scenario: the sum of the initiative NPVs less the present value of the shared claims that count twice
npv_sc AS (
    SELECT dc.scenario_id,
           (SELECT sum(n.s_last) / max(n.denom) FROM npv n WHERE n.yes AND n.scenario_id = dc.scenario_id) AS total,
           (SELECT sum(n.s_last) / max(n.denom) FROM npv n WHERE n.yes AND n.scenario_id = dc.scenario_id) - dc.pv AS attributable
    FROM dc
),
-- totals that are exact sums, rounded once (R9-07)
excl AS (
    SELECT si.scenario_id, si.initiative_id,
           sum(b.ramped) FILTER (WHERE b.benefit_type = 'capacity' AND b.rate_cap IS NULL) AS cap_hours, count(*) FILTER (WHERE b.benefit_type = 'capacity' AND b.rate_cap IS NULL) AS cap_n,
           sum(b.ramped) FILTER (WHERE b.benefit_type = 'avoided_cost' AND NOT b.enters) AS beside, count(*) FILTER (WHERE b.benefit_type = 'avoided_cost' AND NOT b.enters) AS beside_n
    FROM si LEFT JOIN benc b ON b.scenario_id = si.scenario_id AND b.initiative_id = si.initiative_id
    GROUP BY si.scenario_id, si.initiative_id
),
-- initiatives that claim the same capacity (a shared key in one period of the first scenario) are one group; their released hours count once, at the largest
hpairs AS (
    SELECT DISTINCT a.initiative_id AS a, b.initiative_id AS b
    FROM hcl a JOIN hcl b ON a.scenario_id = b.scenario_id AND a.benefit_source_key = b.benefit_source_key AND a.period_index = b.period_index AND a.initiative_id <> b.initiative_id
    WHERE a.benefit_source_key IS NOT NULL AND a.scenario_id = (SELECT scenario_id FROM first_sc)
),
reach(a, b) AS (SELECT a, b FROM hpairs UNION SELECT r.a, p.b FROM reach r JOIN hpairs p ON p.a = r.b),
cap_lab AS (
    SELECT c.initiative_id, c.hours_x,
           least(c.initiative_id COLLATE "C", coalesce((SELECT min(r.b COLLATE "C") FROM reach r WHERE r.a = c.initiative_id), c.initiative_id)) AS lab
    FROM cap c WHERE c.hours_x IS NOT NULL AND c.scenario_id = (SELECT scenario_id FROM first_sc)
),
cap_tot AS (SELECT sum(mx) AS attributable, sum(sm - mx) AS twice FROM (SELECT lab, max(hours_x) AS mx, sum(hours_x) AS sm FROM cap_lab GROUP BY lab) g),
out(path, val) AS (
    SELECT 'empty_population', (NOT EXISTS (SELECT 1 FROM initiatives))::text
    UNION ALL  -- cash flow rows
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.cash_flow[' || t || '].' || k, v
    FROM sc_t, LATERAL (VALUES ('costs', round(costs, 2)::text), ('cash_benefits', round(benefits, 2)::text), ('net_cash_flow', round(net, 2)::text),
                               ('cumulative', round(cumulative, 2)::text), ('discounted_cash_flow', round(net / qp, 2)::text),
                               ('cumulative_discounted', round(s / qp, 2)::text)) x(k, v)
    UNION ALL  -- NPV, paybacks
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.npv.value', CASE WHEN yes THEN round(npv, 2)::text END FROM npv
    UNION ALL
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.npv.value_6dp', CASE WHEN yes THEN round(npv, 6)::text END FROM npv
    UNION ALL
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.payback.' || k, v
    FROM pay_i, LATERAL (VALUES ('simple.period', CASE WHEN yes THEN simple_t::text END), ('simple.interpolated', CASE WHEN yes THEN round(simple_i, 4)::text END),
                                ('simple.reason', simple_reason),
                                ('discounted.period', CASE WHEN yes THEN disc_t::text END), ('discounted.interpolated', CASE WHEN yes THEN round(disc_i, 4)::text END),
                                ('discounted.reason', disc_reason)) x(k, v)
    UNION ALL  -- totals that are exact sums rounded once
    SELECT 'metrics.scenarios.' || scenario_id || '.initiatives.' || initiative_id || '.excluded_from_cash_flow.' || k, v
    FROM excl, LATERAL (VALUES ('capacity_hours_not_converted', CASE WHEN cap_n > 0 THEN round(cap_hours, 2)::text END),
                               ('avoided_cost_beside_total', CASE WHEN beside_n > 0 THEN round(beside, 2)::text END)) x(k, v)
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
        ('observed_above_trend', CASE WHEN trend_rows > 0 AND comp > 0 AND trend_rows = comp THEN round(observed - trend, 2)::text END)) x(k, v)
    WHERE comp > 0 OR unobs > 0
    UNION ALL  -- double count and the scenario NPV total
    SELECT 'metrics.scenarios.' || scenario_id || '.double_count.' || k, v
    FROM dc, LATERAL (VALUES ('planned_benefits', round(planned, 2)::text), ('attributable_benefits', round(planned - removed, 2)::text), ('residual', round(removed, 2)::text),
                             ('double_counted_amount', round(removed, 2)::text), ('double_counted_pv', round(pv, 2)::text),
                             ('planned_hours', round(hplanned, 2)::text), ('attributable_hours', round(hplanned - hremoved, 2)::text), ('hours_residual', round(hremoved, 2)::text)) x(k, v)
    UNION ALL
    SELECT 'metrics.scenarios.' || n.scenario_id || '.npv_total.' || k, v
    FROM npv_sc n, LATERAL (VALUES ('value', round(n.attributable, 2)::text), ('sum_of_initiatives', round(n.total, 2)::text)) x(k, v)
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
    SELECT 'metrics.summary.npv_total', (SELECT round(attributable, 2)::text FROM npv_sc WHERE scenario_id = (SELECT scenario_id FROM first_sc))
    UNION ALL
    SELECT 'metrics.summary.npv_sum_of_initiatives', (SELECT round(total, 2)::text FROM npv_sc WHERE scenario_id = (SELECT scenario_id FROM first_sc))
    UNION ALL
    SELECT 'metrics.summary.double_count_residual', (SELECT round(removed, 2)::text FROM dc WHERE scenario_id = (SELECT scenario_id FROM first_sc)
                                                    AND EXISTS (SELECT 1 FROM scenario_initiatives si2 WHERE si2.scenario_id = dc.scenario_id))
    UNION ALL
    SELECT 'metrics.summary.double_counted_amount', (SELECT round(removed, 2)::text FROM dc WHERE scenario_id = (SELECT scenario_id FROM first_sc)
                                                    AND EXISTS (SELECT 1 FROM scenario_initiatives si2 WHERE si2.scenario_id = dc.scenario_id))
    UNION ALL
    SELECT 'metrics.summary.double_counted_pv', (SELECT round(pv, 2)::text FROM dc WHERE scenario_id = (SELECT scenario_id FROM first_sc)
                                                AND EXISTS (SELECT 1 FROM scenario_initiatives si2 WHERE si2.scenario_id = dc.scenario_id))
    UNION ALL
    SELECT 'metrics.summary.hours_residual', (SELECT round(hremoved, 2)::text FROM dc WHERE scenario_id = (SELECT scenario_id FROM first_sc)
                                             AND EXISTS (SELECT 1 FROM scenario_initiatives si2 WHERE si2.scenario_id = dc.scenario_id))
    UNION ALL
    SELECT 'metrics.summary.adoption_rate', (SELECT round(sum(adopted_count)::numeric / sum(eligible_count), 6)::text FROM ad WHERE eligible_count > 0)
    UNION ALL
    SELECT 'metrics.summary.training_completion', (SELECT round(sum(completed)::numeric / sum(eligible_trainees), 6)::text FROM tr WHERE eligible_trainees > 0)
    UNION ALL
    SELECT 'metrics.summary.risk_exposure_total', (SELECT round(sum(exposure_x), 2)::text FROM rk)
    UNION ALL
    SELECT 'metrics.summary.capacity_released_hours_total', (SELECT round(attributable, 4)::text FROM cap_tot)
    UNION ALL
    SELECT 'metrics.summary.capacity_released_hours_double_counted', (SELECT round(twice, 4)::text FROM cap_tot)
)
SELECT path, val FROM out ORDER BY path
