-- P09-ART-04 investigation 07: adoption against training, with the denominators (D-03, D-09 R9-11, R9-16, DR-07, INJ-05, P09-TEST-05).
-- Question: when nearly everyone has completed training, has the change been adopted? Adoption rate = adopted / eligible from the latest adoption observation recorded by the as-of, on the initiative's
-- eligibility rule version; training completion = completed / eligible trainees from the latest training record. They are two series with two denominators and neither is ever substituted for the other.
-- The pooled rates divide sums, not an average of rates: adoption 0.532881 and training completion 0.888443 are over different populations (11 initiatives have an adoption series, 15 have a training
-- series) and the common-population block compares them over the initiatives that have both. The lag is the number of calendar months (a period is a month) between the first training record at 90 %
-- completion and the first adoption observation at 50 %; an initiative that never reached 50 % has no lag.

-- @@ by_initiative
SELECT i.initiative_id, i.eligibility_rule_version, ad.eligible_count AS adoption_eligible, ad.adopted_count AS adopted,
       CASE WHEN ad.eligible_count > 0 THEN round(ad.adopted_count::numeric / ad.eligible_count, 6) END AS adoption_rate,
       tr.eligible_trainees AS training_eligible, tr.completed AS training_completed,
       CASE WHEN tr.eligible_trainees > 0 THEN round(tr.completed::numeric / tr.eligible_trainees, 6) END AS training_completion,
       CASE WHEN ad.eligible_count > 0 AND tr.eligible_trainees > 0 THEN round(tr.completed::numeric / tr.eligible_trainees - ad.adopted_count::numeric / ad.eligible_count, 6) END AS training_minus_adoption,
       (ad.eligible_count > 0 AND tr.eligible_trainees > 0) AS has_both_series
FROM initiatives i LEFT JOIN cw_adopt ad ON ad.initiative_id = i.initiative_id LEFT JOIN cw_train tr ON tr.initiative_id = i.initiative_id
ORDER BY i.initiative_id COLLATE "C"

-- @@ pooled
SELECT (SELECT count(*) FROM cw_adopt WHERE eligible_count > 0) AS initiatives_with_adoption, (SELECT sum(adopted_count) FROM cw_adopt WHERE eligible_count > 0) AS adopted,
       (SELECT sum(eligible_count) FROM cw_adopt WHERE eligible_count > 0) AS adoption_eligible,
       round((SELECT sum(adopted_count) FROM cw_adopt WHERE eligible_count > 0)::numeric / (SELECT sum(eligible_count) FROM cw_adopt WHERE eligible_count > 0), 6) AS adoption_rate_pooled,
       (SELECT count(*) FROM cw_train WHERE eligible_trainees > 0) AS initiatives_with_training, (SELECT sum(completed) FROM cw_train WHERE eligible_trainees > 0) AS training_completed,
       (SELECT sum(eligible_trainees) FROM cw_train WHERE eligible_trainees > 0) AS training_eligible,
       round((SELECT sum(completed) FROM cw_train WHERE eligible_trainees > 0)::numeric / (SELECT sum(eligible_trainees) FROM cw_train WHERE eligible_trainees > 0), 6) AS training_completion_pooled

-- @@ common_population
SELECT count(*) AS initiatives_with_both_series, sum(ad.adopted_count) AS adopted, sum(ad.eligible_count) AS adoption_eligible, round(sum(ad.adopted_count)::numeric / sum(ad.eligible_count), 6) AS adoption_rate_pooled,
       sum(tr.completed) AS training_completed, sum(tr.eligible_trainees) AS training_eligible, round(sum(tr.completed)::numeric / sum(tr.eligible_trainees), 6) AS training_completion_pooled,
       count(*) FILTER (WHERE ad.adopted_count * 2 >= ad.eligible_count) AS reached_half_adoption, count(*) FILTER (WHERE ad.adopted_count * 2 < ad.eligible_count) AS not_yet_half_adoption
FROM cw_adopt ad JOIN cw_train tr ON tr.initiative_id = ad.initiative_id WHERE ad.eligible_count > 0 AND tr.eligible_trainees > 0

-- @@ lag_to_half_adoption
WITH t90 AS (
    SELECT z.initiative_id, z.recorded_at FROM (SELECT t.initiative_id, t.recorded_at, row_number() OVER (PARTITION BY t.initiative_id ORDER BY t.recorded_at, t.training_id COLLATE "C") AS rn
                                                FROM training_completions t CROSS JOIN cw_p p WHERE t.completed * 100 >= t.eligible_trainees * 90 AND t.recorded_at <= p.as_of) z WHERE z.rn = 1),
a50 AS (
    SELECT z.initiative_id, z.observed_at FROM (SELECT a.initiative_id, a.observed_at, row_number() OVER (PARTITION BY a.initiative_id ORDER BY a.observed_at, a.observation_id COLLATE "C") AS rn
                                                FROM adoption_observations a CROSS JOIN cw_p p WHERE a.eligible_count > 0 AND a.adopted_count * 2 >= a.eligible_count AND a.observed_at <= p.as_of) z WHERE z.rn = 1)
SELECT i.initiative_id, to_char(t90.recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS training_90_percent_on,
       to_char(a50.observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS adoption_50_percent_on,
       CASE WHEN a50.observed_at IS NOT NULL THEN (extract(year FROM a50.observed_at AT TIME ZONE 'UTC') * 12 + extract(month FROM a50.observed_at AT TIME ZONE 'UTC'))::int
                                                 - (extract(year FROM t90.recorded_at AT TIME ZONE 'UTC') * 12 + extract(month FROM t90.recorded_at AT TIME ZONE 'UTC'))::int END AS lag_periods,
       (extract(year FROM p.as_of AT TIME ZONE 'UTC') * 12 + extract(month FROM p.as_of AT TIME ZONE 'UTC'))::int
         - (extract(year FROM t90.recorded_at AT TIME ZONE 'UTC') * 12 + extract(month FROM t90.recorded_at AT TIME ZONE 'UTC'))::int AS periods_since_training_90_percent,
       round(tr.completed::numeric / tr.eligible_trainees, 6) AS training_completion_now, round(ad.adopted_count::numeric / ad.eligible_count, 6) AS adoption_rate_now
FROM initiatives i JOIN t90 ON t90.initiative_id = i.initiative_id JOIN cw_adopt ad ON ad.initiative_id = i.initiative_id AND ad.eligible_count > 0
JOIN cw_train tr ON tr.initiative_id = i.initiative_id LEFT JOIN a50 ON a50.initiative_id = i.initiative_id CROSS JOIN cw_p p
ORDER BY i.initiative_id COLLATE "C"

-- @@ lag_summary
WITH t90 AS (
    SELECT z.initiative_id, z.recorded_at FROM (SELECT t.initiative_id, t.recorded_at, row_number() OVER (PARTITION BY t.initiative_id ORDER BY t.recorded_at, t.training_id COLLATE "C") AS rn
                                                FROM training_completions t CROSS JOIN cw_p p WHERE t.completed * 100 >= t.eligible_trainees * 90 AND t.recorded_at <= p.as_of) z WHERE z.rn = 1),
a50 AS (
    SELECT z.initiative_id, z.observed_at FROM (SELECT a.initiative_id, a.observed_at, row_number() OVER (PARTITION BY a.initiative_id ORDER BY a.observed_at, a.observation_id COLLATE "C") AS rn
                                                FROM adoption_observations a CROSS JOIN cw_p p WHERE a.eligible_count > 0 AND a.adopted_count * 2 >= a.eligible_count AND a.observed_at <= p.as_of) z WHERE z.rn = 1),
lag AS (
    SELECT t90.initiative_id, (extract(year FROM a50.observed_at AT TIME ZONE 'UTC') * 12 + extract(month FROM a50.observed_at AT TIME ZONE 'UTC'))::int
                              - (extract(year FROM t90.recorded_at AT TIME ZONE 'UTC') * 12 + extract(month FROM t90.recorded_at AT TIME ZONE 'UTC'))::int AS lag
    FROM t90 JOIN cw_adopt h ON h.initiative_id = t90.initiative_id AND h.eligible_count > 0 LEFT JOIN a50 ON a50.initiative_id = t90.initiative_id)
SELECT count(*) AS initiatives_with_both_series, count(lag) AS reached_half_adoption, count(*) - count(lag) AS not_yet_half_adoption,
       string_agg(lag::text, ',' ORDER BY lag) FILTER (WHERE lag IS NOT NULL) AS lag_periods_sorted,
       string_agg(initiative_id, ',' ORDER BY initiative_id COLLATE "C") FILTER (WHERE lag IS NULL) AS never_reached_half_adoption
FROM lag
