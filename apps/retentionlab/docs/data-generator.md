# RetentionLab — synthetic data generator specification (P10-WORK-03)

* Seed 20261026; 2,400 accounts created 2024-01 .. 2026-06 across 4 segments and 5 regions, monthly prediction
  cutoffs 2025-01-01 .. 2026-09-01 with a 90-day horizon and 14-day grace, `as_of` 2026-10-05T00:00:00Z (the last
  three cutoffs are immature); subscription, billing, usage and support events with `available_at` ≥ `event_at`
  (a declared share arrives late); a latent churn propensity per account per cutoff kept only in the manifest;
  feature registry v1 (about 20 features); labels; one training run (train to 2025-10-01, validation to 2026-02-01,
  test to 2026-06-01) with purge counts; predictions from the three models; 3 intervention scenarios; a draft
  outreach queue; the demo profile of section 12.
* Designed relationships: the logistic model beats the rule and the random baseline on the test set by a margin
  the manifest states; a segment with a calibration gap; a cohort with population drift after 2026-03; a late
  arrival share that would flip several features if ignored; a sizeable censored tail.
* Injected defects (manifest + replay events, one per P10-TEST-01..12): a cancellation reason offered as a feature,
  an event arriving after the cutoff, an account repeated across splits, a label window crossing a boundary, a
  preprocessing fit on all rows, a threshold chosen on test, immature rows labelled non-churn, a latent-truth
  column offered as a feature, risk read as responsiveness, a capacity above the population, calibration evaluated
  on its own training rows, an id-derived feature.
* Output under 5 MB; publish per-cutoff aggregates and the test-cohort rows; disclose every outcome-informed choice.
