# SupplyScope golden calculation (contract v1, decisions D-01..D-05)

Independent of application code. `../../reference_check.py` recomputes every number below from `inputs.json`
and compares it with `expected.json`. Units are exact integers, money 2 decimal places, rates 6 decimal places.

## The spec sentences [P03-GOLD-01]

> On hand=40, on order=30, backorders=10 gives inventory position=60 under the declared no-reservation fixture.
> Reorder point=70 and target position=120 gives raw order=60. MOQ=50 and pack size=24 produces an order of 72 units.
> If position=80, no order is triggered.

Records: prod-001 (SKU-001, unit_cost 12.50, pack_size 24, MOQ 50), loc-001, sup-001, po-001 (confirmed, ordered
2026-03-20) with line pol-001 (30 units, no receipts), replenishment_params rp (ROP 70, target 120), reservations empty.
As of `2026-03-31T23:59:59Z`; observation window 2026-03-01 to 2026-03-31 (31 days).

## Ledger as of the cutoff (D-01)

Day order within a date: receipts, then demand, then review. The 2026-04-02 movement is after the cutoff and excluded.

| Date | Movement | Delta | Running stock |
|---|---|---|---|
| 03-01 | mv-001 receipt | +60 | 60 |
| 03-05 | mv-002 sale | -25 | 35 |
| 03-11 | mv-003 sale | -35 | 0 |
| 03-12 | mv-005 receipt (15:00), applied first | +35 | 35 |
| 03-12 | mv-004 sale (09:00), applied second | -35 | 0 |
| 03-16 | mv-006 receipt | +40 | 40 |
| 04-02 | mv-007 sale | -10 | excluded (after as_of) |

Receipts 60+35+40 = 135; sales 25+35+35 = 95; **on hand = 135 - 95 = 40**.

Day-order check: on 2026-03-12 the sale is stamped 09:00 and the receipt 15:00. Applied by timestamp the stock would
reach 0 - 35 = -35 (`timestamp_order_stock_min` = -35, a NEGATIVE_STOCK artefact). Applied receipt first then sale
(D-01) it goes 0 -> 35 -> 0, so `running_stock_min` = 0 and `negative_stock` = false.

## Position and replenishment (D-01, D-02)

| Quantity | Arithmetic | golden | position_80 |
|---|---|---|---|
| on order | sum(ordered - received) over confirmed lines: pol-001 30 - 0 | 30 | 30 + pol-002 (20 - 0) = 50 |
| backorders open at cutoff | bo-002 10 (bo-001 closed 03-13) | 10 | 10 |
| reserved / available | 0 / 40 - 0 | 0 / 40 | 0 / 40 |
| inventory position | 40 + on order - 10 (reserved not subtracted) | 60 | 80 |
| triggered | position < ROP 70 | true (60 < 70) | false (80 >= 70) |
| raw order | target 120 - position | 60 | 0 (not triggered) |
| after MOQ | max(raw 60, MOQ 50) | 60 | 0 |
| order quantity | ceil(60 / 24) x 24 = 3 x 24 | 72 | 0 |

## Working capital (D-05)

on hand 40 x unit_cost 12.50 = **500.00** (both states).

## Fill rate and stockout days (D-04)

Sales in the window (sale-001..003): 25 + 35 + 35 = 95 fulfilled immediately. Unmet demand = backorders opened in the
window: bo-001, 5 units, opened 03-12 (the sale that day was 35 of 40 requested). bo-002 (10 units) opened 2026-02-27,
before the window, so it is a position input but not window demand. Requested = 95 + 5 = 100.

* fill_rate = 95 / 100 = **0.950000**
* days with unmet demand = 1 (03-12); observed days = 31; stockout_days = 1 / 31 = 0.0322580645... = **0.032258**

## Variants

* variant-rejected: mv-002 is replayed with an identical payload (second occurrence rejected DUPLICATE_MOVEMENT_ID, first
  kept) and rcpt-001 (30 units of pol-001) is dated 2026-03-18, before po-001 ordered_at 2026-03-20 (RECEIPT_BEFORE_ORDER).
  Raw rows are preserved in `rejected_records`. Because the receipt is rejected, pol-001 stays fully open (on order 30);
  every state equals the golden states.
* variant-empty: products, locations, suppliers only. on hand 0, on order 0, position 0, working capital 0.00,
  empty_population true, fill_rate and stockout_days null (no population). With no replenishment_params the order is
  not evaluated: reorder_point, target_position, reorder_triggered, raw_order, order_after_moq, order_quantity are null
  (not false / 0).

## Assumptions

Stockout day = a date on which a backorder opened (unmet demand). Movements of type receipt with no receipts row are
earlier-order receipts outside the fixture's PO set; the receipts table only holds receipts against po-001 lines.
