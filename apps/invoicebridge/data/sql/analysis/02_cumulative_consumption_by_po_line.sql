-- 02_cumulative_consumption_by_po_line.sql: how much of what was received has been invoiced and accepted, per PO line, at three cutoffs (P05-ART-04, D-03, D-09.2).
-- Question: how much received quantity is still available to invoice, so which invoices can advance?
-- Needs 00_book.sql (ib_run: the book per cutoff, its line results in jsonb). Consumption is the sum of the quantities on the lines of
-- MATCHED invoices that were compared with their PO line (`comparable`): an invoice with any exception consumes nothing, and a merged,
-- rejected or invalid one is not in the book at all. Net received = receipts not reversed and received by the cutoff; a PO line exists
-- at a cutoff when its purchase order was ordered by then. The three cutoffs are 2026-03-31T23:59:59Z, 2026-06-30T23:59:59Z (the
-- month-ends) and the as-of 2026-10-01T02:00:00Z (web/public/data/manifest.json snapshot_cutoffs).
-- Quantities are units and may be added across currencies; MONEY (received-not-invoiced at the PO price) is per currency and is
-- never summed across currencies, so the money column is NULL on the 'ALL' rows.

-- @@ totals_by_cutoff
WITH cuts(c) AS (VALUES ('2026-03-31T23:59:59Z'::timestamptz), ('2026-06-30T23:59:59Z'), ('2026-10-01T02:00:00Z')),
pl AS (
    SELECT cu.c, l.po_line_id, l.quantity, l.unit_price, p.currency,
           coalesce((SELECT sum(r.received_quantity) FROM receipts r WHERE r.po_line_id = l.po_line_id AND NOT r.reversed AND r.received_at <= cu.c), 0) AS net
    FROM cuts cu JOIN purchase_orders p ON p.ordered_at <= cu.c JOIN po_lines l ON l.po_id = p.po_id
),
used AS (
    SELECT r.c, e ->> 'po_line_id' AS po_line_id, sum((e ->> 'q')::numeric) AS used
    FROM ib_run r, jsonb_array_elements(r.line_res) e
    WHERE r.matched AND (e ->> 'comparable')::boolean GROUP BY 1, 2
),
j AS (SELECT pl.*, coalesce(u.used, 0) AS used FROM pl LEFT JOIN used u ON u.c = pl.c AND u.po_line_id = pl.po_line_id)
SELECT c AS cutoff, currency, count(*) AS po_lines, round(sum(quantity), 4) AS ordered_quantity, round(sum(net), 4) AS net_received_quantity,
       round(sum(used), 4) AS accepted_invoiced_quantity, round(sum(greatest(quantity - net, 0)), 4) AS open_to_receive_quantity,
       round(sum(greatest(quantity - used, 0)), 4) AS open_to_invoice_quantity, round(sum(greatest(net - used, 0)), 4) AS received_not_invoiced_quantity,
       round(sum(greatest(net - used, 0) * unit_price), 2) AS received_not_invoiced_value
FROM j GROUP BY c, currency
UNION ALL
SELECT c, 'ALL', count(*), round(sum(quantity), 4), round(sum(net), 4), round(sum(used), 4), round(sum(greatest(quantity - net, 0)), 4),
       round(sum(greatest(quantity - used, 0)), 4), round(sum(greatest(net - used, 0)), 4), NULL
FROM j GROUP BY c
ORDER BY 1, 2;

-- @@ line_state_by_cutoff
-- Every PO line at each cutoff falls into exactly one state; `over_consumed` (accepted invoiced above net received) must stay 0:
-- a quantity-blocked invoice is the control that keeps it there (D-03).
WITH cuts(c) AS (VALUES ('2026-03-31T23:59:59Z'::timestamptz), ('2026-06-30T23:59:59Z'), ('2026-10-01T02:00:00Z')),
pl AS (
    SELECT cu.c, l.po_line_id,
           coalesce((SELECT sum(r.received_quantity) FROM receipts r WHERE r.po_line_id = l.po_line_id AND NOT r.reversed AND r.received_at <= cu.c), 0) AS net
    FROM cuts cu JOIN purchase_orders p ON p.ordered_at <= cu.c JOIN po_lines l ON l.po_id = p.po_id
),
used AS (
    SELECT r.c, e ->> 'po_line_id' AS po_line_id, sum((e ->> 'q')::numeric) AS used
    FROM ib_run r, jsonb_array_elements(r.line_res) e
    WHERE r.matched AND (e ->> 'comparable')::boolean GROUP BY 1, 2
),
j AS (SELECT pl.c, pl.po_line_id, pl.net, coalesce(u.used, 0) AS used FROM pl LEFT JOIN used u ON u.c = pl.c AND u.po_line_id = pl.po_line_id),
s AS (SELECT c, CASE WHEN used > net THEN 'over_consumed' WHEN net = 0 THEN 'nothing_received'
                     WHEN used = 0 THEN 'received_none_invoiced' WHEN used < net THEN 'partly_invoiced' ELSE 'fully_invoiced' END AS state FROM j),
states(ord, state) AS (VALUES (1, 'nothing_received'), (2, 'received_none_invoiced'), (3, 'partly_invoiced'), (4, 'fully_invoiced'), (5, 'over_consumed'))
SELECT cu.c AS cutoff, st.state, count(s.state) AS po_lines
FROM cuts cu CROSS JOIN states st LEFT JOIN s ON s.c = cu.c AND s.state = st.state
GROUP BY cu.c, st.ord, st.state ORDER BY cu.c, st.ord;

-- @@ ladder_top_lines
-- The ten PO lines with the most accepted invoiced quantity at the as-of, with their net received and accepted invoiced quantity at each of
-- the three cutoffs: consumption only grows as invoices are accepted, and never passes what was received.
WITH cuts(c) AS (VALUES ('2026-03-31T23:59:59Z'::timestamptz), ('2026-06-30T23:59:59Z'), ('2026-10-01T02:00:00Z')),
used AS (
    SELECT r.c, e ->> 'po_line_id' AS po_line_id, sum((e ->> 'q')::numeric) AS used
    FROM ib_run r, jsonb_array_elements(r.line_res) e
    WHERE r.matched AND (e ->> 'comparable')::boolean GROUP BY 1, 2
),
net AS (
    SELECT cu.c, l.po_line_id,
           coalesce((SELECT sum(r.received_quantity) FROM receipts r WHERE r.po_line_id = l.po_line_id AND NOT r.reversed AND r.received_at <= cu.c), 0) AS net
    FROM cuts cu JOIN purchase_orders p ON p.ordered_at <= cu.c JOIN po_lines l ON l.po_id = p.po_id
),
top AS (
    SELECT u.po_line_id, u.used FROM used u WHERE u.c = '2026-10-01T02:00:00Z' ORDER BY u.used DESC, u.po_line_id COLLATE "C" LIMIT 10
)
SELECT t.po_line_id, p.vendor_id, p.currency, round(l.quantity, 4) AS ordered_quantity,
       round(coalesce((SELECT n.net FROM net n WHERE n.c = '2026-03-31T23:59:59Z' AND n.po_line_id = t.po_line_id), 0), 4) AS net_at_march,
       round(coalesce((SELECT u.used FROM used u WHERE u.c = '2026-03-31T23:59:59Z' AND u.po_line_id = t.po_line_id), 0), 4) AS invoiced_at_march,
       round(coalesce((SELECT n.net FROM net n WHERE n.c = '2026-06-30T23:59:59Z' AND n.po_line_id = t.po_line_id), 0), 4) AS net_at_june,
       round(coalesce((SELECT u.used FROM used u WHERE u.c = '2026-06-30T23:59:59Z' AND u.po_line_id = t.po_line_id), 0), 4) AS invoiced_at_june,
       round(coalesce((SELECT n.net FROM net n WHERE n.c = '2026-10-01T02:00:00Z' AND n.po_line_id = t.po_line_id), 0), 4) AS net_at_asof,
       round(t.used, 4) AS invoiced_at_asof
FROM top t JOIN po_lines l ON l.po_line_id = t.po_line_id JOIN purchase_orders p ON p.po_id = l.po_id
ORDER BY t.used DESC, t.po_line_id COLLATE "C";
