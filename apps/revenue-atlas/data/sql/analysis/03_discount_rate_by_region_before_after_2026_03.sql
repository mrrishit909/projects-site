-- 03: discount rate = allocated discounts / gross sales (D-05), ratio of sums, by region, for shipments before
-- 2026-03-01 and from 2026-03-01 (half-open on shipped_at, UTC). delta_pp is after minus before in percentage points;
-- extra_discount_usd = gross_after x (rate_after - rate_before): the discount dollars above what the before rate would have given.
WITH p AS (
    SELECT region_id,
           sum(gross_usd)    FILTER (WHERE ship_month <  DATE '2026-03-01') AS g_before,
           sum(discount_usd) FILTER (WHERE ship_month <  DATE '2026-03-01') AS d_before,
           sum(gross_usd)    FILTER (WHERE ship_month >= DATE '2026-03-01') AS g_after,
           sum(discount_usd) FILTER (WHERE ship_month >= DATE '2026-03-01') AS d_after
    FROM ra_line_facts WHERE in_population GROUP BY ROLLUP (region_id))
SELECT COALESCE(region_id, 'ALL REGIONS') AS region,
       round(d_before / NULLIF(g_before, 0), 4) AS rate_before,
       round(d_after  / NULLIF(g_after, 0), 4)  AS rate_after,
       round(100 * (d_after / NULLIF(g_after, 0) - d_before / NULLIF(g_before, 0)), 2) AS delta_pp,
       round(g_before, 2) AS gross_before, round(g_after, 2) AS gross_after,
       round(g_after * (d_after / NULLIF(g_after, 0) - d_before / NULLIF(g_before, 0)), 2) AS extra_discount_usd
FROM p ORDER BY region_id NULLS LAST;
