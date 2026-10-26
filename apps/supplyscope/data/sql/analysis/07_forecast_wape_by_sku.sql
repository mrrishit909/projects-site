-- 07: forecast accuracy by SKU, baselines against the model, from the stored forecast_points (P03-DOMAIN-01, P03-DOMAIN-04,
-- P03-TEST-02, P03-TEST-06, contract D-03). 14 pairs x 4 cutoffs x 14 target days x 3 models. Actual = observed units on sales
-- rows for the target date (0 when none). WAPE = sum|actual - forecast| / sum actual, blank when the actuals sum to 0.
-- naive and seasonal_naive (period 7) are the baselines, ewma (alpha 0.3) is the model. All three are scored on the same
-- points, so a lower WAPE is a lower MAE: ewma 'counts' only when it beats seasonal_naive (contract D-03).
-- leaky_points must be 0 (a target date on or before its cutoff would use the future). zero_demand_runs = runs whose 14-day
-- actuals sum to 0 (the intermittent SKUs, disclosed rather than hidden). selected_models = the stored selected_model per run.
-- Open S-03: the model's promotion factor applies planned_uplift instead of 1 + uplift, so ewma on promoted SKUs is suspect.
WITH pts AS (
    SELECT r.product_id, r.location_id, r.forecast_run_id, r.cutoff, r.selected_model, f.model, f.target_date, f.forecast_value,
           COALESCE((SELECT sum(s.quantity) FROM sales s
                      WHERE s.product_id = r.product_id AND s.location_id = r.location_id
                        AND (s.sold_at AT TIME ZONE 'UTC')::date = f.target_date), 0) AS actual
      FROM forecast_runs r JOIN forecast_points f ON f.forecast_run_id = r.forecast_run_id
), run_actual AS (
    SELECT product_id, location_id, forecast_run_id, sum(actual) FILTER (WHERE model = 'naive') AS run_actual FROM pts GROUP BY 1, 2, 3
), agg AS (
    SELECT product_id, location_id,
           count(DISTINCT forecast_run_id) AS runs,
           count(*) FILTER (WHERE model = 'naive') AS points,
           sum(actual) FILTER (WHERE model = 'naive') AS total_actual,
           sum(abs(actual - forecast_value)) FILTER (WHERE model = 'naive') AS e_naive,
           sum(abs(actual - forecast_value)) FILTER (WHERE model = 'seasonal_naive') AS e_snaive,
           sum(abs(actual - forecast_value)) FILTER (WHERE model = 'ewma') AS e_ewma,
           count(*) FILTER (WHERE target_date <= (cutoff AT TIME ZONE 'UTC')::date) AS leaky_points,
           string_agg(DISTINCT selected_model, '+' ORDER BY selected_model) AS selected_models
      FROM pts GROUP BY product_id, location_id
)
SELECT a.product_id, a.location_id, pr.abc_class, a.runs::int, a.points::int, a.total_actual::int,
       (SELECT count(*) FROM run_actual ra WHERE ra.product_id = a.product_id AND ra.location_id = a.location_id AND ra.run_actual = 0)::int AS zero_demand_runs,
       round(a.e_naive / NULLIF(a.total_actual, 0), 6) AS wape_naive,
       round(a.e_snaive / NULLIF(a.total_actual, 0), 6) AS wape_seasonal_naive,
       round(a.e_ewma / NULLIF(a.total_actual, 0), 6) AS wape_ewma,
       CASE WHEN a.total_actual = 0 THEN NULL WHEN a.e_ewma < a.e_snaive THEN 'yes' ELSE 'no' END AS ewma_beats_seasonal_naive,
       a.leaky_points::int, a.selected_models
  FROM agg a JOIN products pr ON pr.product_id = a.product_id
 ORDER BY a.product_id;
