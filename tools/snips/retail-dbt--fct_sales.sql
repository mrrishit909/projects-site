-- Product sales only: what customers actually bought (no postage, fees, cancellations or adjustments).
select
    line_id,
    invoice,
    invoiced_at,
    cast(date_trunc('month', invoiced_at) as date) as invoice_month,
    customer_id,
    country,
    stock_code,
    description,
    quantity,
    unit_price,
    line_amount as revenue
from {{ ref('int_invoice_lines_classified') }}
where line_type = 'sale'
