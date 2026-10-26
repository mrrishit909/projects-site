# ServiceFlow: requirements and traceability (P04-ART-02)

Dataset `sf-20261026-20261026` (generator hash `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4`), contract v1, code revision `43de7f8`. **Synthetic data only.**
Organising question: **which staffing or routing change meets support targets under uncertain workload?** (P04-GOAL-01). Observed, simulated and hypothetical results are kept apart in every row below: nothing is a realised benefit.

Status values: `verified` (a command was run and its result is recorded here or in `uat-evidence.md`) | `partial` (built in part, the gap named) | `deferred` (not built, stated openly) | `501` (the endpoint exists and answers 501 `NOT_IMPLEMENTED`) | `not_checked` (no check was run). The machine-readable ledger of the program is `docs/program/verification-ledger.json` (outside this directory). "Local" means run in the Linux container on PostgreSQL 16;
"hosted" means a GitHub Actions run on a hosted runner. Hosted runs cited here are those of the ledger (code `6a753e8`, CI `40364940392`, live check `40367109366`); **the reviewer fixes at `43de7f8` (release `e44d15d`) have local evidence only until a hosted run is recorded** (`release-package.md`).
How to read this without installing anything: sections 1-3 are the requirements, section 4 the traceability matrix, section 5 what is deferred.

## 1. User stories and acceptance criteria
1. **As an operations analyst** I open the overview and see arrivals, completions, backlog, first response with its P90, SLA compliance with open overdue kept apart, occupancy, abandonment and CSAT for a window, each with its definition beside it.
   *Accept:* all 28 metric keys equal the independent reference for the whole, training and holdout windows (`data/sql/reference_metrics.sql` against the Python domain; 303 TypeScript golden checks; `sql-analysis.md` section 10).
2. **As an analyst** I see the known answer reproduced before any random arrival: one agent, three tickets at minute 0, 10-minute service, starts 0 / 10 / 20, waits 0 / 10 / 20, mean wait 10, last completion 30.
   *Accept:* equal in the Python domain, the SQL reference, the TypeScript domain, `expected.json` and the workbook's `Golden case` sheet.
3. **As a supervisor** I cannot start service for an agent outside a shift, on a break, without the queue's skill or over the declared concurrency, and I cannot move a ticket's arrival by transferring it.
   *Accept:* 422 `AGENT_NOT_IN_SHIFT`, `AGENT_ON_BREAK`, `AGENT_NOT_QUALIFIED`, `CONCURRENCY_EXCEEDED`; `tickets.created_at` cannot change (`ARRIVAL_IMMUTABLE`); exactly one of two simultaneous starts for one agent wins.
4. **As a planner** I compare a baseline and a proposal on the same seeds and read a paired 95 % interval labelled an estimate, with the warm-up and horizon declared.
   *Accept:* `sim-002` minus `sim-001` over 50 replications is -10.8932 minutes with half-width 3.4329 (simulated), reproduced by the Python simulator and the browser (`data/simulation_reference.py --check`, `npm run check`).
5. **As a data steward** every refused row is kept with its reason and the planted defects are found.
   *Accept:* 70 rows in `rejected_records` equal the manifest's expected rejections; 8 of 9 injected defects found by SQL, the ninth replay-only (`sql-analysis.md` query 08).
6. **As a BI analyst** I can rebuild the headline measures from CSV exports and compare them with the independent recomputation.
   *Accept:* 17 contract measures recomputed from `artifacts/bi/*.csv` equal `reference_metrics.sql` and the domain (`bi-package.md`).
7. **As a reader of the evidence** I see what is built and what returns 501 (C07, C10) and which screens are stubs.
   *Accept:* the case-study and evidence routes say so; this file lists it in section 5.

## 2. Functional requirements
| ID | Requirement | Entities, metrics, commands |
|---|---|---|
| FR-01 | Ingest raw ticket history into an immutable ordered event log; preserve late arrivals; refuse duplicates and defects with a reason and keep the raw row | `ticket_events`, `rejected_records`, `raw_batches`; C01 |
| FR-02 | Reconstruct a state per ticket from the log; a reopen is one customer contact and links the prior cycle | `ticket_events`; C06 |
| FR-03 | FIFO within priority unless the queue overrides; a transfer keeps the arrival and restarts only the per-queue wait | `queues.priority_policy`, `tickets`; C04 |
| FR-04 | Start service only for an agent inside a shift, not on a break, qualified at that instant and under `max_concurrent` | `shifts`, `shift_breaks`, `agent_skills`, `agents`; C03, `resume-work` |
| FR-05 | Compute the 12 contract metrics for any half-open window, cutoff and grouping (queue, priority, agent, channel) with disclosures beside them | P04-MET-01..11; `GET /metrics` |
| FR-06 | Run a seeded simulation with a declared warm-up and horizon, replications and a paired comparison on common random numbers; label estimates as estimates | `simulation_runs`, `simulation_events`; C08, C09, P04-MET-12 |
| FR-07 | Build a candidate shift scenario with availability and breaks respected | `shifts`; C07 (501) |
| FR-08 | Export a reviewed recommendation with uncertainty and targets embedded | C10 (501) |
| FR-09 | Serve the published snapshot as a static interactive site that reproduces the golden case and the three seeded runs in the browser | Mode B: `web/` |
| FR-10 | Provide an independent SQL recomputation of every metric and reconcile every artifact number to it | `data/sql/reference_metrics.sql`, `data/sql/analysis/` |
| FR-11 | Read every entity with stable ordering, paging and a half-open time filter | `GET /data/{entity}` |

## 3. Non-functional requirements
| ID | Requirement | How it is met |
|---|---|---|
| NFR-01 | Deterministic synthetic data: the same seed gives the same bytes; size under 5 MB | `data/generate.py` seed 20261026; 3,826 tickets (the spec's "about 6,000" exceeds the cap, D-07) |
| NFR-02 | Exact arithmetic: minutes at 4 dp and rates at 6 dp from exact rationals, half-up; no float in a published figure | `domain/serviceflow/timeutil.py`; TypeScript integer seconds and rationals |
| NFR-03 | Idempotent commands, actor-bound; 409 for a stale dataset version or a reused key with another payload; 422 with a rule id; never a stack trace | `api/commands.py`, `api/errors.py` (D-06, D-09 R4-05) |
| NFR-04 | Atomic audit: the effect, the audit row and the stored result are one transaction; a failed command leaves no trace | `test_a_failed_command_leaves_no_trace` |
| NFR-05 | Concurrency: lock order idempotency key, ticket rows, agent rows; a deadlock is retried three times then 409 `CONCURRENT_UPDATE` | `test_a_deadlock_is_retried_then_409_never_500`, `test_two_simultaneous_starts_for_one_agent_exactly_one_wins` |
| NFR-06 | Authorization on the verified backend: 401 without an identity, 403 for a forbidden role; the public site never claims access control | `test_missing_actor_is_401_and_bad_role_is_403`, `test_an_analyst_cannot_change_ticket_state_but_may_ingest_and_simulate` |
| NFR-07 | Accessibility and responsiveness: four widths (360, 768, 1280, 1920) and 200 % zoom, no horizontal overflow, labelled tables | `web/e2e/screens.spec.ts` (55 screenshots) |
| NFR-08 | No credentials, real personal records or secrets in any artifact; synthetic label visible | the artifact documents hold placeholders only; `customers.synthetic` is TRUE |
| NFR-09 | Hosted compute and durable evidence: backend on a `postgres:16` service, static build on a hosted runner, evidence archived with checksums | `.github/workflows/serviceflow-ci.yml`, `artifacts/CHECKSUMS.txt` |
| NFR-10 | Reproducible artifacts: every artifact number is reproducible by a named command and reconciled to an independent source | `data/sql/analysis/run_all.py` (185 reconciliation rows), `tests/test_artifacts.py` |

## 4. Traceability matrix
Code paths are under `apps/serviceflow/`. A test name is a function of the named file.

| Requirement | Built in | Test | Evidence | Status |
|---|---|---|---|---|
| P04-GOAL-01, 02 (decision, roles) | `docs/business-case.md`, `docs/executive-memo.md` | `tests/test_artifacts.py` (documents quote the stored results) | `business-case.md` | verified (local) |
| P04-GOAL-03, 04, 06 (visual direction, slug and routes, static default) | `web/src`, `web/public/data/manifest.json` | `web/e2e/journey.spec.ts` (11 routes reachable by direct entry and reload) | CI `40364940392` (Mode B, `6a753e8`); local `npm run e2e` 70 passed at `43de7f8` | verified (hosted on `6a753e8`, local on `43de7f8`) |
| P04-GOAL-05, REL-05 (hosted backend suite with a transient PostgreSQL) | `.github/workflows/serviceflow-ci.yml` | the whole `pytest` suite | CI `40364940392` Mode A (`6a753e8`); local 377 passed at `43de7f8` | verified (hosted on `6a753e8`); hosted run of `43de7f8` pending |
| P04-GOAL-09 (entry milestone: a source-to-decision journey and a working export) | `web/src/views/*` | `web/e2e/journey.spec.ts` | `uat-evidence.md` section 4 | partial: the journey runs end to end; the **export is not built** (C10 501) |
| P04-GOAL-10 (exceptions, robustness, versioning, recovery) | `api/`, `domain/` | `tests/test_adversarial.py`, `tests/test_api_commands.py`, `tests/test_review_findings.py` | `uat-evidence.md` (R4-01..R4-18) | verified (local) |
| P04-GOAL-12 (no live data, payment, operational write in the demo) | `web/` (in-memory adapter) | `web/e2e/journey.spec.ts` | the landing and case study state it | verified |
| P04-DOMAIN-01 FIFO within priority | `domain/serviceflow/simulation.py`, `events.py` | `tests/test_rules.py::test_fifo_within_priority_a_p1_overtakes_a_waiting_p2` and 2 more | local | verified (local) |
| P04-DOMAIN-02, 03 (train on weeks 1-8, validate on 9-12) | `domain/serviceflow/simulation.py` `holdout_report` | `test_holdout_intensity_change_is_reported_not_hidden`, `test_p04_test_12_holdout_intensity_change_is_reported` | `sql-analysis.md` 01, 03 | verified (local) |
| P04-DOMAIN-04 (utilisation and the tail separately) | `domain/serviceflow/metrics.py` | `test_p90_is_shown_beside_the_mean_and_the_per_priority_tail` | `sql-analysis.md` 02, 04 | verified (local) |
| P04-DOMAIN-05 (repeated seeds, comparable demand) | `domain/serviceflow/simulation.py` | `test_common_random_numbers_policies_see_the_same_demand`, `test_compare_policies_same_seed_same_demand` | `executive-memo.md` (50 replications) | verified (local) |
| P04-DOMAIN-06 (estimate is not a realised benefit) | labels on every simulated figure | `tests/test_artifacts.py::test_memo_*` | `executive-memo.md` | verified |
| P04-GOLD-01..07 (known answer, hash, tolerance) | `tests/fixtures/golden/`, `tests/reference_check.py` | `tests/reference_check.py` (ALL OK), `tests/test_golden_domain.py` (13), `tests/test_sql_reference.py` | `sql-analysis.md` section 09-10: 28 keys equal in three sources | verified (local); the reference check also at ledger entry `15:30:18Z` |
| P04-GOLD-08, 09 (rejected and empty variants) | `tests/fixtures/golden/variant-rejected`, `variant-empty` | `tests/test_variants.py` (6) | local | verified (local) |
| P04-DATA-01..12 (entities and field contracts) | `data/migrations/0001_schema.sql`, `0002_constraints.sql`, `domain/serviceflow/models.py` | `tests/test_migrations.py` (19), `test_entity_columns_are_exactly_the_contract_fields` | `data-dictionary.md`, `erd.md` | verified (local) |
| P04-MET-01, 02 (arrival, completion rate) | `domain/serviceflow/metrics.py`, `reference_metrics.sql` | `test_metric_equals_expected`, `test_sql_agrees_with_the_domain_in_other_windows` | 3,817 / 3,608 reconciled in `sql-analysis.md` section 10 | verified (local) |
| P04-MET-03 (backlog at a cutoff) | same | `test_R4_18_*` (cutoff edge) | 12 Monday cutoffs reconciled (query 03) | verified (local) |
| P04-MET-04, 07 (first response, P90 nearest rank) | same | `test_p90_nearest_rank_n10_is_the_ninth_value_not_the_tenth` | 28.0046 / 44.1500 in three sources | verified (local) |
| P04-MET-05, 06 (resolution, handling) | same | `test_handling_excludes_waiting_customer_and_idle_time` | 164.5909 / 189,836.2667 in three sources | verified (local) |
| P04-MET-08 (SLA compliance, open overdue apart) | same | `test_open_overdue_tickets_are_counted_and_shown_separately` | `sql-analysis.md` 03 | verified (local) |
| P04-MET-09 (occupancy) | same | `test_occupancy_is_handling_over_staffed_time_and_null_without_staff`, `test_R4_01_*` | 0.424263 in three sources | verified (local) |
| P04-MET-10, 11 (abandonment, CSAT with response rates) | same | `test_abandonment_only_counts_channels_that_can_abandon`, `test_csat_nonresponse_is_disclosed_beside_the_score` | 0.118213 / 0.864000 in three sources | verified (local) |
| P04-MET-12 (simulated wait improvement) | `domain/serviceflow/simulation.py`, C09 | `test_R4_11_*`, `test_simulation_replications_report_count_and_interval` | `executive-memo.md` | verified (local); simulated |
| P04-FLOW-01 (C01 ingest) | `api/commands.py`, `domain/serviceflow/ingest.py` | `test_ingest_*` (10), `test_R4_02_*`, `test_R4_03_*` | `uat-evidence.md` | verified (local) |
| P04-FLOW-02 (C02 assign queue) | `api/commands.py` | `test_assign_queue_*` (3) | local | verified (local) |
| P04-FLOW-03 (C03 start service) | same | `test_start_service_*` (6) | local | verified (local) |
| P04-FLOW-04 (C04 transfer) | same | `test_transfer_*` (4), `test_p04_test_08_a_transfer_never_resets_the_arrival` | local | verified (local) |
| P04-FLOW-05 (C05 pause, resume) | same | `test_pause_*` (3) | local | verified (local) |
| P04-FLOW-06 (C06 reopen) | same | `test_reopen_*` (2) | local | verified (local) |
| **P04-FLOW-07 (C07 build shift scenario)** | `api/app.py` `refuse(...)` | `test_extension_commands_are_501` | the route answers 501 `NOT_IMPLEMENTED` | **501** (deferred) |
| P04-FLOW-08 (C08 run simulation), P04-FLOW-09 (C09 compare policies) | `api/commands.py` | `test_golden_simulation_through_the_api`, `test_compare_policies_same_seed_same_demand` | local | verified (local) |
| **P04-FLOW-10 (C10 export recommendation)** | `api/app.py` `refuse(...)` | `test_extension_commands_are_501` | the route answers 501 `NOT_IMPLEMENTED` | **501** (deferred) |
| P04-UI-01 Operations overview | `web/src/views/overview.tsx` | `web/e2e/journey.spec.ts` (overview), `review.spec.ts` | screenshots `overview-*.png` | verified (hosted on `6a753e8`, local on `43de7f8`) |
| P04-UI-02 Queue explorer | `web/src/views/stub.tsx` | the route loads | `queues-*.png` | **deferred (stub that shows no figures)** |
| P04-UI-03 Ticket timeline | `web/src/views/tickets.tsx` | `journey.spec.ts` (tickets) | `tickets-*.png` | verified |
| P04-UI-04 Staffing grid | `web/src/views/staffing.tsx` | `journey.spec.ts` (staffing, 420 against 480 minutes) | `staffing-*.png` | verified |
| P04-UI-05 SLA review | `web/src/views/sla.tsx` | `journey.spec.ts` (sla), `review.spec.ts` | `sla-*.png` | verified |
| P04-UI-06 Simulation studio | `web/src/views/simulation.tsx` | `journey.spec.ts` (simulation), `review.spec.ts` (50 replications) | `simulation-*.png` | verified |
| P04-UI-07 Scenario comparison, P04-UI-08 Survey analysis | `web/src/views/stub.tsx` | the routes load | `compare-*.png`, `surveys-*.png` | **deferred (stubs)** |
| P04-UI-09 Evidence ledger, P04-UI-10 Case study | `web/src/views/evidence.tsx`, `case-study.tsx` | `journey.spec.ts` | `evidence-*.png`, `case-study-*.png` | verified |
| P04-TEST-01 bot acknowledgement | `domain/serviceflow/ingest.py`, constraint `events_bot_reply_ck` | `test_p04_test_01_*`, `test_a_bot_cannot_author_a_human_reply_even_directly` | `sql-analysis.md` 08 (INJ-01: 4 refused) | verified (local) |
| P04-TEST-02 reopen is one customer | `domain/serviceflow/events.py` | `test_p04_test_02_*`, `test_reopen_is_one_customer` | query 05; INJ-02 analyst check finds 4 | verified (local) |
| P04-TEST-03 incompatible skill | `ingest.py`, C03 | `test_p04_test_03_*` | query 08 (INJ-03: 3 refused) | verified (local) |
| P04-TEST-04 simultaneous services | `ingest.py`, C01/C03 row locks | `test_p04_test_04_*`, `test_R4_02_*` | query 08 (INJ-04: 3 refused) | verified (local) |
| P04-TEST-05 break is not capacity | `metrics.py` `staffed_minutes` | `test_p04_test_05_*`, `test_break_is_not_capacity` | query 04 (INJ-05: 90 minutes overstated) | verified (local) |
| P04-TEST-06 open overdue | `metrics.py` | `test_p04_test_06_*` | query 03: 0 at every cutoff, 62 tickets seen overdue at an hourly sample | verified (local) |
| P04-TEST-07 clock change | `timeutil.py` | `test_p04_test_07_*`, `test_dst_crossing_shift_is_measured_in_utc_minutes` | query 04 (420-minute row), query 08 (INJ-08: 1) | verified (local) |
| P04-TEST-08 transfer resets arrival | `ingest.py`, trigger `tickets_arrival_fixed` | `test_p04_test_08_*` | query 08 (INJ-06: 3 refused) | verified (local) |
| P04-TEST-09 warm-up | `simulation.py` | `test_p04_test_09_*`, `test_warm_up_is_excluded_from_every_statistic` | memo (warm-up 120 declared) | verified (local) |
| P04-TEST-10 tail beside mean | `metrics.py` | `test_p04_test_10_*` | query 02 | verified (local) |
| P04-TEST-11 CSAT non-response | `metrics.py` | `test_p04_test_11_*` | query 07 (bounds 0.301816 to 0.952492) | verified (local) |
| P04-TEST-12 holdout intensity | `simulation.py` | `test_p04_test_12_*` | query 01, 03 (training against holdout) | verified (local) |
| P04-ART-01..10 | this directory | `tests/test_artifacts.py` | `artifacts/CHECKSUMS.txt` | verified (local); the hosted run of `test_artifacts.py` is not part of `serviceflow-ci.yml` |
| P04-REL-01..04, 09, 17, 18 (site, routes, live check, links both ways) | `web/`, `docs/program/release-manifest.json` | live-check workflow | run `40367109366` (`6a753e8`, portfolio `e3bd4a4`) | verified (hosted); the republish `e44d15d`: CI and live check pending |
| P04-REL-14..24 (portfolio entry, rollback) | `/serviceflow/project.json` on `unified-portfolio` | the portfolio build | `release-package.md` | built and published; integration and rollback documented |

## 5. Deferred and open (stated, not hidden)
* **C07 `build-shift-scenario` and C10 `export-recommendation` return 501.** There is no candidate-schedule builder and no recommendation export; the executive memo is a document, not an application export. The entry milestone (P04-GOAL-09) asks for a working export: **partial**.
* **Queue explorer, scenario comparison and survey analysis are stub screens** that say so and show no figures; their metrics are covered by the API reads, the SQL investigations and this package.
* **Break rule for a window that cuts a shift** (D-05 keeps the full overlap; a declared-interval rule over `shift_breaks` is a later decision); `shift_breaks` has no loader in `data/seed.py`.
* **Metrics default window** and the **full-population reload of C01** are lab-scale choices (D-06).
* **Hosted evidence for `43de7f8`:** local suite, SQL reconciliation and artifact checks are recorded; the hosted CI and live-check runs for the republished release are pending.
* **Not run:** Microsoft Excel (the workbook was recalculated by LibreOffice), Power BI Desktop (no `.pbix`), any DAX engine.
