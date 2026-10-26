-- 01: stock and inventory position as of every month-end, by location (P03-MET-01..04, P03-TEST-10, contract D-01 and D-02).
-- on_hand = sum of posted deltas up to the cutoff, a negative reconstruction counts as 0 (never valued negative).
-- on_order = ordered - received (receipts dated up to the cutoff) on lines of orders placed by the cutoff, counted at the
--   product's home location. As-of rule: an order that is NOT cancelled counts, because purchase_orders.status is the
--   CURRENT status (a closed order was open in earlier months). The contract's final-cutoff figure that counts only
--   currently confirmed orders is on_order_confirmed_only, the difference is open S-04 (closed orders with a partial line).
-- backorders = quantity opened by the cutoff and not closed by it. position = on_hand + on_order - backorders (reserved
--   is not subtracted). Month-end cutoff = last second of the last UTC day.
WITH cuts AS (
    SELECT to_char(m, 'YYYY-MM') AS month,
           ((m + interval '1 month') AT TIME ZONE 'UTC') - interval '1 second' AS as_of
      FROM generate_series(timestamp '2025-04-01', timestamp '2026-09-01', interval '1 month') AS m
), stock AS (
    SELECT c.month, c.as_of, l.product_id, l.location_id, sum(l.quantity_delta) AS raw,
           min(l.running_day_order) AS low
      FROM cuts c JOIN ss_ledger l ON l.event_at <= c.as_of
     GROUP BY c.month, c.as_of, l.product_id, l.location_id
), lines AS (
    SELECT c.month, h.location_id, o.status,
           GREATEST(l.ordered_quantity - COALESCE((SELECT sum(r.received_quantity) FROM receipts r
                                                    WHERE r.po_line_id = l.po_line_id AND r.received_at <= c.as_of), 0), 0) AS open_q
      FROM cuts c
      JOIN purchase_orders o ON o.ordered_at <= c.as_of AND o.status <> 'cancelled'
      JOIN purchase_order_lines l ON l.purchase_order_id = o.purchase_order_id
      JOIN ss_home h ON h.product_id = l.product_id
), bo AS (
    SELECT c.month, b.location_id, sum(b.quantity) AS q
      FROM cuts c JOIN backorders b ON b.opened_at <= c.as_of AND (b.closed_at IS NULL OR b.closed_at > c.as_of)
     GROUP BY c.month, b.location_id
), by_loc AS (
    SELECT c.month, lo.location_id, lo.storage_capacity,
           COALESCE((SELECT sum(GREATEST(s.raw, 0)) FROM stock s WHERE s.month = c.month AND s.location_id = lo.location_id), 0) AS on_hand,
           COALESCE((SELECT sum(open_q) FROM lines x WHERE x.month = c.month AND x.location_id = lo.location_id), 0) AS on_order,
           COALESCE((SELECT sum(open_q) FROM lines x WHERE x.month = c.month AND x.location_id = lo.location_id AND x.status = 'confirmed'), 0) AS on_order_confirmed_only,
           COALESCE((SELECT q FROM bo WHERE bo.month = c.month AND bo.location_id = lo.location_id), 0) AS backorders,
           (SELECT count(*) FROM stock s WHERE s.month = c.month AND s.location_id = lo.location_id AND (s.raw < 0 OR s.low < 0)) AS negative_pairs
      FROM cuts c CROSS JOIN locations lo
)
SELECT month, location_id, on_hand::int, on_order::int, backorders::int,
       (on_hand + on_order - backorders)::int AS position,
       on_order_confirmed_only::int,
       round(100.0 * (on_hand + on_order) / storage_capacity, 1) AS pct_of_capacity,
       negative_pairs::int
  FROM by_loc
 ORDER BY month, location_id;
