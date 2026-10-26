-- 00: shared views for the analysis queries (P03-ART-04). Run once per database before 01..08; 09 stands alone.
-- ss_ledger: every posted movement with its running stock per (product, location) in the contract's DAY ORDER
-- (D-01: inside a date, receipts, then sales, then review and the rest; then event_at, movement_id) and, beside it,
-- the running stock in plain timestamp order, which is what the day order prevents from going negative (P03-DOMAIN-02).
-- ss_home: the one location where a product's open purchase quantity is counted (purchase order lines carry no
-- location; the same allocation as data/sql/reference_metrics.sql: first replenishment_params location).
CREATE OR REPLACE VIEW ss_ledger AS
SELECT m.movement_id, m.product_id, m.location_id, m.movement_type, m.quantity_delta, m.event_at,
       (m.event_at AT TIME ZONE 'UTC')::date AS event_date,
       sum(m.quantity_delta) OVER (PARTITION BY m.product_id, m.location_id
                                   ORDER BY (m.event_at AT TIME ZONE 'UTC')::date,
                                            CASE m.movement_type WHEN 'receipt' THEN 0 WHEN 'sale' THEN 1 ELSE 2 END,
                                            m.event_at, m.movement_id) AS running_day_order,
       sum(m.quantity_delta) OVER (PARTITION BY m.product_id, m.location_id
                                   ORDER BY m.event_at, m.movement_id) AS running_timestamp_order
  FROM inventory_movements m;

CREATE OR REPLACE VIEW ss_home AS
SELECT p.product_id,
       COALESCE((SELECT min(x.location_id) FROM replenishment_params x WHERE x.product_id = p.product_id),
                (SELECT min(x.location_id) FROM inventory_movements x WHERE x.product_id = p.product_id),
                (SELECT min(location_id) FROM locations)) AS location_id
  FROM products p;
