# ChangeWorks — business contracts, version 1 (2026-10-27)

Decision owner: coordinator (Fable 5.1). Spec: `projects/09-changeworks.md`, SHA-256 `7ae9dea5…` at pack commit
`fe5f7981` (verified against `docs/program/source-pack.json`). Rules cite the requirement they satisfy; changing one
bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
Which transformation initiative should be funded, and how will success be established? (P09-GOAL-01). Primary users: a
transformation analyst, a business analyst and a financial analyst (P09-GOAL-02). Boundaries: cash, avoided future
cost, revenue and capacity benefits are four classes that are never summed into one number without a declared
conversion (P09-DOMAIN-01); the approved baseline is immutable (P09-DOMAIN-02); adoption ramps and benefit lags are
modelled explicitly (P09-DOMAIN-03); cross-initiative benefits are never double-counted (P09-DOMAIN-04); uncertainty is
recorded as declared ranges and labels, never as false precision (P09-DOMAIN-05); the deliverables include a
formula-driven workbook and an executive recommendation (P09-DOMAIN-06). Nothing in the product funds anything: a
selected scenario is a **proposal** (P09-FLOW-07).

## D-01 Benefit classes, costs and the cash-flow model
* `benefit_items.benefit_type` ∈ {`cash`, `avoided_cost`, `revenue`, `capacity`}; `cost_items.cost_type` ∈
  {`one_time`, `recurring`}. Amounts are money in USD except `capacity`, whose amount is **hours** per period
  (P09-DOMAIN-01, P09-DATA-04/05).
* **Net cash flow** per period t = Σ cash-class benefits_t − Σ costs_t, where the cash classes are `cash` and
  `revenue`; `avoided_cost` enters only when its item carries `cash_realisation = true` with an `evidence_ref` (a
  budget line actually removed), otherwise it is reported beside the cash flow as avoided cost; `capacity` never
  enters the cash flow unless a **conversion** assumption version exists for the initiative (`capacity_hourly_rate`
  plus `staffing_change_evidence_ref`), in which case the converted amount is a separate `cash` item that cites the
  conversion (P09-MET-01, P09-TEST-01, P09-TEST-12). Golden (P09-GOLD-01): capacity hours are excluded.
* A `one_time` cost has exactly one `period_index`; a `recurring` cost is expanded explicitly into one row per period
  of its half-open range `[start_period, end_period)` by the command that builds cash flows, never by a display
  loop; a one-time cost appearing in more than one period is rejected `ONE_TIME_COST_REPEATED` (P09-FLOW-03,
  P09-TEST-11).
* **NPV** = Σ_{t=0}^{H−1} CF_t ÷ (1 + r)^t over the scenario's `horizon_periods` H with exact rational arithmetic;
  the rate basis must equal the period basis (`rate_basis` = `period_basis` ∈ {`annual`, `monthly`}); an annual rate
  on monthly periods is converted explicitly as (1 + r_annual)^(1/12) − 1 recorded as its own assumption version and
  never applied raw; a mismatch is rejected `RATE_PERIOD_MISMATCH` (P09-MET-02, P09-TEST-03). Golden: cost 1000 at
  t=0, net inflows 600 at t=1 and t=2, r = 0.10 annual → NPV = 5000/121 = 41.322314… shown as 41.32 USD.
* **Simple payback** = the first period index t at which the cumulative undiscounted net cash flow is ≥ 0;
  **discounted payback** = the same on the cumulative discounted flow; both are integer periods with a separate
  linearly interpolated figure (4 places) and both are labelled separately; **null when never crossed** within the
  horizon (P09-GOLD-01, P09-MET-03, P09-TEST-08). Golden: simple payback 2 (interpolated 1.6667), discounted
  payback 2 (interpolated 1.9167).
* Benefit lag and adoption ramp: a benefit item has `starts_period` ≥ the initiative's `deployment_period`; a
  benefit before deployment is rejected `BENEFIT_BEFORE_DEPLOYMENT`; a ramp is an assumption version
  (`adoption_ramp`, a non-decreasing list of fractions in [0, 1] per period from `starts_period`) applied
  multiplicatively to the planned benefit amounts of that initiative; the unramped plan stays visible beside the
  ramped one (P09-DOMAIN-03, P09-TEST-04).
* **Capacity released** (hours per period) = `volume` × (baseline `minutes_per_case` − target `minutes_per_case`) ÷
  60, from the approved process baseline and the initiative's target assumption; it is reported as hours and is
  never a payroll saving by itself (P09-MET-04).
* **Double-count residual** = Σ planned benefits over the selected initiatives − Σ non-overlapping attributable
  benefits, where benefits sharing one `benefit_source_key` (the same released capacity, the same cost line) across
  two initiatives count once in the attributable total and the overlap is listed; a residual other than 0.00 must be
  explained on the portfolio before a scenario can be selected (P09-MET-12, P09-TEST-02, P09-DOMAIN-04).

## D-02 Baselines, assumptions, scenarios and forecasts
* **Evidence and assumptions are separated**: `process_baselines` are evidence (measured `volume`,
  `minutes_per_case`, `error_rate` with `evidence_ref` and `measured_at`); `assumption_versions` are assumptions
  with `version_number` 1..n per (`initiative_id`, `name`), a `rationale` and an `author_id` (P09-FLOW-01).
* An approved baseline is immutable: `initiatives.baseline_version` names the approved set; approval (sponsor
  role) freezes every baseline row of that version; a correction is a new version with a reason, and the earlier
  version stays readable (P09-DOMAIN-02, P09-FLOW-01, P09-FLOW-10).
* `scenario_versions` are immutable: `scenario_id`, `baseline_version`, `discount_rate`, `horizon_periods`,
  the pinned assumption versions and `created_at`; an edit creates a new `scenario_id` (D-11 of the master
  starting contracts). A scenario's figures are **estimates** and are visibly separated from observed results.
* **Revise forecast** (C10) creates forecast version n+1 and never overwrites the original approved forecast; the
  forecast comparison shows original, every revision and observed values with their dates (P09-FLOW-10,
  P09-TEST-06).
* **Cost variance** = actual cost − approved baseline cost for the same initiative and the same half-open period
  range; null when the initiative has no approved baseline (P09-MET-07).
* **Benefit realization** = observed comparable benefit ÷ planned comparable benefit, computed **within one
  `benefit_type`** for matured periods only (periods whose end is ≤ as-of); null when the planned amount is 0;
  observed benefits carry the attribution caveat: an observed improvement is compared with the baseline trend
  recorded before deployment (`baseline_trend_per_period` on the benefit item) and the page reports "observed, not
  attributed"; the share above the trend is shown beside the raw change, never in place of it (P09-MET-06,
  P09-FLOW-09, P09-TEST-10, P09-TEST-12).
* **Risk exposure** = Σ `probability` × `impact` (USD) over an initiative's risk items with probability in [0, 1];
  labelled a scenario estimate (P09-MET-09).

## D-03 Roadmap, dependencies, impacts, readiness and adoption
* `dependencies.dependency_type` ∈ {`finish_to_start`, `start_to_start`}, `lag_periods` ≥ 0; a cycle among
  initiatives is rejected `DEPENDENCY_CYCLE` with the cycle listed (P09-TEST-07). Feasible start = max over
  prerequisites of (prerequisite finish or start + lag); unconstrained start = the requested start;
  **dependency delay** = feasible start − unconstrained start in periods, with resource constraints reported
  separately (P09-MET-10, P09-FLOW-06).
* Shared capacity: `resources` have `capacity_per_period`; an initiative's `resource_allocations` per period summed
  over the roadmap must not exceed capacity; an overallocation is reported `RESOURCE_OVERALLOCATED` with the
  periods and the resource-constrained start is shown beside the dependency-feasible one (P09-TEST-09).
* `stakeholder_groups` (`affected_count`, `impact_level` ∈ {`low`, `medium`, `high`}) and `impact_mappings`
  describe the operating changes an initiative causes for a group; labels are synthetic (P09-FLOW-04/05).
* **Readiness score** = Σ_d weight_d × score_d ÷ Σ_d weight_d over the dimensions assessed for a group, dimensions
  `awareness`, `desire`, `knowledge`, `ability`, `reinforcement` (ADKAR-inspired), integer scores 1..5, declared
  weights; labelled an assessment, not a probability; null when nothing was assessed (P09-MET-08).
* **Adoption rate** = `adopted_count` ÷ `eligible_count` per observation with the denominator preserved and
  eligibility fixed by the initiative's `eligibility_rule_version`; **training completion** = completed ÷ eligible
  trainees from `training_completions` and is never substituted for adoption (P09-MET-05, P09-MET-11, P09-FLOW-08,
  P09-TEST-05).
* **Select scenario** (C07) sets the scenario's status to `proposed` with the comparison it was chosen from; the
  product has no `funded` status and never claims actual funding (P09-FLOW-07).

## D-04 Numbers, time and absence
Money: decimal strings with 2 places in JSON, NUMERIC(20,6) in the database, exact rationals inside the domain;
rounding only at the declared presentation step, ROUND_HALF_UP. Proportions: decimal strings with 6 places in
[0, 1] ("percent" is display only). Periods: integer `period_index` from 0 with `period_basis` and a `period_start`
date; ranges half-open `[from, to)`. Instants UTC with `Z`, server-stamped. Null means unknown, no baseline or a
zero denominator, never 0. Empty population: every count 0, every ratio and NPV null, `empty_population` true.

## Mode disclosure
Mode A: Python domain + PostgreSQL + FastAPI verified on hosted runners. Mode B: TypeScript mirror over the published
snapshot; the sensitivity lab, roadmap edits and scenario selection are browser-memory simulations and say so.
