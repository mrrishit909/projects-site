# RetentionLab (project 10)

Decision: which accounts deserve limited retention attention under uncertain intervention value? Contracts in `docs/contracts.md`
(D-01..D-05; D-05 adopts the golden fixture's decisions D-P10-01..19), API inventory in `docs/api-contract.md`, site brief in
`docs/web-brief.md`, generator spec in `docs/data-generator.md`. Layout and conventions follow `apps/trustledger`. The PostgreSQL database
is `retentionlab`. Everything is synthetic; the economics are hypothetical; no claim of real retention improvement is made.

This README covers the **Mode A backend slice**: pure Python domain, PostgreSQL 16 schema, FastAPI. The static site (Mode B, `web/`) is not
part of it.

## Run

```bash
cd apps/retentionlab
../../.venv/bin/python -I tests/reference_check.py                       # stdlib reference for the golden fixture: ALL OK (1823 checks)
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/retentionlab     # CI: postgres:16 service, same credentials
../../.venv/bin/python data/migrate.py                                   # from empty; a second run applies nothing  (--reset drops this project's tables)
../../.venv/bin/python data/seed.py tests/fixtures/golden/inputs.json --dataset-version ds-golden-1
../../.venv/bin/python -m uvicorn --factory api.app:create_app --port 8010
../../.venv/bin/python -m pytest -q -ra                                  # everything; no test is skipped when DATABASE_URL is set
```

Tests skip only when `DATABASE_URL` is unset (the pure-domain tests still run). The suite freezes the API clock (`tests/conftest.py`,
`2026-05-01T12:00:00Z`), so nothing depends on the date it runs.

## Layout

| Path | What |
|---|---|
| `domain/retentionlab/` | Pure Python, standard library only. `ingest` (D-P10-15 validation), `world` (eligibility, point-in-time features, arrived-late, labels with censoring), `split` (chronological split, label-window and group purge), `rules` (the refusal codes), `fitting` (preprocessing, the three models, Platt; floats only inside the fitting loops), `metrics` (every D-03 metric, exact), `pipeline.evaluate` (the whole fixture shape) |
| `data/migrations/0001_schema.sql`, `0002_constraints.sql` | The 12 entities + `feature_registry`, `split_assignments`, `scoring_publications`, `label_versions`, `feature_versions`, `model_preprocessing`, `model_coefficients`, `calibration_maps` (NUMERIC(20,6)), `audit_events`, `command_results`, `rejected_records`, `dataset_versions`; append-only triggers; the availability, citation, run-frozen and label-maturity triggers |
| `data/migrate.py`, `data/seed.py`, `data/artefacts.py` | Migrator (idempotent, checksummed), loader (`ON CONFLICT DO NOTHING`, rejected rows kept raw), numeric projection of a run's config |
| `data/sql/reference_metrics.sql` | INDEPENDENT SQL recomputation of the metrics of one cutoff set from the facts |
| `api/` | FastAPI: `app` (routes, identity), `commands` (C01..C10, idempotency, locking, retries), `reads` (entities, metrics), `schemas`, `errors`, `db`, `clock` |
| `tests/` | See the proof table; fixtures in `tests/fixtures/golden/` (do not edit) and `tests/fixtures/adversarial/` |

## Routes (prefix `/api/v1/retentionlab`)

Same envelopes as the other apps. Command request `{request_id, dataset_version, idempotency_key, input}`; response
`{command_id, status, result, warnings, version}`; error `{error: {code, message, details[{path, rule_id, message, context}]}, request_id}`;
read `{data, meta{dataset_version, code_sha, contract_version, generated_at, applied_filters, total_count, next_cursor, exclusions}, warnings}`.
Identity headers `X-Actor-Id` (401 when missing) and `X-Actor-Role` in `scientist | analyst | admin` (403 otherwise or when not allowed).

| ID | Route | Roles | Result in one line |
|---|---|---|---|
| C01 | `POST /commands/build-point-in-time-features` | scientist, admin | feature rows of a cutoff set; arrived-late counted; `availability_proof`; refuses POST_OUTCOME_FIELD, LATENT_TRUTH, ID_FEATURE, UNKNOWN_FEATURE |
| C02 | `POST /commands/define-label` | scientist, admin | labels with censoring (null, never false); a censored label matures once |
| C03 | `POST /commands/split-evaluation` | scientist, admin | creates a run with boundaries; split + label-window and group purge counts |
| C04 | `POST /commands/fit-preprocessing` | scientist, admin | median / standardisation / missing indicators fitted on retained training rows; else LEAKAGE |
| C05 | `POST /commands/train-baseline` | scientist, admin | random, rule and logistic (frozen strings); validation comparison |
| C06 | `POST /commands/calibrate-model` | scientist, admin | Platt on validation rows; CALIBRATION_ON_FIT_ROWS / LEAKAGE |
| C07 | `POST /commands/score-accounts` | scientist, admin | predictions citing run, config_hash, feature_version, label_version; publication |
| C08 | `POST /commands/prioritize-outreach` | scientist, analyst, admin | capacity-limited DRAFT queue; CAPACITY_EXCEEDS_POPULATION; RISK_NOT_RESPONSIVENESS; nothing is sent |
| C09 | `POST /commands/simulate-economics` | scientist, analyst, admin | contact budget and expected value, labelled hypothetical |
| C10 | `POST /commands/monitor-refresh` | scientist, admin | drift (PSI diagnostic), missingness, freshness, performance only on mature rows with the immature count |
| R | `GET /data/{entity}` | none | 12 entities + `feature_registry`, `split_assignments`, `scoring_publications` (+ `audit_events`, `rejected_records`, `dataset_versions`); `limit` 1..200, opaque `cursor`, `from`/`to` half-open, whitelisted equality filters |
| M | `GET /metrics` | none | `training_run_id`, `prediction_at` / `cutoff_id` (comma lists) or `from`/`to`, `as_of`, `scenario_id`, `model`, `reference_prediction_at` |

Any other `POST /commands/{x}` is 404 `UNSUPPORTED_ACTION`. There is no route that sends anything.

## What is proven, and by which test

| Claim | Test |
|---|---|
| Domain output equals `expected.json` leaf for leaf (912 / 480 / 334 leaves), including `consistency`; no float | `test_golden_domain.py`, `test_variants.py` |
| Reference calculation is independent and agrees (1,823 checks) | `tests/reference_check.py` |
| Fitting is deterministic, beats the rule and random baselines on AP and Brier on a separable set, frozen strings byte-stable across runs; preprocessing training-only; Platt on validation only | `test_fitting.py` |
| Each rule below the HTTP layer (registry codes, late arrival, window edges, eligibility, censoring, label/group purge, ties, bins, PSI floor, economics rounding) | `test_rules.py` |
| Migrations from empty and idempotent; append-only; availability, citation, frozen-run, label-maturity triggers; NUMERIC(20,6); no float column | `test_migrations.py` |
| SQL recomputation equals `expected.json` (all sets, both variants) and the domain on a fitted synthetic world, model-selectable | `test_sql_reference.py` (AP and PSI are NOT recomputed in SQL: Python only) |
| Commands: 401/403/404/409/422, malformed, stale version, repeated, unsupported; idempotency bound to actor, role, dataset_version; server-stamped instants; lock order, deadlock retry then 409 CONCURRENT_UPDATE, concurrent identical requests run once; draft-only queue; hypothetical economics; monitor with immature labels | `test_api_commands.py` |
| Reads: no records, one, multiple pages, invalid filter/cursor/window, stable order, evidence reconciliation, the metrics endpoint equals `expected.json`, `as_of`, K refusal | `test_api_reads.py` |
| P10-TEST-01..12, DETECT and RECOVER from their smallest fixtures (`tests/fixtures/adversarial/p10-test-NN.json`); interruption leaves nothing; hostile input; role boundaries | `test_adversarial.py` |

## Numbered assumptions beyond D-01..D-05 (for D-06)

1. **Roles.** C01-C07 and C10: scientist, admin. C08, C09: scientist, analyst, admin (`docs/api-contract.md`). Role and actor id are header-asserted, as in the other apps; the role is part of the idempotency binding.
2. **Clock and `as_of`.** A command's `as_of` is the server clock. A report's `as_of` defaults to it and is a snapshot: events with `available_at`, predictions with `scored_at`, and publications with `published_at` later than `as_of` are invisible. Maturity is `label_end <= as_of`.
3. **Which instants a client supplies.** Never a decision instant: a run's and a scenario's `created_at`, `scored_at`, `published_at`, an outreach row's `created_at` are stamped by the server (a client field of that name is 422 FIELD_UNEXPECTED). Analysis parameters are the client's: the cutoff set `prediction_at`, the split boundaries, `reference_prediction_at`.
4. **Cutoffs pre-exist.** C01 does not create `prediction_cutoffs`; it stores a feature row for each *eligible* cutoff of the set with all four registry features. `fields` is validated against the registry and echoed.
5. **Business rule.** Flagged iff `usage_events_30d == 0` or `high_severity_support_90d >= 1` (an "open" case is a high-severity support event in the 90-day window; there is no case-closure event). The rule's two outputs are the observed churn rates of flagged and unflagged retained, mature training rows (an empty group takes the overall rate), so its Brier score is comparable.
6. **Random baseline.** `p = (first 12 hex digits of SHA-256("<seed>:<cutoff_id>") mod 1,000,001) / 1,000,000`: seeded, stateless, order-independent.
7. **Preprocessing.** Median, mean and population standard deviation computed exactly (`Fraction`, `Decimal.sqrt` at 50 digits) and frozen to 6 places; a zero deviation is replaced by 1; imputation uses the frozen median; a missing indicator exists only for a nullable feature that was missing in the fit rows. The fit's row ids are hashed into the config (`fit_rows_sha256`).
8. **Logistic regression.** Objective: mean log-loss + (l2 / 2n) x sum(w^2), intercept unpenalised; zero start; full batch in cutoff-id order; defaults `l2` 1.000000, learning rate 0.100000, 500 iterations. `sigmoid` uses `det_exp` (Taylor + squaring, only `+ - * /`), so the frozen strings do not depend on the platform's libm.
9. **Platt.** `p' = sigmoid(a x logit(p) + b)`, from the identity, 500 iterations at 0.1; `logit` by `Decimal.ln` with `p` clamped to [1e-6, 1 - 1e-6]; fitted on the *uncalibrated* logistic probabilities of the retained, mature validation rows. Only the logistic model is calibrated.
10. **Which rows train.** Retained train rows that have a stored feature row (C04) and a stored mature label (C05, C06); censored rows are excluded and counted.
11. **Run configuration.** `training_runs.config` holds the strings (preprocessing, models, calibration) and `config_hash` is recomputed on every C04-C06 change; the first prediction freezes the run (trigger RUN_FROZEN, HTTP 409). C04 resets models and calibration; C05 resets calibration. The NUMERIC tables are a projection of the config.
12. **Scoring.** `predictions.model_name` (default `logistic_regression`) and `scoring_publications.model_name`; unique per (run, cutoff, model). C07 needs stored feature rows (422 FEATURES_NOT_BUILT) and scores only the missing accounts on a repeat; a publication row is written per call that scored something (`sp-<run>-<model>-<yyyymmdd>-<n>`), status derived (completed iff every eligible account has a prediction).
13. **Scenarios and the queue.** C08/C09 take a stored `scenario_id` or an inline `scenario`; an inline scenario is created if new and immutable afterwards (SCENARIO_IMMUTABLE; an edit is a new id). `assumed_effect` in [0, 1] (ASSUMED_EFFECT_OUT_OF_RANGE); `selected_on: "test"` is THRESHOLD_ON_TEST (declared provenance; the product cannot detect a client that lies). The queue is the top K of the *scored eligible* rows (censored ones included), one queue per scenario (QUEUE_EXISTS), `basis` must be `risk_ranking` (RISK_NOT_RESPONSIVENESS), status `draft`, `sent` 0.
14. **HTTP mapping.** Unknown run, scenario, cutoff set: 404 NOT_FOUND with rule `UNKNOWN_*`. Domain refusals: 422 VALIDATION_FAILED, `details[].rule_id` = the code, offending items in `details[].context.offending`. RUN_FROZEN: 409 INVALID_STATE; QUEUE_EXISTS and SCENARIO_IMMUTABLE: 409 CONFLICT. A leakage/threshold/capacity/responsiveness refusal is written to `audit_events` (`<command>-refused`) in its own transaction.
15. **`GET /metrics`.** Sets default to every set; `training_run_id` defaults to the only run (422 TRAINING_RUN_REQUIRED if several; no run: empty predictions); the K refusal (422 CAPACITY_EXCEEDS_POPULATION) applies to a set with evaluated rows only (D-P10-04); drift only with `reference_prediction_at`, on `usage_events_30d`, bins [0,1) [1,3) [3,inf), floor 0.0001, threshold 0.2. The response also carries the `consistency` block (stored derived rows versus rebuilt).
16. **Number formats on reads.** Entity reads return NUMERIC(20,6) as stored (`"49.000000"`); the metrics payload uses the D-04 formats (money 2 places).
17. **Dataset version.** `seed.py` records a `dataset_versions` row (`ds-<hash12>` unless named); commands carry the current one (409 STALE_DATASET_VERSION otherwise); an empty database has nothing to be stale against.
18. **Labels.** Append-only except one transition: a censored label (`churned` NULL, `mature` false) becomes mature with a known outcome, once (trigger LABEL_IMMUTABLE otherwise).
19. **C10 stores nothing** beyond its audit event and idempotent result; there is no monitoring history table.
20. **Unit of idempotency payload.** Instants under `*_at` / `*_end` keys are hashed as the UTC instant they name.

## Not implemented / open gaps

* The data generator of `docs/data-generator.md` (2,400 accounts, injected defects, manifest) is not part of this slice; the tests use the golden fixture, the 14-account kit of the adversarial fixtures and a 64-account synthetic world (`tests/worlds.py`).
* P10-DOMAIN-06: no randomised-experiment design is implemented or simulated; `experiment_id` on C09 is recorded as a claim only (`supported_by_randomised_experiment` is always false).
* The test set is read once by the *final evaluation* (`GET /metrics`), but nothing prevents a client from reading it repeatedly or from lying about where K was chosen; the refusal is a provenance check, not a proof.
* Cursors are bound to the entity's key shape, not to a `dataset_version`: an "expired dataset" cursor is not rejected.
* No hyper-parameter search, no revisions of published results (R27), no multi-refresh monitoring history, no non-UTC zones.
* AP and PSI have no SQL recomputation (see the proof table); the independent check of PSI is the stdlib reference.
* `load_data` reads every row of the event tables for each command and metrics call; fine for the fixtures and the demo profile, not benchmarked at 10,000 accounts.
* Authentication is header-asserted identity, as in the sibling apps (no real auth backend); nothing here may be claimed as access-control verification beyond the direct request tests.
