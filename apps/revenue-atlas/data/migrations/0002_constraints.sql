-- 0002_constraints.sql: referential integrity, value checks, append-only triggers, indexes.
-- Idempotent: constraints are added only when absent (pg_constraint lookup).
-- Deliberately NO exclusion constraint on cost_versions: overlapping ranges must be
-- storable so command C02 can quarantine them (P01-TEST-03, D-03).

DO $$
DECLARE
    c RECORD;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('order_lines_order_fk',      'order_lines',    'FOREIGN KEY (order_id) REFERENCES orders (order_id)'),
        ('order_lines_product_fk',    'order_lines',    'FOREIGN KEY (product_id) REFERENCES products (product_id)'),
        ('discounts_line_fk',         'discounts',      'FOREIGN KEY (line_id) REFERENCES order_lines (line_id)'),
        ('shipments_order_fk',        'shipments',      'FOREIGN KEY (order_id) REFERENCES orders (order_id)'),
        ('shipment_lines_shipment_fk','shipment_lines', 'FOREIGN KEY (shipment_id) REFERENCES shipments (shipment_id)'),
        ('shipment_lines_line_fk',    'shipment_lines', 'FOREIGN KEY (line_id) REFERENCES order_lines (line_id)'),
        ('shipment_lines_cost_fk',    'shipment_lines', 'FOREIGN KEY (cost_version_id) REFERENCES cost_versions (cost_version_id)'),
        ('returns_shipment_line_fk',  'returns',        'FOREIGN KEY (shipment_line_id) REFERENCES shipment_lines (shipment_line_id)'),
        ('cost_versions_product_fk',  'cost_versions',  'FOREIGN KEY (product_id) REFERENCES products (product_id)'),
        ('orders_currency_ck',        'orders',         $c$CHECK (currency ~ '^[A-Z]{3}$')$c$),
        ('shipments_currency_ck',     'shipments',      $c$CHECK (currency ~ '^[A-Z]{3}$')$c$),
        ('exchange_rates_currency_ck','exchange_rates', $c$CHECK (currency ~ '^[A-Z]{3}$' AND reporting_currency ~ '^[A-Z]{3}$')$c$),
        ('exchange_rates_rate_ck',    'exchange_rates', 'CHECK (rate > 0)'),
        ('order_lines_quantity_ck',   'order_lines',    'CHECK (quantity >= 1)'),
        ('order_lines_price_ck',      'order_lines',    'CHECK (unit_price >= 0)'),
        ('discounts_amount_ck',       'discounts',      'CHECK (discount_amount >= 0)'),
        ('shipments_cost_ck',         'shipments',      'CHECK (shipping_cost >= 0)'),
        ('shipment_lines_qty_ck',     'shipment_lines', 'CHECK (shipped_quantity >= 0)'),
        ('shipment_lines_version_ck', 'shipment_lines', 'CHECK (version >= 1)'),
        ('returns_qty_ck',            'returns',        'CHECK (returned_quantity >= 1)'),
        ('returns_credit_sign_ck',    'returns',        'CHECK (credit_amount >= 0)'),   -- CREDIT_SIGN_REVERSED (D-06)
        ('cost_versions_cost_ck',     'cost_versions',  'CHECK (unit_cost >= 0)'),
        ('cost_versions_range_ck',    'cost_versions',  'CHECK (valid_to IS NULL OR valid_to > valid_from)'),
        ('freight_allocations_amount_ck','freight_allocations','CHECK (amount >= 0)'),
        ('raw_batches_status_ck',     'raw_batches',    $c$CHECK (status IN ('accepted', 'partial'))$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

-- Append-only tables: a return is corrected by a new row, an audit event is never edited.
CREATE OR REPLACE FUNCTION ra_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS returns_append_only ON returns;
CREATE TRIGGER returns_append_only BEFORE UPDATE OR DELETE ON returns
    FOR EACH ROW EXECUTE FUNCTION ra_forbid_mutation();

DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION ra_forbid_mutation();

CREATE INDEX IF NOT EXISTS shipment_lines_shipment_idx ON shipment_lines (shipment_id);
CREATE INDEX IF NOT EXISTS shipment_lines_line_idx ON shipment_lines (line_id);
CREATE INDEX IF NOT EXISTS returns_shipment_line_idx ON returns (shipment_line_id);
CREATE INDEX IF NOT EXISTS cost_versions_product_idx ON cost_versions (product_id, valid_from);
CREATE INDEX IF NOT EXISTS shipments_shipped_at_idx ON shipments (shipped_at);
CREATE INDEX IF NOT EXISTS exchange_rates_lookup_idx ON exchange_rates (currency, rate_date);
