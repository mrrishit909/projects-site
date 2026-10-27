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

## D-05 Fixture decisions (adopted from the golden fixture, P09-GOLD-11)
Adopted verbatim from `tests/fixtures/golden/CALCULATION.md` DECISIONS D-P9-01..24; the fixture and `reference_check.py`
are the binding form. The points that sharpen D-01..D-04:
* **Import order (D-P9-01):** parents first; per record duplicate id, then foreign keys (`UNKNOWN_*` / `DEPENDENT_REJECTED`),
  then rules; the later of two repeated records is rejected.
* **Ramp (D-P9-02):** `values[min(period − starts_period, last)]` indexed from each benefit row's own `starts_period`, last
  value held. **Avoided cost (D-P9-03):** enters the cash flow only with `cash_realisation` true **and** an `evidence_ref`;
  otherwise reported beside it, never refused. **Capacity conversion (D-P9-04):** a derived cash item (hours × rate) citing
  the assumption and evidence. **Monthly rate (D-P9-06):** the converted monthly rate is a declared 6-place decimal
  assumption version (the twelfth root is irrational); NPV is exact rational over that decimal.
* **Cost variance (D-P9-05):** over `[0, min(horizon, matured periods))` against the planned rows whose `baseline_version`
  equals the initiative's approved one; null without an approved baseline, a matured period or actuals. **Matured
  (D-P9-22):** a period whose end ≤ as-of; observations after as-of are ignored.
* **Payback (D-P9-07):** first t with cumulative ≥ 0, interpolated `(t−1) + (−cum[t−1]) ÷ (cum[t] − cum[t−1])`, 0.0000 at
  t = 0, null when never crossed; NPV and paybacks null when there are no flows.
* **Roadmap (D-P9-08):** feasible start = max(requested start, prerequisite constraints) propagated through the chain
  (FS: predecessor feasible start + duration + lag; SS: predecessor feasible start + lag); delay never negative; the roadmap
  does not re-time cash flows. **Allocations (D-P9-15):** checked in id order; the row that crosses capacity is rejected with
  its periods; a sum equal to capacity is allowed.
* **Double count (D-P9-09):** benefits sharing a key in one period across two or more initiatives count once at the largest
  claim; planned is the ramped money-class total, hours excluded.
* **Readiness (D-P9-10):** latest assessment per dimension at or before as-of, per-row decimal weights, incomplete sets
  allowed. **Adoption and training (D-P9-11):** latest record at or before as-of; zero eligible gives null; an eligibility
  rule-version mismatch is rejected. **Realization (D-P9-12):** matured rows with an observation only; unobserved rows listed,
  never counted as 0; trend = Σ `baseline_trend_per_period`.
* **Risk (D-P9-13):** `risk_items.impact` is a USD decimal string (clarifying the section-03 text type); null without items;
  probability outside [0, 1] is `PROBABILITY_OUT_OF_RANGE`. **Assumptions (D-P9-14):** the scenario's pinned version, else the
  latest. **Costs (D-P9-16):** recurring rows carry a half-open `[start_period, end_period)` and null `period_index`; a repeated
  one-time cost is identified by (`initiative_id`, `cost_key`, `cost_basis`). **Forecasts (D-P9-17):** one row per
  (initiative, version, period); a repeat is `VERSION_EXISTS`. **Cycles (D-P9-18):** reported from the initiative of the
  rejected edge; a self-dependency is a two-element cycle. **Statuses (D-P9-19):** initiative candidate | assessed |
  in_delivery | adopted | closed; scenario draft | proposed; "funded" is `STATUS_NOT_ALLOWED`.
* **Formats (D-P9-20/21):** hours, paybacks and readiness as 4-place strings with every exact rational also recorded as
  `n/d`; `metrics.summary` pools only what can be pooled and is null on an empty population. **Baselines (D-P9-23):**
  `process_baselines` carry `baseline_version`, `evidence_ref`, `measured_at`, optional `reason`; a later version stays
  readable but unused until approved. **Impact mappings (D-P9-24):** validated and counted only.
* **Not proven by the fixture:** golden on monthly periods, benefit rows beyond the horizon, metric windows beyond the matured
  clip, baseline approval by role and the immutability of an approved baseline, resource-levelling shifts, ties and three
  claimants in the double-count rule, the C07 proposal transition, API envelopes and idempotency; the backend tests carry them.

## D-06 Backend clarifications (adopted from the backend hand-back; the 23 numbered assumptions are in README.md)
* `/metrics` returns `{as_of, window, scenario_id, period_basis, period_start, empty_population, ingest, metrics}`;
  `period_basis` and `period_start` live in the one-row `dataset_config`; default `as_of` is the server's now. Rows dated
  after `as_of` (adoption, training, readiness, observations, forecast versions) do not exist yet; a scenario's plan rows
  and assumption versions are those recorded by its `created_at` (D-09 R9-01). The window narrows observations by instant and cost variance and realization by period
  start; the dated model is not windowed (`MODEL_NOT_WINDOWED`).
* Metrics use the initiative's current approved baseline; a scenario's `baseline_version` is its label and
  `BASELINE_VERSION_DIFFERS` is returned when they differ. One baseline row per (initiative, version); a second row for
  an approved version is 409 `BASELINE_FROZEN`, for an unapproved one 409 `VERSION_EXISTS`; correcting an approved
  baseline needs a reason; approving a superseded version is 409 `ALREADY_APPROVED`; C01 refuses assumption-like
  fields with 422 `ASSUMPTION_IN_EVIDENCE`.
* Clients never supply instants; evidence dates are plain dates (`measured_on`, `observed_on`, never in the future);
  only the seeder enters back-dated history. Reserved assumption names: `adoption_ramp`, `target_minutes_per_case`,
  `capacity_hourly_rate`, `monthly_rate_conversion`; version numbers server-assigned unless sent; author = actor.
  Ranges: discount rate 0..1, horizon 1..600, periods 0..100000, decimals ≤ 14 integer and 6 decimal digits.
* C02 is an exact, versioned weighted-score ranking aid and may create a candidate initiative; C03 is all-or-nothing
  and always creates a new `scenario_id`, writing `expanded_costs`; C04 refuses non-synthetic stakeholder labels
  (`LABEL_NOT_SYNTHETIC`); C06 checks allocations in the order sent (no resource levelling: the resource-constrained
  start equals the dependency-feasible start); C07 accepts only `proposed`, computes the residual at the server's now,
  stores the explanation and the comparison, and a proposal is final; C08 may carry a training block as a separate
  series; C09 requires the benefit's unit and only `observed_not_attributed`; C10's first forecast is version 1.
* Identity (401) and role (403) are checked before the body; the C01 approve role after the body with a refusal
  audit row. Reads also expose `baseline_approvals`, `opportunity_scores`, `expanded_costs`, `rejected_records`,
  `audit_events`, `dataset_versions`. Extra ingest codes `MALFORMED_RECORD`, `INVALID_*`, `RATIONALE_REQUIRED`,
  `EVIDENCE_REQUIRED` (README). The SQL reference runs with `SET jit = off`; its NPV is compared within 0.000001 USD
  (the bound is stated in D-09 R9-20), every other figure exactly.
* **Partial trend coverage:** `observed_above_trend` is published only when every observed matured row of the benefit type
  carries a recorded trend; otherwise it is null and the warning `PARTIAL_TREND_COVERAGE` lists the rows without one
  (implemented in every implementation by D-09 R9-13).
* **Reference fix (coordinator):** `reference_check.py` now orders instants by parsed value, not string (the domain
  already does); the fixture carries no fractional seconds, so no figure changed.
* Gaps: no resource levelling; the double-count rule is enforced by C07, not a trigger (the database forbids
  `funded`); initiative status moves only candidate → assessed; no command edits or removes plan rows; the workbook and
  export belong to the artifacts; `/metrics` is unpaged and recomputed per call.

## D-07 Synthetic world (adopted from the generator hand-back; the 9 numbered assumptions are in the manifest and generate.py)
Seed 20261026; 36 monthly periods 2026-01 .. 2028-12, `as_of` 2026-10-05T00:00:00Z (9 matured periods); the brief's
counts exactly (24 initiatives in 4 programmes, 30 baselines, 160 assumption versions, 900 cost and 700 benefit items,
40 dependencies, 8 resources, 60 groups, 300 readiness assessments, 500 adoption observations, 200 training
completions, 400 benefit observations, 120 risks, 30 scenarios, 12 forecast version sets = 144 rows) plus 106 impact
mappings and 557 allocations; 2,747 primary objects and 1,544 linked events reported separately; `dataset_version`
cw-20261026-20261026, `dataset_hash` 6bf7ebaa…, `generated_at` = `as_of`; 978,954 bytes published.
* Benefits are recognised for 12 periods per stream and recurring costs over the same window (700 rows cannot cover
  36 periods for 24 initiatives), so NPV and payback describe the twelve-period benefit window (the shorter streams run for fewer periods) and the site says so,
  never "first-year" (D-09 R9-17). Every initiative
  carries a planned discovery cost in period 0 (2 % of its one-time cost); see the payback note below. All 30 world
  scenarios are `draft` (the seeder cannot load `proposed_at`; proposing is shown by the C07 replay). Annual rates carry
  `monthly_rate_conversion` versions; two rates are declared monthly. Baseline trends are recorded on every benefit
  row (partial coverage never fires). Programme membership lives in `manifest.programmes`. Eligibility rules
  `elig-v1`, and `elig-v2` for two initiatives. Seven sizes were padded or trimmed to the brief's counts and are
  disclosed; replay row ids never appear in the world.
* Designed relationships, realised by the domain: DR-01 `init-009` has capacity as its only benefit (2,920.49 h not
  converted, cash 0.00, NPV −761,535.73, payback null); DR-02 `init-001` and `init-002` share `src-fin-ap-shared-team`
  (planned 32,677,894.70, attributable 32,470,748.38, residual 207,146.32 over periods 3..12 in `scn-025`); DR-03
  `init-015` never pays back (benefit-to-cost 0.620043; both paybacks null in all 8 scenarios); DR-04 `init-003`
  forecast versions 1, 2, 3 (745,800.06 → 598,900.05 → 534,207.54, original kept, each revision after observed periods
  more than 10 % below); DR-05 `res-03` at 2.00 of 2.00 FTE in periods 14..16 with three 0.50 requests refused
  `RESOURCE_OVERALLOCATED`; DR-06 `init-008` realisation 0.975795 with the baseline trend 0.848744 of the observed
  improvement (true attributable share 0.150000, in `synthetic_truth` only); DR-07 adoption reaches 50 % four to six
  periods after 90 % training, six initiatives still below (training 0.888443 vs adoption 0.532881).
* Injections INJ-01..12 map to P09-TEST-01..12 with dataset checks and replay events (`DOUBLE_COUNT_UNEXPLAINED`,
  `ATTRIBUTION_NOT_ESTABLISHED`, `STALE_FORECAST_VERSION` among the refusals); INJ-08 and INJ-12 are dataset-only.
* Outcome-informed choices, disclosed in the manifest: the period-0 discovery cost, normalised benefit shares, the
  `init-002` volume floor, extra observation readings, the adoption-ramp range 270–340 days, the D4 second performance
  70 → 66 %, the second revision date 10 → 12 June.
* **Payback rule note (coordinator, for the fix round T-09-05 with the review):** D-P9-07 lets a cumulative of 0 at
  t = 0 count as paid back, so an initiative whose first flow comes later would report payback 0.0000. The rule becomes:
  payback is the first t with cumulative ≥ 0 after the cumulative has been negative; a flow series that never goes
  negative has payback null with reason `NO_INVESTMENT`. The world's period-0 discovery cost keeps every published
  payback honest until then; the golden case (−1,000 at t = 0) is unaffected.
* Gaps: `data/seed.py` cannot load a `proposed` scenario; no generator README beyond the module docstring and the
  manifest disclosures.

## D-08 Site decisions (adopted from the web hand-back; the 14 numbered assumptions are in the web README / evidence page)
* The mirror follows the Python domain exactly, including the payback rule (last crossing, D-09 R9-12) and the
  `PARTIAL_TREND_COVERAGE` warning (D-09 R9-13); `scripts/snapshot-reference.json` is regenerated from the domain.
* The golden copy lives in `public/golden/` (byte-identical to the fixture, checked by the golden check). The default
  scenario is `scn-025`, the one carrying the designed relationships; every page has a scenario picker.
* **Confidence** (portfolio page) is a printed four-point assessment (approved baseline; matured benefits with an
  observation; an adoption rate; actual cost reported): strong 3–4, partial 2, thin 0–1; labelled an assessment, not a
  probability. The portfolio chart compares costs with the benefits that enter the cash flow (D-01), never a sum across
  the four classes; sums across initiatives are exact rational sums rounded once.
* The sensitivity lab runs the domain with three overrides (rate, ramp preset, cost scale); the twelfth-root monthly
  conversion uses exact integer search and equals a 60-digit Decimal calculation on 61 rates; a rate on the wrong basis
  is refused `RATE_PERIOD_MISMATCH`. Roadmap edits and the "propose" action replay the domain's validator and C07
  (`DOUBLE_COUNT_UNEXPLAINED` without an explanation; a proposal is final in the session).
* The synthetic attributable share appears only as a disclosure (benefits and evidence pages) and the golden check
  asserts it is absent from the domain inputs. A JSON number such as `1.0` cannot be told from `1` in JavaScript, so
  only fractional floats are rejected (the database echo of a rejected row keeps the original number text, D-09 R9-22); a numeric `amount` is `MALFORMED_RECORD`. Python `strip()` and code-point
  ordering are mirrored explicitly; instants are BigInt microseconds. The Playwright preview port honours `PW_PORT`.

## D-09 Review fixes (adopted from review R9)
* **R9-01 Scenario figures as of `created_at`.** A scenario's figures come from the cost and benefit rows recorded by its `created_at` (every cost
  and benefit row carries a server `recorded_at`; a row without one is always included) and from the latest assumption version created by then, unless pinned.
  C07 stores a snapshot hash (`snapshot.py`, sha-256 over the resolved inputs) in `scenario_versions.snapshot_hash`; a proposed scenario is served from
  that snapshot and `/metrics` reports `snapshot_verified` and `figures_equal_the_stored_comparison`. `scenario_pins` and `scenario_initiatives`
  are frozen by trigger once a scenario is sealed (`initiatives_expected`, `pins_expected`). Rejected: a copy of the computed figures per scenario (a second source of
  truth that can drift from the rows).
* **R9-02 Attributable totals.** `npv_total` is the sum of the initiative NPVs less the present value of the claims that count twice
  (`double_counted_pv`); the plain sum (`sum_of_initiatives`) and `double_counted_amount` sit beside it, and class totals are attributable class by class.
  The portfolio and business-case pages show the attributable total first. Rejected: keeping the plain sum as the headline with a footnote.
* **R9-03 Hours overlap.** The overlap rule also runs on capacity hours (`hours_residual` per shared key, `hours_overlaps`); `explanation_required` is true for either
  residual and C07 needs the explanation for either; `capacity_released_hours_total` is attributable. Rejected: converting hours to money to reuse the money rule
  (hours are never added to dollars, D-01).
* **R9-04 Evidence references** are stripped and non-blank (`EVIDENCE_REQUIRED`) in the API, domain, TypeScript mirror, SQL (CHECK and reference) and `reference_check.py`.
* **R9-05 Cost key basis.** One `cost_key` has one basis: `COST_KEY_BASIS_CONFLICT` (domain, trigger `cost_items_key_guard`, reference). The P09-TEST-11 recover path uses a new key
  with a stated reason. Rejected: silently re-keying the later row.
* **R9-06 Deployment before feasible start.** The warning `DEPLOYMENT_BEFORE_FEASIBLE_START` is in the metrics tree (`roadmap.warnings`) and on the portfolio, roadmap and
  business-case pages; the cash flow is not re-timed. The manifest discloses the three affected initiatives (init-018, init-019, init-020). Rejected: moving the cash flow to the feasible start (it would
  change recorded plan rows).
* **R9-07 Exact sums, rounded once.** Aggregates are exact sums rounded once, never sums of rounded rows (DR-01 hours 2,920.48; scn-025 unconverted hours 145,045.62).
* **R9-08 DR-05 periods** are computed by the domain (12 to 16) and the site claims check asserts the full set.
* **R9-09 DR-03 names its scenario.** Every ratio of a designed relationship names its scenario: 0.531465 on the ramp-v2 scenarios (scn-015, 018, 025, 026) and 0.620043 on the others.
* **R9-10 Forecast revisions.** A revision must cover every period of the original: `REVISION_PERIODS_INCOMPLETE`; `original_preserved` is derived from the stored rows.
* **R9-11 Observation dates.** `observed_on` lies within [the initiative's first period start, the server date] (`OBSERVED_BEFORE_START`). Every observation has a server
  `recorded_at`; as-of filtering uses it, `late_recorded` lists what was recorded after the as-of, and same-day ties are broken by `recorded_at`.
* **R9-12 Payback** is the last crossing from below zero; a never-negative series has a null payback with reason `NO_INVESTMENT` (`NOT_RECOVERED`, `NO_FLOWS` otherwise), in Python, SQL,
  TypeScript and the reference. Three reviewer series are pinned in the variant-rejected probe block. Rejected: keeping "first period at or above zero" (it reports 0 for a series that never needed paying back).
* **R9-13 Partial trend coverage:** `observed_above_trend` is null with `PARTIAL_TREND_COVERAGE` unless every observed matured row carries a trend (pinned in a probe).
* **R9-14 Period start** day must be at most 28 (`PERIOD_START_INVALID`) in the domain, the mirror and a database CHECK (`dataset_config_day_ck`).
* **R9-15 Test counts.** README and site state the true count of the final run (the review expected 399; tests were added, so the figure is the one in the README).
* **R9-16 Training against adoption** is compared on the common population and the counts are stated: eleven initiatives have both series; five reached half adoption with lags 4, 4, 5, 5, 6 periods; six have not yet.
* **R9-17 Window wording.** The site says "within the twelve-period benefit window" and lists the shorter streams; "first-year" is gone.
* **R9-18 Outcome-informed choices.** The case-study route lists the trend-share design choice. DR-02 is worded as the main site: of the portfolio's 32,677,894.70 of money-class benefits (including the
  4,025,383.47 shown beside the flow) only 32,470,748.38 are attributable once. The main site's own `project.json` is outside this app.
* **R9-19 Not built** lists the declared uncertainty ranges and the workbook and executive recommendation.
* **R9-20 SQL NPV bound.** The SQL reference computes S_t / q^t with exact recursion (no `power()`); its NPV is exact to 0.000001 for horizons up to 36 periods and 14-digit amounts, tested on the
  published world and on a 14-digit case. Rejected: widening `NPV_TOLERANCE`.
* **R9-21 Contrast.** The brass text is `#6b5329` (at least 4.5:1 on every wash) and the current nav number is `#1d1608` on brass; an e2e test measures every text node under 18 px on every route at 1280 px (disabled controls excepted).
* **R9-22 Small rules.** C07 explanations need at least 20 characters (`EXPLANATION_TOO_SHORT`); `expected_version` is required on C10 (0 when there is none); `from = to` is an empty window everywhere;
  `error_rate "1.5"` is `INVALID_FIELD`; the rejected-record echo keeps the original number text (the seeder reads numbers with their lexeme).

## Mode disclosure
Mode A: Python domain + PostgreSQL + FastAPI verified on hosted runners. Mode B: TypeScript mirror over the published
snapshot; the sensitivity lab, roadmap edits and scenario selection are browser-memory simulations and say so.
