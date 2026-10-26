-- 09: the golden fixture (P03-GOLD-01, contract D-01, D-02, D-04, D-05, D-06), computed from the tables of a database seeded
-- with tests/fixtures/golden/inputs.json. Stands alone (needs no views). Cutoff 2026-03-31 23:59:59Z, window 2026-03-01 ..
-- 2026-03-31 (31 days). Expected: on hand 40, on order 30, backorders 10, position 60, ROP 70, target 120, raw 60, MOQ 50 ->
-- 60, pack 24 -> 72; with the fixture's second line (position_80) position 80 and every order quantity 0.
-- Day order (D-01): inside a date receipts, then sales, then the rest. running_min_day_order must be 0; the same movements in
-- plain timestamp order reach -35 on 2026-03-12 (a sale stamped 09:00 before a receipt stamped 15:00).
WITH p AS (SELECT timestamptz '2026-03-31 23:59:59+00' AS as_of, timestamptz '2026-03-01 00:00:00+00' AS ws), mv AS (
    SELECT m.product_id, m.location_id, m.quantity_delta,
           sum(m.quantity_delta) OVER (PARTITION BY m.product_id, m.location_id
                                       ORDER BY (m.event_at AT TIME ZONE 'UTC')::date,
                                                CASE m.movement_type WHEN 'receipt' THEN 0 WHEN 'sale' THEN 1 ELSE 2 END,
                                                m.event_at, m.movement_id) AS run_day,
           sum(m.quantity_delta) OVER (PARTITION BY m.product_id, m.location_id ORDER BY m.event_at, m.movement_id) AS run_ts
      FROM inventory_movements m, p WHERE m.event_at <= p.as_of
), stock AS (
    SELECT product_id, location_id, sum(quantity_delta) AS raw, LEAST(0, min(run_day)) AS low_day, LEAST(0, min(run_ts)) AS low_ts
      FROM mv GROUP BY product_id, location_id
), open_lines AS (
    SELECT l.product_id, GREATEST(l.ordered_quantity - COALESCE((SELECT sum(r.received_quantity) FROM receipts r, p
                                                                  WHERE r.po_line_id = l.po_line_id AND r.received_at <= p.as_of), 0), 0) AS q
      FROM purchase_order_lines l JOIN purchase_orders o ON o.purchase_order_id = l.purchase_order_id, p
     WHERE o.status = 'confirmed' AND o.ordered_at <= p.as_of
), bo AS (
    SELECT b.product_id, b.location_id, sum(b.quantity) AS q FROM backorders b, p
     WHERE b.opened_at <= p.as_of AND (b.closed_at IS NULL OR b.closed_at > p.as_of) GROUP BY b.product_id, b.location_id
), calc AS (
    SELECT rp.product_id, GREATEST(s.raw, 0) AS on_hand, s.low_day, s.low_ts,
           COALESCE((SELECT sum(q) FROM open_lines o WHERE o.product_id = rp.product_id), 0) AS on_order,
           COALESCE(b.q, 0) AS backorders, rp.reorder_point, rp.target_position, pr.minimum_order_quantity AS moq, pr.pack_size, pr.unit_cost
      FROM replenishment_params rp
      JOIN products pr ON pr.product_id = rp.product_id
      JOIN stock s ON s.product_id = rp.product_id AND s.location_id = rp.location_id
      LEFT JOIN bo b ON b.product_id = rp.product_id AND b.location_id = rp.location_id
), arith AS (
    SELECT *, on_hand + on_order - backorders AS position, (on_hand + on_order - backorders) < reorder_point AS triggered FROM calc
), demand AS (
    SELECT (SELECT COALESCE(sum(s.quantity), 0) FROM sales s, p WHERE s.sold_at >= p.ws AND s.sold_at <= p.as_of) AS fulfilled,
           (SELECT COALESCE(sum(b.quantity), 0) FROM backorders b, p WHERE b.opened_at >= p.ws AND b.opened_at <= p.as_of) AS unmet,
           (SELECT count(DISTINCT (b.opened_at AT TIME ZONE 'UTC')::date) FROM backorders b, p WHERE b.opened_at >= p.ws AND b.opened_at <= p.as_of) AS so_days
)
SELECT a.on_hand::int, a.on_order::int, a.backorders::int, a.position::int, a.reorder_point, a.target_position, a.triggered,
       CASE WHEN a.triggered THEN GREATEST(a.target_position - a.position, 0) ELSE 0 END::int AS raw_order,
       a.moq,
       CASE WHEN a.triggered THEN GREATEST(GREATEST(a.target_position - a.position, 0), a.moq) ELSE 0 END::int AS order_after_moq,
       a.pack_size,
       CASE WHEN a.triggered THEN CEIL(GREATEST(GREATEST(a.target_position - a.position, 0), a.moq)::numeric / a.pack_size)::int * a.pack_size ELSE 0 END AS order_quantity,
       a.low_day::int AS running_min_day_order, a.low_ts::int AS running_min_timestamp_order,
       round(a.on_hand * a.unit_cost, 2) AS working_capital,
       d.fulfilled::int AS fulfilled_units, d.unmet::int AS unmet_units,
       round(d.fulfilled::numeric / NULLIF(d.fulfilled + d.unmet, 0), 6) AS fill_rate,
       d.so_days::int AS stockout_days_count,
       round(d.so_days::numeric / 31, 6) AS stockout_days
  FROM arith a, demand d;
