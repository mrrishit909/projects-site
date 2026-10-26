-- 06: working capital by location at the cost in force, across the one cost step (P03-MET-12, P03-TEST-12, contract D-05).
-- Every day of every SKU x location is valued at its OWN cost: the latest cost_versions row with effective_from (UTC date) on
-- or before that day, else products.unit_cost (the cost before any version). value = MAX(end-of-day stock, 0) x cost.
-- The step: +6 % on the 15 sup-04 products from 2026-02-01. Columns: end-of-month value per location (the last day of the
-- month), the total, the average DAILY value of the month (the contract's average inventory value), the same average at the
-- base cost with the step ignored, and their difference (the step effect, 0 before February 2026). Row ALL = the average over
-- all 548 days (the contract's average inventory value). Money is numeric(14,2).
WITH pairs AS (
    SELECT rp.product_id, rp.location_id, pr.unit_cost AS base_cost
      FROM replenishment_params rp JOIN products pr ON pr.product_id = rp.product_id
), daily AS (
    SELECT product_id, location_id, event_date AS day, sum(quantity_delta) AS d FROM ss_ledger GROUP BY 1, 2, 3
), grid AS (
    SELECT p.product_id, p.location_id, p.base_cost, g::date AS day
      FROM pairs p CROSS JOIN generate_series(date '2025-03-31', date '2026-09-30', interval '1 day') AS g
), eod AS (
    SELECT g.product_id, g.location_id, g.base_cost, g.day,
           sum(COALESCE(d.d, 0)) OVER (PARTITION BY g.product_id, g.location_id ORDER BY g.day) AS raw
      FROM grid g LEFT JOIN daily d ON d.product_id = g.product_id AND d.location_id = g.location_id AND d.day = g.day
), valued AS (
    SELECT e.location_id, e.day, to_char(e.day, 'YYYY-MM') AS month, GREATEST(e.raw, 0) AS on_hand,
           GREATEST(e.raw, 0) * COALESCE((SELECT cv.unit_cost FROM cost_versions cv
                                           WHERE cv.product_id = e.product_id AND (cv.effective_from AT TIME ZONE 'UTC')::date <= e.day
                                           ORDER BY cv.effective_from DESC, cv.cost_version_id DESC LIMIT 1), e.base_cost) AS value,
           GREATEST(e.raw, 0) * e.base_cost AS value_base
      FROM eod e WHERE e.day >= date '2025-04-01'
), by_day AS (
    SELECT month, day, location_id, sum(value) AS value, sum(value_base) AS value_base FROM valued GROUP BY month, day, location_id
), month_tot AS (
    SELECT month, day, sum(value) AS value, sum(value_base) AS value_base FROM by_day GROUP BY month, day
), last_day AS (
    SELECT month, max(day) AS day FROM by_day GROUP BY month
)
SELECT l.month,
       round(max(b.value) FILTER (WHERE b.location_id = 'loc-01'), 2) AS end_loc_01,
       round(max(b.value) FILTER (WHERE b.location_id = 'loc-02'), 2) AS end_loc_02,
       round(max(b.value) FILTER (WHERE b.location_id = 'loc-03'), 2) AS end_loc_03,
       round(sum(b.value), 2) AS end_total,
       round((SELECT avg(t.value) FROM month_tot t WHERE t.month = l.month), 2) AS avg_daily_total,
       round((SELECT avg(t.value_base) FROM month_tot t WHERE t.month = l.month), 2) AS avg_daily_at_base_cost,
       round((SELECT avg(t.value - t.value_base) FROM month_tot t WHERE t.month = l.month), 2) AS step_effect
  FROM last_day l JOIN by_day b ON b.month = l.month AND b.day = l.day
 GROUP BY l.month
UNION ALL
SELECT 'ALL', NULL, NULL, NULL, NULL, round(avg(value), 2), round(avg(value_base), 2), round(avg(value - value_base), 2) FROM month_tot
 ORDER BY month;
