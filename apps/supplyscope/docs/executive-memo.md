# Executive memo: what to order, when, and under which assumptions (P03-ART-07)

**Synthetic.** "Northgate Components", its 60 SKUs, three locations and four suppliers are generated (seed 20261026, snapshot `ss-20261026-20261026`, hash `5bdabb50...bcc8c`). Nothing below is a measured effect on a real business: **no real savings, revenue, service or adoption are claimed**, and the relationships the data shows were designed into it (`web/public/data/manifest.json`). Query names are the files of `data/sql/analysis/` (`sql-analysis.md`); P03 ids are in `requirements.md`.

## Decision
Question (P03-GOAL-01): what should be ordered, when, and under which service and working-capital assumptions?

**Order the two triggered class A SKUs at `loc-02`, prod-005 first, after a capacity check.** At the snapshot cutoff 2026-09-30 23:59:59Z the draft buying plan (query 02, parameters of record, contract D-02) is:

| SKU | Supplier (quoted lead) | On hand | On order | Position | Reorder point | Target | Raw | MOQ | Packs x pack size | Order | Value at cost in force |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `prod-005` | `sup-01` (5 days) | 0 | 48 | 48 | 51 | 144 | 96 | 24 | 8 x 12 | 96 | 5104.32 |
| `prod-002` | `sup-02` (12 days) | 70 | 48 | 118 | 128 | 252 | 134 | 24 | 12 x 12 | 144 | 6010.56 |
| total | | 1020 | 608 | 1628 | | | 230 | | | 240 | 11114.88 |

*When:* at the next weekly buying meeting after the cutoff; arrival is promised 5 and 12 supplier-calendar days after the order date (closed days do not count; the only closure in the data, `cal-02` 2026-01-05 .. 2026-01-18, is in the past). `prod-005` first: its on-hand is 0 and it has 82 stockout days in the history (query 05).
*Assumptions of the plan:* service level of the parameters of record (the generator used z = 1.28, about a 0.90 target); unmet demand at `loc-02` is a lost sale; working capital is valued at the cost in force; reserved stock (6 open reservations, 123 units) is not subtracted from the position (P03-TEST-10); orders are confirmed lines only (D-01).
*Capital:* the plan adds 11114.88 at cost, 38.2 % of the working capital of 29090.64 at the cutoff (query 06), a figure of a synthetic ledger, not a budget.
*Capacity:* `loc-02` is already at 103.7 % of its storage capacity counting on hand and on order (582 against 561, query 01), and the contract's order arithmetic has no capacity rule. The plan is therefore a recommendation row to be checked against space, not an instruction.

## Evidence
| What | Number | Query |
|---|---|---|
| The plan reconciles to the ledger | position = on hand + on order - backorders = 1020 + 608 - 0 = 1628; the same from `reference_metrics.sql` and the domain; each of the 60 rows equals the domain's `replenish` | 02, run_all |
| The arithmetic is the golden one | on hand 40, on order 30, backorders 10, position 60; raw 60, MOQ 60, pack 72; position 80 gives 0, from three sources | 09 and `sql-analysis.md` section 10 |
| `loc-02` serves its class A SKUs worst | fill rate 0.877842 (overall 0.932486; `loc-01` 0.964655, `loc-03` 0.955627); 205 stockout SKU-days of 1,644 (12.47 %) | 03 |
| Both SKUs have stocked out a lot | stockout days 82 (`prod-005`) and 74 (`prod-002`) of 548 | 05 |
| Sales understate demand on those days | observed sales are 25.4 % (`prod-005`) and 21.8 % (`prod-002`) of the latent demand on stockout days; 2,423 units of latent demand were not seen across the 8 class A SKUs, equal to the recorded unmet demand | 05 |
| `sup-03` is the unreliable supplier | on-time 0.681102 (173 of 254) against 0.829412 (`sup-01`), 0.864943 (`sup-02`), 0.841530 (`sup-04`); computed from receipts dated up to each cutoff only | 04 |
| Cost step | the 2026-02-01 step (+6 % on 15 `sup-04` products) adds 210.95 to the 21881.18 average daily inventory value; valuing at one cost would hide it | 06 |
| Forecasts beat their baseline where there is volume | `ewma` beats seasonal-naive for all 8 class A SKUs (WAPE 0.447020 to 0.629220) and 11 of 14 SKUs; no point uses the future | 07 |
| Data problems are found, not hidden | 4 rows rejected (3 duplicate movements, 1 receipt before its order); 2 closed orders with a partly received line, 8 receipts spanning a closure, 6 open reservations detected | 08 |

## Options
**1. Service target 0.90 against 0.95.** The parameters of record correspond to about 0.90. The plan if the domain instead derives reorder point and target from the forecast (the path C05 uses when a SKU has no parameter row) is much smaller, and the target changes which SKUs trigger (`options.py`, `sql-analysis.md` section 11):

| Option | Triggered pairs | Class A triggered | Order units | Order value |
|---|---|---|---|---|
| Parameters of record (z 1.28, about 0.90) | 2 | 2 | 240 | 11114.88 |
| Derived from the forecast at 0.90 | 7 | 0 | 88 | 1457.40 |
| Derived from the forecast at 0.95 | 9 | 1 | 154 | 4707.66 |

Moving the derived plan from 0.90 to 0.95 adds 2 triggered pairs, 66 units and 3250.26 of order value. The two families of parameters disagree by a wide margin (for `prod-002` the derived reorder point is 99 at 0.90 and 107 at 0.95 against 128 of record), so the choice of service target cannot be settled from this data without settling how reorder parameters are set first.

**2. Lost sale against backlog.** `loc-03` is the only backlog location. On common random numbers (stored scenarios `sc-95-lost` and `sc-95-backlog`, seed 20261026, warm-up 28 days, 100 replications, 180 days) the simulated direction for the two SKUs is the same: lost sale gives the higher fill rate and the lower stockout-day share, because in the simulation owed units are served from arrivals first, which uses stock that would have met new demand immediately, and the owed units lower the position.

| SKU | Policy | Fill rate | Stockout-day share |
|---|---|---|---|
| `prod-002` | lost_sale | 0.9119 | 0.1009 |
| `prod-002` | backlog | 0.9038 | 0.1115 |
| `prod-005` | lost_sale | 0.8979 | 0.1142 |
| `prod-005` | backlog | 0.8876 | 0.1286 |

The difference is about one percentage point of fill rate. It is a simulated direction with its seed and warm-up printed, not a realised effect; the unmet-demand policy is a business policy (whether late fulfilment is acceptable to the customer), not something the simulation can choose.

## Uncertainty
* One seed, one dataset: there are no confidence intervals beyond the 100 replications of the simulation, and the simulation is a compact (s, S) loop whose statistical quality was not assessed.
* Two SKUs trigger at the cutoff under the parameters of record; a different cutoff, or the forecast-derived parameters, would give a different list (options table). Month-end values are volatile (working capital 13607.34 in 2026-05, 28973.94 in 2026-06), so one date is a weak basis for a capital figure.
* `sup-03` on-time is 0.461538 to 1.000000 by month on 10 to 18 receipts a month; the whole-history rate is the stable figure.
* The stored forecasts and the derived parameters carry the open promotion-factor defect S-03, so `ewma` on promoted SKUs, and the derived-parameter options, could change after the fix.

## Limitations
* **Synthetic.** Costs, suppliers, demand and the 548-day history are generated; the company does not exist. The three relationships above (censoring of class A promoted SKUs, an unreliable `sup-03`, a capacity-bound `loc-02`) are designed into the generator, so finding them shows the queries work, not that a business has them.
* **Open defects and decisions** (`technical-case-study.md`): S-02 (supplier on `replenishment_params`, not on `products`), S-03 (promotion factor), S-04 (closed orders with a partly received line are not on order: 72 units are excluded from on order), reviewer findings R3-01..R3-07 (the stockout-day claim in the case-study text mixes calendar days and SKU-days: 290 / 548 = 0.529197 against 431 / 32880 = 0.013108; a scenario can record the same unmet event twice; a stale draft can be exported; a product with parameters at several locations reports one location's position). Fixes are queued (T-03-07); the figures here are those of the code as it stands, and the fixes for S-03 (forecast-derived options, stored forecasts) and R3-01 (the definition of the stockout-day metric) may change what the contract reports.
* The capacity of `loc-02` and the reservations are not rules of the order arithmetic.

## Recommendation
What the synthetic data supports: place the draft order for `prod-005` (96 units) and, after a capacity check at `loc-02`, for `prod-002` (144 units); read the 0.90 against 0.95 question as an open parameter-setting question, not a result (the derived plans range from 88 to 154 units against 240 of record); keep the lost-sale policy where it is for these SKUs because the simulated direction favours it, subject to the customer-service view; and report every figure with its seed, cutoff and the label synthetic. The data does not support any statement about real savings, real stockout cost or real supplier behaviour.
