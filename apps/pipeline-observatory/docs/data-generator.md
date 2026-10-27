# Pipeline Observatory — synthetic data generator specification (P08-WORK-03)

* Seed 20261026; 8 weeks of hourly runs 2026-08-10 .. 2026-10-04, `as_of` 2026-10-05T00:00:00Z; 6 sources with declared
  frequencies and schema versions (one bumps its schema on 2026-09-15), about 1,300 batches with cursors and
  checkpoints, about 40,000 raw records summarised per batch (publish per-batch counts and a sample of 2,000 raw
  records to stay under the cap), quarantine rows by reason, 12 models over 3 layers with definition hashes, about
  1,300 runs with tasks and attempts, quality results per task run, publications with content hashes and watermarks,
  25 incidents with verified recoveries, 15 backfills (two overlapping requests refused).
* Designed relationships: one source goes stale for three days while its jobs stay green; one failed run that must
  not replace the publication; a rate-limited source whose retries honour retry-after; late events behind the
  watermark included in the next publication; the reconciliation residual is zero except for one day with an
  unexplained residual that opens an incident.
* Injected defects (manifest + replay events, one per P08-TEST-01..12): crash after write before checkpoint,
  overlapping backfills, retries ignoring retry-after, an unexpected required field, a malformed row that would vanish,
  a green job on a stale source, a failed run replacing a publication, an unpropagated delete, a late event behind the
  watermark, a pagination token that repeats, a secret in a structured log, a self-triggering workflow.
* Output under 5 MB: raw records and task runs are the volume drivers; sample raw records and keep per-batch
  aggregates; let the cap win and disclose counts.
