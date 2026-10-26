# Revenue Atlas — business case (P01-ART-01)

**Status of every stakeholder, interview and number in this document: simulated.** The
company, its people and its figures are synthetic; nothing here is a claim about a real
employer, real revenue or real savings (master 10).

## Business problem
A mid-sized distributor ("Northfield Supply", synthetic) sells 36 products in 6 categories
to 48 customers across 4 sales regions. Over the last three quarters contribution margin has
fallen while gross sales held steady. Month-end reviews argue from spreadsheets with
different populations (bookings vs shipments, credits dated by shipment vs by credit date,
freight sometimes double-counted after a join), so the review cannot say *which* customer,
product, region or discount policy explains the decline. Revenue Atlas supports exactly that
decision (P01-GOAL-01).

## Simulated stakeholders
| Role (simulated) | Need | Decision criterion |
|---|---|---|
| VP Sales | Know whether the West region's discount policy change is the cause | Discount rate and contribution by region, same population and window |
| Finance controller | A margin bridge that reconciles to the shipment ledger to the cent | Allocation residual 0.00; every bridge step a contract metric |
| Category manager | Whether fixtures' cost rises were passed to price | COGS at historical cost versus unit price by category and month |
| Returns lead | Whether returns are concentrated and mature enough to judge | Return rate by cohort with maturity disclosed |
| Analyst (primary user) | Drill from a trend to the transactions that make it | Overview → segment → transaction evidence, scope visible at every step |

## Scope and non-goals
In scope: shipment-date operational sales, historical unit cost, discounts, credits for
returns, order freight allocation, dated FX, regional attribution with an explicit UNASSIGNED
bucket, quota attainment at period grain, discount and freight what-if scenarios on a copy of
the baseline, exports with embedded filters and versions, a published static snapshot.
Out of scope: revenue recognition, invoicing, cash, taxes, commissions, real-time feeds,
multi-user persistence on the public site, any LLM at runtime (P01-DOMAIN-01/02, GOAL-11).

## Current-state process (simulated)
1. Sales ops exports orders and shipments monthly; finance exports credits and freight.
2. An analyst joins them in a workbook; freight is joined at order level to line rows and
   is double counted whenever an order has several lines (the P01-TEST-01 failure).
3. Credits are netted in the month of the original shipment, so closed months move.
4. Regional totals exclude customers with no territory, so the regions do not add up to
   the company total.
5. Conclusions are debated for a week; no decision is recorded with its evidence.

## Future-state process
1. C01 ingests a batch, rejects malformed rows and keeps the raw rows with reasons.
2. C02 resolves exactly one cost version per shipped line; C04 allocates freight once per
   shipment line with a zero residual; C03 posts returns against remaining quantity.
3. The analyst reads the overview, opens the margin bridge, drills to a segment and then
   to the transaction ledger (C05), compares regions including UNASSIGNED (C06).
4. A scenario (C07/C08) estimates the effect of reversing the discount policy on a copy
   of the baseline; the scenario is labelled an estimate, never mixed with actuals.
5. C09 exports the findings with filters, contract version, dataset hash and timestamp;
   C10 publishes the verified snapshot with source and build hashes.
Exceptions and ownership: quarantined lines (missing FX, ambiguous cost) are owned by the
data steward and shown as counts on every screen; rejected returns are owned by the returns
lead; residual freight that cannot be allocated is owned by finance and stays visible.

## Decision criteria for the recommendation (executive memo, P01-ART-07)
A cause is "explained" when, on the same population and half-open window, removing it in a
scenario recovers at least half of the contribution decline, and the transaction evidence for
that segment reconciles to the bridge to the cent. Uncertainty from synthetic design is
disclosed: the generator's injected relationships are listed in `data/injection-manifest.json`
so the reader can see that the site finds what was designed in and nothing more.
