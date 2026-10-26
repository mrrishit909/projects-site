-- BI: fact_movement_day (docs/bi-package.md). Grain: one row per SKU x location x UTC date, 2025-04-01 .. 2026-09-30 (60 pairs x 548 days).
-- Needs 00_ledger_views.sql. Stock is the contract's day-order reconstruction (the closing value of a day does not depend on the
-- order inside it). Value at the cost in force on that date (D-05), negative stock valued at 0 (D-01). cogs_value = fulfilled units x that cost.
WITH pairs AS (
    SELECT rp.product_id, rp.location_id, pr.unit_cost AS base_cost
      FROM replenishment_params rp JOIN products pr ON pr.product_id = rp.product_id
), daily AS (
    SELECT product_id, location_id, event_date AS day,
           sum(quantity_delta) FILTER (WHERE movement_type = 'receipt') AS receipt_units,
           -sum(quantity_delta) FILTER (WHERE movement_type = 'sale') AS sale_movement_units,
           sum(quantity_delta) FILTER (WHERE movement_type NOT IN ('receipt', 'sale')) AS other_units,
           sum(quantity_delta) AS net
      FROM ss_ledger GROUP BY 1, 2, 3
), grid AS (
    SELECT p.product_id, p.location_id, p.base_cost, g::date AS day
      FROM pairs p CROSS JOIN generate_series(date '2025-03-31', date '2026-09-30', interval '1 day') AS g
), eod AS (
    SELECT g.*, COALESCE(d.receipt_units, 0) AS receipt_units, COALESCE(d.sale_movement_units, 0) AS sale_movement_units,
           COALESCE(d.other_units, 0) AS other_units,
           sum(COALESCE(d.net, 0)) OVER (PARTITION BY g.product_id, g.location_id ORDER BY g.day) AS closing_raw
      FROM grid g LEFT JOIN daily d ON d.product_id = g.product_id AND d.location_id = g.location_id AND d.day = g.day
), unmet AS (
    SELECT product_id, location_id, day, sum(q) AS q FROM (
        SELECT product_id, location_id, (opened_at AT TIME ZONE 'UTC')::date AS day, quantity AS q FROM backorders
        UNION ALL SELECT product_id, location_id, (occurred_at AT TIME ZONE 'UTC')::date, quantity FROM lost_sales) u GROUP BY 1, 2, 3
), sold AS (
    SELECT product_id, location_id, (sold_at AT TIME ZONE 'UTC')::date AS day, sum(quantity) AS q FROM sales GROUP BY 1, 2, 3
)
SELECT to_char(e.day, 'YYYYMMDD')::int AS date_key, e.product_id, e.location_id,
       e.receipt_units::int, e.sale_movement_units::int, COALESCE(s.q, 0)::int AS fulfilled_units, COALESCE(u.q, 0)::int AS unmet_units,
       (u.day IS NOT NULL) AS stockout_flag,
       e.closing_raw::int AS closing_on_hand_raw, GREATEST(e.closing_raw, 0)::int AS closing_on_hand,
       c.unit_cost AS unit_cost_in_force,
       round(GREATEST(e.closing_raw, 0) * c.unit_cost, 2) AS stock_value,
       round(COALESCE(s.q, 0) * c.unit_cost, 2) AS cogs_value
  FROM eod e
  CROSS JOIN LATERAL (SELECT COALESCE((SELECT cv.unit_cost FROM cost_versions cv WHERE cv.product_id = e.product_id
                                          AND (cv.effective_from AT TIME ZONE 'UTC')::date <= e.day
                                        ORDER BY cv.effective_from DESC, cv.cost_version_id DESC LIMIT 1), e.base_cost) AS unit_cost) c
  LEFT JOIN unmet u ON u.product_id = e.product_id AND u.location_id = e.location_id AND u.day = e.day
  LEFT JOIN sold s ON s.product_id = e.product_id AND s.location_id = e.location_id AND s.day = e.day
 WHERE e.day >= date '2025-04-01'
 ORDER BY e.day, e.product_id, e.location_id;
