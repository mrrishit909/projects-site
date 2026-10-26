-- 07: why records are out of the population. quarantined_records are written by C02 (D-03 cost, D-02 FX),
-- rejected_records by C01 (D-06 malformed currency). gross_usd_at_stake is only computed for quarantined shipment
-- lines whose FX rate exists (an FX_RATE_MISSING line has no USD value by definition, so it shows NULL).
SELECT 'quarantined' AS kind, q.entity, q.reason_code, count(*) AS records,
       count(DISTINCT sl.shipment_id) AS shipments,
       round(sum(f.gross_usd), 2) AS gross_usd_at_stake
FROM quarantined_records q
LEFT JOIN shipment_lines sl ON q.entity = 'shipment_lines' AND sl.shipment_line_id = q.id
LEFT JOIN ra_line_facts f ON f.shipment_line_id = sl.shipment_line_id
GROUP BY q.entity, q.reason_code
UNION ALL
SELECT 'rejected', entity, reason_code, count(*), NULL, NULL FROM rejected_records GROUP BY entity, reason_code
ORDER BY kind DESC, entity, reason_code;
