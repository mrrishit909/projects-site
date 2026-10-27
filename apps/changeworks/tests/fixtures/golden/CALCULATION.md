# ChangeWorks golden calculation (contract v1, decisions D-01..D-04, proposed D-P9-01..D-P9-24, review-9 rules D-P9-25..D-P9-38 and contract D-09)

Independent of application code. `../../reference_check.py` recomputes every figure below from `inputs.json` (and from the two
variants) and compares it with `expected.json` leaf by leaf (standard library only, no app imports, `fractions.Fraction` for every
ratio, rate and discount factor, `decimal.Decimal` for money parsing and display, no float). The hand-worked figures on this
page are typed into the script as literals (`OK hand.*`) and checked against `expected.json`, not against the computation.
Formats (D-04): money 2-place strings, proportions 6-place strings, paybacks / hours / readiness score 4-place strings (D-P9-20),
exact rationals as `n/d` strings, null means unknown / no baseline / zero denominator and is never 0. ROUND_HALF_UP (away from
zero on ties). Periods are integers from 0, ranges half-open `[from, to)`. Golden: `period_basis` annual, `period_start`
2026-01-01 (period t = calendar year 2026+t), `as_of` 2028-06-30T00:00:00Z. A period is matured when its end (the start of period
t+1) is <= as_of: periods 0 and 1 are matured (end 2027-01-01 and 2028-01-01), period 2 (ends 2029-01-01) is not.

Key nesting of `expected.json`: `ingest.counts.<entity>.{accepted,rejected}`, `ingest.rejected_records[]` (entity, id, status,
reason_code, optional details, raw_row), `metrics.summary`, `metrics.scenarios.<scenario_id>.{effective_period_rate,
initiatives.<id>.{cash_flow[],expanded_planned_costs[],excluded_from_cash_flow,converted_capacity[],ramp,unramped_net_cash_flow,
planned_money_benefits,npv,payback.{simple,discounted}.{period,interpolated,reason},capacity_released,cost_variance,
benefit_realization.<type>.{...,trend_coverage}},double_count.{...,double_counted_amount,double_counted_pv,hours_residual,hours_overlaps},
npv_total.{value,exact,basis,sum_of_initiatives}}`, `metrics.initiatives.<id>.{roadmap.{...,warnings},adoption,training,risk,forecast}`,
`metrics.groups.<group_id>.readiness_*`, `metrics.resources.<resource_id>`. Metrics that depend on the scenario (cash flow,
NPV, paybacks, ramp, pinned target, matured window, double count) sit under the scenario; the others do not.

## The spec sentence [P09-GOLD-01]

> At annual period 0 cost=$1000; year 1 net cash inflow=$600; year 2=$600; annual discount rate=10%. NPV = -1000 + 600/1.1 +
> 600/1.1^2 = approximately $41.32. Simple payback and discounted payback must be separately labeled; capacity hours are
> excluded from cash flow unless a defensible conversion is supplied.

Embedded as `init-001` "Invoice automation" in scenario `scn-001` (rate 0.100000 annual, rate_basis annual = period basis,
horizon 3 so t = 0, 1, 2). Inputs: cost `c-101` one_time planned 1000.00 at period 0; cash benefits `b-101` (period 1) and
`b-102` (period 2) of 600.00 each; **also** capacity benefits `b-103`, `b-104` of 400.00 hours (unit hours) at periods 1 and 2.
No `capacity_hourly_rate` conversion assumption exists for `init-001`, so the hours stay out of the cash flow (D-01).

## Part (a): init-001 net cash flow, NPV, paybacks (P09-MET-01, 02, 03)

| t | cash benefits | costs | net cash flow | cumulative | discount factor 1/1.1^t | discounted | cumulative discounted |
|---|---|---|---|---|---|---|---|
| 0 | 0 | 1000 | -1000.00 | -1000.00 | 1 | -1000.00 | -1000.00 |
| 1 | 600 | 0 | 600.00 | -400.00 | 10/11 = 0.909091 | 6000/11 = 545.45 | -1000 + 6000/11 = -5000/11 = -454.55 |
| 2 | 600 | 0 | 600.00 | 200.00 | 100/121 = 0.826446 | 60000/121 = 495.87 | -5000/11 + 60000/121 = (-55000 + 60000)/121 = 5000/121 = 41.32 |

* **NPV = 5000/121 = 41.322314... -> "41.32" USD** (exact rational "5000/121" recorded beside it).
  Check: -1000 = -121000/121; 600/1.1 = 6000/11 = 66000/121; 600/1.21 = 60000/121; sum = (-121000 + 66000 + 60000)/121 = 5000/121.
* **Simple payback**: first t with cumulative >= 0 is t = 2 (cumulative -400 at t = 1, +200 at t = 2). Interpolated:
  (t-1) + (-cum[t-1]) / (cum[t] - cum[t-1]) = 1 + 400/600 = 1 + 2/3 = **1.6667**.
* **Discounted payback**: first t with cumulative discounted >= 0 is t = 2. Interpolated: 1 + (5000/11) / (60000/121) = 1 + (5000 x 121)
  / (11 x 60000) = 1 + 55/60 = 1 + 11/12 = **1.9167**. Both labelled separately in the output (`payback.simple`, `payback.discounted`).
* **Excluded**: capacity hours 400 + 400 = **800.00 hours** (`excluded_from_cash_flow.capacity_hours_not_converted`, reason
  `NO_CONVERSION_ASSUMPTION`). The period 1 and 2 `cash_benefits` stay 600.00 (they would be 1000.00 if hours were added, TEST-01/12).
* **Capacity released** (P09-MET-04): approved baseline `pb-101` (v1; `initiatives.baseline_version` = v1): volume 12000, 10 min/case;
  pinned target `a-101-t1` = 8 min -> 12000 x (10 - 8) / 60 = **400.0000 hours** per period; it equals the 400.00 hours claimed by
  the capacity benefit items and is never a payroll saving.

## Part (b): init-002 "Onboarding redesign" (recurring costs, ramp, benefit classes, lag)

Costs (planned, baseline v1): `c-201` one_time 500.00 at 0; `c-202` recurring 100.00 over the half-open range [1, 3), expanded by the
cash-flow command into rows at periods 1 and 2 (`expanded_planned_costs` has 3 rows with `c-201`). Ramp `a-201-r1` = [0.5, 1.0],
indexed from each benefit item's `starts_period` (D-P9-02); deployment_period 1.

| item | class | planned | starts | ramp idx | ramped | enters cash flow? |
|---|---|---|---|---|---|---|
| b-201 p1 | cash | 400 | 1 | 0 -> 0.5 | 200 | yes |
| b-202 p2 | cash | 400 | 1 | 1 -> 1.0 | 400 | yes |
| b-203 p2 | avoided_cost, cash_realisation true, evidence_ref | 150 | 2 (a lag of 1 after deployment) | 0 -> 0.5 | 75 | yes (budget line removed) |
| b-204 p1 | avoided_cost, cash_realisation false | 80 | 1 | 0 | 40 | **no**, reported beside |
| b-205 p2 | avoided_cost, cash_realisation false | 80 | 1 | 1 | 80 | **no**, reported beside |
| b-206 p2 | revenue | 100 | 2 | 0 | 50 | yes (cash class, D-01) |

Net cash flow: t0 = -500; t1 = 200 - 100 = **100**; t2 = 400 + 75 + 50 - 100 = **425**. Unramped plan beside it: t1 = 400 - 100 = 300,
t2 = 400 + 150 + 100 - 100 = 550 (`unramped_net_cash_flow`). Avoided cost reported beside the cash flow = 40 + 80 = **120.00**.
Cumulative: -500, -400, +25. NPV = -500 + 100 x 10/11 + 425 x 100/121 = -500 + 1000/11 + 42500/121 = (-60500 + 11000 + 42500)/121
= **-7000/121 = -57.85**. Simple payback 2, interpolated 1 + 400/425 = **1.9412**. Discounted cumulative: -500, -409.09, -57.85, never >= 0
-> **discounted payback null** (the simple one is not).
Capacity released: baseline v1 `pb-201` 6000 cases, 30 min; target pinned `a-201-t1` = 24 -> 6000 x 6 / 60 = **600.0000 h**. (The unpinned
`a-201-t2` = 25 and the unapproved `pb-202` v2, volume 6600, are not used: a scenario's pins and the approved baseline are immutable.)

## Part (c): init-003 "Vendor consolidation" (never pays back, no approved baseline)

Cost `c-301` 800.00 at 0; avoided cost `b-301` 150.00 at period 2, cash_realisation true with evidence -> t2 = +150. Net: -800, 0, +150;
cumulative -800, -800, -650, never >= 0. NPV = -800 + 150 x 100/121 = (-96800 + 15000)/121 = **-81800/121 = -676.03**. Simple and discounted
paybacks **null** (not rejected, TEST-08). `baseline_version` is null, so capacity released and cost variance are **null** (not 0).
Sum of the three initiative NPVs = (5000 - 7000 - 81800)/121 = **-83800/121 = -692.56** (`npv_total.sum_of_initiatives`); the scenario's
`npv_total` is the attributable figure of Part (h), -754.55.

## Part (d): cost variance (P09-MET-07), matured window (D-P9-05)

Window = [0, min(horizon 3, matured periods 2)) = [0, 2). init-001: approved baseline cost 1000.00 (c-101), actual 1000.00 (c-102) -> **0.00**
(a real zero, not null). init-002: baseline 500 + 100 (expanded p1) = 600.00; actual 520 (c-203) + 100 (c-204 p1) = 620.00 -> **+20.00**;
the planned 100 of period 2 is outside the window. init-003 -> null (`NO_APPROVED_BASELINE`).

## Part (e): benefit realization within one type, matured periods only (P09-MET-06)

Matured periods are 0 and 1, so period 2 items and observation `bo-3` (300.00 on `b-102`, observed 2028-06-15, a partial period) are excluded
(`immature_observation_ids` = [bo-3]). init-001 cash: `b-101` planned 600, observed 480 -> **480/600 = 0.800000**; baseline trend 50.00
(recorded before deployment) -> observed above trend 480 - 50 = **430.00**, shown beside the raw 480.00, labelled "observed, not attributed".
init-001 capacity (never mixed with cash): 340 / 400 hours = **0.850000**. init-002 cash: planned is the ramped 200, observed 150 -> **0.750000**
(trend 20.00 -> 130.00); init-002 avoided cost: ramped planned 40, observed 30 -> **0.750000**.

## Part (f): adoption, training, risk, readiness, roadmap, double count, forecast

* **Adoption** (MET-05): latest observation at or before as_of. init-001: `ad-2` 30/40 = **0.750000** (series 10/40 = 0.250000 then 0.750000);
  `ad-3` (2028-09-30) is after as_of and excluded. init-002: 20/50 = **0.400000**. init-003: eligible 0 -> **null**. All carry
  `eligibility_rule_version` elig-v1. Pooled summary 50/90 = 0.555556 (init-003's zero denominator contributes nothing).
* **Training completion** (MET-11): init-001 38/40 = **0.950000**, reported separately, `differs_from_adoption` true, `substituted_for_adoption` false.
  init-002/003: no records -> null.
* **Risk exposure** (MET-09): init-001 0.20 x 5000 + 0.05 x 20000 = 1000 + 1000 = **2000.00**; init-002 0.5 x 1000 + 0.0 x 9999 = **500.00**
  (probability 0 and 1 are inside [0, 1]); init-003 has no risk items -> **null**. Labelled "scenario estimate". Summary total 2500.00.
* **Readiness** (MET-08): grp-001 uses the latest assessment per dimension (the 2026-11-01 awareness score 2 is superseded by the 2027-02-01 score
  4): sum w x s = 1x4 + 2x3 + 1x2 + 1x3 + 1x5 = 20, sum w = 6 -> 20/6 = 10/3 = **3.3333**. grp-002 (two of five dimensions): (5 + 3)/2 = **4.0000**.
  grp-003: nothing assessed -> **null**. Labelled "assessment, not a probability".
* **Dependency delay** (MET-10): init-001 start 0, duration 1. init-002 requested 0; `d-1` finish_to_start lag 1 -> feasible 0 + 1 + 1 = 2 -> delay **2**.
  init-003 requested 0: `d-2` finish_to_start lag 0 on init-002 (feasible start 2 + duration 1 = 3) -> 3; `d-3` start_to_start lag 1 on init-001 -> 0 + 1 = 1;
  max = 3, binding `d-2` -> delay **3**. Resource constraints separate: res-001 capacity 2.00 FTE; allocations by period p0 1.00 + 0.75 = 1.75,
  p2 1.50, p3 2.00 (exactly at capacity is allowed) -> no overallocated period, constrained start = dependency-feasible start, resource_delay 0.
* **Double-count residual** (MET-12): money-class ramped planned benefits: init-001 600 + 600 = 1200; init-002 200 + 400 + 75 + 40 + 80 + 50 = 845;
  init-003 150 -> **2195.00**. `b-203` (75, init-002) and `b-301` (150, init-003) share `benefit_source_key` "cost-line:CC-4410" in period 2: counted
  once at the larger claim 150, overlap 225 - 150 = 75. Attributable 2195 - 75 = **2120.00**, **residual 75.00** (non-zero, so `explanation_required` true
  and the overlap is listed). Hours are never added to dollars. The 75.00 that counts twice is a claim of `init-002` (`b-203`, class
  `avoided_cost_realised`, which enters the cash flow) in period 2; its present value and the attributable NPV are in Part (h).
* **Forecast** (TEST-06): original `f-101-1-*` v1 = 600 + 600 = 1200.00 stays unchanged; revision v2 = 480 + 500 = 980.00 (created 2028-02-15);
  latest minus original = **-220.00**; observed values with dates: 480.00 on 2028-01-31 (matured), 300.00 on 2028-06-15 (period not matured).

## Part (h): the review-9 rules on the golden case (D-P9-25..D-P9-38)

* **Attributable NPV and the double-counted amount (R9-02).** The 75.00 that counts twice (`b-203`, init-002, period 2, the smaller claim; `b-301` of init-003
  at 150.00 is the one that counts) enters the cash flow in period 2, so its present value at 10 % is 75 / 1.1^2 = 75 x 100/121 = **7500/121 = 61.98**
  (`double_counted_pv`; `double_counted_amount` 75.00 = the residual, by class `avoided_cost_realised` 75). The attributable `npv_total` is the sum of the
  initiative NPVs less that present value: -83800/121 - 7500/121 = -91300/121 = **-8300/11 = -754.55** (`npv_total.value`, also `summary.npv_total`);
  `npv_total.sum_of_initiatives` keeps -83800/121 = -692.56 beside it. Check: -692.56 - 61.98 = -754.54 by rounded parts; the exact rational rounds once to -754.55.
* **Hours (R9-03).** The golden has 800.00 capacity hours (init-001, `b-103` 400 + `b-104` 400), none with a source key: `planned_hours` 800.00,
  nothing shared, `hours_residual` 0.00, `attributable_hours` 800.00, `hours_overlaps` empty. `summary.capacity_released_hours_total` = 400.0000 + 600.0000 =
  1000.0000 with 0.0000 counted twice (no two initiatives share a capacity key). `explanation_required` stays true because of the **money** residual (75.00);
  `explanation_required_for` = ["money"].
* **Deployment before the feasible start (R9-06).** Benefits are booked from `deployment_period`. init-001: deployment 1, feasible start 0: none. init-002:
  deployment 1 < feasible start 2 (Part (f): requested 0 + duration 1 + lag 1): `DEPLOYMENT_BEFORE_FEASIBLE_START`, 1 period early. init-003: deployment 2 <
  feasible start 3: the same, 1 period early. The cash flow is not re-timed (D-P9-08): init-002 still has net 100.00 in period 1.
* **Payback reasons (R9-12).** init-001: both paybacks found (cumulative -1000, -400, +200 stays >= 0), reason null. init-002 simple: cumulative -500, -400, +25:
  last negative at t = 1, payback 2 (1.9412); discounted cumulative -500, -409.09, -57.85 ends negative: null, reason `NOT_RECOVERED`. init-003: -800, -800, -650 ends
  negative: both null, `NOT_RECOVERED`. (A cumulative that is never negative would be `NO_INVESTMENT`; no flows at all, `NO_FLOWS`: see the probes below.)
* **Trend coverage (R9-13).** init-001 cash compares `b-101` only, which carries a trend: coverage complete, 430.00 above the trend as before. init-001 capacity
  compares `b-103`, which carries none: `baseline_trend` null, `observed_above_trend` null, `rows_without_trend` [b-103]; init-002 avoided cost likewise (`b-204`).
  No warning is raised for a type with no trend at all (nothing is shown that could mislead); `PARTIAL_TREND_COVERAGE` is for some-but-not-all rows (probe below).
* **Forecast (R9-07, R9-10).** v1 covers periods 1 and 2, v2 covers periods 1 and 2: the revision covers the original's periods, `original_preserved` true (the stored
  version 1 exists); latest minus original = 980.00 - 1200.00 = -220.00 from the exact totals (480.000000 + 500.000000 and 600.000000 + 600.000000).
* **Exact totals (R9-07).** Every aggregate is the exact sum rounded once: `capacity_hours_not_converted` 800.00 = 400 + 400, `avoided_cost_beside_total` 120.00 =
  40 + 80, `risk_exposure_total` 2500.00, `capacity_released_hours_total` 1000.0000 (each initiative also records its exact rational: `hours_exact` "400", `risk_exposure_exact`).

## Part (g): ingest counts (golden)

All 71 rows accepted, 0 rejected: initiatives 3, process_baselines 4, assumption_versions 4, resources 1, scenario_versions 1, cost_items 7,
benefit_items 11, dependencies 3, stakeholder_groups 3, impact_mappings 3, resource_allocations 4, readiness_assessments 8,
adoption_observations 5, training_completions 1, benefit_observations 5, risk_items 4, forecast_versions 4.

## variant-rejected (P09-GOLD-08): monthly periods, as_of 2026-06-30 (periods 0..4 matured), 30 rejected records, reasons

Each rejection is a whole record, with the reason code and (where useful) details; the valid records around them are unaffected.

| record | code | why rejection is correct |
|---|---|---|
| rj-i5 initiative | STATUS_NOT_ALLOWED | "funded" is not a status of the product (P09-FLOW-07) |
| rj-i1 (second row) | DUPLICATE_ID | the id exists; replay cannot create a second business record |
| pb-r2 | UNKNOWN_INITIATIVE | baseline names an initiative that does not exist |
| ra-t1x | VERSION_EXISTS | (rj-i1, target_minutes_per_case, 1) exists; assumption versions are never overwritten; ra-t1 stays (value 8) |
| rs-1 | RATE_PERIOD_MISMATCH | annual rate on monthly periods without a recorded conversion |
| rs-4 | STATUS_NOT_ALLOWED | a scenario cannot be "funded", only draft or proposed |
| rs-5 | UNKNOWN_INITIATIVE | lists rj-ghost |
| rc-2 | ONE_TIME_COST_REPEATED | one_time cost key ck-a already at period 0, repeated at period 2; rc-1 kept |
| rc-7 / rc-8 | UNKNOWN_INITIATIVE / DEPENDENT_REJECTED | rj-ghost does not exist / rj-i5 was rejected |
| rb-4 | BENEFIT_BEFORE_DEPLOYMENT | starts at 0, rj-i1 deploys at 1 |
| rb-7 | CAPACITY_WITHOUT_CONVERSION | 40 hours claimed as cash realised, but rj-i2 has no capacity_hourly_rate + staffing_change_evidence_ref |
| rd-3 | DEPENDENCY_CYCLE | rd-1 (i2 needs i1) and rd-2 (i3 needs i2) exist; rd-3 (i1 needs i3) closes [rj-i1, rj-i3, rj-i2, rj-i1] |
| rd-4 / rd-5 | UNKNOWN_INITIATIVE / DEPENDENT_REJECTED | rj-ghost / rj-i5 |
| im-r2, rra-3 | UNKNOWN_GROUP | rg-ghost |
| al-r2 | RESOURCE_OVERALLOCATED | res-r1 capacity 2.00; period 0 already 1.50 (al-r1), +1.00 = 2.50 > 2.00; periods [0] listed |
| al-r4 | UNKNOWN_RESOURCE | res-ghost |
| rra-2 / rra-4 | INVALID_SCORE / INVALID_DIMENSION | score 6 outside 1..5; "enthusiasm" is not an ADKAR dimension |
| rao-2 / rao-3 | ADOPTED_EXCEEDS_ELIGIBLE / ELIGIBILITY_RULE_MISMATCH | 25 of 20; rule elig-v2 where the initiative fixes elig-v1 |
| rt-2 | COMPLETED_EXCEEDS_ELIGIBLE | 21 of 20 |
| rbo-2 / rbo-3 | DEPENDENT_REJECTED / UNKNOWN_BENEFIT | observation of rejected rb-4 / of rb-ghost |
| rk-2 | PROBABILITY_OUT_OF_RANGE | 1.500000 not in [0, 1] |
| rk-3 / rk-4 | DEPENDENT_REJECTED / UNKNOWN_INITIATIVE | rj-i5 / rj-ghost |
| rf-2 | VERSION_EXISTS | forecast (rj-i1, v1, period 1) exists; the original approved forecast is never overwritten |

Accepted records still compute. Scenario `rs-2` (rate 0.100000 annual on monthly periods with recorded conversion `ra-conv` = 0.007974, the
12th-root conversion (1.10)^(1/12) - 1 = 0.0079741... recorded to 6 places, D-P9-06), horizon 4:
* rj-i1: costs 1000 at 0 and 50 at 1..3 (recurring [1, 4)); cash 700 at 1..3 -> net -1000, 650, 650, 650; cumulative -1000, -350, 300, 950;
  simple payback 2, interpolated 1 + 350/650 = **1.5385**; discounted at 0.007974: -1000, 644.86, 639.76, 634.70 -> cumulative -355.14, 284.61 ->
  discounted payback 2, interpolated 1 + 355.14/639.76 = 1.5551; NPV = **919.31**. Capacity released 1200 x 2 / 60 = **40.0000 h**. Training 18/20 = 0.900000.
* rj-i3: net -500, 0, +50, +50 (the 200 avoided cost has cash_realisation true but **no evidence_ref**: accepted, reported beside, not in cash flow,
  `NO_EVIDENCE_REF`); never reaches 0 -> **paybacks null, not rejected**; NPV = **-401.97**.
* rj-i4: conversion `ra-cap` 25.00 USD/hour with staffing evidence: 100 h x 25 = **2500.00** per period at 1 and 2 (separate derived cash items citing
  `ra-cap`); net -1000, 2500, 2500, 0; simple payback 1, interpolated 0 + 1000/2500 = **0.4000**; discounted 0.4032; NPV = **3940.82**. Total rs-2 NPV 4458.17.
* Scenario `rs-3` (monthly 0.010000 declared, no conversion needed), rj-i2: -300, 0, 150, 150; cumulative -300, -300, -150, **0** -> simple payback 3
  (a cumulative of exactly 0 counts), interpolated 2 + 150/150 = **3.0000**; discounted cumulative -300, -300, -152.96, -7.37 -> **null**; NPV =
  -300 + 150/1.0201 + 150/1.030301 = **-7.37** (exact -7590300/1030301).
* Roadmap: rd-1, rd-2 accepted; rj-i1 duration 2 -> rj-i2 feasible 2 (delay 2), finish 3 -> rj-i3 FS lag 1 -> 4 (delay 4); rj-i3 deploys at 1 < 4:
  `DEPLOYMENT_BEFORE_FEASIBLE_START`, 3 periods early.

### Probe block (review 9): payback, plan as built, partial trend, shared hours, late-recorded observations

Six accepted probe initiatives `rj-p1..rj-p6` (all request start 0, duration 1, deployment 1, no dependency: no deployment warning) in two scenarios on monthly periods at a
0.000000 monthly rate (so every discount factor is 1 and the discounted series equals the plain one). `rs-6` (created 2026-01-05) has horizon 5 and all six; `rs-7`
(created 2026-03-01) has horizon 5 and `rj-p2`. No new rejection: the 30 records above are unchanged.

| initiative | net cash flow t = 0..4 | cumulative | rule | result |
|---|---|---|---|---|
| rj-p1 (benefits 600 at t = 1, 2, no cost) | 0, 600, 600, 0, 0 | 0, 600, 1200, 1200, 1200 | never negative: no investment (R9-12; the first-crossing rule said 0.0000) | payback null, `NO_INVESTMENT`; NPV 1200.00 |
| rj-p2 in rs-6 (cost 1000 at 0, 300 at 2; benefits 1200 at 1, 500 at 3) | -1000, 1200, -300, 500, 0 | -1000, 200, -100, 400, 400 | last negative at t = 2, so the last crossing is t = 3: 2 + 100/500 | payback **3, 2.2000** (the first-crossing rule said 1); NPV **400.00** |
| rj-p3 (cost 1000 at 0, 700 at 2; benefit 1500 at 1) | -1000, 1500, -700, 0, 0 | -1000, 500, -200, -200, -200 | ends negative after having crossed once | payback null, `NOT_RECOVERED`; NPV -200.00 |
| rj-p4 (cost 150 at 0; benefits 100 at 1 and 2) | -150, 100, 100, 0, 0 | -150, -50, 50, 50, 50 | 1 + 50/100 | payback 2, **1.5000**; NPV 50.00 |
| rj-p5, rj-p6 (capacity only, 40 and 60 hours at t = 2, no conversion) | none | none | no cost and no cash row: nothing to pay back | NPV null, payback null, `NO_FLOWS` |

* **Plan as it was built (R9-01).** `rc-p2c` (500.00 for rj-p2 at period 3) was recorded 2026-02-01: after `rs-6` was created (2026-01-05) and before `rs-7` (2026-03-01).
  `rs-6` therefore holds rj-p2's two earlier costs (2 expanded rows, NPV above) and `rs-7` all three: net -1000, 1200, -300, 500 - 500 = 0, 0; cumulative
  -1000, 200, -100, -100, -100; payback null, `NOT_RECOVERED`; NPV **-100.00**. The same initiative has two answers because the two scenarios were built on different plans.
* **Attributable NPV of rs-6.** The probes share no money claim, so the attributable NPV equals the sum: 1200 + 400 - 200 + 50 = **1450.00** (rj-p5/p6 null, not 0).
  Money planned: rj-p1 600 + 600, rj-p2 1200 + 500, rj-p3 1500, rj-p4 100 + 100 = 1200 + 1700 + 1500 + 200 = 4600.00 (attributable 4600.00, residual 0.00).
* **Hours counted twice (R9-03).** `rb-p5` (40.00 h, rj-p5) and `rb-p6` (60.00 h, rj-p6) claim `src-probe-team` in period 2, neither converted: counted once at the
  larger, 100 - 60 = **40.00** `hours_residual`; `planned_hours` 100.00, `attributable_hours` 60.00; the money residual is 0.00 and `explanation_required_for` = ["hours"]
  (the proposal needs its explanation for either residual). `rj-p5` and `rj-p6` each list their hours under `capacity_hours_not_converted` (40.00, 60.00).
* **Partial trend (R9-13).** rj-p4's cash rows `rb-p4a` (planned 100, trend 10.00) and `rb-p4b` (planned 100, no trend) are matured (periods 1, 2) and observed (90.00 on
  2026-03-15; 80.00 on 2026-04-15): planned 200.00, observed 170.00, realization **0.850000**, `baseline_trend` 10.00 (the rows that carry one), `observed_above_trend`
  **null** (it would be 160.00 against a trend that covers only half the compared rows), `trend_coverage` incomplete with `rows_without_trend` [rb-p4b], and a
  `PARTIAL_TREND_COVERAGE` warning from the domain.
* **Recorded after as_of (R9-11).** `rbo-p4c` (95.00 for rb-p4a, observed 2026-05-01) was recorded 2026-07-15, `rao-4` (rj-i1, 16 of 20, observed 2026-05-31) the same day and
  `rt-3` (rj-i1 training 19 of 20, event 2026-05-15) was entered 2026-07-10: all after as_of 2026-06-30, so none of them exists yet. The published figures stay what they were
  (rb-p4a observed 90.00; adoption 8/20 = 0.400000; training 18/20 = 0.900000) and each is listed (`late_recorded_observation_ids`, `adoption.late_recorded`, `training.late_recorded`).

## variant-empty (P09-GOLD-09)

Every entity list empty: every count 0 (accepted and rejected), `empty_population` true, `summary.npv_total`, `double_count_residual`,
`adoption_rate`, `training_completion`, `risk_exposure_total`, `capacity_released_hours_total` and the new `npv_sum_of_initiatives`, `double_counted_amount`,
`double_counted_pv`, `hours_residual`, `capacity_released_hours_double_counted` null, `summary_scenario_id` null, and the
scenario, initiative, group and resource maps empty. Nothing is fabricated as 0.

## DECISIONS (proposed, for the coordinator; each lists the alternative rejected)

* **D-P9-01 Import order and cascade.** Entities are validated parents first (initiatives, baselines, assumptions, resources, scenarios, costs, benefits,
  dependencies, groups, impact mappings, allocations, assessments, observations, training, benefit observations, risks, forecasts); per record: duplicate id,
  then foreign keys (unknown parent -> `UNKNOWN_*`; parent rejected -> `DEPENDENT_REJECTED`), then domain / business rules. A repeat of an accepted
  one-time cost, version, allocation or id rejects the *later* record and keeps the first. *Rejected:* rejecting the whole cost line / version family
  (loses the valid first record and makes replays destructive).
* **D-P9-02 Ramp indexing.** Ramp value for a benefit row = `values[min(period_index - starts_period, last)]` of that row's own `starts_period`; the final value is held
  after the list ends; it multiplies every planned benefit row of the initiative (cash, revenue, avoided cost, capacity hours). *Rejected:* indexing from the
  initiative's `deployment_period` (D-01 says "from starts_period", and rows with different starts would otherwise share one curve).
* **D-P9-03 Benefit-class totals.** Dollars and hours are never added: capacity enters money only as derived converted cash items, `avoided_cost` only when
  `cash_realisation` is true **and** `evidence_ref` is present (true without evidence is accepted but reported beside with `NO_EVIDENCE_REF`).
  *Rejected:* rejecting cash_realisation-without-evidence (D-01 says "reported beside the cash flow", not refused).
* **D-P9-04 Capacity conversion is derived.** If a `capacity_hourly_rate` version with `staffing_change_evidence_ref` exists for the initiative (pinned, else the
  latest), each capacity row becomes a separate derived cash item (hours x rate) citing the assumption id and evidence (`converted_capacity`). *Rejected:*
  requiring the analyst to type the converted amount as an input row (a typed amount can silently disagree with the hours).
* **D-P9-05 Cost variance window.** Planned vs actual are compared over [0, min(horizon, matured periods)); "approved baseline cost" = planned cost rows whose
  `baseline_version` equals the initiative's approved `baseline_version`; null with a reason when no approved baseline, no matured period, or no actual rows.
  `cost_items` gain `cost_key`, `cost_basis` (planned or actual) and `baseline_version`. *Rejected:* comparing actuals to the full-horizon baseline (reports a
  spurious under-spend for periods that have not happened).
* **D-P9-06 Rate conversion and exact rational arithmetic.** (1 + r_annual)^(1/12) - 1 is irrational, so "exact rational NPV" is only possible on a *declared*
  decimal. The conversion is therefore a recorded assumption version (`monthly_rate_conversion`, 6-place decimal, optional `initiative_id`) referenced by
  `scenario_versions.rate_conversion_assumption_id`; NPV is exact rational over that decimal. `rate_basis` is a scenario field; the dataset's `period_basis`
  is top-level. The contract does not require the stored value to be consistent with the declared annual rate (not checked; a reviewer decision).
  *Rejected:* computing the 12th root in the domain (needs floats or an arbitrary-precision root, contradicts D-01).
* **D-P9-07 Payback (superseded by D-P9-25 for the rule; the formats stand).** Over t = 0..H-1 only; interpolated = (t-1) + (-cum[t-1])/(cum[t]-cum[t-1]); null for both paybacks
  and NPV when the initiative has no cost or cash rows in the horizon (nothing to pay back). *Rejected:* payback 0 for an initiative with no flows.
* **D-P9-08 Roadmap.** Feasible start = max(requested start, over prerequisites of: FS -> prerequisite feasible start + its duration + lag; SS -> prerequisite
  feasible start + lag), propagated through the chain; delay = feasible - requested (never negative). The roadmap is reported beside the cash flows and does not
  re-time them. Initiatives gain `requested_start_period`, `duration_periods`, `deployment_period`, `eligibility_rule_version`. *Rejected:* using requested starts of
  prerequisites (understates a chain's delay: init-003 would show 0) and shifting the cash flows by the delay (changes the NPV the golden case pins).
* **D-P9-09 Double count (amended by D-P9-26 and D-P9-27).** Planned = ramped money-class benefit amounts (including derived converted capacity, excluding hours) of the scenario's initiatives within
  the horizon. Rows sharing a `benefit_source_key` in one period across >= 2 initiatives count once at the **largest** claim; the rest is the overlap and the
  residual. Same-initiative repeats are not an overlap. *Rejected:* first-claimant-wins by initiative id (arbitrary) and the smallest claim (hides money the portfolio
  could genuinely attribute).
* **D-P9-10 Readiness.** Latest assessment per dimension at or before as_of (ties by id); `weight` is a decimal on each assessment row; the 5-dimension set is not
  required to be complete (unassessed dimensions are omitted, the count is reported). *Rejected:* demanding all five dimensions (would make a partial assessment
  null, but D-03 says null only when nothing was assessed).
* **D-P9-11 Adoption and training.** Rate of the latest observation / record at or before as_of; zero eligible -> null; the series is kept; rows after as_of are listed and
  excluded; an observation whose `eligibility_rule_version` differs from the initiative's is rejected `ELIGIBILITY_RULE_MISMATCH`; adopted (completed) > eligible rejected.
  *Rejected:* pooling observations of different eligibility rules.
* **D-P9-12 Benefit realization.** Per initiative and type: only matured benefit rows that have an observation (latest at or before as_of) are comparable; planned = ramped
  amount; unobserved matured rows are listed, not counted as 0 observed; baseline trend = sum of `baseline_trend_per_period` of the comparable rows (null when none carries one);
  above-trend = observed - trend, shown beside, never instead of, the raw figure. *Rejected:* treating a missing observation as 0 (null never 0).
* **D-P9-13 Risk exposure.** Null when the initiative has no risk items (unknown, not 0); `risk_items.impact` is a decimal USD string (the data-model text type is
  read through D-02, "impact (USD)"); probability outside [0, 1] rejected `PROBABILITY_OUT_OF_RANGE`.
* **D-P9-14 Scenario pins (amended by D-P9-30).** The assumption version used for (initiative, name) is the one pinned by the scenario, otherwise the latest `version_number` that existed when the scenario was created. Scenarios
  gain `rate_basis`, `rate_conversion_assumption_id`, `status` (draft or proposed), `initiative_ids`, `pinned_assumption_ids`. *Rejected:* failing when unpinned.
* **D-P9-15 Allocation check.** `resource_allocations` are checked in id order against accepted rows of the same resource and roadmap period; the row that would push the sum above
  `capacity_per_period` is rejected with the periods; a sum equal to capacity is allowed. The resource-constrained start therefore equals the dependency-feasible start
  (`resource_delay` 0) in the fixture. *Rejected:* rejecting all rows of the overloaded period (loses valid allocations).
* **D-P9-16 Recurring cost shape.** A recurring cost row carries `start_period` and `end_period` (half-open, `start < end`) and null `period_index`; a one-time row
  carries `period_index` only. Rows past the horizon are dropped from the cash flow (`beyond_horizon` lists benefits). A repeated one-time cost is identified by
  (`initiative_id`, `cost_key`, `cost_basis`).
* **D-P9-17 Forecasts.** `forecast_versions` rows: (`initiative_id`, `version_number`, `period_index`, `amount`, `reason`, `created_at`), one row per period; the
  comparison lists every version, the observed cash values with dates and whether their period is matured. A row repeating a (initiative, version, period) is `VERSION_EXISTS`.
* **D-P9-18 Cycle report.** `details.cycle` starts and ends at the initiative of the rejected edge and follows prerequisite edges; self-dependency is a two-element cycle.
* **D-P9-19 Status domains.** Initiative status in candidate, assessed, in_delivery, adopted, closed; scenario status in draft, proposed. `funded` is rejected
  `STATUS_NOT_ALLOWED` for both.
* **D-P9-20 Formats.** Capacity hours, paybacks and the readiness score are 4-place decimal strings (not proportions, so not 6); every exact rational is also recorded as `n/d`;
  discount factors 6 places plus exact.
* **D-P9-21 Summary block.** `metrics.summary` pools only what can be pooled: scenario NPV total, residual (first scenario in id order), pooled adoption and training
  rates (sums of numerators over sums of denominators, zero-denominator initiatives skipped), risk and capacity totals; paybacks, realization, readiness, variance and delay
  stay per entity. Empty population: all of these null.
* **D-P9-22 Maturity.** A period is matured when its end <= as_of (half-open); observations dated after as_of are ignored.
* **D-P9-23 Baseline correction.** `process_baselines` carry `baseline_version`, `evidence_ref`, `measured_at` and an optional `reason`; the initiative's `baseline_version` names the
  approved set and later versions (pb-202 v2) stay readable but unused until approved.
* **D-P9-24 Impact mappings.** `impact_mappings` (mapping_id, initiative_id, group_id, operating_change, impact_level) are validated and counted; no numeric metric is derived.

## DECISIONS of review 9 (D-P9-25..D-P9-38; contract D-09; each lists the alternative rejected)

* **D-P9-25 Payback is the last crossing.** The integer payback is the first period t after the last negative cumulative, provided the cumulative stays >= 0 for every later
  period of the horizon; interpolated as before (always t >= 1, so no 0.0000). A cumulative of exactly 0 is back (>= 0). A series that is never negative has no investment:
  null with `reason` `NO_INVESTMENT`; one that ends negative: null, `NOT_RECOVERED`; no cost or cash row at all: null, `NO_FLOWS`. *Rejected:* the first t with cumulative >= 0
  (reports 0 for a first flow of zero and ignores a later dip).
* **D-P9-26 Attributable totals.** `npv_total` is the sum of the initiative NPVs less `double_counted_pv`, the present value (each period at its own discount factor) of the
  removed shared claims that enter the cash flow; `double_counted_amount` (= the residual) and `double_counted_pv` are published beside it with `sum_of_initiatives`. The class
  totals of the portfolio subtract the removed claims by class (`double_counted_by_class`). *Rejected:* a note beside a total that still counts the claim twice.
* **D-P9-27 Hours are a second double-count rule.** Capacity rows (converted or not) sharing a `benefit_source_key` in one period across two or more initiatives count once at the
  largest hours; `hours_residual` per overlap and in total; `explanation_required` is true for either residual (`explanation_required_for`). `summary.capacity_released_hours_total`
  counts the released hours of initiatives that share a capacity key once, at the largest. *Rejected:* adding hours to dollars to reuse the money rule.
* **D-P9-28 Evidence is words.** An evidence reference (baseline, assumption, staffing change, benefit, benefit observation) is stripped and, when present, non-blank
  (`EVIDENCE_REQUIRED`); the cash flow tests the stripped text. *Rejected:* accepting "   " as evidence.
* **D-P9-29 One key, one kind of cost.** A `cost_key` used as one_time and as recurring for the same initiative and basis is `COST_KEY_BASIS_CONFLICT`. *Rejected:* letting a
  one-time cost be retyped as recurring under its own key.
* **D-P9-30 A scenario is built on its own past.** Its figures use the cost and benefit rows recorded by its `created_at` (`recorded_at`; absent: part of the loaded world) and, per
  assumption name, the pinned version or else the latest version created by then. *Rejected:* recomputing an old scenario from today's plan.
* **D-P9-31 Deployment before the feasible start is reported.** `roadmap.warnings` carries `DEPLOYMENT_BEFORE_FEASIBLE_START`; the cash flow is not re-timed (D-P9-08).
* **D-P9-32 Exact aggregates.** Every total is an exact sum rounded once (never a sum of rounded rows); `latest_minus_original` is the difference of exact totals, published only when the
  latest version covers the original's periods (`revisions_cover_original_periods`), `original_preserved` is read from the stored rows.
* **D-P9-33 Observations carry two instants.** The event time (`observed_at`) and the server-recorded time (`recorded_at`; training: `entered_at`). At as_of an observation exists only when
  both are <= as_of; one recorded later is listed (`late_recorded`); a same-day tie goes to the later record. *Rejected:* letting a back-dated entry rewrite an earlier as_of.
* **D-P9-34 Partial trend coverage.** `observed_above_trend` is published only when every compared row carries a trend; otherwise null, with `trend_coverage.rows_without_trend` and the
  warning `PARTIAL_TREND_COVERAGE` when some rows do.
* **D-P9-35 A period start has a day <= 28** (`PERIOD_START_INVALID`), so that every month has it.
* **D-P9-36 Out-of-range proportion.** An error rate outside [0, 1] is `INVALID_FIELD` (field named), not `INVALID_AMOUNT`.
* **D-P9-37 Shared claims keep their class.** Each claim in an overlap names its `benefit_class` and whether it `enters_cash_flow`; among equal claims the one that enters the cash flow, then the
  smaller (initiative, benefit), is the one that counts.
* **D-P9-38 Probes.** The probe block of variant-rejected pins the three series the first-crossing rule got wrong (never negative, dips again, ends negative), a scenario built before a later cost, a
  partial trend, hours claimed twice and observations recorded after as_of.

## Gaps and tensions found in the contract (none blocking)

1. D-01 "exact rational arithmetic" and "(1 + r)^(1/12) - 1" cannot both hold (D-P9-06).
2. Section 03 types `risk_items.impact` as text while D-02 multiplies it as USD (D-P9-13).
3. D-01 does not say whether a ramp is indexed from the row's `starts_period` or the initiative deployment (D-P9-02); the fixture is constructed so the answer matters (b-203 starts at 2).
4. D-02 does not say whether cost variance is compared over unmatured periods (D-P9-05).
5. D-03 "feasible start" does not say whether to propagate feasible or requested starts of prerequisites, or whether the delay may be negative (D-P9-08).
6. D-01 does not say which of the shared claims counts (D-P9-09).

## Not exercised

Change of `period_basis` to monthly in the golden file (only in the variant); an unramped initiative with a ramp assumption that is not pinned (the unpinned-version-as-of-created_at rule is covered by the backend tests and the generated world); a ramp longer than the number of
periods; benefit rows beyond the horizon (`beyond_horizon` is always empty); `from` / `to` window parameters of the metrics endpoint other than the matured clip; baseline approval
by role, `BASELINE_FROZEN` (rewriting rows of an approved version) and the audit trail; resource-levelling start shifts and a non-zero `resource_delay`; ties in the double-count rule
(two equal claims) and three or more claimants; consistency of the declared monthly conversion value with the declared annual rate; the SQL, workbook, API envelope, idempotency and
role behaviour (this fixture is domain-only); impact mapping metrics; proposal state transition (`select-scenario`); observations of capacity beyond hours; negative amounts.
