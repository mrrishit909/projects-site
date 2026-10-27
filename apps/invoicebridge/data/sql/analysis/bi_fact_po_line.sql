-- bi_fact_po_line.sql: BI package fact table, grain = one purchase-order line at 2026-10-01T02:00:00Z (3,000 rows): ordered, net received, accepted invoiced (P05-ART-06).
-- Needs 00_book.sql. Consumption = the quantities of the matched invoices' compared lines (see 02). Quantities are units; the price is in the line's currency.
WITH used AS (
    SELECT e ->> 'po_line_id' AS po_line_id, sum((e ->> 'q')::numeric) AS used
    FROM ib_run r CROSS JOIN LATERAL jsonb_array_elements(r.line_res) e
    WHERE r.c = '2026-10-01T02:00:00Z' AND r.matched AND (e ->> 'comparable')::boolean GROUP BY 1
)
SELECT l.po_line_id, l.po_id, p.vendor_id, p.currency, l.quantity AS ordered_quantity, l.unit_price,
       coalesce((SELECT sum(r.received_quantity) FROM receipts r WHERE r.po_line_id = l.po_line_id AND NOT r.reversed AND r.received_at <= '2026-10-01T02:00:00Z'), 0) AS net_received_quantity,
       coalesce(u.used, 0) AS accepted_invoiced_quantity
FROM po_lines l JOIN purchase_orders p USING (po_id) LEFT JOIN used u ON u.po_line_id = l.po_line_id
WHERE p.ordered_at <= '2026-10-01T02:00:00Z' ORDER BY l.po_line_id COLLATE "C";
