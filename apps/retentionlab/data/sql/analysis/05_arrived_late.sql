-- P10-ART-04 investigation 05: events that arrived late, and what ignoring the arrival instant would change (D-01 point in time, D-07 DR-04, P10-FLOW-01).
-- Question: what share of events reach the warehouse a day or more after they happened, and how many feature rows would carry a different value if a builder used event_at
-- only? A feature uses an event only when observation_start <= event_at < prediction_at AND available_at < prediction_at. The recomputation below is written from the
-- contract (not from reference_metrics.sql): window start inclusive, cutoff exclusive, days_since floored, a feature with no source events is NULL (never 0).
-- Populations: the 200-account cohort (this database, recomputed here for all 765 stored feature rows) and the whole world's figures published in the manifest
-- (full world, 1,513 test rows; they need the full event history and are shown as published, not recomputed).
-- @@ late_events_by_source
WITH e AS (
    SELECT 'usage_events' AS source, 1 AS ord, event_at, available_at FROM usage_events
    UNION ALL SELECT 'billing_events', 2, event_at, available_at FROM billing_events
    UNION ALL SELECT 'support_events', 3, event_at, available_at FROM support_events
    UNION ALL SELECT 'subscription_events', 4, event_at, available_at FROM subscription_events
)
SELECT e.source, count(*) AS cohort_events, count(*) FILTER (WHERE e.available_at - e.event_at >= interval '1 day') AS late_one_day_or_more,
       round(count(*) FILTER (WHERE e.available_at - e.event_at >= interval '1 day')::numeric / count(*), 6) AS cohort_share,
       (SELECT value::numeric FROM art_published_claim WHERE claim = 'late_share_' || split_part(e.source, '_', 1)) AS published_full_world_share
FROM e GROUP BY e.ord, e.source ORDER BY e.ord;
-- @@ feature_recomputation
WITH rng AS (SELECT validation_end, test_end FROM training_runs ORDER BY training_run_id COLLATE "C" LIMIT 1),
f AS (
    SELECT fr.feature_row_id, pc.prediction_at, fr.features_json AS stored,
           (SELECT count(*) FROM usage_events u WHERE u.account_id = pc.account_id AND u.event_at >= pc.observation_start AND u.event_at < pc.prediction_at
               AND u.event_at >= pc.prediction_at - interval '30 days' AND u.available_at < pc.prediction_at) AS usage_strict,
           (SELECT count(*) FROM usage_events u WHERE u.account_id = pc.account_id AND u.event_at >= pc.observation_start AND u.event_at < pc.prediction_at
               AND u.event_at >= pc.prediction_at - interval '30 days') AS usage_ignoring,
           (SELECT floor(extract(epoch FROM pc.prediction_at - max(u.event_at)) / 86400)::int FROM usage_events u WHERE u.account_id = pc.account_id
               AND u.event_at >= pc.observation_start AND u.event_at < pc.prediction_at AND u.available_at < pc.prediction_at) AS days_strict,
           (SELECT floor(extract(epoch FROM pc.prediction_at - max(u.event_at)) / 86400)::int FROM usage_events u WHERE u.account_id = pc.account_id
               AND u.event_at >= pc.observation_start AND u.event_at < pc.prediction_at) AS days_ignoring,
           (SELECT count(*) FROM support_events s WHERE s.account_id = pc.account_id AND s.severity = 'high' AND s.event_at >= pc.observation_start AND s.event_at < pc.prediction_at
               AND s.available_at < pc.prediction_at) AS high_strict,
           (SELECT count(*) FROM support_events s WHERE s.account_id = pc.account_id AND s.severity = 'high' AND s.event_at >= pc.observation_start AND s.event_at < pc.prediction_at) AS high_ignoring,
           (SELECT sum(b.amount) FROM billing_events b WHERE b.account_id = pc.account_id AND b.event_at >= pc.observation_start AND b.event_at < pc.prediction_at
               AND b.available_at < pc.prediction_at) AS billing_strict,
           (SELECT sum(b.amount) FROM billing_events b WHERE b.account_id = pc.account_id AND b.event_at >= pc.observation_start AND b.event_at < pc.prediction_at) AS billing_ignoring,
           (SELECT count(*) FROM (SELECT event_at, available_at FROM usage_events x WHERE x.account_id = pc.account_id UNION ALL SELECT event_at, available_at FROM billing_events x WHERE x.account_id = pc.account_id
                                  UNION ALL SELECT event_at, available_at FROM support_events x WHERE x.account_id = pc.account_id) z
             WHERE z.event_at >= pc.observation_start AND z.event_at < pc.prediction_at AND z.available_at >= pc.prediction_at) AS late_events_in_window
    FROM feature_rows fr JOIN prediction_cutoffs pc USING (cutoff_id)
),
x AS (
    SELECT f.*, (f.prediction_at >= rng.validation_end AND f.prediction_at < rng.test_end) AS in_test_range,
           ((stored ->> 'usage_events_30d')::int = usage_strict AND (stored ->> 'days_since_last_usage')::int IS NOT DISTINCT FROM days_strict
             AND (stored ->> 'high_severity_support_90d')::int = high_strict AND (stored ->> 'billing_total_90d')::numeric IS NOT DISTINCT FROM billing_strict) AS stored_equals_strict
    FROM f, rng
)
SELECT scope, count(*) AS feature_rows, count(*) FILTER (WHERE stored_equals_strict) AS stored_equals_point_in_time_recomputation,
       count(*) FILTER (WHERE late_events_in_window > 0) AS rows_with_a_late_event,
       count(*) FILTER (WHERE usage_strict <> usage_ignoring OR days_strict IS DISTINCT FROM days_ignoring OR high_strict <> high_ignoring OR billing_strict IS DISTINCT FROM billing_ignoring) AS rows_changed_if_arrival_ignored,
       count(*) FILTER (WHERE usage_strict <> usage_ignoring) AS usage_events_30d_changed, count(*) FILTER (WHERE days_strict IS DISTINCT FROM days_ignoring) AS days_since_last_usage_changed,
       count(*) FILTER (WHERE high_strict <> high_ignoring) AS high_severity_support_90d_changed, count(*) FILTER (WHERE billing_strict IS DISTINCT FROM billing_ignoring) AS billing_total_90d_changed,
       round(count(*) FILTER (WHERE usage_strict <> usage_ignoring OR days_strict IS DISTINCT FROM days_ignoring OR high_strict <> high_ignoring OR billing_strict IS DISTINCT FROM billing_ignoring)::numeric / count(*), 6) AS share_changed
FROM (SELECT x.*, s.scope, s.ord FROM x JOIN (VALUES ('all 765 eligible cohort rows', 1, false), ('test-range cohort rows', 2, true)) AS s(scope, ord, only_test) ON (NOT s.only_test OR x.in_test_range)) y
GROUP BY ord, scope ORDER BY ord;
-- @@ published_full_world
SELECT claim, value FROM art_published_claim
WHERE claim IN ('test_rows', 'test_rows_with_a_late_event', 'test_rows_features_change_if_ignored', 'share_of_test_rows_changed') ORDER BY CASE claim WHEN 'test_rows' THEN 1 WHEN 'test_rows_with_a_late_event' THEN 2
    WHEN 'test_rows_features_change_if_ignored' THEN 3 ELSE 4 END;
-- @@ arrived_late_counted_by_range
-- the late events the point-in-time builder counted and excluded, by range of the cutoff row (cohort): event inside the window, available at or after the cutoff
SELECT CASE WHEN pc.prediction_at < r.train_end THEN 'train' WHEN pc.prediction_at < r.validation_end THEN 'validation' WHEN pc.prediction_at < r.test_end THEN 'test' ELSE 'outside' END AS split_range,
       count(*) AS cohort_feature_rows, count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM usage_events u WHERE u.account_id = pc.account_id AND u.event_at >= pc.observation_start AND u.event_at < pc.prediction_at AND u.available_at >= pc.prediction_at
           UNION ALL SELECT 1 FROM support_events u WHERE u.account_id = pc.account_id AND u.event_at >= pc.observation_start AND u.event_at < pc.prediction_at AND u.available_at >= pc.prediction_at
           UNION ALL SELECT 1 FROM billing_events u WHERE u.account_id = pc.account_id AND u.event_at >= pc.observation_start AND u.event_at < pc.prediction_at AND u.available_at >= pc.prediction_at)) AS rows_with_a_late_event
FROM feature_rows fr JOIN prediction_cutoffs pc USING (cutoff_id), (SELECT train_end, validation_end, test_end FROM training_runs ORDER BY training_run_id COLLATE "C" LIMIT 1) r
GROUP BY 1 ORDER BY min(pc.prediction_at);
