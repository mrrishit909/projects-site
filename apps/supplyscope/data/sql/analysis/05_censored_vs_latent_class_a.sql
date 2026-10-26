-- 05: censored (observed) versus latent demand on stockout days for the class A promoted SKUs (P03-DOMAIN-03, P03-TEST-01,
-- contract D-03). Class A = the 8 SKUs, all with 3 ten-day promotion windows. A stockout day = a UTC date with a backorder
-- opened or a lost sale for the pair. latent_demand holds positive days only (an absent day is 0) and is the generator's
-- published truth, never a feature. observed = units on sales rows. censored_units = latent - observed on stockout days;
-- unmet_recorded = backorder + lost-sale units on those days: they should be equal. unmet_policy is the policy of record of
-- the location (lost_sale at loc-01 and loc-02, backlog at loc-03). days_observed_ne_latent counts the OTHER days on which
-- observed and latent differ (should be 0). Rates are rounded half up at 6 dp.
WITH a_pairs AS (
    SELECT rp.product_id, rp.location_id,
           CASE WHEN EXISTS (SELECT 1 FROM backorders b WHERE b.location_id = rp.location_id) THEN 'backlog' ELSE 'lost_sale' END AS unmet_policy
      FROM replenishment_params rp JOIN products pr ON pr.product_id = rp.product_id WHERE pr.abc_class = 'A'
), days AS (
    SELECT a.product_id, a.location_id, a.unmet_policy, d::date AS day
      FROM a_pairs a CROSS JOIN generate_series(date '2025-04-01', date '2026-09-30', interval '1 day') AS d
), obs AS (
    SELECT product_id, location_id, (sold_at AT TIME ZONE 'UTC')::date AS day, sum(quantity) AS q FROM sales GROUP BY 1, 2, 3
), unmet AS (
    SELECT product_id, location_id, day, sum(q) AS q FROM (
        SELECT product_id, location_id, (opened_at AT TIME ZONE 'UTC')::date AS day, quantity AS q FROM backorders
        UNION ALL
        SELECT product_id, location_id, (occurred_at AT TIME ZONE 'UTC')::date, quantity FROM lost_sales) u
     GROUP BY 1, 2, 3
), per_day AS (
    SELECT d.product_id, d.location_id, d.unmet_policy, d.day,
           COALESCE(o.q, 0) AS observed, COALESCE(l.latent_quantity, 0) AS latent, COALESCE(u.q, 0) AS unmet,
           u.day IS NOT NULL AS stockout,
           EXISTS (SELECT 1 FROM promotions pm WHERE pm.product_id = d.product_id
                      AND d.day BETWEEN (pm.starts_at AT TIME ZONE 'UTC')::date AND (pm.ends_at AT TIME ZONE 'UTC')::date) AS promo
      FROM days d
      LEFT JOIN obs o ON o.product_id = d.product_id AND o.location_id = d.location_id AND o.day = d.day
      LEFT JOIN latent_demand l ON l.product_id = d.product_id AND l.location_id = d.location_id AND l.demand_date = d.day
      LEFT JOIN unmet u ON u.product_id = d.product_id AND u.location_id = d.location_id AND u.day = d.day
)
SELECT product_id, location_id, unmet_policy,
       count(*) FILTER (WHERE stockout)::int AS stockout_days,
       count(*) FILTER (WHERE stockout AND promo)::int AS stockout_days_in_promo,
       sum(observed) FILTER (WHERE stockout)::int AS observed_on_stockout_days,
       sum(latent) FILTER (WHERE stockout)::int AS latent_on_stockout_days,
       (sum(latent) FILTER (WHERE stockout) - sum(observed) FILTER (WHERE stockout))::int AS censored_units,
       COALESCE(sum(unmet) FILTER (WHERE stockout), 0)::int AS unmet_recorded,
       round(1 - sum(observed) FILTER (WHERE stockout)::numeric / NULLIF(sum(latent) FILTER (WHERE stockout), 0), 6) AS share_of_latent_unseen,
       count(*) FILTER (WHERE NOT stockout AND observed <> latent)::int AS days_observed_ne_latent
  FROM per_day
 GROUP BY product_id, location_id, unmet_policy
 ORDER BY product_id;
