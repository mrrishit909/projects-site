-- P08-ART-04 artifact-only tables. NOT a migration: the matcher-free pipeline, the API and the seeder never read or write them. prepare_snapshot.py creates them in
-- the SCRATCH snapshot database (artifacts08_*) after the seed, to hold what the seeder does not load from the published files:
--   artifact_batch_summaries      the per-batch counts the generator's domain run computed over ALL raw rows (the published raw_records is a 2,000-row sample)
--   artifact_model_output_totals  the stored candidate total per run (published model_output_totals)
--   artifact_recorded_freshness   the generator's RECORDED latest accepted event per source (manifest stats.freshness_at_as_of): the sample cannot show it
--   artifact_recorded_residual    the recorded parts of the one candidate whose residual is not zero (manifest DR-05)
-- Everything here is labelled by scope in the investigations: complete world, 2,000-row sample, or recorded.
DROP TABLE IF EXISTS artifact_batch_summaries, artifact_model_output_totals, artifact_recorded_freshness, artifact_recorded_residual;

CREATE TABLE artifact_batch_summaries (
    batch_id             TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL,
    kind                 TEXT NOT NULL,                 -- live | replay | backfill | aborted | schema_q | schema_refetch
    status               TEXT NOT NULL,
    sampled              BOOLEAN NOT NULL,              -- the batch's raw rows are in the published 2,000-row sample
    written_rows         INT NOT NULL,
    received             INT NOT NULL,                  -- rows of a COMMITTED batch (0 for a batch that does not count)
    accepted_unique      INT NOT NULL,
    duplicate            INT NOT NULL,
    quarantined          INT NOT NULL,
    deleted              INT NOT NULL,
    quarantine_by_reason JSONB NOT NULL
);

CREATE TABLE artifact_model_output_totals (
    run_id       TEXT PRIMARY KEY,
    output_rows  INT NOT NULL,
    total_amount NUMERIC(20, 2) NOT NULL
);

CREATE TABLE artifact_recorded_freshness (
    source_id                   TEXT PRIMARY KEY,
    latest_accepted_event_at    TIMESTAMPTZ NOT NULL,
    recorded_freshness_seconds  INT NOT NULL,
    recorded_ingestion_age_seconds INT NOT NULL
);

CREATE TABLE artifact_recorded_residual (
    run_id          TEXT PRIMARY KEY,
    day             TEXT NOT NULL,
    source_total    NUMERIC(20, 2) NOT NULL,
    exclusions_total NUMERIC(20, 2) NOT NULL,
    published_total NUMERIC(20, 2) NOT NULL,
    residual        NUMERIC(20, 2) NOT NULL
);
