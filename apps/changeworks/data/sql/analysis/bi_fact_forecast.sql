-- P09-ART-06 fact: every forecast row (144): version 1 is the original, kept beside every revision. Needs no temporary table.
SELECT f.initiative_id, f.version_number, f.period_index, f.amount::numeric(20,2)::text AS amount, to_char(f.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at, f.reason
FROM forecast_versions f
ORDER BY f.initiative_id COLLATE "C", f.version_number, f.period_index
