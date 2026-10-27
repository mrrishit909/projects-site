-- P09-ART-06 fact: one row per initiative (24): adoption and training completion with their own denominators (never substituted), empty with a status where an initiative has no record. Needs 00_portfolio_model.sql.
SELECT i.initiative_id, i.eligibility_rule_version, coalesce(a.eligible_count::text, '') AS adoption_eligible, coalesce(a.adopted_count::text, '') AS adopted,
       CASE WHEN a.eligible_count > 0 THEN round(a.adopted_count::numeric / a.eligible_count, 6)::text ELSE '' END AS adoption_rate,
       CASE WHEN a.initiative_id IS NULL THEN 'no adoption observation by the as-of' WHEN a.eligible_count = 0 THEN 'zero eligible' ELSE 'value' END AS adoption_status,
       coalesce(t.eligible_trainees::text, '') AS training_eligible, coalesce(t.completed::text, '') AS training_completed,
       CASE WHEN t.eligible_trainees > 0 THEN round(t.completed::numeric / t.eligible_trainees, 6)::text ELSE '' END AS training_completion,
       CASE WHEN t.initiative_id IS NULL THEN 'no training record by the as-of' WHEN t.eligible_trainees = 0 THEN 'zero eligible' ELSE 'value' END AS training_status
FROM initiatives i LEFT JOIN cw_adopt a ON a.initiative_id = i.initiative_id LEFT JOIN cw_train t ON t.initiative_id = i.initiative_id
ORDER BY i.initiative_id COLLATE "C"
