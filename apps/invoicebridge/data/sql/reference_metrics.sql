-- InvoiceBridge reference metrics: an independent SQL recomputation of every key of expected.json["metrics"].
--
-- It reads FACTS only (invoices, invoice_lines, po_lines, purchase_orders, receipts, approvals, approval_policies,
-- export_requests, credit_notes, exceptions, exception_assignments, tolerances) and never a stored status, subtotal,
-- total, match result or merge flag. It recomputes: invoice amounts (tax once per invoice on the unrounded subtotal,
-- numeric ROUND = half away from zero = ROUND_HALF_UP), duplicate merge (source bytes first, then identity, greedy in
-- (imported_at, invoice_id) order), reject decisions, the three-way match with cumulative consumption (a recursive CTE
-- over the invoices in (invoice_date, imported_at, invoice_id) order, one chain per cutoff), approvals with separation
-- of duties and the policy in force, idempotent export, credits, open quantities and the snapshots.
--
-- Parameters: %(as_of)s timestamptz (inclusive cutoff of every fact), %(cutoffs)s timestamptz[] (snapshot cutoffs).
-- Returns ONE row with a jsonb column per metric key; strings carry the exact scale (money 2 dp, quantities 4, rates 6).
-- Ordering that decides a result uses COLLATE "C" (code-point order, as Python sorts).
WITH RECURSIVE
params AS (
    SELECT %(as_of)s::timestamptz AS as_of, %(cutoffs)s::timestamptz[] AS cuts
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
-- ---- duplicate merge: greedy chain over the invoices in import order ------------------------------------------
dord AS (
    SELECT invoice_id, source_sha256 AS sha, ident AS key,
           row_number() OVER (ORDER BY imported_at, invoice_id COLLATE "C") AS rn
    FROM inv
),
dchain (rn, invoice_id, canon, reason, sha_map, key_map) AS (
    SELECT 0::bigint, NULL::text, NULL::text, NULL::text, '{}'::jsonb, '{}'::jsonb
    UNION ALL
    SELECT o.rn, o.invoice_id, k.canon, k.reason,
           jsonb_build_object(o.sha, k.canon) || d.sha_map,
           jsonb_build_object(o.key, k.canon) || d.key_map
    FROM dchain d
    JOIN dord o ON o.rn = d.rn + 1
    CROSS JOIN LATERAL (
        SELECT coalesce(d.sha_map ->> o.sha, d.key_map ->> o.key, o.invoice_id) AS canon,
               CASE WHEN d.sha_map ? o.sha THEN 'DUPLICATE_SOURCE_BYTES'
                    WHEN d.key_map ? o.key THEN 'DUPLICATE_IDENTITY' END AS reason
    ) k
),
merged AS (
    SELECT invoice_id, canon AS merged_into, reason FROM dchain WHERE rn > 0 AND reason IS NOT NULL
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
first_approve AS (
    SELECT DISTINCT ON (invoice_id) invoice_id, decided_at, approval_id
    FROM approvals WHERE decision = 'approve'
    ORDER BY invoice_id, decided_at, approval_id COLLATE "C"
),
-- reject decisions per cutoff: valid ones take the invoice out of the book at that cutoff
rej AS (
    SELECT cu.c, cu.main, d.approval_id, d.invoice_id, d.decided_at,
           CASE WHEN i.invoice_id IS NULL OR m.invoice_id IS NOT NULL OR i.validity IS NOT TRUE OR i.imported_at > cu.c
                     THEN 'NOT_REVIEWABLE'
                WHEN NOT d.has_policy OR NOT (d.actor_role = d.reviewer_role OR coalesce(d.actor_role = d.escalation_role, FALSE))
                     THEN 'ROLE_OR_LIMIT'
                WHEN fa.invoice_id IS NOT NULL AND (fa.decided_at, fa.approval_id COLLATE "C") < (d.decided_at, d.approval_id COLLATE "C")
                     THEN 'REJECT_AFTER_APPROVAL' END AS code
    FROM cuts cu
    JOIN dec d ON d.decision = 'reject' AND d.decided_at <= cu.c
    LEFT JOIN inv i ON i.invoice_id = d.invoice_id
    LEFT JOIN merged m ON m.invoice_id = d.invoice_id
    LEFT JOIN first_approve fa ON fa.invoice_id = d.invoice_id
),
rejected AS (SELECT DISTINCT c, invoice_id FROM rej WHERE code IS NULL),
-- ---- the book per cutoff -------------------------------------------------------------------------------------
cand AS (
    SELECT cu.c, i.invoice_id, i.currency, i.total, i.declared_total, i.sub, i.tax, i.created_by,
           row_number() OVER (PARTITION BY cu.c ORDER BY i.invoice_date, i.imported_at, i.invoice_id COLLATE "C") AS rn
    FROM cuts cu JOIN inv i ON i.validity IS TRUE AND i.imported_at <= cu.c
    WHERE NOT EXISTS (SELECT 1 FROM merged m WHERE m.invoice_id = i.invoice_id)
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
                   p.po_line_id IS NOT NULL AS has_po, p.currency AS po_cur, p.unit_price AS po_price,
                   (p.po_line_id IS NOT NULL AND p.currency = i.currency) AS comparable,
                   coalesce(p.net, 0) - coalesce((m.state ->> l.po_line_id)::numeric, 0)
                     - coalesce(sum(l.quantity) FILTER (WHERE p.po_line_id IS NOT NULL AND p.currency = i.currency)
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
    SELECT mc.c, mc.invoice_id, mc.matched, mc.reasons, ca.total, ca.sub, ca.tax, ca.created_by, ca.rn
    FROM mchain mc JOIN cand ca ON ca.c = mc.c AND ca.invoice_id = mc.invoice_id
    WHERE mc.rn > 0
),
-- the consumption at the end of each chain, and the blocked lines (quantity variance x invoice price)
final_state AS (
    SELECT DISTINCT ON (c) c, state FROM mchain ORDER BY c, rn DESC
),
consumed AS (
    SELECT p.c, p.po_line_id, coalesce((fs.state ->> p.po_line_id)::numeric, 0) AS used
    FROM pl p LEFT JOIN final_state fs ON fs.c = p.c
),
blocked AS (
    -- available at the time of the line is recomputed from the chain: net - consumed before the invoice - earlier lines
    SELECT mc.c, (e ->> 'po_line_id') AS po_line_id, (e ->> 'q')::numeric AS q, (e ->> 'pr')::numeric AS pr, mc.rn, e ->> 'line' AS line
    FROM mchain mc, jsonb_array_elements(mc.line_res) e
    WHERE mc.rn > 0 AND e ->> 'reason' = 'QUANTITY_BLOCKED'
),
blocked_qv AS (
    SELECT b.c, b.po_line_id, b.pr,
           b.q - (p.net - coalesce((prev.state ->> b.po_line_id)::numeric, 0)
                  - coalesce((SELECT sum((e2 ->> 'q')::numeric)
                              FROM mchain mc2, jsonb_array_elements(mc2.line_res) e2
                              WHERE mc2.c = b.c AND mc2.rn = b.rn AND e2 ->> 'po_line_id' = b.po_line_id
                                AND (e2 ->> 'comparable')::boolean AND (e2 ->> 'line') COLLATE "C" < b.line COLLATE "C"), 0)) AS qv
    FROM blocked b
    JOIN pl p ON p.c = b.c AND p.po_line_id = b.po_line_id
    JOIN mchain prev ON prev.c = b.c AND prev.rn = b.rn - 1
),
qty AS (
    SELECT cu.c, cu.main, cu.snap,
           coalesce((SELECT sum(quantity) FROM pl WHERE pl.c = cu.c), 0) AS ordered,
           coalesce((SELECT sum(net) FROM pl WHERE pl.c = cu.c), 0) AS net,
           coalesce((SELECT sum(used) FROM consumed WHERE consumed.c = cu.c), 0) AS used,
           coalesce((SELECT sum(greatest(quantity - net, 0)) FROM pl WHERE pl.c = cu.c), 0) AS open_receive,
           coalesce((SELECT sum(greatest(pl.quantity - k.used, 0)) FROM pl JOIN consumed k ON k.c = pl.c AND k.po_line_id = pl.po_line_id WHERE pl.c = cu.c), 0) AS open_invoice,
           coalesce((SELECT sum(greatest(pl.net - k.used, 0)) FROM pl JOIN consumed k ON k.c = pl.c AND k.po_line_id = pl.po_line_id WHERE pl.c = cu.c), 0) AS rni_q,
           coalesce((SELECT sum(greatest(pl.net - k.used, 0) * pl.unit_price) FROM pl JOIN consumed k ON k.c = pl.c AND k.po_line_id = pl.po_line_id WHERE pl.c = cu.c), 0) AS rni_v,
           coalesce((SELECT sum(qv) FROM blocked_qv WHERE blocked_qv.c = cu.c), 0) AS blk_q,
           coalesce((SELECT sum(qv * pr) FROM blocked_qv WHERE blocked_qv.c = cu.c), 0) AS blk_v
    FROM cuts cu
),
qty_json AS (
    SELECT c, main, snap, jsonb_build_object(
        'ordered_quantity', round(ordered, 4)::text, 'net_received_quantity', round(net, 4)::text,
        'accepted_invoiced_quantity', round(used, 4)::text, 'open_to_receive_quantity', round(open_receive, 4)::text,
        'open_to_invoice_quantity', round(open_invoice, 4)::text, 'received_not_invoiced_quantity', round(rni_q, 4)::text,
        'received_not_invoiced_value', round(rni_v, 2)::text, 'invoiced_not_received_quantity', round(blk_q, 4)::text,
        'invoiced_not_received_value', round(blk_v, 2)::text) AS j
    FROM qty
),
-- ---- approvals at the main cutoff ---------------------------------------------------------------------------
main_run AS (SELECT ri.* FROM run_inv ri JOIN params p ON ri.c = p.as_of),
approve_verdict AS (
    SELECT d.approval_id, d.invoice_id, d.decided_at,
           CASE WHEN r.invoice_id IS NULL OR NOT r.matched THEN 'NOT_MATCHED'
                WHEN d.actor_id = i.created_by THEN 'SELF_APPROVAL'
                WHEN NOT d.has_policy
                     OR NOT (coalesce(d.actor_role = d.escalation_role, FALSE)
                             OR (d.actor_role = d.reviewer_role AND r.total <= d.amount_limit)) THEN 'ROLE_OR_LIMIT' END AS code
    FROM dec d
    JOIN params p ON d.decided_at <= p.as_of AND d.decision = 'approve'
    JOIN inv i ON i.invoice_id = d.invoice_id
    LEFT JOIN main_run r ON r.invoice_id = d.invoice_id
),
approved AS (
    SELECT DISTINCT ON (invoice_id) invoice_id, decided_at
    FROM approve_verdict WHERE code IS NULL ORDER BY invoice_id, decided_at, approval_id COLLATE "C"
),
invalid AS (
    SELECT approval_id, code, decided_at FROM approve_verdict WHERE code IS NOT NULL
    UNION ALL
    SELECT approval_id, code, decided_at FROM rej WHERE main AND code IS NOT NULL
),
-- ---- export: an idempotent batch; a repeated key or batch id returns the prior batch ---------------------------------
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT as_of FROM params)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT as_of FROM params)
),
exp_first AS (
    SELECT DISTINCT ON (iid) iid, r.request_seq, r.batch_id, r.exported_at
    FROM req r, unnest(r.invoice_ids) AS iid
    WHERE NOT r.repeat AND EXISTS (SELECT 1 FROM approved a WHERE a.invoice_id = iid)
    ORDER BY iid, r.request_seq
),
exp_rows AS (
    SELECT x.request_seq, x.iid, i.invoice_number, i.invoice_date, i.vendor_id, i.currency, i.total, x.batch_id, x.exported_at,
           to_char(x.exported_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
             || CASE WHEN mod(date_part('microseconds', x.exported_at AT TIME ZONE 'UTC')::bigint, 1000000) <> 0
                     THEN '.' || to_char(x.exported_at AT TIME ZONE 'UTC', 'US') ELSE '' END || 'Z' AS at_text
    FROM exp_first x JOIN inv i ON i.invoice_id = x.iid
),
-- ---- exceptions: one per (invoice, type); the id and owner come from the stored record when there is one ---------------
exc_d AS (
    SELECT ri.invoice_id, t AS etype, row_number() OVER (ORDER BY ri.invoice_id COLLATE "C", t COLLATE "C") AS pos
    FROM main_run ri, unnest(ri.reasons) AS t
),
exc_s AS (
    SELECT DISTINCT ON (invoice_id, exception_type) invoice_id, exception_type, exception_id
    FROM exceptions
    ORDER BY invoice_id, exception_type, (status <> 'resolved') DESC, created_at DESC, exception_id DESC
),
exc_o AS (
    SELECT DISTINCT ON (exception_id) exception_id, owner_id
    FROM exception_assignments WHERE assigned_at <= (SELECT as_of FROM params)
    ORDER BY exception_id, assigned_at DESC, assignment_id DESC
),
exc AS (
    SELECT d.invoice_id, d.etype, d.pos, coalesce(s.exception_id, 'exc-' || lpad(d.pos::text, 3, '0')) AS eid, o.owner_id
    FROM exc_d d
    LEFT JOIN exc_s s ON s.invoice_id = d.invoice_id AND s.exception_type = d.etype
    LEFT JOIN exc_o o ON o.exception_id = coalesce(s.exception_id, 'exc-' || lpad(d.pos::text, 3, '0'))
),
good AS (SELECT * FROM main_run WHERE matched),
oblig AS (SELECT g.* FROM good g JOIN approved a ON a.invoice_id = g.invoice_id),
cred AS (
    SELECT coalesce(sum(cn.credit_amount), 0) AS total
    FROM credit_notes cn JOIN approved a ON a.invoice_id = cn.invoice_id
    WHERE cn.credited_at IS NULL OR cn.credited_at <= (SELECT as_of FROM params)
),
elig AS (SELECT count(*) AS n, count(*) FILTER (WHERE cardinality(reasons) > 0) AS flagged FROM main_run),
proc AS (
    SELECT count(*) AS n,
           sum(extract(epoch FROM (a.decided_at - i.imported_at))) AS secs
    FROM approved a JOIN inv i ON i.invoice_id = a.invoice_id
),
dups AS (
    SELECT count(*) AS merged_rows, count(DISTINCT merged_into) AS groups FROM merged
)
SELECT
    jsonb_build_object(
        'invoice_count', (SELECT count(*) FROM good),
        'amount_before_tax', round((SELECT coalesce(sum(sub), 0) FROM good), 2)::text,
        'tax', round((SELECT coalesce(sum(tax), 0) FROM good), 2)::text,
        'total', round((SELECT coalesce(sum(total), 0) FROM good), 2)::text) AS matched,
    jsonb_build_object(
        'count', (SELECT count(*) FROM oblig),
        'total', round((SELECT coalesce(sum(total), 0) FROM oblig), 2)::text) AS obligations,
    jsonb_build_object(
        'open_count', (SELECT count(*) FROM exc),
        'unowned_count', (SELECT count(*) FROM exc WHERE owner_id IS NULL),
        'by_reason', jsonb_build_object(
            'QUANTITY_BLOCKED', (SELECT count(*) FROM exc WHERE etype = 'QUANTITY_BLOCKED'),
            'PRICE_VARIANCE', (SELECT count(*) FROM exc WHERE etype = 'PRICE_VARIANCE'),
            'NO_PO_LINE', (SELECT count(*) FROM exc WHERE etype = 'NO_PO_LINE'),
            'ROUNDING_EXCEPTION', (SELECT count(*) FROM exc WHERE etype = 'ROUNDING_EXCEPTION'),
            'CURRENCY_MISMATCH', (SELECT count(*) FROM exc WHERE etype = 'CURRENCY_MISMATCH')),
        'records', coalesce((SELECT jsonb_agg(jsonb_build_object('exception_id', eid, 'invoice_id', invoice_id,
                        'exception_type', etype, 'owner_id', owner_id,
                        'status', CASE WHEN owner_id IS NULL THEN 'open' ELSE 'assigned' END) ORDER BY pos) FROM exc), '[]'::jsonb)) AS exceptions,
    jsonb_build_object('groups_detected', (SELECT groups FROM dups), 'rows_merged', (SELECT merged_rows FROM dups),
                       'unresolved_groups', 0) AS duplicates,
    (SELECT j FROM qty_json WHERE main) AS quantities,
    coalesce((SELECT jsonb_object_agg(
                  to_char(c AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
                  || CASE WHEN mod(date_part('microseconds', c AT TIME ZONE 'UTC')::bigint, 1000000) <> 0
                          THEN '.' || to_char(c AT TIME ZONE 'UTC', 'US') ELSE '' END || 'Z', j)
              FROM qty_json WHERE snap), '{}'::jsonb) AS snapshots,
    jsonb_build_object(
        'eligible_invoices', (SELECT n FROM elig),
        'straight_through_rate', CASE WHEN (SELECT n FROM elig) = 0 THEN NULL
            ELSE to_jsonb(round(((SELECT n - flagged FROM elig))::numeric / (SELECT n FROM elig), 6)::text) END,
        'exception_rate', CASE WHEN (SELECT n FROM elig) = 0 THEN NULL
            ELSE to_jsonb(round(((SELECT flagged FROM elig))::numeric / (SELECT n FROM elig), 6)::text) END) AS rates,
    jsonb_build_object(
        'approved_count', (SELECT n FROM proc),
        'mean_minutes', CASE WHEN (SELECT n FROM proc) = 0 THEN NULL
            ELSE to_jsonb(round((SELECT secs FROM proc) / 60 / (SELECT n FROM proc), 4)::text) END,
        'pending_count', (SELECT n FROM elig) - (SELECT count(*) FROM main_run mr JOIN approved a ON a.invoice_id = mr.invoice_id)) AS processing,
    jsonb_build_object(
        'valid_count', (SELECT count(*) FROM approved),
        'invalid_records', coalesce((SELECT jsonb_agg(jsonb_build_object('approval_id', approval_id, 'reason_code', code)
                                                      ORDER BY decided_at, approval_id COLLATE "C") FROM invalid), '[]'::jsonb)) AS approvals,
    jsonb_build_object(
        'approved_total', round((SELECT coalesce(sum(total), 0) FROM oblig), 2)::text,
        'credit_total', round((SELECT total FROM cred), 2)::text,
        'approved_payable', round((SELECT coalesce(sum(total), 0) FROM oblig) - (SELECT total FROM cred), 2)::text) AS payable,
    jsonb_build_object(
        'requests_received', (SELECT count(*) FROM req),
        'batches_created', (SELECT count(*) FROM req WHERE NOT repeat),
        'repeat_requests_returned_prior', (SELECT count(*) FROM req WHERE repeat),
        'rows', coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'export_id', 'exp-' || batch_id || '-' || iid, 'invoice_id', iid, 'batch_id', batch_id, 'exported_at', at_text,
                    'vendor_id', vendor_id, 'invoice_number', invoice_number, 'invoice_date', to_char(invoice_date, 'YYYY-MM-DD'),
                    'currency', currency, 'amount', round(total, 2)::text,
                    'content_hash', encode(sha256(convert_to(iid || '|' || vendor_id || '|' || invoice_number || '|'
                                           || to_char(invoice_date, 'YYYY-MM-DD') || '|' || currency || '|' || round(total, 2)::text, 'UTF8')), 'hex'))
                    ORDER BY request_seq, iid COLLATE "C") FROM exp_rows), '[]'::jsonb),
        'exclusions', coalesce((SELECT jsonb_agg(jsonb_build_object('invoice_id', mr.invoice_id,
                        'reason_code', CASE WHEN NOT mr.matched THEN 'EXCEPTION_OPEN' ELSE 'NOT_APPROVED' END)
                        ORDER BY mr.invoice_id COLLATE "C")
                     FROM main_run mr WHERE (NOT mr.matched) OR (mr.matched AND NOT EXISTS (SELECT 1 FROM approved a WHERE a.invoice_id = mr.invoice_id))), '[]'::jsonb),
        'accepted_export_total', round((SELECT coalesce(sum(total), 0) FROM exp_rows), 2)::text,
        'eligible_approved_total', round((SELECT coalesce(sum(total), 0) FROM oblig), 2)::text,
        'difference', round((SELECT coalesce(sum(total), 0) FROM exp_rows) - (SELECT coalesce(sum(total), 0) FROM oblig), 2)::text) AS export
