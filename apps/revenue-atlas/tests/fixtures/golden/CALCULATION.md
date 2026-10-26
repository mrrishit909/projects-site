# Revenue Atlas golden calculation (contract v1)

Independent of application code. `../../reference_check.py` recomputes every number below from `inputs.json`
and compares it with `expected.json`. Money is compared exactly at 2 decimal places, rates exactly at 6.

## The spec sentence [P01-GOLD-01]

> Two shipped lines: 2 units at $100 with $20 total discount and $60 unit cost; 1 unit at $50 with $5 discount and $20 unit cost.
> Net merchandise sales=$225; COGS=$140; gross profit=$85. Shipping cost=$15, no shipping revenue or other variable costs:
> contribution=$70. Freight weights by gross sales are 200/250 and 50/250, giving $12 and $3. Returning one first-line unit
> credits $90 and reverses $60 cost; after unchanged freight contribution=$40.

Records: one order `ord-001`, lines `line-001` (2 x 100.00, discount 20.00, cost 60.00) and `line-002` (1 x 50.00,
discount 5.00, cost 20.00), one shipment `shp-001` (shipping cost 15.00) with shipment lines `sl-001` and `sl-002`,
fully shipped, one return `ret-001` (1 unit of `sl-001`, posted credit 90.00). Currency USD, FX 1.0.

## Baseline (before the return)

| Step | Arithmetic | Result |
|---|---|---|
| Gross sales | 2 x 100.00 + 1 x 50.00 = 200.00 + 50.00 | **250.00** |
| Allocated discounts | 20.00 x 2/2 + 5.00 x 1/1 = 20.00 + 5.00 | **25.00** |
| Merchandise credits | no return in this state | **0.00** |
| Net merchandise sales | 250.00 - 25.00 - 0.00 | **225.00** |
| COGS | 2 x 60.00 + 1 x 20.00 = 120.00 + 20.00, less recoverable return cost 0.00 | **140.00** |
| Gross profit | 225.00 - 140.00 | **85.00** |
| Freight weights | 200/250 and 50/250 (gross sales of sl-001, sl-002) | |
| Freight sl-001 | 15.00 x 200/250 = 12.00 | **12.00** |
| Freight sl-002 | 15.00 x 50/250 = 3.00 | **3.00** |
| Allocation residual | 15.00 - (12.00 + 3.00) | **0.00** |
| Contribution margin | 85.00 + 0.00 shipping revenue - 15.00 shipping cost - 0.00 other | **70.00** |
| Eligible net revenue | 225.00 + 0.00 shipping revenue | 225.00 |
| Contribution margin rate | 70.00 / 225.00 = 0.3111... | **0.311111** |
| Discount rate | 25.00 / 250.00 | **0.100000** |
| Return rate | 0 / 3 units | **0.000000** |
| Average order value | 225.00 / 1 distinct order | **225.00** |

## After the return of one first-line unit

The posted credit must equal returned_quantity x (unit_price - allocated_discount / shipped_quantity):
1 x (100.00 - 20.00 / 2) = 1 x 90.00 = **90.00**, which matches `ret-001`. Recoverable return cost is
returned_quantity x unit cost of the line's cost version: 1 x 60.00 = **60.00**.

| Step | Arithmetic | Result |
|---|---|---|
| Gross sales, discounts | unchanged | 250.00, 25.00 |
| Merchandise credits | 90.00 | **90.00** |
| Net merchandise sales | 250.00 - 25.00 - 90.00 | **135.00** |
| COGS | 140.00 - 60.00 | **80.00** |
| Gross profit | 135.00 - 80.00 | **55.00** |
| Freight | unchanged: 12.00 and 3.00, residual 0.00 | 12.00 / 3.00 |
| Contribution margin | 55.00 + 0.00 - 15.00 - 0.00 | **40.00** |
| Contribution margin rate | 40.00 / 135.00 = 0.2962... | **0.296296** |
| Discount rate | 25.00 / 250.00 | **0.100000** |
| Return rate | 1 / 3 units | **0.333333** |
| Average order value | 135.00 / 1 distinct order | **135.00** |

## Rejected-record variant [P01-GOLD-08] (`variant-rejected/`)

The golden inputs plus order `ord-002` with currency `"US$"`, its line `line-003` (1 x 50.00), shipment `shp-002`
(shipping cost 4.00) and shipment line `sl-003`. `US$` is not a three-letter ISO-4217 code, so no `exchange_rates`
row can convert the order's amounts. Including the 50.00 line and 4.00 freight would put unconvertible money into
the totals, so the order and its dependents are rejected at ingest with reason `CURRENCY_NOT_ISO4217` and their raw
rows preserved. Accepted counts equal the golden counts, rejected counts are orders 1, order_lines 1, shipments 1,
shipment_lines 1, quarantined 0, and every total equals the golden baseline (gross 250.00, contribution 70.00).
Rejection is correct because the alternative is a wrong total; the golden numbers prove nothing leaked in.

## Empty-population variant [P01-GOLD-09] (`variant-empty/`)

Customers, products, cost versions and the FX row exist, but there are no orders, shipments or lines.
All sums are 0.00, allocation residual is 0.00, eligible orders/lines/units are 0. Every ratio has a zero
denominator and is **null** (not 0, not an error): contribution margin rate (eligible net revenue 0.00),
discount rate (eligible gross sales 0.00), return rate (shipped units 0), average order value (0 orders).
`empty_population` is `true`.

## Rounding and tolerance [P01-GOLD-05]

No tolerance band: money is compared for exact equality at 2 decimal places and rates at 6 decimal places
(round half up), using `decimal.Decimal`, never binary floats.
