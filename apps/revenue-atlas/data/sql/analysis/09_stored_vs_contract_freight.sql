-- 09: stored C04 freight vs contract freight. Population lines only. contract = shipping_cost re-split over the
-- shipment's in-population lines (what the metrics and reference_totals.sql do); stored = freight_allocations rows of
-- those lines (C04 splits over ALL lines of the shipment, including lines C02 quarantined). The gap is the freight that
-- C04 parked on quarantined sibling lines (stored_on_quarantined_siblings) in shipments that still have in-population lines.
WITH s AS (
    SELECT shipment_id,
           sum(freight_usd) FILTER (WHERE in_population)        AS contract,
           sum(stored_freight_usd) FILTER (WHERE in_population) AS stored,
           sum(stored_freight_usd) FILTER (WHERE NOT in_population) AS on_quarantined,
           count(*) FILTER (WHERE in_population) AS kept, count(*) FILTER (WHERE NOT in_population) AS dropped
    FROM ra_line_facts GROUP BY 1)
SELECT count(*) FILTER (WHERE kept > 0)                                   AS shipments_in_population,
       count(*) FILTER (WHERE kept > 0 AND dropped > 0)                   AS partially_quarantined_shipments,
       round(sum(contract) FILTER (WHERE kept > 0), 2)                    AS contract_freight,
       round(sum(stored) FILTER (WHERE kept > 0), 2)                      AS stored_c04_freight_on_kept_lines,
       round(sum(contract) FILTER (WHERE kept > 0) - sum(stored) FILTER (WHERE kept > 0), 2) AS gap,
       round(sum(on_quarantined) FILTER (WHERE kept > 0), 2)              AS stored_on_quarantined_siblings
FROM s;
