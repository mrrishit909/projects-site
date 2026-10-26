-- 01: margin bridge by month (D-05). Shipment-side steps by shipped_at month, credits and recoverable cost by
-- credit_date month (D-01a); the TOTAL row is the sum of the monthly rows, which must equal reference_totals.sql
-- with no window (reconciled in run_all.py). bridge: gross - discounts - credits = net; net - cogs = gross profit;
-- gross profit - freight = contribution (no shipping revenue, no other variable costs in this dataset).
-- The two SUBTOTAL rows split the series at 2026-01 (the designed cost step) and are used by the executive memo.
WITH ship AS (
    SELECT ship_month AS m, sum(gross_usd) AS gross, sum(discount_usd) AS disc,
           sum(cogs_gross_usd) AS cogs_gross, sum(freight_usd) AS freight
    FROM ra_line_facts WHERE in_population GROUP BY 1),
ret AS (
    SELECT credit_month AS m, sum(credit_usd) AS credits, sum(recoverable_cost_usd) AS recov
    FROM ra_return_facts GROUP BY 1),
monthly AS (
    SELECT COALESCE(s.m, r.m) AS m,
           COALESCE(s.gross, 0) AS gross, COALESCE(s.disc, 0) AS disc, COALESCE(r.credits, 0) AS credits,
           COALESCE(s.cogs_gross, 0) - COALESCE(r.recov, 0) AS cogs, COALESCE(s.freight, 0) AS freight
    FROM ship s FULL JOIN ret r ON r.m = s.m),
rows AS (
    SELECT to_char(m, 'YYYY-MM') AS period, 0 AS ord, gross, disc, credits, cogs, freight FROM monthly
    UNION ALL
    SELECT 'TOTAL', 1, sum(gross), sum(disc), sum(credits), sum(cogs), sum(freight) FROM monthly
    UNION ALL
    SELECT 'SUBTOTAL 2024-10..2025-12', 2, sum(gross), sum(disc), sum(credits), sum(cogs), sum(freight)
    FROM monthly WHERE m < DATE '2026-01-01'
    UNION ALL
    SELECT 'SUBTOTAL 2026-01..2026-09', 3, sum(gross), sum(disc), sum(credits), sum(cogs), sum(freight)
    FROM monthly WHERE m >= DATE '2026-01-01')
SELECT period,
       round(gross, 2)                                   AS gross_sales,
       round(disc, 2)                                    AS discounts,
       round(credits, 2)                                 AS credits,
       round(gross - disc - credits, 2)                  AS net_sales,
       round(cogs, 2)                                    AS cogs,
       round(gross - disc - credits - cogs, 2)           AS gross_profit,
       round(freight, 2)                                 AS freight,
       round(gross - disc - credits - cogs - freight, 2) AS contribution,
       round((gross - disc - credits - cogs - freight) / NULLIF(gross - disc - credits, 0), 4) AS cm_rate
FROM rows ORDER BY ord, period;
