-- 02: contribution by region with UNASSIGNED as its own row (D-06, P01-TEST-11). Region = customers version
-- effective at shipped_at; a return follows its line's region. Whole snapshot, no window. The TOTAL row equals
-- the bridge TOTAL of 01 (regions add up to the company total).
WITH ship AS (
    SELECT region_id, sum(gross_usd) gross, sum(discount_usd) disc, sum(cogs_gross_usd) cogs_gross,
           sum(freight_usd) freight, count(*) AS lines
    FROM ra_line_facts WHERE in_population GROUP BY 1),
ret AS (SELECT region_id, sum(credit_usd) credits, sum(recoverable_cost_usd) recov FROM ra_return_facts GROUP BY 1),
reg AS (
    SELECT s.region_id, s.lines, s.gross, s.disc, COALESCE(r.credits, 0) credits,
           s.cogs_gross - COALESCE(r.recov, 0) cogs, s.freight
    FROM ship s LEFT JOIN ret r USING (region_id)),
rows AS (
    SELECT region_id, 0 AS ord, lines, gross, disc, credits, cogs, freight FROM reg
    UNION ALL SELECT 'TOTAL', 1, sum(lines), sum(gross), sum(disc), sum(credits), sum(cogs), sum(freight) FROM reg)
SELECT region_id, lines AS shipment_lines, round(gross, 2) AS gross_sales, round(gross - disc - credits, 2) AS net_sales,
       round(gross - disc - credits - cogs - freight, 2) AS contribution,
       round((gross - disc - credits - cogs - freight) / NULLIF(gross - disc - credits, 0), 4) AS cm_rate
FROM rows ORDER BY ord, region_id;
