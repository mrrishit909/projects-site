-- 06: top 10 customers by decline in contribution between two half-open six-month periods:
-- A = [2025-10-01, 2026-04-01), B = [2026-04-01, 2026-10-01). Shipment-side steps by shipped_at, credits by credit_date
-- (D-01a). decline = A - B; rank by decline descending, ties broken by customer_id ascending (deterministic).
WITH ship AS (
    SELECT customer_id,
           sum(gross_usd - discount_usd - cogs_gross_usd - freight_usd) FILTER (WHERE shipped_at >= '2025-10-01Z' AND shipped_at < '2026-04-01Z') AS a_ship,
           sum(gross_usd - discount_usd - cogs_gross_usd - freight_usd) FILTER (WHERE shipped_at >= '2026-04-01Z' AND shipped_at < '2026-10-01Z') AS b_ship
    FROM ra_line_facts WHERE in_population GROUP BY 1),
ret AS (
    SELECT customer_id,
           sum(recoverable_cost_usd - credit_usd) FILTER (WHERE credit_date >= DATE '2025-10-01' AND credit_date < DATE '2026-04-01') AS a_ret,
           sum(recoverable_cost_usd - credit_usd) FILTER (WHERE credit_date >= DATE '2026-04-01' AND credit_date < DATE '2026-10-01') AS b_ret
    FROM ra_return_facts GROUP BY 1),
c AS (
    SELECT s.customer_id, COALESCE(s.a_ship, 0) + COALESCE(r.a_ret, 0) AS a, COALESCE(s.b_ship, 0) + COALESCE(r.b_ret, 0) AS b
    FROM ship s LEFT JOIN ret r USING (customer_id)),
ranked AS (
    SELECT c.*, a - b AS decline, row_number() OVER (ORDER BY a - b DESC, customer_id) AS rnk,
           sum(a - b) OVER () AS total_decline, sum(a) OVER () AS total_a, sum(b) OVER () AS total_b
    FROM c)
SELECT rnk AS rank, r.customer_id,
       (SELECT cu.customer_name FROM customers cu WHERE cu.customer_id = r.customer_id ORDER BY effective_from DESC LIMIT 1) AS customer_name,
       (SELECT cu.region_id FROM customers cu WHERE cu.customer_id = r.customer_id ORDER BY effective_from DESC LIMIT 1) AS latest_region,
       round(a, 2) AS contribution_a, round(b, 2) AS contribution_b, round(decline, 2) AS decline,
       round(100 * decline / NULLIF(total_decline, 0), 1) AS pct_of_total_decline,
       round(total_a, 2) AS all_customers_a, round(total_b, 2) AS all_customers_b
FROM ranked r WHERE rnk <= 10 ORDER BY rnk;
