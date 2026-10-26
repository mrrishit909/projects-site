-- BI: fact_draft_order (docs/bi-package.md). Grain: one row per SKU x location x as-of x scenario. The seeded snapshot has no rows in
-- draft_orders (the API command writes them), so this is the arithmetic of query 02 for all 60 pairs at the cutoff, scenario_key
-- 'none' (replenishment_params, parameter_source 'params'), triggered or not, plus persisted draft_orders rows when any exist.
-- Needs 00_ledger_views.sql.
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
SELECT to_char((SELECT as_of FROM p) AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS date_key, product_id, location_id, supplier_id,
       'none'::text AS scenario_key, 'params' AS parameter_source, on_hand::int, on_order::int, backorders::int, position::int AS inventory_position,
       reorder_point, target_position, triggered, raw_order::int, moq AS minimum_order_quantity, after_moq::int AS order_after_moq,
       pack_size, order_qty::int AS order_quantity, unit_cost AS unit_cost_in_force, round(order_qty * unit_cost, 2) AS order_value
  FROM full_arith
UNION ALL
SELECT to_char(d.as_of AT TIME ZONE 'UTC', 'YYYYMMDD')::int, d.product_id, d.location_id, d.supplier_id, COALESCE(d.scenario_id, 'none'), d.parameter_source,
       NULL, NULL, NULL, d.inventory_position, d.reorder_point, d.target_position, d.order_quantity > 0, d.raw_order,
       d.minimum_order_quantity, d.order_after_moq, d.pack_size, d.order_quantity, NULL, NULL
  FROM draft_orders d
 ORDER BY 1, 2, 3;
