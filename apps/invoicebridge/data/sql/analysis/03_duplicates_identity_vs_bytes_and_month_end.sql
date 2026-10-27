-- 03_duplicates_identity_vs_bytes_and_month_end.sql: duplicates by identity and by bytes, and when the re-sent files arrive (P05-ART-04, D-01, D-05, D-06.4, D-09.3).
-- Question: which invoices must be merged rather than paid twice, and is it safe to treat a repeated invoice number as a duplicate?
-- Needs 00_book.sql (ib_facts: the duplicate merges recomputed from facts per cutoff; the main cutoff is 2026-10-01T02:00:00Z).
-- Identity = vendor, the invoice number upper-cased with only letters and digits kept, the invoice date and the COMPUTED total;
-- the same source bytes (sha256) are checked first. A merged invoice keeps its lineage row and its source hash and consumes nothing.
-- "Month-end" is the last three calendar days (UTC) of the month of `imported_at`.

-- @@ merges_by_reason_and_cutoff
SELECT c AS cutoff, code AS reason_code, count(*) AS rows_merged, count(DISTINCT ref) AS canonical_invoices
FROM ib_facts WHERE kind = 'merged' GROUP BY c, code ORDER BY c, code COLLATE "C";

-- @@ identity_vs_bytes
-- Each merged row against its canonical copy at the main cutoff: are the bytes equal, the file names equal, how long after the canonical
-- was the copy imported (days, 4 dp), and do both belong to the same vendor.
SELECT f.code AS reason_code, count(*) AS rows_merged,
       count(*) FILTER (WHERE d.source_sha256 = k.source_sha256) AS same_source_bytes,
       count(*) FILTER (WHERE d.source_filename = k.source_filename) AS same_file_name,
       count(*) FILTER (WHERE d.vendor_id = k.vendor_id) AS same_vendor,
       round(avg(extract(epoch FROM (d.imported_at - k.imported_at)) / 86400)::numeric, 4) AS mean_days_after_canonical
FROM ib_facts f JOIN invoices d ON d.invoice_id = f.invoice_id JOIN invoices k ON k.invoice_id = f.ref
WHERE f.kind = 'merged' AND f.c = '2026-10-01T02:00:00Z' GROUP BY f.code ORDER BY f.code COLLATE "C";

-- @@ month_end_clustering
-- Of the invoices merged by identity (the re-sent PDFs: other bytes, same identity) and of all imported invoices: how many were imported in
-- the last three days of a month. An invoice is month-end when its UTC import date is within two days of the last day of its month.
WITH t AS (
    SELECT i.invoice_id,
           ((date_trunc('month', i.imported_at AT TIME ZONE 'UTC') + interval '1 month - 1 day')::date - (i.imported_at AT TIME ZONE 'UTC')::date) <= 2 AS month_end,
           f.code IS NOT NULL AS merged_identity
    FROM invoices i LEFT JOIN ib_facts f ON f.kind = 'merged' AND f.c = '2026-10-01T02:00:00Z' AND f.invoice_id = i.invoice_id AND f.code = 'DUPLICATE_IDENTITY'
)
SELECT 'merged by identity (re-sent PDFs)' AS population, count(*) AS invoices, count(*) FILTER (WHERE month_end) AS imported_in_last_three_days,
       round(count(*) FILTER (WHERE month_end)::numeric / count(*), 4) AS share
FROM t WHERE merged_identity
UNION ALL
SELECT 'all invoices', count(*), count(*) FILTER (WHERE month_end), round(count(*) FILTER (WHERE month_end)::numeric / count(*), 4) FROM t
UNION ALL
SELECT 'invoices that are not re-sent copies', count(*), count(*) FILTER (WHERE month_end), round(count(*) FILTER (WHERE month_end)::numeric / count(*), 4) FROM t WHERE NOT merged_identity;

-- @@ merged_by_import_month
SELECT to_char(i.imported_at AT TIME ZONE 'UTC', 'YYYY-MM') AS import_month, count(*) AS rows_merged_by_identity,
       count(*) FILTER (WHERE ((date_trunc('month', i.imported_at AT TIME ZONE 'UTC') + interval '1 month - 1 day')::date - (i.imported_at AT TIME ZONE 'UTC')::date) <= 2) AS in_last_three_days
FROM ib_facts f JOIN invoices i ON i.invoice_id = f.invoice_id
WHERE f.kind = 'merged' AND f.c = '2026-10-01T02:00:00Z' AND f.code = 'DUPLICATE_IDENTITY'
GROUP BY 1 ORDER BY 1;

-- @@ same_number_other_vendor
-- A repeated invoice number is not a duplicate when the vendor differs (D-01): normalised numbers shared by invoices of more than one vendor,
-- and whether either was merged. (The generator's INJ-02: four pairs, two differing only in case.)
WITH n AS (
    SELECT regexp_replace(upper(invoice_number), '[^A-Z0-9]', '', 'g') AS number_norm, invoice_id, vendor_id
    FROM invoices
),
g AS (SELECT number_norm FROM n GROUP BY number_norm HAVING count(DISTINCT vendor_id) > 1)
SELECT n.number_norm, count(*) AS invoices, count(DISTINCT n.vendor_id) AS vendors,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'merged' AND f.c = '2026-10-01T02:00:00Z' AND f.invoice_id = n.invoice_id)) AS merged_rows
FROM n JOIN g USING (number_norm) GROUP BY n.number_norm ORDER BY n.number_norm COLLATE "C";

-- @@ lineage_append_only
-- The import lineage keeps one row per accepted import, merged ones included (D-01, 0002 forbids UPDATE and DELETE on it).
SELECT import_status, coalesce(reason_code, '') AS reason_code, count(*) AS lineage_rows, count(DISTINCT invoice_id) AS invoices
FROM import_lineage GROUP BY import_status, coalesce(reason_code, '') ORDER BY import_status COLLATE "C", coalesce(reason_code, '') COLLATE "C";
