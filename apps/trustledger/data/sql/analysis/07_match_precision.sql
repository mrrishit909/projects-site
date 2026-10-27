-- P07-ART-04 investigation 07: identity-match precision over approvals, and the wider review-correct share (D-04, D-06, DR-06).
-- Match precision = approved merge decisions CONFIRMED by the synthetic truth / approved merge decisions (a reversal does not remove the approval).
-- Review-correct share (the contract's `reviewed_correct_share`) = reviewed candidates whose two records are the same true entity / reviewed candidates, approvals and
-- rejections together (a wider population than precision, D-06). The truth is the verification layer's table `verification_truth` (loaded by prepare_snapshot.py,
-- never read by the matcher, the API or the seeder). Synthetic personal details only. Observed on the loaded snapshot at its as-of.

-- @@ precision
-- Two different "review" shares are kept apart and labelled. reviewed_correct_share (the contract's, D-06) = reviewed pairs that ARE the same true entity / reviewed pairs:
-- how good the proposed candidates were. decision_agreement_share (this analysis) = reviews whose decision agrees with the truth (an approval of a true match or a rejection of a
-- non-match) / reviews: how good the reviewers were. They answer different questions and differ (185 of 220 against 205 of 220 on this snapshot).
WITH d AS (
    SELECT c.candidate_id, m.decision, (tl.true_entity = tr.true_entity) AS same_entity
    FROM merge_decisions m JOIN match_candidates c ON c.candidate_id = m.candidate_id
    JOIN verification_truth tl ON tl.record_id = c.left_record_id JOIN verification_truth tr ON tr.record_id = c.right_record_id, tl_p
    WHERE m.decision IN ('approve', 'reject') AND m.decided_at <= tl_p.as_of)
SELECT count(*) FILTER (WHERE decision = 'approve') AS approved, count(*) FILTER (WHERE decision = 'approve' AND same_entity) AS approved_correct,
       round(count(*) FILTER (WHERE decision = 'approve' AND same_entity)::numeric / count(*) FILTER (WHERE decision = 'approve'), 6) AS precision,
       count(*) AS reviewed, count(*) FILTER (WHERE decision = 'reject') AS rejected,
       count(*) FILTER (WHERE same_entity) AS reviewed_correct,
       round(count(*) FILTER (WHERE same_entity)::numeric / count(*), 6) AS reviewed_correct_share,
       count(*) FILTER (WHERE (decision = 'approve') = same_entity) AS decisions_agreeing_with_truth,
       round(count(*) FILTER (WHERE (decision = 'approve') = same_entity)::numeric / count(*), 6) AS decision_agreement_share
FROM d

-- @@ review_matrix
-- Decision x truth: where the 220 reviews are right and wrong.
WITH d AS (
    SELECT m.decision, (tl.true_entity = tr.true_entity) AS same_entity
    FROM merge_decisions m JOIN match_candidates c ON c.candidate_id = m.candidate_id
    JOIN verification_truth tl ON tl.record_id = c.left_record_id JOIN verification_truth tr ON tr.record_id = c.right_record_id
    WHERE m.decision IN ('approve', 'reject'))
SELECT decision, CASE WHEN same_entity THEN 'same entity' ELSE 'different entities' END AS truth, count(*) AS decisions,
       CASE WHEN (decision = 'approve') = same_entity THEN 'agrees with the truth' ELSE 'disagrees' END AS verdict
FROM d GROUP BY decision, same_entity ORDER BY decision, same_entity DESC

-- @@ candidates
-- The funnel: candidates proposed, reviewed, unreviewed, the household ambiguity flagged at proposal, and the reversals.
SELECT (SELECT count(*) FROM match_candidates) AS candidates,
       (SELECT count(DISTINCT (left_record_id, right_record_id)) FROM match_candidates WHERE left_record_id COLLATE "C" < right_record_id COLLATE "C") AS canonical_distinct_pairs,
       (SELECT count(DISTINCT candidate_id) FROM merge_decisions WHERE decision IN ('approve', 'reject')) AS reviewed,
       (SELECT count(*) FROM match_candidates c WHERE NOT EXISTS (SELECT 1 FROM merge_decisions m WHERE m.candidate_id = c.candidate_id)) AS unreviewed,
       (SELECT count(*) FROM merge_decisions WHERE decision = 'reverse') AS reversals,
       (SELECT count(*) FROM match_candidates WHERE uncertainty IS NOT NULL) AS candidates_flagged_shared_name_and_address,
       (SELECT count(*) FROM merge_decisions WHERE decision IN ('approve', 'reject') AND reviewer_id = (SELECT proposed_by FROM match_candidates c WHERE c.candidate_id = merge_decisions.candidate_id)) AS reviews_by_the_proposer

-- @@ wrong_approvals
-- The approvals the truth says were wrong, whether a reversal followed, and whether the pair was flagged as a possible household when it was proposed.
SELECT c.candidate_id, c.left_record_id, c.right_record_id, round(c.score, 6) AS score, c.uncertainty IS NOT NULL AS flagged_possible_household,
       m.reviewer_id, EXISTS (SELECT 1 FROM merge_decisions r WHERE r.reverses_merge_id = m.merge_id) AS reversed_afterwards
FROM merge_decisions m JOIN match_candidates c ON c.candidate_id = m.candidate_id
JOIN verification_truth tl ON tl.record_id = c.left_record_id JOIN verification_truth tr ON tr.record_id = c.right_record_id
WHERE m.decision = 'approve' AND tl.true_entity <> tr.true_entity ORDER BY c.candidate_id COLLATE "C"

-- @@ reversals
SELECT count(*) AS reversals, count(DISTINCT reverses_merge_id) AS approvals_reversed,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM merge_decisions a JOIN match_candidates c ON c.candidate_id = a.candidate_id
                                      JOIN verification_truth tl ON tl.record_id = c.left_record_id JOIN verification_truth tr ON tr.record_id = c.right_record_id
                                      WHERE a.merge_id = merge_decisions.reverses_merge_id AND tl.true_entity <> tr.true_entity)) AS reversals_of_wrong_approvals,
       count(*) FILTER (WHERE reason IS NULL OR btrim(reason) = '') AS reversals_without_a_reason
FROM merge_decisions WHERE decision = 'reverse'
