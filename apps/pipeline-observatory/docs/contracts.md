# Pipeline Observatory — business contracts, version 1 (2026-10-27)

Decision owner: coordinator (Fable 5.1). Spec: `projects/08-pipeline-observatory.md`, SHA-256 `1ffbfbe7…` at pack
commit `fe5f7981` (verified against `docs/program/source-pack.json`). Rules cite the requirement they satisfy;
changing one bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
Is this dataset safe, complete, and fresh enough to publish? (P08-GOAL-01). Primary users: a data engineer and a data
reliability analyst. Boundaries: PostgreSQL only as a service container on GitHub-hosted runners (P08-DOMAIN-01); the
repository is the canonical durable state and transient databases are rebuilt from versioned sources on each run
(P08-DOMAIN-02/03); no exactly-once claim without a boundary proof (P08-DOMAIN-04); publications are immutable static
snapshots (P08-DOMAIN-05); durable results archived as compact versioned files (P08-DOMAIN-06).

## D-01 Ingestion, idempotency and checkpoints
* A source is fetched page by page from a cursor; a page carries the next cursor and a rate-limit hint; a retry
  honours `retry_after_seconds` and never retries sooner; a cursor that repeats itself (same `next_cursor` twice) stops
  the fetch with `CURSOR_LOOP` (P08-FLOW-01, P08-TEST-03, P08-TEST-10).
* Every raw record keeps `payload_hash` = sha256 of the canonical payload and `source_key`; within a batch and across
  batches of one source, a record whose `source_key` was already **accepted** is a **duplicate** (counted separately,
  never quarantined, never accepted twice); a record that fails the contract (schema or semantic check, e.g. a negative
  quantity) is **quarantined** with a reason code and is never silently dropped (P08-FLOW-02, P08-MET-04/05,
  P08-TEST-05). Golden (P08-GOLD-01): received 10, accepted unique 8, duplicate 1, quarantined 1; replaying the batch
  leaves 8 accepted; a crash after the data write but before the checkpoint leaves 8, never 9 (P08-TEST-01).
* A batch commits atomically with its checkpoint: accepted records, quarantine rows and the checkpoint row
  (`committed_cursor`, `version_number` + 1) are one transaction; a replay from the last committed cursor is
  idempotent on `source_key`; the delivery guarantee claimed is **at-least-once with idempotent apply**, proven at the
  source-key boundary, never exactly-once (P08-FLOW-03, P08-DOMAIN-04).
* A schema version that adds a required field is a contract change: the batch is quarantined whole with
  `SCHEMA_CHANGED` and the source's expected `schema_version` must be bumped explicitly (P08-TEST-04). A delete event
  is a record with `op = delete` that must propagate to the published snapshot as an exclusion with its reason, never
  ignored (P08-TEST-08).

## D-02 Freshness, completeness and the publication gate
* Source freshness = cutoff − latest source event timestamp among accepted records; ingestion age = cutoff − last
  **successful** ingestion (a batch whose status is `committed`); the two are distinct and a green run with a stale
  source shows stale freshness (P08-MET-01/02, P08-TEST-06). Completeness = accepted expected records ÷ expected
  records, where the expectation is the synthetic source's declared count per partition (P08-MET-03). Rejection rate =
  quarantined ÷ received; duplicate rate = duplicates ÷ received (P08-MET-04/05).
* The quality gate runs the critical checks (keys unique, relationships intact, reconciliation residual zero,
  freshness within target); any critical failure **blocks publication** and opens an incident; a failed run never
  replaces the current publication (the publication pointer moves only to a passed candidate, atomically)
  (P08-FLOW-05/06, P08-TEST-07). Publication lag = published_at − latest included source event; the publish watermark
  is disclosed with every publication, and an event later than the watermark that arrives afterwards is a late event
  counted and included in the next publication, never lost (P08-MET-08, P08-TEST-09).
* Reconciliation residual = source business total − published business total − explained exclusions (quarantined,
  duplicates, deletes), zero on the golden fixture and reported with its parts (P08-MET-09).

## D-03 Runs, tasks, incidents and backfills
* A run has tasks; a task has attempts; task success rate = successful terminal tasks ÷ terminal tasks (attempts are
  not tasks); pipeline duration = finished_at − started_at with failed and successful distributions separate
  (P08-MET-06/07). Observed processing rate = accepted records ÷ measured processing seconds with the hardware and the
  cache state disclosed (P08-MET-12).
* An incident opens on a failed run or a blocked gate and closes only after a **verified recovery**: a later run
  passes the gate and reconciles; recovery time = verified recovery − detection, never process restart (P08-FLOW-09,
  P08-MET-10). A fault injection is allowed only in the synthetic sandbox and is recorded (P08-FLOW-07).
* A backfill request covers a half-open partition range [start, end); two backfills over overlapping ranges of one
  source cannot run together (`BACKFILL_OVERLAP`); backfill coverage = verified requested partitions ÷ requested
  partitions (P08-FLOW-08, P08-MET-11, P08-TEST-02). Structured logs never contain a secret: a redaction check runs on
  every log line and a workflow never triggers itself (P08-TEST-11/12).
* Archived evidence carries hashes and the retention mapping (P08-FLOW-10).

## D-04 Numbers, time and absence
Proportions are decimal strings with 6 places; durations in seconds as integers or minutes with 4 places as stated;
counts nonnegative integers; money (business totals) Decimal strings with 2 places; null means unknown or zero
denominator, never 0. Instants are UTC with `Z`. Ranges are half-open. Empty population: every count 0, every ratio
null, `empty_population` true.

## D-05 Fixture decisions (adopted from the golden fixture, P08-GOLD-11)
Adopted verbatim from `tests/fixtures/golden/CALCULATION.md` DECISIONS D-P8-01..13; the fixture and `reference_check.py`
are the binding form. In short:
* **Duplicates (D-P8-01).** A record is a duplicate when its `source_key` is already accepted in a committed batch of the same
  source (earlier batch, or earlier in the same batch), whatever its `payload_hash`; the key check runs before the contract
  check. A replayed invalid row is quarantined again, one quarantine row per occurrence (`quarantined` counts occurrences,
  `quarantined_distinct_keys` distinct keys). A changed payload under a known key is still a duplicate; there is no "changed" class.
* **Expected records and completeness (D-P8-02).** `source_expectations` declares the count per source and UTC-date partition,
  including rows that later fail. Completeness = accepted unique records of the partition / expected, not capped, null when
  expected is 0. The partition is the UTC date of the freshness timestamp field.
* **Freshness vs ingestion age (D-P8-03).** Freshness = cutoff - max `payload_json.event_ts` over accepted records; ingestion age =
  cutoff - max `checkpoints.committed_at` over committed batches.
* **Batch statuses (D-P8-04).** `committed` or `aborted`; only committed batches count; an aborted batch's staged rows are evidence only.
* **Business total and reconciliation scope (D-P8-05).** `payload_json.amount` (signed, 2 places). Source total = every received row of
  the batches in `publications.included_batch_ids`; published = accepted rows; exclusions signed (quarantined, duplicates, deletes).
* **Verified recovery (D-P8-06).** The first run at or after `opened_at` that succeeded, passed its gate, published, and reconciled to
  0.00; verified instant = its publication's `published_at`; detection = `opened_at`; a closed incident must agree or `closure_consistent` is false.
* **Metric keys (D-P8-07).** `metrics.{ingestion, freshness, completeness, runs, quality_gate, publications, late_events,
  reconciliation, incidents, backfills, processing_rate}` with the nesting in the fixture; `ingest.counts` are structural import counts.
* **Gate (D-P8-08).** A quality result passes iff `failure_count` = 0; `allowed` iff at least one critical result exists and none
  failed, else `blocked`; the pointer moves only on success + allowed + publication; a blocked run has no publication row.
* **Late event (D-P8-09).** An accepted record whose batch committed after the `published_at` of the latest earlier publication
  covering its source and whose `event_ts` <= that publication's `watermark` (a disclosed field distinct from the latest included event).
* **Hashes (D-P8-10).** `payload_hash` = sha256 of canonical JSON (sorted keys, `,`/`:` separators, ASCII); `content_hash` = sha256 of
  the sorted included payload hashes joined with "\n"; `definition_hash` = sha256 of the definition text.
* **Rejection codes (D-P8-11).** NEGATIVE_QUANTITY, MISSING_FIELD, BACKFILL_OVERLAP, CHECKPOINT_REGRESSION (version <= previous),
  CHECKPOINT_GAP (version > previous + 1), DUPLICATE_ID (repeated primary key, or repeated run/task/attempt), DEPENDENT_REJECTED,
  UNKNOWN_SOURCE / UNKNOWN_BATCH / UNKNOWN_RUN / UNKNOWN_TASK_RUN / UNKNOWN_BACKFILL. A rejected checkpoint rejects its batch and
  the batch's rows. Overlap is judged against earlier accepted requests of the source in `backfill_id` order; half-open daily partitions.
* **Entity fields and names (D-P8-12).** The section-03 names (`source_contracts`, `ingestion_batches`, `model_definitions`,
  `backfill_requests`) and the added fields listed in CALCULATION.md are the schema; the backend migrations mirror them.
* **Durations and rates (D-P8-13).** Run duration = integer seconds; group means in minutes (4 places); headline ingestion rates per
  batch with the source aggregate beside them; processing rate = accepted records of the measured batch / measured seconds, 6 places.
* **Not proven by the fixture.** Cursor pagination with retry-after and CURSOR_LOOP, SCHEMA_CHANGED, delete events, redaction and
  the self-trigger check have no golden inputs; the backend tests must carry their own fixtures for them (P08-TEST-03/04/08/10/11/12).

## D-06 Backend clarifications (adopted from the backend hand-back; the 19 numbered assumptions are in README.md)
* Batch statuses add `staged` (fetched, uncounted) and `quarantined` (refused whole); a crashed commit leaves the batch
  `staged` since a dying transaction cannot write `aborted`; batches apply per source in checkpoint-version order.
* C01 stages a page the fetcher received (the app calls no external source; retry-after enforced per source and cursor;
  cursor loops detected within a fetch session), C02 validates and persists verdicts without counting (and is the only
  way to bump a source's expected `schema_version`, operator or admin), C03 re-classifies under the source lock and
  refuses an unvalidated batch; C03 takes an optional processing measurement.
* Delete events: a delete of a live accepted key is classed `deleted`, a repeated delete `duplicate`, a delete of an
  unknown key quarantined `DELETE_TARGET_UNKNOWN`, an unknown `op` quarantined `UNKNOWN_OP`; a delete removes the record
  from publications that include the deleting batch and enters reconciliation as an exclusion; `received` may exceed
  accepted + duplicate + quarantined by the deleted rows. Extra quarantine reason `INVALID_FIELD`; a row with no key is
  `MISSING_FIELD`.
* Gate: the latest result per rule name counts; C05 computes `keys_unique`, `relationships_intact`,
  `reconciliation_residual_zero` (critical), `freshness_within_target` (critical where the source declares a target)
  and `completeness_vs_expectation` (warning); allowed sets the run `success`, blocked sets it `failed` and opens an
  incident. Publication: `source_ids` is every source contract, the watermark is operator-supplied and never in the
  future, `published_at` is the server's time; the published total is the stored model output where one exists.
* C04 creates a run for a new `run_id`; attempt numbers must be consecutive (409 `DUPLICATE_ID`, 422 `ATTEMPT_GAP`).
  Faults `duplicate_key`, `task_failure`, `crash_before_checkpoint`; sandbox = `PIPELINE_ENVIRONMENT == sandbox`.
  Backfill ranges aligned to UTC midnight; a refused request consumes its id. C09 closes at the verified instant.
* Status codes: 409 for checkpoint regression and gap, `CURSOR_LOOP`, `BACKFILL_OVERLAP`, `DUPLICATE_ID`; 429
  `RETRY_TOO_SOON` with `Retry-After`; 403 `NOT_SANDBOX`; 500 `INJECTED_CRASH`; 422 with the rule id otherwise.
  `/metrics`: `from`/`to` on each entity's primary instant, `cutoff` drops facts not yet known, `group_by` none|source.
  Rows are locked `FOR NO KEY UPDATE`. Database guards: unique (source_id, source_key) on accepted records, checkpoint
  order and commit pairing by trigger, append-only evidence, no publication or pointer for a failed run or blocked gate.
* Known gaps: the SQL reference does not model delete events (domain and API tests do); no real fetcher, scheduler or
  retention job; the workflow guard reads workflow text (no YAML parser in the pinned requirements).

## D-07 Synthetic world (adopted from the generator hand-back; the 17 numbered assumptions are in README.md / the manifest)
Seed 20261026, hourly runs 2026-08-10T01:15 .. 2026-10-04T23:15 (1,343 runs, 1,318 succeeded, 25 planned failures),
`as_of` 2026-10-05T00:00:00Z; 6 sources with cadences 4h/6h/12h/daily, per-source freshness targets (orders 5.5 h,
payments 6 h, shipments 72 h, inventory 72 h, web events 60 h, refunds 7 d) and `src-payments` declaring schema "2"
from 2026-09-15; 1,311 batches (1,278 live, 15 backfill, 8 aborted + 8 replays, 1 schema-quarantined + 1 refetch),
1,302 checkpoints; 40,191 raw rows written, 39,901 received by committed batches, classified 37,248 accepted / 2,101
duplicate / 429 quarantined (plus deletes); 12 models over 3 layers; 5,462 task runs; 6,640 quality results; 1,318
publications; 25 incidents all closed by verified recovery (mean 60.6827 min); 15 backfills (13 accepted, 2 refused
`BACKFILL_OVERLAP`), coverage 11/15 = 0.733333. `dataset_version` po-20261026-20261026, `dataset_hash` d9f0aa18…
over the 16 entity files; `generated_at` = `as_of`.
* A run starts at hh:15 and publishes the snapshot of the UTC day of the tick minus one hour, rebuilt hourly; accepted
  backfills ride on the first run after their batches commit. The watermark is the earliest, over all sources, of the
  window end of the latest batch committed before the gate (so backfill records are always late). Refused backfills
  keep status `requested` with their ids consumed. Crashed ingests end `aborted` with rows and no checkpoint (the
  cleanup state after D-06's `staged`). Stale batches replay the last accepted rows (all duplicates), cursor unchanged,
  checkpoint version still +1. Quality results sit on the quality-gate task run (five checks per gate). No
  `keys_unique` failure occurs in the history (the duplicate-key fault lives in replay event EV-07).
* Extra entities `source_expectations`, `model_output_totals` (the stored candidate total per run; blocked runs'
  residuals come from it), `batch_summaries`, `fetch_log`; extra fields `model_definitions.layer/depends_on`,
  `source_contracts.freshness_target_seconds`; `task_runs.attempt` is an integer in the world (strings in the golden).
* **Published `raw_records` is a sample** of 2,000 rows in 62 whole batches; metrics over the published files describe
  the sample (`content_hash_ok` false for every publication there, `quarantine_rows_match` false for unsampled
  batches) and the manifest states the counts for both the complete and the published world. The processing
  measurement is one synthetic batch, disclosed. Replay events EV-01..12 (74 steps) run after the as-of on a fresh
  database seeded from the published files with the clock frozen per step. The generator memoises `parse_ts` at
  runtime without changing the domain files.
* Designed relationships, realised: DR-01 `src-refunds` stale from 2026-10-02 (freshness 262,378 s vs ingestion age
  17,363 s, 72 green runs, completeness 0.000000 on three days; its 7-day target hides it from the gate, deliberately);
  DR-02 `run-1187` blocked on relationships, pointer stays on `pub-1186`, `inc-022` recovered by `run-1188` after
  67.8833 min; DR-03 49 rate-limited responses on `src-shipments`, all retries honouring retry-after; DR-04 757 late
  events (9 designed, 41 corrections, 707 backfilled), all in the next publication, 0 lost; DR-05 every publication
  reconciles to 0.00 and the one unexplained residual (−141.46 on `run-0731`, 2026-09-09) blocks and opens `inc-015`.
* Outcome-informed choices, disclosed in the manifest: event rates up about 5 % and the shipments cadence 8h → 6h to
  reach the brief's volume; freshness targets loosened and backfills restricted after unplanned gate failures;
  backfill dates re-spaced; slot-flag spacing 3 → 2 days; the freshness-delay margin 2 h → 15 min; no designed
  relationship was tuned on its realised value.
* Gaps: the seeded database is the sample (`seed.py` loads neither `fetch_log`, `model_output_totals` nor the
  processing measurement); late events are dominated by backfills; no replay event exercises C09 or C10; the domain
  over 40,000 rows takes about a minute.

## Mode disclosure
Mode A: Python domain + PostgreSQL + FastAPI verified on hosted runners, including the crash-before-checkpoint and
overlap experiments. Mode B: TypeScript mirror over the published snapshot; the quarantine desk, backfill console and
fault injection are browser-memory simulations and say so.
