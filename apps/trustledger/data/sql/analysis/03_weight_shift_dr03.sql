-- P07-ART-04 investigation 03: the weight change that moves scores with no rule change (D-01, D-07 assumption 4, DR-03, INJ-05).
-- Question: how much of a score movement is the weights alone? The same rows and the same rules are scored under w1 and under w2 (the change is dated 2026-09-01).
-- The shift is the EXACT difference (w2 minus w1) of the unrounded scores, shown to 6 places (it can differ from the difference of two rounded scores by 0.000001, D-10 R7-18).

-- @@ weights
SELECT weight_version, valid_from::date AS valid_from, weights ->> 'completeness' AS completeness, weights ->> 'validity' AS validity, weights ->> 'uniqueness' AS uniqueness,
       weights ->> 'relationship' AS relationship, weights ->> 'timeliness' AS timeliness
FROM rule_weight_versions ORDER BY valid_from

-- @@ shift_by_dataset
WITH s AS (
    SELECT d.dataset_id, w.weight_version,
           sum((w.weights ->> d.dimension)::numeric * d.score) / sum((w.weights ->> d.dimension)::numeric) AS score
    FROM tl_dim d CROSS JOIN rule_weight_versions w GROUP BY d.dataset_id, w.weight_version),
p AS (
    SELECT dataset_id, max(score) FILTER (WHERE weight_version = 'w1') AS w1, max(score) FILTER (WHERE weight_version = 'w2') AS w2 FROM s GROUP BY dataset_id)
SELECT dataset_id, round(w1, 6) AS score_w1, round(w2, 6) AS score_w2, round(w2 - w1, 6) AS shift,
       (w2 <> w1) AS differs, abs(w2 - w1) >= 0.005 AS moved_at_least_0_005
FROM p ORDER BY dataset_id COLLATE "C"

-- @@ summary
WITH s AS (
    SELECT d.dataset_id, w.weight_version,
           sum((w.weights ->> d.dimension)::numeric * d.score) / sum((w.weights ->> d.dimension)::numeric) AS score
    FROM tl_dim d CROSS JOIN rule_weight_versions w GROUP BY d.dataset_id, w.weight_version),
p AS (
    SELECT dataset_id, max(score) FILTER (WHERE weight_version = 'w1') AS w1, max(score) FILTER (WHERE weight_version = 'w2') AS w2 FROM s GROUP BY dataset_id)
SELECT count(*) AS datasets_scored, count(*) FILTER (WHERE w1 <> w2) AS datasets_with_different_score,
       count(*) FILTER (WHERE abs(w2 - w1) >= 0.005) AS datasets_moved_at_least_0_005,
       round(avg(w1), 6) AS mean_score_w1, round(avg(w2), 6) AS mean_score_w2,
       round((SELECT w2 - w1 FROM p ORDER BY abs(w2 - w1) DESC, dataset_id COLLATE "C" LIMIT 1), 6) AS largest_move,
       (SELECT dataset_id FROM p ORDER BY abs(w2 - w1) DESC, dataset_id COLLATE "C" LIMIT 1) AS largest_move_dataset
FROM p

-- @@ runs_by_weight_version
-- The stored runs name the weight version in force when they were made: the change is a new version, not an edit (append-only).
SELECT weight_version, count(*) AS runs, tl_iso(min(run_at)) AS first_run, tl_iso(max(run_at)) AS last_run FROM rule_runs GROUP BY weight_version ORDER BY weight_version

-- @@ rule_changes_near_the_weight_change
-- A rule version change is "near" the weight change when it took effect within 14 days either side; DR-03 says none did, so the movement is the weights alone.
SELECT count(*) AS rule_versions_after_the_first, count(*) FILTER (WHERE abs(extract(epoch FROM (v.valid_from - w.valid_from)) / 86400) <= 14) AS within_14_days_of_the_weight_change,
       min(abs(round(extract(epoch FROM (v.valid_from - w.valid_from)) / 86400)))::int AS nearest_days,
       (SELECT count(*) FROM quality_rules r, (SELECT valid_from FROM rule_weight_versions ORDER BY valid_from DESC LIMIT 1) c WHERE r.disabled_at IS NOT NULL AND abs(extract(epoch FROM (r.disabled_at - c.valid_from)) / 86400) <= 14) AS rules_disabled_within_14_days
FROM quality_rule_versions v CROSS JOIN (SELECT valid_from FROM rule_weight_versions ORDER BY valid_from DESC LIMIT 1) w
WHERE v.version_number > 1 AND v.valid_from IS NOT NULL

-- @@ lowest_scores
-- What a score-first priority list would put on top: the eight lowest-scoring datasets under w2, with their rank (1 = lowest, ties by dataset id) under each version. The list changes
-- with the weights, which is why the fix-first rule of investigation 10 does not rank by score.
WITH s AS (
    SELECT d.dataset_id, w.weight_version,
           sum((w.weights ->> d.dimension)::numeric * d.score) / sum((w.weights ->> d.dimension)::numeric) AS score
    FROM tl_dim d CROSS JOIN rule_weight_versions w GROUP BY d.dataset_id, w.weight_version),
p AS (
    SELECT dataset_id, max(score) FILTER (WHERE weight_version = 'w1') AS w1, max(score) FILTER (WHERE weight_version = 'w2') AS w2 FROM s GROUP BY dataset_id),
r AS (
    SELECT dataset_id, w1, w2, row_number() OVER (ORDER BY w1, dataset_id COLLATE "C") AS rank_w1, row_number() OVER (ORDER BY w2, dataset_id COLLATE "C") AS rank_w2 FROM p)
SELECT dataset_id, round(w1, 6) AS score_w1, rank_w1, round(w2, 6) AS score_w2, rank_w2 FROM r ORDER BY rank_w2 LIMIT 8
