-- D-09 (R5-20): a byte-twin whose extracted fields differ from the canonical's is held for review (status needs_review,
-- reason BYTES_FIELDS_CONFLICT on its lineage row) instead of being merged. Idempotent: the constraint is replaced.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'invoices_status_ck') THEN
        ALTER TABLE invoices DROP CONSTRAINT invoices_status_ck;
    END IF;
    ALTER TABLE invoices ADD CONSTRAINT invoices_status_ck CHECK (status IN
        ('received', 'valid', 'invalid', 'matched', 'exception', 'approved', 'rejected', 'exported', 'adjusted', 'merged', 'needs_review'));
END
$$;
