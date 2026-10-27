-- P07-ART-06 fact: one row per match candidate (400): the human decision (approve, reject or none), whether an approval was reversed, and the verification layer's truth column
-- (`truth_same_entity`, synthetic, for precision only; the matcher never reads it).
SELECT c.candidate_id, c.left_record_id, c.right_record_id, round(c.score, 6) AS score, (c.uncertainty IS NOT NULL)::int AS flagged_possible_household,
       coalesce((SELECT m.decision FROM merge_decisions m WHERE m.candidate_id = c.candidate_id AND m.decision IN ('approve', 'reject')), 'none') AS decision,
       EXISTS (SELECT 1 FROM merge_decisions r JOIN merge_decisions a ON a.merge_id = r.reverses_merge_id WHERE a.candidate_id = c.candidate_id AND r.decision = 'reverse')::int AS reversed,
       (tl.true_entity = tr.true_entity)::int AS truth_same_entity
FROM match_candidates c JOIN verification_truth tl ON tl.record_id = c.left_record_id JOIN verification_truth tr ON tr.record_id = c.right_record_id ORDER BY c.candidate_id COLLATE "C"
