-- discount_reconciliation.sql (review finding R-02, docs/contracts.md D-04 and D-08).
-- For every order line whose shipment lines ALL hold a discount_allocations row (C04 has run for each shipment),
-- the stored rows must add up to the contract split: round(sum(discount_amount) x sum(shipped) / ordered, 2).
-- For a fully shipped line that is the discount total. The query returns the lines that DRIFT; no rows means the
-- persisted allocations equal the contract. C04 upserts the split of the whole order line, so a line shipped across
-- several C04 calls reconciles after the last call (before the fix the first call's rows were never updated).
SELECT ol.line_id,
       ol.quantity                                                        AS ordered_quantity,
       sum(sl.shipped_quantity)                                           AS shipped_quantity,
       COALESCE(d.total, 0)                                               AS discount_total,
       round(COALESCE(d.total, 0) * sum(sl.shipped_quantity) / ol.quantity, 2) AS expected_allocated,
       sum(da.amount)                                                     AS stored_allocated,
       sum(da.amount) - round(COALESCE(d.total, 0) * sum(sl.shipped_quantity) / ol.quantity, 2) AS drift
FROM order_lines ol
JOIN shipment_lines sl ON sl.line_id = ol.line_id
LEFT JOIN discount_allocations da ON da.shipment_line_id = sl.shipment_line_id
LEFT JOIN (SELECT line_id, sum(discount_amount) AS total FROM discounts GROUP BY line_id) d ON d.line_id = ol.line_id
GROUP BY ol.line_id, ol.quantity, d.total
HAVING count(da.shipment_line_id) = count(sl.shipment_line_id)
   AND sum(da.amount) <> round(COALESCE(d.total, 0) * sum(sl.shipped_quantity) / ol.quantity, 2)
ORDER BY ol.line_id;
