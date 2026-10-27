const e=`# Pipeline Observatory golden calculation (contract v1, decisions D-01..D-04)

Independent of application code. \`../../reference_check.py\` recomputes every figure below from \`inputs.json\` and compares it
with \`expected.json\` leaf by leaf (standard library only, no app imports, \`fractions.Fraction\` for every ratio, \`decimal.Decimal\`
for money, no float). The hand-worked headline figures on this page are also typed into the script as literals (\`OK hand.*\`).
Formats (D-04): proportions are 6-place decimal strings, durations are integer seconds (recovery and run means also in minutes,
4 places), money is a 2-place decimal string, null means unknown or a zero denominator, never 0. Instants are UTC with \`Z\`.
Rounding: ROUND_HALF_UP. Cutoff = as_of = 2026-10-05T00:00:00Z. All instants below are on 2026-10-04 unless a date is given.

Entity names are the section-03 names (\`source_contracts\`, \`ingestion_batches\`, \`raw_records\`, \`quarantine_records\`, \`checkpoints\`,
\`model_definitions\`, \`pipeline_runs\`, \`task_runs\`, \`quality_results\`, \`publications\`, \`incidents\`, \`backfill_requests\`). Fields beyond
the section-03 minimum are listed in DECISIONS (D-P8-12).

## The spec sentence [P08-GOLD-01]

> Source supplies 10 rows: 8 valid unique rows, 1 duplicate of a valid key, 1 invalid negative quantity. Received=10, accepted
> unique=8, duplicate=1, quarantined=1. Replaying the batch leaves 8 accepted unique records. A crash before checkpoint must not
> create a ninth accepted business record.

## Part (a): the batch of ten rows (source \`src-orders\`, batch \`b-001\`)

Delivery order (\`raw_record_id\` = \`rr-b-001-NN\`; \`source_key\` = \`payload_json.record_id\`; amount = quantity x unit_price):

| # | source_key | qty | unit_price | amount | event_ts | class |
|---|---|---|---|---|---|---|
| 01 | ORD-1001 | 2 | 12.50 | 25.00 | 08:00 | accepted |
| 02 | ORD-1002 | 1 | 40.00 | 40.00 | 08:20 | accepted |
| 03 | ORD-1003 | 3 | 9.99 | 29.97 | 08:40 | accepted |
| 04 | ORD-1004 | 5 | 4.00 | 20.00 | 09:00 | accepted |
| 05 | ORD-1005 | 1 | 100.00 | 100.00 | 09:10 | accepted |
| 06 | ORD-1003 | 3 | 9.99 | 29.97 | 08:40 | **duplicate** (key accepted at row 03; same payload_hash) |
| 07 | ORD-1006 | 4 | 7.25 | 29.00 | 09:20 | accepted |
| 08 | ORD-1009 | **-3** | 10.00 | -30.00 | 09:25 | **quarantined**, \`NEGATIVE_QUANTITY\` |
| 09 | ORD-1007 | 2 | 15.50 | 31.00 | 09:30 | accepted (latest accepted event) |
| 10 | ORD-1008 | 6 | 2.50 | 15.00 | 09:15 | accepted |

Received 10. Accepted unique = rows 01,02,03,04,05,07,09,10 = **8**. Duplicate = row 06 = **1**. Quarantined = row 08 = **1**
(a quarantine row \`q-b-001-01\` exists, so nothing was dropped; 8 + 1 + 1 = 10).
**Rejection rate = 1/10 = 0.100000. Duplicate rate = 1/10 = 0.100000.**
\`payload_hash\` of every row = sha256 of the canonical JSON payload (sorted keys, separators \`,\` and \`:\`, ASCII); rows 03 and 06 have
the same hash; the script recomputes all 31 hashes.

## Part (b): the replay, batch \`b-002\` (same ten rows, same window \`cur-000\`)

Classification is by source_key against keys already accepted in committed batches (DECISIONS D-P8-01). Rows 01..05, 07, 09, 10 (8 rows)
are replays of accepted keys: duplicates. Row 06 repeats ORD-1003: duplicate. Row 08 (ORD-1009) was never accepted, so the key
check does not apply and the contract check quarantines it again.
Received 10, newly accepted **0**, duplicates 8 + 1 = **9**, quarantined **1** (a second quarantine row \`q-b-002-01\`, same key).
Rates for this batch: rejection 1/10 = 0.100000, duplicate 9/10 = 0.900000.
Source after both batches (committed batches only): received 20, accepted unique **8** (distinct accepted keys; 8 + 0), duplicates
9 + 1 = 10, quarantined occurrences 1 + 1 = 2 over 1 distinct key; rejection rate 2/20 = 0.100000, duplicate rate 10/20 = 0.500000.
**Replay leaves 8 accepted.**

## Part (c): the crash, batch \`b-003\` (status \`aborted\`, no checkpoint)

b-003 re-delivers the window from \`cur-000\` at 18:00:00. Its ten rows were written (\`raw_records\` rr-b-003-01..10, the staged data
write) but the process died before the checkpoint: no \`checkpoints\` row, status \`aborted\`. Rule (D-01): a batch commits atomically
with its checkpoint, so an aborted batch contributes **0** to every count (\`counted\` false, \`written_rows\` 10 as evidence only).
* Checkpoint version after the crash: cp-001 version 1, cp-002 version 2; nothing for b-003. **Version stays 2** (cursor \`cur-010\`,
  batch b-002); \`uncommitted_batches\` = [b-003], with 0 checkpoints.
* Replay from the last committed cursor: every key is already accepted, so the replay yields 0 new accepted; accepted unique stays **8**.
* Why not more than 8: apply is idempotent on source_key. A non-idempotent apply that counted b-003's staged rows would reach 8 + 8 = 16
  (not 9); a ninth record can only appear if the crashed batch carried one extra new valid key. Neither can happen here: counted 8.
  (The brief's "never 9" is therefore satisfied vacuously by this data; see "Contract gaps" in the hand-back.)

## Part (d): freshness versus ingestion age [P08-MET-01/02, D-02]

Cutoff 2026-10-05T00:00:00Z. Committed batches of src-orders: b-001 (checkpoint committed 10:05:00), b-002 (12:05:00); b-003 aborted is not
a successful ingestion.
* Latest accepted event = ORD-1007 at 09:30:00. **Freshness = 00:00 (Oct 5) - 09:30 = 14 h 30 min = 52200 s.**
* Last successful ingestion = 12:05:00 (b-002). **Ingestion age = 11 h 55 min = 42900 s.**
They differ (52200 vs 42900): the newest event is older than the newest committed batch (09:30 < 12:05), and a green run on a stale
source shows the stale freshness. src-refunds: latest event 09:10, ingestion 11:05 -> 53400 s and 46500 s.

## Part (e): completeness against the declared expectation [P08-MET-03]

The synthetic source declares 9 records for partition 2026-10-04 (the 8 valid keys plus ORD-1009, which was expected and then
quarantined). Accepted unique in the partition (UTC date of event_ts) = 8. **Completeness = 8/9 = 0.888889** (the quarantined row is
a missing expected record). src-refunds: 1 expected, 1 accepted: 1.000000.

## Part (f): the run, its tasks and attempts [P08-MET-06/07, D-03]

run-001, 10:10:00 to 10:30:00, status success. Task runs (one row per attempt): ingest att 1 success; transform att 1 **failed**,
transform att 2 success; quality_gate att 1 success; publish att 1 success = 5 attempts, 4 tasks.
* Task success rate = successful terminal tasks / terminal tasks = 4/4 = **1.000000** (a task is successful when its last attempt is).
* Attempts are not conflated: attempt success rate = 4/5 = **0.800000**.
* Duration = finished_at - started_at = 20 min = **1200 s** (successful distribution).
run-002 (12:10:00 to 12:20:00, failed): ingest, transform success, quality_gate failed (3 tasks, 3 attempts): 2/3 = 0.666667, 600 s (failed
distribution). run-003 (20:00:00 to 20:15:00, success): 4/4, 900 s. Across the three runs: tasks 10/11 = 0.909091, attempts 10/12 =
0.833333; successful durations [900, 1200] mean 1050 s = **17.5000 min**; failed [600] = 10.0000 min (kept apart).

## Part (g): the quality gate and the publication pointer [P08-FLOW-05/06, P08-TEST-07]

* run-001 gate: \`keys_unique\` (critical) eligible 8, failures 0 -> pass; \`completeness_vs_expectation\` (warning) eligible 9, failures 1 ->
  fail. One critical passing, no critical failing: **allowed** (a failing non-critical check does not block). Pointer -> pub-001.
* run-002 gate: \`keys_unique\` (critical) eligible 9, failures 1 (an injected duplicate key in the candidate) -> **blocked**; a failed run never
  replaces the publication: pointer after run-002 = **pub-001** (still the first). It also opens inc-001 (below).
* run-003 gate: keys_unique 0/9, reconciliation_residual_zero 0/1 (both critical, pass) -> allowed; pointer -> pub-003.
A check passes iff its failure_count is 0 (D-P8-08). The gate fails closed: no critical result at all would also block.

## Part (h): publication lag, watermark, and the late event [P08-MET-08, P08-TEST-09]

pub-001 published 10:30:00 from b-001; disclosed watermark 10:00:00; latest included event 09:30:00. **Lag = 10:30 - 09:30 = 3600 s.**
pub-003 published 20:15:00 (batches b-001, b-002, b-101), watermark 11:00:00, latest included event still 09:30 -> lag 10 h 45 min = 38700 s.
**Late event:** REF-2001 (src-refunds, batch b-101) has event_ts 09:10:00 <= watermark 10:00:00 of pub-001, but its batch committed at
11:05:00, after pub-001 was published (10:30:00). It is counted (late events = 1), accepted (not dropped), and included in the next
publication, pub-003 (included 1, lost 0). The orders rows arrived at 10:05, before any publication, so none of them is late.
Publication content_hash = sha256 of the sorted payload_hashes of the included accepted records joined by newlines (D-P8-10); verified.

## Part (i): reconciliation [P08-MET-09, D-02]

Residual = source business total - published business total - explained exclusions (quarantined + duplicates + deletes). Business total
field = \`amount\` (D-P8-05). Scope = the batches the publication includes. pub-001, batch b-001:
* Source total = all 10 received amounts = 25.00 + 40.00 + 29.97 + 20.00 + 100.00 + 29.97 + 29.00 - 30.00 + 31.00 + 15.00 = **289.94**.
* Published total = the 8 accepted = 25.00 + 40.00 + 29.97 + 20.00 + 100.00 + 29.00 + 31.00 + 15.00 = **289.97**.
* Exclusions: quarantined row -30.00; duplicate row +29.97; deletes 0.00; total **-0.03**.
* **Residual = 289.94 - 289.97 - (-0.03) = 0.00.** (Signs matter: a quarantined negative amount is a negative exclusion.)
pub-003, batches b-001, b-002, b-101: source 289.94 + 289.94 + 12.00 = 591.88; published 289.97 + 12.00 = 301.97; quarantined -30.00 x 2 =
-60.00; duplicates 29.97 + (289.94 + 30.00 = 319.94) = 349.91; exclusions 289.91; residual 591.88 - 301.97 - 289.91 = **0.00**.

## Part (j): incident and verified recovery [P08-FLOW-09, P08-MET-10]

inc-001: run-002 blocked at 12:20:00 (detection = opened_at). Verified recovery (D-P8-06): a later run (started >= opened_at) with status
success whose gate is allowed, that published, and whose publication reconciles to 0.00: run-003 (started 20:00:00), pub-003 residual 0.00.
Verified instant = pub-003 published_at = 20:15:00. **Recovery time = 20:15:00 - 12:20:00 = 7 h 55 min = 28500 s = 475.0000 min.** (Not
the restart of a process, not the first green task.) closed_at equals the verified instant: consistent.

## Part (k): backfill [P08-MET-11, P08-FLOW-08]

bf-001 over [2026-09-01T00:00:00Z, 2026-09-04T00:00:00Z) is half-open: partitions 09-01, 09-02, 09-03 (09-04 is excluded) = 3. Verified:
09-01, 09-02. **Coverage = 2/3 = 0.666667.** The overlapping request is in variant-rejected.

## Part (l): observed processing rate [P08-MET-12]

b-001 accepted 8 records in a measured 12 s (a declared synthetic fixture value): **8/12 = 0.666667 records per second**; disclosed with the
hardware line "Synthetic fixture value, not a benchmark: 2 vCPU, 8 GB RAM, GitHub-hosted runner class" and cache state "cold". Not a
benchmark claim; an observed rate with its conditions.

## Variant: rejected records [P08-GOLD-08] (\`variant-rejected/\`)

One source, three committed-looking batches, one run, two backfill requests plus one adjacent request. Three rows are rejected, with
their dependants (10 records rejected in all; nothing is dropped, each is listed in \`ingest.rejected_records\` with its raw row):

1. **\`cp-003\` CHECKPOINT_REGRESSION.** Checkpoints of src-orders in commit order carry versions 1 (cp-001), 2 (cp-002), then 1 (cp-003).
   Each commit must be previous + 1 (D-01). Version 1 after 2 means a checkpoint going backwards, which would let a replay re-read data
   already committed. Rejected is correct: the commit is atomic, so the whole batch b-003 is **DEPENDENT_REJECTED** and so are its raw rows
   rr-b-003-01 and rr-b-003-02. Effects: src-orders received 4 (b-001 3 + b-002 1), accepted unique 3, quarantined 1 (ORD-3, negative
   quantity), committed version stays 2; ORD-5 and ORD-6 are never counted (otherwise accepted would be 5).
2. **\`tr-001-2\` DUPLICATE_ID.** run-001 already has ingest attempt 1 (tr-001-1); a second row for the same run, task and attempt number
   repeats the attempt. Attempts must be distinct, or a retry could be hidden or counted twice. Rejected is correct; its quality result
   qr-001-2 is **DEPENDENT_REJECTED**. Run-001: tasks ingest and quality_gate, 2/2 = 1.000000, attempts 2/2.
3. **\`bf-002\` BACKFILL_OVERLAP.** bf-002 covers [09-03, 09-06) and bf-001 [09-01, 09-04) is accepted: 09-03 is in both (start 09-03 < end
   09-04 and 09-01 < end 09-06). Two backfills over overlapping ranges of one source cannot run together. Its run \`run-bf-2\` (backfill_id
   bf-002), the task tr-bf2-1 and the quality result qr-bf2-1 are **DEPENDENT_REJECTED**. bf-003 [09-04, 09-05) merely touches bf-001's end
   (09-04 is excluded from bf-001) so it is accepted: half-open ranges. Coverage: bf-001 2/3, bf-003 0/1 = 0.000000 (a zero numerator is
   0, not null), overall 2/4 = 0.500000.
Other figures: completeness 3/4 = 0.750000; reconciliation of pub-001 (b-001, b-002): source 20.00 + 5.50 - 8.00 + 12.00 = 29.50, published
20.00 + 5.50 + 12.00 = 37.50, exclusion -8.00, residual 29.50 - 37.50 + 8.00 = 0.00; processing 2/6 = 0.333333 records per second;
publication lag 11:30 - 09:30 = 7200 s.

## Variant: empty population [P08-GOLD-09] (\`variant-empty/\`)

One source contract, a declared expectation of 0 records for the partition, and no batch, row, run, publication, incident or backfill.
Every count is 0; every ratio (rejection rate, duplicate rate, completeness 0/0, task and attempt success, run-duration mean, backfill
coverage, processing rate, mean recovery) is **null**, not 0; freshness and ingestion age are null (no accepted event, no committed batch);
\`current_publication_id\` null; \`empty_population\` true (no raw_record received).

## DECISIONS (what the contract leaves open; every one proposed for coordinator approval, P08-GOLD-11)

* **D-P8-01 Duplicate classification on replay.** A record is a duplicate when its source_key is already accepted in a committed batch
  of the same source (earlier batch, or earlier in the same batch), whatever its payload_hash; the key check runs before the contract
  check. Replays of accepted keys are therefore duplicates (b-002: 8 replays + the original duplicate = 9). A replayed invalid row
  is quarantined again, one quarantine row per occurrence (\`quarantined\` counts occurrences, \`quarantined_distinct_keys\` distinct keys).
  Open: same key with a different payload_hash (a changed record) is still a duplicate here; the contract has no "changed" class.
* **D-P8-02 "Expected records".** The declared count per source and partition (\`source_expectations\`), counting every record the source
  intends to deliver for the partition including ones that later fail validation. Completeness = accepted unique records whose partition is
  that one / expected_records, not capped at 1; null when expected is 0. A partition is the UTC date of the freshness timestamp field.
* **D-P8-03 Freshness timestamp field.** \`payload_json.event_ts\` (declared in inputs as \`freshness_timestamp_field\`). Freshness = cutoff - max
  event_ts of accepted records; ingestion age = cutoff - max \`checkpoints.committed_at\` of committed batches (batch has no end time).
* **D-P8-04 Aborted and other statuses.** \`ingestion_batches.status\` in {committed, aborted}; only committed batches count; an aborted
  batch's staged rows are evidence, never counted, and its checkpoint (none expected) would be ignored.
* **D-P8-05 Business total field.** \`payload_json.amount\`, a money string with 2 places, signed. Source total = sum over every received row
  of the batches in scope; published total = sum over accepted rows; exclusions are signed sums (quarantined, duplicates, deletes).
  Scope = the batches a publication lists in \`included_batch_ids\`. Deletes are not exercised (the reference asserts no \`op\` other than upsert).
* **D-P8-06 Verified recovery.** The first run starting at or after the incident's opened_at that is status success, has an allowed gate,
  published, and whose publication reconciles to residual 0.00. Verified instant = that publication's published_at; recovery = verified - opened_at
  (detection = opened_at). A closed incident must match (recovery_run_id and closed_at) else \`closure_consistent\` is false.
* **D-P8-07 Metric keys and nesting.** \`metrics.{ingestion,freshness,completeness,runs,quality_gate,publications,late_events,reconciliation,
  incidents,backfills,processing_rate}\`; ingestion is keyed \`sources.<source_id>.batches.<batch_id>\` plus \`overall\`; completeness
  \`<source_id>.<partition>\`; reconciliation, publications, gate and incidents keyed by their entity id; rates are \`*_rate\` strings.
  Entity import counts under \`ingest.counts.<entity>.{accepted,rejected}\` are structural imports and differ from record-level \`accepted_unique\`.
* **D-P8-08 Check pass rule and gate.** A quality result passes iff failure_count = 0; severity values \`critical\` and \`warning\`; decision
  \`allowed\` iff at least one critical result exists and none failed, else \`blocked\` (fail closed). The pointer moves to a run's publication
  only if the run status is success, the gate is allowed and a publication exists; a blocked run has no publication row.
* **D-P8-09 Late event.** An accepted record whose arrival (its batch's checkpoint committed_at) is after the published_at of the latest
  earlier publication that covers its source and whose event_ts <= that publication's watermark. The watermark is a disclosed field of the
  publication, distinct from the latest included event. Next publication = the first later one that includes the record's batch.
* **D-P8-10 content_hash.** sha256 of the sorted payload_hashes of the accepted records included, joined with "\\n"; definition_hash =
  sha256 of the model definition text; payload_hash = sha256 of canonical JSON (sorted keys, \`,\` \`:\` separators, ASCII).
* **D-P8-11 Rejection codes and rules.** Dedicated codes: NEGATIVE_QUANTITY, MISSING_FIELD (a required payload field absent), BACKFILL_OVERLAP,
  CHECKPOINT_REGRESSION (version <= previous), CHECKPOINT_GAP (version > previous + 1), DUPLICATE_ID (repeated primary key or repeated
  run/task/attempt), DEPENDENT_REJECTED, UNKNOWN_SOURCE / UNKNOWN_BATCH / UNKNOWN_RUN / UNKNOWN_TASK_RUN / UNKNOWN_BACKFILL. A rejected
  checkpoint rejects its batch (atomic commit) and thereby the batch's rows. Overlap is judged against earlier accepted requests of the
  source in backfill_id order; ranges are half-open and daily (UTC) partitions.
* **D-P8-12 Fields added to the section-03 minimum.** \`checkpoints.batch_id\`; \`publications.{watermark,source_ids,included_batch_ids}\`;
  \`quality_results.severity\`; \`pipeline_runs.backfill_id\`; \`incidents.{closed_at,recovery_run_id}\`; \`backfill_requests.partitions\`
  (\`partition\`, \`verified\`); \`model_definitions.definition\`; payload fields \`record_id, quantity, unit_price, amount, event_ts\`. Inputs also carry
  \`cutoff\`, \`business_total_field\`, \`freshness_timestamp_field\`, \`partition_rule\`, \`source_expectations\`, \`processing_measurement\`.
* **D-P8-13 Durations and rates.** Run duration = finished_at - started_at integer seconds; group means in minutes (4 places). Headline ingestion
  rates are per batch (b-001 0.100000 / 0.100000); the source aggregate (over committed batches) is reported beside them. Processing rate =
  accepted records of the measured batch / measured seconds, records per second, 6 places.

## Not exercised by this fixture

Cursor pagination with retry-after and \`CURSOR_LOOP\` (P08-TEST-03/10), \`SCHEMA_CHANGED\` (P08-TEST-04), delete events (P08-TEST-08), the
redaction and workflow self-trigger checks (P08-TEST-11/12) need page, schema or log inputs this fixture does not carry; they need their own
fixtures.
`;export{e as default};
