-- 08: allocation residual check (D-04, P01-MET-12). Freight: for every shipment, shipping_cost minus the sum of
-- its stored freight_allocations (native currency); every shipment must be 0.00. Discounts: for every order line, the
-- cent-rounded discount for the shipped share, round(discount x shipped/ordered, 2), minus the sum of its stored
-- discount_allocations. Any non-zero residual or missing allocation fails (the last column of the single result row).
-- Freight is checked for shipments that have at least one in-population line: C04 allocates only over lines that are not
-- quarantined (D-08, R-08), so a shipment whose every line is quarantined carries no allocation, exactly as the contract
-- metrics ignore it (their lines and their freight are outside the population).
WITH f AS (
    SELECT s.shipment_id, s.shipping_cost - COALESCE(sum(fa.amount), 0) AS residual, count(fa.*) AS alloc_rows
    FROM shipments s JOIN shipment_lines sl ON sl.shipment_id = s.shipment_id
    LEFT JOIN freight_allocations fa ON fa.shipment_line_id = sl.shipment_line_id
    WHERE EXISTS (SELECT 1 FROM ra_line_facts r WHERE r.shipment_id = s.shipment_id AND r.in_population)
    GROUP BY s.shipment_id, s.shipping_cost),
d AS (
    SELECT ol.line_id,
           round(COALESCE((SELECT sum(discount_amount) FROM discounts x WHERE x.line_id = ol.line_id), 0)
                 * sum(sl.shipped_quantity) / ol.quantity, 2) - COALESCE(sum(da.amount), 0) AS residual
    FROM order_lines ol JOIN shipment_lines sl ON sl.line_id = ol.line_id
    LEFT JOIN discount_allocations da ON da.shipment_line_id = sl.shipment_line_id
    GROUP BY ol.line_id, ol.quantity)
SELECT (SELECT count(*) FROM f)                                    AS shipments_checked,
       (SELECT count(*) FROM f WHERE residual <> 0)                AS shipments_nonzero_residual,
       (SELECT COALESCE(sum(abs(residual)), 0) FROM f)             AS freight_abs_residual,
       (SELECT count(*) FROM f WHERE alloc_rows = 0)               AS shipments_without_allocation,
       (SELECT count(*) FROM d)                                    AS order_lines_checked,
       (SELECT count(*) FROM d WHERE residual <> 0)                AS order_lines_nonzero_residual,
       (SELECT COALESCE(sum(abs(residual)), 0) FROM d)             AS discount_abs_residual,
       (SELECT count(*) FROM f WHERE residual <> 0 OR alloc_rows = 0)
         + (SELECT count(*) FROM d WHERE residual <> 0)            AS failures;
