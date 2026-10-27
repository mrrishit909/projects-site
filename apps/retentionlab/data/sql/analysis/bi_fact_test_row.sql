-- P10-ART-06 fact: one row per test-table row (grain: account x test cutoff), the model probabilities and the outcome; population test_world.
SELECT row_no, account_id, prediction_at, segment AS segment_key, region AS region_key, usage_events_30d, days_since_last_usage, high_severity_support_90d, billing_total_90d, churned,
       p_random_baseline, p_business_rule, p_logistic_calibrated AS p_logistic_regression, p_prevalence_baseline, p_logistic_uncalibrated
FROM art_test_table ORDER BY row_no;
