# SupplyScope — business case (P03-ART-01)

**Every stakeholder, interview and number here is simulated.** Nothing is a claim about a
real employer, real purchase orders or measured savings (P03-DOMAIN-06, master 10).

## Business problem
"Northgate Components" (synthetic) stocks 60 SKUs in three locations from four suppliers.
The weekly buying meeting works from a spreadsheet that reads on-hand from a stale export,
treats units on order as available, counts a partial receipt as complete, forecasts next
month from last month's sales even when last month was a stockout, and rounds to packs
after applying the minimum order. SupplyScope supports the decision: what should be ordered,
when, and under which service and working-capital assumptions? (P03-GOAL-01)

## Simulated stakeholders
| Role (simulated) | Need | Decision criterion |
|---|---|---|
| Supply planner (primary) | A draft buying plan that reconciles to the ledger | Position = on hand + confirmed on order − backorders as of the cutoff |
| Finance | Working capital of the plan | Σ on hand × cost at the cost in force; no negative valuation |
| Customer service | Fewer stockouts on A items | Fill rate and stockout days by SKU; latent vs censored demand disclosed |
| Buyer | Supplier reliability without hindsight | On-time rate from receipts dated ≤ cutoff only |
| Data scientist | Forecasts that beat a baseline honestly | Seasonal-naive first; rolling-origin WAPE on the same folds |

## Scope and non-goals
In scope: an immutable movement ledger reconstructed as-of any instant with a declared day
order; replenishment arithmetic with reorder point, target, MOQ, pack rounding and supplier
calendars; baselines-first demand forecasts with information cutoffs; receipts that cannot
precede orders; unmet demand as lost sale or backlog by policy; policy comparison on common
random numbers; draft buying plans exported as CSV. Out of scope: submitting purchase orders,
supplier commitments, live ERP feeds, real cost data.

## Current-state and future-state process
Current (simulated): exports, a spreadsheet, a buyer's judgement, orders keyed by hand.
Future: C01 loads movements and rejects duplicates; C02 reconstructs stock as-of; C03 fits
baselines and a model at a cutoff; C05 drafts orders with the arithmetic shown; C06 simulates
arrivals on the supplier calendar; C07 records unmet demand by the scenario's policy; C10
exports the plan with versions embedded. Exceptions owned: negative reconstructions (data
steward), receipts before order (buyer), forecasts that lose to baseline (data scientist).

## Decision criteria
Adopt the policy with the lower working capital at the same fill rate on common random
numbers, provided stockout days on A items do not rise; present the result as a simulated
direction with its seed and warm-up printed, never as a realised saving (P03-MET-12 style).
