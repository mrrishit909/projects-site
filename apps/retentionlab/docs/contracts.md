# RetentionLab — business contracts, version 1 (2026-10-27)

Decision owner: coordinator (Fable 5.1). Spec: `projects/10-retentionlab.md`, SHA-256 `6784f44e…` at pack commit
`fe5f7981` (verified against `docs/program/source-pack.json`). Rules cite the requirement they satisfy; changing one
bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
Which accounts deserve limited retention attention under uncertain intervention value? (P10-GOAL-01). Primary users:
a data scientist, a data analyst and a BI analyst (P10-GOAL-02). Boundaries: point-in-time correctness uses
`available_at` as well as `event_at` (P10-DOMAIN-01); chronological splits with a label-window purge
(P10-DOMAIN-02); the generator's latent truth never enters a predictor (P10-DOMAIN-03); logistic regression is
compared with a random and a simple-rule baseline (P10-DOMAIN-04); no claim of real retention improvement from a
synthetic evaluation (P10-DOMAIN-05); a randomised intervention experiment is designed separately and never
simulated as evidence (P10-DOMAIN-06). High risk is not treatment responsiveness (P10-FLOW-08, P10-TEST-09).

## D-01 Point-in-time features, eligibility and labels
* A prediction cutoff is (`account_id`, `prediction_at`, `horizon_end`, `observation_start`). An account is
  **eligible** at a cutoff when it was created before `observation_start` and had an active subscription at
  `prediction_at` (the latest subscription event before `prediction_at` is `start` or `renew`, not `cancel`).
* A feature at a cutoff uses only events with `observation_start` ≤ `event_at` < `prediction_at` **and**
  `available_at` < `prediction_at`; `feature_rows.max_available_at` is the largest `available_at` used and the
  builder proves `max_available_at` < `prediction_at` on every row. An event that occurred earlier but arrived
  after the cutoff is excluded and counted as `arrived_late` (P10-FLOW-01, P10-TEST-02). An event whose
  `available_at` < `event_at` is rejected `AVAILABILITY_BEFORE_EVENT`.
* The **feature registry** (`feature_version`) names every feature, its source entity and its window; a field
  flagged `post_outcome` (cancellation reason, cancellation survey, refund-after-cancel) can never be a feature,
  and a builder request naming one is refused `POST_OUTCOME_FIELD` (P10-TEST-01). Identifier-derived fields
  (`account_id`, hashes of it, creation sequence numbers) are refused `ID_FEATURE`, and any field whose name or
  lineage starts with `latent_` or comes from the generator manifest is refused `LATENT_TRUTH` (P10-DOMAIN-03,
  P10-TEST-08, P10-TEST-12).
* **Label**: `churned` = a subscription `cancel` event with `prediction_at` ≤ `event_at` < `horizon_end` and
  `available_at` < `label_end`, where `label_end` = `horizon_end` + the declared `label_grace` (14 days); a row is
  **mature** only when `label_end` ≤ as-of. An immature row is **censored**: excluded from every evaluation and
  never labelled non-churn (P10-FLOW-02, P10-TEST-07). The horizon is fixed per `label_version` (90 days) and the
  subscription definition is the registry's (P10-MET-01).
* **Churn rate** = mature eligible churned ÷ mature eligible accounts at the cutoff set in scope (P10-MET-01).

## D-02 Splits, training, calibration and scoring
* **Chronological split** by `prediction_at`: train `[.., train_end)`, validation `[train_end, validation_end)`,
  test `[validation_end, test_end)`. **Purge**: a row whose label window `[prediction_at, label_end)` crosses a
  boundary is dropped from the earlier side (embargo = horizon + grace) (P10-FLOW-03, P10-TEST-04). **Group
  purge**: an account with a row in the test range has its earlier rows removed from train and validation, and an
  account with a row in validation has its earlier rows removed from train, so no account is seen on both sides
  of a boundary (P10-TEST-03). The dropped counts are published with the split.
* **Preprocessing** (median imputation, standardisation, missing indicators) is fitted on the training rows only
  and applied frozen to the others; a fit over any other rows is refused `LEAKAGE` (P10-FLOW-04, P10-TEST-05).
* **Models**: a seeded random baseline, a simple business rule (no usage in the last 30 days or an open
  high-severity support case), and a logistic regression fitted in pure Python by deterministic gradient descent
  with L2 penalty (floating point is allowed inside fitting only; coefficients and probabilities are frozen as
  decimal strings with 6 places and every metric is computed exactly on the frozen strings) (P10-FLOW-05,
  P10-DOMAIN-04).
* **Calibration**: Platt scaling fitted on validation rows only; the reliability curve and the calibration gap
  are evaluated on the test rows, never on the rows the calibration was fitted on (P10-FLOW-06, P10-TEST-11).
  Capacity K and any threshold are chosen on validation; the test set is read once, by the final evaluation
  (P10-TEST-06).
* **Scoring**: a frozen model (`training_run_id`, `config_hash`, `feature_version`, `label_version`) scores a
  cutoff; a prediction cites all four; a scoring publication is `completed` when every eligible account at the
  cutoff has a prediction (P10-FLOW-07). **Scoring freshness** = cutoff − latest completed scoring publication, in
  hours, separate from data freshness (latest `available_at` ingested) (P10-MET-12).
* **Monitor refresh**: a new cohort is scored and compared; labels arrive later, so performance on a cohort is
  reported only once its rows are mature, with the immature count shown (P10-FLOW-10).

## D-03 Evaluation, capacity and economics
* Ranking: predictions sorted by probability descending, ties by `account_id` ascending (documented, deterministic).
  **Precision at K** = true churners among the top K ÷ K; **recall at K** = true churners among the top K ÷ all
  eligible churners, null when there are no positives; K ≤ the eligible population, otherwise refused
  `CAPACITY_EXCEEDS_POPULATION` (P10-MET-02/03, P10-TEST-10). Golden (P10-GOLD-01): risks .8, .6, .4, .1 with
  outcomes 1, 0, 1, 0 at K = 2 give precision 0.500000 and recall 0.500000.
* **Average precision** = Σ_k (R_k − R_{k−1}) × P_k over the ranked positives (step-wise, no interpolation, the
  same definition as scikit-learn's `average_precision_score`), with the prevalence as its baseline; golden
  0.833333 (P10-MET-04). **Brier score** = mean((probability − outcome)²) on one evaluation population; golden
  0.192500 (P10-MET-05). **Risk lift at K** = top-K churn rate ÷ overall churn rate on the same population, a
  ranking statistic and not treatment uplift; golden 1.000000 (P10-MET-09).
* **Calibration gap** per bin = mean predicted risk − observed churn rate, in percentage points, on 10 equal-width
  bins over [0, 1) (the last bin closed), each with its count; a bin with no rows is null (P10-MET-06).
* **Feature missingness** = missing eligible feature values ÷ eligible values, by observation period and feature
  (P10-MET-10). **Population drift** = the population stability index of each declared feature against the
  reference cohort on the declared bins, with the threshold 0.2 shown as a diagnostic, not proof (P10-MET-11).
* An **intervention scenario** declares `capacity`, `contact_cost`, `assumed_effect` (the assumed share of an
  account's churn risk that an intervention removes, in [0, 1], so the assumed retained probability is probability ×
  `assumed_effect`; a coordinator correction of the earlier "absolute reduction" wording, which contradicted the formula) and `margin_value` (USD retained per retained account). The outreach
  queue is the top-K by risk, capacity-limited, with status `draft` only; nothing is sent (P10-FLOW-08).
  **Contact budget** = selected accounts × `contact_cost` (P10-MET-07). **Expected intervention value** =
  Σ_selected (probability × `assumed_effect` × `margin_value` − `contact_cost`), labelled hypothetical and
  assumption-based unless a randomised experiment supports the effect; the product never estimates a treatment
  effect from the risk ranking (P10-MET-08, P10-FLOW-09, P10-GOLD-01, P10-TEST-09).

## D-04 Numbers, time and absence
Proportions and scores as decimal strings with 6 places; percentage points with 2 places; money (USD) with 2 places
and NUMERIC(20,6) in the database; hours as integers; probabilities in [0, 1]. Instants UTC with `Z`,
server-stamped; ranges half-open. Null means unknown, censored or a zero denominator, never 0. Empty population:
every count 0, every ratio and score null, `empty_population` true. `accounts.synthetic` is always true.

## D-05 Fixture decisions (adopted from the golden fixture, P10-GOLD-11)
Adopted verbatim from `tests/fixtures/golden/CALCULATION.md` section 9, D-P10-01..19; the fixture and `reference_check.py`
are the binding form. The points that sharpen D-01..D-04:
* **Scope (D-P10-01/02):** a cutoff set is the rows sharing one `prediction_at`; outcome metrics use mature eligible rows
  with an accepted prediction (`unscored_excluded` published); churn rate uses all mature eligible rows; missingness, drift
  and the outreach queue use all eligible rows including censored ones (the monitor needs them).
* **Ties and K (D-P10-03/04):** ties break by `account_id` ascending for precision, recall, lift and the queue; AP groups
  tied probabilities as scikit-learn does; `tie_split_at_k` flags a tie across rank K; evaluation needs 1 ≤ K ≤ evaluated
  population and the queue K ≤ scored eligible population, else `CAPACITY_EXCEEDS_POPULATION`; an empty evaluated
  population gives null K metrics, not a refusal.
* **Visibility (D-P10-05/06/07):** eligibility uses point-in-time visibility (both instants before the cutoff); "created
  before observation_start" is strict; no visible subscription event is `NOT_ACTIVE`; window start inclusive, cutoff
  exclusive; `days_since` floored; a feature with no source events is null; `arrived_late` counts events in the window
  whose `available_at` is at or after the cutoff.
* **Labels and splits (D-P10-08/09):** `churned` is null while immature; a cancel arriving at or after `label_end` is not
  churn; a label window crosses a boundary only if `label_end` > boundary; label purge first, then group purge counting
  membership by range; test rows are never purged; drop reasons LABEL_WINDOW, GROUP_TEST, GROUP_VALIDATION; rows at or
  after `test_end` are `outside`.
* **Drift and calibration (D-P10-10/11):** PSI = Σ (actual − expected) × ln(actual ÷ expected) on declared half-open bins
  against the eligible rows of a declared reference set, zero proportions floored to 0.0001 without renormalising,
  `Decimal.ln` at 60 digits rounded half-up to 6 places, `exceeds_threshold` on the unrounded value; calibration bin =
  floor(10p) with p = 1 in the last bin, gap = (mean − observed) × 100 at 2 places; Platt fit rows must be retained
  validation rows and never overlap the evaluation rows.
* **Freshness and economics (D-P10-12/13):** publication status is derived (completed iff every eligible account has a
  prediction); P10-MET-12's "cutoff" is read as the report `as_of`; hours floored; economics follow the D-03 formula with
  unrounded 6-place per-account terms and one rounding at the total.
* **Refusals and import (D-P10-14/15):** feature requests refused with the first code in the order POST_OUTCOME_FIELD,
  LATENT_TRUTH, ID_FEATURE, UNKNOWN_FEATURE, listing every offending field; new codes THRESHOLD_ON_TEST, SYNTHETIC_REQUIRED,
  OUTREACH_NOT_DRAFT, UNKNOWN_CUTOFF, UNKNOWN_TRAINING_RUN, UNKNOWN_SCENARIO, DUPLICATE_ID, PROBABILITY_OUT_OF_RANGE,
  CENSORED_LABEL; import order per row DUPLICATE_ID, then foreign keys, then the domain rule.
* **Formats (D-P10-16/17/18/19):** churn rate is a proportion string; `config_hash` is the SHA-256 of the canonical JSON of
  the training run's `config` and a prediction's citations must equal the run's; the missingness period is the UTC calendar
  month of `prediction_at`; derived entities are stored in `inputs.json` with `expected.json.consistency`.
* **Not proven by the fixture:** model fitting (predictions are frozen inputs), the union of test sets as one evaluation,
  threshold rules, experiment design, multi-refresh monitoring, the metrics-endpoint K refusal, non-UTC zones, HTTP
  envelopes; the backend tests carry them.

## D-06 Backend clarifications (adopted from the backend hand-back; the 20 numbered assumptions are in README.md)
* A command's `as_of` is the server clock; a report's `as_of` defaults to it and is a snapshot (later-arriving events,
  predictions and publications are invisible). Clients never supply decision instants; analysis parameters (cutoff set,
  split boundaries, reference cohort) are the client's. C01 stores the four registry features for every eligible cutoff.
* The business rule flags no usage in 30 days or a high-severity support event in 90 days (no closure events exist);
  the random baseline is a SHA-256 of seed and cutoff id. Preprocessing is exact then frozen to 6 places (population
  standard deviation, zero deviation → 1, missing indicators only where fit rows had missing values). Logistic
  objective: mean log-loss + l2/2n × Σ weights² (intercept unpenalised), zero start, 500 iterations at rate 0.1;
  sigmoid through a deterministic `det_exp` built from basic arithmetic so results do not depend on libm. Platt:
  `p' = sigmoid(a·logit(p) + b)`, 500 iterations at 0.1, `Decimal.ln` for the logit, fitted on the validation rows'
  uncalibrated logistic probabilities; only the logistic model is calibrated. Training rows = retained train rows with a
  stored feature row and a stored mature label.
* `config_hash` is recomputed on each C04–C06 change; the first prediction freezes the run (409 `INVALID_STATE`); C04
  resets models and calibration, C05 resets calibration. Predictions and publications carry `model_name`; C07 needs
  stored feature rows (422 `FEATURES_NOT_BUILT`) and scores only the missing accounts on a repeat; publication status
  is derived. C08/C09 take a stored or inline scenario (immutable once created); `selected_on: "test"` is
  `THRESHOLD_ON_TEST`; `basis` must be `risk_ranking`; one draft queue per scenario. Unknown run/scenario/set is 404
  with an `UNKNOWN_*` rule; domain refusals are 422 with the offending items in `details[].context`; leakage,
  threshold, capacity and responsiveness refusals are audited in their own transaction. `/metrics`: sets default to
  all, run defaults to the only run (422 `TRAINING_RUN_REQUIRED` if several), the K refusal only when the set has
  evaluated rows, drift only with `reference_prediction_at`, and the response carries `consistency`. Entity reads show
  NUMERIC(20,6) as stored; metrics use the D-04 formats. Labels are append-only except a censored label maturing
  once; C10 stores an audit event and the idempotent result.
* Gaps: no randomised-experiment design (`experiment_id` recorded only); the test-read-once rule rests on a declared
  provenance field; cursors are not bound to a dataset_version; no SQL recomputation of AP or PSI (the stdlib
  reference is the independent check); no hyper-parameter search, monitoring history or non-UTC zones; not
  benchmarked at 10,000 accounts.

## D-07 Synthetic world (adopted from the generator hand-back; the 14 numbered assumptions are in generate.py and the manifest)
Seed 20261026; 2,400 accounts over 4 segments and 5 regions, monthly cutoffs 2025-01-01 .. 2026-09-01 (90-day horizon,
14-day grace), `as_of` 2026-10-05T00:00:00Z; one training run (train to 2025-10-01, validation to 2026-02-01, test to
2026-06-01) fitted by the domain; `dataset_version` rl-20261026-20261026, `dataset_hash` 9ebaaada…, `generated_at` =
`as_of`; 4,614,525 bytes published (D-09 added the prevalence-constant model, so the cohort carries four models' predictions).
* **The published files are the complete records of a uniform 200-account cohort** (13,329 usage, 1,646 subscription,
  1,567 billing and 322 support events; 970 cutoffs; 765 feature rows; 769 labels; 2,456 predictions; 48 publications;
  3 scenarios; 35 draft queue rows) plus `test_cohort.json` (all 1,513 mature eligible test-range rows of the full world
  with features, outcome and the four probabilities), `cutoff_aggregates.json` (per-cutoff counts and metrics for all
  2,400 accounts and the drift series), `calibration.json`, `split_summary.json`. The domain evaluates the full world in
  memory; the manifest's numbers come from it. Cohort predictions start at the 2025-10-01 cutoff.
* Account-level split roles by hash of the id (train 32 %, validation 36 %, test 32 %); an account has cutoff rows only
  in its role's range plus every cutoff from 2026-06-01 (otherwise the group purge would remove almost every earlier
  row). Cutoff rows exist while an account exists and has not cancelled. Events not yet available at `as_of` are not in
  the world; cancellations arriving after the grace are not churn. Latent propensity (a stylised 90-day probability
  from a weekly hazard) is kept for all 9,039 eligible cutoffs in `synthetic_truth` only; registry v1 has 12 rows, the
  11 golden rows plus `generator_seed_bucket` (latent, refused). Predictions carry `model_name`; metrics are computed
  per model. Scoring instants are generator choices. The test range is evaluated as the union of its four cutoffs (the
  per-cutoff metrics are also published). Scenario capacities 5, 10, 20 fixed before any outcome, `selected_on`
  validation.
* Designed relationships, realised by the domain on the 1,513-row test population (prevalence 0.124917): logistic
  (Platt) AP 0.2386 and Brier 0.1050 against the rule 0.1367 / 0.1093 and random 0.1268 / 0.3265 (DR-01; the latent
  propensity scores AP 0.310, in `synthetic_truth` only); DR-02 starter segment calibration gap −8.07 pp (overall
  −2.86) from an unobserved repricing on 2026-02-01; DR-03 apac `usage_events_30d` PSI 0.491–0.765 from 2026-05-01
  (60 % of logins unrecorded from 2026-03-31) while the whole population stays below 0.03; DR-04 ignoring
  `available_at` would change a feature on 11.57 % of test rows (three of four features flip); DR-05 3,594 of 9,039
  eligible rows (39.8 %) censored, mature churn 0.104500. Training: 1,088 retained rows, 744 eligible and mature for fitting (79 churners); validation: 384 retained rows, 289 eligible and mature for
  calibration (27 churners); purge
  counts published (train loses 879 LABEL_WINDOW, 124 GROUP_TEST, 52 GROUP_VALIDATION; validation 1,291 and 13).
  Economics at the 2026-09-01 cutoff on the 97 scored accounts of the published cohort: capacity 5 → +21.38, 10 → −6.87, 20 → −95.46; on the whole 2,400-account
  world (1,241 scored accounts) the same scenarios give +81.13, +71.04, −29.12 (D-09 R10-04); all hypothetical. Scoring freshness
  812 h, data freshness 1 h (latest `available_at` 2026-10-04T22:09:42Z against the 2026-10-05 as-of).
* Injections INJ-01..12 map to P10-TEST-01..12 (INJ-02/03/04/07 present in the data, the rest request-level), with 12
  replay events of 33 steps through the API at server clock 2026-10-05T12:00Z.
* **Outcome-informed choices, disclosed in the manifest (D-G02) and to be stated on the site and the case study:** the
  hazard intercepts were lowered after a first simulation; **the engagement signal was strengthened (coefficient 1100 →
  2200 plus a per-account offset) until the model's margins over the baselines were met**, so the margin is by
  construction; the drift change moved to 2026-03-31 with 40 % of logins kept and the target narrowed to cutoffs from
  2026-05-01; late cancellations 2 % → 4 %; the late-arrival target relaxed to three features; scenario assumptions
  changed once after all three showed negative value; the cohort grew from 140 to 200 accounts for the size cap.
* Gaps: four domain features only (eight other registered fields are refused); the validation set is small (289 rows)
  so the Platt fit is noisy; the published sample is not the population (the tests rebuild the world in memory);
  determinism depends on CPython 3.11's `random`; `high_severity_support_90d` is weak.

## D-08 Site decisions (adopted from the web hand-back; the 14 numbered assumptions are in the web README / evidence page)
* The TypeScript mirror evaluates frozen predictions only (fitting is not mirrored); the natural log is deterministic
  fixed-point BigInt at 10^90 and a static guard keeps Math functions out of every figure (chart geometry only). The
  test-table tie rule is probability descending, then account id (code-point order), then the earlier cutoff for the
  union; per-cutoff test populations are also offered and equal `cutoff_aggregates.json`. The cohort is evaluated per
  model with predictions filtered by `model_name`; the test table's calibrated column stands for the logistic model.
* **The model's margin over the baselines is labelled "met, by construction" on the models page, with the D-G02
  disclosure above the charts and on every route's honesty block**; the latent ceiling and the unobserved designs
  appear only on the evidence page as disclosures, and the per-row propensities are dropped at load.
* The golden copy lives in `public/golden/` (byte-identical, hash-checked). A PSI term prints as Python prints a quantized
  Decimal; a negative amount that rounds to zero prints "-0.00". `config_hash` is checked with Web Crypto over the
  canonical JSON. A JSON-number probability is accepted as the exact value it denotes and frozen to 6 places (Python
  keeps the raw float; published data uses strings). Tenure is computed on the cohort sample only. Account factors are
  exact log-odds contributions shown as associations, never causes. The planner validates K against the chosen
  population and reuses `CAPACITY_EXCEEDS_POPULATION`; `ASSUMED_EFFECT_OUT_OF_RANGE` is a UI message only. Simulation
  state is module memory; nothing uses browser storage. System font stacks only.
* Edge cases pinned by the check scripts: a cancellation at the cutoff instant counts as churn; `available_at` equal to
  the cutoff counts as arrived late; a label window ending exactly on a boundary does not cross it; two predictions for
  one (run, cutoff) keep the later row. Fifteen of the 116 designed-relationship figures (104 before D-09 added the prevalence reference, the largest regional gap and the Platt effect, all recomputed here) need the full event history
  and are shown as "published, full world", not recomputed. apac PSI also spikes in some small pre-change months and
  the page says so. The scaffold's `postbuild-routes.mjs` route list and `node-shim.d.ts` were corrected for this app.

## Mode disclosure
Mode A: Python domain (features, labels, splits, fitting, calibration, scoring, metrics) + PostgreSQL + FastAPI
verified on hosted runners. Mode B: TypeScript mirror over the published snapshot (frozen predictions and rows);
the capacity planner, the economics simulation and the outreach queue are browser-memory simulations and say so.

## D-09 Review fixes (adopted from review R10)
Binding coordinator decisions after review R10. One bullet per item; where an alternative was rejected it is named. `CONTRACT_VERSION` is unchanged (no
stored fact of the golden fixture moved); the data generator output, the migrations (0003) and the site moved, and the corrections to D-07 above are part of this
decision.
* **R10-01 Future as-of and stored labels.** `GET /metrics` refuses an `as_of` later than the server clock with 422 `AS_OF_IN_FUTURE` (`rules.check_as_of`;
  mirrored by `checkAsOf` in the TypeScript domain, the only place a planner could choose an as-of: the site offers no such control, so the guard is exercised by
  `scripts/review-check.ts`). The analysis never reports a row as mature when its stored label is censored: stored labels are authoritative (`World.analyse`),
  and a recomputed maturity that disagrees is a consistency finding (`labels_mismatched`), not a relabel; the one writer that matures a label is C02
  `define-label`, which reads the rules' own maturity (`World.recomputed`) at the server clock. Rejected: letting a later `as_of` overwrite the stored label (the
  reviewer's case: clock 2026-05-01T12:00Z, set 2026-03-01, `as_of=2026-07-01` produced a churn rate for rows whose label is censored); clamping the `as_of` to
  the clock silently (a hidden change of the question asked). Detect/recover tests: `tests/test_review10.py` (the reviewer's case through the API; the golden cohort
  with a 2027 as-of through the domain), `tests/test_api_reads.py::test_as_of_decides_what_is_known_and_what_is_mature`, `scripts/review-check.ts` world 30. The
  earlier tests that read at an `as_of` later than the stepping test clock now read at a clock moved past the `as_of` for the call (`support_db.get`); no assertion
  was weakened.
* **R10-02 Contrast on the cream panels.** Chips, definition links, folds and labels on `.paper` use a dark brass (`#6b4f17`, 6.5:1 on the cream) and the
  `<dt>` labels of the case-study card the plum ink; the note emphasis uses the coral ink. `e2e/review10.spec.ts` measures every text node under 18 px on every route
  at 1280 px (definitions and folds opened) and fails below 4.5:1, disabled controls excepted (large text, 24 px or 18.66 px bold, needs 3:1). Rejected: darkening
  the shared gold token (it is the right colour on the plum ground).
* **R10-03 The model card at 360 px.** Below 480 px the `dt`/`dd` pairs stack; identifiers wrap after an underscore (`<wbr>`) or a hyphen only, never inside a word
  (`word-break: break-all` and `overflow-wrap: anywhere` are gone from `dd`). `e2e/review10.spec.ts` checks stacking, the absence of `break-all`, and every line
  break between two letters of one word on the card at 360 px.
* **R10-04 The population under every economic figure.** Wherever the economics appear they name the population they are computed on ("97 scored accounts of the
  published cohort") and the full-world values are shown beside them: +81.13 / +71.04 / −29.12 on 1,241 scored accounts, computed by the domain over the full
  world and published as `economics_full_world` in `cutoff_aggregates.json` (and the manifest). `tests/test_generator.py` asserts them (and recomputes them from
  the full inputs without the generator's helper). Rejected: replacing the cohort's figures (the browser recomputes the cohort; it cannot recompute the world).
* **R10-05 Test counts.** The evidence and case-study routes state the counts of the final run from one place (`web/src/lib/counts.ts`), so the two routes cannot
  disagree with each other or with the run: 342 Python tests (`pytest`; 323 before these fixes plus 19 for them), 1,823 stdlib reference checks, 3,197 mirror checks
  (`npm run golden`), 95 adversarial mirror checks (`npm run review`) and 90 browser tests. The routes carried no test count before; the coordinator's 323 is the
  pre-fix pytest figure and is not what the final run reports, so the site states the count it was built with.
* **R10-06 Rows are not accounts.** The models page states rows and distinct accounts (1,513 rows from 442 accounts; 189 churning rows from 95 accounts) and that
  the rows are correlated across overlapping cutoffs and no interval is given. Rejected: a cluster-robust interval (it would claim more than the design supports).
* **R10-07 The monitoring page states the whole apac series.** It prints all 21 values, the 0.0001-floor artefact (four of the five pre-change exceedances have a
  floored empty bin on 57 reference rows; the fifth is ordinary sampling variation) and labels the five pre-change exceedances as false positives and the five
  from 2026-05-01 as the shift; the case study matches. `floored_bins` is published per region and cutoff in `cutoff_aggregates.json`. Rejected: raising the floor
  or changing the PSI (D-P10-10 binds).
* **R10-08 Platt scaling made the model worse on test.** The calibration page says so: Brier 0.104515 → 0.105019, overall gap −2.26 → −2.86 pp, and why (289 fit rows,
  all from one cutoff, 2025-10-01: the label-window purge removes the later validation cutoffs). `platt_effect` and `fit_rows_by_cutoff` are in
  `calibration.json`. Rejected: refitting Platt on more rows after seeing test outcomes (an outcome-informed change); the published result stands and is disclosed.
* **R10-09 apac's calibration gap.** The page names apac as the largest regional gap (−10.68 pp) and labels it a one-draw realisation of this seed, not a designed
  relationship (the instrumentation change was designed to move apac's usage distribution, not its calibration). Rejected: designing a regional calibration effect
  after the fact.
* **R10-10 P10-TEST-12 reinterpreted.** P10-TEST-12 (an identifier-derived feature) was tested only as a refusal of seed-derived and id-derived fields. It is
  reinterpreted as "the fitted model depends on no identifier and no row order" and checked by construction: the same world with every account id permuted (cutoff
  ids follow) and every row list shuffled is refitted, and the frozen preprocessing, coefficients, rule rates, prevalence, Platt mapping and every probability of the
  logistic, rule and prevalence models are byte-identical (`tests/test_generator.py::test_r10_10_*`; the seeded random baseline is keyed by the cutoff id on purpose
  and is excluded). The refusal of seed-derived fields (INJ-12) stays, in the same test. README sentence added.
* **R10-11 Outcome-informed choices on the case study.** The manifest's D-G02 (eight numbered items, including the INJ-02 examples allowed in any range and the
  starter repricing uplift 700 → 600) and D-G03 (the hash-assigned split roles, the consequence for the test population, the injected violators) carry `items`;
  the case-study route lists all eleven, and `e2e/review10.spec.ts` compares the list with the manifest. Rejected: leaving the roles out because they are a design
  choice (they shape the test population).
* **R10-12 Corrections to D-07.** "prevalence about 0.134" is 0.124917 and "mature churn 0.108" is 0.104500 (both corrected above).
* **R10-13 Training rows.** Wherever "744 training rows" appeared the text says "1,088 retained rows, 744 eligible and mature for fitting" (validation: 384 retained,
  289 eligible and mature for calibration).
* **R10-14 A prevalence-constant baseline.** `prevalence_baseline` is a fourth model in `fitting.py` (`fit_prevalence`: the training prevalence, frozen to 6 places,
  for every account), in the generator's predictions and publications, the test table (`p_prevalence_baseline`), the models page and its margins table, and in the
  schema (migration `0003_prevalence_model.sql` widens the `model_name` checks). The stated margins stay as declared against the rule and the random baseline; the
  margin over the constant (Brier 0.109664 − 0.105019 = 0.004645) is a reference, not a target, and the page says that the Brier margin over the random baseline
  (random Brier 0.326543) is the uninformative one. C05 reports `beats.prevalence_baseline` on Brier only (the AP of a constant is the prevalence).
* **R10-15 Smaller defects.** `num.ts` scale comments say 10^90; a feature request naming a field twice is refused `DUPLICATE_FIELD` (last in the priority, after
  UNKNOWN_FEATURE; every repeated name is listed once; Python, TypeScript and the API); the snapshot reference's DR-03 label leaf is a compared value.
