-- P09-ART-04 investigation 08: forecast revisions with the original preserved (D-02, D-05 D-P9-17, D-09 R9-10, DR-04, INJ-06, P09-TEST-06).
-- Question: when a forecast was missed and revised, is the approved forecast still there, and what did each revision change? A forecast is one row per (initiative, version, period); the first forecast is
-- version 1, the original; a revision is version n+1 and never overwrites (UPDATE, DELETE and a repeated (initiative, version, period) are refused by the database and by the domain: VERSION_EXISTS,
-- FORECAST_OVERWRITE). A revision must cover every period of the original (REVISION_PERIODS_INCOMPLETE). A revision follows a miss when the cash benefit observed by the revision date, in a period not
-- yet checked at the previous revision, is more than 10 % below the previous version's amount for that period. Scope: the 12 forecast sets (144 rows) and init-003 in detail.

-- @@ versions
SELECT f.initiative_id, f.version_number, to_char(min(f.created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at, count(*) AS periods, min(f.period_index) AS first_period,
       max(f.period_index) AS last_period, round(sum(f.amount), 2) AS total, min(f.reason COLLATE "C") AS reason
FROM forecast_versions f
GROUP BY f.initiative_id, f.version_number
ORDER BY f.initiative_id COLLATE "C", f.version_number

-- @@ original_preserved
WITH v AS (SELECT f.initiative_id, f.version_number, array_agg(f.period_index ORDER BY f.period_index) AS periods, sum(f.amount) AS total FROM forecast_versions f GROUP BY f.initiative_id, f.version_number)
SELECT o.initiative_id, (SELECT count(*) FROM v x WHERE x.initiative_id = o.initiative_id) AS versions, cardinality(o.periods) AS original_rows, o.version_number AS original_version,
       (SELECT bool_and(x.periods @> o.periods) FROM v x WHERE x.initiative_id = o.initiative_id) AS every_version_covers_the_original_periods,
       round(o.total, 2) AS original_total,
       round((SELECT l.total FROM v l WHERE l.initiative_id = o.initiative_id ORDER BY l.version_number DESC LIMIT 1) - o.total, 2) AS latest_minus_original
FROM v o WHERE o.version_number = 1
ORDER BY o.initiative_id COLLATE "C"

-- @@ init003_versions
WITH v AS (SELECT f.version_number, min(f.created_at) AS created_at, sum(f.amount) AS total, min(f.reason COLLATE "C") AS reason FROM forecast_versions f WHERE f.initiative_id = 'init-003' GROUP BY f.version_number)
SELECT v.version_number, to_char(v.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at, round(v.total, 2) AS total,
       round(v.total - (SELECT o.total FROM v o WHERE o.version_number = 1), 2) AS change_vs_original,
       round(v.total - coalesce((SELECT p.total FROM v p WHERE p.version_number = v.version_number - 1), v.total), 2) AS change_vs_previous, v.reason
FROM v ORDER BY v.version_number

-- @@ init003_by_period
WITH ob AS (
    SELECT z.period_index, z.measured_value FROM (SELECT b.period_index, o.measured_value,
                                                         row_number() OVER (PARTITION BY b.benefit_id ORDER BY o.observed_at DESC, coalesce(o.recorded_at, o.observed_at) DESC, o.benefit_observation_id COLLATE "C" DESC) AS rn
                                                  FROM benefit_items b JOIN benefit_observations o ON o.benefit_id = b.benefit_id CROSS JOIN cw_p p
                                                  WHERE b.initiative_id = 'init-003' AND b.benefit_type = 'cash' AND o.observed_at <= p.as_of AND coalesce(o.recorded_at, o.observed_at) <= p.as_of) z WHERE z.rn = 1)
SELECT f.period_index, max(f.amount) FILTER (WHERE f.version_number = 1)::numeric(20,2) AS v1, max(f.amount) FILTER (WHERE f.version_number = 2)::numeric(20,2) AS v2,
       max(f.amount) FILTER (WHERE f.version_number = 3)::numeric(20,2) AS v3, ob.measured_value::numeric(20,2) AS latest_observed,
       round(ob.measured_value / max(f.amount) FILTER (WHERE f.version_number = 1), 6) AS observed_over_v1
FROM forecast_versions f LEFT JOIN ob ON ob.period_index = f.period_index
WHERE f.initiative_id = 'init-003'
GROUP BY f.period_index, ob.measured_value
ORDER BY f.period_index

-- @@ revision_triggers
WITH vers AS (SELECT f.initiative_id, f.version_number, min(f.created_at) AS created_at FROM forecast_versions f GROUP BY f.initiative_id, f.version_number),
known AS (      -- the cash benefit observed in each period by the instant T: the latest observation of each benefit at or before T (and recorded by T)
    SELECT r.initiative_id, r.version_number, z.period_index, z.measured_value
    FROM vers r
    JOIN LATERAL (SELECT y.period_index, y.measured_value FROM (SELECT b.period_index, o.measured_value,
                                                                       row_number() OVER (PARTITION BY b.benefit_id ORDER BY o.observed_at DESC, o.benefit_observation_id COLLATE "C" DESC) AS rn
                                                                FROM benefit_items b JOIN benefit_observations o ON o.benefit_id = b.benefit_id
                                                                WHERE b.initiative_id = r.initiative_id AND b.benefit_type = 'cash' AND o.observed_at <= r.created_at
                                                                  AND coalesce(o.recorded_at, o.observed_at) <= r.created_at) y WHERE y.rn = 1) z ON true),
chk AS (
    SELECT n.initiative_id, n.version_number AS revision, p.version_number AS revises_version, n.created_at, f.period_index, f.amount AS previous_amount, k.measured_value AS observed
    FROM vers n JOIN vers p ON p.initiative_id = n.initiative_id AND p.version_number = n.version_number - 1
    JOIN forecast_versions f ON f.initiative_id = p.initiative_id AND f.version_number = p.version_number
    JOIN known k ON k.initiative_id = n.initiative_id AND k.version_number = n.version_number AND k.period_index = f.period_index
    WHERE NOT EXISTS (SELECT 1 FROM known kp WHERE kp.initiative_id = p.initiative_id AND kp.version_number = p.version_number AND kp.period_index = f.period_index))
SELECT c.initiative_id, c.revision, c.revises_version, to_char(c.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at,
       string_agg(c.period_index::text, ',' ORDER BY c.period_index) AS periods_checked,
       string_agg(c.period_index::text, ',' ORDER BY c.period_index) FILTER (WHERE c.observed * 10 < c.previous_amount * 9) AS periods_more_than_10_percent_below,
       round(min(c.observed / c.previous_amount), 6) AS lowest_observed_over_forecast, round(max(c.observed / c.previous_amount), 6) AS highest_observed_over_forecast
FROM chk c
GROUP BY c.initiative_id, c.revision, c.revises_version, c.created_at
ORDER BY c.initiative_id COLLATE "C", c.revision
