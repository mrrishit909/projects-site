# Pipeline Observatory: requirements and traceability (P08-ART-02)

Dataset `po-20261026-20261026` (generator `dataset_hash` `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`), contract v1, code revision `ed7eb5a` (the app content published as `b326690`). **Synthetic data only.** Requirement ids are those of the specification (`projects/08-pipeline-observatory.md`, SHA-256 `1ffbfbe7...` at pack commit `fe5f7981`, verified against `docs/program/source-pack.json`); decisions D-01..D-09 are in `contracts.md`.
The organising question: **is this dataset safe, complete, and fresh enough to publish?** (P08-GOAL-01).

**How to read it without installing anything:** section 1 gives the user stories with acceptance criteria and the observed answer; sections 2 and 3 the functional and non-functional requirements; section 4 the traceability matrix (requirement id, code, test, evidence); section 5 what is deferred, open or not verified. Observed results, constructed (designed) relationships and hypothetical benefits are kept apart throughout.

## 1. User stories and acceptance criteria
| # | As a... | I want... | Acceptance criterion | Observed answer (scope) |
|---|---|---|---|---|
| US-1 | data engineer | a batch that crashes after writing rows to be replayed without a second copy of any key | after a crash before the checkpoint the accepted count is unchanged and the checkpoint did not move; the replay accepts each key once | golden: 8 before and after, version 2; world: 8 of 8 crashed batches replayed, 273 rows classified once (complete world) |
| US-2 | data reliability analyst | to see a source that is stale while its jobs are green | freshness is shown beside ingestion age, independent of job colour | `src-refunds` 262,378 s against 17,363 s, 72 green runs (freshness recorded, age complete world) |
| US-3 | data engineer | a failed or blocked run never to replace the publication | the pointer moves only to a successful run with an allowed gate | 25 runs left it; `run-1187` blocked, pointer stayed on `pub-1186` (complete world) |
| US-4 | analyst | every received row in exactly one class | received = accepted + duplicate + quarantined + deleted | 39,901 = 37,248 + 2,101 + 429 + 123 (complete world) |
| US-5 | source owner | a retry never to come sooner than the source asked | every retry waits at least `retry_after_seconds`; a repeated cursor in one session stops the fetch | 49 of 49 retries honoured; 1 loop stopped; 48 refetches not mistaken for loops (complete world) |
| US-6 | data consumer | a late event behind the watermark to be counted and included next time | late events are counted, included in the next publication, never lost | 757 recorded, 0 lost (recorded); 141 recomputed over the sample |
| US-7 | analyst | the published total to reconcile to a stated residual | residual = source total - published total - signed exclusions, with its parts | 0.00 on 1,318 of 1,318 (recorded); one blocked candidate -141.46 (recomputed from parts) |
| US-8 | on-call engineer | an incident to close only after a verified recovery | recovery time = verified recovery - detection | 25 of 25; mean 60.6827 minutes (complete world) |
| US-9 | analyst | backfills that cannot run together over one range | a request overlapping a requested or running one is refused with its id consumed | bf-006 and bf-012 refused; coverage 11 of 15 = 0.733333 (complete world) |
| US-10 | reviewer | every number to say what it is a number of | each figure is tagged complete world, 2,000-row sample or recorded | the scope column of the BI package and the scope tags of the site |

## 2. Functional requirements (commands and reads; `docs/api-contract.md`, `README.md`)
| ID | Requirement | Command or read |
|---|---|---|
| P08-FLOW-01 | fetch a source page from a cursor; 429 records `retry_after_seconds`; a retry sooner is refused; a repeated cursor in one session is a loop | C01 `POST /commands/fetch-source-page` |
| P08-FLOW-02 | validate a batch against the contract: accepted / duplicate / quarantined per row; a page declaring another schema is quarantined whole | C02 `validate-contract` |
| P08-FLOW-03 | commit a batch with its checkpoint (version previous + 1) in one transaction; idempotent on `(source_id, source_key)` | C03 `commit-batch` |
| P08-FLOW-04 | transform the models; key and relationship tests | C04 `transform-models` |
| P08-FLOW-05 | run the quality gate: fail closed, a critical failure blocks and opens an incident | C05 `run-quality-gate` |
| P08-FLOW-06 | publish a passed candidate and move the pointer atomically; watermark disclosed, never regressing | C06 `publish-snapshot` |
| P08-FLOW-07 | inject a fault, sandbox only (`PIPELINE_ENVIRONMENT=sandbox`) | C07 `inject-fault` |
| P08-FLOW-08 | request a backfill over a half-open range; refuse an overlap with a requested or running request | C08 `request-backfill` |
| P08-FLOW-09 | recover an incident only after a verified recovery with residual 0.00 | C09 `recover-incident` |
| P08-FLOW-10 | archive evidence with a sha256 per item and the retention mapping | C10 `archive-evidence` |
| reads | stable ordering, cursor, filters and half-open windows over 23 entities; the eleven metric families | `GET /data/{entity}`, `GET /metrics` |

## 3. Non-functional requirements
| Area | Requirement | How it is met and checked |
|---|---|---|
| Correctness | no floating point in a published figure; proportions 6 places, minutes 4, money 2; null for a zero denominator | Python `Fraction` and `Decimal`; `FLOAT_NOT_ALLOWED`; `test_migrations.py` (no float column) |
| Idempotency and concurrency | one transaction per command; replay storms and concurrent commits accept each key once | `test_adversarial.py` (concurrent replays, four concurrent backfills, one winner); `test_api_protocol.py` |
| Delivery guarantee | at-least-once with idempotent apply, proven at the source-key boundary, never exactly-once (P08-DOMAIN-04) | `accepted_records` primary key; crash proven three ways (hook, killed backend, armed fault) |
| Immutability | publications and evidence are append-only; the pointer moves only to a passed candidate | triggers in migration 0002; `test_migrations.py` |
| Security | no secret in a log line; a workflow never triggers itself; identity is header-asserted, there is no authentication (D-09 R8-14); sandbox off by default (R8-13) | `test_redaction.py`, `test_workflow_guard.py` (the real `pipeline-observatory-ci.yml` is checked), `test_api_protocol.py` |
| Reproducibility | deterministic generator (seed 20261026), byte-identical on rerun; fixture hashes verified | `tests/test_generator.py`, `tests/test_hashes.py`, `reference_check.py` (7 hashes) |
| Independence | the expected answer, the SQL reference and the TypeScript mirror do not share code with the domain | `tests/reference_check.py` (stdlib only), `data/sql/reference_metrics.sql`, `web/scripts/golden-check.ts` |
| Hosted compute | code runs on GitHub-hosted runners with a transient `postgres:16`; nothing on a laptop | `.github/workflows/pipeline-observatory-ci.yml` (jobs `reference-and-domain`, `web`) |
| Accessibility and responsiveness | four widths and 200% zoom, no horizontal overflow, no console errors | `web/e2e/screens.spec.ts` |
| Disclosure | every figure on the site and in these documents carries its scope; synthetic everywhere | the evidence page; the BI `scope` column |
| Artifacts | binary outputs generated on hosted compute and kept in GitHub releases (P08-ART-xx-R06) | **not yet attached to a release** (section 5) |

## 4. Traceability matrix
### Goals and domain boundaries
| ID | Requirement (short) | Where met | Verified by |
|---|---|---|---|
| P08-GOAL-01 | the decision: safe, complete and fresh enough to publish | the verdict rule on the site's landing page; `Publish decision` in the workbook; `executive-memo.md` | `web/e2e/journey.spec.ts` (landing); `tests/test_artifacts.py` (workbook verdict) |
| P08-GOAL-02..04 | portfolio roles, visual direction, slug and routes consistent | `web/src/routes.ts`, the catalogue entry | `journey.spec.ts` (every route reachable on the nested base path) |
| P08-GOAL-05, 06 | hosted compute only; static demo by default, backend evidence from CI | CI workflow; the site is a static build | CI runs (`release-package.md`) |
| P08-GOAL-09, 10 | entry journey on the fixture; mid-level exceptions and recovery | the golden fixture and the 12 experiments | `tests/test_api_golden.py`; the replay events EV-01..12 in `tests/test_generator.py` |
| P08-GOAL-12 | no live data, payment or write | synthetic generator; simulations labelled | `journey.spec.ts` (honesty labels) |
| P08-GOAL-13, 14 | meaning defined before implementation; conflicts resolved by a logged decision | `contracts.md` D-01..D-09; `CALCULATION.md` | `tests/reference_check.py` |
| P08-DOMAIN-01..03 | PostgreSQL only as a hosted service; the repository is canonical; databases rebuilt each run | CI `services: postgres`; `data/migrate.py`, `data/seed.py`; this package's scratch databases | `tests/test_migrations.py`; `run_all.py` |
| P08-DOMAIN-04 | no exactly-once claim without a boundary proof | `contracts.md` D-01; `technical-case-study.md` | crash tests (`test_api_commands.py::test_c03_*`) |
| P08-DOMAIN-05, 06 | immutable static snapshots; durable results as compact versioned files | `web/public/data` (4.7 MB, 16 entity files); `artifacts/` | `tests/test_generator.py` (size budget) |

### Data model (P08-DATA-01..12)
| ID | Entity | Table | Published file | Dictionary |
|---|---|---|---|---|
| P08-DATA-01 | source_contracts | `source_contracts` (+ `source_expectations`) | `source_contracts.json`, `source_expectations.json` | `data-dictionary.md` |
| P08-DATA-02 | ingestion_batches | `ingestion_batches` | `ingestion_batches.json` | yes |
| P08-DATA-03 | raw_records | `raw_records` (+ `accepted_records`) | `raw_records.json` (**2,000-row sample**) | yes |
| P08-DATA-04 | quarantine_records | `quarantine_records` | `quarantine_records.json` | yes |
| P08-DATA-05 | checkpoints | `checkpoints` | `checkpoints.json` | yes |
| P08-DATA-06 | model_definitions | `model_definitions` | `model_definitions.json` | yes |
| P08-DATA-07 | pipeline_runs | `pipeline_runs` | `pipeline_runs.json` | yes |
| P08-DATA-08 | task_runs | `task_runs` | `task_runs.json` | yes |
| P08-DATA-09 | quality_results | `quality_results` | `quality_results.json` | yes |
| P08-DATA-10 | publications | `publications` (+ `publication_pointer`) | `publications.json` | yes |
| P08-DATA-11 | incidents | `incidents` | `incidents.json` | yes |
| P08-DATA-12 | backfill_requests | `backfill_requests` | `backfill_requests.json` | yes |
Verified by `tests/test_migrations.py` (schema, constraints) and `test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations` in `tests/test_artifacts.py`.

### Metrics (P08-MET-01..12)
| ID | Metric | Domain (`domain/pipeline_observatory/metrics.py`) | Independent SQL | Golden value | Snapshot value (scope) | Analysis |
|---|---|---|---|---|---|---|
| P08-MET-01 | source freshness | `_freshness` | `reference_metrics.sql` `freshness` | 52,200 s | refunds 262,378 s (recorded) | sql-analysis 4 |
| P08-MET-02 | ingestion age | `_freshness` | `freshness` | 42,900 s | refunds 17,363 s (complete world) | sql-analysis 4 |
| P08-MET-03 | completeness | `_completeness` | `completeness` | 0.888889 | 0.945541 refunds ... 0.995255 (complete world) | sql-analysis 4 |
| P08-MET-04 | rejection rate | `_ingestion` | `ingestion` | 0.100000 | 0.010752 (complete world) | sql-analysis 1 |
| P08-MET-05 | duplicate rate | `_ingestion` | `ingestion` | 0.100000 | 0.052655 (complete world) | sql-analysis 1 |
| P08-MET-06, 07 | pipeline duration; task success rate | `_runs` | `runs` | 1.000000 / 0.800000 | 0.995311 / 0.971622; 13.9114 and 13.7227 min | sql-analysis 2, 3 |
| P08-MET-08 | publication lag | `compute` (publications) | `publications` | 3,600 s | recorded for the world; the sample cannot show it | sql-analysis 10 |
| P08-MET-09 | reconciliation residual | `compute` (reconciliation) | `reconciliation` | 0.00 | 0.00 on 1,318 (recorded); -141.46 on one candidate | sql-analysis 6 |
| P08-MET-10 | recovery time | `compute` (incidents) | `incidents` | 475.0000 min | mean 60.6827 min (complete world) | sql-analysis 6 |
| P08-MET-11 | backfill coverage | `compute` (backfills) | `backfills` | 0.666667 | 0.733333 (complete world) | sql-analysis 7 |
| P08-MET-12 | observed processing rate | `compute` (processing_rate) | `processing_rate` | 0.666667 | 39.253789 records/s on one synthetic batch, not a benchmark (recorded); 39.642441 over the sample | sql-analysis 10 |
Verified by `tests/test_golden_domain.py`, `tests/test_sql_reference.py`, `web/scripts/golden-check.ts` and `run_all.py` families A and B.

### Workflows (P08-FLOW-01..10)
| ID | Command | Test (examples) |
|---|---|---|
| P08-FLOW-01 | C01 | `test_c01_p08_test_03_*`, `test_c01_p08_test_10_*`, `test_review_fixes.py::test_a_fetch_must_name_its_session` |
| P08-FLOW-02 | C02 | `test_c02_p08_test_04_*`, `test_c02_p08_test_05_*` |
| P08-FLOW-03 | C03 | `test_c03_crash_*`, `test_c03_a_real_backend_kill_*`, `test_c03_an_injected_crash_fault_*` |
| P08-FLOW-04 | C04 | `test_c04_a_delete_event_*` |
| P08-FLOW-05 | C05 | `test_c05_p08_test_06_*`, `test_review_fixes.py::test_a_publication_that_omits_a_committed_batch_is_blocked_by_scope_complete` |
| P08-FLOW-06 | C06 | `test_c06_refuses_*`, `test_review_fixes.py::test_a_watermark_never_goes_back` |
| P08-FLOW-07 | C07 | `test_review_fixes.py::test_the_sandbox_allows_a_fault_only_when_it_says_sandbox` |
| P08-FLOW-08 | C08 | `test_c08_*`, `test_adversarial.py::test_06` |
| P08-FLOW-09 | C09 | `test_c09_*` |
| P08-FLOW-10 | C10 | `test_c10_*` |

### Screens (P08-UI-01..10; `web/src/routes.ts`)
| ID | Screen | Route | Browser test (`web/e2e/journey.spec.ts`) |
|---|---|---|---|
| P08-UI-01 | Platform overview | `overview/` | "overview: freshness beside ingestion age equals the Python reference; the silent source is hatched while its jobs are green" |
| P08-UI-02 | Dependency graph | `dag/` | "dag: freshness on the nodes, and keyboard isolation of a node" |
| P08-UI-03 | Run detail | `runs/` | "runs: the blocked run keeps the pointer ..." and the golden case test |
| P08-UI-04 | Source contract | `sources/` | "incidents, sources, benchmark, evidence and case study: figures equal Python's" |
| P08-UI-05 | Quarantine desk | `quarantine/` | "quarantine desk: filters, no-data state, replay of a corrected row in memory ..." |
| P08-UI-06 | Quality gate | `gate/` | "gate: critical checks, the decision, the pointer; fault injection re-decides in memory ..." |
| P08-UI-07 | Backfill console | `backfill/` | "backfill: totals equal Python's; the refused requests; ..." |
| P08-UI-08 | Incident timeline | `incidents/` | the combined test above |
| P08-UI-09 | Benchmark evidence | `benchmark/` | the combined test above |
| P08-UI-10 | Case study | `case-study/` | the combined test above |

### Adversarial tests (P08-TEST-01..12, detect and recover)
| ID | Experiment | Detect / recover | Tests |
|---|---|---|---|
| P08-TEST-01 | crash after the data write, before the checkpoint (INJ-01) | the batch stays `staged`/`aborted`, counts for nothing; the replay accepts each key once | `test_api_commands.py::test_c03_crash_*`, `test_adversarial.py::test_01`, `::test_03`; world: sql-analysis 1 `crash_replay` |
| P08-TEST-02 | overlapping backfills (INJ-02) | `BACKFILL_OVERLAP`, kept in `rejected_records` | `test_adversarial.py::test_06`, `test_c08_*`; sql-analysis 7 |
| P08-TEST-03 | retries ignore retry-after (INJ-03) | `RETRY_TOO_SOON`; the log shows all waits honoured | `test_domain_rules.py::test_p08_test_03_*`; sql-analysis 8 |
| P08-TEST-04 | schema adds a required field (INJ-04) | the batch quarantined whole; bump on purpose; refetch | `test_domain_rules.py::test_p08_test_04_*`; sql-analysis 1 |
| P08-TEST-05 | malformed row vanishes (INJ-05) | quarantined with a reason, never dropped | `test_domain_rules.py`, `test_c02_p08_test_05_*` |
| P08-TEST-06 | green job, stale source (INJ-06) | freshness beside ingestion age; the declared target is the control | `test_c05_p08_test_06_*`; sql-analysis 4 |
| P08-TEST-07 | failed run replaces a publication (INJ-07) | gate blocks, pointer unmoved, verified recovery | `test_adversarial.py::test_07`; sql-analysis 5 |
| P08-TEST-08 | delete not propagated (INJ-08) | delete propagates as a signed exclusion | `test_domain_rules.py::test_p08_test_08_*` |
| P08-TEST-09 | late event behind the watermark (INJ-09) | counted and included in the next publication | `test_domain_rules.py::test_p08_test_09_*` |
| P08-TEST-10 | pagination token repeats (INJ-10) | `CURSOR_LOOP` inside a session; a new session is a refetch | `test_domain_rules.py::test_p08_test_10_*`; sql-analysis 8 |
| P08-TEST-11 | secret in a structured log (INJ-11) | the redaction check | `tests/test_redaction.py` |
| P08-TEST-12 | workflow triggers itself (INJ-12) | the workflow guard | `tests/test_workflow_guard.py` |

### Known answer and work packages
| ID | Where met |
|---|---|
| P08-GOLD-01..11 | `tests/fixtures/golden/` (`inputs.json`, `expected.json`, `CALCULATION.md`, `HASHES.json`, rejected and empty variants), `tests/reference_check.py`; SQL in `09_golden_known_answer.sql` |
| P08-WORK-01..10 | the ledgers `docs/program/` (contract, fixtures, data, backend, web, analytics, review, artifacts, release, integrate); this package is P08-WORK-08 |

### Artifacts (P08-ART-01..10)
| ID | Deliverable | File |
|---|---|---|
| P08-ART-01 | business case | `docs/business-case.md` |
| P08-ART-02 | requirements and traceability | this file |
| P08-ART-03 | data dictionary and ERD | `docs/data-dictionary.md`, `docs/erd.md` |
| P08-ART-04 | executable SQL investigations, reconciled | `data/sql/analysis/`, `docs/sql-analysis.md`, `artifacts/analysis-results.json` |
| P08-ART-05 | formula-driven workbook | `artifacts/pipeline-observatory-analyst-workbook.xlsx`, `docs/workbook.md` |
| P08-ART-06 | BI package | `artifacts/bi/*.csv`, `docs/bi-package.md` |
| P08-ART-07 | executive memo | `docs/executive-memo.md` |
| P08-ART-08 | UAT evidence | `docs/uat-evidence.md` |
| P08-ART-09 | technical case study | `docs/technical-case-study.md` |
| P08-ART-10 | release package, checksums, résumé bullets | `docs/release-package.md`, `artifacts/CHECKSUMS.txt`, `docs/resume-bullets.md` |
Each artifact cites the dataset hash and the code revision, names real entities, metrics and workflow ids, separates observed from simulated from hypothetical, and is checked by `tests/test_artifacts.py`.

## 5. Deferred and open (stated, not hidden)
* **Hosted run of `tests/test_artifacts.py`:** none is recorded yet. The CI workflow (`pipeline-observatory-ci.yml`, job `reference-and-domain`) provisions LibreOffice Calc, the scratch databases `artifacts08_snapshot` and `artifacts08_golden` (exported as `ARTIFACTS_DATABASE_URL` and `ARTIFACTS_GOLDEN_DATABASE_URL`), full history and the portfolio case study, so the tests are meant to run there without skipping. Without LibreOffice, the scratch URLs, the commit `ed7eb5a` or the portfolio case study they skip with a printed reason; a no-skip gate would count those skips.
* **Excel and Power BI Desktop were not run.** The workbook was recalculated by LibreOffice only; there is no `.pbix` and the DAX is documentation.
* **Binary artifacts are not attached to a GitHub release** (P08-ART-xx-R06): the workbook was generated in the session's cloud container; a durable release asset needs a hosted workflow run, which this package did not start.
* **Not built (also stated by the public case study):** the full raw-record history in the verified database; replay events for C09 and C10; delete events in the SQL reference (reconciled exactly in `sql-analysis.md` section 11); a real fetcher and scheduler; authentication.
* **Links from the site's evidence area (P08-ART-xx-R14):** left to the coordinator; the documents are safe to link (synthetic, no credentials).
