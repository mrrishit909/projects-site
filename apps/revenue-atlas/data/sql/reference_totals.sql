-- reference_totals.sql: an INDEPENDENT recomputation of the contract's money metrics
-- (docs/contracts.md D-01..D-05) straight from the tables. It does not call the Python
-- domain and does not read freight_allocations / discount_allocations: it carries its own
-- largest-remainder allocation (D-04) built from integer arithmetic on window functions.
--
-- Parameters (psycopg named style): %(lo)s and %(hi)s, timestamptz or NULL, window [lo, hi).
-- Population: shipment lines of 'shipped' / 'partially_returned' orders that have a
-- cost_version_id (set by C02) valid for the shipped UTC date and an FX rate for that date
-- (USD->USD needs no row). Everything else is quarantined, i.e. excluded (D-01..D-03).
-- Window semantics (docs/contracts.md D-01a): shipment lines are selected by shipped_at (gross,
-- discounts, COGS before returns, freight); return credits are selected by credit_date (taken as
-- 00:00 UTC of that date) for credits, recoverable cost, from lines in the population whatever
-- their shipped_at. No window (both NULL): everything counts.
--
-- Largest remainder, per group G with total T cents and integer weights w_i, W = sum(w):
--   floor_i = div(T * w_i, W);  rem_i = mod(T * w_i, W);  leftover = T - sum(floor_i)
--   the `leftover` rows with the largest rem_i (ties: lowest key) receive one extra cent.
WITH
base AS (
    SELECT sl.shipment_line_id, sl.shipment_id, sl.line_id, sl.shipped_quantity,
           ol.quantity AS ordered_qty, ol.unit_price, ol.order_id,
           s.shipped_at, s.shipping_cost,
           COALESCE(fo.rate, CASE WHEN o.currency = 'USD' THEN 1 END) AS order_rate,
           COALESCE(fs.rate, CASE WHEN s.currency = 'USD' THEN 1 END) AS ship_rate,
           cv.unit_cost,
           sl.shipped_quantity * ol.unit_price AS native_gross
    FROM shipment_lines sl
    JOIN order_lines ol ON ol.line_id = sl.line_id
    JOIN orders o       ON o.order_id = ol.order_id
    JOIN shipments s    ON s.shipment_id = sl.shipment_id
    JOIN cost_versions cv ON cv.cost_version_id = sl.cost_version_id
                         AND cv.product_id = ol.product_id
                         AND cv.valid_from <= (s.shipped_at AT TIME ZONE 'UTC')::date
                         AND (cv.valid_to IS NULL OR (s.shipped_at AT TIME ZONE 'UTC')::date < cv.valid_to)
    LEFT JOIN exchange_rates fo ON fo.currency = o.currency AND fo.reporting_currency = 'USD'
                               AND fo.rate_date = (s.shipped_at AT TIME ZONE 'UTC')::date
    LEFT JOIN exchange_rates fs ON fs.currency = s.currency AND fs.reporting_currency = 'USD'
                               AND fs.rate_date = (s.shipped_at AT TIME ZONE 'UTC')::date
    WHERE o.status IN ('shipped', 'partially_returned')
),
kept AS (SELECT * FROM base WHERE order_rate IS NOT NULL AND ship_rate IS NOT NULL),

-- Discounts: line total = round(discount * shipped / ordered, 2), split by shipped quantity.
disc_in AS (
    SELECT k.shipment_line_id, k.line_id, k.order_rate,
           COALESCE(d.total, 0) AS disc_total,
           k.shipped_quantity::numeric AS w,
           SUM(k.shipped_quantity) OVER (PARTITION BY k.line_id) AS shipped_total,
           k.ordered_qty
    FROM kept k
    LEFT JOIN (SELECT line_id, SUM(discount_amount) AS total FROM discounts GROUP BY line_id) d
           ON d.line_id = k.line_id
),
disc_t AS (
    SELECT *, round(disc_total * shipped_total / ordered_qty, 2) * 100 AS t_cents,
           SUM(w) OVER (PARTITION BY line_id) AS wsum
    FROM disc_in
),
disc_f AS (
    SELECT *, CASE WHEN wsum = 0 OR t_cents = 0 THEN 0 ELSE div(t_cents * w, wsum) END AS floor_c,
              CASE WHEN wsum = 0 OR t_cents = 0 THEN 0 ELSE mod(t_cents * w, wsum) END AS rem_c
    FROM disc_t
),
disc_r AS (
    SELECT *, t_cents - SUM(floor_c) OVER (PARTITION BY line_id) AS leftover,
           row_number() OVER (PARTITION BY line_id ORDER BY rem_c DESC, shipment_line_id) AS rk
    FROM disc_f
),
disc AS (
    SELECT shipment_line_id,
           ((floor_c + CASE WHEN rk <= leftover THEN 1 ELSE 0 END) / 100.0) * order_rate AS usd
    FROM disc_r
),

-- Freight: round(shipping_cost, 2) split by native gross sales, else by quantity, else unallocated.
frt_in AS (
    SELECT k.shipment_line_id, k.shipment_id, k.ship_rate,
           round(k.shipping_cost, 2) * 100 AS t_cents,
           CASE WHEN SUM(k.native_gross) OVER (PARTITION BY k.shipment_id) > 0
                THEN k.native_gross * 1000000 ELSE k.shipped_quantity::numeric END AS w
    FROM kept k
),
frt_t AS (SELECT *, SUM(w) OVER (PARTITION BY shipment_id) AS wsum FROM frt_in),
frt_f AS (
    SELECT *, CASE WHEN wsum = 0 THEN 0 ELSE div(t_cents * w, wsum) END AS floor_c,
              CASE WHEN wsum = 0 THEN 0 ELSE mod(t_cents * w, wsum) END AS rem_c
    FROM frt_t
),
frt_r AS (
    SELECT *, t_cents - SUM(floor_c) OVER (PARTITION BY shipment_id) AS leftover,
           row_number() OVER (PARTITION BY shipment_id ORDER BY rem_c DESC, shipment_line_id) AS rk
    FROM frt_f
),
frt AS (  -- allocated freight per line in USD; wsum = 0 leaves the cost unallocated
    SELECT shipment_line_id, shipment_id, wsum, t_cents, ship_rate,
           CASE WHEN wsum = 0 THEN 0
                ELSE ((floor_c + CASE WHEN rk <= leftover THEN 1 ELSE 0 END) / 100.0) * ship_rate
           END AS usd
    FROM frt_r
),

-- Returns: credit-date FX, cumulative quantity capped at shipped quantity, credit >= 0.
ret_run AS (
    SELECT r.return_id, r.shipment_line_id, r.returned_quantity, r.credit_amount, r.credit_date,
           SUM(r.returned_quantity) OVER (PARTITION BY r.shipment_line_id
                                          ORDER BY r.credit_date, r.return_id) AS cum_qty
    FROM returns r
),
ret AS (
    SELECT rr.shipment_line_id, rr.returned_quantity, rr.credit_date,
           rr.credit_amount * COALESCE(fx.rate, CASE WHEN o.currency = 'USD' THEN 1 END) AS credit_usd,
           rr.returned_quantity * k.unit_cost AS recoverable
    FROM ret_run rr
    JOIN kept k ON k.shipment_line_id = rr.shipment_line_id
    JOIN orders o ON o.order_id = k.order_id
    LEFT JOIN exchange_rates fx ON fx.currency = o.currency AND fx.reporting_currency = 'USD'
                               AND fx.rate_date = rr.credit_date
    WHERE rr.cum_qty <= k.shipped_quantity AND rr.credit_amount >= 0
),
ret_w AS (  -- credits recognised on credit_date inside the window (D-01a)
    SELECT SUM(credit_usd) AS credits, SUM(recoverable) AS recov
    FROM ret
    WHERE credit_usd IS NOT NULL
      AND (%(lo)s::timestamptz IS NULL OR (credit_date::timestamp AT TIME ZONE 'UTC') >= %(lo)s::timestamptz)
      AND (%(hi)s::timestamptz IS NULL OR (credit_date::timestamp AT TIME ZONE 'UTC') <  %(hi)s::timestamptz)
),

lines AS (  -- one row per kept line SHIPPED inside the window
    SELECT k.shipment_line_id, k.shipment_id,
           k.native_gross * k.order_rate AS gross,
           COALESCE(d.usd, 0) AS disc,
           k.shipped_quantity * k.unit_cost AS cogs_gross,
           COALESCE(f.usd, 0) AS freight
    FROM kept k
    LEFT JOIN disc d ON d.shipment_line_id = k.shipment_line_id
    LEFT JOIN frt f ON f.shipment_line_id = k.shipment_line_id
    WHERE (%(lo)s::timestamptz IS NULL OR k.shipped_at >= %(lo)s::timestamptz)
      AND (%(hi)s::timestamptz IS NULL OR k.shipped_at <  %(hi)s::timestamptz)
),
ship_in_window AS (  -- one row per shipment that has lines in the window
    SELECT DISTINCT ON (k.shipment_id) k.shipment_id, k.shipping_cost, k.ship_rate,
           (SELECT wsum FROM frt WHERE frt.shipment_id = k.shipment_id LIMIT 1) AS wsum,
           (SELECT t_cents FROM frt WHERE frt.shipment_id = k.shipment_id LIMIT 1) AS t_cents
    FROM kept k
    WHERE k.shipment_line_id IN (SELECT shipment_line_id FROM lines)
    ORDER BY k.shipment_id
),
totals AS (
    SELECT COALESCE((SELECT SUM(gross) FROM lines), 0)      AS gross,
           COALESCE((SELECT SUM(disc) FROM lines), 0)       AS disc,
           COALESCE((SELECT credits FROM ret_w), 0)         AS credits,
           COALESCE((SELECT recov FROM ret_w), 0)           AS recov,
           COALESCE((SELECT SUM(cogs_gross) FROM lines), 0) AS cogs_gross,
           COALESCE((SELECT SUM(freight) FROM lines), 0)
             + COALESCE((SELECT SUM(t_cents / 100.0 * ship_rate) FROM ship_in_window WHERE wsum = 0), 0)
             AS ship_cost,
           COALESCE((SELECT SUM(shipping_cost * ship_rate) FROM ship_in_window), 0) AS declared
)
SELECT round(gross, 2)::text                             AS gross_sales,
       round(disc, 2)::text                              AS allocated_discounts,
       round(credits, 2)::text                           AS merchandise_credits,
       round(gross - disc - credits, 2)::text            AS net_merchandise_sales,
       round(cogs_gross - recov, 2)::text                AS cogs,
       round(recov, 2)::text                             AS recoverable_return_cost,
       round(gross - disc - credits - (cogs_gross - recov), 2)::text AS gross_profit,
       round(ship_cost, 2)::text                         AS shipping_cost,
       round(gross - disc - credits - (cogs_gross - recov) - ship_cost, 2)::text AS contribution_margin,
       round(declared - ship_cost, 2)::text              AS allocation_residual
FROM totals;
