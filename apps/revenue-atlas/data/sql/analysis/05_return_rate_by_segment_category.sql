-- 05: return rate = returned units / shipped units of the shipment cohort (D-05; cohort-by-shipment view, not the
-- credit-date windowing of D-01a), by segment x category. A cohort is mature when shipped at least 45 days before the
-- last day of data (the generator's maximum credit delay, manifest return_credit_delay_days [5,45]); mature_rate uses
-- only those lines, so recent shipments whose returns have not been credited yet do not depress the rate.
-- Output: the 12 highest mature rates, then two comparison rows: enterprise x cat-apparel's complement ("ALL OTHER") and ALL.
WITH cutoff AS (SELECT (max(shipped_at AT TIME ZONE 'UTC')::date - 45) AS d FROM ra_line_facts),
ret AS (SELECT shipment_line_id, sum(returned_quantity) AS rq FROM ra_return_facts GROUP BY 1),
x AS (
    SELECT f.segment, f.category_id, f.shipped_quantity, COALESCE(r.rq, 0) AS rq,
           (f.shipped_at AT TIME ZONE 'UTC')::date <= (SELECT d FROM cutoff) AS mature
    FROM ra_line_facts f LEFT JOIN ret r USING (shipment_line_id) WHERE f.in_population),
cell AS (
    SELECT segment, category_id,
           sum(shipped_quantity) AS su, sum(rq) AS ru,
           sum(shipped_quantity) FILTER (WHERE mature) AS mu, sum(rq) FILTER (WHERE mature) AS mr
    FROM x GROUP BY segment, category_id),
top12 AS (SELECT *, row_number() OVER (ORDER BY mr::numeric / NULLIF(mu, 0) DESC NULLS LAST, segment, category_id) AS rk FROM cell),
rows AS (
    SELECT rk AS ord, segment, category_id, su, ru, mu, mr FROM top12 WHERE rk <= 12
    UNION ALL
    SELECT 101, 'ALL OTHER', 'all other cells', sum(su), sum(ru), sum(mu), sum(mr)
    FROM cell WHERE NOT (segment = 'enterprise' AND category_id = 'cat-apparel')
    UNION ALL
    SELECT 102, 'ALL', 'all cells', sum(su), sum(ru), sum(mu), sum(mr) FROM cell)
SELECT segment, category_id, su AS shipped_units, ru AS returned_units,
       round(ru::numeric / NULLIF(su, 0), 4) AS return_rate, mu AS mature_units,
       round(mr::numeric / NULLIF(mu, 0), 4) AS mature_rate
FROM rows ORDER BY ord;
