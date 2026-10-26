# Executive memo: what explains the margin decline? (P01-ART-07)

To: VP Sales and Finance controller of "Northfield Supply" (simulated). From: Revenue Atlas analyst workbench. Contract v1.1, snapshot `ra-20261026-20261026`.
**Every person, company and figure here is synthetic.** The numbers come from `data/sql/analysis/` run on a generated dataset (`sql-analysis.md`, `artifacts/analysis-results.json`); none is a real saving, loss or forecast.

## Decision
Which customer, product, region or discount policy explains the decline in contribution margin (P01-GOAL-01), so that the monthly margin review knows where to look first?

## Answer the data supports
**The cat-fixtures cost step explains most of the margin-rate drop; the West discount change is real in rate terms but small in dollars; customer-level decline is concentrated but not explained by these queries.**

Contribution margin rate was 0.3929 for 2024-10..2025-12 and 0.3267 for 2026-01..2026-09 (a drop of 6.62 percentage points; query 01 subtotals). At the later period's net sales of 3,661,781.43 that rate gap is 242,418.66 of contribution.

| Candidate cause | Evidence (query) | Dollars against the 242,418.66 | Share |
|---|---|---|---|
| Product: fixtures cost vs price | 04: fixtures cost-to-price 0.5943 (2024-10..2025-12) to 0.7284 (2026-01..2026-09); other categories 0.5826 to 0.6048. Step is in 2026-01 (0.6071 to 0.7212) | 187,416.40 cost above the earlier ratio | 77.3 % |
| Region and discount policy: reg-west | 03: discount rate 0.0263 to 0.0574 (+3.11 pp) from 2026-03; other regions -0.11 to +0.08 pp. 02: reg-west is 741,548.51 of 9,651,206.89 gross (7.7 %) | 6,592.14 extra discount | 2.7 % |
| Customer | 06: top three (cust-0017, cust-0009, cust-0007) = 110,433.59 of a 130,499.24 half-year-to-half-year contribution decline (84.6 %) | not comparable: absolute dollars, includes volume | n/a |
| Returns | 05: enterprise x cat-apparel 0.0861 against 0.0358 for all other cells (about 2.4x); 01: credits are 361,316.17 in total | not decomposed | n/a |

The business case sets the bar for "explained": removing the cause recovers at least half of the decline and the evidence reconciles to the cent. Fixtures clears half on the arithmetic above (77.3 %); West does not (2.7 %).
Reconciliation holds: the bridge total (contribution 3,309,826.22) equals `data/sql/reference_totals.sql` and the Python domain; the allocation residual is 0.00 (queries 01, 08).

## Options
1. **Fixtures price and cost pass-through review.** Test what price would restore the earlier cost-to-price ratio. Supported by query 04; needs real costing facts to mean anything.
2. **Revisit the West promo discount depth.** Rate doubled, dollars small; worth a policy check, unlikely to move the total.
3. **Account reviews for the three largest decliners.** Supported as a focus list (query 06); the data does not say why they fell.
4. **Monitor only.** Keep the monthly bridge and watch whether fixtures returns to the earlier ratio.

## Uncertainty
* The 77.3 % and 2.7 % shares are screening arithmetic: a cost-to-price ratio (or discount rate) held at its earlier level, ignoring product mix, volume and seasonality (the high-volume December sits in the earlier period). They are not scenario-engine results; scenario commands C07/C08 are not implemented in the backend and D-07 does not rescale costs.
* The two periods are 15 and 9 months long; ratios are comparable, dollar totals are not. Customer periods are two six-month halves.
* One synthetic dataset, one seed, no confidence intervals.

## Limitations
* **Synthetic and designed-in.** The generator planted three relationships (fixtures cost +18 % from 2026-01, West discount depth from 2026-03, enterprise apparel returns about 3x per line; `data/injection-manifest.json`). Finding them shows the analysis can detect such effects; it does not show they exist in any business. Customer decline (query 06) is the only result not designed in, and it is unexplained.
* **Static demo.** The public site recomputes the contract in the browser over the published snapshot; mutations live in browser memory only.
* **Known open defects** (independent review R-01..R-07, ledger): the web overview and bridge count credits by shipment month, not credit date (R-04), so the browser's monthly credits differ from query 01; grouped sums can drift by cents after FX conversion (R-05; the 9,651,206.89 total here is exact); stored C04 freight spans quarantined lines (query 09: 287.78). This memo uses the SQL figures.
* Quotas are not analysed (no attainment calculation in the slice).

## Recommendation
Start the margin review with fixtures cost-to-price. On this data it accounts for most of the rate drop, and the other candidates do not. Treat the figures as a way to rank where to look, **not as real savings**: no price change or cost recovery is claimed, and confirming the cause needs real cost data and the scenario step the backend does not yet have.
