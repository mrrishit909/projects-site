-- 08: what was rejected at load and why, and the other planted defects that the data still carries (P03-TEST-04, P03-TEST-07,
-- P03-TEST-10, P03-TEST-11, contract D-01 and D-04, data/injection-manifest.json). One row per reason.
-- lens 'rejection': rows in rejected_records (seed went through the domain's validate_batch; the raw row is kept).
-- lens 'detected': defects that are accepted rows by design and are found by a query: closed purchase orders whose line was
--   only partly received (INJ-03, never counted as complete), receipts of an order placed before the supplier closure that arrive
--   after it (INJ-04), reservations still open at the cutoff (INJ-07: reserved is not subtracted from position).
-- ids lists the record ids (sorted). records is the number of records.
SELECT 'rejection' AS lens, entity, reason_code AS reason, count(*)::int AS records, string_agg(id, ', ' ORDER BY id) AS ids
  FROM rejected_records GROUP BY entity, reason_code
UNION ALL
SELECT 'detected', 'purchase_order_lines', 'CLOSED_ORDER_PARTLY_RECEIVED', count(*)::int, string_agg(po_line_id, ', ' ORDER BY po_line_id)
  FROM (SELECT l.po_line_id FROM purchase_order_lines l JOIN purchase_orders o ON o.purchase_order_id = l.purchase_order_id
         WHERE o.status = 'closed'
           AND l.ordered_quantity > COALESCE((SELECT sum(r.received_quantity) FROM receipts r WHERE r.po_line_id = l.po_line_id), 0)) x
UNION ALL
SELECT 'detected', 'receipts', 'LEAD_TIME_SPANS_CLOSURE', count(*)::int, string_agg(receipt_id, ', ' ORDER BY receipt_id)
  FROM (SELECT r.receipt_id
          FROM receipts r JOIN purchase_order_lines l ON l.po_line_id = r.po_line_id
          JOIN purchase_orders o ON o.purchase_order_id = l.purchase_order_id
          JOIN suppliers s ON s.supplier_id = o.supplier_id
          JOIN calendar_closures c ON c.calendar_id = s.calendar_id
         WHERE (o.ordered_at AT TIME ZONE 'UTC')::date < c.closed_from AND (r.received_at AT TIME ZONE 'UTC')::date > c.closed_to) y
UNION ALL
SELECT 'detected', 'reservations', 'OPEN_RESERVATION_AT_CUTOFF', count(*)::int, string_agg(reservation_id, ', ' ORDER BY reservation_id)
  FROM reservations WHERE reserved_at <= timestamptz '2026-09-30 23:59:59+00' AND (released_at IS NULL OR released_at > timestamptz '2026-09-30 23:59:59+00')
 ORDER BY 1 DESC, 2, 3;
