# RetentionLab golden fixture: the arithmetic by hand

Contract v1 (`docs/contracts.md` D-01..D-04). Every figure of `expected.json` is derived below from `inputs.json` with
pencil arithmetic; `reference_check.py` (standard library only, `Fraction` for ratios and scores, `Decimal` for money
and for the one logarithm, no float) recomputes the same figures from the inputs and compares leaf by leaf, and
asserts the literals marked `hand.*` here. Numbers: proportions and scores 6 places, percentage points 2, money 2,
hours integer, ROUND_HALF_UP, half-open ranges, null never 0. Everything is synthetic (`accounts.synthetic` true) and
the economics are hypothetical.

**Model fitting is NOT part of this fixture.** Predictions are frozen inputs (6-place decimal strings). Nothing here
fits a baseline, a logistic regression, a preprocessing step or a Platt scaling; the training run carries a `config`
object (names, seed, frozen coefficients as strings) whose canonical-JSON SHA-256 is its `config_hash`, and the
requests (`rq-*`) only assert *which rows a fit would be allowed to touch*. The fitting itself is tested by the
application tests, not here.

## 0. The world

`as_of` = 2026-05-01T00:00:00Z. `label_version` lv-1: horizon 90 days, grace 14 days. `feature_version` fv-1: observation
window 90 days. A cutoff row is (`account_id`, `prediction_at`, `horizon_end` = prediction_at + 90 d,
`observation_start` = prediction_at - 90 d); `label_end` = horizon_end + 14 d; mature iff label_end <= as_of.

| set (prediction_at) | observation_start | horizon_end | label_end | mature at as_of |
|---|---|---|---|---|
| 2025-03-01 (reference cohort) | 2024-12-01 | 2025-05-30 | 2025-06-13 | yes |
| 2026-01-01 (the golden set) | 2025-10-03 | 2026-04-01 | 2026-04-15 | yes (04-15 <= 05-01) |
| 2026-02-01 (new cohort) | 2025-11-03 | 2026-05-02 | 2026-05-16 | **no** (05-16 > 05-01) |

Day counts: Jan 1 - 90 d: Dec 31 + Nov 30 + Oct 29 = 90, so 2025-10-03. Jan 1 + 90 d: Jan 31 + Feb 28 + Mar 31 = 90, so
2026-04-01. Feb 1 + 90 d: 28 + 31 + 30 = 89 reaches May 1, so 90 is 2026-05-02.

Accounts 1-14 (created 2024-06-01, except account 6: 2025-10-03T00:00:00Z). All have a `start` subscription event at
creation. Other subscription events: a2 `renew` 2025-11-01 and `cancel` 2026-04-05; a1 `cancel` 2026-02-10T09:00;
a3 `cancel` event 2026-03-15T12:00, **available 2026-04-10**; a4 `cancel` event 2026-03-20, **available 2026-04-20**;
a5 `cancel` 2025-11-15.

Usage events (all `available_at` = `event_at` unless stated): a1 2025-11-10, 12-05, 12-20, **12-30T12:00 available
2026-01-03**, 2026-01-10, 01-20, 01-25; a2 2025-09-01, 12-28, 2026-01-05 and 2025-02-10; a3 2026-01-18; a4 2025-12-10,
12-15, 12-31T18:00, 2026-01-12, 01-29; reference cohort 2025-02: a7 (05, 20), a8 (01, 10, 15, 27), a10 (14), a12 (03, 25).
Support events: a1 12-10 high, 12-12 low; a3 2025-10-15 high, 12-29 high; a4 **2025-12-31T12:00 high, available
2026-01-01T00:00:00Z**. Billing events: a1 49.00 on 2025-11-01, 2025-12-01, **2026-01-01T00:00**; a2 99.00 on 2025-12-02
and 2026-01-02; a4 20.00 on **2025-10-03T00:00** and 2026-01-01T00:00.

## 1. P10-GOLD-01: the four accounts (set 2026-01-01)

Cutoff rows: accounts 1-6. Eligibility (D-01): created strictly before observation_start (2025-10-03) **and** the latest
subscription event visible before the cutoff is `start` or `renew`.

| account | rule | result |
|---|---|---|
| 1, 2, 3, 4 | created 2024-06-01 < 2025-10-03; latest event `start` (a2 `renew`) | eligible |
| 5 | latest event before the cutoff is `cancel` (2025-11-15) | ineligible `NOT_ACTIVE` |
| 6 | created_at 2025-10-03T00:00 is **not before** observation_start 2025-10-03T00:00 | ineligible `CREATED_ON_OR_AFTER_OBSERVATION_START` |

Eligible 4 of 6 cutoff rows (`hand.jan_eligible_4_of_6`). All four are mature (label_end 2026-04-15 <= as-of).

**Labels** (D-01): churned = a `cancel` with prediction_at <= event_at < horizon_end (2026-04-01) and available_at <
label_end (2026-04-15).

* a1: cancel 2026-02-10, available the same instant: inside both, **churned** (outcome 1).
* a2: cancel 2026-04-05 is not < horizon_end 2026-04-01: **not churned** (0). (`hand.a2_cancel_after_horizon_is_not_churn`)
* a3: cancel 2026-03-15 inside the horizon, arrived 2026-04-10 < 2026-04-15 (inside the grace): **churned** (1).
  (`hand.a3_cancel_arrives_in_grace_is_churn`)
* a4: cancel 2026-03-20 inside the horizon but arrived 2026-04-20, not < 2026-04-15: **not churned** (0) under the
  contract rule. (`hand.a4_cancel_arrives_after_label_end_is_not_churn`; see D-P10-08 for why this is a documented
  limitation and not a bug.)

Outcomes in rank order: 1, 0, 1, 0. Frozen predictions: 0.800000, 0.600000, 0.400000, 0.100000.

**Churn rate** (P10-MET-01) = mature eligible churned / mature eligible = 2 / 4 = **0.500000**.

**Ranking** (probability descending, ties by account_id): a1 0.8, a2 0.6, a3 0.4, a4 0.1. Capacity K = 2 (scenario sc-001).

* **Precision at K** = churners in top 2 / K = (a1 yes, a2 no) 1 / 2 = **0.500000**.
* **Recall at K** = churners in top 2 / all eligible churners = 1 / 2 = **0.500000**.
* **Risk lift at K** = top-K churn rate / overall churn rate = (1/2) / (2/4) = **1.000000** (a ranking statistic, not
  treatment uplift).
* **Brier score** = mean of squared differences:

  | account | p | y | (p - y)^2 |
  |---|---|---|---|
  | 1 | 0.8 | 1 | 0.2^2 = 0.04 |
  | 2 | 0.6 | 0 | 0.6^2 = 0.36 |
  | 3 | 0.4 | 1 | 0.6^2 = 0.36 |
  | 4 | 0.1 | 0 | 0.1^2 = 0.01 |

  Sum 0.04 + 0.36 + 0.36 + 0.01 = 0.77; 0.77 / 4 = 0.1925 = **0.192500**.
* **Average precision** (scikit-learn `average_precision_score`: sum over distinct thresholds of (R_n - R_(n-1)) x P_n),
  positives = 2, baseline (prevalence) = 2/4 = 0.500000:

  | threshold | TP | FP | precision P_n | recall R_n | R_n - R_(n-1) | term |
  |---|---|---|---|---|---|---|
  | 0.8 | 1 | 0 | 1 | 1/2 | 1/2 | 1/2 x 1 = 0.5 |
  | 0.6 | 1 | 1 | 1/2 | 1/2 | 0 | 0 |
  | 0.4 | 2 | 1 | 2/3 | 1 | 1/2 | 1/2 x 2/3 = 1/3 |
  | 0.1 | 2 | 2 | 1/2 | 1 | 0 | 0 |

  AP = 1/2 + 0 + 1/3 + 0 = 5/6 = 0.8333... = **0.833333**.
* **Calibration** (10 equal-width bins on [0, 1), the last closed; index = floor(10 p) so 0.8 goes to [0.8, 0.9); gap =
  (mean predicted - observed churn) x 100, percentage points):

  | bin | rows | mean predicted | observed | gap (pp) |
  |---|---|---|---|---|
  | [0.1, 0.2) index 1 | a4 | 0.1 | 0 | +10.00 |
  | [0.4, 0.5) index 4 | a3 | 0.4 | 1 | -60.00 |
  | [0.6, 0.7) index 6 | a2 | 0.6 | 0 | +60.00 |
  | [0.8, 0.9) index 8 | a1 | 0.8 | 1 | -20.00 |
  | indexes 0, 2, 3, 5, 7, 9 | none | null | null | **null** (count 0) |

## 2. Economics (D-03), hypothetical

Scenario sc-001: capacity 2, contact_cost 5.00, assumed_effect 0.100000, margin_value 131.75. The outreach queue is the top
2 by risk: a1 and a2, status `draft` (nothing is sent). **Contact budget** = 2 x 5.00 = **10.00**. **Expected intervention
value** = sum over selected of (p x effect x margin - cost):

* a1: 0.8 x 0.1 x 131.75 = 10.54; 10.54 - 5.00 = 5.54.
* a2: 0.6 x 0.1 x 131.75 = 7.905; 7.905 - 5.00 = 2.905.
* Sum 8.445, rounded **once, at the end**, ROUND_HALF_UP: **8.45** (ROUND_HALF_EVEN would give 8.44; the fixture is built to
  catch that).

Labelled hypothetical and assumption-based; `treatment_effect_estimate` is null: the ranking supplies no treatment effect
(P10-GOLD-01, P10-TEST-09). The money uses `Decimal`; no float.

## 3. Point-in-time features, arrived late, missingness (set 2026-01-01)

Feature rows (D-01, D-P10-06): an event qualifies when observation_start <= event_at < prediction_at **and** available_at
< prediction_at. `usage_events_30d` counts qualifying usage with event_at >= prediction_at - 30 d (2025-12-02);
`days_since_last_usage` = whole days from the latest qualifying usage to the cutoff (floor), null with no usage;
`high_severity_support_90d` counts qualifying `high` support events; `billing_total_90d` sums qualifying amounts, null with
none. `max_available_at` = the largest available_at over all qualifying events.

| account | usage_events_30d | days_since | high support | billing | max_available_at | why |
|---|---|---|---|---|---|---|
| 1 | 2 | 12 | 1 | 98.00 | 2025-12-20 | usage 12-05, 12-20 in window; 11-10 is outside the 30 d window; 12-30T12 arrived 01-03 (late, excluded); days: 12-20 to 01-01 = 12; billing 49 + 49 (01-01T00:00 is not < cutoff) |
| 2 | 1 | 4 | 0 | 99.00 | 2025-12-28 | 09-01 is before observation_start; 12-28 to 01-01 = 4 |
| 3 | 0 | null | 2 | null | 2025-12-29 | no usage, no billing: null, never 0; support 10-15 and 12-29 high |
| 4 | 3 | 0 | 0 | 20.00 | 2025-12-31T18:00 | last usage 12-31T18:00 is 6 h before the cutoff: floor 0; support 12-31T12 high arrived 01-01T00:00:00Z, not < cutoff (late); billing 10-03T00:00 equals observation_start (included), 01-01T00:00 is excluded |

**Arrived late** (event occurred before the cutoff, available at or after it; excluded from features and counted): a1's
usage event and a4's support event = 1 + 1 = **2** (subscription 0, billing 0). No row's `max_available_at` is >= its cutoff
(`feature_rows` consistency).

**Feature missingness** (P10-MET-10), period 2026-01 (UTC month of prediction_at), eligible rows 4 x 4 features = 16 values:
days_since_last_usage missing 1 (a3), billing_total_90d missing 1 (a3), the other two 0: 2 / 16 = **0.125000**; by feature
0/4, 1/4 = 0.250000, 0/4, 1/4.

## 4. The censored cohort (set 2026-02-01)

Rows for a1-a4, all eligible (a1's cancel on 02-10 is after the cutoff). label_end = 2026-05-16 > as_of: all four
**censored**, labels `churned` null (not false), so churn rate = 0 / 0 = **null**, every ranking metric null,
`empty_evaluation` true (but `empty_population` false: 4 eligible). Predictions exist for a1 0.500000, a2 0.500000,
a3 0.300000 only: the publication sp-002 covers 3 of 4 eligible accounts and is **incomplete**. Features (30 d window
2026-01-02..01-31; observation 2025-11-03..): a1 3, 7 d, 1, 98.00 (billing 2025-12-01 and 2026-01-01; 11-01 is before
observation_start); a2 1, 27 d, 0, 198.00; a3 1, 14 d, 1, null; a4 2, 3 d, 1, 20.00 (the 2026-01-01T00:00 payment and the
12-31T12 support event, now both available before the Feb cutoff). Missing: 1 of 16 (a3 billing) = 1/16 = **0.062500**.

## 5. Population drift (P10-MET-11): PSI on declared bins

Feature usage_events_30d, bins [0,1), [1,3), [3,inf) (half-open), reference cohort = the eligible rows of set 2025-03-01
(a1, a2, a7, a8, a9, a10, a12). Their usage_events_30d (window 2025-01-30..02-28): a1 0, a9 0, a2 1, a10 1, a7 2, a12 2,
a8 4: bins 2, 4, 1 of 7: 2/7 = 0.285714, 4/7 = 0.571429, 1/7 = 0.142857. PSI = sum (actual - expected) x ln(actual /
expected), actual = the current cohort; natural logarithm; a zero proportion is replaced by 0.0001 (D-P10-10).

* **Set 2026-01-01**: current usage_events_30d a1 2, a2 1, a3 0, a4 3: [0,1) holds a3 (1), [1,3) holds a1 and a2 (2), [3,inf)
  holds a4 (1), so 1/4, 2/4, 1/4.
  * bin 0: (1/4 - 2/7) ln((1/4)/(2/7)) = (-1/28) ln(7/8) = (-0.0357143)(-0.1335314) = 0.0047690
  * bin 1-2: (1/2 - 4/7) ln(7/8) = (-1/14)(-0.1335314) = 0.0095380
  * bin 3+: (1/4 - 1/7) ln(7/4) = (3/28)(0.5596158) = 0.0599588
  * Sum 0.0742658 = 3 ln 2 / 28 (because ln(7/4) - ln(7/8) = ln 2) = 3 x 0.6931472 / 28 = **0.074266**, below the 0.2
    diagnostic threshold (a diagnostic, not proof).
* **Set 2026-02-01**: current counts a1 3, a2 1, a3 1, a4 2: bins 0, 3, 1 of 4 = 0, 0.75, 0.25.
  * bin 0 (zero, floored to 0.0001): (0.0001 - 0.2857143) ln(0.0001/0.2857143) = (-0.2856143)(ln 0.00035 = -7.9575774) =
    2.2727978
  * bin 1-2: (3/4 - 4/7) ln(21/16) = (5/28)(0.2719337) = 0.0485596
  * bin 3+: 0.0599588
  * Sum 2.3813162 -> **2.381316**, above 0.2, `exceeds_threshold` true (diagnostic only).

The logarithm is not rational; `Decimal.ln()` at 60 significant digits (never a float) gives the 10-place terms in
`expected.json`.

## 6. Freshness, hours (P10-MET-12)

* Latest completed scoring publication: sp-001 (set 2026-01-01, all 4 eligible scored) published 2026-01-01T02:00:00Z.
  sp-002 is incomplete (3 of 4) and is not counted. Scoring freshness = as_of - published = 2026-05-01T00:00 -
  2026-01-01T02:00 = 120 days - 2 h = 2880 - 2 = **2878** hours (Jan 31 + Feb 28 + Mar 31 + Apr 30 = 120).
* Data freshness (separate figure) = as_of - the latest `available_at` ingested, 2026-04-20T00:00 (a4's cancel event) =
  11 days = **264** hours.

## 7. Chronological split with purges (D-02), training run tr-001

train_end 2025-07-01, validation_end 2025-12-01, test_end 2026-06-01; embargo = 90 + 14 = 104 days. 27 cutoff rows:

| prediction_at | accounts | range |
|---|---|---|
| 2025-03-01 | 1, 2, 7, 8, 9, 10, 12 | train |
| 2025-03-19 | 10 | train (label_end 2025-07-01 **equals** train_end: not crossing) |
| 2025-05-01 | 7, 8 | train (label_end 2025-08-13 > train_end) |
| 2025-07-01 | 3, 9, 11 | validation (starts at train_end) |
| 2025-08-19 | 13 | validation (label_end 2025-12-01 **equals** validation_end) |
| 2025-09-15 | 11, 12 | validation (label_end 2025-12-28 > validation_end) |
| 2025-12-01 | 14 | **test** (a row exactly at validation_end belongs to test) |
| 2026-01-01 | 1-6 | test |
| 2026-02-01 | 1-4 | test |

Counts by range: train 7 + 1 + 2 = 10, validation 3 + 1 + 2 = 6, test 1 + 6 + 4 = 11, outside 0.

1. **Label-window purge** (label_end > the boundary drops the row from the earlier side): train: the two 2025-05-01 rows
   (a7, a8); validation: the two 2025-09-15 rows (a11, a12). The 2025-03-19 and 2025-08-19 rows end exactly on the boundary
   and stay.
2. **Group purge** (on rows that survive step 1; group membership is by range, so a row dropped in step 1 still counts for
   its account). Accounts with a test row: 1, 2, 3, 4, 5, 6, 14. Accounts with a validation row: 3, 9, 11, 12, 13.
   Train rows: a1, a2 (test) -> `GROUP_TEST` 2; a9, a12 (validation; a12's validation row was itself label-dropped) ->
   `GROUP_VALIDATION` 2; a7, a8, a10 x 2 stay. Validation rows: a3's 2025-07-01 row (test) -> `GROUP_TEST` 1; a9, a11, a13 stay.
3. Result: train 10 = 4 retained + 2 label + 2 group_test + 2 group_validation; validation 6 = 3 retained + 2 label + 1
   group_test; test 11 retained (test rows are not purged; maturity governs their use).

## 8. The three variants

**variant-empty**: every list empty, so every count 0, every ratio and score null (churn rate, AP, Brier, PSI, missingness,
freshness), calibration bins 10 with count 0 and null gaps, `empty_population` true (0 / 0 is null, never 0).

**variant-rejected** (accounts 1, 2, 3, 4, 7, 8 are good; the rest is refused). 18 rejected rows and 9 refused requests:

| row | refused as | why it is correct |
|---|---|---|
| account 97 (`synthetic` false) | `SYNTHETIC_REQUIRED` | D-04: `accounts.synthetic` is always true |
| second account 3 | `DUPLICATE_ID` | the primary key is unique; the first row stays |
| se-008, ue-002 | `AVAILABILITY_BEFORE_EVENT` | available_at precedes event_at: an event cannot be known before it happens (D-01) |
| se-009 (account 99), co-98 (account 98), oe-003 (account 77) | `UNKNOWN_ACCOUNT` | foreign key |
| se-010 (account 97), co-97 | `DEPENDENT_REJECTED` | the parent account was rejected |
| fr-co-98, lb-co-98, pr-co-98 | `DEPENDENT_REJECTED` | the parent cutoff co-98 was rejected (cascade) |
| fr-co-77 | `UNKNOWN_CUTOFF` | foreign key |
| lb-co-01-20260201 (churned false, label_end 2026-05-16 > as_of) | `CENSORED_LABEL` | an immature row can never be labelled non-churn (D-01) |
| pr-co-04 (1.200000) | `PROBABILITY_OUT_OF_RANGE` | a probability lies in [0, 1] |
| pr-x1 (run tr-9) | `UNKNOWN_TRAINING_RUN` | foreign key |
| oe-002 (scenario sc-9) | `UNKNOWN_SCENARIO` | foreign key |
| oe-004 (status sent) | `OUTREACH_NOT_DRAFT` | the queue is draft only; nothing is sent (D-03) |
| rq-101 (cancellation_reason) | `POST_OUTCOME_FIELD` | registry flag post_outcome: knowable only after the outcome |
| rq-102 (latent_churn_propensity) | `LATENT_TRUTH` | generator truth never enters a predictor |
| rq-103 (account_id_hash) | `ID_FEATURE` | identifier-derived |
| rq-104 (cancellation_reason, account_id) | `POST_OUTCOME_FIELD` | two kinds named: the first in the priority order is the code, both are listed |
| rq-105 (days_since_signup_magic) | `UNKNOWN_FEATURE` | not in the registry (C01: registry only) |
| rq-106 (fit rows include a validation row) | `LEAKAGE` | preprocessing is fitted on retained training rows only |
| rq-107 (calibration evaluated on its fit rows) | `CALIBRATION_ON_FIT_ROWS` | the reliability curve must use rows the calibration did not see |
| rq-108 (threshold selected on test) | `THRESHOLD_ON_TEST` | K and thresholds are chosen on validation; the test set is read once |
| rq-109 (sc-2 capacity 5, population 3) | `CAPACITY_EXCEEDS_POPULATION` | K may not exceed the eligible population |

Figures that remain, for the accepted rows (set 2026-01-01; a4 is eligible and mature but unscored because its prediction
was refused, so it is excluded from ranking and counted as `unscored_excluded` 1):

* Churn rate (mature eligible 4: a1 churns on 2026-02-10, a2's cancel was refused, a3, a4 none) = 1 / 4 = **0.250000**.
* Evaluated population a1 0.5 (1), a2 0.5 (0), a3 0.2 (0): a tie at 0.5. Ranking by probability, ties by account_id: a1, a2, a3.
* K = 1 (sc-1): precision = 1 / 1 = 1.000000, recall = 1 / 1 = 1.000000, risk lift = (1/1) / (1/3) = **3.000000**;
  `tie_split_at_k` true (rank 1 and rank 2 share 0.5, so which account is "top 1" is a convention, D-P10-03).
* **Average precision** with ties grouped as scikit-learn does: threshold 0.5 holds a1 and a2: TP 1, FP 1, P = 1/2, R = 1:
  (1 - 0) x 1/2 = 0.5; threshold 0.2: R stays 1: 0. AP = **0.500000** (a rank-order AP would claim 1.0), prevalence 1/3.
* Brier = (0.25 + 0.25 + 0.04) / 3 = 0.54 / 3 = **0.180000**.
* Economics sc-1: 0.5 x 0.2 x 100.00 - 8.00 = 10.00 - 8.00 = **2.00**; budget 1 x 8.00 = 8.00.
* Missingness (a1: usage 1, days 27, support 0, billing null; a2-a4 no usage and no billing): days missing 3 of 4, billing 4
  of 4: 7 / 16 = **0.437500**.
* Publication sp-001 covers 3 of 4 eligible accounts: incomplete, so scoring freshness is **null** (no completed publication);
  data freshness = 2026-05-01 - 2026-02-10T00:00 = 80 days = 1920 hours.

## 9. DECISIONS (proposed; the contract leaves these open)

Each gives the rule the fixture encodes and the alternative it rejects. They need coordinator acceptance and then an entry
in `docs/contracts.md`; until then the fixture is the only place they are written down.

* **D-P10-01 Cutoff set.** A cutoff row is per account; a *cutoff set* is the rows sharing one `prediction_at`, and a metric
  scope names sets by `prediction_at` (with a training run and an optional scenario). *Rejected:* scoping by a single
  `cutoff_id` (identifies one account, so no population).
* **D-P10-02 Populations.** Outcome metrics (churn rate, precision, recall, AP, Brier, lift, calibration) use *mature eligible
  rows that have an accepted prediction* (evaluated); the unscored mature count is published as `unscored_excluded`; churn rate
  alone uses all mature eligible rows. Input-quality metrics (missingness, drift) and the outreach queue use *all eligible
  rows including censored ones*, because a new cohort is monitored before its labels arrive (D-02 monitor refresh).
  *Rejected:* excluding censored rows from missingness and drift (would make the monitor of a new cohort empty).
* **D-P10-03 Ties.** Precision, recall, lift and the top-K queue break ties by `account_id` ascending; average precision groups
  tied probabilities into one threshold exactly as scikit-learn does; `tie_split_at_k` flags a tie across rank K. *Rejected:*
  AP over the tie-broken order (optimistic and dependent on account ids; differs from `average_precision_score`).
* **D-P10-04 Capacity.** The evaluation requires 1 <= K <= evaluated population, the queue requires K <= scored eligible
  population, else `CAPACITY_EXCEEDS_POPULATION`; with an empty evaluated population the K metrics are null, not refused.
  *Rejected:* refusing the metrics endpoint for a cohort whose labels have not arrived.
* **D-P10-05 Eligibility.** The latest subscription event uses point-in-time visibility (event_at < prediction_at **and**
  available_at < prediction_at), ties by event_at then id; "created before observation_start" is strict (equal is ineligible,
  `CREATED_ON_OR_AFTER_OBSERVATION_START`); no visible subscription event is `NOT_ACTIVE`. *Rejected:* looking at event_at only
  (a cancel that arrived after the cutoff would hide an active account).
* **D-P10-06 Features.** Exactly the four registry features above; window start inclusive, cutoff exclusive; `days_since` is
  floor of whole days; a feature with no source events is null (days_since, billing), counts are 0; `max_available_at` is the
  maximum over all qualifying events of the three event sources and null when there are none. *Rejected:* zero for an
  absent billing total (null never 0).
* **D-P10-07 arrived_late.** Counted per source entity for eligible rows: event_at in the observation window (subscription:
  event_at < cutoff) and available_at >= cutoff (equal counts as late). *Rejected:* counting only strictly later arrivals.
* **D-P10-08 Labels.** `labels.churned` is null while immature, labels exist only for eligible rows, maturity is
  label_end <= as_of (equal is mature); a cancel that arrives at or after label_end is not churn (a documented limitation of
  the contract's rule, visible in the a4 case). *Rejected:* back-filling late cancels into old labels (breaks reproducibility
  of published results; R27 revisions are a separate feature).
* **D-P10-09 Split.** A label window crosses a boundary when label_end > boundary (equal does not cross); label purge runs
  first, then the group purge; group membership counts a row by its range even if it was label-dropped; test rows are never
  purged; the drop reason is one of LABEL_WINDOW, GROUP_TEST, GROUP_VALIDATION (test wins over validation). Rows at or after
  test_end are `outside`. *Rejected:* a group purge that only looks at retained rows (the account would still be seen across
  the boundary through the dropped row's features).
* **D-P10-10 PSI.** PSI = sum (actual - expected) ln(actual / expected), actual = current cohort, natural log, declared
  half-open bins, nulls excluded, the reference cohort is the eligible rows of a declared cutoff set; a zero proportion is
  replaced by 0.0001 without renormalising; computed with `Decimal.ln` at 60 digits and rounded half-up to 6 places;
  `exceeds_threshold` is PSI > 0.2 on the unrounded value, always shown as diagnostic only. *Rejected:* float `math.log` (the
  fixture forbids floats); returning null whenever a bin is empty (small cohorts would never report drift).
* **D-P10-11 Calibration.** Bin index = floor(10 p) with p = 1 in the last bin, computed on exact fractions (0.8 x 10 is exactly
  8, which a float cannot promise); gap in percentage points = (mean predicted - observed) x 100, 2 places; Platt fit rows
  must be retained validation rows (else `LEAKAGE`) and may not appear among the evaluation rows. *Rejected:* float binning.
* **D-P10-12 Scoring publication and freshness.** `status` is derived: completed iff at least one eligible account and every
  eligible account at the set has an accepted prediction of the run. The contract's "cutoff - latest completed scoring
  publication" is read with the *report cutoff* = `as_of` (a publication cannot precede the prediction cutoff it scores, so
  the literal reading would be negative). Hours are whole hours, floor; null with no completed publication. Data freshness =
  as_of - latest ingested `available_at`. *Rejected:* subtracting from the prediction cutoff.
* **D-P10-13 Economics.** The contract's formula is implemented literally, p x effect x margin - cost, rounded once at the
  total; per-account terms are shown as unrounded 6-place intermediates. *Flag:* `assumed_effect` is defined as an absolute
  reduction of churn probability, but the formula multiplies it by the predicted probability as if it were relative; the
  fixture follows the formula and the owner should confirm the intended meaning. The queue is the top K of the *scored
  eligible* rows (forward-looking), not of the mature rows.
* **D-P10-14 Command refusals.** Requests are validated against the registry and the split: a feature request is refused with
  the first code in the order POST_OUTCOME_FIELD, LATENT_TRUTH, ID_FEATURE, UNKNOWN_FEATURE and lists every offending field;
  names starting `latent_` are LATENT_TRUTH and names starting `account_id` are ID_FEATURE even when unregistered. New code
  `THRESHOLD_ON_TEST` for capacity or threshold selected on the test rows. *Rejected:* one generic refusal code.
* **D-P10-15 Import validation.** Per row: DUPLICATE_ID, then foreign keys in the documented order (a rejected parent gives
  DEPENDENT_REJECTED, an absent one UNKNOWN_ACCOUNT / UNKNOWN_CUTOFF / UNKNOWN_TRAINING_RUN / UNKNOWN_SCENARIO), then the
  domain rule (SYNTHETIC_REQUIRED, AVAILABILITY_BEFORE_EVENT, PROBABILITY_OUT_OF_RANGE, CENSORED_LABEL, OUTREACH_NOT_DRAFT).
  Entities are processed parents first. The rejected list is in processing order and keeps every row.
* **D-P10-16 Formats.** Churn rate is the proportion string (0.500000), not "50.00 %": the unit "percent" of the metric
  contract is a presentation step; risk lift is a ratio string; percentage points 2 places; hours integers.
* **D-P10-17 Hashes and citations.** `config_hash` = SHA-256 of the canonical JSON (sorted keys, no spaces, ASCII) of the
  training run's `config`; a prediction cites `config_hash`, `feature_version` and `label_version` that must equal the run's.
* **D-P10-18 Observation period.** The period of the missingness metric is the UTC calendar month of `prediction_at` (YYYY-MM).
* **D-P10-19 Stored versus rebuilt.** The derived entities (feature_rows, labels, split_assignments, scoring_publications,
  the draft outreach queue, config_hash, predictions' citations) are stored in `inputs.json` as the application would store
  them; `expected.json.consistency` lists the stored rows that differ from the rebuilt ones (empty in all three fixtures).

## 10. Not exercised

* **Model fitting itself** (random baseline, business rule, logistic regression by gradient descent with L2, median
  imputation, standardisation, Platt scaling): predictions are frozen inputs, the `config` is only hashed.
* The union of all test-range sets as one evaluation (the fixture evaluates the sets 2026-01-01 and 2026-02-01 separately),
  and any test row with label_end after test_end.
* A threshold-based rule (only capacity K); an outreach `status` other than draft being sent; the randomised experiment
  design (P10-DOMAIN-06); real-time monitoring over several refreshes; revisions of published results (R27); a cancellation
  that is the second of several; ties across the whole sorted list beyond the variant's one tie; scenarios with
  assumed_effect outside [0, 1]; a refusal of the metrics endpoint with K above the population (only the command is refused);
  mixed segments or regions in any metric; time zones other than UTC; pagination and the HTTP envelopes (API tests).
