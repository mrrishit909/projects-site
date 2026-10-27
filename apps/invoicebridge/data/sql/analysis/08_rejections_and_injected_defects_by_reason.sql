-- 08_rejections_and_injected_defects_by_reason.sql: what was rejected, merged or refused, and which of the twelve injected defects the facts reveal (P05-ART-04, D-05, D-06, P05-TEST-01..12).
-- Question: which invoices were refused and why, and are the planted defects found rather than hidden?
-- Needs 00_book.sql. Three kinds of "no" are kept apart: INGEST REJECTIONS (a row the contract refuses, kept in `rejected_records` with its
-- reason: none on this snapshot, every generated row is well-formed), MERGES (a duplicate that is not paid twice, 03) and REJECT DECISIONS
-- (a reviewer rejects an invoice with a reason, C08). The generator rejects only invoices that were exceptions in EVERY run and never
-- rejects an injected exception invoice (D-07): the reject-decision mix is outcome-selected, not a finding.
-- The signatures of the injected defects are written from the facts alone (they do not read data/injection-manifest.json); the run_all.py
-- reconciliation then compares them with the manifest. Five of the twelve injections are REPLAY-ONLY: they are attempts through the API
-- (self-approval, racing approvals, a credit applied twice, a correction overwriting the original, a paid flag) that the commands refuse
-- and that leave no row in a snapshot, so their signatures find 0 here by design and the evidence is tests/test_adversarial.py and the
-- replay events (data/injection-events.json).

-- @@ ingest_outcomes
SELECT 'import lineage: accepted' AS outcome, count(*) AS n FROM import_lineage WHERE import_status = 'accepted'
UNION ALL SELECT 'import lineage: merged (DUPLICATE_IDENTITY)', count(*) FROM import_lineage WHERE import_status = 'merged' AND reason_code = 'DUPLICATE_IDENTITY'
UNION ALL SELECT 'import lineage: merged (DUPLICATE_SOURCE_BYTES)', count(*) FROM import_lineage WHERE import_status = 'merged' AND reason_code = 'DUPLICATE_SOURCE_BYTES'
UNION ALL SELECT 'rejected_records kept (ingest rejections)', count(*) FROM rejected_records
UNION ALL SELECT 'reject decisions (C08) recorded', count(*) FROM approvals WHERE decision = 'reject'
UNION ALL SELECT 'reject decisions that are valid', count(*) FROM ib_facts WHERE kind = 'reject' AND c = '2026-10-01T02:00:00Z' AND code IS NULL
UNION ALL SELECT 'reject decisions refused (invalid)', count(*) FROM ib_facts WHERE kind = 'reject' AND c = '2026-10-01T02:00:00Z' AND code IS NOT NULL;

-- @@ reject_decisions_by_reason
-- The reason a reviewer wrote, the exception type the invoice carries in the stored history, and whether the invoice is still in the book
-- (a valid rejection takes it out). Rejected invoices keep their exception rows, resolved when the invoice was rejected.
SELECT reviewer_reason, exception_type_in_history, count(*) AS reject_decisions, count(*) FILTER (WHERE is_valid) AS valid,
       count(*) FILTER (WHERE in_book) AS still_in_the_book, count(*) FILTER (WHERE resolved_exc) AS with_a_resolved_exception
FROM (
    SELECT a.reason AS reviewer_reason, coalesce((SELECT min(e.exception_type) FROM exceptions e WHERE e.invoice_id = a.invoice_id), 'none') AS exception_type_in_history,
           EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'reject' AND f.c = '2026-10-01T02:00:00Z' AND f.ref = a.approval_id AND f.code IS NULL) AS is_valid,
           EXISTS (SELECT 1 FROM ib_run r WHERE r.c = '2026-10-01T02:00:00Z' AND r.invoice_id = a.invoice_id) AS in_book,
           EXISTS (SELECT 1 FROM exceptions e WHERE e.invoice_id = a.invoice_id AND e.resolved_at IS NOT NULL) AS resolved_exc
    FROM approvals a WHERE a.decision = 'reject'
) z GROUP BY reviewer_reason, exception_type_in_history ORDER BY reviewer_reason COLLATE "C", exception_type_in_history COLLATE "C";

-- @@ injected_defect_signatures
-- One row per injected defect (INJ-01 .. INJ-12): what the facts show and whether the injection can leave a row in a snapshot at all.
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
req AS (SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat FROM export_requests r)
SELECT inj, signature, found, replay_only FROM (
    SELECT 1 AS ord, 'INJ-01' AS inj, 'groups of invoices that share source bytes under different ids' AS signature,
           (SELECT count(*) FROM (SELECT source_sha256 FROM invoices GROUP BY source_sha256 HAVING count(*) > 1) z) AS found, FALSE AS replay_only
    UNION ALL SELECT 2, 'INJ-02', 'normalised invoice numbers shared by invoices of different vendors',
           (SELECT count(*) FROM (SELECT regexp_replace(upper(invoice_number), '[^A-Z0-9]', '', 'g') AS n FROM invoices GROUP BY 1 HAVING count(DISTINCT vendor_id) > 1) z), FALSE
    UNION ALL SELECT 3, 'INJ-03', 'invoices with an open QUANTITY_BLOCKED outside vendors ven-020 .. ven-029 (a superset: the receipt is short, nothing follows)',
           (SELECT count(*) FROM ib_run r WHERE r.c = (SELECT t FROM asof) AND 'QUANTITY_BLOCKED' = ANY (r.reasons) AND r.vendor_id NOT BETWEEN 'ven-020' AND 'ven-029'), FALSE
    UNION ALL SELECT 4, 'INJ-04', 'invoices outside ven-020 .. ven-029 with an open QUANTITY_BLOCKED line whose own quantity is within what was received (blocked by earlier consumption; a superset)',
           (SELECT count(DISTINCT r.invoice_id) FROM ib_run r CROSS JOIN LATERAL jsonb_array_elements(r.line_res) e
             WHERE r.c = (SELECT t FROM asof) AND e ->> 'reason' = 'QUANTITY_BLOCKED' AND r.vendor_id NOT BETWEEN 'ven-020' AND 'ven-029'
               AND (e ->> 'q')::numeric <= coalesce((SELECT sum(rc.received_quantity) FROM receipts rc WHERE rc.po_line_id = e ->> 'po_line_id' AND NOT rc.reversed AND rc.received_at <= r.c), 0)), FALSE
    UNION ALL SELECT 5, 'INJ-05', 'invoices whose declared total differs from the computed total by more than 0.02',
           (SELECT count(*) FROM ib_run r JOIN invoices i USING (invoice_id) WHERE r.c = (SELECT t FROM asof) AND abs(i.declared_total - r.total) > 0.02), FALSE
    UNION ALL SELECT 6, 'INJ-06', 'approvals by the invoice creator (self-approval attempt)',
           (SELECT count(*) FROM approvals a JOIN invoices i USING (invoice_id) WHERE a.decision = 'approve' AND a.actor_id = i.created_by), TRUE
    UNION ALL SELECT 7, 'INJ-07', 'invoices with more than one approve decision (racing approvals)',
           (SELECT count(*) FROM (SELECT invoice_id FROM approvals WHERE decision = 'approve' GROUP BY invoice_id HAVING count(*) > 1) z), TRUE
    UNION ALL SELECT 8, 'INJ-08', 'credit notes beyond the first for one credit id (a credit applied twice)',
           (SELECT count(*) FROM (SELECT credit_id FROM credit_notes GROUP BY credit_id HAVING count(*) > 1) z), TRUE
    UNION ALL SELECT 9, 'INJ-09', 'invoices with a line in a currency other than its purchase order''s',
           (SELECT count(DISTINCT i.invoice_id) FROM invoices i JOIN invoice_lines l USING (invoice_id) JOIN po_lines pl ON pl.po_line_id = l.po_line_id
              JOIN purchase_orders p ON p.po_id = pl.po_id WHERE p.currency <> i.currency), FALSE
    UNION ALL SELECT 10, 'INJ-10', 'invoice ids with more than one stored version (a correction overwriting the original)',
           (SELECT count(*) FROM (SELECT invoice_id FROM import_lineage GROUP BY invoice_id HAVING count(*) > 1) z), TRUE
    UNION ALL SELECT 11, 'INJ-11', 'export requests repeated after a timeout (same batch id and key, later exported_at)',
           (SELECT count(*) FROM req WHERE repeat), FALSE
    UNION ALL SELECT 12, 'INJ-12', 'export batches carrying a paid flag (the schema has no such column)',
           (SELECT count(*) FROM information_schema.columns WHERE table_name IN ('export_batches', 'export_rows', 'export_requests', 'invoices') AND column_name IN ('paid', 'is_paid', 'paid_at')), TRUE
) z ORDER BY ord;

-- @@ open_quantity_blocked_outside_02x
-- The invoices behind the INJ-03 signature (listed so that run_all.py can check the five injected invoices are among them).
SELECT r.invoice_id, r.vendor_id FROM ib_run r
WHERE r.c = '2026-10-01T02:00:00Z' AND 'QUANTITY_BLOCKED' = ANY (r.reasons) AND r.vendor_id NOT BETWEEN 'ven-020' AND 'ven-029'
ORDER BY r.invoice_id COLLATE "C";

-- @@ cumulative_blocked_candidates
-- The invoices behind the INJ-04 signature.
SELECT invoice_id, vendor_id FROM (
    SELECT DISTINCT r.invoice_id, r.vendor_id FROM ib_run r CROSS JOIN LATERAL jsonb_array_elements(r.line_res) e
    WHERE r.c = '2026-10-01T02:00:00Z' AND e ->> 'reason' = 'QUANTITY_BLOCKED' AND r.vendor_id NOT BETWEEN 'ven-020' AND 'ven-029'
      AND (e ->> 'q')::numeric <= coalesce((SELECT sum(rc.received_quantity) FROM receipts rc WHERE rc.po_line_id = e ->> 'po_line_id' AND NOT rc.reversed AND rc.received_at <= r.c), 0)
) z ORDER BY invoice_id COLLATE "C";
