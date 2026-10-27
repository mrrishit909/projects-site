-- bi_dimensions.sql: the dimension tables of the BI package, exported as CSV by run_all.py --bi-out (P05-ART-06, docs/bi-package.md).
-- Needs only the facts (no 00_book.sql). One row per member; the surrogate key is the natural key.

-- @@ dim_vendor
SELECT vendor_id, vendor_name, currency, active::int AS active,
       CASE WHEN vendor_id BETWEEN 'ven-020' AND 'ven-029' THEN 'ven-02x' WHEN vendor_id = 'ven-007' THEN 'ven-007' ELSE 'other vendors' END AS vendor_group
FROM vendors ORDER BY vendor_id COLLATE "C";

-- @@ dim_date
SELECT to_char(d, 'YYYYMMDD')::int AS date_key, to_char(d, 'YYYY-MM-DD') AS date, extract(year FROM d)::int AS year, extract(month FROM d)::int AS month,
       to_char(d, 'YYYY-MM') AS year_month, extract(isodow FROM d)::int AS iso_weekday,
       (((date_trunc('month', d) + interval '1 month - 1 day')::date - d::date) <= 2)::int AS in_last_three_days_of_month
FROM generate_series('2025-10-01'::date, '2026-10-01'::date, interval '1 day') AS g(d) ORDER BY 1;

-- @@ dim_currency
SELECT currency, 'no dated conversion rate exists: money is reported per currency and never summed across currencies' AS note
FROM (SELECT DISTINCT currency FROM vendors) v ORDER BY currency COLLATE "C";

-- @@ dim_policy
SELECT policy_id, version_number, amount_limit, reviewer_role, coalesce(escalation_role, '') AS escalation_role, to_char(effective_from AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS effective_from
FROM approval_policies ORDER BY version_number;

-- @@ dim_reason
SELECT reason_code, description FROM (VALUES
    (1, 'QUANTITY_BLOCKED', 'the invoiced quantity exceeds what was received and not yet invoiced'),
    (2, 'PRICE_VARIANCE', 'the invoiced unit price differs from the purchase-order price beyond the tolerance'),
    (3, 'NO_PO_LINE', 'the invoice line names no purchase-order line of this vendor'),
    (4, 'ROUNDING_EXCEPTION', 'the declared total or a line amount differs from the computed one beyond the tolerance'),
    (5, 'CURRENCY_MISMATCH', 'the invoice currency differs from the purchase-order currency and no dated rate exists')) AS t(ord, reason_code, description) ORDER BY ord;
