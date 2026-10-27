-- RetentionLab reference metrics: an INDEPENDENT recomputation, in SQL, of the metrics of one cutoff set from the FACTS (accounts,
-- the four event tables, cutoffs, predictions, scenarios, publications, the label version): eligibility, point-in-time features,
-- arrived-late counts, labels with censoring, churn rate, precision / recall / risk lift at K, Brier score, the 10 calibration bins,
-- feature missingness, the draft outreach queue, contact budget and expected intervention value, and the two freshness figures.
-- It reads no stored feature_rows, labels, split or publication status (the publication status is DERIVED here from eligibility and
-- predictions). It equals expected.json cutoff_sets[...] on the golden fixture and both variants.
--
-- NOT recomputed here (Python only, tested against expected.json and by hand in the domain tests): average precision (tied-threshold
-- grouping), the population stability index (a natural logarithm at 60 digits), the chronological split with its purges, and
-- the Platt / logistic fitting.
--
-- Parameters (psycopg): %(as_of)s timestamptz (what is known: later-arriving events, predictions and publications are invisible),
-- %(pa)s the cutoff set's prediction_at, %(run)s training run id, %(scenario)s scenario id or NULL, %(model)s model name.
-- Exactness: counts are integers, probabilities are NUMERIC(20,6) and every sum / square / product is exact NUMERIC; a ratio is
-- round(a / b, 6) (PostgreSQL rounds half away from zero = ROUND_HALF_UP; ties are terminating decimals, which NUMERIC division keeps exactly).
-- Order of the ranking: probability DESC, account_id ASC (D-P10-03). Text comparison uses COLLATE "C" (code-point order, like the domain).
WITH
p AS (SELECT %(as_of)s::timestamptz AS as_of, %(pa)s::timestamptz AS pa, %(run)s::text AS run, %(scenario)s::text AS sc, %(model)s::text AS model),
lv AS (SELECT grace_days FROM label_versions ORDER BY label_version_id LIMIT 1),
fv AS (SELECT feature_version FROM feature_versions ORDER BY feature_version LIMIT 1),
win AS (SELECT coalesce((SELECT r.window_days FROM feature_registry r, fv WHERE r.feature_version = fv.feature_version AND r.feature_name = 'usage_events_30d'), 30) AS usage_days),

-- ---- every cutoff row, with its account's creation instant and its label window --------------------------------------------------
cx AS (
    SELECT c.cutoff_id, c.account_id, c.prediction_at, c.observation_start, c.horizon_end,
           c.horizon_end + make_interval(days => lv.grace_days) AS label_end, a.created_at
    FROM prediction_cutoffs c JOIN accounts a USING (account_id), lv
),
-- the latest subscription event VISIBLE at the cutoff: event_at and available_at both before it (D-P10-05), ties by event_at then id
last_sub AS (
    SELECT DISTINCT ON (cx.cutoff_id) cx.cutoff_id, s.event_type
    FROM cx
    JOIN subscription_events s ON s.account_id = cx.account_id AND s.event_at < cx.prediction_at AND s.available_at < cx.prediction_at
    CROSS JOIN p
    WHERE s.available_at <= p.as_of
    ORDER BY cx.cutoff_id, s.event_at DESC, s.subscription_event_id COLLATE "C" DESC
),
el AS (
    SELECT cx.*,
           (cx.created_at < cx.observation_start AND ls.event_type IN ('start', 'renew')) AS eligible,
           CASE WHEN cx.created_at >= cx.observation_start THEN 'CREATED_ON_OR_AFTER_OBSERVATION_START' ELSE 'NOT_ACTIVE' END AS why,
           (cx.label_end <= p.as_of) AS mature
    FROM cx LEFT JOIN last_sub ls USING (cutoff_id) CROSS JOIN p
),
-- a mature eligible row churned iff a cancel lies in [prediction_at, horizon_end) and ARRIVED before label_end (D-01, D-P10-08)
lab AS (
    SELECT el.cutoff_id,
           EXISTS (SELECT 1 FROM subscription_events s
                   WHERE s.account_id = el.account_id AND s.event_type = 'cancel' AND s.event_at >= el.prediction_at AND s.event_at < el.horizon_end
                     AND s.available_at < el.label_end AND s.available_at <= p.as_of) AS churned
    FROM el CROSS JOIN p WHERE el.eligible AND el.mature
),
st AS (SELECT el.*, lab.churned FROM el LEFT JOIN lab USING (cutoff_id) CROSS JOIN p WHERE el.prediction_at = p.pa),

-- ---- point-in-time features of the eligible rows of the set (window start inclusive, cutoff exclusive, both instants before it) -----
feat AS (
    SELECT st.cutoff_id, st.account_id,
           (SELECT count(*) FROM usage_events u, p, win WHERE u.account_id = st.account_id AND u.event_at >= st.observation_start AND u.event_at < st.prediction_at
               AND u.available_at < st.prediction_at AND u.available_at <= p.as_of AND u.event_at >= st.prediction_at - make_interval(days => win.usage_days)) AS usage30,
           (SELECT floor(extract(epoch FROM st.prediction_at - max(u.event_at)) / 86400)::int FROM usage_events u, p
             WHERE u.account_id = st.account_id AND u.event_at >= st.observation_start AND u.event_at < st.prediction_at
               AND u.available_at < st.prediction_at AND u.available_at <= p.as_of) AS days_since,
           (SELECT count(*) FROM support_events e, p WHERE e.account_id = st.account_id AND e.severity = 'high' AND e.event_at >= st.observation_start
               AND e.event_at < st.prediction_at AND e.available_at < st.prediction_at AND e.available_at <= p.as_of) AS high90,
           (SELECT sum(b.amount) FROM billing_events b, p WHERE b.account_id = st.account_id AND b.event_at >= st.observation_start
               AND b.event_at < st.prediction_at AND b.available_at < st.prediction_at AND b.available_at <= p.as_of) AS billing
    FROM st WHERE st.eligible
),
-- events that happened inside the window but arrived at or after the cutoff: counted, never used (D-P10-07)
late AS (
    SELECT
      (SELECT count(*) FROM st JOIN subscription_events s ON s.account_id = st.account_id CROSS JOIN p
        WHERE st.eligible AND s.event_at < st.prediction_at AND s.available_at >= st.prediction_at AND s.available_at <= p.as_of) AS subscription,
      (SELECT count(*) FROM st JOIN billing_events s ON s.account_id = st.account_id CROSS JOIN p
        WHERE st.eligible AND s.event_at >= st.observation_start AND s.event_at < st.prediction_at AND s.available_at >= st.prediction_at AND s.available_at <= p.as_of) AS billing,
      (SELECT count(*) FROM st JOIN usage_events s ON s.account_id = st.account_id CROSS JOIN p
        WHERE st.eligible AND s.event_at >= st.observation_start AND s.event_at < st.prediction_at AND s.available_at >= st.prediction_at AND s.available_at <= p.as_of) AS usage,
      (SELECT count(*) FROM st JOIN support_events s ON s.account_id = st.account_id CROSS JOIN p
        WHERE st.eligible AND s.event_at >= st.observation_start AND s.event_at < st.prediction_at AND s.available_at >= st.prediction_at AND s.available_at <= p.as_of) AS support
),

-- ---- predictions, the evaluated population and the ranking ------------------------------------------------------------------------
pr AS (SELECT cutoff_id, probability FROM predictions, p WHERE training_run_id = p.run AND model_name = p.model AND scored_at <= p.as_of),
ev AS (
    SELECT st.cutoff_id, st.account_id, pr.probability AS pb, st.churned AS y,
           row_number() OVER (ORDER BY pr.probability DESC, st.account_id ASC) AS rk
    FROM st JOIN pr USING (cutoff_id) WHERE st.eligible AND st.mature
),
q AS (
    SELECT st.account_id, pr.probability AS pb, row_number() OVER (ORDER BY pr.probability DESC, st.account_id ASC) AS rk
    FROM st JOIN pr USING (cutoff_id) WHERE st.eligible
),
sc AS (SELECT s.* FROM intervention_scenarios s, p WHERE s.scenario_id = p.sc),
tot AS (
    SELECT (SELECT count(*) FROM st) AS cutoff_rows,
           (SELECT count(*) FROM st WHERE eligible) AS eligible,
           (SELECT count(*) FROM st WHERE eligible AND mature) AS mature,
           (SELECT count(*) FROM st WHERE eligible AND mature AND churned) AS churned,
           (SELECT count(*) FROM st JOIN pr USING (cutoff_id) WHERE st.eligible) AS scored,
           (SELECT count(*) FROM ev) AS n,
           (SELECT count(*) FROM ev WHERE y) AS pos,
           (SELECT count(*) FROM q) AS qn,
           (SELECT capacity FROM sc) AS k
),
kk AS (
    SELECT tot.*, (tot.k IS NOT NULL AND tot.n > 0 AND tot.k >= 1 AND tot.k <= tot.n) AS k_ok,
           (SELECT count(*) FROM ev WHERE ev.rk <= tot.k AND ev.y) AS hits
    FROM tot
),
bins AS (
    SELECT g AS idx,
           (SELECT count(*) FROM ev WHERE least(floor(ev.pb * 10), 9) = g) AS cnt,
           (SELECT sum(ev.pb) FROM ev WHERE least(floor(ev.pb * 10), 9) = g) AS sum_p,
           (SELECT count(*) FROM ev WHERE least(floor(ev.pb * 10), 9) = g AND ev.y) AS pos
    FROM generate_series(0, 9) g
),
-- ---- publications with a DERIVED status, freshness --------------------------------------------------------------------------------
pubs AS (
    SELECT sp.publication_id, sp.published_at,
           (SELECT count(*) FROM el WHERE el.eligible AND el.prediction_at = sp.prediction_at) AS elig,
           (SELECT count(*) FROM el JOIN predictions x ON x.cutoff_id = el.cutoff_id AND x.training_run_id = sp.training_run_id AND x.model_name = p.model AND x.scored_at <= p.as_of
             WHERE el.eligible AND el.prediction_at = sp.prediction_at) AS done
    FROM scoring_publications sp CROSS JOIN p WHERE sp.model_name = p.model AND sp.published_at <= p.as_of
),
latest AS (SELECT publication_id, published_at FROM pubs WHERE elig > 0 AND done = elig ORDER BY published_at DESC, publication_id COLLATE "C" DESC LIMIT 1),
newest AS (
    SELECT max(t) AS t FROM (
        SELECT max(available_at) AS t FROM subscription_events, p WHERE available_at <= p.as_of UNION ALL
        SELECT max(available_at) FROM billing_events, p WHERE available_at <= p.as_of UNION ALL
        SELECT max(available_at) FROM usage_events, p WHERE available_at <= p.as_of UNION ALL
        SELECT max(available_at) FROM support_events, p WHERE available_at <= p.as_of) x
)
SELECT
    jsonb_build_object(
        'cutoff_rows', kk.cutoff_rows, 'eligible', kk.eligible,
        'ineligible', coalesce((SELECT jsonb_object_agg(why, c) FROM (SELECT why, count(*) AS c FROM st WHERE NOT eligible GROUP BY why) i), '{}'::jsonb),
        'mature', kk.mature, 'censored', kk.eligible - kk.mature, 'scored', kk.scored, 'evaluated', kk.n, 'unscored_excluded', kk.mature - kk.n, 'churned', kk.churned
    ) AS population,
    jsonb_build_object('value', CASE WHEN kk.mature = 0 THEN NULL ELSE round(kk.churned::numeric / kk.mature, 6)::numeric(20,6)::text END,
                       'churned', kk.churned, 'mature_eligible', kk.mature) AS churn_rate,
    jsonb_build_object('subscription_events', late.subscription, 'billing_events', late.billing, 'usage_events', late.usage, 'support_events', late.support,
                       'total', late.subscription + late.billing + late.usage + late.support) AS late_events,
    CASE WHEN kk.k_ok THEN jsonb_build_object('value', round(kk.hits::numeric / kk.k, 6)::numeric(20,6)::text, 'hits', kk.hits, 'k', kk.k) END AS precision_at_k,
    CASE WHEN kk.k_ok THEN jsonb_build_object('value', CASE WHEN kk.pos = 0 THEN NULL ELSE round(kk.hits::numeric / kk.pos, 6)::numeric(20,6)::text END,
                                              'hits', kk.hits, 'positives', kk.pos) END AS recall_at_k,
    CASE WHEN kk.k_ok THEN jsonb_build_object(
        'value', CASE WHEN kk.pos = 0 THEN NULL ELSE round((kk.hits::numeric / kk.k) / (kk.pos::numeric / kk.n), 6)::numeric(20,6)::text END,
        'top_k_rate', round(kk.hits::numeric / kk.k, 6)::numeric(20,6)::text,
        'overall_rate', CASE WHEN kk.n = 0 THEN NULL ELSE round(kk.pos::numeric / kk.n, 6)::numeric(20,6)::text END,
        'tie_split_at_k', kk.k < kk.n AND (SELECT a.pb = b.pb FROM ev a, ev b WHERE a.rk = kk.k AND b.rk = kk.k + 1)) END AS risk_lift_at_k,
    jsonb_build_object(
        'value', CASE WHEN kk.n = 0 THEN NULL ELSE round((SELECT sum((ev.pb - ev.y::int) ^ 2) FROM ev) / kk.n, 6)::numeric(20,6)::text END,
        'n', kk.n,
        'terms', coalesce((SELECT jsonb_agg(round((ev.pb - ev.y::int) ^ 2, 6)::numeric(20,6)::text ORDER BY ev.rk) FROM ev), '[]'::jsonb)) AS brier_score,
    (SELECT jsonb_agg(jsonb_build_object(
        'index', b.idx, 'lower', (b.idx / 10.0)::numeric(20,6)::text, 'upper', ((b.idx + 1) / 10.0)::numeric(20,6)::text, 'closed_upper', b.idx = 9,
        'count', b.cnt,
        'mean_predicted', CASE WHEN b.cnt = 0 THEN NULL ELSE round(b.sum_p / b.cnt, 6)::numeric(20,6)::text END,
        'observed_rate', CASE WHEN b.cnt = 0 THEN NULL ELSE round(b.pos::numeric / b.cnt, 6)::numeric(20,6)::text END,
        'gap_pp', CASE WHEN b.cnt = 0 THEN NULL ELSE round((b.sum_p - b.pos) * 100 / b.cnt, 2)::numeric(20,2)::text END) ORDER BY b.idx) FROM bins b) AS calibration_bins,
    CASE WHEN kk.k IS NOT NULL AND kk.k >= 1 AND kk.k <= kk.qn THEN jsonb_build_object(
        'contact_budget', (kk.k * (SELECT contact_cost FROM sc))::numeric(20,2)::text,
        'expected_value', round((SELECT sum(q.pb * sc.assumed_effect * sc.margin_value - sc.contact_cost) FROM q, sc WHERE q.rk <= kk.k), 2)::numeric(20,2)::text,
        'selected_account_ids', (SELECT jsonb_agg(q.account_id ORDER BY q.rk) FROM q WHERE q.rk <= kk.k),
        'terms', (SELECT jsonb_agg(round(q.pb * sc.assumed_effect * sc.margin_value - sc.contact_cost, 6)::numeric(20,6)::text ORDER BY q.rk) FROM q, sc WHERE q.rk <= kk.k)) END AS economics,
    CASE WHEN kk.k IS NOT NULL AND kk.k >= 1 AND kk.k <= kk.qn THEN jsonb_build_object(
        'status', 'draft', 'account_ids', (SELECT jsonb_agg(q.account_id ORDER BY q.rk) FROM q WHERE q.rk <= kk.k), 'population', kk.qn) END AS outreach_queue,
    jsonb_build_object(
        'period', to_char(p.pa AT TIME ZONE 'UTC', 'YYYY-MM'),
        'overall_missing', (SELECT count(*) FILTER (WHERE days_since IS NULL) + count(*) FILTER (WHERE billing IS NULL) FROM feat),
        'overall_total', kk.eligible * 4,
        'overall_value', CASE WHEN kk.eligible = 0 THEN NULL ELSE round(((SELECT count(*) FILTER (WHERE days_since IS NULL) + count(*) FILTER (WHERE billing IS NULL) FROM feat))::numeric / (kk.eligible * 4), 6)::numeric(20,6)::text END,
        'days_since_last_usage_missing', (SELECT count(*) FROM feat WHERE days_since IS NULL),
        'billing_total_90d_missing', (SELECT count(*) FROM feat WHERE billing IS NULL)) AS feature_missingness,
    (SELECT jsonb_build_object('scoring_hours', CASE WHEN l.published_at IS NULL THEN NULL ELSE floor(extract(epoch FROM p.as_of - l.published_at) / 3600)::int END,
                               'latest_completed_publication_id', l.publication_id,
                               'data_hours', CASE WHEN n.t IS NULL THEN NULL ELSE floor(extract(epoch FROM p.as_of - n.t) / 3600)::int END)
       FROM p LEFT JOIN latest l ON true CROSS JOIN newest n) AS freshness,
    (kk.eligible = 0) AS empty_population,
    (kk.n = 0) AS empty_evaluation
FROM kk CROSS JOIN late CROSS JOIN p;
