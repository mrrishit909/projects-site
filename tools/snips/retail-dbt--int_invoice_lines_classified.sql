-- Every line gets exactly one type, so each mart can say which lines it counts.
with lines as (
    select * from {{ ref('stg_invoice_lines') }}
),

kinds as (
    select * from {{ ref('stock_code_kinds') }}
)

select
    lines.*,
    case
        when regexp_matches(lines.stock_code, '^[0-9]{5}') or lines.stock_code like 'DCGS%' then 'product'
        else kinds.kind
    end as stock_kind,
    case
        when lines.invoice like 'A%'                            then 'bad_debt_adjustment'
        when lines.invoice like 'C%'                            then 'cancellation'
        when stock_kind <> 'product'                            then 'non_product'
        when lines.quantity > 0 and lines.unit_price > 0        then 'sale'
        else 'stock_adjustment'     -- zero price or negative quantity on a normal invoice: damaged, lost, samples
    end as line_type
from lines
left join kinds on lines.stock_code = kinds.stock_code
