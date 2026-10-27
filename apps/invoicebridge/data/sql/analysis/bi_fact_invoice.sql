-- bi_fact_invoice.sql: BI package fact table, grain = one row per imported invoice (2,800 on the snapshot), state AS OF 2026-10-01T02:00:00Z (P05-ART-06, docs/bi-package.md).
-- Needs 00_book.sql (ib_run, ib_facts). Amounts come from the lines (tax once per invoice on the unrounded subtotal, half-up, D-02); the status is the
-- derived one (merged > needs_review > rejected > received > adjusted > exported > approved > matched > exception, as invoicebridge.book.derive).
-- Flags are 0/1. Money is the invoice's own currency; it is never summed across currencies. run_all.py --bi-out writes the CSV.
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
amt AS (
    SELECT i.invoice_id, round(sum(l.quantity * l.unit_price), 2) AS sub, round(sum(l.quantity * l.unit_price) * i.tax_rate, 2) AS tax
    FROM invoices i JOIN invoice_lines l USING (invoice_id) GROUP BY i.invoice_id, i.tax_rate
),
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT t FROM asof)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT t FROM asof)
),
exp AS (
    SELECT DISTINCT ON (iid) iid AS invoice_id, r.batch_id, r.exported_at
    FROM req r CROSS JOIN LATERAL unnest(r.invoice_ids) AS iid
    JOIN ib_facts f ON f.kind = 'commit' AND f.c = (SELECT t FROM asof) AND f.invoice_id = iid AND f.at <= r.exported_at
    WHERE NOT r.repeat ORDER BY iid, r.request_seq
),
cred AS (
    SELECT cn.invoice_id, sum(cn.credit_amount) AS total FROM credit_notes cn
    WHERE cn.credited_at IS NULL OR cn.credited_at <= (SELECT t FROM asof) GROUP BY cn.invoice_id
),
b AS (
    SELECT i.invoice_id, i.vendor_id, i.currency, i.invoice_date, i.imported_at, i.created_by, i.declared_total, i.freight, i.invoice_discount,
           a.sub, a.tax, a.sub + a.tax + i.freight - i.invoice_discount AS total,
           r.invoice_id IS NOT NULL AS in_book, coalesce(r.matched, FALSE) AS matched, coalesce(array_to_string(r.reasons, '|'), '') AS open_reasons,
           (r.invoice_id IS NOT NULL AND cardinality(r.reasons) > 0) OR EXISTS (SELECT 1 FROM exceptions e WHERE e.invoice_id = i.invoice_id) AS ever_excepted,
           f.at AS approved_at, x.batch_id AS export_batch_id, x.exported_at, coalesce(c.total, 0) AS credit_total,
           m.ref AS merged_into, m.code AS merge_reason, rv.invoice_id IS NOT NULL AS in_review,
           EXISTS (SELECT 1 FROM ib_facts j WHERE j.kind = 'reject' AND j.c = (SELECT t FROM asof) AND j.invoice_id = i.invoice_id AND j.code IS NULL) AS rejected
    FROM invoices i JOIN amt a USING (invoice_id)
    LEFT JOIN ib_run r ON r.c = (SELECT t FROM asof) AND r.invoice_id = i.invoice_id
    LEFT JOIN ib_facts f ON f.kind = 'commit' AND f.c = (SELECT t FROM asof) AND f.invoice_id = i.invoice_id
    LEFT JOIN exp x ON x.invoice_id = i.invoice_id
    LEFT JOIN cred c ON c.invoice_id = i.invoice_id AND f.invoice_id IS NOT NULL
    LEFT JOIN ib_facts m ON m.kind = 'merged' AND m.c = (SELECT t FROM asof) AND m.invoice_id = i.invoice_id
    LEFT JOIN ib_facts rv ON rv.kind = 'review' AND rv.c = (SELECT t FROM asof) AND rv.invoice_id = i.invoice_id
)
SELECT b.invoice_id, b.vendor_id, b.currency, to_char(b.invoice_date, 'YYYYMMDD')::int AS invoice_date_key,
       to_char(b.imported_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS imported_date_key,
       b.sub AS subtotal, b.tax, b.freight, b.invoice_discount, b.total, b.declared_total, b.created_by,
       CASE WHEN b.merged_into IS NOT NULL THEN 'merged' WHEN b.in_review THEN 'needs_review' WHEN b.rejected THEN 'rejected' WHEN NOT b.in_book THEN 'received'
            WHEN b.approved_at IS NOT NULL AND b.credit_total > 0 THEN 'adjusted' WHEN b.export_batch_id IS NOT NULL THEN 'exported'
            WHEN b.approved_at IS NOT NULL THEN 'approved' WHEN b.matched THEN 'matched' ELSE 'exception' END AS status_at_asof,
       b.in_book::int AS in_book, b.matched::int AS matched, b.open_reasons, b.ever_excepted::int AS ever_excepted,
       (b.approved_at IS NOT NULL)::int AS approved, to_char(b.approved_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS approved_date_key,
       extract(epoch FROM (b.approved_at - b.imported_at))::bigint AS seconds_to_approval,
       (b.export_batch_id IS NOT NULL)::int AS exported, b.export_batch_id, to_char(b.exported_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS exported_date_key,
       round(b.credit_total, 2) AS credit_total, CASE WHEN b.approved_at IS NOT NULL THEN round(b.total - b.credit_total, 2) END AS approved_payable,
       b.merged_into, b.merge_reason
FROM b ORDER BY b.invoice_id COLLATE "C";
