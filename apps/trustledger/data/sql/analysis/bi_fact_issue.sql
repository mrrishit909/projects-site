-- P07-ART-06 fact: one row per issue (574): its class (resolved only after a successful rerun of the same rule version), hours (4 dp; resolved = verifying rerun - detection, claimed =
-- close - detection, open = age at the as-of) and the accountability of its owner at the as-of.
SELECT i.issue_id, i.dataset_id, i.rule_id, i.owner_id, i.severity, i.status, i.class, i.detected_at::date AS detected_date, tl_iso(i.detected_at) AS detected_at,
       coalesce(tl_iso(i.closed_at), '') AS closed_at, round(i.hours, 4) AS hours, i.cycles AS reopen_cycles,
       (CASE WHEN o.deactivated_at IS NOT NULL THEN tl_p.as_of < o.deactivated_at ELSE o.active END)::int AS owner_accountable
FROM tl_issue i JOIN owners o ON o.owner_id = i.owner_id, tl_p ORDER BY i.issue_id COLLATE "C"
