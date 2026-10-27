# ChangeWorks: business case (P09-ART-01)

**Every stakeholder, scenario and number here is synthetic.** Nothing is a claim about a real organisation, a real budget, a real person or a measured benefit, and no figure below is one; the product funds nothing (P09-GOAL-01, P09-FLOW-07).
Dataset `cw-20261026-20261026` (seed 20261026, generator `dataset_hash` `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`), contract v1, code revision `29948f9` (`29948f92f0c3839f070e4b6499b99f3810d1361b`); the world has 24 initiatives in 4 programmes, 30 scenarios, 900 cost and 700 benefit rows, 36 monthly periods from 2026-01, and the as-of **2026-10-05T00:00:00Z** (9 matured periods).
Three kinds of statement are kept apart throughout: **observed** (what the synthetic world records as having happened: actual costs, adoption and training records, benefit observations, allocations), **constructed** (what the generator built in on purpose: seven designed relationships DR-01..DR-07, twelve injected defects INJ-01..INJ-12, and its disclosed outcome-informed choices; and every scenario figure, which is a **plan estimate**) and **hypothetical** (what a real organisation might gain: not claimed anywhere; the word does not attach to any number below).

**How to read it:** this file needs nothing installed. The numbers are quoted from `sql-analysis.md` (investigations 01-11 and the reconciliation of its section 13, 763 rows all equal); `requirements.md` traces each requirement id to code and tests; `executive-memo.md` turns the evidence into a recommendation; `workbook.md` and `bi-package.md` describe the analyst workbook and the BI files. Money is USD with 2 places, capacity is hours, proportions are decimal fractions with 6 places, paybacks are period indexes (calendar months) with a 4-place interpolation, and every figure names its scenario.

## The business decision
**Which transformation initiative should be funded, and how will success be established?** (P09-GOAL-01.) The primary users are a transformation analyst, a business analyst and a financial analyst (P09-GOAL-02). ChangeWorks builds the evidence for a proposal; a sponsor proposes a scenario (C07 `select-scenario`), and funding happens outside the product.

## Business problem
The portfolio review argues about a spreadsheet. Time savings are booked as cash although nobody's hours left the payroll; two initiatives claim the same released capacity; an annual discount rate is applied to monthly periods; benefits start before the system is deployed; training completion is reported as adoption; a forecast is overwritten after a missed target so the approved one is gone; a dependency loop makes the roadmap impossible; a one-time licence recurs by accident; and avoided cost is added to cash as if both were money in the bank. Each of these is one of the specification's adversarial cases (P09-TEST-01..12) and one of the injected defects of the synthetic world (INJ-01..INJ-12).

What the synthetic world shows (scenario `scn-025`, all 24 initiatives, 8 % annual converted to 0.006434 per month, 36 periods; `sql-analysis.md`):
* **The plain sum overstates the portfolio.** The initiative NPVs sum to **1,438,382.25**, but `init-001` and `init-002` claim the same accounts-payable team's capacity (`src-fin-ap-shared-team`, periods 3..12): 207,146.32 of benefits counted twice, present value **195,233.20**. Counted once the portfolio NPV is **1,243,149.05** (DR-02, constructed; investigation 02).
* **Four classes, not one number.** 25,914,200.00 of planned costs against 15,288,067.20 cash, 6,074,000.13 revenue, 5,516,433.35 avoided cost realised and 1,774,010.55 capacity converted; 4,025,383.47 of avoided cost and 145,045.62 capacity hours stay beside the cash flow (investigation 01). The plain money claims total 32,677,894.70; 32,470,748.38 are attributable once.
* **Six initiatives never pay back.** `init-006`, `init-009`, `init-015`, `init-019`, `init-021` and `init-022` are `NOT_RECOVERED` in every scenario that contains them; four of the six have no benefit that enters the cash flow at all (their avoided cost has no realisation evidence and their capacity no conversion; `init-009` plans capacity only, 2,920.48 hours, NPV -761,535.73: DR-01), and `init-015` returns only **0.531465** of its cost in `scn-025` and 0.620043 under the earlier ramp (DR-03) (investigations 04, 11).
* **Observed delivery is mixed.** Pooled adoption is **0.532881** against training completion **0.888443** (0.963778 on the eleven initiatives with both series); five of eleven reached half adoption 4 to 6 months after training (DR-07). `init-003`'s forecast was revised twice after misses, 745,800.06 to 598,900.05 to 534,207.54, the original kept (DR-04). `init-008` realises 0.975795 of plan, but 0.848744 of the observed change is the pre-deployment trend (DR-06). Thirteen initiatives have a cost variance: 7 over, 6 under, net +253,802.33 (investigations 06-08).
* **The roadmap is tight.** Four initiatives are delayed by dependencies (3, 7, 10, 6 periods); three book benefits before their feasible start (`init-018`, `init-019`, `init-020`: `DEPLOYMENT_BEFORE_FEASIBLE_START`); the data migration specialist `res-03` is at capacity in periods 12..16 (DR-05) and the change manager pool `res-02` in 18 consecutive periods (investigation 09).

ChangeWorks fixes the arithmetic first: the four classes kept apart, capacity admitted to the cash flow only through a declared conversion with staffing evidence, a discount rate whose basis matches the period, benefits that cannot precede deployment, adoption with its denominator and training kept separate, an immutable approved baseline and every forecast revision beside the original, a dependency graph that refuses cycles, a double-count residual that must be explained, and a scenario whose only reachable state is `proposed`.

## Simulated stakeholders (roles, not people)
| Role (simulated) | Need | Decision criterion | Entities, metrics, commands |
|---|---|---|---|
| Transformation analyst (primary user) | Compare scenarios and prepare the proposal | Every figure names its scenario, rate and horizon; the attributable NPV leads, the plain sum sits beside it | `scenario_versions`, `scenario_pins`; P09-MET-02, P09-MET-12; C03 `build-cash-flows`, C07 `select-scenario` |
| Business analyst (primary user) | Baselines, impacts, readiness and adoption that stand up | Evidence is measured, assumptions are versioned; adoption keeps its denominator | `process_baselines`, `stakeholder_groups`, `impact_mappings`, `readiness_assessments`, `adoption_observations`, `training_completions`; P09-MET-04, 05, 08, 11; C01 `establish-baseline`, C04 `map-impacts`, C05 `assess-readiness`, C08 `record-adoption` |
| Financial analyst (primary user) | A cash-flow model whose NPV and paybacks can be audited | Exact rationals; costs expanded over half-open ranges; capacity in money only with a conversion | `cost_items`, `benefit_items`, `assumption_versions`, `forecast_versions`; P09-MET-01..03, 07; C02 `assess-opportunity`, C03, C10 `revise-forecast`; the workbook |
| Sponsor (decision owner) | Approve a baseline, propose a scenario, revise a forecast | A residual is explained before a proposal; a proposal is final; there is no funded state | `baseline_approvals`, `scenario_versions`; C01 `approve`, C07, C10 |
| Change manager (reader) | Who is affected and how ready they are | Readiness is an assessment, not a probability | `stakeholder_groups`, `readiness_assessments`; P09-MET-08 |
| Finance controller (reader) | Which avoided cost is real | Avoided cost enters the flow only with evidence that a budget line was removed | `benefit_items.cash_realisation`, `evidence_ref`; D-01 |
| HR / workforce planning (reader) | Whether released hours become a staffing change | Capacity is money only with a `staffing_change_evidence_ref` | `assumption_versions` (`capacity_hourly_rate`); P09-MET-04 |
| PMO / resource owner (reader) | Whether the roadmap fits the people | Allocation up to capacity; the crossing request is refused with its period | `resources`, `resource_allocations`, `dependencies`; P09-MET-10; C06 `plan-roadmap` |
| Auditor (reader) | Reconstruct what was proposed and from what | Append-only versions, audited refusals, a sealed scenario with its snapshot hash | `audit_events`, `command_results`, `rejected_records` |

## Scope
In scope: the six domain rules P09-DOMAIN-01..06 (four benefit classes, an immutable baseline, ramps and lags, no double count, uncertainty as labels, the workbook and the recommendation), the twelve metrics P09-MET-01..12 (net cash flow, NPV, discounted and simple payback, capacity released, adoption, benefit realisation, cost variance, readiness, risk exposure, dependency delay, training completion, double-count residual), the ten workflows P09-FLOW-01..10 (commands C01..C10), the twelve data entities P09-DATA-01..12, the golden case P09-GOLD-01 and the adversarial cases P09-TEST-01..12, the public site (P09-UI-01..10) and this artifact package (P09-ART-01..10).
Out of scope: funding anything, any real organisation's data, live data, paid inference (P09-GOAL-11), resource levelling that moves starts (D-06 gaps), attribution of an observed improvement to an initiative (the product says "observed, not attributed"), and Excel or Power BI execution (`workbook.md`, `bi-package.md`).

## Current-state and future-state process
| Step | Current state (the problem) | Future state (ChangeWorks) | Workflow id |
|---|---|---|---|
| 1. Baseline | A spreadsheet tab, edited after approval | Measured evidence with an evidence reference; approval freezes it; a correction is a new version with a reason | P09-FLOW-01, C01 `establish-baseline` |
| 2. Opportunity | A score nobody can reproduce | Criteria, weights and rationale; an exact weighted score, versioned | P09-FLOW-02, C02 `assess-opportunity` |
| 3. Cash flows | One benefit column, hours as dollars, monthly flows at an annual rate | Four classes; recurring costs expanded over half-open ranges; a rate converted and recorded; NPV exact; both paybacks labelled | P09-FLOW-03, C03 `build-cash-flows` |
| 4. Impacts | A slide | Operating changes per synthetic stakeholder group | P09-FLOW-04, C04 `map-impacts` |
| 5. Readiness | A traffic light | Five dimensions with weights, "an assessment, not a probability" | P09-FLOW-05, C05 `assess-readiness` |
| 6. Roadmap | Bars on a chart | Feasible starts, delays, a refused cycle, allocations up to capacity | P09-FLOW-06, C06 `plan-roadmap` |
| 7. Selection | "Approved" in an e-mail | `proposed`, with the comparison and the residual explanation; never `funded` | P09-FLOW-07, C07 `select-scenario` |
| 8. Adoption | Training completion reported as adoption | Adoption over its eligible denominator; training a separate series | P09-FLOW-08, C08 `record-adoption` |
| 9. Benefits | "Savings achieved" | Observed within one benefit type, matured periods only, the trend beside the raw change, observed not attributed | P09-FLOW-09, C09 `track-benefits` |
| 10. Forecast | Overwritten after a miss | Version n+1, the original kept, every revision and the observed values side by side | P09-FLOW-10, C10 `revise-forecast` |

## Decision criteria
1. **A cash case**: NPV above zero in the scenario that will be proposed, and both paybacks found inside the benefit window (investigation 11's screen; 18 of 24 in `scn-025`).
2. **Deliverable as planned**: no dependency on an initiative that does not carry a cash case (option D of investigation 11: 10 initiatives; option B breaks 4 dependencies), no deployment before the feasible start, resources within capacity.
3. **Counted once**: the attributable NPV and the attributable benefits are the headline; any residual (money or hours) is explained before C07.
4. **Evidence over estimate**: where periods have matured, observed realisation within each benefit type, adoption over its eligible population and cost variance against the approved baseline are read beside the plan, with the baseline trend beside the raw change.
5. **How success will be established** (before the proposal, not after): which metric, on which population, at which matured period, with which evidence reference (see `executive-memo.md`).

## Kinds of result in this package
| Kind | Examples | Where the figure comes from |
|---|---|---|
| Observed (one synthetic draw) | adoption 0.532881, training 0.888443, cost variance +253,802.33, realisation 0.975795 of `init-008` | the loaded records at the as-of; `sql-analysis.md` investigations 06-09 |
| Constructed | the shared capacity DR-02, the capacity-only initiative DR-01, the ratio 0.531465 of DR-03, every NPV and payback | the generator's design and the scenarios' plans; `sql-analysis.md` investigations 01-05, 11 |
| Hypothetical | any benefit to a real organisation | not claimed |

## Modes and verification (Mode A and Mode B)
Mode A, the Python domain, PostgreSQL 16 schema and FastAPI commands, is verified on GitHub-hosted runners against a transient PostgreSQL (CI run 40474351325 green on `29948f9`, release manifest); Mode B, the public static site over the published snapshot, simulates its sensitivity lab, roadmap edits and proposals in browser memory (D-08). This package analyses the published snapshot at `29948f9`; its SQL was run on scratch databases (`artifacts09_*`), never on the shared development database. Excel and Power BI were not run.

## Link from the website
The portfolio case study (`changeworks/project.json` on `unified-portfolio`) links the site and the source; linking these documents from its evidence area is the coordinator's decision and is not done by this package (it commits and publishes nothing).
