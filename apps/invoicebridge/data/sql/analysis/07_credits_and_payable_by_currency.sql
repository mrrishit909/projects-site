-- 07_credits_and_payable_by_currency.sql: credit notes and the approved payable, per currency (P05-ART-04, D-02, D-04, D-09.11, D-09.17, P05-MET-10).
-- Question: how much of what advanced is actually payable once credits are applied?
-- Needs 00_book.sql (ib_run, ib_facts). An OBLIGATION is an invoice with a policy-valid approval in the book at the as-of; a credit note
-- reduces the payable of an obligation, once per credit_id, by no more than the invoice total, and moves no cash. Credits against an
-- invoice that is not an obligation are not applied. MONEY IS PER CURRENCY: there is no dated conversion rate in the contract, so no
-- figure here adds one currency to another and no row carries a cross-currency total.

-- @@ payable_by_currency
WITH ob AS (
    SELECT i.invoice_id, i.currency, i.total FROM ib_facts f JOIN ib_run i ON i.c = f.c AND i.invoice_id = f.invoice_id
    WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z'
),
cr AS (SELECT o.currency, count(*) AS credit_notes, count(DISTINCT cn.invoice_id) AS invoices_credited, sum(cn.credit_amount) AS credit_total
       FROM credit_notes cn JOIN ob o ON o.invoice_id = cn.invoice_id WHERE cn.credited_at IS NULL OR cn.credited_at <= '2026-10-01T02:00:00Z' GROUP BY o.currency),
t AS (SELECT currency, count(*) AS obligations, sum(total) AS approved_total FROM ob GROUP BY currency)
SELECT t.currency, t.obligations, round(t.approved_total, 2) AS approved_total, coalesce(cr.credit_notes, 0) AS credit_notes,
       coalesce(cr.invoices_credited, 0) AS invoices_credited, round(coalesce(cr.credit_total, 0), 2) AS credit_total,
       round(t.approved_total - coalesce(cr.credit_total, 0), 2) AS approved_payable,
       round(coalesce(cr.credit_total, 0) / t.approved_total, 6) AS credit_share_of_approved_total
FROM t LEFT JOIN cr USING (currency) ORDER BY t.currency COLLATE "C";

-- @@ credit_share_of_invoices
-- "Credit share 4.0 %" is a share of INVOICES, not of approvals (D-09.17): the same 112 invoices are shown against both denominators.
SELECT 'invoices carrying at least one credit note' AS measure, count(DISTINCT invoice_id) AS n FROM credit_notes
UNION ALL SELECT 'credit notes', count(*) FROM credit_notes
UNION ALL SELECT 'invoices imported (denominator of the 4.0 % claim)', count(*) FROM invoices
UNION ALL SELECT 'obligations at the as-of (denominator of the 4.9 % reading)', count(*) FROM ib_facts WHERE kind = 'commit' AND c = '2026-10-01T02:00:00Z'
UNION ALL SELECT 'credit notes against an invoice that is not an obligation', count(*) FROM credit_notes cn
    WHERE NOT EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z' AND f.invoice_id = cn.invoice_id);

-- @@ credits_per_invoice
SELECT n_credits AS credit_notes_on_the_invoice, count(*) AS invoices FROM (SELECT invoice_id, count(*) AS n_credits FROM credit_notes GROUP BY invoice_id) z
GROUP BY n_credits ORDER BY n_credits;

-- @@ credit_size_by_currency
-- Cumulative credit as a share of the invoice total, per currency: the largest share must not pass 1 (a credit cannot exceed its invoice).
WITH c AS (
    SELECT i.currency, cn.invoice_id, sum(cn.credit_amount) AS credited, i.total
    FROM credit_notes cn JOIN ib_run i ON i.c = '2026-10-01T02:00:00Z' AND i.invoice_id = cn.invoice_id GROUP BY i.currency, cn.invoice_id, i.total
)
SELECT currency, count(*) AS invoices_credited, round(min(credited / total), 6) AS smallest_share, round(avg(credited / total), 6) AS mean_share,
       round(max(credited / total), 6) AS largest_share, count(*) FILTER (WHERE credited > total) AS credited_above_the_invoice_total
FROM c GROUP BY currency ORDER BY currency COLLATE "C";
