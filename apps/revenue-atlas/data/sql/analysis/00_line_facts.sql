-- 00_line_facts.sql: analysis views over the seeded snapshot after C02 + C04 (prepare_snapshot.py).
-- One row per shipment line (D-01 grain). Money is USD (D-02: order currency converted at the shipped UTC date).
-- Region is the customers version effective at the shipped UTC date, else UNASSIGNED (D-06).
-- in_population = costed (C02), not quarantined, order shipped or partially_returned, FX present (D-01).
-- Discounts: the stored discount_allocations of C04 (D-04). Freight: shipping_cost re-split by gross-sales weight over
-- the shipment's IN-POPULATION lines with largest remainder (lowest shipment_line_id breaks ties), which is what the contract
-- metrics do; the stored freight_allocations of C04 span ALL lines of a shipment incl. quarantined ones and are kept
-- as stored_freight_usd for the diagnostic 09_stored_vs_contract_freight.sql. Everything else reads these two views.
DROP VIEW IF EXISTS ra_return_facts;
DROP VIEW IF EXISTS ra_line_facts;

CREATE VIEW ra_line_facts AS
WITH base AS (
    SELECT sl.shipment_line_id, sl.shipment_id, o.order_id, ol.line_id, o.customer_id, ol.product_id, p.category_id,
           COALESCE(cv_at.segment, cv_first.segment)                       AS segment,
           COALESCE(cv_at.region_id, 'UNASSIGNED')                         AS region_id,
           s.shipped_at,
           date_trunc('month', s.shipped_at AT TIME ZONE 'UTC')::date      AS ship_month,
           o.currency AS order_currency, sl.shipped_quantity, ol.quantity AS ordered_quantity, ol.unit_price,
           sl.shipped_quantity * ol.unit_price                             AS native_gross,
           sl.shipped_quantity * ol.unit_price * rate_o.r                  AS gross_usd,
           COALESCE(da.amount, 0) * rate_o.r                               AS discount_usd,
           sl.shipped_quantity * c.unit_cost                               AS cogs_gross_usd,
           COALESCE(fa.amount, 0) * rate_s.r                               AS stored_freight_usd,
           s.shipping_cost, rate_s.r                                       AS ship_rate,
           (sl.cost_version_id IS NOT NULL AND q.id IS NULL AND o.status IN ('shipped', 'partially_returned')
            AND rate_o.r IS NOT NULL AND rate_s.r IS NOT NULL)             AS in_population,
           q.reason_code                                                   AS quarantine_reason
    FROM shipment_lines sl
    JOIN order_lines ol ON ol.line_id = sl.line_id
    JOIN orders o       ON o.order_id = ol.order_id
    JOIN products p     ON p.product_id = ol.product_id
    JOIN shipments s    ON s.shipment_id = sl.shipment_id
    LEFT JOIN cost_versions c ON c.cost_version_id = sl.cost_version_id
    LEFT JOIN quarantined_records q ON q.entity = 'shipment_lines' AND q.id = sl.shipment_line_id
    LEFT JOIN discount_allocations da ON da.shipment_line_id = sl.shipment_line_id
    LEFT JOIN freight_allocations fa  ON fa.shipment_line_id = sl.shipment_line_id
    LEFT JOIN LATERAL (SELECT region_id, segment FROM customers cu
                       WHERE cu.customer_id = o.customer_id
                         AND cu.effective_from <= (s.shipped_at AT TIME ZONE 'UTC')::date
                       ORDER BY cu.effective_from DESC LIMIT 1) cv_at ON true
    LEFT JOIN LATERAL (SELECT segment FROM customers cu WHERE cu.customer_id = o.customer_id
                       ORDER BY cu.effective_from LIMIT 1) cv_first ON true
    LEFT JOIN LATERAL (SELECT COALESCE((SELECT x.rate FROM exchange_rates x
                                        WHERE x.currency = o.currency AND x.reporting_currency = 'USD'
                                          AND x.rate_date = (s.shipped_at AT TIME ZONE 'UTC')::date),
                                       CASE WHEN o.currency = 'USD' THEN 1 END) AS r) rate_o ON true
    LEFT JOIN LATERAL (SELECT COALESCE((SELECT x.rate FROM exchange_rates x
                                        WHERE x.currency = s.currency AND x.reporting_currency = 'USD'
                                          AND x.rate_date = (s.shipped_at AT TIME ZONE 'UTC')::date),
                                       CASE WHEN s.currency = 'USD' THEN 1 END) AS r) rate_s ON true),
w1 AS (  -- weights over in-population lines only: gross cents, else shipped quantity (D-04)
    SELECT shipment_line_id, shipment_id, round(shipping_cost, 2) * 100 AS t_cents,
           CASE WHEN sum(native_gross) OVER (PARTITION BY shipment_id) > 0 THEN round(native_gross * 100)
                ELSE shipped_quantity::numeric END AS wt
    FROM base WHERE in_population),
w2 AS (SELECT *, sum(wt) OVER (PARTITION BY shipment_id) AS wsum FROM w1),
w3 AS (SELECT *, CASE WHEN wsum = 0 THEN 0 ELSE div(t_cents * wt, wsum) END AS fl,
                 CASE WHEN wsum = 0 THEN 0 ELSE mod(t_cents * wt, wsum) END AS rm FROM w2),
w4 AS (SELECT *, t_cents - sum(fl) OVER (PARTITION BY shipment_id) AS leftover,
                 row_number() OVER (PARTITION BY shipment_id ORDER BY rm DESC, shipment_line_id) AS rk FROM w3)
SELECT b.shipment_line_id, b.shipment_id, b.order_id, b.line_id, b.customer_id, b.product_id, b.category_id, b.segment,
       b.region_id, b.shipped_at, b.ship_month, b.order_currency, b.shipped_quantity, b.ordered_quantity, b.unit_price,
       b.gross_usd, b.discount_usd, b.cogs_gross_usd,
       COALESCE((w4.fl + CASE WHEN w4.rk <= w4.leftover THEN 1 ELSE 0 END) / 100.0 * b.ship_rate, 0) AS freight_usd,
       b.stored_freight_usd, b.in_population, b.quarantine_reason
FROM base b LEFT JOIN w4 ON w4.shipment_line_id = b.shipment_line_id;

-- One row per accepted return of a line in the population: credit at the credit-date FX rate (D-02), recoverable
-- cost at the line's own cost version (D-03), recognised in the month of credit_date (D-01a).
CREATE VIEW ra_return_facts AS
SELECT r.return_id, r.shipment_line_id, r.returned_quantity, r.credit_date,
       date_trunc('month', r.credit_date)::date AS credit_month,
       r.credit_amount * rate.r                 AS credit_usd,
       r.returned_quantity * c.unit_cost        AS recoverable_cost_usd,
       f.region_id, f.segment, f.category_id, f.customer_id, f.ship_month
FROM returns r
JOIN ra_line_facts f ON f.shipment_line_id = r.shipment_line_id AND f.in_population
JOIN shipment_lines sl ON sl.shipment_line_id = r.shipment_line_id
JOIN cost_versions c ON c.cost_version_id = sl.cost_version_id
LEFT JOIN LATERAL (SELECT COALESCE((SELECT x.rate FROM exchange_rates x
                                    WHERE x.currency = f.order_currency AND x.reporting_currency = 'USD'
                                      AND x.rate_date = r.credit_date),
                                   CASE WHEN f.order_currency = 'USD' THEN 1 END) AS r) rate ON true
WHERE rate.r IS NOT NULL AND r.credit_amount >= 0;
