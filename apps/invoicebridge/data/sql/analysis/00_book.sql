-- 00_book.sql: the derived book per cutoff, recomputed from FACTS and kept in temporary tables for the investigations (P05-ART-04).
--
-- The common table expressions below are a verbatim copy of data/sql/reference_metrics.sql (the independent SQL recomputation of
-- every metric: tax once per invoice, duplicates by source bytes then identity, committed invoices first, the three-way match with
-- cumulative consumption in a recursive chain, policy-valid approvals), with ONE change: its two parameters are written as the
-- snapshot's literals (the as-of 2026-10-01T02:00:00Z and the three snapshot cutoffs of web/public/data/manifest.json), so the file
-- runs under psql as it is. tests/test_artifacts.py checks that the copy equals the reference text line for line.
-- It reads no stored status, match result, merge flag or total. Temporary tables (they vanish with the session):
--   ib_run    one row per invoice in the book at each cutoff c: matched, reasons, total, vendor, currency, line results (jsonb)
--   ib_facts  one row per (cutoff, kind) of: merged (ref = canonical, code = reason), review, commit (the first policy-valid approval),
--             reject (a reject decision, code NULL when valid)
-- Run time is about as long as one reference query (the chain is recursive): about two minutes on 2,800 invoices.

-- @@ book_run
CREATE TEMP TABLE ib_run AS
WITH RECURSIVE
params AS (
    SELECT '2026-10-01T02:00:00Z'::timestamptz AS as_of,
           ARRAY['2026-03-31T23:59:59Z', '2026-06-30T23:59:59Z', '2026-10-01T02:00:00Z']::timestamptz[] AS cuts
),
tol AS (
    SELECT coalesce((SELECT price_per_unit FROM tolerances WHERE id = 1), 0.00)          AS price,
           coalesce((SELECT rounding_per_line FROM tolerances WHERE id = 1), 0.01)       AS per_line,
           coalesce((SELECT rounding_per_invoice FROM tolerances WHERE id = 1), 0.02)    AS per_invoice
),
-- one row per distinct cutoff: the main one (main) and/or a snapshot cutoff (snap)
cuts AS (
    SELECT c, bool_or(main) AS main, bool_or(NOT main) AS snap
    FROM (SELECT as_of AS c, TRUE AS main FROM params
          UNION ALL SELECT x, FALSE FROM params, unnest(cuts) AS x) z
    GROUP BY c
),
-- ---- invoice amounts, recomputed from the lines --------------------------------------------------------------
inv_raw AS (
    SELECT i.*, coalesce(sum(l.quantity * l.unit_price), 0) AS raw
    FROM invoices i LEFT JOIN invoice_lines l USING (invoice_id)
    GROUP BY i.invoice_id
),
inv AS (
    SELECT invoice_id, vendor_id, invoice_number, invoice_date, currency, imported_at, created_by, source_sha256, validity,
           declared_total, freight, invoice_discount,
           round(raw, 2) AS sub, round(raw * tax_rate, 2) AS tax,
           round(raw, 2) + round(raw * tax_rate, 2) + freight - invoice_discount AS total,
           vendor_id || '|' || regexp_replace(upper(invoice_number), '[^A-Z0-9]', '', 'g') || '|' || to_char(invoice_date, 'YYYY-MM-DD')
               || '|' || (round(raw, 2) + round(raw * tax_rate, 2) + freight - invoice_discount)::text AS ident
    FROM inv_raw
),
-- ---- policies and decisions ---------------------------------------------------------------------------------
dec AS (
    SELECT a.approval_id, a.invoice_id, a.actor_id, a.actor_role, a.decision, a.decided_at,
           p.reviewer_role, p.escalation_role, p.amount_limit, p.policy_id IS NOT NULL AS has_policy
    FROM approvals a
    LEFT JOIN LATERAL (
        SELECT * FROM approval_policies ap WHERE ap.effective_from <= a.decided_at
        ORDER BY ap.effective_from DESC, ap.version_number DESC, ap.policy_id COLLATE "C" DESC LIMIT 1
    ) p ON TRUE
),
-- the first POLICY-VALID approve decision of each invoice per cutoff (separation of duties, role and limit at decision time,
-- not before the import): the committed invoices. Independent of duplicates, rejections and the match.
pol_ok AS (
    SELECT DISTINCT ON (cu.c, d.invoice_id) cu.c, d.invoice_id, d.approval_id, d.decided_at
    FROM cuts cu
    JOIN dec d ON d.decision = 'approve' AND d.decided_at <= cu.c
    JOIN inv i ON i.invoice_id = d.invoice_id AND i.validity IS DISTINCT FROM FALSE AND i.imported_at <= cu.c
    WHERE d.actor_id <> i.created_by
      AND d.has_policy
      AND (coalesce(d.actor_role = d.escalation_role, FALSE) OR (d.actor_role = d.reviewer_role AND i.total <= d.amount_limit))
      AND d.decided_at >= i.imported_at
    ORDER BY cu.c, d.invoice_id, d.decided_at, d.approval_id COLLATE "C"
),
-- ---- duplicate merge per cutoff: greedy chain, committed invoices first, then import order --------------------------
dord AS (
    SELECT cu.c, i.invoice_id, i.source_sha256 AS sha, i.ident AS key,
           row_number() OVER (PARTITION BY cu.c ORDER BY (po.invoice_id IS NULL), po.decided_at, po.approval_id COLLATE "C",
                              i.imported_at, i.invoice_id COLLATE "C") AS rn
    FROM cuts cu
    JOIN inv i ON i.validity IS DISTINCT FROM FALSE AND i.imported_at <= cu.c
    LEFT JOIN pol_ok po ON po.c = cu.c AND po.invoice_id = i.invoice_id
),
dchain (c, rn, invoice_id, canon, reason, conflict, sha_map, key_map) AS (
    SELECT c, 0::bigint, NULL::text, NULL::text, NULL::text, FALSE, '{}'::jsonb, '{}'::jsonb FROM cuts
    UNION ALL
    SELECT o.c, o.rn, o.invoice_id, k.canon, k.reason, k.conflict,
           CASE WHEN k.conflict THEN d.sha_map ELSE jsonb_build_object(o.sha, k.canon) || d.sha_map END,
           CASE WHEN k.conflict THEN d.key_map ELSE jsonb_build_object(o.key, k.canon) || d.key_map END
    FROM dchain d
    JOIN dord o ON o.c = d.c AND o.rn = d.rn + 1
    CROSS JOIN LATERAL (
        SELECT coalesce(d.sha_map ->> o.sha, d.key_map ->> o.key, o.invoice_id) AS canon,
               CASE WHEN d.sha_map ? o.sha THEN 'DUPLICATE_SOURCE_BYTES'
                    WHEN d.key_map ? o.key THEN 'DUPLICATE_IDENTITY' END AS reason,
               -- same bytes, other extracted fields: held for review, merged into nothing, seeds neither map
               (d.sha_map ? o.sha AND (SELECT x.ident FROM inv x WHERE x.invoice_id = d.sha_map ->> o.sha) IS DISTINCT FROM o.key) AS conflict
    ) k
),
merged AS (
    SELECT c, invoice_id, canon AS merged_into, reason FROM dchain WHERE rn > 0 AND reason IS NOT NULL AND NOT conflict
),
review AS (
    SELECT c, invoice_id, canon FROM dchain WHERE rn > 0 AND conflict
),
rej AS (
    SELECT cu.c, cu.main, d.approval_id, d.invoice_id, d.decided_at,
           CASE WHEN i.invoice_id IS NULL OR m.invoice_id IS NOT NULL OR rv.invoice_id IS NOT NULL OR i.validity IS NOT TRUE
                     OR i.imported_at > cu.c THEN 'NOT_REVIEWABLE'
                WHEN NOT d.has_policy OR NOT (d.actor_role = d.reviewer_role OR coalesce(d.actor_role = d.escalation_role, FALSE))
                     THEN 'ROLE_OR_LIMIT'
                WHEN d.actor_id = i.created_by THEN 'SELF_DECISION'
                WHEN d.decided_at < i.imported_at THEN 'BEFORE_IMPORT'
                WHEN fa.invoice_id IS NOT NULL AND (fa.decided_at, fa.approval_id COLLATE "C") < (d.decided_at, d.approval_id COLLATE "C")
                     THEN 'REJECT_AFTER_APPROVAL' END AS code
    FROM cuts cu
    JOIN dec d ON d.decision = 'reject' AND d.decided_at <= cu.c
    LEFT JOIN inv i ON i.invoice_id = d.invoice_id
    LEFT JOIN merged m ON m.c = cu.c AND m.invoice_id = d.invoice_id
    LEFT JOIN review rv ON rv.c = cu.c AND rv.invoice_id = d.invoice_id
    LEFT JOIN pol_ok fa ON fa.c = cu.c AND fa.invoice_id = d.invoice_id
),
-- reject decisions per cutoff: valid ones take the invoice out of the book at that cutoff
rejected AS (SELECT DISTINCT c, invoice_id FROM rej WHERE code IS NULL),
-- ---- the book per cutoff -------------------------------------------------------------------------------------
cand AS (
    SELECT cu.c, i.invoice_id, i.currency, i.vendor_id, i.total, i.declared_total, i.sub, i.tax, i.created_by,
           row_number() OVER (PARTITION BY cu.c ORDER BY (po.invoice_id IS NULL), po.decided_at, po.approval_id COLLATE "C",
                              i.invoice_date, i.imported_at, i.invoice_id COLLATE "C") AS rn
    FROM cuts cu
    JOIN inv i ON i.validity IS TRUE AND i.imported_at <= cu.c
    LEFT JOIN pol_ok po ON po.c = cu.c AND po.invoice_id = i.invoice_id
    WHERE NOT EXISTS (SELECT 1 FROM merged m WHERE m.c = cu.c AND m.invoice_id = i.invoice_id)
      AND NOT EXISTS (SELECT 1 FROM review v WHERE v.c = cu.c AND v.invoice_id = i.invoice_id)
      AND NOT EXISTS (SELECT 1 FROM rejected r WHERE r.c = cu.c AND r.invoice_id = i.invoice_id)
),
pl AS (
    SELECT cu.c, l.po_line_id, l.quantity, l.unit_price, p.currency, p.vendor_id,
           coalesce(sum(r.received_quantity) FILTER (WHERE NOT r.reversed AND r.received_at <= cu.c), 0) AS net
    FROM cuts cu
    JOIN purchase_orders p ON p.ordered_at <= cu.c
    JOIN po_lines l ON l.po_id = p.po_id
    LEFT JOIN receipts r ON r.po_line_id = l.po_line_id
    GROUP BY cu.c, l.po_line_id, l.quantity, l.unit_price, p.currency, p.vendor_id
),
mchain (c, rn, invoice_id, matched, state, reasons, line_res) AS (
    SELECT c, 0::bigint, NULL::text, TRUE, '{}'::jsonb, NULL::text[], NULL::jsonb FROM cuts
    UNION ALL
    SELECT m.c, i.rn, i.invoice_id, r.matched, r.new_state, r.reasons, r.line_res
    FROM mchain m
    JOIN cand i ON i.c = m.c AND i.rn = m.rn + 1
    CROSS JOIN LATERAL (
        WITH ln AS (
            SELECT l.invoice_line_id, l.po_line_id, l.quantity AS q, l.unit_price AS pr, l.line_amount,
                   (p.po_line_id IS NOT NULL AND p.vendor_id = i.vendor_id) AS has_po, p.currency AS po_cur, p.unit_price AS po_price,
                   (p.po_line_id IS NOT NULL AND p.vendor_id = i.vendor_id AND p.currency = i.currency) AS comparable,
                   coalesce(p.net, 0) - coalesce((m.state ->> l.po_line_id)::numeric, 0)
                     - coalesce(sum(l.quantity) FILTER (WHERE p.po_line_id IS NOT NULL AND p.vendor_id = i.vendor_id AND p.currency = i.currency)
                                OVER (PARTITION BY l.po_line_id ORDER BY l.invoice_line_id COLLATE "C"
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS avail
            FROM invoice_lines l
            LEFT JOIN pl p ON p.c = m.c AND p.po_line_id = l.po_line_id
            WHERE l.invoice_id = i.invoice_id
        ),
        lr AS (
            SELECT ln.*,
                   CASE WHEN NOT has_po THEN 'NO_PO_LINE'
                        WHEN NOT comparable THEN 'CURRENCY_MISMATCH'
                        WHEN q - avail > 0 THEN 'QUANTITY_BLOCKED'
                        WHEN abs(pr - po_price) > (SELECT price FROM tol) THEN 'PRICE_VARIANCE' END AS reason,
                   (line_amount IS NOT NULL AND abs(line_amount - round(q * pr, 2)) > (SELECT per_line FROM tol)) AS line_round
            FROM ln
        ),
        agg AS (
            SELECT array(SELECT x FROM (SELECT DISTINCT x FROM (
                       SELECT reason AS x FROM lr WHERE reason IS NOT NULL
                       UNION ALL SELECT 'ROUNDING_EXCEPTION' WHERE EXISTS (SELECT 1 FROM lr WHERE line_round)
                                                                  OR abs(i.declared_total - i.total) > (SELECT per_invoice FROM tol)
                   ) y) z ORDER BY x COLLATE "C") AS reasons
        )
        SELECT (cardinality(agg.reasons) = 0) AS matched,
               agg.reasons AS reasons,
               CASE WHEN cardinality(agg.reasons) = 0 THEN
                    m.state || coalesce((SELECT jsonb_object_agg(g.po_line_id, coalesce((m.state ->> g.po_line_id)::numeric, 0) + g.sq)
                                         FROM (SELECT po_line_id, sum(q) AS sq FROM lr WHERE comparable GROUP BY po_line_id) g), '{}'::jsonb)
                    ELSE m.state END AS new_state,
               (SELECT jsonb_agg(jsonb_build_object('line', lr.invoice_line_id, 'po_line_id', lr.po_line_id, 'reason', lr.reason,
                                                    'q', lr.q, 'pr', lr.pr, 'comparable', lr.comparable)
                                 ORDER BY lr.invoice_line_id COLLATE "C") FROM lr) AS line_res
        FROM agg
    ) r
),
run_inv AS (
    SELECT mc.c, mc.invoice_id, mc.matched, mc.reasons, ca.total, ca.sub, ca.tax, ca.created_by, ca.currency, ca.rn
    FROM mchain mc JOIN cand ca ON ca.c = mc.c AND ca.invoice_id = mc.invoice_id
    WHERE mc.rn > 0
)
SELECT ri.c, ri.invoice_id, ri.rn, ri.matched, ri.reasons, ri.total, ri.sub, ri.tax, ri.currency, ri.created_by,
       ca.vendor_id, mc.line_res
FROM run_inv ri
JOIN cand ca ON ca.c = ri.c AND ca.invoice_id = ri.invoice_id
JOIN mchain mc ON mc.c = ri.c AND mc.invoice_id = ri.invoice_id AND mc.rn > 0;

-- @@ book_facts
CREATE TEMP TABLE ib_facts AS
WITH RECURSIVE
params AS (
    SELECT '2026-10-01T02:00:00Z'::timestamptz AS as_of,
           ARRAY['2026-03-31T23:59:59Z', '2026-06-30T23:59:59Z', '2026-10-01T02:00:00Z']::timestamptz[] AS cuts
),
tol AS (
    SELECT coalesce((SELECT price_per_unit FROM tolerances WHERE id = 1), 0.00)          AS price,
           coalesce((SELECT rounding_per_line FROM tolerances WHERE id = 1), 0.01)       AS per_line,
           coalesce((SELECT rounding_per_invoice FROM tolerances WHERE id = 1), 0.02)    AS per_invoice
),
-- one row per distinct cutoff: the main one (main) and/or a snapshot cutoff (snap)
cuts AS (
    SELECT c, bool_or(main) AS main, bool_or(NOT main) AS snap
    FROM (SELECT as_of AS c, TRUE AS main FROM params
          UNION ALL SELECT x, FALSE FROM params, unnest(cuts) AS x) z
    GROUP BY c
),
-- ---- invoice amounts, recomputed from the lines --------------------------------------------------------------
inv_raw AS (
    SELECT i.*, coalesce(sum(l.quantity * l.unit_price), 0) AS raw
    FROM invoices i LEFT JOIN invoice_lines l USING (invoice_id)
    GROUP BY i.invoice_id
),
inv AS (
    SELECT invoice_id, vendor_id, invoice_number, invoice_date, currency, imported_at, created_by, source_sha256, validity,
           declared_total, freight, invoice_discount,
           round(raw, 2) AS sub, round(raw * tax_rate, 2) AS tax,
           round(raw, 2) + round(raw * tax_rate, 2) + freight - invoice_discount AS total,
           vendor_id || '|' || regexp_replace(upper(invoice_number), '[^A-Z0-9]', '', 'g') || '|' || to_char(invoice_date, 'YYYY-MM-DD')
               || '|' || (round(raw, 2) + round(raw * tax_rate, 2) + freight - invoice_discount)::text AS ident
    FROM inv_raw
),
-- ---- policies and decisions ---------------------------------------------------------------------------------
dec AS (
    SELECT a.approval_id, a.invoice_id, a.actor_id, a.actor_role, a.decision, a.decided_at,
           p.reviewer_role, p.escalation_role, p.amount_limit, p.policy_id IS NOT NULL AS has_policy
    FROM approvals a
    LEFT JOIN LATERAL (
        SELECT * FROM approval_policies ap WHERE ap.effective_from <= a.decided_at
        ORDER BY ap.effective_from DESC, ap.version_number DESC, ap.policy_id COLLATE "C" DESC LIMIT 1
    ) p ON TRUE
),
-- the first POLICY-VALID approve decision of each invoice per cutoff (separation of duties, role and limit at decision time,
-- not before the import): the committed invoices. Independent of duplicates, rejections and the match.
pol_ok AS (
    SELECT DISTINCT ON (cu.c, d.invoice_id) cu.c, d.invoice_id, d.approval_id, d.decided_at
    FROM cuts cu
    JOIN dec d ON d.decision = 'approve' AND d.decided_at <= cu.c
    JOIN inv i ON i.invoice_id = d.invoice_id AND i.validity IS DISTINCT FROM FALSE AND i.imported_at <= cu.c
    WHERE d.actor_id <> i.created_by
      AND d.has_policy
      AND (coalesce(d.actor_role = d.escalation_role, FALSE) OR (d.actor_role = d.reviewer_role AND i.total <= d.amount_limit))
      AND d.decided_at >= i.imported_at
    ORDER BY cu.c, d.invoice_id, d.decided_at, d.approval_id COLLATE "C"
),
-- ---- duplicate merge per cutoff: greedy chain, committed invoices first, then import order --------------------------
dord AS (
    SELECT cu.c, i.invoice_id, i.source_sha256 AS sha, i.ident AS key,
           row_number() OVER (PARTITION BY cu.c ORDER BY (po.invoice_id IS NULL), po.decided_at, po.approval_id COLLATE "C",
                              i.imported_at, i.invoice_id COLLATE "C") AS rn
    FROM cuts cu
    JOIN inv i ON i.validity IS DISTINCT FROM FALSE AND i.imported_at <= cu.c
    LEFT JOIN pol_ok po ON po.c = cu.c AND po.invoice_id = i.invoice_id
),
dchain (c, rn, invoice_id, canon, reason, conflict, sha_map, key_map) AS (
    SELECT c, 0::bigint, NULL::text, NULL::text, NULL::text, FALSE, '{}'::jsonb, '{}'::jsonb FROM cuts
    UNION ALL
    SELECT o.c, o.rn, o.invoice_id, k.canon, k.reason, k.conflict,
           CASE WHEN k.conflict THEN d.sha_map ELSE jsonb_build_object(o.sha, k.canon) || d.sha_map END,
           CASE WHEN k.conflict THEN d.key_map ELSE jsonb_build_object(o.key, k.canon) || d.key_map END
    FROM dchain d
    JOIN dord o ON o.c = d.c AND o.rn = d.rn + 1
    CROSS JOIN LATERAL (
        SELECT coalesce(d.sha_map ->> o.sha, d.key_map ->> o.key, o.invoice_id) AS canon,
               CASE WHEN d.sha_map ? o.sha THEN 'DUPLICATE_SOURCE_BYTES'
                    WHEN d.key_map ? o.key THEN 'DUPLICATE_IDENTITY' END AS reason,
               -- same bytes, other extracted fields: held for review, merged into nothing, seeds neither map
               (d.sha_map ? o.sha AND (SELECT x.ident FROM inv x WHERE x.invoice_id = d.sha_map ->> o.sha) IS DISTINCT FROM o.key) AS conflict
    ) k
),
merged AS (
    SELECT c, invoice_id, canon AS merged_into, reason FROM dchain WHERE rn > 0 AND reason IS NOT NULL AND NOT conflict
),
review AS (
    SELECT c, invoice_id, canon FROM dchain WHERE rn > 0 AND conflict
),
rej AS (
    SELECT cu.c, cu.main, d.approval_id, d.invoice_id, d.decided_at,
           CASE WHEN i.invoice_id IS NULL OR m.invoice_id IS NOT NULL OR rv.invoice_id IS NOT NULL OR i.validity IS NOT TRUE
                     OR i.imported_at > cu.c THEN 'NOT_REVIEWABLE'
                WHEN NOT d.has_policy OR NOT (d.actor_role = d.reviewer_role OR coalesce(d.actor_role = d.escalation_role, FALSE))
                     THEN 'ROLE_OR_LIMIT'
                WHEN d.actor_id = i.created_by THEN 'SELF_DECISION'
                WHEN d.decided_at < i.imported_at THEN 'BEFORE_IMPORT'
                WHEN fa.invoice_id IS NOT NULL AND (fa.decided_at, fa.approval_id COLLATE "C") < (d.decided_at, d.approval_id COLLATE "C")
                     THEN 'REJECT_AFTER_APPROVAL' END AS code
    FROM cuts cu
    JOIN dec d ON d.decision = 'reject' AND d.decided_at <= cu.c
    LEFT JOIN inv i ON i.invoice_id = d.invoice_id
    LEFT JOIN merged m ON m.c = cu.c AND m.invoice_id = d.invoice_id
    LEFT JOIN review rv ON rv.c = cu.c AND rv.invoice_id = d.invoice_id
    LEFT JOIN pol_ok fa ON fa.c = cu.c AND fa.invoice_id = d.invoice_id
)
SELECT 'merged'::text AS kind, c, invoice_id, merged_into AS ref, reason AS code, NULL::timestamptz AS at FROM merged
UNION ALL SELECT 'review', c, invoice_id, canon, 'BYTES_FIELDS_CONFLICT', NULL FROM review
UNION ALL SELECT 'commit', c, invoice_id, approval_id, NULL, decided_at FROM pol_ok
UNION ALL SELECT 'reject', c, invoice_id, approval_id, code, decided_at FROM rej;
