# RetentionLab: SQL analysis (P10-ART-04)

**Everything here is simulated on a synthetic world; the economics are hypothetical; no retention improvement is claimed.** Dataset `rl-20261026-20261026` (seed 20261026, `dataset_hash` `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`), contract v1, code revision `ce96e65`, as-of 2026-10-05T00:00:00Z.

**How to read it:** this file needs nothing installed: every table below is the stored output of `data/sql/analysis/run_all.py` (`artifacts/analysis-results.json`), filled in by `artifacts/render_sql_analysis.py` so no figure in a table is typed by hand, and `tests/test_artifacts.py` fails on any drift. To re-run: scratch databases `artifacts10_*` on a PostgreSQL 16 (section "Method").

## Method
* **Ten investigations, ten SQL files.** `01_model_comparison.sql` .. `08_rows_and_margins.sql` and `10_segment_region_calibration.sql` run on the **snapshot database**: the 200-account cohort loaded through `data/migrate.py` and `data/seed.py` (the same validation as the API) plus the verification layer (`data/sql/verification_layer.sql`: the 1,513-row **test table**, the per-cutoff counts and drift series of the 2,400-account world, the full-world economics and split counts, all loaded from the published files). `09_golden_known_answer.sql` runs on the **golden database** (`tests/fixtures/golden/inputs.json`). Each file holds several blocks marked `-- @@ name`, each a single read-only statement; 43 result sets, 229 rows in all. `prepare_snapshot.py` refuses any database not named `artifacts10_*` (the shared `retentionlab` database is never touched). Every `ORDER BY` on a text column uses `COLLATE "C"`; none orders by a boolean.
* **Exactness.** Counts are integers; probabilities are NUMERIC(20,6); every sum, square and product is exact NUMERIC; a ratio is `round(a / b, 6)` (half away from zero = the domain's ROUND_HALF_UP). Average precision is the scikit-learn step form over distinct probabilities. Rank order: probability descending, then account id, then the earlier cutoff.
* **AP and PSI are recomputed in SQL here** (window functions for AP; PostgreSQL's numeric `ln()` for PSI), which the earlier reference SQL did not do (`reference_metrics.sql` header). They are also computed in plain Python (`python_side.py`, `Decimal.ln` at 60 digits) and by the domain, and the three agree (reconciliation C and A).
* **Independent sources.** `data/sql/analysis/python_side.py` (standard library only; no SQL, no domain code) recomputes every result set from the raw JSON; `data/sql/reference_metrics.sql` and `retentionlab.evaluate` give the cohort's and the golden fixture's metrics; `tests/fixtures/golden/expected.json` and `CALCULATION.md` give the hand answers; the manifest, `calibration.json`, `split_summary.json`, `cutoff_aggregates.json` and the injection manifest give the published figures; a fresh in-memory rebuild of the whole world by `data/generate.py` checks the full-world files.
* **Populations are never mixed.** Each table says which one it describes: the **test table** (1,513 rows, full world, outcomes known), the **cohort** (200 accounts), the **queue** (the 2026-09-01 cutoff, all outcomes censored: 97 scored cohort accounts, 1,241 scored world accounts) or the **world** (2,400 accounts, published aggregates).

## 1. Model comparison on the held-out test population (`01_model_comparison.sql`)
Question: how do four models rank and score the 1,513 mature eligible rows of the test range (cutoffs 2026-02-01 .. 2026-05-01)? Rows are not accounts: 1,513 rows from 442 accounts, 189 churning rows from 95 accounts.

<!-- BEGIN:01_model_comparison__models -->
| model | test_rows | accounts | positive_rows | positive_accounts | prevalence | average_precision | brier_score | mean_probability |
|---|---|---|---|---|---|---|---|---|
| random_baseline | 1513 | 442 | 189 | 95 | 0.124917 | 0.126793 | 0.326543 | 0.491803 |
| business_rule | 1513 | 442 | 189 | 95 | 0.124917 | 0.136653 | 0.109255 | 0.103818 |
| logistic_regression (Platt) | 1513 | 442 | 189 | 95 | 0.124917 | 0.238552 | 0.105019 | 0.096314 |
| prevalence_baseline | 1513 | 442 | 189 | 95 | 0.124917 | 0.124917 | 0.109664 | 0.106183 |
| logistic_regression (before Platt) | 1513 | 442 | 189 | 95 | 0.124917 | 0.238552 | 0.104515 | 0.102358 |
<!-- END:01_model_comparison__models -->

Reading: the Platt-calibrated logistic regression has the best average precision (0.238552) and Brier score (0.105019), ahead of the rule (0.136653 / 0.109255), the random baseline (0.126793 / 0.326543) and the prevalence constant (0.124917 / 0.109664, whose AP is the prevalence). Platt scaling leaves the ranking, so the AP, unchanged and slightly worsens the Brier score (0.104515 before). These margins are **met by construction** (section 8). Reconciled to: the manifest `designed_relationships[DR-01]` (AP, Brier, rows, positives for four models), `python_side.py` and the workbook `Models` sheet.

<!-- BEGIN:01_model_comparison__per_cutoff -->
| prediction_at | test_rows | positive_rows | prevalence | logistic_brier |
|---|---|---|---|---|
| 2026-02-01T00:00:00+00:00 | 364 | 47 | 0.129121 | 0.107872 |
| 2026-03-01T00:00:00+00:00 | 372 | 46 | 0.123656 | 0.102224 |
| 2026-04-01T00:00:00+00:00 | 385 | 51 | 0.132468 | 0.109707 |
| 2026-05-01T00:00:00+00:00 | 392 | 45 | 0.114796 | 0.100418 |
<!-- END:01_model_comparison__per_cutoff -->

## 2. Calibration bins and the Platt effect (`02_calibration_platt.sql`)
Question: where are the probabilities too low or too high, and did the Platt mapping (fitted on 289 retained validation rows from one cutoff) help on the test rows it never saw? An empty bin has no mean, no rate and no gap (null, never 0).

<!-- BEGIN:02_calibration_platt__bins -->
| model | bin_index | lower_bound | upper_bound | rows_in_bin | churned_rows | empty_bin | mean_predicted | observed_rate | gap_pp |
|---|---|---|---|---|---|---|---|---|---|
| logistic_regression (Platt) | 0 | 0.000000 | 0.100000 | 815 | 56 | false | 0.056654 | 0.068712 | -1.21 |
| logistic_regression (Platt) | 1 | 0.100000 | 0.200000 | 640 | 117 | false | 0.133245 | 0.182813 | -4.96 |
| logistic_regression (Platt) | 2 | 0.200000 | 0.300000 | 50 | 15 | false | 0.230107 | 0.300000 | -6.99 |
| logistic_regression (Platt) | 3 | 0.300000 | 0.400000 | 8 | 1 | false | 0.345991 | 0.125000 | 22.10 |
| logistic_regression (Platt) | 4 | 0.400000 | 0.500000 | 0 | 0 | true |  |  |  |
| logistic_regression (Platt) | 5 | 0.500000 | 0.600000 | 0 | 0 | true |  |  |  |
| logistic_regression (Platt) | 6 | 0.600000 | 0.700000 | 0 | 0 | true |  |  |  |
| logistic_regression (Platt) | 7 | 0.700000 | 0.800000 | 0 | 0 | true |  |  |  |
| logistic_regression (Platt) | 8 | 0.800000 | 0.900000 | 0 | 0 | true |  |  |  |
| logistic_regression (Platt) | 9 | 0.900000 | 1.000000 | 0 | 0 | true |  |  |  |
| logistic_regression (before Platt) | 0 | 0.000000 | 0.100000 | 778 | 51 | false | 0.056720 | 0.065553 | -0.88 |
| logistic_regression (before Platt) | 1 | 0.100000 | 0.200000 | 653 | 113 | false | 0.138021 | 0.173047 | -3.50 |
| logistic_regression (before Platt) | 2 | 0.200000 | 0.300000 | 72 | 23 | false | 0.235707 | 0.319444 | -8.37 |
| logistic_regression (before Platt) | 3 | 0.300000 | 0.400000 | 7 | 2 | false | 0.340665 | 0.285714 | 5.50 |
| logistic_regression (before Platt) | 4 | 0.400000 | 0.500000 | 3 | 0 | false | 0.418756 | 0.000000 | 41.88 |
| logistic_regression (before Platt) | 5 | 0.500000 | 0.600000 | 0 | 0 | true |  |  |  |
| logistic_regression (before Platt) | 6 | 0.600000 | 0.700000 | 0 | 0 | true |  |  |  |
| logistic_regression (before Platt) | 7 | 0.700000 | 0.800000 | 0 | 0 | true |  |  |  |
| logistic_regression (before Platt) | 8 | 0.800000 | 0.900000 | 0 | 0 | true |  |  |  |
| logistic_regression (before Platt) | 9 | 0.900000 | 1.000000 | 0 | 0 | true |  |  |  |
<!-- END:02_calibration_platt__bins -->

<!-- BEGIN:02_calibration_platt__platt_effect -->
| test_rows | platt_a | platt_b | fit_rows | brier_before | brier_after | brier_change | overall_gap_pp_before | overall_gap_pp_after | made_the_brier_worse |
|---|---|---|---|---|---|---|---|---|---|
| 1513 | 0.954588 | -0.161286 | 289 | 0.104515 | 0.105019 | 0.000504 | -2.26 | -2.86 | true |
<!-- END:02_calibration_platt__platt_effect -->

Reading: churn is under-predicted in every occupied bin of the Platt-calibrated model except the 0.3-0.4 bin; six of the ten bins hold no rows (0.4 and above). Platt scaling made the model **worse** on test (Brier 0.104515 to 0.105019, overall gap -2.26 to -2.86 pp) because the fit rows all come from one validation cutoff:

<!-- BEGIN:02_calibration_platt__fit_rows_by_cutoff -->
| prediction_at | retained_mature_validation_rows_of_the_cohort |
|---|---|
| 2025-10-01T00:00:00+00:00 | 21 |
<!-- END:02_calibration_platt__fit_rows_by_cutoff -->

(that is the cohort sample of the 289 fit rows; `calibration.json` gives `fit_rows_by_cutoff` = {2025-10-01: 289} for the world). The frozen mapping p' = sigmoid(a logit(p) + b) applied in SQL to the uncalibrated column reproduces the stored calibrated probability exactly:

<!-- BEGIN:02_calibration_platt__platt_reproduced -->
| rows_compared | equal_at_6_places | within_one_unit_in_the_6th_place | further_apart |
|---|---|---|---|
| 1513 | 1513 | 1513 | 0 |
<!-- END:02_calibration_platt__platt_reproduced -->

Reconciled to: `calibration.json` (`reliability_calibrated`, `reliability_uncalibrated` bin by bin, `platt_effect`, `a`, `b`), the loaded `calibration_maps`, `python_side.py` (60-digit decimals) and the workbook `Calibration` sheet.

## 3. Precision, recall and lift at the three capacities, with budgets and the hypothetical values (`03_capacity_economics.sql`)
Question: what does a capacity of 5, 10 or 20 get, what does it cost, and what is it worth under the declared assumptions? Capacities were fixed on validation before any outcome (D-G08). Precision, recall and lift need outcomes, so they are on the **test table**; the economics are on the **2026-09-01 queue**, whose outcomes are all censored.

<!-- BEGIN:03_capacity_economics__test_population_at_k -->
| model | scenario_id | capacity | evaluated_rows | positives | churners_in_top_k | precision_at_k | recall_at_k | risk_lift_at_k | tie_split_at_k | population |
|---|---|---|---|---|---|---|---|---|---|---|
| random_baseline | sc-001 | 5 | 1513 | 189 | 0 | 0.000000 | 0.000000 | 0.000000 | false | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| random_baseline | sc-002 | 10 | 1513 | 189 | 1 | 0.100000 | 0.005291 | 0.800529 | false | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| random_baseline | sc-003 | 20 | 1513 | 189 | 1 | 0.050000 | 0.005291 | 0.400265 | false | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| business_rule | sc-001 | 5 | 1513 | 189 | 2 | 0.400000 | 0.010582 | 3.202116 | true | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| business_rule | sc-002 | 10 | 1513 | 189 | 3 | 0.300000 | 0.015873 | 2.401587 | true | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| business_rule | sc-003 | 20 | 1513 | 189 | 3 | 0.150000 | 0.015873 | 1.200794 | true | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| logistic_regression (Platt) | sc-001 | 5 | 1513 | 189 | 0 | 0.000000 | 0.000000 | 0.000000 | false | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| logistic_regression (Platt) | sc-002 | 10 | 1513 | 189 | 2 | 0.200000 | 0.010582 | 1.601058 | false | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| logistic_regression (Platt) | sc-003 | 20 | 1513 | 189 | 5 | 0.250000 | 0.026455 | 2.001323 | false | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| prevalence_baseline | sc-001 | 5 | 1513 | 189 | 0 | 0.000000 | 0.000000 | 0.000000 | true | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| prevalence_baseline | sc-002 | 10 | 1513 | 189 | 0 | 0.000000 | 0.000000 | 0.000000 | true | test table: 1,513 mature eligible rows of the full world (outcomes known) |
| prevalence_baseline | sc-003 | 20 | 1513 | 189 | 0 | 0.000000 | 0.000000 | 0.000000 | true | test table: 1,513 mature eligible rows of the full world (outcomes known) |
<!-- END:03_capacity_economics__test_population_at_k -->

Reading: the logistic model's top 5 holds **no churner** (0 of 5), its top 10 holds 2 (precision 0.200000, lift 1.601058) and its top 20 holds 5 (precision 0.250000, recall 0.026455, lift 2.001323). The rule's and the prevalence constant's top K are ties broken by account id (`tie_split_at_k` true), so their precision at K says nothing about the model; risk lift is a ranking statistic, not treatment uplift.

<!-- BEGIN:03_capacity_economics__cohort_economics -->
| scenario_id | capacity | scored_accounts | contact_cost | assumed_effect | margin_value | selected_accounts | contact_budget | expected_value | stored_draft_queue_rows | stored_rows_in_my_top_k | label | population |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sc-001 | 5 | 97 | 8.000000 | 0.300000 | 200.000000 | 5 | 40.00 | 21.38 | 5 | 5 | hypothetical | 97 scored accounts of the published cohort at 2026-09-01 (outcomes censored) |
| sc-002 | 10 | 97 | 8.000000 | 0.200000 | 200.000000 | 10 | 80.00 | -6.87 | 10 | 10 | hypothetical | 97 scored accounts of the published cohort at 2026-09-01 (outcomes censored) |
| sc-003 | 20 | 97 | 8.000000 | 0.100000 | 200.000000 | 20 | 160.00 | -95.46 | 20 | 20 | hypothetical | 97 scored accounts of the published cohort at 2026-09-01 (outcomes censored) |
<!-- END:03_capacity_economics__cohort_economics -->

<!-- BEGIN:03_capacity_economics__both_populations -->
| scenario_id | capacity | contact_budget | cohort_scored_accounts | cohort_expected_value | world_scored_accounts | world_expected_value | world_contact_budget | world_value_positive | cohort_value_positive | label | world_label_is_hypothetical |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sc-001 | 5 | 40.00 | 97 | 21.38 | 1241 | 81.13 | 40.00 | true | true | hypothetical | true |
| sc-002 | 10 | 80.00 | 97 | -6.87 | 1241 | 71.04 | 80.00 | true | false | hypothetical | true |
| sc-003 | 20 | 160.00 | 97 | -95.46 | 1241 | -29.12 | 160.00 | false | false | hypothetical | true |
<!-- END:03_capacity_economics__both_populations -->

Reading: **HYPOTHETICAL**, assumption-based values (assumed effect 0.3, 0.2, 0.1 of risk removed; margin 200.00; contact cost 8.00): on the 97 scored accounts of the cohort +21.38, -6.87 and -95.46 USD; on the 1,241 scored accounts of the whole world +81.13, +71.04 and -29.12 USD. They are different populations and are not comparable results. No treatment effect is estimated (`treatment_effect_estimate` is null). The stored draft queue equals the top K of the SQL's own ranking at every capacity (`stored_rows_in_my_top_k`). The world values are published aggregates; they cannot be recomputed from the cohort and are reconciled by rebuilding the world (reconciliation F).

<!-- BEGIN:03_capacity_economics__censored_at_the_queue_cutoff -->
| prediction_at | cohort_cutoff_rows | mature_rows | censored_rows |
|---|---|---|---|
| 2026-09-01T00:00:00+00:00 | 97 | 0 | 97 |
<!-- END:03_capacity_economics__censored_at_the_queue_cutoff -->

## 4. The censored tail by cutoff (`04_censored_tail.sql`)
Question: how many eligible rows have a label window that is still open at the as-of, and what would a careless reader see? A row is mature only when `label_end` = horizon_end + 14 days is at or before the as-of; a censored row is excluded from every evaluation and is never labelled non-churn.

<!-- BEGIN:04_censored_tail__world_by_cutoff -->
| prediction_at | split_range | cutoff_rows | eligible | mature | censored | churned | censored_share | mature_churn_rate | published_rate_if_censored_were_non_churn | implied_cancellations_seen_so_far | window_still_open_at_as_of |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-01-01T00:00:00+00:00 | train | 168 | 113 | 113 | 0 | 12 | 0.000000 | 0.106195 |  |  | false |
| 2025-02-01T00:00:00+00:00 | train | 184 | 126 | 126 | 0 | 13 | 0.000000 | 0.103175 |  |  | false |
| 2025-03-01T00:00:00+00:00 | train | 200 | 131 | 131 | 0 | 12 | 0.000000 | 0.091603 |  |  | false |
| 2025-04-01T00:00:00+00:00 | train | 218 | 150 | 150 | 0 | 12 | 0.000000 | 0.080000 |  |  | false |
| 2025-05-01T00:00:00+00:00 | train | 239 | 165 | 165 | 0 | 13 | 0.000000 | 0.078788 |  |  | false |
| 2025-06-01T00:00:00+00:00 | train | 255 | 183 | 183 | 0 | 17 | 0.000000 | 0.092896 |  |  | false |
| 2025-07-01T00:00:00+00:00 | train | 271 | 198 | 198 | 0 | 20 | 0.000000 | 0.101010 |  |  | false |
| 2025-08-01T00:00:00+00:00 | train | 298 | 214 | 214 | 0 | 27 | 0.000000 | 0.126168 |  |  | false |
| 2025-09-01T00:00:00+00:00 | train | 310 | 228 | 228 | 0 | 23 | 0.000000 | 0.100877 |  |  | false |
| 2025-10-01T00:00:00+00:00 | validation | 397 | 300 | 300 | 0 | 27 | 0.000000 | 0.090000 |  |  | false |
| 2025-11-01T00:00:00+00:00 | validation | 414 | 318 | 318 | 0 | 25 | 0.000000 | 0.078616 |  |  | false |
| 2025-12-01T00:00:00+00:00 | validation | 425 | 329 | 329 | 0 | 26 | 0.000000 | 0.079027 |  |  | false |
| 2026-01-01T00:00:00+00:00 | validation | 452 | 353 | 353 | 0 | 36 | 0.000000 | 0.101983 |  |  | false |
| 2026-02-01T00:00:00+00:00 | test | 453 | 364 | 364 | 0 | 47 | 0.000000 | 0.129121 |  |  | false |
| 2026-03-01T00:00:00+00:00 | test | 459 | 372 | 372 | 0 | 46 | 0.000000 | 0.123656 |  |  | false |
| 2026-04-01T00:00:00+00:00 | test | 472 | 385 | 385 | 0 | 51 | 0.000000 | 0.132468 |  |  | false |
| 2026-05-01T00:00:00+00:00 | test | 478 | 392 | 392 | 0 | 45 | 0.000000 | 0.114796 |  |  | false |
| 2026-06-01T00:00:00+00:00 | outside | 1404 | 1124 | 1124 | 0 | 117 | 0.000000 | 0.104093 |  |  | false |
| 2026-07-01T00:00:00+00:00 | outside | 1439 | 1154 | 0 | 1154 | 0 | 1.000000 |  | 0.094454 | 109 | true |
| 2026-08-01T00:00:00+00:00 | outside | 1378 | 1199 | 0 | 1199 | 0 | 1.000000 |  | 0.069224 | 83 | true |
| 2026-09-01T00:00:00+00:00 | outside | 1329 | 1241 | 0 | 1241 | 0 | 1.000000 |  | 0.038678 | 48 | true |
<!-- END:04_censored_tail__world_by_cutoff -->

<!-- BEGIN:04_censored_tail__world_summary -->
| eligible_rows | mature_rows | censored_rows | mature_churned_rows | censored_share | mature_churn_rate | cutoffs_with_censored_rows | first_censored_cutoff |
|---|---|---|---|---|---|---|---|
| 9039 | 5445 | 3594 | 569 | 0.397610 | 0.104500 | 3 | 2026-07-01T00:00:00+00:00 |
<!-- END:04_censored_tail__world_summary -->

Reading: 3,594 of 9,039 eligible world rows (0.397610) are censored, all in the last three cutoffs; the mature churn rate is 0.104500. Counting censored rows as retained would show 9.4 %, 6.9 % and 3.9 % churn on the last three cutoffs (only the cancellations seen so far, 109, 83 and 48 rows, count): the rate collapses towards zero the nearer the cutoff is to the as-of. The cohort, rebuilt from the loaded tables:

<!-- BEGIN:04_censored_tail__cohort_by_cutoff -->
| prediction_at | cohort_cutoff_rows | eligible | mature | censored | churned | mature_without_outcome | censored_but_labelled | censored_share | cancellations_seen_so_far_in_censored_rows | rate_if_censored_were_non_churn |
|---|---|---|---|---|---|---|---|---|---|---|
| 2025-01-01T00:00:00+00:00 | 14 | 14 | 14 | 0 | 1 | 0 | 0 | 0.000000 | 0 |  |
| 2025-02-01T00:00:00+00:00 | 16 | 14 | 14 | 0 | 1 | 0 | 0 | 0.000000 | 0 |  |
| 2025-03-01T00:00:00+00:00 | 19 | 14 | 14 | 0 | 1 | 0 | 0 | 0.000000 | 0 |  |
| 2025-04-01T00:00:00+00:00 | 22 | 13 | 13 | 0 | 0 | 0 | 0 | 0.000000 | 0 |  |
| 2025-05-01T00:00:00+00:00 | 25 | 15 | 15 | 0 | 1 | 0 | 0 | 0.000000 | 0 |  |
| 2025-06-01T00:00:00+00:00 | 27 | 16 | 16 | 0 | 2 | 0 | 0 | 0.000000 | 0 |  |
| 2025-07-01T00:00:00+00:00 | 28 | 20 | 20 | 0 | 3 | 0 | 0 | 0.000000 | 0 |  |
| 2025-08-01T00:00:00+00:00 | 33 | 22 | 22 | 0 | 3 | 0 | 0 | 0.000000 | 0 |  |
| 2025-09-01T00:00:00+00:00 | 36 | 23 | 23 | 0 | 1 | 0 | 0 | 0.000000 | 0 |  |
| 2025-10-01T00:00:00+00:00 | 34 | 24 | 24 | 0 | 2 | 0 | 0 | 0.000000 | 0 |  |
| 2025-11-01T00:00:00+00:00 | 34 | 25 | 25 | 0 | 1 | 0 | 0 | 0.000000 | 0 |  |
| 2025-12-01T00:00:00+00:00 | 35 | 28 | 28 | 0 | 1 | 0 | 0 | 0.000000 | 0 |  |
| 2026-01-01T00:00:00+00:00 | 38 | 30 | 30 | 0 | 4 | 0 | 0 | 0.000000 | 0 |  |
| 2026-02-01T00:00:00+00:00 | 37 | 32 | 32 | 0 | 4 | 0 | 0 | 0.000000 | 0 |  |
| 2026-03-01T00:00:00+00:00 | 40 | 32 | 32 | 0 | 5 | 0 | 0 | 0.000000 | 0 |  |
| 2026-04-01T00:00:00+00:00 | 42 | 34 | 34 | 0 | 6 | 0 | 0 | 0.000000 | 0 |  |
| 2026-05-01T00:00:00+00:00 | 42 | 33 | 33 | 0 | 6 | 0 | 0 | 0.000000 | 0 |  |
| 2026-06-01T00:00:00+00:00 | 118 | 90 | 90 | 0 | 12 | 0 | 0 | 0.000000 | 0 |  |
| 2026-07-01T00:00:00+00:00 | 119 | 94 | 0 | 94 | 0 | 0 | 0 | 1.000000 | 11 | 0.117021 |
| 2026-08-01T00:00:00+00:00 | 109 | 95 | 0 | 95 | 0 | 0 | 0 | 1.000000 | 9 | 0.094737 |
| 2026-09-01T00:00:00+00:00 | 102 | 97 | 0 | 97 | 0 | 0 | 0 | 1.000000 | 4 | 0.041237 |
<!-- END:04_censored_tail__cohort_by_cutoff -->

<!-- BEGIN:04_censored_tail__cohort_maturity_rule -->
| labelled_rows | stored_flag_equals_rule | stored_label_end_equals_rule |
|---|---|---|
| 765 | 765 | 765 |
<!-- END:04_censored_tail__cohort_maturity_rule -->

<!-- BEGIN:04_censored_tail__rejected_false_labels -->
| reason_code | rejected_labels | false_and_immature |
|---|---|---|
| CENSORED_LABEL | 4 | 4 |
<!-- END:04_censored_tail__rejected_false_labels -->

(INJ-07: four labels of false for open windows were refused at import and kept raw.)

## 5. Events that arrived late (`05_arrived_late.sql`)
Question: what share of events reach the warehouse a day or more late, and how many feature rows would carry a different value if a builder used the event instant only? The recomputation is written from the contract, not from `reference_metrics.sql`.

<!-- BEGIN:05_arrived_late__late_events_by_source -->
| source | cohort_events | late_one_day_or_more | cohort_share | published_full_world_share |
|---|---|---|---|---|
| usage_events | 13329 | 847 | 0.063546 | 0.068313 |
| billing_events | 1567 | 174 | 0.111040 | 0.117287 |
| support_events | 322 | 36 | 0.111801 | 0.092171 |
| subscription_events | 1646 | 47 | 0.028554 | 0.026151 |
<!-- END:05_arrived_late__late_events_by_source -->

<!-- BEGIN:05_arrived_late__feature_recomputation -->
| scope | feature_rows | stored_equals_point_in_time_recomputation | rows_with_a_late_event | rows_changed_if_arrival_ignored | usage_events_30d_changed | days_since_last_usage_changed | high_severity_support_90d_changed | billing_total_90d_changed | share_changed |
|---|---|---|---|---|---|---|---|---|---|
| all 765 eligible cohort rows | 765 | 765 | 98 | 97 | 73 | 45 | 1 | 27 | 0.126797 |
| test-range cohort rows | 131 | 131 | 18 | 18 | 11 | 4 | 0 | 7 | 0.137405 |
<!-- END:05_arrived_late__feature_recomputation -->

Reading: all 765 stored cohort feature rows equal the point-in-time recomputation from the events. Ignoring `available_at` would change at least one feature on 97 of them (0.126797; 18 of the 131 test-range rows, 0.137405). The whole-world figures are published, not recomputable from the cohort:

<!-- BEGIN:05_arrived_late__published_full_world -->
| claim | value |
|---|---|
| test_rows | 1513 |
| test_rows_with_a_late_event | 183 |
| test_rows_features_change_if_ignored | 175 |
| share_of_test_rows_changed | 0.115664 |
<!-- END:05_arrived_late__published_full_world -->

<!-- BEGIN:05_arrived_late__arrived_late_counted_by_range -->
| split_range | cohort_feature_rows | rows_with_a_late_event |
|---|---|---|
| train | 151 | 20 |
| validation | 107 | 9 |
| test | 131 | 18 |
| outside | 376 | 51 |
<!-- END:05_arrived_late__arrived_late_counted_by_range -->

(world: 183 of the 1,513 test rows carry a late event and 175 of them, 0.115664, would change a feature if the arrival instant were ignored; the cohort's late shares by source differ from the world's because the cohort is a sample).

## 6. Purge counts (`06_purge_counts.sql`)
Question: how many rows does the chronological split drop, and why? Label purge first (embargo = 90-day horizon + 14-day grace = 104 days), then group purge by range membership; test rows are never purged.

<!-- BEGIN:06_purge_counts__world_published -->
| split_range | cutoff_rows | retained | label_window | group_test | group_validation | dropped | counts_add_up |
|---|---|---|---|---|---|---|---|
| train | 2143 | 1088 | 879 | 124 | 52 | 1055 | true |
| validation | 1688 | 384 | 1291 | 13 | 0 | 1304 | true |
| test | 1862 | 1862 | 0 | 0 | 0 | 0 | true |
| outside | 5550 | 5550 | 0 | 0 | 0 | 0 | true |
<!-- END:06_purge_counts__world_published -->

<!-- BEGIN:06_purge_counts__world_totals -->
| train_label_window | train_group_test | train_group_validation | validation_label_window | validation_group_test | train_dropped_because_the_account_sits_on_the_other_side | dropped_in_all_ranges | embargo_days |
|---|---|---|---|---|---|---|---|
| 879 | 124 | 52 | 1291 | 13 | 176 | 2359 | 104 |
<!-- END:06_purge_counts__world_totals -->

The cohort: stored assignments, the same assignment recomputed here from the cutoff windows and the run's boundaries (row-for-row difference count last), and the leakage checks:

<!-- BEGIN:06_purge_counts__cohort_stored -->
| split_range | cutoff_rows | retained | label_window | group_test | group_validation |
|---|---|---|---|---|---|
| train | 220 | 86 | 97 | 32 | 5 |
| validation | 141 | 31 | 107 | 3 | 0 |
| test | 161 | 161 | 0 | 0 | 0 |
| outside | 448 | 448 | 0 | 0 | 0 |
<!-- END:06_purge_counts__cohort_stored -->

<!-- BEGIN:06_purge_counts__cohort_recomputed -->
| split_range | cutoff_rows | retained | label_window | group_test | group_validation | rows_that_differ_from_the_stored_assignment |
|---|---|---|---|---|---|---|
| train | 220 | 86 | 97 | 32 | 5 | 0 |
| validation | 141 | 31 | 107 | 3 | 0 | 0 |
| test | 161 | 161 | 0 | 0 | 0 | 0 |
| outside | 448 | 448 | 0 | 0 | 0 | 0 |
<!-- END:06_purge_counts__cohort_recomputed -->

<!-- BEGIN:06_purge_counts__cohort_no_account_on_both_sides -->
| accounts_retained_in_two_ranges |
|---|
| 0 |
<!-- END:06_purge_counts__cohort_no_account_on_both_sides -->

<!-- BEGIN:06_purge_counts__cohort_label_windows_inside_the_range -->
| split_range | retained_rows | retained_rows_crossing_the_boundary |
|---|---|---|
| train | 86 | 0 |
| validation | 31 | 0 |
<!-- END:06_purge_counts__cohort_label_windows_inside_the_range -->

Reading: of the world's 2,143 training rows 1,055 are dropped (879 LABEL_WINDOW, 124 GROUP_TEST, 52 GROUP_VALIDATION) leaving 1,088 retained; of 1,688 validation rows 1,304 are dropped (1,291 and 13), leaving 384, and the single surviving validation cutoff is why the Platt fit is small and noisy. The test range keeps all 1,862 rows. In the cohort the recomputed assignment differs from the stored one on 0 of 970 rows.

## 7. Drift by region, with the floored bins flagged (`07_drift_by_region.sql`)
Question: from the 2026-03-31 change in how logins are recorded, which region's `usage_events_30d` distribution leaves its own 2026-02-01 cohort, and which exceedances of the 0.2 threshold are artefacts of the 0.0001 floor? The first table is recomputed in SQL from the test table for every region (the 2026-02-01 test rows are the eligible reference cohort of the whole world).

<!-- BEGIN:07_drift_by_region__psi_test_range -->
| grp | prediction_at | reference_rows | current_rows | psi | floored_bins | exceeds_threshold |
|---|---|---|---|---|---|---|
| all_accounts | 2026-02-01T00:00:00+00:00 | 364 | 364 | 0.000000 | 0 | false |
| all_accounts | 2026-03-01T00:00:00+00:00 | 364 | 372 | 0.028286 | 0 | false |
| all_accounts | 2026-04-01T00:00:00+00:00 | 364 | 385 | 0.009458 | 0 | false |
| all_accounts | 2026-05-01T00:00:00+00:00 | 364 | 392 | 0.017043 | 0 | false |
| other_regions | 2026-02-01T00:00:00+00:00 | 307 | 307 | 0.000000 | 0 | false |
| other_regions | 2026-03-01T00:00:00+00:00 | 307 | 313 | 0.018526 | 0 | false |
| other_regions | 2026-04-01T00:00:00+00:00 | 307 | 324 | 0.017150 | 0 | false |
| other_regions | 2026-05-01T00:00:00+00:00 | 307 | 336 | 0.010967 | 0 | false |
| amer | 2026-02-01T00:00:00+00:00 | 148 | 148 | 0.000000 | 0 | false |
| amer | 2026-03-01T00:00:00+00:00 | 148 | 147 | 0.019362 | 0 | false |
| amer | 2026-04-01T00:00:00+00:00 | 148 | 150 | 0.016363 | 0 | false |
| amer | 2026-05-01T00:00:00+00:00 | 148 | 152 | 0.045941 | 0 | false |
| anz | 2026-02-01T00:00:00+00:00 | 30 | 30 | 0.000000 | 0 | false |
| anz | 2026-03-01T00:00:00+00:00 | 30 | 30 | 0.000000 | 0 | false |
| anz | 2026-04-01T00:00:00+00:00 | 30 | 36 | 0.194195 | 1 | false |
| anz | 2026-05-01T00:00:00+00:00 | 30 | 39 | 0.185016 | 0 | false |
| apac | 2026-02-01T00:00:00+00:00 | 57 | 57 | 0.000000 | 0 | false |
| apac | 2026-03-01T00:00:00+00:00 | 57 | 59 | 0.142972 | 0 | false |
| apac | 2026-04-01T00:00:00+00:00 | 57 | 61 | 0.058749 | 0 | false |
| apac | 2026-05-01T00:00:00+00:00 | 57 | 56 | 0.513545 | 0 | true |
| emea | 2026-02-01T00:00:00+00:00 | 87 | 87 | 0.000000 | 1 | false |
| emea | 2026-03-01T00:00:00+00:00 | 87 | 93 | 0.020644 | 1 | false |
| emea | 2026-04-01T00:00:00+00:00 | 87 | 95 | 0.132971 | 1 | false |
| emea | 2026-05-01T00:00:00+00:00 | 87 | 98 | 0.108827 | 1 | false |
| latam | 2026-02-01T00:00:00+00:00 | 42 | 42 | 0.000000 | 0 | false |
| latam | 2026-03-01T00:00:00+00:00 | 42 | 43 | 0.065902 | 0 | false |
| latam | 2026-04-01T00:00:00+00:00 | 42 | 43 | 0.052904 | 0 | false |
| latam | 2026-05-01T00:00:00+00:00 | 42 | 47 | 0.128171 | 0 | false |
<!-- END:07_drift_by_region__psi_test_range -->

The 21-cutoff apac series of the whole world as published (with the whole population and the other regions beside it):

<!-- BEGIN:07_drift_by_region__published_series_apac -->
| prediction_at | psi | current_rows | reference_rows | floored_bins | exceeds_threshold | comparison_before_the_change | exceeds_with_a_floored_bin | all_accounts_psi | other_regions_psi |
|---|---|---|---|---|---|---|---|---|---|
| 2025-01-01T00:00:00+00:00 | 0.108350 | 21 | 57 | 0 | false | true | false | 0.016721 | 0.023959 |
| 2025-02-01T00:00:00+00:00 | 0.638981 | 24 | 57 | 1 | true | true | true | 0.022450 | 0.051631 |
| 2025-03-01T00:00:00+00:00 | 0.051031 | 28 | 57 | 0 | false | true | false | 0.009982 | 0.007233 |
| 2025-04-01T00:00:00+00:00 | 0.006783 | 30 | 57 | 0 | false | true | false | 0.006141 | 0.009378 |
| 2025-05-01T00:00:00+00:00 | 0.111157 | 33 | 57 | 0 | false | true | false | 0.012696 | 0.007907 |
| 2025-06-01T00:00:00+00:00 | 0.641052 | 38 | 57 | 1 | true | true | true | 0.043730 | 0.018169 |
| 2025-07-01T00:00:00+00:00 | 0.026742 | 38 | 57 | 0 | false | true | false | 0.002029 | 0.000923 |
| 2025-08-01T00:00:00+00:00 | 0.623027 | 37 | 57 | 1 | true | true | true | 0.001181 | 0.004830 |
| 2025-09-01T00:00:00+00:00 | 0.181500 | 39 | 57 | 0 | false | true | false | 0.018325 | 0.008635 |
| 2025-10-01T00:00:00+00:00 | 0.679573 | 49 | 57 | 1 | true | true | true | 0.011837 | 0.025216 |
| 2025-11-01T00:00:00+00:00 | 0.085816 | 54 | 57 | 0 | false | true | false | 0.003782 | 0.000323 |
| 2025-12-01T00:00:00+00:00 | 0.139882 | 57 | 57 | 0 | false | true | false | 0.010498 | 0.009134 |
| 2026-01-01T00:00:00+00:00 | 0.251339 | 62 | 57 | 0 | true | true | false | 0.004366 | 0.013403 |
| 2026-02-01T00:00:00+00:00 | 0.000000 | 57 | 57 | 0 | false | false | false | 0.000000 | 0.000000 |
| 2026-03-01T00:00:00+00:00 | 0.142972 | 59 | 57 | 0 | false | true | false | 0.028286 | 0.018526 |
| 2026-04-01T00:00:00+00:00 | 0.058749 | 61 | 57 | 0 | false | false | false | 0.009458 | 0.017150 |
| 2026-05-01T00:00:00+00:00 | 0.513545 | 56 | 57 | 0 | true | false | false | 0.017043 | 0.010967 |
| 2026-06-01T00:00:00+00:00 | 0.551353 | 184 | 57 | 0 | true | false | false | 0.000867 | 0.016833 |
| 2026-07-01T00:00:00+00:00 | 0.579740 | 188 | 57 | 0 | true | false | false | 0.000647 | 0.020612 |
| 2026-08-01T00:00:00+00:00 | 0.765053 | 190 | 57 | 0 | true | false | false | 0.003020 | 0.014031 |
| 2026-09-01T00:00:00+00:00 | 0.491035 | 199 | 57 | 0 | true | false | false | 0.002069 | 0.022153 |
<!-- END:07_drift_by_region__published_series_apac -->

<!-- BEGIN:07_drift_by_region__published_summary -->
| cutoffs_before_the_reference | exceedances_before_the_reference | comparison_cutoffs_before_the_change | exceedances_before_the_change | exceedances_before_the_change_with_a_floored_bin | exceedances_before_the_change_without_a_floored_bin | max_psi_before_the_change | exceedances_from_the_change | first_exceedance_from_the_change | shift_min_psi | shift_max_psi | all_accounts_max_psi | all_accounts_psi_2026_05 | all_accounts_psi_latest | other_regions_max_psi |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 13 | 5 | 14 | 5 | 4 | 1 | 0.679573 | 5 | 2026-05-01T00:00:00+00:00 | 0.491035 | 0.765053 | 0.043730 | 0.017043 | 0.002069 | 0.051631 |
<!-- END:07_drift_by_region__published_summary -->

Reading: apac exceeds 0.2 from 2026-05-01 (0.513545, 0.551353, 0.579740, 0.765053, 0.491035) while the whole population never exceeds 0.043730 and the other regions never 0.051631: the aggregate would hide the shift. The same diagnostic also exceeds 0.2 on **five of the 14 comparison cutoffs before the change** (13 before the reference cohort), up to 0.679573; **four of the five carry a floored bin** (a cohort of a few dozen rows with no row in a bin), so they are artefacts of the floor, and the fifth (2026-01-01, 0.251339) is ordinary sampling variation: PSI here is a diagnostic with false positives, not proof. Other regions with few rows (anz: 30 reference rows) also approach the threshold without crossing it (0.194195 at 2026-04-01 with a floored bin).

## 8. Rows are not accounts, and the margins are met by construction (`08_rows_and_margins.sql`)

<!-- BEGIN:08_rows_and_margins__rows_and_accounts -->
| test_rows | distinct_accounts | churning_rows | churning_accounts | accounts_with_1_row | accounts_with_2_rows | accounts_with_3_rows | accounts_with_4_rows | accounts_churning_in_more_than_one_row | prevalence_of_rows | share_of_accounts_with_a_churning_row |
|---|---|---|---|---|---|---|---|---|---|---|
| 1513 | 442 | 189 | 95 | 46 | 39 | 39 | 318 | 62 | 0.124917 | 0.214932 |
<!-- END:08_rows_and_margins__rows_and_accounts -->

<!-- BEGIN:08_rows_and_margins__margins -->
| margin | declared_before_the_first_run | against | realised_margin | status |
|---|---|---|---|---|
| ap_over_rule | 0.030000 | business_rule | 0.101899 | met, by construction (D-G02) |
| ap_over_random | 0.050000 | random_baseline | 0.111759 | met, by construction (D-G02) |
| brier_under_rule | 0.002000 | business_rule | 0.004236 | met, by construction (D-G02) |
| brier_under_random | 0.050000 | random_baseline | 0.221524 | met, by construction (D-G02); uninformative: a uniform random score cannot beat about 0.33 |
| ap_over_prevalence_constant (reference) |  | prevalence_baseline | 0.113635 | reference, not a target |
| brier_under_prevalence_constant (reference) |  | prevalence_baseline | 0.004645 | reference, not a target |
<!-- END:08_rows_and_margins__margins -->

<!-- BEGIN:08_rows_and_margins__random_brier_is_uninformative -->
| random_baseline_brier | prevalence_constant_brier | random_baseline_mean_probability | prevalence |
|---|---|---|---|
| 0.326543 | 0.109664 | 0.491803 | 0.124917 |
<!-- END:08_rows_and_margins__random_brier_is_uninformative -->

Reading: 318 of the 442 test accounts appear in all four cutoffs and 62 accounts churn in more than one row, so the 189 churning rows are 95 accounts and the rows are correlated (no interval is given). The four declared margins (0.03, 0.05, 0.002, 0.05) are all met, but the generator's engagement signal was strengthened (coefficient 1100 to 2200 plus a per-account offset) until they were (manifest D-G02): **a met margin here is a property of the synthetic world, not evidence that such a model beats a simple rule on real accounts.** The Brier margin over the random baseline (0.221524) is uninformative, since a uniform random score cannot do better than about 0.33; the honest reference is the prevalence constant (AP margin 0.113635, Brier margin 0.004645).

## 9. The golden known answer (`09_golden_known_answer.sql`, golden database)
Four mature eligible accounts, frozen risks .8 .6 .4 .1, outcomes 1 0 1 0, capacity 2 (scenario sc-001: contact cost 5.00, assumed effect 0.1, margin 131.75). Eligibility and the outcome are derived from the subscription events, not read from the stored label.

<!-- BEGIN:09_golden_known_answer__ranking -->
| rank | account_id | risk | outcome | squared_error |
|---|---|---|---|---|
| 1 | 1 | 0.800000 | 1 | 0.040000 |
| 2 | 2 | 0.600000 | 0 | 0.360000 |
| 3 | 3 | 0.400000 | 1 | 0.360000 |
| 4 | 4 | 0.100000 | 0 | 0.010000 |
<!-- END:09_golden_known_answer__ranking -->

<!-- BEGIN:09_golden_known_answer__known_answer -->
| cutoff_rows | eligible_rows | ineligible_created_on_or_after_observation_start | ineligible_not_active | mature_eligible | churned | churn_rate | capacity | precision_at_k | recall_at_k | risk_lift_at_k | brier_score | average_precision | contact_budget | expected_intervention_value | label |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 6 | 4 | 1 | 1 | 4 | 2 | 0.500000 | 2 | 0.500000 | 0.500000 | 1.000000 | 0.192500 | 0.833333 | 10.00 | 8.45 | hypothetical |
<!-- END:09_golden_known_answer__known_answer -->

<!-- BEGIN:09_golden_known_answer__average_precision_terms -->
| threshold | true_positives | false_positives | precision | recall | delta_recall | term |
|---|---|---|---|---|---|---|
| 0.800000 | 1 | 0 | 1.000000 | 0.500000 | 0.500000 | 0.500000 |
| 0.600000 | 1 | 1 | 0.500000 | 0.500000 | 0.000000 | 0.000000 |
| 0.400000 | 2 | 1 | 0.666667 | 1.000000 | 0.500000 | 0.333333 |
| 0.100000 | 2 | 2 | 0.500000 | 1.000000 | 0.000000 | 0.000000 |
<!-- END:09_golden_known_answer__average_precision_terms -->

Reading: churn 2/4 = 0.500000; precision and recall at K = 2 are 0.500000; Brier (0.04 + 0.36 + 0.36 + 0.01) / 4 = 0.192500; AP 1/2 + 1/3 = 5/6 = 0.833333; lift 1.000000; budget 10.00; expected value 8.445 rounded once to 8.45 (hypothetical). The rest of the fixture: two arrived-late events (one usage, one support), a fully censored February cohort whose ranking metrics are null, 27 split rows by reason, four occupied calibration bins with gaps +10.00 / -60.00 / +60.00 / -20.00 pp, and the PSI against the 2025-03-01 cohort.

<!-- BEGIN:09_golden_known_answer__arrived_late -->
| source | arrived_late |
|---|---|
| usage_events | 1 |
| support_events | 1 |
| billing_events | 0 |
| subscription_events | 0 |
<!-- END:09_golden_known_answer__arrived_late -->

<!-- BEGIN:09_golden_known_answer__censored_cohort -->
| prediction_at | eligible_rows | mature_rows | censored_rows | rows_with_an_outcome | churn_rate |
|---|---|---|---|---|---|
| 2026-02-01T00:00:00+00:00 | 4 | 0 | 4 | 0 |  |
<!-- END:09_golden_known_answer__censored_cohort -->

<!-- BEGIN:09_golden_known_answer__purge_counts -->
| split_range | cutoff_rows | retained | label_window | group_test | group_validation |
|---|---|---|---|---|---|
| train | 10 | 4 | 2 | 2 | 2 |
| validation | 6 | 3 | 2 | 1 | 0 |
| test | 11 | 11 | 0 | 0 | 0 |
<!-- END:09_golden_known_answer__purge_counts -->

<!-- BEGIN:09_golden_known_answer__calibration_bins -->
| bin_index | rows_in_bin | empty_bin | mean_predicted | observed_rate | gap_pp |
|---|---|---|---|---|---|
| 0 | 0 | true |  |  |  |
| 1 | 1 | false | 0.100000 | 0.000000 | 10.00 |
| 2 | 0 | true |  |  |  |
| 3 | 0 | true |  |  |  |
| 4 | 1 | false | 0.400000 | 1.000000 | -60.00 |
| 5 | 0 | true |  |  |  |
| 6 | 1 | false | 0.600000 | 0.000000 | 60.00 |
| 7 | 0 | true |  |  |  |
| 8 | 1 | false | 0.800000 | 1.000000 | -20.00 |
| 9 | 0 | true |  |  |  |
<!-- END:09_golden_known_answer__calibration_bins -->

<!-- BEGIN:09_golden_known_answer__psi_against_the_march_2025_cohort -->
| prediction_at | reference_rows | current_rows | psi | floored_bins | exceeds_threshold |
|---|---|---|---|---|---|
| 2026-01-01T00:00:00+00:00 | 7 | 4 | 0.074266 | 0 | false |
| 2026-02-01T00:00:00+00:00 | 7 | 4 | 2.381316 | 1 | true |
<!-- END:09_golden_known_answer__psi_against_the_march_2025_cohort -->

(PSI 0.074266 for 2026-01-01, and 2.381316 for the censored February cohort whose 0-bin is empty: a floored bin.)

## 10. Where the model is least calibrated (`10_segment_region_calibration.sql`)

<!-- BEGIN:10_segment_region_calibration__by_segment -->
| dimension | grp | test_rows | churning_rows | mean_predicted | observed_rate | gap_pp | gap_pp_before_platt |
|---|---|---|---|---|---|---|---|
| segment | enterprise | 213 | 11 | 0.038807 | 0.051643 | -1.28 | -1.18 |
| segment | mid | 380 | 34 | 0.069537 | 0.089474 | -1.99 | -1.66 |
| segment | smb | 498 | 52 | 0.106581 | 0.104418 | 0.22 | 0.90 |
| segment | starter | 422 | 92 | 0.137336 | 0.218009 | -8.07 | -7.06 |
<!-- END:10_segment_region_calibration__by_segment -->

<!-- BEGIN:10_segment_region_calibration__by_region -->
| dimension | grp | test_rows | churning_rows | mean_predicted | observed_rate | gap_pp | gap_pp_before_platt |
|---|---|---|---|---|---|---|---|
| region | amer | 597 | 58 | 0.091238 | 0.097152 | -0.59 | -0.04 |
| region | anz | 135 | 17 | 0.092662 | 0.125926 | -3.33 | -2.74 |
| region | apac | 233 | 49 | 0.103481 | 0.210300 | -10.68 | -10.00 |
| region | emea | 373 | 42 | 0.102085 | 0.112601 | -1.05 | -0.39 |
| region | latam | 175 | 23 | 0.094605 | 0.131429 | -3.68 | -3.09 |
<!-- END:10_segment_region_calibration__by_region -->

<!-- BEGIN:10_segment_region_calibration__largest_gaps -->
| dimension | most_negative_gap_group | test_rows | gap_pp |
|---|---|---|---|
| overall | all test rows | 1513 | -2.86 |
| segment | starter | 422 | -8.07 |
| region | apac | 233 | -10.68 |
<!-- END:10_segment_region_calibration__largest_gaps -->

<!-- BEGIN:10_segment_region_calibration__starter_after_the_repricing -->
| prediction_at | starter_rows | churning_rows | mean_predicted | observed_rate | gap_pp |
|---|---|---|---|---|---|
| 2026-02-01T00:00:00+00:00 | 107 | 23 | 0.135836 | 0.214953 | -7.91 |
| 2026-03-01T00:00:00+00:00 | 108 | 25 | 0.136536 | 0.231481 | -9.49 |
| 2026-04-01T00:00:00+00:00 | 105 | 27 | 0.137065 | 0.257143 | -12.01 |
| 2026-05-01T00:00:00+00:00 | 102 | 17 | 0.140036 | 0.166667 | -2.66 |
<!-- END:10_segment_region_calibration__starter_after_the_repricing -->

Reading: the starter plan's -8.07 pp gap is the **designed** relationship DR-02 (an unobserved repricing on 2026-02-01 raised churn and no feature sees it); apac's larger -10.68 pp gap is **not designed**: it is a one-draw realisation of this seed (D-09 R10-09). Small groups carry 17 to 27 churning rows per cutoff, so each month's gap is noisy and no interval is given.

## 11. Reconciliation
`run_all.py` exits 0 only if every query ran and every reconciliation row is equal. It prints the count; the stored count is 393 rows, all equal. Groups: **A** the golden fixture (reference SQL = Python domain = `expected.json` for both cutoff sets, plus the SQL of investigation 09 against the hand answers of `CALCULATION.md`); **B** the cohort (the reference SQL, the domain re-run over the loaded cohort and the manifest agree for every one of 4 models x 21 cutoffs; the economics of the three queues; row counts; dataset hash); **C** every result set cell by cell against `python_side.py`; **D** the designed relationships DR-01..DR-05, the calibration file, the split summary, the injection manifest and the manifest statistics; **E** the BI measures recomputed from the CSV facts; **F** the whole 2,400-account world rebuilt in memory by the generator and compared with the published test table, aggregates, economics, training run and split counts.

<!-- BEGIN:reconciliation_summary -->
| group | what | rows | equal |
|---|---|---|---|
| A | golden fixture | 46 | 46 |
| B | cohort (reference SQL, domain, manifest) | 117 | 117 |
| C | every result set against python_side.py | 44 | 44 |
| D | designed relationships and published files | 107 | 107 |
| E | BI package | 52 | 52 |
| F | whole 2,400-account world rebuilt in memory | 27 | 27 |
<!-- END:reconciliation_summary -->

The full list (each row compares at least two independent sources; the sources and values are in `artifacts/analysis-results.json` under `reconciliation`):

<!-- BEGIN:reconciliation_listing -->
| n | check | equal |
|---|---|---|
| 1 | A golden whole shape of expected.json (domain evaluate() vs the file, digest) | true |
| 2 | A golden consistency block (domain vs expected.json) | true |
| 3 | A golden 2026-01-01 population: reference SQL = domain = expected.json (digest) | true |
| 4 | A golden 2026-01-01 churn_rate: reference SQL = domain = expected.json (digest) | true |
| 5 | A golden 2026-01-01 late_events: reference SQL = domain = expected.json (digest) | true |
| 6 | A golden 2026-01-01 precision_at_k: reference SQL = domain = expected.json (digest) | true |
| 7 | A golden 2026-01-01 recall_at_k: reference SQL = domain = expected.json (digest) | true |
| 8 | A golden 2026-01-01 risk_lift_at_k: reference SQL = domain = expected.json (digest) | true |
| 9 | A golden 2026-01-01 outreach_queue: reference SQL = domain = expected.json (digest) | true |
| 10 | A golden 2026-01-01 empty_population: reference SQL = domain = expected.json (digest) | true |
| 11 | A golden 2026-01-01 empty_evaluation: reference SQL = domain = expected.json (digest) | true |
| 12 | A golden 2026-01-01 brier_score: reference SQL = domain = expected.json (digest) | true |
| 13 | A golden 2026-01-01 calibration bins: reference SQL = domain = expected.json (digest) | true |
| 14 | A golden 2026-01-01 economics: reference SQL = domain = expected.json (budget, value, accounts) | true |
| 15 | A golden 2026-01-01 feature missingness overall (reference SQL vs expected.json vs domain) | true |
| 16 | A golden 2026-02-01 population: reference SQL = domain = expected.json (digest) | true |
| 17 | A golden 2026-02-01 churn_rate: reference SQL = domain = expected.json (digest) | true |
| 18 | A golden 2026-02-01 late_events: reference SQL = domain = expected.json (digest) | true |
| 19 | A golden 2026-02-01 precision_at_k: reference SQL = domain = expected.json (digest) | true |
| 20 | A golden 2026-02-01 recall_at_k: reference SQL = domain = expected.json (digest) | true |
| 21 | A golden 2026-02-01 risk_lift_at_k: reference SQL = domain = expected.json (digest) | true |
| 22 | A golden 2026-02-01 outreach_queue: reference SQL = domain = expected.json (digest) | true |
| 23 | A golden 2026-02-01 empty_population: reference SQL = domain = expected.json (digest) | true |
| 24 | A golden 2026-02-01 empty_evaluation: reference SQL = domain = expected.json (digest) | true |
| 25 | A golden 2026-02-01 brier_score: reference SQL = domain = expected.json (digest) | true |
| 26 | A golden 2026-02-01 calibration bins: reference SQL = domain = expected.json (digest) | true |
| 27 | A golden 2026-02-01 economics: reference SQL = domain = expected.json (budget, value, accounts) | true |
| 28 | A golden 2026-02-01 feature missingness overall (reference SQL vs expected.json vs domain) | true |
| 29 | A golden known answer churn rate: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json | true |
| 30 | A golden known answer precision at K=2: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json | true |
| 31 | A golden known answer recall at K=2: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json | true |
| 32 | A golden known answer risk lift at K=2: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json | true |
| 33 | A golden known answer Brier score: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json | true |
| 34 | A golden known answer average precision (5/6): SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json | true |
| 35 | A golden known answer contact budget: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json | true |
| 36 | A golden known answer expected intervention value: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json | true |
| 37 | A golden eligible of cutoff rows (4 of 6) and the two reasons (SQL 09 vs hand) | true |
| 38 | A golden arrived-late events (SQL 09 vs expected.json): usage, support, billing, subscription | true |
| 39 | A golden censored February cohort: eligible/mature/censored, ranking metrics null (SQL 09 vs expected.json) | true |
| 40 | A golden purge counts train (SQL 09 vs expected.json) | true |
| 41 | A golden purge counts validation (SQL 09 vs expected.json) | true |
| 42 | A golden purge counts test (SQL 09 vs expected.json) | true |
| 43 | A golden PSI 2026-01-01 against 2025-03-01 (SQL ln() vs domain Decimal.ln vs expected.json) | true |
| 44 | A golden PSI 2026-02-01 against 2025-03-01 (SQL ln() vs domain Decimal.ln vs expected.json) | true |
| 45 | A golden occupied calibration bins and gaps (SQL 09 vs expected.json) | true |
| 46 | A golden hand literals: gaps +10.00, -60.00, +60.00, -20.00 in bins 1, 4, 6, 8 | true |
| 47 | B cohort random_baseline 2025-01-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 48 | B cohort random_baseline 2025-02-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 49 | B cohort random_baseline 2025-03-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 50 | B cohort random_baseline 2025-04-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 51 | B cohort random_baseline 2025-05-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 52 | B cohort random_baseline 2025-06-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 53 | B cohort random_baseline 2025-07-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 54 | B cohort random_baseline 2025-08-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 55 | B cohort random_baseline 2025-09-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 56 | B cohort random_baseline 2025-10-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 57 | B cohort random_baseline 2025-11-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 58 | B cohort random_baseline 2025-12-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 59 | B cohort random_baseline 2026-01-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 60 | B cohort random_baseline 2026-02-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 61 | B cohort random_baseline 2026-03-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 62 | B cohort random_baseline 2026-04-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 63 | B cohort random_baseline 2026-05-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 64 | B cohort random_baseline 2026-06-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 65 | B cohort random_baseline 2026-07-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 66 | B cohort random_baseline 2026-08-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 67 | B cohort random_baseline 2026-09-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 68 | B cohort business_rule 2025-01-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 69 | B cohort business_rule 2025-02-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 70 | B cohort business_rule 2025-03-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 71 | B cohort business_rule 2025-04-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 72 | B cohort business_rule 2025-05-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 73 | B cohort business_rule 2025-06-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 74 | B cohort business_rule 2025-07-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 75 | B cohort business_rule 2025-08-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 76 | B cohort business_rule 2025-09-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 77 | B cohort business_rule 2025-10-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 78 | B cohort business_rule 2025-11-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 79 | B cohort business_rule 2025-12-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 80 | B cohort business_rule 2026-01-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 81 | B cohort business_rule 2026-02-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 82 | B cohort business_rule 2026-03-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 83 | B cohort business_rule 2026-04-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 84 | B cohort business_rule 2026-05-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 85 | B cohort business_rule 2026-06-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 86 | B cohort business_rule 2026-07-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 87 | B cohort business_rule 2026-08-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 88 | B cohort business_rule 2026-09-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 89 | B cohort logistic_regression 2025-01-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 90 | B cohort logistic_regression 2025-02-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 91 | B cohort logistic_regression 2025-03-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 92 | B cohort logistic_regression 2025-04-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 93 | B cohort logistic_regression 2025-05-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 94 | B cohort logistic_regression 2025-06-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 95 | B cohort logistic_regression 2025-07-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 96 | B cohort logistic_regression 2025-08-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 97 | B cohort logistic_regression 2025-09-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 98 | B cohort logistic_regression 2025-10-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 99 | B cohort logistic_regression 2025-11-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 100 | B cohort logistic_regression 2025-12-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 101 | B cohort logistic_regression 2026-01-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 102 | B cohort logistic_regression 2026-02-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 103 | B cohort logistic_regression 2026-03-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 104 | B cohort logistic_regression 2026-04-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 105 | B cohort logistic_regression 2026-05-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 106 | B cohort logistic_regression 2026-06-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 107 | B cohort logistic_regression 2026-07-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 108 | B cohort logistic_regression 2026-08-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 109 | B cohort logistic_regression 2026-09-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 110 | B cohort prevalence_baseline 2025-01-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 111 | B cohort prevalence_baseline 2025-02-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 112 | B cohort prevalence_baseline 2025-03-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 113 | B cohort prevalence_baseline 2025-04-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 114 | B cohort prevalence_baseline 2025-05-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 115 | B cohort prevalence_baseline 2025-06-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 116 | B cohort prevalence_baseline 2025-07-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 117 | B cohort prevalence_baseline 2025-08-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 118 | B cohort prevalence_baseline 2025-09-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 119 | B cohort prevalence_baseline 2025-10-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 120 | B cohort prevalence_baseline 2025-11-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 121 | B cohort prevalence_baseline 2025-12-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 122 | B cohort prevalence_baseline 2026-01-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 123 | B cohort prevalence_baseline 2026-02-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 124 | B cohort prevalence_baseline 2026-03-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 125 | B cohort prevalence_baseline 2026-04-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 126 | B cohort prevalence_baseline 2026-05-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 127 | B cohort prevalence_baseline 2026-06-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 128 | B cohort prevalence_baseline 2026-07-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 129 | B cohort prevalence_baseline 2026-08-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 130 | B cohort prevalence_baseline 2026-09-01: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest) | true |
| 131 | B cohort random_baseline: the domain's consistency block over the loaded cohort is empty (stored derived rows = rebuilt rows) | true |
| 132 | B cohort business_rule: the domain's consistency block over the loaded cohort is empty (stored derived rows = rebuilt rows) | true |
| 133 | B cohort logistic_regression: the domain's consistency block over the loaded cohort is empty (stored derived rows = rebuilt rows) | true |
| 134 | B cohort prevalence_baseline: the domain's consistency block over the loaded cohort is empty (stored derived rows = rebuilt rows) | true |
| 135 | B cohort economics sc-001 expected value on 97 scored accounts (SQL 03 = reference SQL = manifest = python_side) | true |
| 136 | B cohort economics sc-001 contact budget and capacity (SQL 03 = reference SQL = manifest) | true |
| 137 | B cohort economics sc-001 draft queue = the first 5 of the ranking (stored rows in my top K vs manifest queue vs reference SQL) | true |
| 138 | B cohort economics sc-001 label hypothetical, no treatment effect, population 97 | true |
| 139 | B cohort economics sc-002 expected value on 97 scored accounts (SQL 03 = reference SQL = manifest = python_side) | true |
| 140 | B cohort economics sc-002 contact budget and capacity (SQL 03 = reference SQL = manifest) | true |
| 141 | B cohort economics sc-002 draft queue = the first 10 of the ranking (stored rows in my top K vs manifest queue vs reference SQL) | true |
| 142 | B cohort economics sc-002 label hypothetical, no treatment effect, population 97 | true |
| 143 | B cohort economics sc-003 expected value on 97 scored accounts (SQL 03 = reference SQL = manifest = python_side) | true |
| 144 | B cohort economics sc-003 contact budget and capacity (SQL 03 = reference SQL = manifest) | true |
| 145 | B cohort economics sc-003 draft queue = the first 20 of the ranking (stored rows in my top K vs manifest queue vs reference SQL) | true |
| 146 | B cohort economics sc-003 label hypothetical, no treatment effect, population 97 | true |
| 147 | B cohort freshness: scoring 812 h, data 1 h (reference SQL vs manifest vs domain) | true |
| 148 | B dataset version and hash: seed output = manifest = the constant of this package | true |
| 149 | B loaded rows of accounts (database count = manifest row_counts) | true |
| 150 | B loaded rows of subscription_events (database count = manifest row_counts) | true |
| 151 | B loaded rows of billing_events (database count = manifest row_counts) | true |
| 152 | B loaded rows of usage_events (database count = manifest row_counts) | true |
| 153 | B loaded rows of support_events (database count = manifest row_counts) | true |
| 154 | B loaded rows of prediction_cutoffs (database count = manifest row_counts) | true |
| 155 | B loaded rows of feature_rows (database count = manifest row_counts) | true |
| 156 | B loaded rows of predictions (database count = manifest row_counts) | true |
| 157 | B loaded rows of scoring_publications (database count = manifest row_counts) | true |
| 158 | B loaded rows of intervention_scenarios (database count = manifest row_counts) | true |
| 159 | B loaded rows of outreach_events (database count = manifest row_counts) | true |
| 160 | B loaded rows of feature_registry (database count = manifest row_counts) | true |
| 161 | B loaded rows of split_assignments (database count = manifest row_counts) | true |
| 162 | B loaded labels + the rejected injected labels = manifest labels (765 + 4 = 769) | true |
| 163 | B test table loaded = manifest row_counts.test_cohort | true |
| 164 | C 01_model_comparison__models: 5 rows, every cell SQL = python_side.py (digest) | true |
| 165 | C 01_model_comparison__per_cutoff: 4 rows, every cell SQL = python_side.py (digest) | true |
| 166 | C 02_calibration_platt__bins: 20 rows, every cell SQL = python_side.py (digest) | true |
| 167 | C 02_calibration_platt__fit_rows_by_cutoff: 1 rows, every cell SQL = python_side.py (digest) | true |
| 168 | C 02_calibration_platt__platt_effect: 1 rows, every cell SQL = python_side.py (digest) | true |
| 169 | C 02_calibration_platt__platt_reproduced: 1 rows, every cell SQL = python_side.py (digest) | true |
| 170 | C 03_capacity_economics__both_populations: 3 rows, every cell SQL = python_side.py (digest) | true |
| 171 | C 03_capacity_economics__censored_at_the_queue_cutoff: 1 rows, every cell SQL = python_side.py (digest) | true |
| 172 | C 03_capacity_economics__cohort_economics: 3 rows, every cell SQL = python_side.py (digest) | true |
| 173 | C 03_capacity_economics__test_population_at_k: 12 rows, every cell SQL = python_side.py (digest) | true |
| 174 | C 04_censored_tail__cohort_by_cutoff: 21 rows, every cell SQL = python_side.py (digest) | true |
| 175 | C 04_censored_tail__cohort_maturity_rule: 1 rows, every cell SQL = python_side.py (digest) | true |
| 176 | C 04_censored_tail__rejected_false_labels: 1 rows, every cell SQL = python_side.py (digest) | true |
| 177 | C 04_censored_tail__world_by_cutoff: 21 rows, every cell SQL = python_side.py (digest) | true |
| 178 | C 04_censored_tail__world_summary: 1 rows, every cell SQL = python_side.py (digest) | true |
| 179 | C 05_arrived_late__arrived_late_counted_by_range: 4 rows, every cell SQL = python_side.py (digest) | true |
| 180 | C 05_arrived_late__feature_recomputation: 2 rows, every cell SQL = python_side.py (digest) | true |
| 181 | C 05_arrived_late__late_events_by_source: 4 rows, every cell SQL = python_side.py (digest) | true |
| 182 | C 05_arrived_late__published_full_world: 4 rows, every cell SQL = python_side.py (digest) | true |
| 183 | C 06_purge_counts__cohort_label_windows_inside_the_range: 2 rows, every cell SQL = python_side.py (digest) | true |
| 184 | C 06_purge_counts__cohort_no_account_on_both_sides: 1 rows, every cell SQL = python_side.py (digest) | true |
| 185 | C 06_purge_counts__cohort_recomputed: 4 rows, every cell SQL = python_side.py (digest) | true |
| 186 | C 06_purge_counts__cohort_stored: 4 rows, every cell SQL = python_side.py (digest) | true |
| 187 | C 06_purge_counts__world_published: 4 rows, every cell SQL = python_side.py (digest) | true |
| 188 | C 06_purge_counts__world_totals: 1 rows, every cell SQL = python_side.py (digest) | true |
| 189 | C 07_drift_by_region__psi_test_range: 28 rows, every cell SQL = python_side.py (digest) | true |
| 190 | C 07_drift_by_region__published_series_apac: 21 rows, every cell SQL = python_side.py (digest) | true |
| 191 | C 07_drift_by_region__published_summary: 1 rows, every cell SQL = python_side.py (digest) | true |
| 192 | C 08_rows_and_margins__margins: 6 rows, every cell SQL = python_side.py (digest) | true |
| 193 | C 08_rows_and_margins__random_brier_is_uninformative: 1 rows, every cell SQL = python_side.py (digest) | true |
| 194 | C 08_rows_and_margins__rows_and_accounts: 1 rows, every cell SQL = python_side.py (digest) | true |
| 195 | C 09_golden_known_answer__arrived_late: 4 rows, every cell SQL = python_side.py (digest) | true |
| 196 | C 09_golden_known_answer__average_precision_terms: 4 rows, every cell SQL = python_side.py (digest) | true |
| 197 | C 09_golden_known_answer__calibration_bins: 10 rows, every cell SQL = python_side.py (digest) | true |
| 198 | C 09_golden_known_answer__censored_cohort: 1 rows, every cell SQL = python_side.py (digest) | true |
| 199 | C 09_golden_known_answer__known_answer: 1 rows, every cell SQL = python_side.py (digest) | true |
| 200 | C 09_golden_known_answer__psi_against_the_march_2025_cohort: 2 rows, every cell SQL = python_side.py (digest) | true |
| 201 | C 09_golden_known_answer__purge_counts: 3 rows, every cell SQL = python_side.py (digest) | true |
| 202 | C 09_golden_known_answer__ranking: 4 rows, every cell SQL = python_side.py (digest) | true |
| 203 | C 10_segment_region_calibration__by_region: 5 rows, every cell SQL = python_side.py (digest) | true |
| 204 | C 10_segment_region_calibration__by_segment: 4 rows, every cell SQL = python_side.py (digest) | true |
| 205 | C 10_segment_region_calibration__largest_gaps: 3 rows, every cell SQL = python_side.py (digest) | true |
| 206 | C 10_segment_region_calibration__starter_after_the_repricing: 4 rows, every cell SQL = python_side.py (digest) | true |
| 207 | C python_side covers exactly the result sets the SQL files produce | true |
| 208 | D DR-01 random_baseline: average precision and Brier (SQL 01 vs manifest) | true |
| 209 | D DR-01 random_baseline: rows, positives, prevalence (SQL 01 vs manifest) | true |
| 210 | D DR-01 business_rule: average precision and Brier (SQL 01 vs manifest) | true |
| 211 | D DR-01 business_rule: rows, positives, prevalence (SQL 01 vs manifest) | true |
| 212 | D DR-01 logistic_regression: average precision and Brier (SQL 01 vs manifest) | true |
| 213 | D DR-01 logistic_regression: rows, positives, prevalence (SQL 01 vs manifest) | true |
| 214 | D DR-01 prevalence_baseline: average precision and Brier (SQL 01 vs manifest) | true |
| 215 | D DR-01 prevalence_baseline: rows, positives, prevalence (SQL 01 vs manifest) | true |
| 216 | D DR-01 margin ap_over_rule: realised margin (SQL 08 vs manifest; met = by construction) | true |
| 217 | D DR-01 margin ap_over_random: realised margin (SQL 08 vs manifest; met = by construction) | true |
| 218 | D DR-01 margin brier_under_rule: realised margin (SQL 08 vs manifest; met = by construction) | true |
| 219 | D DR-01 margin brier_under_random: realised margin (SQL 08 vs manifest; met = by construction) | true |
| 220 | D DR-01 reference margins over the prevalence constant (SQL 08 vs manifest) | true |
| 221 | D DR-01 the model before Platt: Brier 0.104515 (SQL 01 vs calibration.json platt_effect) | true |
| 222 | D Platt effect (SQL 02 vs calibration.json): Brier before, after, gaps, fit rows, worse on test | true |
| 223 | D Platt mapping a, b (loaded calibration_maps vs calibration.json vs manifest training) | true |
| 224 | D the frozen Platt mapping applied in SQL reproduces the stored calibrated probability on all 1,513 rows | true |
| 225 | D calibration fit rows all come from one cutoff (cohort SQL 02 vs calibration.json fit_rows_by_cutoff) | true |
| 226 | D reliability bin 0 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 227 | D reliability bin 1 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 228 | D reliability bin 2 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 229 | D reliability bin 3 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 230 | D reliability bin 4 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 231 | D reliability bin 5 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 232 | D reliability bin 6 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 233 | D reliability bin 7 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 234 | D reliability bin 8 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 235 | D reliability bin 9 of logistic_regression (Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 236 | D reliability bin 0 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 237 | D reliability bin 1 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 238 | D reliability bin 2 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 239 | D reliability bin 3 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 240 | D reliability bin 4 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 241 | D reliability bin 5 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 242 | D reliability bin 6 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 243 | D reliability bin 7 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 244 | D reliability bin 8 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 245 | D reliability bin 9 of logistic_regression (before Platt): count, mean, observed, gap (SQL 02 vs calibration.json) | true |
| 246 | D DR-02 segment enterprise: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 247 | D DR-02 segment mid: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 248 | D DR-02 segment smb: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 249 | D DR-02 segment starter: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 250 | D DR-02 region amer: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 251 | D DR-02 region anz: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 252 | D DR-02 region apac: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 253 | D DR-02 region emea: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 254 | D DR-02 region latam: n, positives, mean, observed, gap (SQL 10 vs calibration.json) | true |
| 255 | D the largest regional gap is apac, -10.68 pp, not designed (SQL 10 vs calibration.json largest_region_gap) | true |
| 256 | D overall calibration gap -2.86 pp and its mean predicted (SQL 10 vs calibration.json overall) | true |
| 257 | D DR-03 PSI all_accounts 2026-02-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 258 | D DR-03 PSI all_accounts 2026-03-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 259 | D DR-03 PSI all_accounts 2026-04-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 260 | D DR-03 PSI all_accounts 2026-05-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 261 | D DR-03 PSI other_regions 2026-02-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 262 | D DR-03 PSI other_regions 2026-03-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 263 | D DR-03 PSI other_regions 2026-04-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 264 | D DR-03 PSI other_regions 2026-05-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 265 | D DR-03 PSI apac 2026-02-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 266 | D DR-03 floored bins apac 2026-02-01 (SQL from the test table vs published) | true |
| 267 | D DR-03 PSI apac 2026-03-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 268 | D DR-03 floored bins apac 2026-03-01 (SQL from the test table vs published) | true |
| 269 | D DR-03 PSI apac 2026-04-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 270 | D DR-03 floored bins apac 2026-04-01 (SQL from the test table vs published) | true |
| 271 | D DR-03 PSI apac 2026-05-01: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds) | true |
| 272 | D DR-03 floored bins apac 2026-05-01 (SQL from the test table vs published) | true |
| 273 | D DR-03 apac after the change: five exceedances from 2026-05-01, minimum and maximum PSI (SQL 07 vs manifest after_change_psi) | true |
| 274 | D DR-03 the two published pre-change figures are 0.000000 (the reference) and 0.142972 (2026-03-01) (SQL 07 vs manifest before_change_psi) | true |
| 275 | D DR-03 the whole population never exceeds 0.2 (maximum 0.043730) and other regions stay below it (SQL 07 vs the case study's claim) | true |
| 276 | D R10-07 apac pre-change exceedances: 5 of 14 comparison cutoffs, 4 with a floored bin, maximum 0.679573 (SQL 07 vs the published series by python_side) | true |
| 277 | D DR-05 eligible, censored rows, share and mature churn rate (SQL 04 vs manifest) | true |
| 278 | D DR-05 the censored rows are exactly the last three cutoffs (SQL 04 vs manifest immature_cutoffs) | true |
| 279 | D DR-05 2026-07-01 rate if censored rows were counted as non-churn, an integer number of cancellations seen so far (SQL 04 vs manifest) | true |
| 280 | D DR-05 2026-08-01 rate if censored rows were counted as non-churn, an integer number of cancellations seen so far (SQL 04 vs manifest) | true |
| 281 | D DR-05 2026-09-01 rate if censored rows were counted as non-churn, an integer number of cancellations seen so far (SQL 04 vs manifest) | true |
| 282 | D population range outside: eligible, mature, censored, churned (SQL 04 aggregate sums vs manifest population.by_range) | true |
| 283 | D population range test: eligible, mature, censored, churned (SQL 04 aggregate sums vs manifest population.by_range) | true |
| 284 | D population range train: eligible, mature, censored, churned (SQL 04 aggregate sums vs manifest population.by_range) | true |
| 285 | D population range validation: eligible, mature, censored, churned (SQL 04 aggregate sums vs manifest population.by_range) | true |
| 286 | D test prevalence 0.124917 and 1,513 rows (SQL 01 vs manifest population) | true |
| 287 | D R10-06 rows are not accounts: 1,513 rows from 442 accounts, 189 churning rows from 95 accounts (SQL 08 vs the generator test) | true |
| 288 | D DR-04 late share usage_events: published full-world share = manifest realised share (SQL 05 vs manifest); the cohort share is a different population | true |
| 289 | D DR-04 late share billing_events: published full-world share = manifest realised share (SQL 05 vs manifest); the cohort share is a different population | true |
| 290 | D DR-04 late share support_events: published full-world share = manifest realised share (SQL 05 vs manifest); the cohort share is a different population | true |
| 291 | D DR-04 late share subscription_events: published full-world share = manifest realised share (SQL 05 vs manifest); the cohort share is a different population | true |
| 292 | D DR-04 full-world test rows with a late event 183, features that change 175 = 0.115664 (published, SQL 05 vs manifest) | true |
| 293 | D point-in-time: all 765 stored feature rows equal the recomputation from the events (SQL 05) | true |
| 294 | D purge counts of the whole world train (SQL 06 on the published split vs manifest training vs split_summary) | true |
| 295 | D purge counts of the whole world validation (SQL 06 on the published split vs manifest training vs split_summary) | true |
| 296 | D purge counts of the whole world test (SQL 06 on the published split vs manifest training vs split_summary) | true |
| 297 | D purge counts of the whole world outside (SQL 06 on the published split vs manifest training vs split_summary) | true |
| 298 | D purge counts of the cohort train: recomputed in SQL from the cutoff windows vs split_summary published_cohort vs manifest claims | true |
| 299 | D purge counts of the cohort validation: recomputed in SQL from the cutoff windows vs split_summary published_cohort vs manifest claims | true |
| 300 | D purge counts of the cohort test: recomputed in SQL from the cutoff windows vs split_summary published_cohort vs manifest claims | true |
| 301 | D purge counts of the cohort outside: recomputed in SQL from the cutoff windows vs split_summary published_cohort vs manifest claims | true |
| 302 | D the 104-day embargo (SQL 06 vs split_summary vs manifest training) | true |
| 303 | D the training run: 744 rows fit, 79 positives; validation 289 rows, 27 positives (manifest training vs calibration fit_rows) | true |
| 304 | D full-world economics sc-001: scored accounts, budget, value (SQL 03 loaded aggregate vs manifest vs cutoff_aggregates) | true |
| 305 | D full-world economics sc-002: scored accounts, budget, value (SQL 03 loaded aggregate vs manifest vs cutoff_aggregates) | true |
| 306 | D full-world economics sc-003: scored accounts, budget, value (SQL 03 loaded aggregate vs manifest vs cutoff_aggregates) | true |
| 307 | D the cohort values (+21.38 / -6.87 / -95.46 on 97) and the world values (+81.13 / +71.04 / -29.12 on 1,241) are different populations (SQL 03) | true |
| 308 | D top-K of the logistic model on the test population: churners in the top 5, 10, 20 (SQL 03 vs python_side) | true |
| 309 | D INJ-07 four labels of false for an open window are refused CENSORED_LABEL and kept raw (SQL 04 vs injection manifest) | true |
| 310 | D INJ-03 no account retained on both sides of a boundary (SQL 06 vs injection manifest check) | true |
| 311 | D INJ-04 no retained train or validation row has a label window crossing its boundary (SQL 06) | true |
| 312 | D INJ-09 every outreach row is a draft (loaded outreach_events) | true |
| 313 | D INJ-10 the three capacities are within the scored population (SQL 03: scored accounts >= capacity) | true |
| 314 | D cohort maturity rule: stored flag and label_end equal the 104-day rule for all 765 labelled rows (SQL 04) | true |
| 315 | E BI measure average precision and Brier of random_baseline: recomputed from the CSV test rows vs the SQL fact vs investigation 01 vs the manifest | true |
| 316 | E BI measure average precision and Brier of business_rule: recomputed from the CSV test rows vs the SQL fact vs investigation 01 vs the manifest | true |
| 317 | E BI measure average precision and Brier of logistic_regression: recomputed from the CSV test rows vs the SQL fact vs investigation 01 vs the manifest | true |
| 318 | E BI measure average precision and Brier of prevalence_baseline: recomputed from the CSV test rows vs the SQL fact vs investigation 01 vs the manifest | true |
| 319 | E BI measure average precision and Brier of logistic_uncalibrated: recomputed from the CSV test rows vs the SQL fact vs investigation 01 vs the manifest | true |
| 320 | E BI precision_at_k random_baseline sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 321 | E BI recall_at_k random_baseline sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 322 | E BI risk_lift_at_k random_baseline sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 323 | E BI precision_at_k random_baseline sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 324 | E BI recall_at_k random_baseline sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 325 | E BI risk_lift_at_k random_baseline sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 326 | E BI precision_at_k random_baseline sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 327 | E BI recall_at_k random_baseline sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 328 | E BI risk_lift_at_k random_baseline sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 329 | E BI precision_at_k business_rule sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 330 | E BI recall_at_k business_rule sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 331 | E BI risk_lift_at_k business_rule sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 332 | E BI precision_at_k business_rule sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 333 | E BI recall_at_k business_rule sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 334 | E BI risk_lift_at_k business_rule sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 335 | E BI precision_at_k business_rule sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 336 | E BI recall_at_k business_rule sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 337 | E BI risk_lift_at_k business_rule sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 338 | E BI precision_at_k logistic_regression sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 339 | E BI recall_at_k logistic_regression sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 340 | E BI risk_lift_at_k logistic_regression sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 341 | E BI precision_at_k logistic_regression sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 342 | E BI recall_at_k logistic_regression sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 343 | E BI risk_lift_at_k logistic_regression sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 344 | E BI precision_at_k logistic_regression sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 345 | E BI recall_at_k logistic_regression sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 346 | E BI risk_lift_at_k logistic_regression sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 347 | E BI precision_at_k prevalence_baseline sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 348 | E BI recall_at_k prevalence_baseline sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 349 | E BI risk_lift_at_k prevalence_baseline sc-001: recomputed from the CSV rows vs the SQL fact | true |
| 350 | E BI precision_at_k prevalence_baseline sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 351 | E BI recall_at_k prevalence_baseline sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 352 | E BI risk_lift_at_k prevalence_baseline sc-002: recomputed from the CSV rows vs the SQL fact | true |
| 353 | E BI precision_at_k prevalence_baseline sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 354 | E BI recall_at_k prevalence_baseline sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 355 | E BI risk_lift_at_k prevalence_baseline sc-003: recomputed from the CSV rows vs the SQL fact | true |
| 356 | E BI expected value cohort_200 sc-001: measure vs SQL fact vs investigation 03 (hypothetical) | true |
| 357 | E BI expected value cohort_200 sc-002: measure vs SQL fact vs investigation 03 (hypothetical) | true |
| 358 | E BI expected value cohort_200 sc-003: measure vs SQL fact vs investigation 03 (hypothetical) | true |
| 359 | E BI expected value world_2400 sc-001: measure vs SQL fact vs investigation 03 (hypothetical) | true |
| 360 | E BI expected value world_2400 sc-002: measure vs SQL fact vs investigation 03 (hypothetical) | true |
| 361 | E BI expected value world_2400 sc-003: measure vs SQL fact vs investigation 03 (hypothetical) | true |
| 362 | E BI every economics measure is labelled hypothetical and names its population | true |
| 363 | E BI nothing is withheld silently: every row with an empty value has a status other than 'value' | true |
| 364 | E BI the six empty reliability bins of the Platt-calibrated model are rows with a stated reason | true |
| 365 | E BI CSV row counts equal the SQL fact counts (test rows 1513; model metric 5; capacity 18; cutoff 42; drift 91; purge 8; segment gap 9) | true |
| 366 | E BI dimension keys: every fact key is in its dimension (population, model, scenario, cutoff) | true |
| 367 | F full world: the rebuilt test table equals test_cohort.json (1,513 rows x 14 columns, digest) | true |
| 368 | F full world: the rebuilt economics equal manifest economics_full_world and cutoff_aggregates (digest) | true |
| 369 | F full world 2025-01-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 370 | F full world 2025-02-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 371 | F full world 2025-03-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 372 | F full world 2025-04-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 373 | F full world 2025-05-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 374 | F full world 2025-06-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 375 | F full world 2025-07-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 376 | F full world 2025-08-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 377 | F full world 2025-09-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 378 | F full world 2025-10-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 379 | F full world 2025-11-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 380 | F full world 2025-12-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 381 | F full world 2026-01-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 382 | F full world 2026-02-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 383 | F full world 2026-03-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 384 | F full world 2026-04-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 385 | F full world 2026-05-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 386 | F full world 2026-06-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 387 | F full world 2026-07-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 388 | F full world 2026-08-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 389 | F full world 2026-09-01: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest) | true |
| 390 | F full world: the rebuilt censored-tail design relationship equals the manifest (DR-05, digest) | true |
| 391 | F full world: the rebuilt population statistics (accounts, events, ranges, 9,039 eligible rows, 3,594 censored) equal manifest population (digest) | true |
| 392 | F full world: the rebuilt training run (config, config hash, boundaries) equals the published run and the manifest (digest) | true |
| 393 | F full world: the rebuilt split counts equal split_summary and the manifest (digest) | true |
<!-- END:reconciliation_listing -->

## 12. What this analysis does not claim
* It does not claim that any retention improvement exists or would follow from acting on the ranking. The economics are assumptions; a ranking by risk is not a treatment effect; the margins over the baselines are met by construction.
* It does not recompute the whole world from the cohort: world figures are published aggregates, reconciled by re-running the generator, not by SQL over 2,400 accounts.
* The PSI series is a diagnostic with known false positives; it is not proof of drift. Row-level correlation is not corrected, so no interval or significance is given.
* The 97-account and 1,241-account values are different populations.
* SQL `ln()` is PostgreSQL's numeric natural logarithm; the domain uses `Decimal.ln` at 60 digits; both round to 6 places and agree on every compared value, but they are different implementations.
* Average precision and PSI now have a SQL statement. The README and D-06 still say they have none (written before this package); the public case study lists the SQL recomputation under "Not built yet".
