-- bi_fact_decision.sql: BI package fact table, grain = one approve or reject decision (2,356 rows) with the policy in force and its validity at 2026-10-01T02:00:00Z (P05-ART-06).
-- Needs 00_book.sql (ib_facts: `commit` = first policy-valid approval, `reject` = reject decisions with their refusal code).
SELECT a.approval_id, a.invoice_id, a.actor_id, a.actor_role, a.decision, to_char(a.decided_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS decided_date_key,
       p.policy_id, p.version_number AS policy_version,
       (EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z' AND f.ref = a.approval_id)
        OR EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'reject' AND f.c = '2026-10-01T02:00:00Z' AND f.ref = a.approval_id AND f.code IS NULL))::int AS valid,
       coalesce((SELECT f.code FROM ib_facts f WHERE f.kind = 'reject' AND f.c = '2026-10-01T02:00:00Z' AND f.ref = a.approval_id), '') AS refusal_code
FROM approvals a LEFT JOIN LATERAL (SELECT * FROM approval_policies ap WHERE ap.effective_from <= a.decided_at
                                    ORDER BY ap.effective_from DESC, ap.version_number DESC LIMIT 1) p ON TRUE
ORDER BY a.approval_id COLLATE "C";
