-- 06_export_batches_and_reconciliation.sql: export batches, retries and the reconciliation of what was exported with what was approved (P05-ART-04, D-04, D-09.6, P05-MET-11).
-- Question: which approved invoices have advanced to payment export, which have not and why?
-- Needs 00_book.sql (ib_run: the book at the as-of; ib_facts: `commit` rows, the first policy-valid approval of each invoice).
-- An export REQUEST names invoices; a request whose idempotency key or batch id was seen before is a REPEAT and returns the prior batch,
-- writing nothing. An export ROW exists for an invoice named by a non-repeat request when a policy-valid approval exists at or before the
-- request's exported_at (D-09: a row needs a prior approval); the first such request wins. The amount is the invoice's COMPUTED total.
-- The reconciliation difference is 0.00 BY CONSTRUCTION of the generator, which closes each period with a batch of everything approved
-- (D-07, data/README-generator.md): a zero here shows the arithmetic and the exclusion list agree, not that a real export process is complete.
-- Money is per currency and never summed across currencies. Instants are UTC.

-- @@ batch_summary
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT t FROM asof)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT t FROM asof)
),
rows_ AS (
    SELECT DISTINCT ON (iid) iid, r.request_seq, r.batch_id, r.exported_at
    FROM req r CROSS JOIN LATERAL unnest(r.invoice_ids) AS iid
    JOIN ib_facts f ON f.kind = 'commit' AND f.c = (SELECT t FROM asof) AND f.invoice_id = iid AND f.at <= r.exported_at
    WHERE NOT r.repeat ORDER BY iid, r.request_seq
)
SELECT 'requests received' AS measure, count(*) AS n FROM req
UNION ALL SELECT 'batches created (non-repeat requests)', count(*) FROM req WHERE NOT repeat
UNION ALL SELECT 'repeat requests answered with the prior batch', count(*) FROM req WHERE repeat
UNION ALL SELECT 'export rows (invoices exported)', count(*) FROM rows_
UNION ALL SELECT 'distinct invoices named by any request', count(DISTINCT iid) FROM req, unnest(invoice_ids) AS iid
UNION ALL SELECT 'stored export_batches rows (cross-check)', count(*) FROM export_batches
UNION ALL SELECT 'stored export_rows rows (cross-check)', count(*) FROM export_rows;

-- @@ reconciliation_by_currency
-- Per currency: what the export rows total against what the approved (obligation) invoices total, and the number of invoices on each side.
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT t FROM asof)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT t FROM asof)
),
rows_ AS (
    SELECT DISTINCT ON (iid) iid, r.request_seq
    FROM req r CROSS JOIN LATERAL unnest(r.invoice_ids) AS iid
    JOIN ib_facts f ON f.kind = 'commit' AND f.c = (SELECT t FROM asof) AND f.invoice_id = iid AND f.at <= r.exported_at
    WHERE NOT r.repeat ORDER BY iid, r.request_seq
),
ex AS (SELECT i.currency, count(*) AS n, sum(i.total) AS tot FROM rows_ x JOIN ib_run i ON i.c = (SELECT t FROM asof) AND i.invoice_id = x.iid GROUP BY i.currency),
ob AS (SELECT i.currency, count(*) AS n, sum(i.total) AS tot FROM ib_facts f JOIN ib_run i ON i.c = f.c AND i.invoice_id = f.invoice_id
       WHERE f.kind = 'commit' AND f.c = (SELECT t FROM asof) GROUP BY i.currency)
SELECT coalesce(ex.currency, ob.currency) AS currency, coalesce(ex.n, 0) AS exported_invoices, round(coalesce(ex.tot, 0), 2) AS accepted_export_total,
       coalesce(ob.n, 0) AS approved_invoices, round(coalesce(ob.tot, 0), 2) AS eligible_approved_total,
       round(coalesce(ex.tot, 0) - coalesce(ob.tot, 0), 2) AS difference
FROM ex FULL JOIN ob USING (currency) ORDER BY currency COLLATE "C";

-- @@ exclusions_by_reason_and_currency
-- Every invoice in the book at the as-of that no export row took, with the reason (the explicit exclusions of P05-MET-11):
-- EXCEPTION_OPEN (not matched, not approved), NOT_APPROVED (matched, no policy-valid approval), EXPORT_BEFORE_APPROVAL (a request named it
-- before its approval), APPROVED_NOT_EXPORTED (approved, never named by a request).
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT t FROM asof)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT t FROM asof)
),
rows_ AS (
    SELECT DISTINCT ON (iid) iid FROM req r CROSS JOIN LATERAL unnest(r.invoice_ids) AS iid
    JOIN ib_facts f ON f.kind = 'commit' AND f.c = (SELECT t FROM asof) AND f.invoice_id = iid AND f.at <= r.exported_at
    WHERE NOT r.repeat ORDER BY iid, r.request_seq
),
x AS (
    SELECT i.invoice_id, i.currency, i.total,
           CASE WHEN f.invoice_id IS NULL AND NOT i.matched THEN 'EXCEPTION_OPEN'
                WHEN f.invoice_id IS NULL THEN 'NOT_APPROVED'
                WHEN EXISTS (SELECT 1 FROM req r1 WHERE NOT r1.repeat AND i.invoice_id = ANY (r1.invoice_ids)) THEN 'EXPORT_BEFORE_APPROVAL'
                ELSE 'APPROVED_NOT_EXPORTED' END AS reason_code
    FROM ib_run i LEFT JOIN ib_facts f ON f.kind = 'commit' AND f.c = i.c AND f.invoice_id = i.invoice_id
    WHERE i.c = (SELECT t FROM asof) AND NOT EXISTS (SELECT 1 FROM rows_ WHERE rows_.iid = i.invoice_id)
)
SELECT reason_code, currency, count(*) AS invoices, round(sum(total), 2) AS invoice_total
FROM x GROUP BY reason_code, currency ORDER BY reason_code COLLATE "C", currency COLLATE "C";

-- @@ batch_cadence
-- Non-repeat batches by weekday and time of day of exported_at (UTC): the cadence the generator uses (Fridays 16:00Z) and the size of a batch.
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT t FROM asof)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT t FROM asof)
)
SELECT to_char(exported_at AT TIME ZONE 'UTC', 'Dy HH24:MI') AS weekday_and_time, count(*) AS batches, min(cardinality(invoice_ids)) AS fewest_invoices,
       max(cardinality(invoice_ids)) AS most_invoices, round(avg(cardinality(invoice_ids))::numeric, 4) AS mean_invoices
FROM req WHERE NOT repeat GROUP BY 1 ORDER BY 1;

-- @@ repeat_requests
-- The requests answered with the prior batch (a retry after a timeout): same batch id and key, a later exported_at.
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT t FROM asof)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT t FROM asof)
)
SELECT r.batch_id, r.idempotency_key, cardinality(r.invoice_ids) AS invoices_named,
       extract(epoch FROM (r.exported_at - f.exported_at))::int AS seconds_after_first_request
FROM req r JOIN LATERAL (SELECT e.exported_at FROM export_requests e WHERE e.request_seq < r.request_seq AND e.batch_id = r.batch_id ORDER BY e.request_seq LIMIT 1) f ON TRUE
WHERE r.repeat ORDER BY r.batch_id COLLATE "C";

-- @@ approval_to_export_lag
-- Days (4 dp) from the policy-valid approval to the export request that took the invoice, by currency.
WITH asof AS (SELECT '2026-10-01T02:00:00Z'::timestamptz AS t),
req AS (
    SELECT r.*, EXISTS (SELECT 1 FROM export_requests e WHERE e.request_seq < r.request_seq AND e.exported_at <= (SELECT t FROM asof)
                        AND (e.idempotency_key = r.idempotency_key OR e.batch_id = r.batch_id)) AS repeat
    FROM export_requests r WHERE r.exported_at <= (SELECT t FROM asof)
),
rows_ AS (
    SELECT DISTINCT ON (iid) iid, r.exported_at, f.at AS approved_at
    FROM req r CROSS JOIN LATERAL unnest(r.invoice_ids) AS iid
    JOIN ib_facts f ON f.kind = 'commit' AND f.c = (SELECT t FROM asof) AND f.invoice_id = iid AND f.at <= r.exported_at
    WHERE NOT r.repeat ORDER BY iid, r.request_seq
)
SELECT i.currency, count(*) AS exported_invoices, round(avg(extract(epoch FROM (x.exported_at - x.approved_at)) / 86400)::numeric, 4) AS mean_days_approval_to_export,
       round(max(extract(epoch FROM (x.exported_at - x.approved_at)) / 86400)::numeric, 4) AS longest_days
FROM rows_ x JOIN ib_run i ON i.c = (SELECT t FROM asof) AND i.invoice_id = x.iid
GROUP BY i.currency ORDER BY i.currency COLLATE "C";
