-- bi_fact_export_row.sql: BI package fact table, grain = one export row (an invoice taken by a non-repeat request after its policy-valid approval), 2,299 rows (P05-ART-06).
-- Needs 00_book.sql (ib_facts, ib_run). The amount is the invoice's computed total in its own currency.
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT t FROM asof)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT t FROM asof)
)
SELECT x.iid AS invoice_id, x.batch_id, to_char(x.exported_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS exported_date_key, i.currency, i.total AS amount,
       to_char(x.approved_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS approved_date_key
FROM (
    SELECT DISTINCT ON (iid) iid, r.batch_id, r.exported_at, f.at AS approved_at
    FROM req r CROSS JOIN LATERAL unnest(r.invoice_ids) AS iid
    JOIN ib_facts f ON f.kind = 'commit' AND f.c = (SELECT t FROM asof) AND f.invoice_id = iid AND f.at <= r.exported_at
    WHERE NOT r.repeat ORDER BY iid, r.request_seq
) x JOIN ib_run i ON i.c = (SELECT t FROM asof) AND i.invoice_id = x.iid
ORDER BY x.iid COLLATE "C";
