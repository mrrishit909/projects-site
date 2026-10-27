-- bi_fact_exception.sql: BI package fact table, grain = one stored exception (660 rows, resolved ones included) with its state at 2026-10-01T02:00:00Z (P05-ART-06).
-- Needs only the stored history (`exceptions`, `exception_assignments`). Open = created and not yet resolved at the as-of; the owner is the latest assignment.
SELECT e.exception_id, e.invoice_id, e.exception_type AS reason_code, to_char(e.created_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS created_date_key,
       to_char(e.resolved_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS resolved_date_key,
       (e.created_at <= '2026-10-01T02:00:00Z' AND (e.resolved_at IS NULL OR e.resolved_at > '2026-10-01T02:00:00Z'))::int AS open_at_asof,
       coalesce((SELECT a.owner_id FROM exception_assignments a WHERE a.exception_id = e.exception_id AND a.assigned_at <= '2026-10-01T02:00:00Z'
                 ORDER BY a.assigned_at DESC, a.assignment_id DESC LIMIT 1), '') AS owner_at_asof,
       (SELECT count(*) FROM exception_assignments a WHERE a.exception_id = e.exception_id) AS assignments,
       round(extract(epoch FROM (SELECT min(a.assigned_at) FROM exception_assignments a WHERE a.exception_id = e.exception_id) - e.created_at) / 3600, 4) AS hours_to_first_assignment
FROM exceptions e ORDER BY e.exception_id COLLATE "C";
