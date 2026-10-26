-- 04: cat-fixtures historical unit cost vs realised unit price by shipped month (D-03: cost at the version valid
-- on shipped_at). unit_price = gross sales / units, unit_cost = COGS before returns / units (both USD, unit-weighted);
-- cost_to_price is their ratio; other_cost_to_price is the same ratio for all other categories (a control).
-- extra_cost_usd (months from 2026-01) = fixtures COGS - fixtures gross x (cost_to_price of 2024-10..2025-12): the cost
-- above what the earlier ratio would have given. The last row sums it over 2026-01..2026-09.
WITH m AS (
    SELECT ship_month,
           sum(shipped_quantity) FILTER (WHERE category_id = 'cat-fixtures') AS units,
           sum(gross_usd)        FILTER (WHERE category_id = 'cat-fixtures') AS g,
           sum(cogs_gross_usd)   FILTER (WHERE category_id = 'cat-fixtures') AS c,
           sum(gross_usd)        FILTER (WHERE category_id <> 'cat-fixtures') AS og,
           sum(cogs_gross_usd)   FILTER (WHERE category_id <> 'cat-fixtures') AS oc
    FROM ra_line_facts WHERE in_population GROUP BY ship_month),
pre AS (SELECT sum(c) / sum(g) AS ratio FROM m WHERE ship_month < DATE '2026-01-01'),
rows AS (
    SELECT to_char(ship_month, 'YYYY-MM') AS month, 0 AS ord, units, round(g / units, 2) AS unit_price,
           round(c / units, 2) AS unit_cost, round(c / g, 4) AS cost_to_price, round(oc / og, 4) AS other_cost_to_price,
           CASE WHEN ship_month >= DATE '2026-01-01' THEN round(c - g * (SELECT ratio FROM pre), 2) END AS extra_cost_usd
    FROM m
    UNION ALL
    SELECT 'SUM 2026-01..2026-09', 1, sum(units), NULL, NULL, round(sum(c) / sum(g), 4), round(sum(oc) / sum(og), 4),
           round(sum(c - g * (SELECT ratio FROM pre)), 2)
    FROM m WHERE ship_month >= DATE '2026-01-01'
    UNION ALL
    SELECT 'SUM 2024-10..2025-12', 2, sum(units), NULL, NULL, round(sum(c) / sum(g), 4), round(sum(oc) / sum(og), 4), NULL
    FROM m WHERE ship_month < DATE '2026-01-01')
SELECT month, units AS fixtures_units, unit_price AS fixtures_unit_price, unit_cost AS fixtures_unit_cost,
       cost_to_price, other_cost_to_price, extra_cost_usd
FROM rows ORDER BY ord, month;
