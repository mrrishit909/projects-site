-- The verification layer's truth table. NOT a migration: the matcher, the API and the pipeline never read it. A test (or a
-- reviewer) loads the fixture's ``synthetic_truth.true_entity`` here so that data/sql/reference_metrics.sql and the API's
-- verification step can compute match precision; without it precision is null (unknown), never 0.
CREATE TABLE IF NOT EXISTS verification_truth (
    record_id   TEXT PRIMARY KEY,
    true_entity TEXT NOT NULL
);
