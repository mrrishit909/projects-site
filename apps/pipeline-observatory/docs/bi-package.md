# BI package (P08-ART-06)

Dataset `po-20261026-20261026` (generator `dataset_hash` `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`), contract v1, code revision `ed7eb5a`, as-of 2026-10-05T00:00:00Z. **Synthetic data only**; nothing is a claim about a real platform. The package is a reusable metric model: eight CSV dimensions and facts exported by `data/sql/analysis/run_all.py --bi-out artifacts/bi`, a measures file that withholds nothing silently, the relationships, Power Query and DAX to load and use them, and the verification status.
Observed results (this one draw), constructed relationships and hypothetical benefits (not claimed) are kept apart.
The decision it supports: **is this dataset safe, complete and fresh enough to publish?** (P08-GOAL-01).

**How to read it without installing anything:** the model first (the grain of each CSV and the relationships), then the measures with their scope and DAX, then the verification status, stated plainly. The CSV files are plain text: open them in any editor or spreadsheet; `measures_recomputed.csv` is the answer key.

## Scope: the column that travels with every figure
Every fact carries a `scope` (or, in `fact_freshness`, one scope column per figure) and `measures_recomputed.csv` carries one per measure, from the vocabulary of `dim_scope`:
| scope | meaning |
|---|---|
| `complete_world` | computed from tables the published files carry in full |
| `sample` | computed from the 2,000-row raw sample: it describes the sample, not the pipeline |
| `recorded` | a statement of the generator about the complete world that the files cannot recompute |
A figure the files cannot show is **not dropped and not 0**: the measure has a row with an empty value and a status (`recorded_only`, `sample_only`, `not_verifiable_from_the_sample`, `null: zero denominator`). Nothing is withheld silently; `tests/test_artifacts.py` fails if an empty value has the status `value`.

## The model (star schema, `artifacts/bi/`)
| File | Grain | Rows | Scope |
|---|---|---|---|
| `dim_source.csv` | one source (6) with cadence, target, schema version, expected records | 6 | complete_world |
| `dim_date.csv` | one UTC day of the window (2026-08-10 to 2026-10-04) | 56 | |
| `dim_failure_kind.csv` | one failure kind and the stage it stops at | 6 | |
| `dim_check.csv` | one gate check and its severity | 7 | |
| `dim_scope.csv` | one scope | 3 | |
| `dim_measure.csv` | one measure with its definition, default scope and contract | 30 | |
| `fact_batch.csv` | one ingestion batch, with received / accepted / duplicate / quarantined / deleted, `counted`, `sampled` and the schema-quarantined rows apart | 1,311 | complete_world |
| `fact_run.csv` | one pipeline run with stage, gate decision, failure kind, duration, task and attempt counts | 1,343 | complete_world |
| `fact_gate_check.csv` | one check result of a run that reached the gate (1,328 x 7) | 9,296 | complete_world |
| `fact_incident.csv` | one incident with the verified recovery | 25 | complete_world |
| `fact_backfill_partition.csv` | one requested partition of a request, accepted (15) or refused (4); `in_coverage` | 19 | complete_world |
| `fact_fetch.csv` | one fetch-log row; for a rate-limited response the wait and whether it honoured the hint | 1,361 | complete_world |
| `fact_freshness.csv` | one source at the as-of: ingestion age (complete_world), freshness (recorded), target, cadence, over target, silent, expected and accepted records | 6 | per column |
| `measures_recomputed.csv` | one measure per slice, recomputed from the CSV facts above in plain Python | 108 | per row |

## Relationships (all many-to-one, single direction from fact to dimension)
| From | To |
|---|---|
| `fact_batch[source_id]` | `dim_source[source_id]` |
| `fact_batch[date_key]`, `fact_run[date_key]`, `fact_fetch[date_key]`, `fact_backfill_partition[date_key]` | `dim_date[date_key]` |
| `fact_run[failure_kind]`, `fact_incident[failure_kind]` | `dim_failure_kind[failure_kind]` (blank for a successful run) |
| `fact_gate_check[rule_name]` | `dim_check[rule_name]` |
| `fact_gate_check[run_id]`, `fact_incident[run_id]` | `fact_run[run_id]` (use a bridge or `TREATAS`; keep the filter direction from `fact_run`) |
| `fact_fetch[source_id]`, `fact_backfill_partition[source_id]`, `fact_freshness[source_id]` | `dim_source[source_id]` |
| `fact_*[scope]`, `measures_recomputed[scope]` | `dim_scope[scope]` |
| `measures_recomputed[measure]` | `dim_measure[measure]` |

## Power Query (M) to load a CSV
```
let
    Source = Csv.Document(File.Contents("artifacts\bi\fact_run.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {{"duration_seconds", Int64.Type}, {"tasks_terminal", Int64.Type}, {"tasks_successful", Int64.Type},
                                                  {"attempts", Int64.Type}, {"attempts_successful", Int64.Type}, {"published", type logical}})
in
    Typed
```
Booleans are the texts `true` and `false`; empty cells are empty text (a successful run has no `failure_kind`). Proportions are decimal text with six places: load them as `type text` or `Decimal.Type` and never as a floating-point number if the six places matter.

## Measures
The measure model below is `dim_measure.csv` with a DAX definition for each. **The DAX is documentation: it was not executed** (no Power BI Desktop or DAX engine was available). Its meaning is pinned by `measures_recomputed.csv`, which the package computes with exact arithmetic from the same CSV facts.
| measure | definition | default scope | contract | DAX (not executed) |
|---|---|---|---|---|
| `accepted_unique` | rows whose source key was not yet accepted and that satisfy the contract | complete_world | D-01, D-P8-01 | `Accepted = CALCULATE(SUM(fact_batch[accepted_unique]), fact_batch[counted] = TRUE())` |
| `allowed` | runs the gate allowed (a critical result exists and none failed) | complete_world | D-P8-08 | `Allowed = CALCULATE([Runs], fact_run[gate_decision] = "allowed")` |
| `attempt_success_rate` | successful attempts / attempts | complete_world | P08-MET-06 | `Attempt Success Rate = DIVIDE(SUM(fact_run[attempts_successful]), SUM(fact_run[attempts]))` |
| `backfill_coverage` | verified partitions / requested partitions of the accepted requests | complete_world | P08-MET-11, D-09 R8-11 | `Backfill Coverage = DIVIDE(CALCULATE(COUNTROWS(fact_backfill_partition), fact_backfill_partition[in_coverage] = TRUE(), fact_backfill_partition[verified] = TRUE()), CALCULATE(COUNTROWS(fact_backfill_partition), fact_backfill_partition[in_coverage] = TRUE()))` |
| `blocked_at_gate` | runs the gate blocked | complete_world | D-P8-08 | `Blocked At Gate = CALCULATE([Runs], fact_run[gate_decision] = "blocked")` |
| `completeness` | accepted unique / expected records over all partitions of a source | complete_world | P08-MET-03 | `Completeness = DIVIDE(SUM(fact_freshness[accepted_records]), SUM(fact_freshness[expected_records]))` |
| `deleted` | removal markers that took an accepted key out of the snapshot (an exclusion with its reason, never silently lost) | complete_world | D-06 | `Deleted = CALCULATE(SUM(fact_batch[deleted]), fact_batch[counted] = TRUE())` |
| `duplicate` | rows whose source key was already accepted, whatever the payload | complete_world | D-01, D-P8-01 | `Duplicates = CALCULATE(SUM(fact_batch[duplicate]), fact_batch[counted] = TRUE())` |
| `duplicate_rate` | duplicate / received; null for a zero denominator | complete_world | P08-MET-05 | `Duplicate Rate = DIVIDE([Duplicates], [Received])` |
| `failed_before_gate` | runs that failed in a task before the gate ran | complete_world | D-09 R8-07 | `Failed Before Gate = CALCULATE([Runs], fact_run[stage] = "failed_before_gate")` |
| `failed_runs` | failed runs of one failure kind | complete_world | D-09 R8-07 | `Failed Runs = CALCULATE([Runs], fact_run[status] = "failed")   -- sliced by dim_failure_kind` |
| `fetches` | rows of the fetch log of one status | complete_world | D-09 R8-06 | `Fetches = COUNTROWS(fact_fetch)   -- sliced by status` |
| `freshness_seconds` | as-of minus the latest accepted event, whole seconds (the generator records the event) | recorded | P08-MET-01 | `Freshness (s) = MAX(fact_freshness[freshness_seconds])   -- RECORDED` |
| `incidents` | incidents opened by a failed or blocked run | complete_world | D-03 | `Incidents = COUNTROWS(fact_incident)` |
| `ingestion_age_seconds` | as-of minus the last committed batch, whole seconds | complete_world | P08-MET-02 | `Ingestion Age (s) = MAX(fact_freshness[ingestion_age_seconds])` |
| `late_events` | accepted events that arrived behind the watermark of an earlier publication | recorded | P08-MET-08 | `(no measure: RECORDED only; the sample count belongs to the sample, see the status in measures_recomputed.csv)` |
| `mean_recovery_minutes` | mean of (verified recovery - detection), minutes to 4 places | complete_world | P08-MET-10 | `Mean Recovery Minutes = DIVIDE(AVERAGE(fact_incident[recovery_seconds]), 60)` |
| `publication_content_hash_ok` | a publication whose recomputed content hash equals the stored one | recorded | D-P8-10 | `(no measure: RECORDED only; the sample cannot verify any publication)` |
| `quarantined` | rows that fail the contract, one quarantine row per occurrence; the schema-quarantined batch is not in this count | complete_world | D-01, D-09 R8-10 | `Quarantined = CALCULATE(SUM(fact_batch[quarantined]), fact_batch[counted] = TRUE())` |
| `reached_gate` | runs that have quality results | complete_world | D-09 R8-07 | `Reached Gate = CALCULATE([Runs], fact_run[gate_decision] <> "not_reached")` |
| `received` | rows of committed batches (accepted + duplicate + quarantined + deleted) | complete_world | D-01 | `Received = CALCULATE(SUM(fact_batch[received]), fact_batch[counted] = TRUE())` |
| `reconciliation_residual` | source total - published total - explained exclusions of a publication | recorded | P08-MET-09 | `(no measure: RECORDED only; investigation 06 recomputes the one non-zero candidate)` |
| `refused_backfill_partitions` | partitions of requests refused for overlap, beside the coverage and never inside it | complete_world | D-09 R8-11 | `Refused Backfill Partitions = CALCULATE(COUNTROWS(fact_backfill_partition), fact_backfill_partition[in_coverage] = FALSE())` |
| `rejection_rate` | quarantined / received; null for a zero denominator | complete_world | P08-MET-04 | `Rejection Rate = DIVIDE([Quarantined], [Received])` |
| `retries_honoured` | retries after a 429 that waited at least the retry-after hint / retries | complete_world | P08-TEST-03 | `Retries Honoured = DIVIDE(CALCULATE(COUNTROWS(fact_fetch), fact_fetch[retry_honoured] = TRUE()), CALCULATE(COUNTROWS(fact_fetch), fact_fetch[status] = "rate_limited"))` |
| `runs` | hourly pipeline runs | complete_world | D-09 R8-07 | `Runs = COUNTROWS(fact_run)` |
| `schema_quarantined_rows` | rows of the batch refused whole for a schema change, listed apart from every rate | complete_world | D-01 P08-TEST-04 | `Schema Quarantined Rows = CALCULATE(SUM(fact_batch[schema_quarantined_rows]), fact_batch[status] = "quarantined")` |
| `silent` | freshness above two declared cadences (a display rule, not a contract rule) | recorded | D-08 | `Silent = IF(MAX(fact_freshness[freshness_seconds]) > 2 * MAX(fact_freshness[cadence_seconds]), TRUE(), FALSE())` |
| `silent_sources` | sources whose freshness is above two declared cadences | recorded | D-08 | `Silent Sources = COUNTROWS(FILTER(fact_freshness, fact_freshness[silent] = TRUE()))` |
| `task_success_rate` | successful terminal tasks / terminal tasks (attempts are not tasks) | complete_world | P08-MET-06 | `Task Success Rate = DIVIDE(SUM(fact_run[tasks_successful]), SUM(fact_run[tasks_terminal]))` |

## The measures, recomputed from the CSV facts
The headline rows of `artifacts/bi/measures_recomputed.csv` (every slice is in the file; the rendered rows are those of the whole population, plus every row that is not a value):
<!-- BEGIN:bi_measures_headline -->
| measure | slice | scope | value | numerator | denominator | status | note |
|---|---|---|---|---|---|---|---|
| received | all | complete_world | 39901 |  |  | value | committed batches only |
| accepted_unique | all | complete_world | 37248 |  |  | value |  |
| duplicate | all | complete_world | 2101 |  |  | value |  |
| quarantined | all | complete_world | 429 |  |  | value |  |
| deleted | all | complete_world | 123 |  |  | value |  |
| rejection_rate | all | complete_world | 0.010752 | 429 | 39901 | value | quarantined / received; the schema-quarantined batch is not in it |
| duplicate_rate | all | complete_world | 0.052655 | 2101 | 39901 | value | duplicate / received |
| schema_quarantined_rows | all | complete_world | 17 |  |  | value | rows of the batch refused whole for SCHEMA_CHANGED; listed apart from every rate |
| runs | all | complete_world | 1343 |  |  | value |  |
| reached_gate | all | complete_world | 1328 |  |  | value |  |
| allowed | all | complete_world | 1318 |  |  | value |  |
| blocked_at_gate | all | complete_world | 10 |  |  | value |  |
| failed_before_gate | all | complete_world | 15 |  |  | value |  |
| task_success_rate | all | complete_world | 0.995311 | 5307 | 5332 | value | successful terminal tasks / terminal tasks |
| attempt_success_rate | all | complete_world | 0.971622 | 5307 | 5462 | value | attempts are not tasks |
| silent_sources | all | recorded | 1 |  |  | value |  |
| incidents | all | complete_world | 25 |  |  | value |  |
| mean_recovery_minutes | all | complete_world | 60.6827 |  |  | value | verified recovery minus detection |
| backfill_coverage | all | complete_world | 0.733333 | 11 | 15 | value | verified / requested partitions of the accepted requests |
| refused_backfill_partitions | all | complete_world | 4 |  |  | value | beside the coverage, never inside it |
| retries_honoured | all | complete_world | 1.000000 | 49 | 49 | value | retries that waited at least the retry-after hint / retries |
| late_events | complete world | recorded |  |  |  | recorded_only | the generator records 757 (manifest stats.late_events: backfill 707, corrections 41, designed 9), all included in the next publication, none lost; the published files cannot recompute it |
| late_events | 2,000-row sample | sample |  |  |  | sample_only | the reference SQL and the domain both count 141 over the sample; it describes the sample, not the world |
| reconciliation_residual | all publications | recorded |  |  |  | recorded_only | needs the amount of every raw row: the manifest records 0 of 1318 publications and 1 of 1331 candidates with a residual other than 0.00 (DR-05); only that one candidate is recomputed (investigation 06) |
| publication_content_hash_ok | complete world | recorded |  |  |  | recorded_only | the manifest records 1318 of 1318 (stats.publications.content_hash_ok) |
| publication_content_hash_ok | 2,000-row sample | sample |  |  |  | not_verifiable_from_the_sample | 0 of 1318 publications have every included batch in the sample, so the recomputed check is false for all of them (investigation 10) |
<!-- END:bi_measures_headline -->

Reconciliation (family E of `run_all.py`, 14 rows): the row counts of every CSV; the ingestion measures (received 39901, accepted 37248, duplicate 2101, quarantined 429, deleted 123, rejection rate 0.010752, duplicate rate 0.052655), the rates per source, the schema-quarantined rows 17 listed apart, the run funnel 1343 / 1328 / 1318 / 10 / 15, failed runs by kind, task success 0.995311 and attempt success 0.971622, ingestion age and freshness per source, silent sources 1 and completeness per source, incidents 25 with mean recovery 60.6827 minutes and by kind, backfill coverage 0.733333 with 4 refused partitions, retries honoured 49 of 49 and fetches by status, all against the SQL investigations, the Python domain and the manifest; nothing withheld without a status; every scope and every measure defined.

## Verification status (stated plainly)
* **Verified in this pass:** the CSV files are produced by the SQL of `data/sql/analysis/bi_*.sql` against the loaded scratch database; the measures are recomputed from the CSV text in plain Python and equal the SQL, the domain and the manifest (family E); `tests/test_artifacts.py` re-runs the SQL against fresh scratch databases and requires the same rows, and recomputes the measures again from the files.
* **Not verified:** Power BI Desktop, the DAX above, any Power Query load, any report page. There is **no `.pbix`** and none is claimed; the package is the model, the files and the answer key.
* **Scope reminder:** `freshness_seconds` and `silent` are RECORDED (the generator's latest accepted event; the sample cannot show it); `late_events`, `reconciliation_residual` and `publication_content_hash_ok` are not computable from the files and appear only as statused rows.
