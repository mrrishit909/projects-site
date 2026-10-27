-- bi_fact_credit_note.sql: BI package fact table, grain = one credit note (117 rows) (P05-ART-06).
-- Needs 00_book.sql. `applied` = the invoice is an obligation at 2026-10-01T02:00:00Z and the note is dated by then; it reduces the payable and moves no cash.
SELECT cn.credit_id, cn.invoice_id, i.currency, cn.credit_amount, to_char(cn.credited_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS credited_date_key,
       (EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z' AND f.invoice_id = cn.invoice_id)
        AND (cn.credited_at IS NULL OR cn.credited_at <= '2026-10-01T02:00:00Z'))::int AS applied
FROM credit_notes cn JOIN invoices i USING (invoice_id) ORDER BY cn.credit_id COLLATE "C";
