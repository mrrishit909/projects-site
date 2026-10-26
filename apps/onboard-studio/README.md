# Onboard Studio (Mode A backend)

Python domain + PostgreSQL + FastAPI for the Business Data Lab project 02. Synthetic data only. Contract:
`docs/contracts.md` (v1, D-01..D-05); routes: `docs/api-contract.md`. Independent of Revenue Atlas (no shared code).

| Path | What it is |
|---|---|
| `domain/onboard_studio/` | Pure standard-library domain. `calendar` (half-open working intervals, holidays subtracted), `workflow` (Kahn publish check, readiness, approval and pause checks, definition hash), `ingest` (`validate_batch`, dependent rejection), `metrics` (`compute_metrics`, `group_metrics`), `pipeline` (`run_pipeline(inputs, state)`) |
| `data/` | `migrate.py`, `seed.py`, `migrations/0001_schema.sql`, `0002_constraints.sql`, `sql/reference_metrics.sql` (independent SQL recomputation), see `data/README.md` |
| `api/` | FastAPI app, prefix `/api/v1/onboard-studio` |
| `tests/` | golden, variants, rules, migrations, SQL reference, API commands and reads, adversarial (`test_p02_test_NN_*`) |

## Run

    python -m venv .venv && .venv/bin/pip install -r requirements.txt
    export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/onboard_studio
    python data/migrate.py                       # idempotent; --reset drops this project's tables first
    python data/seed.py tests/fixtures/golden/inputs.json
    python -m pytest -q                          # database tests skip cleanly when DATABASE_URL is unset
    python -I tests/reference_check.py           # the independent oracle (never edited)
    uvicorn api.app:create_app --factory

## Rules in one place

* Hours are decimal strings at 4 dp, rates at 6 dp, both ROUND_HALF_UP; durations are never negative.
* Business time = overlap of `[start, end)` with the calendar's working intervals minus holiday intervals; a holiday
  on a weekend subtracts nothing. Active = business minus the business overlap of pause-eligible waiting intervals
  (clipped to the case span and merged). A pause outside every working interval contributes 0 and is flagged
  `PAUSE_OUTSIDE_WORKING_INTERVAL` (a warning on commands and metrics, `flags` in the pipeline result).
* Ingest rejects a case with its child rows for `WORKFLOW_VERSION_NOT_PUBLISHED`, `DEPENDENCY_CYCLE`,
  `SELF_APPROVAL`, `STEP_NOT_READY`, `MISSING_REQUIRED_DOCUMENT`, `CASE_ALREADY_COMPLETE`,
  `PAUSE_REASON_NOT_CONFIGURED` (an interval with `pause_requested: true`), `ORPHAN_REFERENCE`; `DECISION_CONFLICT`
  rejects only the later approval. Priority is in that order. Raw rows are kept in `rejected_records`.

## API

Commands: `{request_id, dataset_version, idempotency_key, input}` with `X-Actor-Id` and `X-Actor-Role`
(`ops|reviewer|admin`; 401 without id, 403 for another role). Atomic with its audit event; the same key and payload
replays (`Idempotent-Replay: true`), the same key with another payload is 409.

| Command | Result / errors |
|---|---|
| `create-case` (C01) | binds a published version; 422 `WORKFLOW_VERSION_NOT_PUBLISHED`; 409 `CASE_EXISTS` |
| `submit-document` (C02), `resubmit-document` (C04) | new `document_versions` row, synthetic `sha256:` placeholder; resubmit only after a rejection |
| `reject-submission` (C03) | reason required; `accept-document` (addition) records an acceptance; both are rows of `document_reviews` |
| `unlock-dependent-step` (C05) | 422 `STEP_NOT_READY` |
| `approve-step` (C06) | role must equal `role_key` (403 `ROLE_MISMATCH`), reviewer not an assignee (403 `SELF_APPROVAL`), 409 `DECISION_CONFLICT` / `STALE_VERSION` |
| `pause-sla` (C08) | 422 `PAUSE_REASON_NOT_CONFIGURED` |
| `complete-case` (C09) | 422 `MISSING_REQUIRED_DOCUMENT`; 409 `CASE_ALREADY_COMPLETE`; `reopen-case` is always 409 `CASE_REOPEN_FORBIDDEN` |
| `publish-workflow-version` (P) | admin only; 422 `DEPENDENCY_CYCLE`; 409 `ALREADY_PUBLISHED` |
| `reassign-work` (C07), `migrate-workflow` (C10) | **501 `NOT_IMPLEMENTED`** (extension milestone) |

Reads: `GET /data/{entity}?limit&cursor&from&to&<column>=` (limit <= 200, cursor paging by key, unknown filter 422
`INVALID_FILTER`, reversed window 422 `INVALID_WINDOW`) and `GET /metrics?from&to&cutoff&state&group_by`
(`from/to` half-open on `opened_at`; `cutoff` comma-separated, default now; `state=pause_not_eligible` empties the
pause policy, `pause_eligible` and no state keep each SLA rule's own; `group_by=organization|segment|region|workflow_version`).
