# ProductSignal — business contracts, version 1 (2026-10-26)

Decision owner: coordinator (Fable 5.1). Spec: `projects/06-productsignal.md`, SHA-256
`ed0d0941…cfbd6` at pack commit `fe5f7981` (verified against `docs/program/source-pack.json`). Rules cite the
requirement they satisfy; changing one bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
Should an onboarding change ship, stop, or receive more investigation? (P06-GOAL-01). Primary users: a product analyst
and an experimentation analyst. Non-goals: no automatic product release from a decision (P06-FLOW-10), no causal claims
from observational feature correlations (P06-DOMAIN-05), no chatbot and no paid inference (P06-GOAL-11).

## D-01 Events, identity and tracking quality
* Canonical events are deduplicated on `event_id`; a re-sent event with a different `event_id` but the same
  (`user_id`, `event_name`, `event_at`) and identical properties is a duplicate, dropped and counted (P06-FLOW-01,
  P06-TEST-05). `event_at` is the business instant (UTC); `received_at` is when the log accepted it. A run at cutoff
  `C` uses only events with `received_at` ≤ C; a late event changes a later run, never a published one: results carry
  the cutoff and `config_hash`, and a revision is disclosed as such (P06-TEST-06, P06-MET-xx-R27).
* Identity resolution is time-aware and deterministic (P06-FLOW-02, P06-TEST-07): an `identity_link` attributes the
  anonymous events of `anonymous_id` to `user_id` only for events with `event_at` ≥ `linked_at`; events before the
  link stay anonymous. Signup conversion (P06-MET-01) is therefore measured on the visitor unit: distinct
  `anonymous_id`s with a `visit` event in the window are the denominator, those with a `signup` event (same
  `anonymous_id`) within the window the numerator; the identity denominator is documented beside the figure.
* Excluded everywhere: users with `bot_flag`, accounts with `internal`, events whose `user_id` is unknown (no user and
  no link); each exclusion is counted and shown when it changes a figure materially (P06-MET-xx-R11/R12). A delayed
  event is one with `received_at` − `event_at` > 24 h; delayed, duplicate and unknown-identity counts are the
  tracking-quality figures (P06-UI-04).

## D-02 Units, cohorts and maturity
* The experiment and retention unit is the **account** (P06-DOMAIN-01): user-level events roll up to the account
  before any ratio; a metric over accounts never counts users (P06-MET-07-R04, P06-TEST-01). Signup of an account =
  the earliest `signup` event of its non-bot users; `signup_at` is that instant.
* Activation (P06-MET-02): an account with an `activated` event within 7 × 24 h of `signup_at`, half-open
  [signup_at, signup_at + 7 d). A signup is **mature** when `signup_at` + 7 d ≤ cutoff; immature signups are excluded
  and counted (P06-TEST-04). Golden (P06-GOLD-01): 20/100 and 30/100 mature assigned accounts.
* Day-7 retention (P06-MET-04): an account is retained on day 7 when a session of one of its users starts on the
  seventh calendar day after the signup day **in the account's IANA timezone** (day 0 = signup day); "on or after day
  7" is a separate figure, never mixed in (P06-TEST-12). Maturity: day 8 has begun in that timezone at the cutoff.
  Golden: 5 of 20 mature accounts = 0.2500. Week-4 retention (P06-MET-05): a session on any of calendar days 28–34
  in the account timezone; mature when day 35 has begun.
* Funnel (P06-FLOW-03, P06-MET-03): a versioned definition of ordered steps with a maximum gap; a unit reaches step
  k only if it reached step k − 1 earlier (strict order, same unit) and within the gap; step conversion = units at k ÷
  units at k − 1; the window applies to the first step; exclusions are listed with the result.
* Feature adoption (P06-MET-06): eligible active accounts (a session in the window, eligibility decided without any
  treatment outcome) using the feature ÷ eligible active accounts.

## D-03 Experiments
* Assignment is by account, idempotent per (`experiment_version_id`, `unit_id`): the first assignment fixes the
  variant; a later assignment of the same unit to another variant is rejected `ASSIGNMENT_CONFLICT` (P06-FLOW-04).
  An exposure must reference an assignment and satisfy `exposed_at` ≥ `assigned_at`; otherwise it is rejected
  `EXPOSURE_BEFORE_ASSIGNMENT` (P06-FLOW-05, P06-TEST-11).
* Primary analysis is intention-to-treat (P06-DOMAIN-02): every assigned mature unit counts in its assigned variant
  whether or not exposed; exposure rate (P06-MET-09) = exposed assigned units ÷ assigned units and is reported beside
  the ITT result; an exposed-only analysis is labelled exploratory and never a decision basis (P06-TEST-02 covers
  treatment-dependent exclusion: exclusions must be decided from pre-assignment facts only).
* Sample ratio (P06-MET-10): a chi-square goodness-of-fit statistic of observed assignments against the prespecified
  allocation, with p-value; verdict `MISMATCH` when p < 0.001, `INSUFFICIENT` when any expected cell < 5, else `OK`;
  a `MISMATCH` result is shown before any lift and blocks a `ship` decision (P06-DOMAIN-04, P06-TEST-08).
* Lift (P06-MET-07/08): conversion per variant = activated mature assigned units ÷ mature assigned units (proportions
  in [0,1], 6 dp); absolute lift = treatment − control in percentage points (signed); relative lift = absolute ÷
  control, **null when control is 0** (P06-TEST-10). Interval: Newcombe hybrid score interval at 95 % (z = 1.959964)
  on the difference, square roots exact to 1e-8; a result is `conclusive` only when the interval excludes 0 and the
  analysis run is at or after `planned_end` of a frozen plan. Golden: 0.2000 vs 0.3000, absolute 0.1000 (10.00 pp),
  relative 0.500000, interval includes 0, so not conclusive (P06-GOLD-01).
* The analysis plan (primary outcome, guardrails, horizon = `planned_end`, allocation) is frozen before any outcome
  is read: `config_hash` is written by C06 and every analysis run cites it; a run before the freeze is refused
  (P06-FLOW-06, P06-DOMAIN-03). Every run is logged; a run before `planned_end` is `interim` and cannot support
  `ship`; the count of prior runs is shown with every result (P06-TEST-03).
* Guardrail error rate (P06-MET-11): assigned units with a `product_error` event inside the prespecified window ÷
  eligible assigned units, per variant. Revenue per assigned account (P06-MET-12): eligible subscription revenue
  (USD, Decimal, subscriptions with `starts_at` in the window, status active or ended) ÷ assigned accounts, per
  variant, with a t-interval over account-level values (the account is the cluster).
* Segment analysis (P06-UI-08) is exploratory: every segment result carries the label, the number of segments tested
  and a Bonferroni-adjusted threshold; no decision cites a segment (P06-DOMAIN-06, P06-TEST-09).
* A decision (C10) is `ship`, `stop` or `inconclusive`, cites one analysis run and the guardrail review, requires a
  frozen plan and a non-`MISMATCH` sample ratio, and never changes any product state (P06-FLOW-09/10).

## D-04 Numbers, time and absence
Proportions are decimal strings with 6 places in [0,1]; percentage points with 2 places, signed; counts nonnegative
integers; money Decimal strings with 2 places (USD); null means unknown or zero denominator, never 0. Instants are UTC
with `Z`; calendars use the account's IANA timezone. Windows are half-open [from, to) on the metric's stated timestamp.
Empty population: every count 0, every ratio null, `empty_population` true.

## Mode disclosure
Mode A: Python domain + PostgreSQL + FastAPI verified on hosted runners. Mode B: TypeScript mirror over the
published snapshot; the registry and decision screens' actions are browser-memory simulations and say so.

## D-05 Fixture-driven clarifications (2026-10-26, adopted from A-039; full text D-P6-1..25 in tests/fixtures/golden/CALCULATION.md)
Rounding ROUND_HALF_UP once on unrounded values. Added fields beyond the specification's minimum: `accounts.timezone`
(IANA), `events.anonymous_id` with `events.user_id` nullable, `subscriptions.amount_usd`. Unknown identity = a
`user_id` that is no user, or neither id present; an unlinked anonymous visit is valid. Event processing order:
received by cutoff, dedupe, unknown, bot, internal; events received after the cutoff are reported separately from
delayed (> 24 h strictly). Duplicate key (user_id or anonymous_id, name, event_at, property set); earliest
received_at wins. Funnel unit is the visitor key anchored on the earliest visit in the window; gap inclusive; strict
order; no re-anchoring; signup conversion has no gap and may differ from the funnel's first step. Activation window
[signup, +7 d), maturity inclusive (signup + 7 d ≤ cutoff; an activation at exactly +7 d does not count). Retention
day index on the local calendar date; cohorts by local signup date; sessions roll up to the account; bot and internal
sessions ignored. Feature-adoption eligibility: plan in {team, business} and at least one non-bot session in the
window. SRM over all accepted assignments, Σ(o−e)²/e, p = erfc(√(stat/2)) by a Decimal series; verdict order
INSUFFICIENT, MISMATCH, OK; empty population INSUFFICIENT with null numbers. Newcombe is treatment − control with a
closed interval for "includes 0"; `conclusive` also needs a non-interim run and a valid plan hash. Revenue t-interval
per variant over all mature assigned accounts (zeros included, df = n − 1, two-sided, null for n < 2). Exposure rate
over mature assigned accounts; guardrail window [assigned_at, +7 d). `config_hash` = sha256 of the key-sorted compact
plan JSON without the hash; `plan_frozen` means frozen_at ≤ earliest run; `interim` means cutoff < planned_end.
Rejection codes: ASSIGNMENT_CONFLICT, EXPOSURE_BEFORE_ASSIGNMENT, DEPENDENT_REJECTED, UNKNOWN_ASSIGNMENT. Golden:
Wilson control [0.133367, 0.288829], treatment [0.218949, 0.395849], Newcombe difference [−0.020249, 0.216734].
Provenance note: expected.json was emitted by the reference script after agreeing with a separate float cross-check
and the hand arithmetic in CALCULATION.md; the independence rests on those two. Unpinned: DST edges, three or more
variants, segment analysis, a run before the freeze, interim presented as final, a Welch difference of revenue means.

## D-06 Backend clarifications (2026-10-26, adopted from A-041/A-043; the 16 numbered assumptions are in README.md)
The event log is append-only; C01 stamps `received_at` with the API clock (admin may backfill); a re-sent `event_id`
is idempotent when the content matches and rejected when it differs. Extra rejection codes: MALFORMED_RECORD,
DUPLICATE_ID, UNKNOWN_ACCOUNT, UNKNOWN_USER, UNKNOWN_EVENT, UNKNOWN_EXPERIMENT_VERSION, UNKNOWN_UNIT, UNKNOWN_VARIANT,
INELIGIBLE_UNIT, INVALID_INTERVAL, IDENTITY_CONFLICT, UNSUPPORTED_UNIT_TYPE; rejected rows are kept raw. Default
windows: signup conversion, funnel and feature adoption the 7 days before the cutoff; activation 28 days; retention
cohort the seven local dates ending 35 days before the cutoff date; feature adoption uses `export` for plans team and
business. Internal accounts are ineligible for assignment (422); exactly two variants with allocation summing to 1.
Only `active` and `ended` subscriptions carry revenue (USD). C06: one frozen plan per version, never edited
(PLAN_ALREADY_FROZEN); unit_type, planned_end and primary_metric must match the version; frozen_at defaults to now and
may not be in the future; refused once any run exists (OUTCOME_ALREADY_READ); a plan with unit_type "user" is 422
UNIT_MISMATCH. C08 refuses a non-account unit, a non-ITT analysis and exclusions outside plan, segment, timezone and
internal; a pre-assignment exclusion is applied, disclosed and blocks ship (PLAN_DEVIATION); a later run that includes
late events carries a `revision` block and never rewrites the earlier result. Segments: only those with both arms,
`segments_tested` counted, threshold alpha ÷ count, pooled-z p-value, Newcombe at the adjusted z. C09: HARMFUL when the
whole Newcombe interval of the error-rate difference is above 0, INSUFFICIENT when a variant has no eligible unit, else
OK. C10: one decision per run; the review must belong to the run; ship is blocked by an interim run, SRM MISMATCH, a
HARMFUL guardrail, a plan deviation or a config-hash mismatch; **coordinator decision:** SRM MISMATCH also blocks `stop`
(the data cannot support either direction; only `inconclusive` is allowed); a ship on a non-conclusive final run is
allowed with a NOT_CONCLUSIVE warning; a refused decision leaves a `record-decision-refused` audit row. The Student t
table covers df 1..2000 at 95 % (the SQL interval is null outside it). GET /metrics defaults the cutoff to the API clock;
group_by splits account-based metrics only; `dataset_version` is the latest `dataset_versions` row ("unversioned" if
none). Known: the DB suite takes about 3 minutes; the deadlock retry is tested by injection, not a real deadlock;
variant-empty is covered through the domain and SQL, not the API replay; DST edges are unpinned.

## D-07 Synthetic world (2026-10-26, adopted from A-044)
Seed 20261026, 26 weeks 2026-04-06..2026-10-04, `as_of` 2026-10-05T00:00:00Z; 600 accounts, 1,824 users (18 bots),
1,264 identity links, 3,420 sessions, 12,552 events, 207 subscriptions on 198 accounts (33 %), experiment v1 (400
assigned, permuted blocks of four, enrolment closed a week before planned_end 2026-08-02 so every assigned account is
mature at the final run; three interim runs and one final) and v2 (154 assigned, enrolment 2026-08-05..09-30, the
randomiser sends 3 of 5 to treatment against a 0.40 plan, one run at planned_end; its plan is frozen after v1's last
run). "Business segment activates faster" is read as the `business` plan with the correlated `enterprise` segment
(higher 7-day rate and shorter median time to activation). Exposures carry `event_id` null on the surface
`onboarding_checklist`. Timezones America/New_York, America/Los_Angeles, Europe/London with no DST transition in the
window. Metric windows are README assumption 3 written explicitly in the config. Runs are created 5 minutes after their
cutoff. The inputs carry one `analysis_plan` (v1's, the plan of record); the manifest carries both plans. Realised,
drawn once: activation 63/200 vs 82/200, +9.50 pp (true effect +8.00), Newcombe [0.000812, 0.186863] (conclusive by a
hair); week-4 retention −4.50 pp with an interval including 0; guardrail −0.50 pp including 0; revenue per account USD
97.83 vs 130.95, difference including 0; v1 SRM OK, v2 MISMATCH (chi-square 25.004329, p 0.000001); exposure 0.8725.
**Outcome-informed choices, disclosed in the manifest:** v1 randomisation was changed from a fair coin (223/177, p
0.021) to permuted blocks after seeing it; `product_error` was changed from per-account to 8 % per session after seeing
an unrealistic guardrail gap; v2 enrolment start and bounce-visitor counts were tuned; the INJ-06 candidate window was
widened. Everything else is reported as drawn. **Domain finding (fixed in D-08):** assignments, exposures and
subscriptions were not filtered by the cutoff, so an interim run counted rows dated after it.

## D-08 Cutoff rule (2026-10-26, A-046)
Found by the generator worker (A-044, D-07): assignments, exposures and subscriptions were not filtered by the analysis
cutoff, so an interim run counted rows dated after it. On the published snapshot at cutoff 2026-05-18 `assigned_units`
was 400 and the SRM observed counts 200/200 although only 155 accounts had been assigned (77 control, 78 treatment; SRM
OK, chi-square 0.006452); revenue totals included subscriptions that start later (control 7,710.00 / treatment 6,573.00,
means 118.62 / 102.70; by the cutoff 5,322.00 / 5,481.00, means 81.88 / 85.64). Events (received by the cutoff), sessions
and maturity were already cutoff-aware.

**Rule: a run at cutoff C sees only the facts that existed by C**, in the Python domain, in `data/sql/reference_metrics.sql`
and in the API (`GET /metrics`, C07 check-maturity, C08 analyze-experiment; C09 and C10 recompute through the domain):
* assignments: `assigned_at <= C` (the unit's first such assignment is its assignment; a unit first assigned after C is not
  an assigned unit, so it is in neither `assigned_units`, the SRM observed counts, nor any arm);
* exposures: `exposed_at <= C` (the exposure rate and the exploratory exposed-only block);
* subscriptions: `starts_at <= C` in addition to the plan's half-open revenue window `[from, to)` (revenue per account);
* metric observations: `window_end <= C`;
* the boundary is inclusive (`<=`), as for events received at the cutoff; sessions keep their own `started_at < C`.
* C07 counts and writes observations for the units assigned by its cutoff only.

**Decisions.** (1) The rule applies to dated facts, not to configuration: the frozen plan, analysis runs and decisions are
records of what was decided and logged, not measurements of the world, so they are not cut by instant. A run is still
found by `cutoff_at` and its prior runs by `created_at`; a plan frozen after C does not change a figure computed with it
(the plan hash and `plan_frozen` report that). (2) `group_by=variant` and the segment analysis use the same cutoff-filtered
assignments. (3) A later cutoff includes the rows (they are facts that arrived in time), as a disclosed revision like late
events. (4) Nothing generated changes: the golden cutoff and the published as-of are after every fact, so the golden
fixtures, both variants and the 706 reference checks are unchanged. Regression tests: `tests/test_review_findings.py`.

## D-09 Static site (2026-10-26, adopted from A-047)
At a cutoff other than the as-of, windowed metrics use `default_windows(cutoff)` and the funnel window is [cutoff − 7 d,
cutoff); at the as-of they use the manifest's windows (asserted equal to the defaults). The browser builds both plans
from `manifest.analysis_plans` and passes experiment_version_id and run_id explicitly. The cohort page groups accounts
by the Monday of their local signup date; a cell is blank when no account of the week is mature, "partial" when only
some are (counting the mature ones), filled otherwise; the weekly grid is restated independently in the Python snapshot
reference and the two agree. The decision page applies C10 as written plus "one decision per run"; a refused attempt
writes an in-memory audit row; everything is gone on reload. Fonts are system stacks (nothing fetched from a third
party). `code_sha` is absent from the generator manifest ("not recorded" until publish stamps it). `/result/` and
`/evidence/` always load the golden fixture; `?dataset=golden` switches the primary dataset elsewhere. The registry's
"freeze a plan" is a simulated draft computing a config_hash in memory. Local dates use Intl, checked against
zoneinfo for every half hour from 2026-03-01 to 2026-11-12 in the three zones (both DST transitions). The Playwright
evidence is not hosted on the site (the evidence page says so).
