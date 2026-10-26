-- InvoiceBridge constraints and triggers (idempotent).
--
-- * Money and quantity rules the domain enforces are repeated here so no writer can bypass them.
-- * The source of an import is IMMUTABLE (P05-DOMAIN-06): an invoice's extracted fields and lines never change; only the
--   workflow columns (status, validity, merge, version) move. import_lineage, audit_events, exception_assignments,
--   approvals, export_rows and credit_notes are append-only. A receipt may only be REVERSED (reversed, reversed_at).
-- * An invoice exports once (UNIQUE (invoice_id) on export_rows) and a credit applies once (credit_id is the key).

DO $$
DECLARE c record;
BEGIN
    FOR c IN SELECT * FROM (VALUES
        ('vendors_currency_ck',   'vendors',         $c$CHECK (currency ~ '^[A-Z]{3}$')$c$),
        ('po_currency_ck',        'purchase_orders', $c$CHECK (currency ~ '^[A-Z]{3}$')$c$),
        ('po_lines_qty_ck',       'po_lines',        'CHECK (quantity > 0 AND unit_price >= 0)'),
        ('receipts_qty_ck',       'receipts',        'CHECK (received_quantity > 0)'),
        ('policies_ck',           'approval_policies', 'CHECK (amount_limit >= 0 AND version_number >= 1)'),
        ('tolerances_ck',         'tolerances',      'CHECK (id = 1 AND price_per_unit >= 0 AND rounding_per_line >= 0 AND rounding_per_invoice >= 0)'),
        ('invoices_currency_ck',  'invoices',        $c$CHECK (currency ~ '^[A-Z]{3}$')$c$),
        ('invoices_sha_ck',       'invoices',        $c$CHECK (source_sha256 ~ '^[0-9a-f]{64}$')$c$),
        ('invoices_rate_ck',      'invoices',        'CHECK (tax_rate >= 0 AND tax_rate <= 1 AND freight >= 0 AND invoice_discount >= 0)'),
        ('invoices_status_ck',    'invoices',        $c$CHECK (status IN ('received', 'valid', 'invalid', 'matched', 'exception', 'approved', 'rejected', 'exported', 'adjusted', 'merged'))$c$),
        ('invoices_merge_ck',     'invoices',        $c$CHECK ((status = 'merged') = (merged_into IS NOT NULL))$c$),
        ('invoice_lines_qty_ck',  'invoice_lines',   'CHECK (quantity > 0 AND unit_price >= 0)'),
        ('lineage_status_ck',     'import_lineage',  $c$CHECK (import_status IN ('accepted', 'rejected', 'merged'))$c$),
        ('lineage_sha_ck',        'import_lineage',  $c$CHECK (source_sha256 ~ '^[0-9a-f]{64}$')$c$),
        ('match_status_ck',       'match_results',   $c$CHECK (status IN ('matched', 'exception'))$c$),
        ('match_reason_ck',       'match_results',   $c$CHECK ((status = 'matched') = (reason_code IS NULL) AND (reason_code IS NULL OR reason_code IN ('QUANTITY_BLOCKED', 'PRICE_VARIANCE', 'NO_PO_LINE', 'CURRENCY_MISMATCH')))$c$),
        ('exceptions_type_ck',    'exceptions',      $c$CHECK (exception_type IN ('QUANTITY_BLOCKED', 'PRICE_VARIANCE', 'NO_PO_LINE', 'ROUNDING_EXCEPTION', 'CURRENCY_MISMATCH'))$c$),
        ('exceptions_status_ck',  'exceptions',      $c$CHECK (status IN ('open', 'assigned', 'resolved') AND ((status = 'open') = (owner_id IS NULL) OR status = 'resolved'))$c$),
        ('approvals_decision_ck', 'approvals',       $c$CHECK (decision IN ('approve', 'reject') AND (decision = 'approve' OR (reason IS NOT NULL AND length(btrim(reason)) > 0)))$c$),
        ('credits_amount_ck',     'credit_notes',    'CHECK (credit_amount > 0)'),
        ('export_rows_hash_ck',   'export_rows',     $c$CHECK (content_hash ~ '^[0-9a-f]{64}$')$c$),
        ('export_rows_inv_uq',    'export_rows',     'UNIQUE (invoice_id)'),
        ('export_rows_batch_uq',  'export_rows',     'UNIQUE (invoice_id, batch_id)'),
        ('export_requests_ck',    'export_requests', $c$CHECK (outcome IN ('created', 'returned_prior'))$c$)
    ) AS t (name, tbl, def)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.name) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', c.tbl, c.name, c.def);
        END IF;
    END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION ib_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END
$$ LANGUAGE plpgsql;

-- The extracted source never changes: only the workflow columns of an invoice may be updated.
CREATE OR REPLACE FUNCTION ib_invoice_source_fixed() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'invoices are never deleted' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.invoice_id, NEW.vendor_id, NEW.invoice_number, NEW.invoice_number_norm, NEW.invoice_date, NEW.currency,
        NEW.tax_rate, NEW.freight, NEW.invoice_discount, NEW.declared_total, NEW.subtotal, NEW.tax, NEW.total,
        NEW.created_by, NEW.source_sha256, NEW.source_filename, NEW.idempotency_key, NEW.imported_at)
       IS DISTINCT FROM
       (OLD.invoice_id, OLD.vendor_id, OLD.invoice_number, OLD.invoice_number_norm, OLD.invoice_date, OLD.currency,
        OLD.tax_rate, OLD.freight, OLD.invoice_discount, OLD.declared_total, OLD.subtotal, OLD.tax, OLD.total,
        OLD.created_by, OLD.source_sha256, OLD.source_filename, OLD.idempotency_key, OLD.imported_at) THEN
        RAISE EXCEPTION 'the extracted source of invoice % is immutable (corrections are versioned rows)', OLD.invoice_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- A receipt can only be reversed, never edited.
CREATE OR REPLACE FUNCTION ib_receipt_reverse_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'receipts are never deleted; reverse them' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.receipt_id, NEW.po_line_id, NEW.received_quantity, NEW.received_at)
       IS DISTINCT FROM (OLD.receipt_id, OLD.po_line_id, OLD.received_quantity, OLD.received_at) OR (OLD.reversed AND NOT NEW.reversed) THEN
        RAISE EXCEPTION 'a receipt may only be reversed' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['import_lineage', 'audit_events', 'exception_assignments', 'approvals', 'export_rows',
                             'credit_notes', 'invoice_lines']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_immutable') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION ib_forbid_mutation()',
                           t || '_immutable', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION ib_forbid_mutation()',
                           t || '_no_truncate', t);
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'invoices_source_fixed') THEN
        CREATE TRIGGER invoices_source_fixed BEFORE UPDATE OR DELETE ON invoices
            FOR EACH ROW EXECUTE FUNCTION ib_invoice_source_fixed();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'receipts_reverse_only') THEN
        CREATE TRIGGER receipts_reverse_only BEFORE UPDATE OR DELETE ON receipts
            FOR EACH ROW EXECUTE FUNCTION ib_receipt_reverse_only();
    END IF;
END
$$;
