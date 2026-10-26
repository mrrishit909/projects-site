-- SupplyScope constraints, triggers and indexes (idempotent).

DO $$
DECLARE c record;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('suppliers_lead_ck',        'suppliers',           'CHECK (quoted_lead_days >= 0)'),
        ('products_cost_ck',         'products',            'CHECK (unit_cost >= 0)'),
        ('products_pack_ck',         'products',            'CHECK (pack_size >= 1)'),
        ('products_moq_ck',          'products',            'CHECK (minimum_order_quantity >= 0)'),
        ('locations_capacity_ck',    'locations',           'CHECK (storage_capacity >= 0)'),
        ('closures_range_ck',        'calendar_closures',   'CHECK (closed_to >= closed_from)'),
        ('cost_versions_cost_ck',    'cost_versions',       'CHECK (unit_cost >= 0)'),
        ('scenarios_target_ck',      'policy_scenarios',    'CHECK (service_target > 0 AND service_target < 1)'),
        ('scenarios_policy_ck',      'policy_scenarios',    $c$CHECK (unmet_policy IN ('lost_sale', 'backlog'))$c$),
        ('scenarios_counts_ck',      'policy_scenarios',    'CHECK (warmup_days >= 0 AND replications >= 1)'),
        ('po_status_ck',             'purchase_orders',     $c$CHECK (status IN ('confirmed', 'cancelled', 'closed'))$c$),
        ('po_lines_qty_ck',          'purchase_order_lines','CHECK (ordered_quantity > 0 AND unit_cost >= 0)'),
        ('receipts_qty_ck',          'receipts',            'CHECK (received_quantity > 0)'),
        ('movements_type_ck',        'inventory_movements', $c$CHECK (movement_type IN ('receipt', 'sale', 'adjustment', 'review', 'return'))$c$),
        ('movements_delta_ck',       'inventory_movements', 'CHECK (quantity_delta <> 0)'),
        ('movements_sign_ck',        'inventory_movements', $c$CHECK (NOT (movement_type IN ('receipt', 'return') AND quantity_delta < 0) AND NOT (movement_type = 'sale' AND quantity_delta > 0))$c$),
        ('sales_qty_ck',             'sales',               'CHECK (quantity > 0)'),
        ('promotions_range_ck',      'promotions',          'CHECK (ends_at >= starts_at AND planned_uplift >= 0)'),
        ('latent_qty_ck',            'latent_demand',       'CHECK (latent_quantity >= 0)'),
        ('forecast_runs_ck',         'forecast_runs',       'CHECK (horizon_days >= 1)'),
        ('forecast_points_ck',       'forecast_points',     'CHECK (forecast_value >= 0)'),
        ('backorders_qty_ck',        'backorders',          'CHECK (quantity > 0 AND (closed_at IS NULL OR closed_at >= opened_at))'),
        ('lost_sales_qty_ck',        'lost_sales',          'CHECK (quantity > 0)'),
        ('reservations_qty_ck',      'reservations',        'CHECK (quantity > 0 AND (released_at IS NULL OR released_at >= reserved_at))'),
        ('params_ck',                'replenishment_params','CHECK (reorder_point >= 0 AND target_position >= 0)'),
        ('draft_orders_status_ck',   'draft_orders',        $c$CHECK (status = 'draft')$c$),
        ('draft_orders_qty_ck',      'draft_orders',        'CHECK (order_quantity >= 0 AND pack_size >= 1 AND order_quantity % pack_size = 0)'),
        ('draft_orders_source_ck',   'draft_orders',        $c$CHECK (parameter_source IN ('params', 'forecast'))$c$),
        ('raw_batches_status_ck',    'raw_batches',         $c$CHECK (status IN ('accepted', 'partial', 'rejected'))$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

-- Immutable and append-only tables: a posted movement and an audit event are never edited or deleted (P03-TEST-04).
CREATE OR REPLACE FUNCTION ss_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS inventory_movements_immutable ON inventory_movements;
CREATE TRIGGER inventory_movements_immutable BEFORE UPDATE OR DELETE ON inventory_movements
    FOR EACH ROW EXECUTE FUNCTION ss_forbid_mutation();
DROP TRIGGER IF EXISTS inventory_movements_no_truncate ON inventory_movements;
CREATE TRIGGER inventory_movements_no_truncate BEFORE TRUNCATE ON inventory_movements
    FOR EACH STATEMENT EXECUTE FUNCTION ss_forbid_mutation();
DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION ss_forbid_mutation();

-- D-04: a receipt is not dated before its order (P03-TEST-11), cannot over-receive its line, and a partial receipt
-- leaves the line open. The line row is locked so two concurrent receipts cannot both fit.
CREATE OR REPLACE FUNCTION ss_receipt_rules() RETURNS trigger AS $$
DECLARE ordered TIMESTAMPTZ; qty INT; got INT;
BEGIN
    SELECT o.ordered_at, l.ordered_quantity INTO ordered, qty
      FROM purchase_order_lines l JOIN purchase_orders o ON o.purchase_order_id = l.purchase_order_id
     WHERE l.po_line_id = NEW.po_line_id FOR UPDATE OF l;
    IF NEW.received_at < ordered THEN
        RAISE EXCEPTION 'RECEIPT_BEFORE_ORDER: receipt % precedes the order', NEW.receipt_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    SELECT COALESCE(sum(received_quantity), 0) INTO got FROM receipts
     WHERE po_line_id = NEW.po_line_id AND receipt_id <> NEW.receipt_id;
    IF got + NEW.received_quantity > qty THEN
        RAISE EXCEPTION 'RECEIPT_EXCEEDS_ORDERED: line % would be over-received', NEW.po_line_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS receipts_rules ON receipts;
CREATE TRIGGER receipts_rules BEFORE INSERT OR UPDATE ON receipts
    FOR EACH ROW EXECUTE FUNCTION ss_receipt_rules();

-- A purchase order cannot move after its receipts (the order date is what receipts are checked against).
CREATE OR REPLACE FUNCTION ss_order_date_fixed() RETURNS trigger AS $$
BEGIN
    IF NEW.ordered_at IS DISTINCT FROM OLD.ordered_at AND EXISTS (
        SELECT 1 FROM receipts r JOIN purchase_order_lines l ON l.po_line_id = r.po_line_id
         WHERE l.purchase_order_id = OLD.purchase_order_id) THEN
        RAISE EXCEPTION 'order % has receipts: its date cannot change', OLD.purchase_order_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS purchase_orders_date_fixed ON purchase_orders;
CREATE TRIGGER purchase_orders_date_fixed BEFORE UPDATE ON purchase_orders
    FOR EACH ROW EXECUTE FUNCTION ss_order_date_fixed();

-- D-04 / P03-TEST-08: one unmet-demand event is a backorder OR a lost sale, never both (keyed by demand_ref).
CREATE OR REPLACE FUNCTION ss_unmet_xor() RETURNS trigger AS $$
BEGIN
    IF NEW.demand_ref IS NULL THEN RETURN NEW; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('unmet:' || NEW.demand_ref, 0));
    IF TG_TABLE_NAME = 'backorders' AND EXISTS (SELECT 1 FROM lost_sales WHERE demand_ref = NEW.demand_ref)
       OR TG_TABLE_NAME = 'lost_sales' AND EXISTS (SELECT 1 FROM backorders WHERE demand_ref = NEW.demand_ref) THEN
        RAISE EXCEPTION 'UNMET_POLICY_CONFLICT: demand % is already recorded as the other kind', NEW.demand_ref
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS backorders_xor ON backorders;
CREATE TRIGGER backorders_xor BEFORE INSERT ON backorders FOR EACH ROW EXECUTE FUNCTION ss_unmet_xor();
DROP TRIGGER IF EXISTS lost_sales_xor ON lost_sales;
CREATE TRIGGER lost_sales_xor BEFORE INSERT ON lost_sales FOR EACH ROW EXECUTE FUNCTION ss_unmet_xor();

CREATE INDEX IF NOT EXISTS movements_pair_at_idx ON inventory_movements (product_id, location_id, event_at);
CREATE INDEX IF NOT EXISTS sales_pair_at_idx ON sales (product_id, location_id, sold_at);
CREATE INDEX IF NOT EXISTS receipts_line_idx ON receipts (po_line_id);
CREATE INDEX IF NOT EXISTS po_lines_order_idx ON purchase_order_lines (purchase_order_id);
CREATE INDEX IF NOT EXISTS draft_orders_as_of_idx ON draft_orders (as_of, product_id, location_id);
