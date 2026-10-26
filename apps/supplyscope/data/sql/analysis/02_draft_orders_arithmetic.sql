-- 02: the draft buying plan at the snapshot cutoff 2026-09-30 23:59:59Z, one row per triggered SKU x location with every
-- arithmetic column (P03-GOLD-01, P03-MET-05..08, P03-FLOW-03, contract D-02 and D-06), plus a TOTAL row.
-- position = on hand + confirmed on order - open backorders. triggered = position < reorder point. raw = target - position.
-- after_moq = MAX(raw, MOQ). order_qty = CEILING(after_moq / pack) x pack. Not triggered means all three are 0.
-- On order here is the contract's: open quantity of CONFIRMED orders only (D-01), unlike query 01's as-of rule.
-- unit_cost is the cost in force on the as-of date (D-05) and order_value = order_qty x unit_cost: the working capital the plan adds.
-- The draft_orders table itself is empty in the seeded snapshot (rows are written by the API command), so this is the
-- arithmetic the command would persist, from replenishment_params (parameter_source = 'params').
WITH p AS (SELECT timestamptz '2026-09-30 23:59:59+00' AS as_of), stock AS (
    SELECT l.product_id, l.location_id, GREATEST(sum(l.quantity_delta), 0) AS on_hand
      FROM ss_ledger l, p WHERE l.event_at <= p.as_of GROUP BY l.product_id, l.location_id
), open_q AS (
    SELECT h.product_id,
           sum(GREATEST(l.ordered_quantity - COALESCE((SELECT sum(r.received_quantity) FROM receipts r, p
                                                         WHERE r.po_line_id = l.po_line_id AND r.received_at <= p.as_of), 0), 0)) AS q
      FROM purchase_order_lines l
      JOIN purchase_orders o ON o.purchase_order_id = l.purchase_order_id AND o.status = 'confirmed'
      JOIN ss_home h ON h.product_id = l.product_id, p
     WHERE o.ordered_at <= p.as_of
     GROUP BY h.product_id
), bo AS (
    SELECT b.product_id, b.location_id, sum(b.quantity) AS q
      FROM backorders b, p WHERE b.opened_at <= p.as_of AND (b.closed_at IS NULL OR b.closed_at > p.as_of)
     GROUP BY b.product_id, b.location_id
), calc AS (
    SELECT rp.product_id, rp.location_id, pr.abc_class, rp.supplier_id,
           COALESCE(s.on_hand, 0) AS on_hand,
           CASE WHEN h.location_id = rp.location_id THEN COALESCE(o.q, 0) ELSE 0 END AS on_order,
           COALESCE(b.q, 0) AS backorders,
           rp.reorder_point, rp.target_position, pr.minimum_order_quantity AS moq, pr.pack_size,
           COALESCE((SELECT cv.unit_cost FROM cost_versions cv, p WHERE cv.product_id = rp.product_id
                        AND (cv.effective_from AT TIME ZONE 'UTC')::date <= (p.as_of AT TIME ZONE 'UTC')::date
                      ORDER BY cv.effective_from DESC, cv.cost_version_id DESC LIMIT 1), pr.unit_cost) AS unit_cost
      FROM replenishment_params rp
      JOIN products pr ON pr.product_id = rp.product_id
      JOIN ss_home h ON h.product_id = rp.product_id
      LEFT JOIN stock s ON s.product_id = rp.product_id AND s.location_id = rp.location_id
      LEFT JOIN open_q o ON o.product_id = rp.product_id
      LEFT JOIN bo b ON b.product_id = rp.product_id AND b.location_id = rp.location_id
), arith AS (
    SELECT *, on_hand + on_order - backorders AS position,
           (on_hand + on_order - backorders) < reorder_point AS triggered FROM calc
), full_arith AS (
    SELECT *, CASE WHEN triggered THEN GREATEST(target_position - position, 0) ELSE 0 END AS raw_order,
              CASE WHEN triggered THEN GREATEST(GREATEST(target_position - position, 0), moq) ELSE 0 END AS after_moq,
              CASE WHEN triggered THEN CEIL(GREATEST(GREATEST(target_position - position, 0), moq)::numeric / pack_size)::int * pack_size ELSE 0 END AS order_qty
      FROM arith
)
SELECT * FROM (
SELECT product_id, location_id, abc_class, supplier_id, on_hand::int, on_order::int, backorders::int,
       position::int, reorder_point, target_position, raw_order::int, moq, after_moq::int, pack_size, order_qty::int,
       unit_cost, round(order_qty * unit_cost, 2) AS order_value
  FROM full_arith WHERE triggered
UNION ALL
SELECT 'TOTAL (' || count(*) FILTER (WHERE triggered) || ' of ' || count(*) || ' triggered)', NULL, NULL, NULL,
       sum(on_hand)::int, sum(on_order)::int, sum(backorders)::int, sum(position)::int, sum(reorder_point)::int,
       sum(target_position)::int, sum(raw_order)::int, NULL, sum(after_moq)::int, NULL, sum(order_qty)::int,
       NULL, round(sum(order_qty * unit_cost), 2)
  FROM full_arith
) t
 ORDER BY (product_id LIKE 'TOTAL%'), order_qty DESC NULLS LAST, product_id;
