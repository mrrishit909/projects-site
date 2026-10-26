-- 03: fill rate and stockout days by location and ABC class over the whole observed window 2025-04-01 .. 2026-09-30
-- (548 days), with location subtotals and an ALL row (P03-MET-09..10, P03-TEST-08, contract D-04 and D-06).
-- fulfilled = units on sales rows. unmet = backorders opened + lost sales (one event is one or the other, never both).
-- requested = fulfilled + unmet, fill_rate = fulfilled / requested. A stockout day of a pair is a date on which a backorder
-- opened or a lost sale occurred for it. stockout_pair_day_share = stockout pair-days / (pairs x 548): the share of
-- SKU x location x day cells with unmet demand. Rates are rounded half up at 6 dp.
WITH pairs AS (
    SELECT rp.product_id, rp.location_id, pr.abc_class
      FROM replenishment_params rp JOIN products pr ON pr.product_id = rp.product_id
), fulfilled AS (
    SELECT product_id, location_id, sum(quantity) AS q FROM sales
     WHERE sold_at >= timestamptz '2025-04-01 00:00:00+00' AND sold_at <= timestamptz '2026-09-30 23:59:59+00'
     GROUP BY product_id, location_id
), unmet_events AS (
    SELECT product_id, location_id, quantity, (opened_at AT TIME ZONE 'UTC')::date AS d FROM backorders
     WHERE opened_at >= timestamptz '2025-04-01 00:00:00+00' AND opened_at <= timestamptz '2026-09-30 23:59:59+00'
    UNION ALL
    SELECT product_id, location_id, quantity, (occurred_at AT TIME ZONE 'UTC')::date FROM lost_sales
     WHERE occurred_at >= timestamptz '2025-04-01 00:00:00+00' AND occurred_at <= timestamptz '2026-09-30 23:59:59+00'
), unmet AS (
    SELECT product_id, location_id, sum(quantity) AS q, count(DISTINCT d) AS so_days FROM unmet_events GROUP BY product_id, location_id
), per_pair AS (
    SELECT p.location_id, p.abc_class, COALESCE(f.q, 0) AS fulfilled, COALESCE(u.q, 0) AS unmet, COALESCE(u.so_days, 0) AS so_days
      FROM pairs p
      LEFT JOIN fulfilled f ON f.product_id = p.product_id AND f.location_id = p.location_id
      LEFT JOIN unmet u ON u.product_id = p.product_id AND u.location_id = p.location_id
)
SELECT COALESCE(location_id, 'ALL') AS location_id, COALESCE(abc_class, 'ALL') AS abc_class, count(*)::int AS pairs,
       sum(fulfilled)::int AS fulfilled_units, sum(unmet)::int AS unmet_units, (sum(fulfilled) + sum(unmet))::int AS requested_units,
       round(sum(fulfilled)::numeric / NULLIF(sum(fulfilled) + sum(unmet), 0), 6) AS fill_rate,
       sum(so_days)::int AS stockout_pair_days,
       round(sum(so_days)::numeric / (count(*) * 548), 6) AS stockout_pair_day_share
  FROM per_pair
 GROUP BY ROLLUP (location_id, abc_class)
 ORDER BY GROUPING(location_id), location_id, GROUPING(abc_class), abc_class;
