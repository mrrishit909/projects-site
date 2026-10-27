-- P10-ART-04 verification layer. NOT a migration: the domain, the API and the seeder never read or load it.
-- data/sql/analysis/prepare_snapshot.py creates it in a SCRATCH database (artifacts10_*) after the seed and fills it from the published
-- files of web/public/data (test_cohort.json, cutoff_aggregates.json, split_summary.json, manifest.json). Only the analysis investigations
-- and the BI queries read it. Every table says which population its rows describe (the full 2,400-account world, not the 200-account cohort).
DROP TABLE IF EXISTS art_test_table, art_cutoff_aggregate, art_drift_published, art_economics_full_world, art_split_population, art_published_claim;

-- all 1,513 mature eligible rows of the test range of the FULL world (4 cutoffs), the four models' probabilities and the outcome (population: full world)
CREATE TABLE art_test_table (
    row_no INT PRIMARY KEY,                    -- position in test_cohort.json (cutoff, then account)
    account_id BIGINT NOT NULL,
    cutoff_index INT NOT NULL,
    prediction_at TIMESTAMPTZ NOT NULL,
    segment TEXT NOT NULL,
    region TEXT NOT NULL,
    usage_events_30d INT,
    days_since_last_usage INT,
    high_severity_support_90d INT,
    billing_total_90d NUMERIC(20,6),
    churned SMALLINT NOT NULL CHECK (churned IN (0, 1)),
    p_random_baseline NUMERIC(20,6) NOT NULL,
    p_business_rule NUMERIC(20,6) NOT NULL,
    p_logistic_uncalibrated NUMERIC(20,6) NOT NULL,
    p_logistic_calibrated NUMERIC(20,6) NOT NULL,
    p_prevalence_baseline NUMERIC(20,6) NOT NULL,
    UNIQUE (account_id, cutoff_index)
);

-- per-cutoff counts of the FULL world (cutoff_aggregates.json): one row per monthly cutoff
CREATE TABLE art_cutoff_aggregate (
    prediction_at TIMESTAMPTZ PRIMARY KEY,
    split_range TEXT NOT NULL,
    cutoff_rows INT NOT NULL,
    eligible INT NOT NULL,
    mature INT NOT NULL,
    censored INT NOT NULL,
    churned INT NOT NULL,
    scored INT NOT NULL,
    evaluated INT NOT NULL,
    churn_rate NUMERIC(20,6),
    late_events_total INT NOT NULL,
    late_usage INT NOT NULL, late_billing INT NOT NULL, late_support INT NOT NULL, late_subscription INT NOT NULL
);

-- the usage_events_30d stability series of the FULL world (cutoff_aggregates.json drift.by_cutoff), three groups per cutoff
CREATE TABLE art_drift_published (
    prediction_at TIMESTAMPTZ NOT NULL,
    grp TEXT NOT NULL CHECK (grp IN ('all_accounts', 'apac', 'other_regions')),
    psi NUMERIC(20,6),
    current_rows INT NOT NULL,
    reference_rows INT NOT NULL,
    floored_bins INT,                          -- published for the region groups only; NULL for all_accounts
    exceeds_threshold BOOLEAN NOT NULL,
    PRIMARY KEY (prediction_at, grp)
);

-- economics of the FULL world at the 2026-09-01 cutoff (cutoff_aggregates.json economics_full_world): hypothetical, assumption-based
CREATE TABLE art_economics_full_world (
    scenario_id TEXT PRIMARY KEY,
    capacity INT NOT NULL,
    scored_accounts INT NOT NULL,
    contact_cost NUMERIC(20,6) NOT NULL,
    assumed_effect NUMERIC(20,6) NOT NULL,
    margin_value NUMERIC(20,6) NOT NULL,
    contact_budget NUMERIC(20,6) NOT NULL,
    expected_value NUMERIC(20,2) NOT NULL,
    label TEXT NOT NULL
);

-- split counts of the FULL world per range (split_summary.json population): the domain's purge result, published
CREATE TABLE art_split_population (
    split_range TEXT PRIMARY KEY,
    total INT NOT NULL, retained INT NOT NULL, label_window INT NOT NULL, group_test INT NOT NULL, group_validation INT NOT NULL
);

-- figures the manifest publishes for comparison (name, population, value as text): the second source of the reconciliation
CREATE TABLE art_published_claim (
    claim TEXT PRIMARY KEY,
    population TEXT NOT NULL,
    value TEXT
);
