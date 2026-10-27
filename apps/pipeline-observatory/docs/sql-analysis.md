# SQL analysis (P08-ART-04)

Dataset `po-20261026-20261026` (generator `dataset_hash` `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`), contract v1, code revision `ed7eb5a` (the app content published as `b326690`), as-of 2026-10-05T00:00:00Z. **Synthetic data only**: one generated platform (seed 20261026), nothing about a real pipeline. Observed results (what this one draw shows), constructed relationships (the generator's designed relationships DR-01..DR-05 and twelve injected defects) and hypothetical benefits (not claimed) are kept apart.
The decision these queries support: **is this dataset safe, complete and fresh enough to publish?** (P08-GOAL-01).

**How to read it without installing anything:** every table below is rendered from `artifacts/analysis-results.json` by `artifacts/render_sql_analysis.py` (no figure is typed into a table), and `tests/test_artifacts.py` re-renders in memory and fails on any drift. Each section names its question, its **scope** and the file that answers it. To run it yourself: `data/sql/analysis/run_all.py` (section 11).

## 0. Scope and conventions
Every figure carries one of three scopes (D-08, D-09 R8-09), because the published `raw_records` is a **2,000-row sample** of 62 whole batches (50 of which carry rows) of a world of 40,191 raw rows:
* **complete world**: computed here from tables the files carry in full (batches, checkpoints, runs, tasks, quality results, publications, incidents, backfills, quarantine rows, expectations, the fetch log, the per-batch counts `batch_summaries`);
* **2,000-row sample**: computed from the loaded raw rows; it describes the sample, not the pipeline;
* **recorded**: a statement of the generator about the complete world that the files cannot recompute (the latest accepted event per source, the 757 late events, the residual of each publication); the analysis reads it, labels it, and recomputes only the arithmetic around it.

Proportions are decimal fractions with six places, minutes four places, instants UTC with `Z`; a zero denominator is null, never 0. Every `ORDER BY` of a text column says `COLLATE "C"` (or orders by a number or an instant); no investigation writes. Result sets are named `<file>__<block>`; `python_side.py` recomputes each from the raw JSON in plain Python and `run_all.py` compares them cell by cell.

| File | Question | Scope |
|---|---|---|
| `00_definitions.sql` | the gate result, stage and failure kind of every run; the verified recovery of every incident (temporary tables) | complete world |
| `01_ingestion_by_source.sql` | rows received, accepted, duplicate, quarantined, deleted and the rates per source, the schema-quarantined batch apart, crash and replay | complete world |
| `02_run_funnel_by_failure_kind.sql` | 1,343 / 1,328 / 1,318 / 10 / 15 by failure kind | complete world |
| `03_task_vs_attempt_success.sql` | task success against attempt success | complete world |
| `04_freshness_vs_ingestion_age.sql` | freshness against ingestion age per source; the silent source | ingestion age: complete world; freshness: recorded |
| `05_publication_pointer_and_blocked_runs.sql` | the publication pointer and the runs that never moved it | complete world |
| `06_incidents_and_verified_recovery.sql` | incidents and verified recovery minutes | complete world (the one residual: recorded) |
| `07_backfill_coverage_and_refused_overlaps.sql` | backfill coverage and the refused overlaps | complete world |
| `08_fetch_log_retry_after.sql` | retry-after compliance, refetch against loop | complete world |
| `09_golden_known_answer.sql` | the golden known answer (the golden database) | the 32-row fixture |
| `10_sample_scope_reconciliation.sql` | what the sample shows against the world and the record | all three, compared |

## 1. Ingestion counts and rates per source (`01_ingestion_by_source.sql`)
**Question:** of the rows the sources sent, how many entered the dataset, how many were refused and why, and where did the schema-quarantined rows go? **Scope:** complete world (the per-batch counts are the generator's domain run over all 40,191 raw rows).

Committed batches by source (received = accepted + duplicate + quarantined + deleted; the rates divide by received):
<!-- BEGIN:01_ingestion_by_source__by_source -->
| source_id | committed_batches | received | accepted_unique | duplicate | quarantined | deleted | rejection_rate | duplicate_rate |
|---|---|---|---|---|---|---|---|---|
| src-inventory | 61 | 1723 | 1630 | 72 | 21 | 0 | 0.012188 | 0.041788 |
| src-orders | 335 | 16815 | 16066 | 502 | 181 | 66 | 0.010764 | 0.029854 |
| src-payments | 336 | 10805 | 10125 | 522 | 123 | 35 | 0.011384 | 0.048311 |
| src-refunds | 228 | 4295 | 3785 | 468 | 42 | 0 | 0.009779 | 0.108964 |
| src-shipments | 226 | 4410 | 3985 | 368 | 35 | 22 | 0.007937 | 0.083447 |
| src-web-events | 116 | 1853 | 1657 | 169 | 27 | 0 | 0.014571 | 0.091203 |
<!-- END:01_ingestion_by_source__by_source -->

Overall (rates from the sums, not the mean of the source rates):
<!-- BEGIN:01_ingestion_by_source__overall -->
| committed_batches | received | accepted_unique | duplicate | quarantined | deleted | rejection_rate | duplicate_rate | unclassified |
|---|---|---|---|---|---|---|---|---|
| 1302 | 39901 | 37248 | 2101 | 429 | 123 | 0.010752 | 0.052655 | 0 |
<!-- END:01_ingestion_by_source__overall -->

**Reading.** 39,901 rows reached committed batches: 37,248 accepted, 2,101 duplicates, 429 quarantined, plus 123 delete events propagated as exclusions; rejection rate 0.010752, duplicate rate 0.052655. `src-refunds` has the highest duplicate rate (0.108964): 156 of its 468 duplicates come from the three days after it went silent, when it kept answering with the same page (section 4). Quarantined occurrences against distinct keys (a replayed invalid row is quarantined again):
<!-- BEGIN:01_ingestion_by_source__quarantine_distinct_keys -->
| source_id | quarantine_rows | distinct_keys | rows_without_key |
|---|---|---|---|
| src-inventory | 21 | 21 | 0 |
| src-orders | 181 | 166 | 1 |
| src-payments | 123 | 115 | 0 |
| src-refunds | 42 | 42 | 0 |
| src-shipments | 35 | 32 | 0 |
| src-web-events | 27 | 27 | 0 |
<!-- END:01_ingestion_by_source__quarantine_distinct_keys -->

The quarantine rows by reason, split by where they sit. **The one batch refused whole for a schema change is listed separately and is in no rate** (D-09 R8-10): 429 quarantine rows in committed batches plus 17 in `b-0847` make the 446 published.
<!-- BEGIN:01_ingestion_by_source__quarantine_by_reason -->
| reason_code | in_committed_batches | in_schema_quarantined_batch | in_other_batches | all_rows |
|---|---|---|---|---|
| DELETE_TARGET_UNKNOWN | 25 | 0 | 0 | 25 |
| INVALID_FIELD | 85 | 0 | 0 | 85 |
| MISSING_FIELD | 96 | 0 | 0 | 96 |
| NEGATIVE_QUANTITY | 220 | 0 | 0 | 220 |
| SCHEMA_CHANGED | 0 | 17 | 0 | 17 |
| UNKNOWN_OP | 3 | 0 | 0 | 3 |
<!-- END:01_ingestion_by_source__quarantine_by_reason -->

The schema-quarantined batch and the fetch of the same window committed after the version was bumped on purpose (INJ-04, P08-TEST-04):
<!-- BEGIN:01_ingestion_by_source__schema_quarantined -->
| batch_id | source_id | status | started_at | source_cursor | kind | written_rows | schema_changed_rows | checkpoints | contract_schema_version |
|---|---|---|---|---|---|---|---|---|---|
| b-0847 | src-payments | quarantined | 2026-09-15T02:04:17Z | off-006575 | schema_q | 17 | 17 | 0 | 2 |
| b-0848 | src-payments | committed | 2026-09-15T02:41:37Z | off-006575 | schema_refetch | 17 | 0 | 1 | 2 |
<!-- END:01_ingestion_by_source__schema_quarantined -->

The 1,311 batches by kind and status (aborted batches carry rows and no checkpoint and count for nothing):
<!-- BEGIN:01_ingestion_by_source__by_batch_kind -->
| kind | status | batches | written_rows | received | accepted_unique | duplicate | checkpoints |
|---|---|---|---|---|---|---|---|
| aborted | aborted | 8 | 273 | 0 | 0 | 0 | 0 |
| backfill | committed | 15 | 715 | 715 | 707 | 0 | 15 |
| live | committed | 1278 | 38896 | 38896 | 36271 | 2087 | 1278 |
| replay | committed | 8 | 273 | 273 | 255 | 12 | 8 |
| schema_q | quarantined | 1 | 17 | 0 | 0 | 0 | 0 |
| schema_refetch | committed | 1 | 17 | 17 | 15 | 2 | 1 |
<!-- END:01_ingestion_by_source__by_batch_kind -->

**The delivery guarantee at the key boundary, at the scale of the world** (INJ-01, P08-TEST-01): every aborted batch was fetched again from the same cursor, committed with the next checkpoint version, and its rows were classified exactly once. 273 rows were written by the eight crashed ingests and 273 were classified by the eight replays (255 accepted, 12 duplicates, 6 quarantined); no key was accepted twice (`accepted_records` has a primary key on `(source_id, source_key)`).
<!-- BEGIN:01_ingestion_by_source__crash_replay -->
| aborted_batch | source_id | aborted_rows | aborted_checkpoints | replay_batch | replay_received | replay_accepted | replay_duplicate | replay_quarantined | previous_version | replay_version | version_step | rows_classified_once |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b-0165 | src-orders | 18 | 0 | b-0166 | 18 | 15 | 3 | 0 | 42 | 43 | 1 | true |
| b-0365 | src-orders | 81 | 0 | b-0366 | 81 | 75 | 3 | 3 | 93 | 94 | 1 | true |
| b-0453 | src-shipments | 10 | 0 | b-0454 | 10 | 10 | 0 | 0 | 78 | 79 | 1 | true |
| b-0596 | src-orders | 71 | 0 | b-0597 | 71 | 69 | 1 | 1 | 152 | 153 | 1 | true |
| b-0675 | src-refunds | 26 | 0 | b-0676 | 26 | 24 | 1 | 1 | 117 | 118 | 1 | true |
| b-0714 | src-payments | 34 | 0 | b-0715 | 34 | 32 | 2 | 0 | 182 | 183 | 1 | true |
| b-0759 | src-refunds | 6 | 0 | b-0760 | 6 | 5 | 0 | 1 | 131 | 132 | 1 | true |
| b-0975 | src-refunds | 27 | 0 | b-0976 | 27 | 25 | 2 | 0 | 168 | 169 | 1 | true |
<!-- END:01_ingestion_by_source__crash_replay -->

## 2. The run funnel by failure kind (`02_run_funnel_by_failure_kind.sql`)
**Question:** how often does the pipeline fail, where does it fail, and which failures can a gate see? **Scope:** complete world.
<!-- BEGIN:02_run_funnel_by_failure_kind__funnel -->
| runs | reached_gate | allowed | blocked_at_gate | failed_before_gate | succeeded | failed | published | backfill_runs |
|---|---|---|---|---|---|---|---|---|
| 1343 | 1328 | 1318 | 10 | 15 | 1318 | 25 | 1318 | 13 |
<!-- END:02_run_funnel_by_failure_kind__funnel -->

**Reading.** 1,343 hourly runs: 1,328 reached the quality gate, 1,318 were allowed and 10 were blocked; the other 15 failed in a task before the gate ran. "25 failed" is true; "25 blocked" is not (review finding R8-07; the domain's pointer history labels all 25 `blocked` because a run with no critical result is not allowed, which is why the funnel keeps the stages apart). The 25 by stage and kind:
<!-- BEGIN:02_run_funnel_by_failure_kind__by_failure_kind -->
| stage | failure_kind | runs | incidents | mean_duration_minutes | first_run | last_run |
|---|---|---|---|---|---|---|
| blocked_at_gate | freshness | 5 | 5 | 9.3033 | run-0225 | run-1146 |
| blocked_at_gate | relationships | 4 | 4 | 9.6333 | run-0780 | run-1232 |
| blocked_at_gate | residual | 1 | 1 | 9.1833 | run-0731 | run-0731 |
| failed_before_gate | gate_infra | 3 | 3 | 16.5000 | run-0206 | run-0655 |
| failed_before_gate | ingest | 3 | 3 | 8.6667 | run-0179 | run-0510 |
| failed_before_gate | transform | 9 | 9 | 19.2593 | run-0185 | run-1244 |
<!-- END:02_run_funnel_by_failure_kind__by_failure_kind -->

What the gate asked of the 1,328 runs that reached it (seven checks each). `completeness_vs_expectation` is a warning that fails in 1,304 of 1,328 gates (0.981928) and so carries little signal; only the critical checks block:
<!-- BEGIN:02_run_funnel_by_failure_kind__gate_checks -->
| rule_name | severity | gates | failed | failed_share | eligible_total | failure_total |
|---|---|---|---|---|---|---|
| freshness_within_target | critical | 1328 | 5 | 0.003765 | 7279 | 5 |
| keys_unique | critical | 1328 | 0 | 0.000000 | 441635 | 0 |
| late_events_included | critical | 1328 | 0 | 0.000000 | 757 | 0 |
| reconciliation_residual_zero | critical | 1328 | 1 | 0.000753 | 1328 | 1 |
| relationships_intact | critical | 1328 | 4 | 0.003012 | 441635 | 4 |
| scope_complete | critical | 1328 | 0 | 0.000000 | 18159 | 0 |
| completeness_vs_expectation | warning | 1328 | 1304 | 0.981928 | 23821330 | 275219 |
<!-- END:02_run_funnel_by_failure_kind__gate_checks -->

Run durations (failed and successful kept apart, P08-MET-07) and the failures by week (not clustered by design):
<!-- BEGIN:02_run_funnel_by_failure_kind__durations -->
| status | runs | min_seconds | max_seconds | mean_minutes |
|---|---|---|---|---|
| failed | 25 | 428 | 1325 | 13.7227 |
| success | 1318 | 660 | 1327 | 13.9114 |
<!-- END:02_run_funnel_by_failure_kind__durations -->
<!-- BEGIN:02_run_funnel_by_failure_kind__failures_by_week -->
| week_start | runs | failed | blocked_at_gate | failed_before_gate |
|---|---|---|---|---|
| 2026-08-10 | 167 | 0 | 0 | 0 |
| 2026-08-17 | 168 | 6 | 2 | 4 |
| 2026-08-24 | 168 | 2 | 0 | 2 |
| 2026-08-31 | 168 | 5 | 1 | 4 |
| 2026-09-07 | 168 | 4 | 3 | 1 |
| 2026-09-14 | 168 | 1 | 0 | 1 |
| 2026-09-21 | 168 | 3 | 1 | 2 |
| 2026-09-28 | 168 | 4 | 3 | 1 |
<!-- END:02_run_funnel_by_failure_kind__failures_by_week -->

## 3. Task success against attempt success (`03_task_vs_attempt_success.sql`)
**Question:** how reliable are the jobs when retries are allowed, and how much do the retries hide? **Scope:** complete world.
<!-- BEGIN:03_task_vs_attempt_success__overall -->
| tasks_terminal | tasks_successful | task_success_rate | attempts | attempts_successful | attempt_success_rate | tasks_retried | retried_then_succeeded |
|---|---|---|---|---|---|---|---|
| 5332 | 5307 | 0.995311 | 5462 | 5307 | 0.971622 | 115 | 100 |
<!-- END:03_task_vs_attempt_success__overall -->

**Reading.** 5,332 tasks (a task is a run and a task name), 5,307 ended successfully: task success 0.995311. The same work took 5,462 attempts of which 5,307 succeeded: attempt success 0.971622. An attempt is not a task. 115 tasks needed more than one attempt; 100 of them succeeded on a retry, 15 used all three attempts and failed; the other 10 failed tasks are the blocked quality gates, which are not retried.
<!-- BEGIN:03_task_vs_attempt_success__by_task -->
| task_name | tasks | tasks_successful | task_success_rate | attempts | attempts_successful | attempt_success_rate | tasks_retried |
|---|---|---|---|---|---|---|---|
| ingest | 1343 | 1340 | 0.997766 | 1383 | 1340 | 0.968908 | 37 |
| publish | 1318 | 1318 | 1.000000 | 1349 | 1318 | 0.977020 | 31 |
| quality_gate | 1331 | 1318 | 0.990233 | 1337 | 1318 | 0.985789 | 3 |
| transform | 1340 | 1331 | 0.993284 | 1393 | 1331 | 0.955492 | 44 |
<!-- END:03_task_vs_attempt_success__by_task -->
<!-- BEGIN:03_task_vs_attempt_success__retry_depth -->
| attempts | tasks | ended_success | ended_failed |
|---|---|---|---|
| 1 | 5217 | 5207 | 10 |
| 2 | 100 | 100 | 0 |
| 3 | 15 | 0 | 15 |
<!-- END:03_task_vs_attempt_success__retry_depth -->
<!-- BEGIN:03_task_vs_attempt_success__run_level -->
| status | runs | attempts | attempts_successful | attempt_success_rate |
|---|---|---|---|---|
| failed | 25 | 90 | 35 | 0.388889 |
| success | 1318 | 5372 | 5272 | 0.981385 |
<!-- END:03_task_vs_attempt_success__run_level -->

## 4. Freshness against ingestion age, and the silent source (`04_freshness_vs_ingestion_age.sql`)
**Question:** which sources are fresh, which are merely running, and what did the gate see? **Scope:** ingestion age is complete world (recomputed from the checkpoints); freshness is **recorded** (the latest accepted event needs every raw row; the generator's recorded instants are the input and the seconds are recomputed from them).
<!-- BEGIN:04_freshness_vs_ingestion_age__ingestion_age -->
| source_id | last_successful_ingestion_at | ingestion_age_seconds | ingestion_age_minutes | checkpoint_version | committed_batches |
|---|---|---|---|---|---|
| src-inventory | 2026-10-04T05:12:06Z | 67674 | 1127.9000 | 61 | 61 |
| src-orders | 2026-10-04T20:08:33Z | 13887 | 231.4500 | 335 | 335 |
| src-payments | 2026-10-04T22:09:22Z | 6638 | 110.6333 | 336 | 336 |
| src-refunds | 2026-10-04T19:10:37Z | 17363 | 289.3833 | 228 | 228 |
| src-shipments | 2026-10-04T21:14:29Z | 9931 | 165.5167 | 226 | 226 |
| src-web-events | 2026-10-04T18:14:36Z | 20724 | 345.4000 | 116 | 116 |
<!-- END:04_freshness_vs_ingestion_age__ingestion_age -->
<!-- BEGIN:04_freshness_vs_ingestion_age__freshness_vs_age -->
| source_id | latest_accepted_event_at | freshness_seconds | freshness_minutes | recorded_freshness_seconds | ingestion_age_seconds | recorded_ingestion_age_seconds | gap_seconds | freshness_target_seconds | over_target | cadence_seconds | silent |
|---|---|---|---|---|---|---|---|---|---|---|---|
| src-inventory | 2026-10-04T01:59:57Z | 79203 | 1320.0500 | 79203 | 67674 | 67674 | 11529 | 259200 | false | 86400 | false |
| src-orders | 2026-10-04T19:58:06Z | 14514 | 241.9000 | 14514 | 13887 | 13887 | 627 | 19800 | false | 14400 | false |
| src-payments | 2026-10-04T21:50:34Z | 7766 | 129.4333 | 7766 | 6638 | 6638 | 1128 | 21600 | false | 14400 | false |
| src-refunds | 2026-10-01T23:07:02Z | 262378 | 4372.9667 | 262378 | 17363 | 17363 | 245015 | 604800 | false | 21600 | true |
| src-shipments | 2026-10-04T20:43:31Z | 11789 | 196.4833 | 11789 | 9931 | 9931 | 1858 | 259200 | false | 21600 | false |
| src-web-events | 2026-10-04T18:03:22Z | 21398 | 356.6333 | 21398 | 20724 | 20724 | 674 | 216000 | false | 43200 | false |
<!-- END:04_freshness_vs_ingestion_age__freshness_vs_age -->

**Reading.** Five sources are fresh: their freshness is within a few hours of their ingestion age and under their declared target. `src-refunds` is **silent while its jobs are green**: its freshness is 262,378 s (4,372.9667 minutes, 3 days 52 minutes) against an ingestion age of 17,363 s (289.3833 minutes), a gap of 245,015 s; it is above two declared cadences (21,600 s each) but below its declared 7-day target (604,800 s), so the critical freshness check passed. What the pipeline did meanwhile (DR-01):
<!-- BEGIN:04_freshness_vs_ingestion_age__silent_source -->
| source_id | silent_since | runs_since | runs_succeeded | runs_allowed_by_the_gate | freshness_checks_passed | committed_batches_since | batches_with_no_accepted_record | accepted_since | duplicates_since |
|---|---|---|---|---|---|---|---|---|---|
| src-refunds | 2026-10-02T00:00:00Z | 72 | 72 | 72 | 72 | 12 | 11 | 16 | 156 |
<!-- END:04_freshness_vs_ingestion_age__silent_source -->

Since 2026-10-02T00:00:00Z all 72 hourly runs succeeded, the gate allowed all 72 and the freshness check passed in all 72; 12 batches committed, 11 with no accepted record (16 records accepted in all, 156 duplicates): the source keeps answering with the same page. The partitions it was expected to fill (the generator records completeness 0.000000 on each):
<!-- BEGIN:04_freshness_vs_ingestion_age__silent_partitions -->
| source_id | partition | expected_records |
|---|---|---|
| src-refunds | 2026-10-02 | 76 |
| src-refunds | 2026-10-03 | 63 |
| src-refunds | 2026-10-04 | 53 |
<!-- END:04_freshness_vs_ingestion_age__silent_partitions -->

Completeness over all 56 partitions hides the stale tail (`src-refunds` is the lowest source at 0.945541, and its last three days are empty):
<!-- BEGIN:04_freshness_vs_ingestion_age__completeness -->
| source_id | partitions | expected_records | accepted_records | completeness |
|---|---|---|---|---|
| src-inventory | 56 | 1645 | 1630 | 0.990881 |
| src-orders | 56 | 16176 | 16066 | 0.993200 |
| src-payments | 56 | 10207 | 10125 | 0.991966 |
| src-refunds | 56 | 4003 | 3785 | 0.945541 |
| src-shipments | 56 | 4004 | 3985 | 0.995255 |
| src-web-events | 56 | 1678 | 1657 | 0.987485 |
<!-- END:04_freshness_vs_ingestion_age__completeness -->

## 5. The publication pointer and the runs that never moved it (`05_publication_pointer_and_blocked_runs.sql`)
**Question:** when a run fails, what do readers of the published dataset see? **Scope:** complete world.
<!-- BEGIN:05_publication_pointer_and_blocked_runs__summary -->
| runs | publications | runs_that_moved_the_pointer | runs_that_left_it | pointer | pointer_run | latest_publication | publications_of_failed_or_blocked_runs | first_published_at | last_published_at |
|---|---|---|---|---|---|---|---|---|---|
| 1343 | 1318 | 1318 | 25 | pub-1343 | run-1343 | pub-1343 | 0 | 2026-08-10T01:30:34Z | 2026-10-04T23:34:14Z |
<!-- END:05_publication_pointer_and_blocked_runs__summary -->

**Reading.** 1,318 runs moved the pointer, 25 left it; every publication belongs to a successful run with an allowed gate (0 publications of a failed or blocked run); the pointer rests on `pub-1343`. The designated blocked run of P08-TEST-07 (DR-02): `run-1187`, the second run in time order to fail `relationships_intact` (1 of 206 rows), published nothing, left the pointer on `pub-1186`, opened `inc-022`, and was recovered by `run-1188`:
<!-- BEGIN:05_publication_pointer_and_blocked_runs__designed_blocked_run -->
| run_id | failure_kind | relationships_eligible | relationships_failed | gate_decision | pointer_before | pointer_after | publication_exists | incident_id | recovery_run_id | detected_at |
|---|---|---|---|---|---|---|---|---|---|---|
| run-1187 | relationships | 206 | 1 | blocked | pub-1186 | pub-1186 | false | inc-022 | run-1188 | 2026-09-28T11:24:42Z |
<!-- END:05_publication_pointer_and_blocked_runs__designed_blocked_run -->

All 25 runs that never moved the pointer (the pointer after equals the pointer before in every row):
<!-- BEGIN:05_publication_pointer_and_blocked_runs__unmoved_runs -->
| run_id | started_at | stage | failure_kind | failed_critical_check | pointer_before | pointer_after | pointer_unchanged | publication_exists | incident_id |
|---|---|---|---|---|---|---|---|---|---|
| run-0179 | 2026-08-17T11:15:00Z | failed_before_gate | ingest |  | pub-0178 | pub-0178 | true | false | inc-001 |
| run-0185 | 2026-08-17T17:15:00Z | failed_before_gate | transform |  | pub-0184 | pub-0184 | true | false | inc-002 |
| run-0206 | 2026-08-18T14:15:00Z | failed_before_gate | gate_infra |  | pub-0205 | pub-0205 | true | false | inc-003 |
| run-0225 | 2026-08-19T09:15:00Z | blocked_at_gate | freshness | freshness_within_target | pub-0224 | pub-0224 | true | false | inc-004 |
| run-0250 | 2026-08-20T10:15:00Z | failed_before_gate | transform |  | pub-0249 | pub-0249 | true | false | inc-005 |
| run-0302 | 2026-08-22T14:15:00Z | blocked_at_gate | freshness | freshness_within_target | pub-0301 | pub-0301 | true | false | inc-006 |
| run-0346 | 2026-08-24T10:15:00Z | failed_before_gate | transform |  | pub-0345 | pub-0345 | true | false | inc-007 |
| run-0438 | 2026-08-28T06:15:00Z | failed_before_gate | ingest |  | pub-0437 | pub-0437 | true | false | inc-008 |
| run-0510 | 2026-08-31T06:15:00Z | failed_before_gate | ingest |  | pub-0509 | pub-0509 | true | false | inc-009 |
| run-0520 | 2026-08-31T16:15:00Z | blocked_at_gate | freshness | freshness_within_target | pub-0519 | pub-0519 | true | false | inc-010 |
| run-0543 | 2026-09-01T15:15:00Z | failed_before_gate | transform |  | pub-0542 | pub-0542 | true | false | inc-011 |
| run-0573 | 2026-09-02T21:15:00Z | failed_before_gate | gate_infra |  | pub-0572 | pub-0572 | true | false | inc-012 |
| run-0655 | 2026-09-06T07:15:00Z | failed_before_gate | gate_infra |  | pub-0654 | pub-0654 | true | false | inc-013 |
| run-0687 | 2026-09-07T15:15:00Z | failed_before_gate | transform |  | pub-0686 | pub-0686 | true | false | inc-014 |
| run-0731 | 2026-09-09T11:15:00Z | blocked_at_gate | residual | reconciliation_residual_zero | pub-0730 | pub-0730 | true | false | inc-015 |
| run-0780 | 2026-09-11T12:15:00Z | blocked_at_gate | relationships | relationships_intact | pub-0779 | pub-0779 | true | false | inc-016 |
| run-0832 | 2026-09-13T16:15:00Z | blocked_at_gate | freshness | freshness_within_target | pub-0831 | pub-0831 | true | false | inc-017 |
| run-0997 | 2026-09-20T13:15:00Z | failed_before_gate | transform |  | pub-0996 | pub-0996 | true | false | inc-018 |
| run-1139 | 2026-09-26T11:15:00Z | failed_before_gate | transform |  | pub-1138 | pub-1138 | true | false | inc-019 |
| run-1146 | 2026-09-26T18:15:00Z | blocked_at_gate | freshness | freshness_within_target | pub-1145 | pub-1145 | true | false | inc-020 |
| run-1159 | 2026-09-27T07:15:00Z | failed_before_gate | transform |  | pub-1158 | pub-1158 | true | false | inc-021 |
| run-1187 | 2026-09-28T11:15:00Z | blocked_at_gate | relationships | relationships_intact | pub-1186 | pub-1186 | true | false | inc-022 |
| run-1206 | 2026-09-29T06:15:00Z | blocked_at_gate | relationships | relationships_intact | pub-1205 | pub-1205 | true | false | inc-023 |
| run-1232 | 2026-09-30T08:15:00Z | blocked_at_gate | relationships | relationships_intact | pub-1231 | pub-1231 | true | false | inc-024 |
| run-1244 | 2026-09-30T20:15:00Z | failed_before_gate | transform |  | pub-1243 | pub-1243 | true | false | inc-025 |
<!-- END:05_publication_pointer_and_blocked_runs__unmoved_runs -->

How long a failure leaves readers on the older snapshot (seconds from the pointer's publication to the next publication that moved it):
<!-- BEGIN:05_publication_pointer_and_blocked_runs__pointer_staleness -->
| unmoved_runs | min_seconds | max_seconds | mean_minutes |
|---|---|---|---|
| 25 | 6798 | 7595 | 120.1453 |
<!-- END:05_publication_pointer_and_blocked_runs__pointer_staleness -->

## 6. Incidents and verified recovery minutes (`06_incidents_and_verified_recovery.sql`)
**Question:** how long are readers on an older snapshot after a failure, and is every closure honest? **Scope:** complete world; the one unexplained residual is recorded (DR-05) and its arithmetic recomputed.
<!-- BEGIN:06_incidents_and_verified_recovery__summary -->
| incidents | open | closed | verified | closures_consistent | mean_recovery_minutes | min_recovery_minutes | max_recovery_minutes |
|---|---|---|---|---|---|---|---|
| 25 | 0 | 25 | 25 | 25 | 60.6827 | 50.7500 | 72.4000 |
<!-- END:06_incidents_and_verified_recovery__summary -->

**Reading.** 25 incidents, all closed, all on a **verified** recovery (the first later run that succeeded, was allowed, published and passed the reconciliation check; recovery time = that publication minus the detection, never a restart): mean 60.6827 minutes, from 50.7500 to 72.4000. The closure instant equals the verified instant in every case. By what failed:
<!-- BEGIN:06_incidents_and_verified_recovery__by_failure_kind -->
| failure_kind | stage | incidents | mean_recovery_minutes | min_recovery_minutes | max_recovery_minutes |
|---|---|---|---|---|---|
| freshness | blocked_at_gate | 5 | 66.7800 | 63.4833 | 72.4000 |
| gate_infra | failed_before_gate | 3 | 56.5278 | 55.6833 | 57.4500 |
| ingest | failed_before_gate | 3 | 65.2778 | 62.6000 | 67.4333 |
| relationships | blocked_at_gate | 4 | 64.1000 | 60.9500 | 67.8833 |
| residual | blocked_at_gate | 1 | 63.1000 | 63.1000 | 63.1000 |
| transform | failed_before_gate | 9 | 55.3611 | 50.7500 | 61.2167 |
<!-- END:06_incidents_and_verified_recovery__by_failure_kind -->

The 25 incidents one by one:
<!-- BEGIN:06_incidents_and_verified_recovery__incidents -->
| incident_id | run_id | failure_kind | severity | status | detected_at | recovery_run_id | first_verified_run | recovery_is_first_verified | verified_at | closed_at_is_verified_instant | recovery_seconds | recovery_minutes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| inc-001 | run-0179 | ingest | medium | closed | 2026-08-17T11:22:08Z | run-0180 | run-0180 | true | 2026-08-17T12:29:34Z | true | 4046 | 67.4333 |
| inc-002 | run-0185 | transform | high | closed | 2026-08-17T17:30:41Z | run-0186 | run-0186 | true | 2026-08-17T18:30:02Z | true | 3561 | 59.3500 |
| inc-003 | run-0206 | gate_infra | medium | closed | 2026-08-18T14:32:45Z | run-0207 | run-0207 | true | 2026-08-18T15:29:12Z | true | 3387 | 56.4500 |
| inc-004 | run-0225 | freshness | medium | closed | 2026-08-19T09:24:26Z | run-0226 | run-0226 | true | 2026-08-19T10:27:55Z | true | 3809 | 63.4833 |
| inc-005 | run-0250 | transform | high | closed | 2026-08-20T10:35:18Z | run-0251 | run-0251 | true | 2026-08-20T11:31:00Z | true | 3342 | 55.7000 |
| inc-006 | run-0302 | freshness | medium | closed | 2026-08-22T14:24:07Z | run-0303 | run-0303 | true | 2026-08-22T15:30:43Z | true | 3996 | 66.6000 |
| inc-007 | run-0346 | transform | high | closed | 2026-08-24T10:33:25Z | run-0347 | run-0347 | true | 2026-08-24T11:34:38Z | true | 3673 | 61.2167 |
| inc-008 | run-0438 | ingest | medium | closed | 2026-08-28T06:24:11Z | run-0439 | run-0439 | true | 2026-08-28T07:29:59Z | true | 3948 | 65.8000 |
| inc-009 | run-0510 | ingest | medium | closed | 2026-08-31T06:24:41Z | run-0511 | run-0511 | true | 2026-08-31T07:27:17Z | true | 3756 | 62.6000 |
| inc-010 | run-0520 | freshness | medium | closed | 2026-08-31T16:24:45Z | run-0521 | run-0521 | true | 2026-08-31T17:30:13Z | true | 3928 | 65.4667 |
| inc-011 | run-0543 | transform | high | closed | 2026-09-01T15:32:57Z | run-0544 | run-0544 | true | 2026-09-01T16:30:19Z | true | 3442 | 57.3667 |
| inc-012 | run-0573 | gate_infra | medium | closed | 2026-09-02T21:30:24Z | run-0574 | run-0574 | true | 2026-09-02T22:27:51Z | true | 3447 | 57.4500 |
| inc-013 | run-0655 | gate_infra | medium | closed | 2026-09-06T07:31:21Z | run-0656 | run-0656 | true | 2026-09-06T08:27:02Z | true | 3341 | 55.6833 |
| inc-014 | run-0687 | transform | high | closed | 2026-09-07T15:31:13Z | run-0688 | run-0688 | true | 2026-09-07T16:30:11Z | true | 3538 | 58.9667 |
| inc-015 | run-0731 | residual | critical | closed | 2026-09-09T11:24:11Z | run-0732 | run-0732 | true | 2026-09-09T12:27:17Z | true | 3786 | 63.1000 |
| inc-016 | run-0780 | relationships | high | closed | 2026-09-11T12:23:52Z | run-0781 | run-0781 | true | 2026-09-11T13:29:16Z | true | 3924 | 65.4000 |
| inc-017 | run-0832 | freshness | medium | closed | 2026-09-13T16:24:26Z | run-0833 | run-0833 | true | 2026-09-13T17:30:23Z | true | 3957 | 65.9500 |
| inc-018 | run-0997 | transform | high | closed | 2026-09-20T13:36:05Z | run-0998 | run-0998 | true | 2026-09-20T14:26:56Z | true | 3051 | 50.8500 |
| inc-019 | run-1139 | transform | high | closed | 2026-09-26T11:35:25Z | run-1140 | run-1140 | true | 2026-09-26T12:28:31Z | true | 3186 | 53.1000 |
| inc-020 | run-1146 | freshness | medium | closed | 2026-09-26T18:23:47Z | run-1147 | run-1147 | true | 2026-09-26T19:36:11Z | true | 4344 | 72.4000 |
| inc-021 | run-1159 | transform | high | closed | 2026-09-27T07:37:05Z | run-1160 | run-1160 | true | 2026-09-27T08:28:02Z | true | 3057 | 50.9500 |
| inc-022 | run-1187 | relationships | high | closed | 2026-09-28T11:24:42Z | run-1188 | run-1188 | true | 2026-09-28T12:32:35Z | true | 4073 | 67.8833 |
| inc-023 | run-1206 | relationships | high | closed | 2026-09-29T06:25:29Z | run-1207 | run-1207 | true | 2026-09-29T07:26:26Z | true | 3657 | 60.9500 |
| inc-024 | run-1232 | relationships | high | closed | 2026-09-30T08:24:29Z | run-1233 | run-1233 | true | 2026-09-30T09:26:39Z | true | 3730 | 62.1667 |
| inc-025 | run-1244 | transform | high | closed | 2026-09-30T20:36:11Z | run-1245 | run-1245 | true | 2026-09-30T21:26:56Z | true | 3045 | 50.7500 |
<!-- END:06_incidents_and_verified_recovery__incidents -->

Every publication reconciles to 0.00 but one candidate: `run-0731` (2026-09-09) read the staged rows of a crashed batch, its candidate total was off by their amount, the gate blocked it and `inc-015` opened. Source total - stored candidate total - explained exclusions = -141.46; **no cause is recorded** (no quarantine, duplicate or delete accounts for it):
<!-- BEGIN:06_incidents_and_verified_recovery__residual_candidate -->
| run_id | day | source_total | exclusions_total | stored_candidate_total | recorded_published_total | residual | recorded_residual | stage | failure_kind | incident_id | publications_of_the_run |
|---|---|---|---|---|---|---|---|---|---|---|---|
| run-0731 | 2026-09-09 | 23694.91 | 1137.66 | 22698.71 | 22698.71 | -141.46 | -141.46 | blocked_at_gate | residual | inc-015 | 0 |
<!-- END:06_incidents_and_verified_recovery__residual_candidate -->

## 7. Backfill coverage and the refused overlaps (`07_backfill_coverage_and_refused_overlaps.sql`)
**Question:** of the history we asked to be re-ingested, how much was verified, and what did the system refuse? **Scope:** complete world.
<!-- BEGIN:07_backfill_coverage_and_refused_overlaps__coverage_summary -->
| accepted_requests | requested_partitions | verified_partitions | coverage | refused_requests | refused_partitions | requests_complete | requests_partial | backfill_runs |
|---|---|---|---|---|---|---|---|---|
| 13 | 15 | 11 | 0.733333 | 2 | 4 | 9 | 4 | 13 |
<!-- END:07_backfill_coverage_and_refused_overlaps__coverage_summary -->

**Reading.** Eleven of the fifteen partitions of the thirteen accepted requests were verified (0.733333); two further requests for four partitions were refused for overlap and sit beside the coverage, never inside it (D-09 R8-11). Each refusal arrived while the request it overlapped was still requested or running (D-09 R8-12; a settled request would not have blocked it):
<!-- BEGIN:07_backfill_coverage_and_refused_overlaps__refused_overlaps -->
| refused_request | source_id | start_day | end_day | overlapped_request | overlapped_start_day | overlapped_end_day | shared_partitions | seconds_before_the_overlapped_request_settled | overlapped_final_status | reason_code |
|---|---|---|---|---|---|---|---|---|---|---|
| bf-006 | src-inventory | 2026-08-22 | 2026-08-24 | bf-004 | 2026-08-22 | 2026-08-23 | 1 | 3643 | partial | BACKFILL_OVERLAP |
| bf-012 | src-web-events | 2026-08-26 | 2026-08-28 | bf-010 | 2026-08-26 | 2026-08-27 | 1 | 2718 | complete | BACKFILL_OVERLAP |
<!-- END:07_backfill_coverage_and_refused_overlaps__refused_overlaps -->
<!-- BEGIN:07_backfill_coverage_and_refused_overlaps__requests -->
| backfill_id | source_id | outcome | start_day | end_day | requested_partitions | verified_partitions | coverage | status | requested_at | settled_at | run_id |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bf-001 | src-shipments | accepted | 2026-08-15 | 2026-08-16 | 1 | 1 | 1.000000 | complete | 2026-08-19T09:59:05Z | 2026-08-19T11:29:53Z | run-0227 |
| bf-002 | src-web-events | accepted | 2026-08-13 | 2026-08-14 | 1 | 0 | 0.000000 | partial | 2026-08-22T04:38:39Z | 2026-08-22T06:30:00Z | run-0294 |
| bf-003 | src-inventory | accepted | 2026-08-20 | 2026-08-21 | 1 | 1 | 1.000000 | complete | 2026-08-24T23:38:41Z | 2026-08-25T01:26:32Z | run-0361 |
| bf-004 | src-inventory | accepted | 2026-08-22 | 2026-08-23 | 1 | 0 | 0.000000 | partial | 2026-08-27T18:18:25Z | 2026-08-27T20:26:17Z | run-0428 |
| bf-005 | src-refunds | accepted | 2026-08-24 | 2026-08-26 | 2 | 2 | 1.000000 | complete | 2026-08-30T09:32:45Z | 2026-08-30T11:27:13Z | run-0491 |
| bf-006 | src-inventory | refused | 2026-08-22 | 2026-08-24 | 2 | 0 |  | requested | 2026-08-27T19:25:34Z |  |  |
| bf-007 | src-inventory | accepted | 2026-08-28 | 2026-08-29 | 1 | 1 | 1.000000 | complete | 2026-09-04T21:35:34Z | 2026-09-04T23:26:45Z | run-0623 |
| bf-008 | src-inventory | accepted | 2026-09-03 | 2026-09-04 | 1 | 1 | 1.000000 | complete | 2026-09-07T16:11:26Z | 2026-09-07T18:30:41Z | run-0690 |
| bf-009 | src-web-events | accepted | 2026-08-21 | 2026-08-22 | 1 | 1 | 1.000000 | complete | 2026-09-10T10:10:23Z | 2026-09-10T12:27:20Z | run-0756 |
| bf-010 | src-web-events | accepted | 2026-08-26 | 2026-08-27 | 1 | 1 | 1.000000 | complete | 2026-09-13T05:33:23Z | 2026-09-13T07:26:02Z | run-0823 |
| bf-011 | src-web-events | accepted | 2026-09-07 | 2026-09-08 | 1 | 0 | 0.000000 | partial | 2026-09-16T00:37:17Z | 2026-09-16T02:26:31Z | run-0890 |
| bf-012 | src-web-events | refused | 2026-08-26 | 2026-08-28 | 2 | 0 |  | requested | 2026-09-13T06:40:44Z |  |  |
| bf-013 | src-inventory | accepted | 2026-09-17 | 2026-09-18 | 1 | 0 | 0.000000 | partial | 2026-09-21T12:22:52Z | 2026-09-21T14:26:43Z | run-1022 |
| bf-014 | src-shipments | accepted | 2026-09-10 | 2026-09-11 | 1 | 1 | 1.000000 | complete | 2026-09-24T05:30:36Z | 2026-09-24T07:30:10Z | run-1087 |
| bf-015 | src-refunds | accepted | 2026-09-22 | 2026-09-24 | 2 | 2 | 1.000000 | complete | 2026-09-26T23:02:08Z | 2026-09-27T01:30:22Z | run-1153 |
<!-- END:07_backfill_coverage_and_refused_overlaps__requests -->
<!-- BEGIN:07_backfill_coverage_and_refused_overlaps__by_source -->
| source_id | accepted_requests | requested_partitions | verified_partitions | coverage | refused_requests |
|---|---|---|---|---|---|
| src-inventory | 5 | 5 | 3 | 0.600000 | 1 |
| src-refunds | 2 | 4 | 4 | 1.000000 | 0 |
| src-shipments | 2 | 2 | 2 | 1.000000 | 0 |
| src-web-events | 4 | 4 | 2 | 0.500000 | 1 |
<!-- END:07_backfill_coverage_and_refused_overlaps__by_source -->
<!-- BEGIN:07_backfill_coverage_and_refused_overlaps__unverified_partitions -->
| backfill_id | source_id | partition | status |
|---|---|---|---|
| bf-002 | src-web-events | 2026-08-13 | partial |
| bf-004 | src-inventory | 2026-08-22 | partial |
| bf-011 | src-web-events | 2026-09-07 | partial |
| bf-013 | src-inventory | 2026-09-17 | partial |
<!-- END:07_backfill_coverage_and_refused_overlaps__unverified_partitions -->

The accepted requests never overlap or touch one another:
<!-- BEGIN:07_backfill_coverage_and_refused_overlaps__accepted_pairs -->
| overlapping_pairs | touching_pairs | pairs_of_one_source |
|---|---|---|
| 0 | 0 | 18 |
<!-- END:07_backfill_coverage_and_refused_overlaps__accepted_pairs -->

## 8. The fetch log: retry-after compliance, refetch against loop (`08_fetch_log_retry_after.sql`)
**Question:** does the fetcher honour the source, and can a loop be told from a harmless re-poll? **Scope:** complete world (1,361 rows).
<!-- BEGIN:08_fetch_log_retry_after__statuses -->
| status | fetches | sessions | sources | with_a_batch |
|---|---|---|---|---|
| cursor_loop | 1 | 1 | 1 | 0 |
| ok | 1263 | 1263 | 6 | 1263 |
| rate_limited | 49 | 33 | 1 | 0 |
| refetch | 48 | 48 | 6 | 48 |
<!-- END:08_fetch_log_retry_after__statuses -->
<!-- BEGIN:08_fetch_log_retry_after__retry_summary -->
| rate_limited_responses | retries | retries_honouring_retry_after | retries_too_soon | min_slack_seconds | max_slack_seconds | sessions_rate_limited | sources_rate_limited | source_id | retries_rate_limited_again |
|---|---|---|---|---|---|---|---|---|---|
| 49 | 49 | 49 | 0 | 0 | 25 | 33 | 1 | src-shipments | 16 |
<!-- END:08_fetch_log_retry_after__retry_summary -->

**Reading.** Only `src-shipments` is rate limited: 49 responses over 33 sessions, 49 retries, every one at least as late as its hint (0 too soon; slack 0 to 25 s); 16 retries were rate limited again. By hint:
<!-- BEGIN:08_fetch_log_retry_after__retry_by_hint -->
| retry_after_seconds | responses | min_slack_seconds | max_slack_seconds | honoured |
|---|---|---|---|---|
| 30 | 16 | 0 | 22 | 16 |
| 60 | 9 | 1 | 23 | 9 |
| 90 | 13 | 1 | 25 | 13 |
| 120 | 11 | 0 | 23 | 11 |
<!-- END:08_fetch_log_retry_after__retry_by_hint -->

A **refetch** is a cursor another session already served, or a re-poll of the last committed cursor by a new session (the page points at itself because the source has nothing new); a **loop** repeats a cursor inside one session. All 48 refetch rows meet the refetch condition and none repeats inside its session; the one loop row does (R8-06):
<!-- BEGIN:08_fetch_log_retry_after__refetch_vs_loop -->
| status | batch_kind | fetches | pointing_at_themselves |
|---|---|---|---|
| cursor_loop | no batch | 1 | 0 |
| refetch | backfill | 15 | 15 |
| refetch | live | 24 | 11 |
| refetch | replay | 8 | 0 |
| refetch | schema_refetch | 1 | 0 |
<!-- END:08_fetch_log_retry_after__refetch_vs_loop -->
<!-- BEGIN:08_fetch_log_retry_after__refetch_check -->
| status | fetches | cursor_served_before_by_another_session | pointing_at_themselves | refetch_conditions_met | repeats_inside_its_session |
|---|---|---|---|---|---|
| cursor_loop | 1 | 0 | 0 | 0 | 1 |
| ok | 1263 | 0 | 0 | 0 | 0 |
| rate_limited | 49 | 0 | 0 | 0 | 0 |
| refetch | 48 | 34 | 26 | 48 | 0 |
<!-- END:08_fetch_log_retry_after__refetch_check -->
<!-- BEGIN:08_fetch_log_retry_after__cursor_loop -->
| loop_fetch | source_id | session_id | looping_cursor | points_back_to | first_page_fetch | first_page_cursor | first_page_next | first_page_at | loop_detected_at | no_batch_created | rows_in_the_session |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 577 | src-web-events | src-web-events:47 | off-000713 | off-000693 | 576 | off-000693 | off-000713 | 2026-09-02T18:21:04Z | 2026-09-02T18:21:49Z | true | 2 |
<!-- END:08_fetch_log_retry_after__cursor_loop -->

## 9. The golden known answer (`09_golden_known_answer.sql`, on the golden database)
**Question:** does the SQL reproduce the hand-worked answer of `tests/fixtures/golden/CALCULATION.md`? **Scope:** the 32-row fixture; every figure is equal to `expected.json`, the Python domain and `data/sql/reference_metrics.sql` (section 11, family A).

Ten rows arrive: 8 valid unique, 1 duplicate of a valid key, 1 negative quantity (P08-GOLD-01):
<!-- BEGIN:09_golden_known_answer__batches -->
| batch_id | source_id | status | written_rows | received | accepted_unique | duplicate | quarantined | rejection_rate | duplicate_rate |
|---|---|---|---|---|---|---|---|---|---|
| b-001 | src-orders | committed | 10 | 10 | 8 | 1 | 1 | 0.100000 | 0.100000 |
| b-002 | src-orders | committed | 10 | 10 | 0 | 9 | 1 | 0.100000 | 0.900000 |
| b-003 | src-orders | aborted | 10 | 0 | 0 | 0 | 0 |  |  |
| b-101 | src-refunds | committed | 2 | 2 | 1 | 0 | 1 | 0.500000 | 0.000000 |
<!-- END:09_golden_known_answer__batches -->
<!-- BEGIN:09_golden_known_answer__sources -->
| source_id | committed_batches | received | accepted_unique | duplicate | quarantined | quarantined_distinct_keys | rejection_rate | duplicate_rate | checkpoint_version |
|---|---|---|---|---|---|---|---|---|---|
| src-orders | 2 | 20 | 8 | 10 | 2 | 1 | 0.100000 | 0.500000 | 2 |
| src-refunds | 1 | 2 | 1 | 0 | 1 | 1 | 0.500000 | 0.000000 | 1 |
<!-- END:09_golden_known_answer__sources -->
<!-- BEGIN:09_golden_known_answer__replay_and_crash -->
| source_id | accepted_keys | distinct_accepted_keys | accepted_by_the_replay | rows_written_by_the_crashed_batch | checkpoints_of_the_crashed_batch | new_keys_in_the_crashed_batch | checkpoint_version |
|---|---|---|---|---|---|---|---|
| src-orders | 8 | 8 | 0 | 10 | 0 | 0 | 2 |
<!-- END:09_golden_known_answer__replay_and_crash -->

Replaying the batch leaves 8; the crashed batch `b-003` wrote 10 rows and no checkpoint and the checkpoint stays at version 2. **Every key of the crashed batch is already accepted or already quarantined, so this fixture alone cannot make a ninth record** (the crash case is vacuous here; the backend test crashes a batch with a new key). Freshness 52,200 s against an ingestion age of 42,900 s; completeness 8 of 9:
<!-- BEGIN:09_golden_known_answer__freshness -->
| source_id | latest_accepted_event_at | freshness_seconds | last_successful_ingestion_at | ingestion_age_seconds |
|---|---|---|---|---|
| src-orders | 2026-10-04T09:30:00Z | 52200 | 2026-10-04T12:05:00Z | 42900 |
| src-refunds | 2026-10-04T09:10:00Z | 53400 | 2026-10-04T11:05:00Z | 46500 |
<!-- END:09_golden_known_answer__freshness -->
<!-- BEGIN:09_golden_known_answer__completeness -->
| source_id | partition | expected_records | accepted_records | completeness |
|---|---|---|---|---|
| src-orders | 2026-10-04 | 9 | 8 | 0.888889 |
| src-refunds | 2026-10-04 | 1 | 1 | 1.000000 |
<!-- END:09_golden_known_answer__completeness -->
<!-- BEGIN:09_golden_known_answer__runs -->
| run_id | status | duration_seconds | tasks_terminal | tasks_successful | task_success_rate | attempts | attempts_successful | attempt_success_rate |
|---|---|---|---|---|---|---|---|---|
| run-001 | success | 1200 | 4 | 4 | 1.000000 | 5 | 4 | 0.800000 |
| run-002 | failed | 600 | 3 | 2 | 0.666667 | 3 | 2 | 0.666667 |
| run-003 | success | 900 | 4 | 4 | 1.000000 | 4 | 4 | 1.000000 |
<!-- END:09_golden_known_answer__runs -->
<!-- BEGIN:09_golden_known_answer__runs_overall -->
| tasks_terminal | tasks_successful | task_success_rate | attempts | attempts_successful | attempt_success_rate |
|---|---|---|---|---|---|
| 11 | 10 | 0.909091 | 12 | 10 | 0.833333 |
<!-- END:09_golden_known_answer__runs_overall -->
<!-- BEGIN:09_golden_known_answer__gate_pointer -->
| run_id | gate_decision | critical_failures | noncritical_failures | publication_exists | pointer_after |
|---|---|---|---|---|---|
| run-001 | allowed | 0 | 1 | true | pub-001 |
| run-002 | blocked | 1 | 1 | false | pub-001 |
| run-003 | allowed | 0 | 1 | true | pub-003 |
<!-- END:09_golden_known_answer__gate_pointer -->
<!-- BEGIN:09_golden_known_answer__publications -->
| publication_id | published_at | watermark | included_batches | published_records | latest_included_event_at | lag_seconds |
|---|---|---|---|---|---|---|
| pub-001 | 2026-10-04T10:30:00Z | 2026-10-04T10:00:00Z | b-001 | 8 | 2026-10-04T09:30:00Z | 3600 |
| pub-003 | 2026-10-04T20:15:00Z | 2026-10-04T11:00:00Z | b-001,b-002,b-101 | 9 | 2026-10-04T09:30:00Z | 38700 |
<!-- END:09_golden_known_answer__publications -->
<!-- BEGIN:09_golden_known_answer__late_event -->
| source_id | source_key | batch_id | event_at | arrival_at | behind_publication_id | watermark | included_in_publication_id |
|---|---|---|---|---|---|---|---|
| src-refunds | REF-2001 | b-101 | 2026-10-04T09:10:00Z | 2026-10-04T11:05:00Z | pub-001 | 2026-10-04T10:00:00Z | pub-003 |
<!-- END:09_golden_known_answer__late_event -->
<!-- BEGIN:09_golden_known_answer__reconciliation -->
| publication_id | source_total | published_total | quarantined | duplicates | residual |
|---|---|---|---|---|---|
| pub-001 | 289.94 | 289.97 | -30.00 | 29.97 | 0.00 |
| pub-003 | 599.88 | 301.97 | -52.00 | 349.91 | 0.00 |
<!-- END:09_golden_known_answer__reconciliation -->
<!-- BEGIN:09_golden_known_answer__recovery -->
| incident_id | run_id | detected_at | recovery_run_id | first_verified_run | recovery_is_first_verified | verified_at | closed_at_is_verified_instant | recovery_seconds | recovery_minutes |
|---|---|---|---|---|---|---|---|---|---|
| inc-001 | run-002 | 2026-10-04T12:20:00Z | run-003 | run-003 | true | 2026-10-04T20:15:00Z | true | 28500 | 475.0000 |
<!-- END:09_golden_known_answer__recovery -->
<!-- BEGIN:09_golden_known_answer__backfill_processing -->
| backfill_id | source_id | requested_partitions | verified_partitions | coverage | measured_batch | measured_seconds | accepted_records | records_per_second | cache_state |
|---|---|---|---|---|---|---|---|---|---|
| bf-001 | src-orders | 3 | 2 | 0.666667 | b-001 | 12 | 8 | 0.666667 | cold |
<!-- END:09_golden_known_answer__backfill_processing -->

## 10. The sample-scope reconciliation (`10_sample_scope_reconciliation.sql`)
**Question:** which figures may a reader take from the loaded database, which only from the generator's record, and how far apart are the two? **Scope:** all three, compared on purpose.
<!-- BEGIN:10_sample_scope_reconciliation__scope_total -->
| batches | sampled_batches | sampled_batches_with_rows | world_rows | sample_rows | sample_share | sample_rows_in_uncounted_batches |
|---|---|---|---|---|---|---|
| 1311 | 62 | 50 | 40191 | 2000 | 0.049762 | 122 |
<!-- END:10_sample_scope_reconciliation__scope_total -->
<!-- BEGIN:10_sample_scope_reconciliation__scope_rows -->
| source_id | batches | sampled_batches | sampled_batches_with_rows | world_rows | sample_rows | sample_share |
|---|---|---|---|---|---|---|
| src-inventory | 61 | 4 | 4 | 1723 | 86 | 0.049913 |
| src-orders | 338 | 16 | 16 | 16985 | 1054 | 0.062055 |
| src-payments | 338 | 12 | 12 | 10856 | 418 | 0.038504 |
| src-refunds | 231 | 14 | 6 | 4354 | 152 | 0.034910 |
| src-shipments | 227 | 8 | 7 | 4420 | 193 | 0.043665 |
| src-web-events | 116 | 8 | 5 | 1853 | 97 | 0.052348 |
<!-- END:10_sample_scope_reconciliation__scope_rows -->

**Reading.** The loaded database holds 2,000 of the world's 40,191 raw rows (0.049762) in 62 whole batches, 50 of which carry rows. The same 1,878 rows of the sampled committed batches, classified three ways:
<!-- BEGIN:10_sample_scope_reconciliation__rates_by_scope -->
| scope | received | accepted_unique | duplicate | quarantined | rejection_rate | duplicate_rate |
|---|---|---|---|---|---|---|
| complete world, 1,302 committed batches | 39901 | 37248 | 2101 | 429 | 0.010752 | 0.052655 |
| the sampled committed batches, classified with the full key history | 1878 | 1769 | 76 | 30 | 0.015974 | 0.040469 |
| the 2,000-row sample, classified from the loaded rows only | 1878 | 1822 | 23 | 32 | 0.017039 | 0.012247 |
<!-- END:10_sample_scope_reconciliation__rates_by_scope -->

The sample **overstates accepted records and understates duplicates**, because a key whose first copy sits in an unsampled batch looks new: the sample's duplicate rate is 0.012247, the same rows with the full key history 0.040469, the pipeline's 0.052655. By source:
<!-- BEGIN:10_sample_scope_reconciliation__classes_by_source -->
| source_id | received | world_accepted | world_duplicate | world_quarantined | world_deleted | sample_accepted | sample_duplicate | sample_quarantined | sample_deleted |
|---|---|---|---|---|---|---|---|---|---|
| src-inventory | 86 | 81 | 2 | 3 | 0 | 83 | 0 | 3 | 0 |
| src-orders | 983 | 948 | 23 | 10 | 2 | 967 | 4 | 11 | 1 |
| src-payments | 367 | 346 | 10 | 10 | 1 | 356 | 0 | 11 | 0 |
| src-refunds | 152 | 124 | 26 | 2 | 0 | 131 | 19 | 2 | 0 |
| src-shipments | 193 | 182 | 9 | 2 | 0 | 191 | 0 | 2 | 0 |
| src-web-events | 97 | 88 | 6 | 3 | 0 | 94 | 0 | 3 | 0 |
<!-- END:10_sample_scope_reconciliation__classes_by_source -->

The quarantine rows are published in full (446) but only 47 sit in sampled batches; no publication can have its content hash recomputed from the sample (the generator records the check as true for all 1,318); freshness over the sample is wrong for five of the six sources (only `src-refunds` coincides, because its last events are in sampled batches); one duplicate in the measured batch becomes an accepted record, so the observed processing rate is 39.253789 records per second in the world and 39.642441 over the sample:
<!-- BEGIN:10_sample_scope_reconciliation__quarantine_rows -->
| quarantine_rows | in_sampled_batches | in_unsampled_batches | unsampled_in_committed_batches | in_the_schema_quarantined_batch |
|---|---|---|---|---|
| 446 | 47 | 399 | 399 | 17 |
<!-- END:10_sample_scope_reconciliation__quarantine_rows -->
<!-- BEGIN:10_sample_scope_reconciliation__publications -->
| publications | verifiable_from_the_sample | partly_in_the_sample | none_in_the_sample |
|---|---|---|---|
| 1318 | 0 | 435 | 883 |
<!-- END:10_sample_scope_reconciliation__publications -->
<!-- BEGIN:10_sample_scope_reconciliation__freshness_on_the_sample -->
| source_id | sample_latest_accepted_event_at | sample_freshness_seconds | recorded_freshness_seconds |
|---|---|---|---|
| src-inventory | 2026-09-16T23:59:46Z | 1555214 | 79203 |
| src-orders | 2026-09-27T19:51:31Z | 619709 | 14514 |
| src-payments | 2026-09-24T05:57:01Z | 928979 | 7766 |
| src-refunds | 2026-10-01T23:07:02Z | 262378 | 262378 |
| src-shipments | 2026-10-02T08:43:47Z | 227773 | 11789 |
| src-web-events | 2026-09-27T23:58:39Z | 604881 | 21398 |
<!-- END:10_sample_scope_reconciliation__freshness_on_the_sample -->
<!-- BEGIN:10_sample_scope_reconciliation__processing_batch -->
| batch_id | measured_seconds | cache_state | received | world_accepted | sample_accepted | world_records_per_second | sample_records_per_second |
|---|---|---|---|---|---|---|---|
| b-1121 | 2.573 | cold | 102 | 101 | 102 | 39.253789 | 39.642441 |
<!-- END:10_sample_scope_reconciliation__processing_batch -->

## 11. Reconciliation (`data/sql/analysis/run_all.py`)
`run_all.py` creates two scratch databases (`artifacts08_run_snapshot`, `artifacts08_run_golden`; or uses `ARTIFACTS_DATABASE_URL` and `ARTIFACTS_GOLDEN_DATABASE_URL`, whose names must start with `artifacts08_`), loads the snapshot and the golden fixture through `data/migrate.py` and `data/seed.py`, runs the ten investigations and the BI queries, and prints one line per reconciliation row. It exits 0 only when every query ran and every row is equal. **Last run: `RESULT: OK (204 reconciliation rows, 204 equal; 64 result sets, 303 rows)`.** The families:
* **A (38 rows), golden:** `reference_metrics.sql`, the Python domain and `expected.json` agree on every metric key and on the whole expected shape; the SQL of investigation 09 equals the hand answer of `CALCULATION.md` (10 / 8 / 1 / 1; 52,200 s against 42,900 s; 8 of 9; 1.000000 against 0.800000; pub-001 / pub-001 / pub-003; 289.94 / 289.97 / -30.00 / 29.97 / 0.00; 475.0000 minutes; 2 of 3; 0.666667).
* **B (77 rows), the loaded snapshot:** row counts and the dataset hash against the manifest; the reference SQL against the domain over the sample on all eleven metric keys at the as-of and at 2026-09-14 (the **known gap** below); the complete-world investigations against the manifest's recorded statistics and the domain; the sample figures against the domain over the sample.
* **C (52 rows), independent side:** every one of the 51 result sets of investigations 01..08 and 10 equals `python_side.py` (plain Python from the raw JSON, no SQL, no domain code), cell by cell, plus one row that the two sides return the same 51 sets.
* **D (23 rows), designed relationships and defects:** DR-01, DR-02, DR-03, DR-05 (DR-04 is recorded and its arithmetic is checked), INJ-01, INJ-02, INJ-03, INJ-04, INJ-05, INJ-06, INJ-07, INJ-10, and the decisions R8-06, R8-07, R8-10, R8-11.
* **E (14 rows), BI package:** row counts and the measures recomputed from the CSV facts against the SQL, the domain and the manifest, and nothing withheld without a status.

**A known gap, reconciled instead of hidden.** `data/sql/reference_metrics.sql` does not model delete events (README "Not implemented", D-06). The sample holds ten rows whose payload carries an `op` other than upsert (one delete of an accepted key, six deletes of keys the sample never accepted, three unknown ops). The reference SQL reads them as ordinary rows, so on the sample the `ingestion`, `publications` and `reconciliation` keys differ from the domain; `run_all.py` asserts that the difference is exactly what those rows explain (duplicate +2, quarantined -1 at the as-of; +1 and -1 at 2026-09-14) and that the publications and reconciliation entries that differ are exactly those that include `b-1022`, the batch of the one delete the sample propagates. The other eight keys are equal.
