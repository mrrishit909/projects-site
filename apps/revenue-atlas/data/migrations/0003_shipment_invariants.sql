-- 0003_shipment_invariants.sql: review findings R-01 and R-06 (docs/contracts.md D-08).
-- Per-line invariants that cannot be a plain CHECK because they read other rows, so they are triggers:
--   shipped_le_ordered : the shipped quantity of all shipment lines of an order line never exceeds order_lines.quantity;
--   order_match        : a shipment line's order line belongs to the shipment's order.
-- The domain (validate_batch) rejects both at C01 first; the triggers are the database-side guard for rows that arrive in a
-- later batch or from any other writer. Idempotent: functions are replaced, triggers dropped and recreated.

CREATE OR REPLACE FUNCTION ra_check_shipment_line() RETURNS trigger AS $$
DECLARE
    ordered INTEGER;
    line_order TEXT;
    ship_order TEXT;
    shipped BIGINT;
BEGIN
    -- FOR NO KEY UPDATE serialises concurrent shipments of one order line without blocking foreign-key checks.
    SELECT quantity, order_id INTO ordered, line_order FROM order_lines WHERE line_id = NEW.line_id FOR NO KEY UPDATE;
    IF ordered IS NULL THEN
        RETURN NEW;                                   -- the foreign key reports the unknown line
    END IF;
    SELECT order_id INTO ship_order FROM shipments WHERE shipment_id = NEW.shipment_id;
    IF ship_order IS NOT NULL AND ship_order <> line_order THEN
        RAISE EXCEPTION 'shipment line % belongs to order % but its shipment to order %',
            NEW.shipment_line_id, line_order, ship_order
            USING ERRCODE = 'check_violation', CONSTRAINT = 'shipment_lines_order_match';
    END IF;
    SELECT COALESCE(sum(shipped_quantity), 0) INTO shipped FROM shipment_lines
        WHERE line_id = NEW.line_id AND shipment_line_id <> NEW.shipment_line_id;
    IF shipped + NEW.shipped_quantity > ordered THEN
        RAISE EXCEPTION 'order line % ordered % but % would be shipped', NEW.line_id, ordered, shipped + NEW.shipped_quantity
            USING ERRCODE = 'check_violation', CONSTRAINT = 'shipment_lines_shipped_le_ordered';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS shipment_lines_invariants ON shipment_lines;
CREATE TRIGGER shipment_lines_invariants BEFORE INSERT OR UPDATE OF shipped_quantity, line_id, shipment_id ON shipment_lines
    FOR EACH ROW EXECUTE FUNCTION ra_check_shipment_line();

-- Lowering an order line's quantity below what already shipped is refused for the same reason.
CREATE OR REPLACE FUNCTION ra_check_order_line_quantity() RETURNS trigger AS $$
DECLARE
    shipped BIGINT;
BEGIN
    SELECT COALESCE(sum(shipped_quantity), 0) INTO shipped FROM shipment_lines WHERE line_id = NEW.line_id;
    IF shipped > NEW.quantity THEN
        RAISE EXCEPTION 'order line % already shipped % of the new quantity %', NEW.line_id, shipped, NEW.quantity
            USING ERRCODE = 'check_violation', CONSTRAINT = 'shipment_lines_shipped_le_ordered';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS order_lines_quantity_floor ON order_lines;
CREATE TRIGGER order_lines_quantity_floor BEFORE UPDATE OF quantity ON order_lines
    FOR EACH ROW EXECUTE FUNCTION ra_check_order_line_quantity();
