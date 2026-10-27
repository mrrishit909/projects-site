-- TrustLedger review R7 (docs/contracts.md D-10). Idempotent where it can be; applied once by migrate.py.
--
-- * quality_rules: a validity pattern may not use \s \d \w \b (or their negations): the three engines read them differently (R7-04).
-- * metric_versions: the status `reviewed` between `draft` and `published` (FLOW-02, R7-12).
-- * quality_rule_versions: the definition of every rule version, append-only, so an earlier version's eligibility is readable (R7-12).
-- * dataset_rows: new row VERSIONS (C11 correct-dataset-rows): row_version, supersedes_row_id, reason, corrected_by, recorded_at. Nothing is
--   edited; the measurement reads the latest version per record id (R7-07).
-- * dataset_refreshes: each recorded refresh of a dataset, append-only (C12 record-refresh, R7-07).

-- A pattern is portable only without \s \d \w \b (an odd run of backslashes before the letter; `\\s` is a literal backslash and an s).
CREATE OR REPLACE FUNCTION tl_pattern_not_portable(p TEXT) RETURNS BOOLEAN AS $$
    SELECT p IS NOT NULL AND p ~ '(^|[^\\])(\\\\)*\\[sSdDwWbB]'
$$ LANGUAGE sql IMMUTABLE;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'rules_pattern_portable_ck') THEN
        ALTER TABLE quality_rules ADD CONSTRAINT rules_pattern_portable_ck
            CHECK (NOT tl_pattern_not_portable(definition ->> 'pattern'));
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'metric_versions_ck') THEN
        ALTER TABLE metric_versions DROP CONSTRAINT metric_versions_ck;
    END IF;
    ALTER TABLE metric_versions ADD CONSTRAINT metric_versions_ck
        CHECK (status IN ('draft', 'reviewed', 'published', 'superseded') AND version_number >= 1);
END
$$;

-- Row versions. `supersedes_row_id` names the superseded version as '<row_id>@<row_version>'; a first version supersedes nothing.
ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS row_version       INT NOT NULL DEFAULT 1;
ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS supersedes_row_id TEXT;
ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS reason            TEXT;
ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS corrected_by      TEXT;
ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS recorded_at       TIMESTAMPTZ;      -- NULL for the rows loaded with the dataset
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dataset_rows_row_uq') THEN
        ALTER TABLE dataset_rows DROP CONSTRAINT dataset_rows_row_uq;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dataset_rows_version_uq') THEN
        ALTER TABLE dataset_rows ADD CONSTRAINT dataset_rows_version_uq UNIQUE (dataset_id, row_id, row_version);
        ALTER TABLE dataset_rows ADD CONSTRAINT dataset_rows_version_ck CHECK (
            row_version >= 1 AND ((row_version = 1) = (supersedes_row_id IS NULL))
            AND (row_version = 1 OR (length(btrim(coalesce(reason, ''))) > 0 AND corrected_by IS NOT NULL AND recorded_at IS NOT NULL
                                     AND supersedes_row_id = row_id || '@' || (row_version - 1)::text)));
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS dataset_refreshes (
    dataset_id   TEXT NOT NULL REFERENCES datasets (dataset_id),
    refreshed_at TIMESTAMPTZ NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL,
    recorded_by  TEXT NOT NULL,
    PRIMARY KEY (dataset_id, refreshed_at)
);

-- The definition of each version of a rule. `valid_from` is the instant the version took effect (NULL when the loader does not know it).
CREATE TABLE IF NOT EXISTS quality_rule_versions (
    rule_id        TEXT NOT NULL REFERENCES quality_rules (rule_id),
    version_number INT NOT NULL,
    rule_type      TEXT NOT NULL,
    severity       TEXT NOT NULL,
    definition     JSONB NOT NULL,
    valid_from     TIMESTAMPTZ,
    PRIMARY KEY (rule_id, version_number),
    CONSTRAINT rule_versions_ck CHECK (version_number >= 1 AND rule_type IN ('completeness', 'validity', 'uniqueness', 'relationship', 'timeliness')
                                       AND severity IN ('low', 'medium', 'high', 'critical') AND NOT tl_pattern_not_portable(definition ->> 'pattern'))
);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['dataset_refreshes', 'quality_rule_versions']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_immutable') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION tl_forbid_mutation()', t || '_immutable', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION tl_forbid_mutation()', t || '_no_truncate', t);
        END IF;
    END LOOP;
END
$$;
