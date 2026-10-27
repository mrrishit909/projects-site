-- 09_golden_known_answer.sql: the spec sentence recomputed from the facts of the GOLDEN fixture (P05-ART-04, P05-GOLD-01, D-02, D-03, D-05).
-- Run on the database prepared with `prepare_snapshot.py --golden` (tests/fixtures/golden/inputs.json), never on the snapshot.
-- "PO 10 units at 20.00; accepted receipt 6; first invoice 6 units at 20.00 matches 120.00 before tax; a second invoice for 4 units is
-- quantity-blocked until a receipt arrives; importing the first invoice twice leaves one obligation; with 10 % tax and no other charges
-- the first total is 132.00." Nothing below reads a stored status, total or merge flag: amounts and identities come from the lines.

-- @@ golden_per_invoice
SELECT i.invoice_id, round(sum(l.quantity * l.unit_price), 2) AS subtotal, round(sum(l.quantity * l.unit_price) * i.tax_rate, 2) AS tax,
       round(sum(l.quantity * l.unit_price), 2) + round(sum(l.quantity * l.unit_price) * i.tax_rate, 2) + i.freight - i.invoice_discount AS total,
       i.declared_total,
       abs(i.declared_total - (round(sum(l.quantity * l.unit_price), 2) + round(sum(l.quantity * l.unit_price) * i.tax_rate, 2) + i.freight - i.invoice_discount)) AS rounding_difference
FROM invoices i JOIN invoice_lines l USING (invoice_id) GROUP BY i.invoice_id, i.tax_rate, i.freight, i.invoice_discount, i.declared_total ORDER BY i.invoice_id COLLATE "C";

-- @@ golden_identity_groups
-- Identity = vendor, normalised number, invoice date and the COMPUTED total; the group with two invoices is the duplicate (inv-003 re-sent with other bytes).
WITH t AS (
    SELECT i.invoice_id, i.vendor_id || '|' || regexp_replace(upper(i.invoice_number), '[^A-Z0-9]', '', 'g') || '|' || to_char(i.invoice_date, 'YYYY-MM-DD') || '|'
               || (round(sum(l.quantity * l.unit_price), 2) + round(sum(l.quantity * l.unit_price) * i.tax_rate, 2) + i.freight - i.invoice_discount)::text AS identity_key,
           i.source_sha256
    FROM invoices i JOIN invoice_lines l USING (invoice_id) GROUP BY i.invoice_id, i.vendor_id, i.invoice_number, i.invoice_date, i.tax_rate, i.freight, i.invoice_discount, i.source_sha256
)
SELECT identity_key, count(*) AS invoices, count(DISTINCT source_sha256) AS distinct_source_bytes, min(invoice_id COLLATE "C") AS earliest_invoice_id
FROM t GROUP BY identity_key ORDER BY identity_key COLLATE "C";

-- @@ golden_quantities
-- Ordered 10, received 6, the first invoice takes 6, so 0 is available for the second invoice of 4: a quantity variance of 4.0000 (QUANTITY_BLOCKED).
WITH q AS (
    SELECT l.po_line_id, l.quantity AS ordered,
           coalesce((SELECT sum(r.received_quantity) FROM receipts r WHERE r.po_line_id = l.po_line_id AND NOT r.reversed), 0) AS net,
           coalesce((SELECT sum(il.quantity) FROM invoice_lines il WHERE il.po_line_id = l.po_line_id AND il.invoice_id = 'inv-001'), 0) AS first_q,
           coalesce((SELECT sum(il.quantity) FROM invoice_lines il WHERE il.po_line_id = l.po_line_id AND il.invoice_id = 'inv-002'), 0) AS second_q
    FROM po_lines l
)
SELECT po_line_id, round(ordered, 4) AS ordered_quantity, round(net, 4) AS net_received_quantity, round(first_q, 4) AS first_invoice_quantity,
       round(net - first_q, 4) AS available_for_the_second_invoice, round(second_q, 4) AS second_invoice_quantity,
       round(second_q - (net - first_q), 4) AS quantity_variance_of_the_second_invoice
FROM q ORDER BY po_line_id COLLATE "C";
