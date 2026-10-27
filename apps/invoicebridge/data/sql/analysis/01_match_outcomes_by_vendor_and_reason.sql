-- 01_match_outcomes_by_vendor_and_reason.sql: how the three-way match ends, by reason and by vendor, and what "open" means (P05-ART-04, D-03, D-09.10, D-09.17).
-- Question: which invoices may advance and which require exception review, and where do the reviews come from?
-- Needs 00_book.sql (ib_run: the book recomputed from facts at the main cutoff 2026-10-01T02:00:00Z) and the stored exception
-- history (`exceptions`: one row per (invoice, type), kept after it is resolved).
-- Two populations are kept apart in every block and named in the column:
--   OPEN AT THE CUTOFF = a reason the match still raises at 2026-10-01T02:00:00Z (recomputed from facts, ib_run.reasons);
--   EVER               = an exception of that type was raised at some point, resolved or not (the stored history).
-- Vendor groups are the generator's designed relationships (data/README-generator.md, manifest DR-01 and DR-02): ven-02x is
-- ven-020 .. ven-029, ven-007 is the price-list vendor. A group is a SQL label here, not a column of the schema.
-- Counts only, except by_currency: money is per currency and never summed across currencies.

-- @@ reason_open_vs_ever
WITH main AS (SELECT * FROM ib_run WHERE c = '2026-10-01T02:00:00Z'),
open_at AS (SELECT t AS reason, count(*) AS n FROM main, unnest(reasons) AS t GROUP BY t),
hist AS (SELECT exception_type AS reason, count(*) AS raised, count(*) FILTER (WHERE status = 'resolved') AS resolved,
                count(DISTINCT invoice_id) AS invoices FROM exceptions GROUP BY exception_type),
codes(ord, reason) AS (VALUES (1, 'QUANTITY_BLOCKED'), (2, 'PRICE_VARIANCE'), (3, 'NO_PO_LINE'), (4, 'ROUNDING_EXCEPTION'), (5, 'CURRENCY_MISMATCH'))
SELECT reason, open_at_cutoff, ever_raised, ever_resolved, ever_invoices, open_share_of_ever
FROM (
    SELECT c.ord, c.reason, coalesce(o.n, 0) AS open_at_cutoff, coalesce(h.raised, 0) AS ever_raised,
           coalesce(h.resolved, 0) AS ever_resolved, coalesce(h.invoices, 0) AS ever_invoices,
           CASE WHEN coalesce(h.raised, 0) = 0 THEN NULL ELSE round(coalesce(o.n, 0)::numeric / h.raised, 6) END AS open_share_of_ever
    FROM codes c LEFT JOIN open_at o USING (reason) LEFT JOIN hist h USING (reason)
    UNION ALL
    SELECT 99, 'ALL', (SELECT coalesce(sum(n), 0) FROM open_at), (SELECT coalesce(sum(raised), 0) FROM hist),
           (SELECT coalesce(sum(resolved), 0) FROM hist), (SELECT count(DISTINCT invoice_id) FROM exceptions),
           round((SELECT sum(n) FROM open_at)::numeric / (SELECT sum(raised) FROM hist), 6)
) z ORDER BY ord;

-- @@ vendor_group_open_vs_ever
-- Per vendor group and reason (QUANTITY_BLOCKED, PRICE_VARIANCE): the invoices in the book at the cutoff, those with the reason OPEN
-- at the cutoff and those that EVER had it (an open reason counts as ever; a rejected invoice is outside the book and outside both).
WITH main AS (SELECT * FROM ib_run WHERE c = '2026-10-01T02:00:00Z'),
grp AS (SELECT vendor_id, CASE WHEN vendor_id BETWEEN 'ven-020' AND 'ven-029' THEN 'ven-02x' WHEN vendor_id = 'ven-007' THEN 'ven-007'
                               ELSE 'other vendors' END AS vendor_group FROM vendors),
per AS (
    SELECT g.vendor_group, m.invoice_id,
           'QUANTITY_BLOCKED' = ANY(m.reasons) AS qb_open,
           'PRICE_VARIANCE' = ANY(m.reasons) AS pv_open,
           'QUANTITY_BLOCKED' = ANY(m.reasons) OR EXISTS (SELECT 1 FROM exceptions e WHERE e.invoice_id = m.invoice_id AND e.exception_type = 'QUANTITY_BLOCKED') AS qb_ever,
           'PRICE_VARIANCE' = ANY(m.reasons) OR EXISTS (SELECT 1 FROM exceptions e WHERE e.invoice_id = m.invoice_id AND e.exception_type = 'PRICE_VARIANCE') AS pv_ever
    FROM main m JOIN grp g ON g.vendor_id = m.vendor_id
)
SELECT vendor_group, count(*) AS invoices_in_book,
       count(*) FILTER (WHERE qb_open) AS quantity_blocked_open, round(count(*) FILTER (WHERE qb_open)::numeric / count(*), 6) AS quantity_blocked_open_rate,
       count(*) FILTER (WHERE qb_ever) AS quantity_blocked_ever, round(count(*) FILTER (WHERE qb_ever)::numeric / count(*), 6) AS quantity_blocked_ever_rate,
       count(*) FILTER (WHERE pv_open) AS price_variance_open, count(*) FILTER (WHERE pv_ever) AS price_variance_ever
FROM per GROUP BY vendor_group ORDER BY vendor_group COLLATE "C";

-- @@ by_vendor
SELECT v.vendor_id, v.currency,
       CASE WHEN v.vendor_id BETWEEN 'ven-020' AND 'ven-029' THEN 'ven-02x' WHEN v.vendor_id = 'ven-007' THEN 'ven-007' ELSE 'other vendors' END AS vendor_group,
       count(m.invoice_id) AS invoices_in_book,
       count(m.invoice_id) FILTER (WHERE m.matched) AS matched_at_cutoff,
       count(m.invoice_id) FILTER (WHERE NOT m.matched) AS with_open_exception,
       count(m.invoice_id) FILTER (WHERE m.matched AND EXISTS (SELECT 1 FROM exceptions e WHERE e.invoice_id = m.invoice_id)) AS matched_after_an_exception
FROM vendors v LEFT JOIN ib_run m ON m.vendor_id = v.vendor_id AND m.c = '2026-10-01T02:00:00Z'
GROUP BY v.vendor_id, v.currency ORDER BY v.vendor_id COLLATE "C";

-- @@ by_currency
-- Money of the matched invoices in each currency's own units (never summed across currencies).
SELECT currency, count(*) AS invoices_in_book, count(*) FILTER (WHERE matched) AS matched_at_cutoff,
       round(sum(total) FILTER (WHERE matched), 2) AS matched_total, count(*) FILTER (WHERE NOT matched) AS with_open_exception
FROM ib_run WHERE c = '2026-10-01T02:00:00Z' GROUP BY currency ORDER BY currency COLLATE "C";

-- @@ history_by_vendor_group
-- The same groups over ALL stored exception rows (resolved ones and those of invoices later rejected included), for the two designed reasons:
-- how many of the exception rows ever raised belong to the group, and how many of the open ones. Here the unit is the exception ROW, whereas
-- vendor_group_open_vs_ever counts the invoices still in the book, so the two answer different questions and are never quoted as one.
WITH main AS (SELECT * FROM ib_run WHERE c = '2026-10-01T02:00:00Z'),
grp AS (SELECT vendor_id, CASE WHEN vendor_id BETWEEN 'ven-020' AND 'ven-029' THEN 'ven-02x' WHEN vendor_id = 'ven-007' THEN 'ven-007'
                               ELSE 'other vendors' END AS vendor_group FROM vendors),
ever AS (SELECT g.vendor_group, e.exception_type AS reason, count(*) AS raised, count(DISTINCT e.invoice_id) AS invoices
         FROM exceptions e JOIN invoices i USING (invoice_id) JOIN grp g ON g.vendor_id = i.vendor_id
         WHERE e.exception_type IN ('QUANTITY_BLOCKED', 'PRICE_VARIANCE') GROUP BY 1, 2),
open_at AS (SELECT g.vendor_group, t AS reason, count(*) AS n FROM main m JOIN grp g ON g.vendor_id = m.vendor_id, unnest(m.reasons) AS t
            WHERE t IN ('QUANTITY_BLOCKED', 'PRICE_VARIANCE') GROUP BY 1, 2)
SELECT e.vendor_group, e.reason, e.raised AS ever_raised_rows, e.invoices AS ever_raised_invoices, coalesce(o.n, 0) AS open_at_cutoff
FROM ever e LEFT JOIN open_at o USING (vendor_group, reason) ORDER BY e.reason COLLATE "C", e.vendor_group COLLATE "C";

-- @@ rates_by_currency
-- Per currency: the invoices in the book, those blocked at the cutoff, those EVER excepted (blocked now or in the stored history) and the two rates
-- the contract publishes (straight-through = not blocked at the cutoff, D-09.10) beside the never-excepted rate. Rates are 6 dp.
WITH main AS (SELECT * FROM ib_run WHERE c = '2026-10-01T02:00:00Z'),
f AS (SELECT m.currency, m.invoice_id, cardinality(m.reasons) > 0 AS blocked,
             (cardinality(m.reasons) > 0 OR EXISTS (SELECT 1 FROM exceptions e WHERE e.invoice_id = m.invoice_id)) AS ever FROM main m)
SELECT currency, count(*) AS invoices_in_book, count(*) FILTER (WHERE blocked) AS blocked_at_cutoff, count(*) FILTER (WHERE ever) AS ever_excepted,
       round(count(*) FILTER (WHERE NOT blocked)::numeric / count(*), 6) AS straight_through_rate,
       round(count(*) FILTER (WHERE NOT ever)::numeric / count(*), 6) AS never_excepted_rate
FROM f GROUP BY currency ORDER BY currency COLLATE "C";
