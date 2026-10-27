# Pipeline Observatory (project 08)

Decision: is this dataset safe, complete and fresh enough to publish? Contracts in `docs/contracts.md`, API inventory
in `docs/api-contract.md`, site brief in `docs/web-brief.md`, generator spec in `docs/data-generator.md`. Layout and
conventions follow `apps/trustledger` and `apps/productsignal`. The PostgreSQL database is `pipeline_observatory`.

This directory holds **Mode A**, the verified backend: pure Python domain, PostgreSQL 16 schema, FastAPI. The browser product (`web/`)
is Mode B and is outside this README.

## Layout

| Path | What |
|---|---|
| `domain/pipeline_observatory/` | Pure Python (Decimal for money, Fraction for ratios, no float): `ingest.py` (entity import with rejection codes and DEPENDENT_REJECTED cascades), `classify.py` (accepted / duplicate / quarantined / deleted, checkpoint order), `fetch.py` (cursor pagination, retry-after, CURSOR_LOOP), `backfill.py` (half-open ranges), `gate.py` (fail-closed gate, pointer rule), `reconcile.py` (signed exclusions, late events, verified recovery), `metrics.py` (the full tree in the nesting of `expected.json`), `hashing.py` (the three hash kinds), `redaction.py`, `workflow_guard.py`, `scope.py` |
| `data/sql/migrations/` | `0001_schema.sql` (tables), `0002_constraints.sql` (append-only, checkpoint order, commit pairing, pointer and publication guards) |
| `data/sql/reference_metrics.sql` | the independent SQL recomputation of every metric family (never reads a stored classification) |
| `data/migrate.py`, `data/seed.py` | apply migrations (`--reset` drops this app's tables only); load an `inputs.json` idempotently through the domain's import validation |
| `api/` | FastAPI, prefix `/api/v1/pipeline-observatory`: `app.py`, `commands.py` (C01..C10), `reads.py`, `schemas.py`, `db.py`, `errors.py`, `logs.py`, `clock.py` |
| `tests/` | see "What is proven by which test" |

## How to run

```
cd apps/pipeline-observatory
../../.venv/bin/python -I tests/reference_check.py          # independent stdlib reference: ALL OK (706 checks)
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/pipeline_observatory   # the default the tests use
../../.venv/bin/python -m pytest -q                          # domain + migrations + SQL reference + API (about 90 s)
../../.venv/bin/python data/migrate.py [--reset]             # apply the migrations
../../.venv/bin/python data/seed.py tests/fixtures/golden/inputs.json --dataset-version ds-golden-1
CODE_SHA=$(git rev-parse --short HEAD) ../../.venv/bin/python -m uvicorn api.app:app --port 8808   # serve; docs at /api/v1/pipeline-observatory/docs
```

The database tests **fail** (never skip) when PostgreSQL is not reachable; `DATABASE_URL` defaults to the lab database. Every test is
deterministic: the API clock is frozen (`tests/conftest.py`, `support_db.at(...)`), ids the tests assert are named by the test, and
concurrency tests assert outcomes that hold under any interleaving (exactly one winner, a source-key accepted once).

Environment: `DATABASE_URL`, `CODE_SHA` (shown in `meta.code_sha` and stamped on runs), `PIPELINE_ENVIRONMENT` (`sandbox`, the default,
is the only value that allows C07 fault injection).

## Conventions (same as the sibling apps)

* Envelopes: commands take `{request_id, dataset_version, idempotency_key, input}` and return `{command_id, status, result, warnings, version}`;
  reads return `{data, meta, warnings}`; errors are `{error: {code, message, details: [{path, rule_id, message, context?}]}, request_id}`.
* Identity headers `X-Actor-Id` and `X-Actor-Role` (engineer | operator | admin): no actor id is 401, an unknown role or a role the command does not allow is 403, both before the body is read. Reads need no actor.
* Idempotency is bound to the actor id, the role and the payload hash (command name, `dataset_version`, input; instants compared as instants). The same key
  with the same binding returns the stored response (`Idempotent-Replay: true`); any other binding is 409 `IDEMPOTENCY_KEY_REUSED`.
  A `dataset_version` other than the current one is 409 `STALE_DATASET_VERSION` and nothing is written.
* Every instant that is a decision (`started_at` of a batch or run, `committed_at`, `published_at`, `opened_at`, `closed_at`, `verified_at`) is stamped by the server; a client that sends one gets 422 `FIELD_UNEXPECTED`.
* One transaction per command: effects, audit event and stored result commit together or not at all. Lock order: idempotency key (advisory), source rows by id, run / backfill / incident rows by id. A deadlock or serialization failure is retried (three attempts), then 409 `CONCURRENT_UPDATE`.
* No float anywhere: money and proportions are strings (6 places; minutes 4; money 2), a JSON float in a command is 422 `FLOAT_NOT_ALLOWED`, null means unknown or a zero denominator.

## Routes

| ID | Method and path | Roles | Transition and hard validation |
|---|---|---|---|
| C01 | POST `/commands/fetch-source-page` | engineer, operator, admin | cursor → staged batch (raw rows, server-computed `payload_hash`); a 429 page records `retry_after_seconds`, a retry sooner is 429 `RETRY_TOO_SOON` (+ `Retry-After`); a `next_cursor` repeated inside a `fetch_session` is 409 `CURSOR_LOOP` and stops the session |
| C02 | POST `/commands/validate-contract` | engineer, operator, admin | raw → accepted / duplicate / quarantined per row (key check before contract check, nothing dropped); a batch declaring another `schema_version` is quarantined whole (`SCHEMA_CHANGED`); `bump_schema_version` (operator, admin) is the explicit bump |
| C03 | POST `/commands/commit-batch` | engineer, operator, admin | staged → committed, ONE transaction with the checkpoint (version previous + 1: 409 `CHECKPOINT_REGRESSION` / `CHECKPOINT_GAP`); idempotent apply on `(source_id, source_key)`; optional `processing` measurement |
| C04 | POST `/commands/transform-models` | engineer, operator, admin | committed batches → `model_outputs` for a run (created if new); key and relationship tests; attempts distinct (409 `DUPLICATE_ID`, 422 `ATTEMPT_GAP`) |
| C05 | POST `/commands/run-quality-gate` | engineer, operator, admin | candidate → allowed / blocked, fail closed; blocked fails the run and opens an incident |
| C06 | POST `/commands/publish-snapshot` | operator, admin | passed candidate → publication + pointer in one transaction; refuses a run that is not `success` (409 `RUN_NOT_SUCCESSFUL`) or whose gate is blocked (409 `GATE_BLOCKED`); watermark disclosed, never in the future |
| C07 | POST `/commands/inject-fault` | operator, admin | sandbox only (403 `NOT_SANDBOX`), recorded in `fault_injections` and the audit; `duplicate_key`, `task_failure`, `crash_before_checkpoint` |
| C08 | POST `/commands/request-backfill` | engineer, operator, admin | half-open `[start_at, end_at)` over daily UTC partitions; overlap with an accepted request of the source is 409 `BACKFILL_OVERLAP` (kept in `rejected_records`), a touching range is accepted |
| C09 | POST `/commands/recover-incident` | operator, admin | closes only after a verified recovery whose reconciliation residual is 0.00 (422 `RECOVERY_NOT_VERIFIED`, `RESIDUAL_NOT_ZERO`, `RECOVERY_RUN_MISMATCH`) |
| C10 | POST `/commands/archive-evidence` | operator, admin | extension, **implemented**: finished run → manifest with a sha256 per item, its own sha256 and the retention mapping (409 `RUN_NOT_COMPLETED`, `ALREADY_ARCHIVED`) |
| R | GET `/data/{entity}` | none | stable `COLLATE "C"` ordering by the entity key, opaque `cursor`, `limit` 1..200, half-open `from`/`to` on the entity's time field, equality filters from a whitelist (422 `INVALID_FILTER`). Entities: `source_contracts`, `source_expectations`, `ingestion_batches`, `raw_records`, `accepted_records`, `quarantine_records`, `checkpoints`, `model_definitions`, `pipeline_runs`, `task_runs`, `quality_results`, `publications`, `publication_pointer`, `incidents`, `backfill_requests`, `model_outputs`, `processing_measurements`, `fetch_log`, `fault_injections`, `evidence_archives`, `rejected_records`, `audit_events`, `dataset_versions` |
| M | GET `/metrics?from=&to=&cutoff=&source_id=&group_by=` | none | the eleven metric families under `data.metrics` in the nesting of `expected.json`, `data.ingest` (import counts and rejected rows), `data.deleted_records`; half-open window, `cutoff` (default now), one source, `group_by` none or source |

## What is proven by which test

| Requirement | Test |
|---|---|
| Domain output = `expected.json` leaf for leaf (golden, rejected, empty); P08-GOLD-01/08/09 | `tests/test_golden_domain.py`, `tests/test_variants.py` |
| The backend result against the reference, through PostgreSQL and the API (P08-GOLD-06) | `test_api_golden.py` (seeded fixtures read through `GET /metrics`; the whole golden story played through the commands with the clock at the fixture's instants) |
| Independent SQL = `expected.json` for all three fixtures and = the domain on a changed population | `tests/test_sql_reference.py` |
| The three hash kinds recomputed (D-P8-10, P08-GOLD-10) | `tests/test_hashes.py` |
| P08-TEST-01 crash after the data write before the checkpoint; replay idempotent, never a ninth record | `test_api_commands.py::test_c03_crash_*`, `::test_c03_a_real_backend_kill_*`, `::test_c03_an_injected_crash_fault_*`; `test_adversarial.py::test_01`, `::test_03` (concurrent replays); `test_migrations.py` (pairing, primary key) |
| P08-TEST-02 overlapping backfills | `test_adversarial.py::test_06` (four concurrent requests, one wins), `test_api_commands.py::test_c08_*`, `test_domain_rules.py` (half-open) |
| P08-TEST-03 retry-after honoured | `test_domain_rules.py::test_p08_test_03_*` (fixture `pagination/rate_limited.json`), `test_api_commands.py::test_c01_p08_test_03_*` |
| P08-TEST-04 schema adds a required field | `test_domain_rules.py::test_p08_test_04_*`, `test_api_commands.py::test_c02_p08_test_04_*` (fixture `schema/schema_changed.json`) |
| P08-TEST-05 malformed row never vanishes | `test_domain_rules.py` (classification), `test_api_commands.py::test_c02_p08_test_05_*` |
| P08-TEST-06 green job, stale source | `test_api_commands.py::test_c05_p08_test_06_*`, `::test_c05_a_declared_freshness_target_*`, `test_golden_domain.py` (52200 s vs 42900 s) |
| P08-TEST-07 failed run never replaces the publication | `test_adversarial.py::test_07`, `test_api_commands.py::test_c06_refuses_*`, `test_migrations.py::test_the_pointer_refuses_*` |
| P08-TEST-08 delete event propagated | `test_domain_rules.py::test_p08_test_08_*` (fixture `deletes/deletes.json`), `test_api_commands.py::test_c04_a_delete_event_*` |
| P08-TEST-09 late event behind the watermark | `test_domain_rules.py::test_p08_test_09_*`, `test_api_golden.py` (REF-2001 in pub-003) |
| P08-TEST-10 pagination token repeats | `test_domain_rules.py::test_p08_test_10_*` (fixtures `cursor_loop.json`, `self_loop.json`), `test_api_commands.py::test_c01_p08_test_10_*` |
| P08-TEST-11 no secret in logs or evidence | `tests/test_redaction.py` (fixtures `logs/with_secrets.log`, `logs/clean.log`) |
| P08-TEST-12 a workflow never triggers itself | `tests/test_workflow_guard.py` (fixtures `workflows/*.yml`; the real `pipeline-observatory-ci.yml` is checked) |
| Roles, 401/403 order, idempotency binding, stale dataset, deadlock retries, 409 `CONCURRENT_UPDATE`, server-stamped instants, route inventory | `tests/test_api_protocol.py` |
| Replay storms, out-of-order checkpoints, duplicate attempts, blocked publication, actor / role mismatch, body reuse, hostile input, leaking errors | `tests/test_adversarial.py` |
| Reads: ordering, cursor, filters, windows, metrics window / cutoff / source / group | `tests/test_api_reads.py` |
| Schema: idempotent migrations, no float column, append-only evidence, checkpoint guard, commit pairing, pointer guard | `tests/test_migrations.py` |

## Assumptions beyond D-01..D-05 (proposed as D-06)

1. **Batch statuses.** The database allows `staged` (fetched, not counted), `committed`, `aborted`, `quarantined` (refused whole, SCHEMA_CHANGED). Only `committed` counts (D-P8-04). A crashed commit rolls back and leaves the batch `staged` (a dying transaction cannot write `aborted`); the fixture's `aborted` b-003 is the same state, loaded as given.
2. **Apply order.** Within a source the batches are applied in checkpoint-version order (commit order), falling back to `(started_at, batch_id)`; identical to the reference on every fixture.
3. **Sequence.** C01 stages, C02 validates (verdicts persisted as evidence in `raw_records.disposition`, nothing counted), C03 commits and re-classifies under the source lock against what is accepted NOW. C03 refuses an unvalidated batch.
4. **SCHEMA_CHANGED.** A page declares `schema_version`; a value other than the contract's quarantines the whole batch at C02, status `quarantined`, the checkpoint does not move. The expected version changes only by C02 `bump_schema_version` (operator or admin) naming the version the batch declares; the window is then fetched again. The domain mirrors it with an optional `ingestion_batches.schema_version`.
5. **Delete events.** `payload.op = delete`: `deleted` if the key is accepted and live, `duplicate` if already deleted, else quarantined `DELETE_TARGET_UNKNOWN`; an unknown `op` is quarantined `UNKNOWN_OP`. A delete removes the record from every publication that includes the deleting batch. Reconciliation `deletes` = sum of the delete rows' amounts + the amounts of the records they removed, so the residual stays 0.00. A batch's `received` then exceeds accepted + duplicate + quarantined by its deleted rows (the golden has none); `GET /metrics` lists `data.deleted_records` with the reason `DELETE_EVENT`.
6. **More quarantine reasons.** `INVALID_FIELD` (quantity not an integer or a bool, money not a 2-place decimal string, `event_ts` not an instant); a row without a key has `source_key` NULL and is quarantined `MISSING_FIELD`.
7. **Latest result per rule.** In a run's gate the latest result of a rule name (by `quality_result_id`) counts, so a transform retry replaces its earlier tests.
8. **Gate checks.** C04 records `model_keys_unique` and `model_relationships_intact` (critical). C05 records `keys_unique`, `relationships_intact`, `reconciliation_residual_zero` (critical), `freshness_within_target` (critical, only for sources with `source_contracts.freshness_target_seconds`; a source with no accepted event fails), `completeness_vs_expectation` (warning: expected minus accepted per declared partition). Allowed sets the run `success` (`finished_at` is set at publication); blocked sets it `failed` with `finished_at` and opens an incident (reason `GATE_BLOCKED`).
9. **Publication.** `source_ids` = every source contract (the dataset's sources; golden pub-001 lists refunds although only an orders batch is included, which D-P8-09 needs); `watermark` is supplied by the operator (the golden's 11:00 for pub-003 is not derivable from the batches), never after the server's now; `published_at` = the run's `finished_at` = the server's now; id `pub-<run suffix>`. The reconciliation's published total is the stored `model_outputs` total where the API built one (so a drifting table shows as a residual and C09 refuses), else the accepted records'.
10. **Runs and tasks.** C04 creates a run for a new or absent `run_id` and records `ingest` attempt 1; C04, C05, C06 add `transform`, `quality_gate`, `publish` attempts. `attempt` is the next integer; naming an existing one is 409 `DUPLICATE_ID`, skipping is 422 `ATTEMPT_GAP`.
11. **Faults.** `duplicate_key` (copies an output row), `task_failure` (fails the run, opens an incident), `crash_before_checkpoint` (one-shot, consumed on an autocommit connection so the record survives the rollback). Sandbox = `PIPELINE_ENVIRONMENT == sandbox` (default).
12. **Backfills.** Ranges are aligned to UTC midnight. Ids are `bf-NNN`, allocated past every accepted and refused id (a refused request consumes its id and is kept in `rejected_records`, which reproduces the variant: bf-001 accepted, bf-002 refused, bf-003 accepted). Publishing a backfill run verifies the partitions whose accepted records in the run's scope reach the declared expectation (> 0); status `complete` or `partial`.
13. **Recovery.** `closed_at` is the verified instant (the recovery publication's `published_at`), not the server's now; the optional `recovery_run_id` must be the first verified run.
14. **Status codes.** 409: `CHECKPOINT_REGRESSION`, `CHECKPOINT_GAP`, `CURSOR_LOOP`, `BACKFILL_OVERLAP`, `DUPLICATE_ID`, state conflicts; 429 `RETRY_TOO_SOON` with `Retry-After`; 403 `NOT_SANDBOX`; 500 `INJECTED_CRASH` (an injected crash is a crash); other rule failures 422 `VALIDATION_FAILED` with the rule id.
15. **Sources are synthetic.** C01 takes the page the fetcher received (`status` 200 or 429, records, `next_cursor`, `retry_after_seconds`, `schema_version`); the app calls no external source. Retry-after is enforced per `(source, cursor)`; a cursor loop is detected inside a `fetch_session` (a replay of a window with a new session is not a loop).
16. **`/metrics` scope.** `from`/`to` narrow batches and runs by `started_at`, publications by `published_at`, incidents by `opened_at`, backfills by `start_at`, expectations by partition day; `cutoff` also drops a batch committed at or after it; rejected import rows are never narrowed.
17. **Dataset version.** Only the loader writes `dataset_versions`; commands never bump it (as the siblings). A database with no row has nothing to be stale against.
18. **Database guards.** Besides keys and checks: `accepted_records` primary key `(source_id, source_key)`; checkpoint guard trigger (previous + 1); deferred pairing triggers (a committed batch has its checkpoint, a checkpoint's batch is committed); append-only triggers on evidence tables; `po_gate_allowed` and the publication / pointer guards (a pointer moves only to a successful run with an allowed gate).
19. **Measurement.** C03 accepts an optional `processing` object (`measured_seconds`, `hardware`, `cache_state`); the latest measurement feeds `processing_rate`. `measured_seconds` is `NUMERIC` without a scale so `"12"` reads back as `"12"`.
20. **Locks.** Source, run and batch rows are locked `FOR NO KEY UPDATE` so a command can still write the audit / fault / rejected rows on its autocommit connection (which reference the source) without waiting on itself.

## Not implemented / known gaps

* No `data/sql/seed_golden.sql`: the loader is `data/seed.py` (same rules as the API, idempotent). The independent SQL reference does not model delete events (the domain tests do) and `GET /metrics` has no `group_by` other than `none` and `source`.
* The web product (Mode B), the CI workflow and `docs/contracts.md` are untouched. YAML is not parsed (no PyYAML in `requirements.txt`): `workflow_guard.py` reads workflow text.
* No real network fetching, scheduler or retention job: C01 records what the fetcher received, C10 stores the manifest in the database (the release asset is a CI step).
