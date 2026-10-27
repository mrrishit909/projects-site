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
* An **intervention scenario** declares `capacity`, `contact_cost`, `assumed_effect` (an assumed absolute
  reduction of churn probability in [0, 1]) and `margin_value` (USD retained per retained account). The outreach
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

## Mode disclosure
Mode A: Python domain (features, labels, splits, fitting, calibration, scoring, metrics) + PostgreSQL + FastAPI
verified on hosted runners. Mode B: TypeScript mirror over the published snapshot (frozen predictions and rows);
the capacity planner, the economics simulation and the outreach queue are browser-memory simulations and say so.
