-- 04: supplier on-time rate by supplier and RECEIPT month, with no future leakage (P03-MET-11, P03-FLOW-09, P03-TEST-05,
-- contract D-04). promised date = order date (UTC) + quoted lead days counted on the supplier calendar: days inside a
-- calendar_closures range do not count. A receipt is on time when its UTC date <= the promised date. Month m uses only
-- receipts dated inside m. cum_* uses only receipts dated up to that month-end (the as-of view a buyer had then). A receipt
-- dated after a cutoff is never read for that cutoff. overdue_open_lines = lines of orders placed by the cutoff, promised on or
-- before the cutoff, not yet fully received by it (neither on time nor late yet: censored, reported beside the rate).
-- A row 'ALL' per supplier is the whole history. Rates are rounded half up at 6 dp, blank when no receipt is eligible.
WITH months AS (
    SELECT to_char(m, 'YYYY-MM') AS month, (m AT TIME ZONE 'UTC') AS m_start,
           ((m + interval '1 month') AT TIME ZONE 'UTC') - interval '1 second' AS as_of
      FROM generate_series(timestamp '2025-04-01', timestamp '2026-09-01', interval '1 month') AS m
), promised AS (
    SELECT o.purchase_order_id, o.supplier_id, o.ordered_at, o.status,
           (SELECT x.d FROM (SELECT ((o.ordered_at AT TIME ZONE 'UTC')::date + g) AS d, row_number() OVER (ORDER BY g) AS n
                               FROM generate_series(1, 200) AS g
                              WHERE NOT EXISTS (SELECT 1 FROM calendar_closures c
                                                 WHERE c.calendar_id = s.calendar_id
                                                   AND ((o.ordered_at AT TIME ZONE 'UTC')::date + g) BETWEEN c.closed_from AND c.closed_to)) x
             WHERE x.n = s.quoted_lead_days) AS promised_date
      FROM purchase_orders o JOIN suppliers s ON s.supplier_id = o.supplier_id
), rcpt AS (
    SELECT p.supplier_id, r.received_at, r.po_line_id,
           (r.received_at AT TIME ZONE 'UTC')::date <= p.promised_date AS on_time
      FROM receipts r
      JOIN purchase_order_lines l ON l.po_line_id = r.po_line_id
      JOIN promised p ON p.purchase_order_id = l.purchase_order_id
), per AS (
    SELECT s.supplier_id, m.month, m.m_start, m.as_of,
           count(r.*) FILTER (WHERE r.received_at >= m.m_start AND r.received_at <= m.as_of) AS elig,
           count(r.*) FILTER (WHERE r.received_at >= m.m_start AND r.received_at <= m.as_of AND r.on_time) AS ontime,
           count(r.*) FILTER (WHERE r.received_at <= m.as_of) AS cum_elig,
           count(r.*) FILTER (WHERE r.received_at <= m.as_of AND r.on_time) AS cum_ontime
      FROM suppliers s CROSS JOIN months m LEFT JOIN rcpt r ON r.supplier_id = s.supplier_id
     GROUP BY s.supplier_id, m.month, m.m_start, m.as_of
), overdue AS (
    SELECT m.month, p.supplier_id, count(*) AS n
      FROM months m
      JOIN promised p ON p.ordered_at <= m.as_of AND p.status <> 'cancelled' AND p.promised_date <= (m.as_of AT TIME ZONE 'UTC')::date
      JOIN purchase_order_lines l ON l.purchase_order_id = p.purchase_order_id
     WHERE l.ordered_quantity > COALESCE((SELECT sum(r.received_quantity) FROM receipts r
                                           WHERE r.po_line_id = l.po_line_id AND r.received_at <= m.as_of), 0)
     GROUP BY m.month, p.supplier_id
)
SELECT per.supplier_id, per.month, per.elig::int AS eligible_receipts, per.ontime::int AS on_time_receipts,
       round(per.ontime::numeric / NULLIF(per.elig, 0), 6) AS on_time_rate,
       per.cum_elig::int AS cum_eligible, round(per.cum_ontime::numeric / NULLIF(per.cum_elig, 0), 6) AS cum_on_time_rate,
       COALESCE(od.n, 0)::int AS overdue_open_lines
  FROM per LEFT JOIN overdue od ON od.month = per.month AND od.supplier_id = per.supplier_id
UNION ALL
SELECT supplier_id, 'ALL', count(*)::int, count(*) FILTER (WHERE on_time)::int,
       round(count(*) FILTER (WHERE on_time)::numeric / NULLIF(count(*), 0), 6), count(*)::int,
       round(count(*) FILTER (WHERE on_time)::numeric / NULLIF(count(*), 0), 6), NULL
  FROM rcpt GROUP BY supplier_id
 ORDER BY supplier_id, month;
