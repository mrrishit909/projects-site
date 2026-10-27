-- P08-ART-06 fact_incident: one row per incident (25) with the verified recovery. Scope: complete_world.
SELECT v.incident_id, v.run_id, r.failure_kind, v.severity, v.status, to_char(v.opened_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS detected_at, v.recovery_run_id,
       to_char(v.verified_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS verified_at, v.recovery_seconds, round(v.recovery_seconds::numeric / 60, 4) AS recovery_minutes,
       v.recovery_run_id = v.first_verified_run AND v.closed_at = v.verified_at AS closure_consistent, 'complete_world' AS scope
FROM po_incident v JOIN po_run r ON r.run_id = v.run_id ORDER BY v.incident_id COLLATE "C"
