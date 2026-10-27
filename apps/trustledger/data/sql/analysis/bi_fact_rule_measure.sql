-- P07-ART-06 fact: one row per rule active at the as-of (55 of 60): what it measured. An empty score is "not measured", with the reason in score_status. The score is the
-- exact fraction score_numerator / score_denominator (passing over eligible, over populated for validity), so a consumer can average without the 6-place rounding.
SELECT m.rule_id, m.dataset_id, m.dimension, m.severity, m.eligible, coalesce(m.populated::text, '') AS populated, m.failing, round(m.score, 6) AS score,
       CASE WHEN m.score IS NULL THEN '' ELSE (m.eligible - m.failing)::text END AS score_numerator,
       CASE WHEN m.score IS NULL THEN '' WHEN m.dimension = 'validity' THEN m.populated::text ELSE m.eligible::text END AS score_denominator,
       CASE WHEN m.score IS NOT NULL THEN 'measured'
            WHEN m.dimension = 'timeliness' AND NOT EXISTS (SELECT 1 FROM tl_tstate t WHERE t.seq = 0 AND t.dataset_id = m.dataset_id) THEN 'not_measured: dataset not monitored'
            WHEN m.dimension = 'timeliness' THEN 'not_measured: window open, no refresh yet (pending)'
            ELSE 'not_measured: no eligible value' END AS score_status
FROM tl_rule_measure m ORDER BY m.rule_id COLLATE "C"
