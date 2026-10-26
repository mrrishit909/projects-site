-- SupplyScope reference metrics: an independent SQL recomputation of the golden numbers (no code shared with the
-- Python domain). Parameters: %(as_of)s, %(window_start)s, %(window_end)s (NULL = up to and including as_of).
-- D-01 day order inside a date: receipts (0), then sales (1), then review and the rest (2), then event_at, id.
-- One row: the keys of expected.json, then the extra keys stockout_calendar_days_share and observed_sku_days (R3-01).
-- Money is numeric(14,2) text, rates are numeric text at 6 dp (ROUND half up). Sums and the integer outputs are BIGINT
-- (R3-07: an int4 cast overflowed on large ledgers). Unmet-demand rows recorded under a scenario (scenario_id not null)
-- are not canonical and are excluded (R3-02). The position sums the unclamped ledger over every location (R3-04, R3-07).
-- stockout_days = sum of pair stockout days / (active pairs x calendar days observed), pairs active by as_of (R3-01).
WITH p AS (
    SELECT %(as_of)s::timestamptz AS as_of, %(window_start)s::timestamptz AS ws, %(window_end)s::timestamptz AS we
), day_ord AS (
    SELECT m.product_id, m.location_id, m.quantity_delta,
           row_number() OVER (PARTITION BY m.product_id, m.location_id
                              ORDER BY (m.event_at AT TIME ZONE 'UTC')::date,
                                       CASE m.movement_type WHEN 'receipt' THEN 0 WHEN 'sale' THEN 1 ELSE 2 END,
                                       m.event_at, m.movement_id) AS seq
      FROM inventory_movements m, p WHERE m.event_at <= p.as_of
), day_run AS (
    SELECT product_id, location_id,
           sum(quantity_delta) OVER (PARTITION BY product_id, location_id ORDER BY seq) AS run FROM day_ord
), time_ord AS (
    SELECT m.product_id, m.location_id, m.quantity_delta,
           row_number() OVER (PARTITION BY m.product_id, m.location_id ORDER BY m.event_at, m.movement_id) AS seq
      FROM inventory_movements m, p WHERE m.event_at <= p.as_of
), time_run AS (
    SELECT product_id, location_id,
           sum(quantity_delta) OVER (PARTITION BY product_id, location_id ORDER BY seq) AS run FROM time_ord
), stock AS (
    SELECT t.product_id, t.location_id, t.raw, GREATEST(t.raw, 0) AS on_hand,
           LEAST(0, (SELECT min(run) FROM day_run d WHERE d.product_id = t.product_id AND d.location_id = t.location_id)) AS low,
           LEAST(0, (SELECT min(run) FROM time_run d WHERE d.product_id = t.product_id AND d.location_id = t.location_id)) AS naive_low
      FROM (SELECT product_id, location_id, sum(quantity_delta) AS raw FROM day_ord GROUP BY 1, 2) t
), open_lines AS (
    SELECT l.product_id,
           GREATEST(l.ordered_quantity - COALESCE((SELECT sum(r.received_quantity) FROM receipts r, p
                                                    WHERE r.po_line_id = l.po_line_id AND r.received_at <= p.as_of), 0), 0) AS open_q
      FROM purchase_order_lines l JOIN purchase_orders o ON o.purchase_order_id = l.purchase_order_id, p
     WHERE o.status = 'confirmed' AND o.ordered_at <= p.as_of
), alloc AS (
    SELECT pr.product_id,
           COALESCE((SELECT min(x.location_id) FROM replenishment_params x WHERE x.product_id = pr.product_id),
                    (SELECT min(x.location_id) FROM inventory_movements x WHERE x.product_id = pr.product_id),
                    (SELECT min(location_id) FROM locations)) AS location_id
      FROM products pr
), open_bo AS (
    SELECT b.product_id, b.location_id, sum(b.quantity) AS q
      FROM backorders b, p WHERE b.scenario_id IS NULL AND b.opened_at <= p.as_of
       AND (b.closed_at IS NULL OR b.closed_at > p.as_of) GROUP BY 1, 2
), rep AS (
    SELECT rp.product_id, rp.location_id, rp.reorder_point, rp.target_position, pr.minimum_order_quantity AS moq, pr.pack_size,
           COALESCE(s.raw, 0) AS oh,
           CASE WHEN a.location_id = rp.location_id
                THEN COALESCE((SELECT sum(open_q) FROM open_lines o WHERE o.product_id = rp.product_id), 0) ELSE 0 END AS oo,
           COALESCE(b.q, 0) AS bo
      FROM replenishment_params rp
      JOIN products pr ON pr.product_id = rp.product_id
      JOIN alloc a ON a.product_id = rp.product_id
      LEFT JOIN stock s ON s.product_id = rp.product_id AND s.location_id = rp.location_id
      LEFT JOIN open_bo b ON b.product_id = rp.product_id AND b.location_id = rp.location_id
), rep2 AS (
    SELECT *, (oh + oo - bo) AS pos, (oh + oo - bo) < reorder_point AS trig FROM rep
), rep3 AS (
    SELECT *, CASE WHEN trig THEN GREATEST(target_position - pos, 0) ELSE 0 END AS raw_q FROM rep2
), rep4 AS (
    SELECT *, CASE WHEN trig THEN GREATEST(raw_q, moq) ELSE 0 END AS after_moq FROM rep3
), rep5 AS (
    SELECT *, CASE WHEN trig THEN CEIL(after_moq::numeric / pack_size)::bigint * pack_size ELSE 0 END AS qty FROM rep4
), demand AS (
    SELECT (SELECT COALESCE(sum(s.quantity), 0) FROM sales s, p
             WHERE s.sold_at <= p.as_of AND s.sold_at >= p.ws AND (p.we IS NULL OR s.sold_at < p.we)) AS fulfilled,
           (SELECT COALESCE(sum(q), 0) FROM (
                SELECT b.quantity AS q FROM backorders b, p
                 WHERE b.scenario_id IS NULL AND b.opened_at <= p.as_of AND b.opened_at >= p.ws AND (p.we IS NULL OR b.opened_at < p.we)
                UNION ALL
                SELECT l.quantity FROM lost_sales l, p
                 WHERE l.scenario_id IS NULL AND l.occurred_at <= p.as_of AND l.occurred_at >= p.ws
                   AND (p.we IS NULL OR l.occurred_at < p.we)) u) AS unmet,
           (SELECT count(DISTINCT d) FROM (
                SELECT (b.opened_at AT TIME ZONE 'UTC')::date AS d FROM backorders b, p
                 WHERE b.scenario_id IS NULL AND b.opened_at <= p.as_of AND b.opened_at >= p.ws
                   AND (p.we IS NULL OR b.opened_at < p.we)
                UNION ALL
                SELECT (l.occurred_at AT TIME ZONE 'UTC')::date FROM lost_sales l, p
                 WHERE l.scenario_id IS NULL AND l.occurred_at <= p.as_of AND l.occurred_at >= p.ws
                   AND (p.we IS NULL OR l.occurred_at < p.we)) u) AS so_days,
           (SELECT count(*) FROM (
                SELECT b.product_id, b.location_id, (b.opened_at AT TIME ZONE 'UTC')::date AS d FROM backorders b, p
                 WHERE b.scenario_id IS NULL AND b.opened_at <= p.as_of AND b.opened_at >= p.ws
                   AND (p.we IS NULL OR b.opened_at < p.we)
                UNION
                SELECT l.product_id, l.location_id, (l.occurred_at AT TIME ZONE 'UTC')::date FROM lost_sales l, p
                 WHERE l.scenario_id IS NULL AND l.occurred_at <= p.as_of AND l.occurred_at >= p.ws
                   AND (p.we IS NULL OR l.occurred_at < p.we)) u) AS so_pair_days,
           (SELECT count(*) FROM (
                SELECT m.product_id, m.location_id FROM inventory_movements m, p WHERE m.event_at <= p.as_of
                UNION SELECT s.product_id, s.location_id FROM sales s, p WHERE s.sold_at <= p.as_of
                UNION SELECT b.product_id, b.location_id FROM backorders b, p
                       WHERE b.scenario_id IS NULL AND b.opened_at <= p.as_of
                UNION SELECT l.product_id, l.location_id FROM lost_sales l, p
                       WHERE l.scenario_id IS NULL AND l.occurred_at <= p.as_of) a) AS n_pairs,
           GREATEST(((LEAST(p.as_of, COALESCE(p.we - interval '1 microsecond', p.as_of)) AT TIME ZONE 'UTC')::date
                     - (p.ws AT TIME ZONE 'UTC')::date) + 1, 0) AS obs_days
      FROM p
), capital AS (
    SELECT COALESCE(sum(s.on_hand * COALESCE(
               (SELECT cv.unit_cost FROM cost_versions cv, p
                 WHERE cv.product_id = s.product_id
                   AND (cv.effective_from AT TIME ZONE 'UTC')::date <= (p.as_of AT TIME ZONE 'UTC')::date
                 ORDER BY cv.effective_from DESC, cv.cost_version_id DESC LIMIT 1), pr.unit_cost)), 0) AS value
      FROM stock s JOIN products pr ON pr.product_id = s.product_id
), t AS (
    SELECT (SELECT COALESCE(sum(on_hand), 0) FROM stock) AS on_hand,
           (SELECT COALESCE(sum(raw), 0) FROM stock) AS on_hand_raw,
           (SELECT COALESCE(sum(open_q), 0) FROM open_lines) AS on_order,
           (SELECT COALESCE(sum(q), 0) FROM open_bo) AS backorders,
           (SELECT COALESCE(sum(r.quantity), 0) FROM reservations r, p
             WHERE r.reserved_at <= p.as_of AND (r.released_at IS NULL OR r.released_at > p.as_of)) AS reserved,
           (SELECT count(*) FROM rep5) AS n_params
)
SELECT CASE WHEN d.fulfilled + d.unmet = 0 THEN NULL
            ELSE round(d.fulfilled::numeric / (d.fulfilled + d.unmet), 6)::text END AS fill_rate,
       (d.fulfilled + d.unmet)::bigint AS requested_units,
       d.fulfilled::bigint AS fulfilled_units,
       d.unmet::bigint AS unmet_units,
       d.obs_days::bigint AS observed_days,
       d.so_pair_days::bigint AS stockout_day_count,
       CASE WHEN NOT EXISTS (SELECT 1 FROM inventory_movements) AND NOT EXISTS (SELECT 1 FROM sales) THEN NULL
            WHEN d.obs_days = 0 OR d.n_pairs = 0 THEN NULL
            ELSE round(d.so_pair_days::numeric / (d.n_pairs::numeric * d.obs_days), 6)::text END AS stockout_days,
       LEAST(0, COALESCE((SELECT min(low) FROM stock), 0))::bigint AS running_stock_min,
       LEAST(0, COALESCE((SELECT min(naive_low) FROM stock), 0))::bigint AS timestamp_order_stock_min,
       COALESCE((SELECT bool_or(raw < 0 OR low < 0) FROM stock), false) AS negative_stock,
       round(c.value, 2)::text AS working_capital,
       (NOT EXISTS (SELECT 1 FROM inventory_movements) AND NOT EXISTS (SELECT 1 FROM sales)) AS empty_population,
       t.on_hand::bigint AS on_hand, t.on_order::bigint AS on_order, t.backorders::bigint AS backorders,
       t.reserved::bigint AS reserved, (t.on_hand - t.reserved)::bigint AS available,
       (t.on_hand_raw + t.on_order - t.backorders)::bigint AS inventory_position,
       (SELECT CASE WHEN count(*) = 0 THEN NULL ELSE sum(reorder_point) END FROM rep5)::bigint AS reorder_point,
       (SELECT CASE WHEN count(*) = 0 THEN NULL ELSE sum(target_position) END FROM rep5)::bigint AS target_position,
       (SELECT CASE WHEN count(*) = 0 THEN NULL ELSE bool_or(trig) END FROM rep5) AS reorder_triggered,
       (SELECT CASE WHEN count(*) = 0 THEN NULL ELSE sum(raw_q) END FROM rep5)::bigint AS raw_order,
       (SELECT CASE WHEN count(*) = 0 THEN NULL ELSE sum(after_moq) END FROM rep5)::bigint AS order_after_moq,
       (SELECT CASE WHEN count(*) = 0 THEN NULL ELSE sum(qty) END FROM rep5)::bigint AS order_quantity,
       CASE WHEN NOT EXISTS (SELECT 1 FROM inventory_movements) AND NOT EXISTS (SELECT 1 FROM sales) THEN NULL
            WHEN d.obs_days = 0 THEN NULL
            ELSE round(d.so_days::numeric / d.obs_days, 6)::text END AS stockout_calendar_days_share,
       (d.n_pairs * d.obs_days)::bigint AS observed_sku_days
  FROM t, demand d, capital c;
