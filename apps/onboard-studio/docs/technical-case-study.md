# Technical case study: Onboard Studio (P02-ART-09)

A synthetic workflow-analytics product built around one question: which onboarding workflow should be adopted and how should exceptions be handled (P02-GOAL-01). It is a **business-data lab** project, not a customer system: all data is generated, there is no real document storage, e-signature or adoption data (P02-DOMAIN-06), and no result describes a real business.

## Architecture
```mermaid
flowchart LR
  G[generate.py seed 20261026] --> S[(web/public/data snapshot JSON, 740 cases)]
  S --> TS[Mode B: TypeScript domain in the browser, case actions simulated in memory]
  S --> SEED[data/seed.py via validate_batch]
  SEED --> PG[(PostgreSQL 16, two plain-SQL migrations, 21 tables)]
  API[FastAPI commands C01-C09 + P + reads] --> PG
  PY[Python domain: calendar, workflow, ingest, metrics, pipeline] --> API
  PY --> SEED
  PG --> REF[reference_metrics.sql: interval-overlap arithmetic]
  PG --> AN[analysis SQL 00-09: multirange arithmetic]
  ORACLE[tests/reference_check.py: stdlib oracle over the golden fixture] -.-> PY
  TS --> PAGES[GitHub Pages: labs/onboard-studio]
```
* **Mode A (verified on hosted runners):** Python domain (`domain/onboard_studio`), PostgreSQL migrations (`data/migrations`), FastAPI commands and reads (`api/`), prefix `/api/v1/onboard-studio`.
* **Mode B (public):** the same contract in TypeScript (`web/src/domain`) over the published snapshot; every case action is a browser-memory simulation and a reload restores the snapshot. Static hosting only; the backend is not deployed.
* **One contract** (`docs/contracts.md`, v1, D-01..D-06) with a **golden fixture** whose answers are hand-derived (`tests/fixtures/golden/CALCULATION.md`: calendar 66 h, business 2 h, paused 65 h, active 1 h or 2 h).
* **Five independent implementations of the durations:** the Python domain, the TypeScript domain, `data/sql/reference_metrics.sql` (overlap arithmetic), the analysis SQL (`00_case_facts.sql`, multiranges) and the stdlib oracle `tests/reference_check.py`; plus the workbook's spreadsheet formulas for the golden case. They check each other (below).

## Tradeoffs
* **Exact integer and rational durations.** Time is half-open intervals in UTC; Python carries seconds as `Fraction` and rounds once, in `d4` and `d6`, ROUND_HALF_UP; TypeScript uses integer milliseconds; PostgreSQL sums exact numeric seconds; the BI design loads integer seconds. Cost: more code than float arithmetic and a rule that nothing rounds early.
  Benefit: a mean can land exactly on a rounding tie and still round correctly, and three implementations agree to the fourth decimal.
* **The half-up tie defect, found by the TypeScript build.** Building the browser domain meant a Python-versus-TypeScript cross-check. It found that the Python reference accumulated Decimal division error per case: a mean whose exact value is 1.31125 came out as 1.3112 instead of 1.3113.
  The fix (commit `2a60c40`) is exact `Fraction` hours in `timeutil.py`, converted to `Decimal` once; the ledger records the cross-check afterwards at 5,112 cells with 0 differences, and 279 tests passing. The independent review's Q-03 is the same family of defect in `reference_metrics.sql`
  (it divides per case before averaging); it is not yet fixed (open gaps).
* **Append-only documents with a reviews table.** A resubmission is a new `document_versions` row and a trigger forbids UPDATE and DELETE, so the prior version can never be overwritten (P02-TEST-06). Review decisions are rows of `document_reviews`, also append-only, and the effective status is the latest review.
  Cost: the status of a document is a lookup, not a column read (the commands and reads use `COALESCE` over the latest review), and the seeded snapshot carries the final status in `document_versions.review_status` instead (the review table is empty there). Benefit: history is never lost and no application path can edit it.
* **Immutable published versions, enforced by triggers.** A published workflow version, its steps, dependencies and required documents cannot change (`definition_hash` is the sha256 of the ordered definition), and a case keeps its version for life; the only way to change a workflow is a new version. Cost: no hot fixes; migration of open cases is an extension command (C10, 501).
  Benefit: "which version did this case run under" is never ambiguous, which is what makes the version comparison meaningful.
* **Reject whole cases, not rows.** A case with a missing required document, a wrong pause reason or a self-approval is rejected at ingest with all of its child rows (one reason, raw rows kept in `rejected_records`), except `DECISION_CONFLICT`, which rejects only the later approval. Cost: 7 of 740 generated cases leave the population.
  Benefit: no half-case can reach a metric, and every refusal is countable (query 08 reconciles to the injection manifest exactly).
* **Different methods for the independent checks.** The analysis SQL uses multiranges (`range_agg`, intersection, `unnest`) where the reference uses explicit overlap arithmetic, so one wrong idea is unlikely to be shared. Cost: two SQL idioms to maintain. Benefit: on the snapshot they agree to 4 decimals on population means and the Python domain agrees with the SQL on each of the 712 completed cases (`sql-analysis.md`).
* **Idempotent commands with an audit written in the same transaction** (section below). Cost: a command table and an advisory lock per key. Benefit: a retry is safe and a failed command leaves no trace.

## Recovery behaviour (observed in tests)
| Situation | Behaviour | Test |
|---|---|---|
| Create a case on an unpublished version | 422 `WORKFLOW_VERSION_NOT_PUBLISHED`; no row written | `test_create_case_binds_only_a_published_version` |
| Complete a case with a required document missing or only rejected | 422 `MISSING_REQUIRED_DOCUMENT` with the missing steps and types in `details[].context`; nothing written | `test_p02_test_01_*` |
| Second decision on the same step version | 409 `DECISION_CONFLICT` (the unique `(step_instance_id, version_number)`); a decision carrying the new version is accepted; stale expected version is 409 `STALE_VERSION` | `test_p02_test_02_*`, `test_approve_step_stale_version_and_unknown_step` |
| Pause for a reason outside the policy | 422 `PAUSE_REASON_NOT_CONFIGURED`; a pause outside working time is accepted, contributes 0 business hours and returns a `PAUSE_OUTSIDE_WORKING_INTERVAL` warning | `test_p02_test_03_*`, `test_pause_sla_unconfigured_reason_is_422` |
| Publish a version with a dependency cycle (Kahn) | 422 `DEPENDENCY_CYCLE`; publishing a published version is 409 `ALREADY_PUBLISHED`; an UPDATE of a published definition is refused by the trigger | `test_p02_test_05_*`, `test_publish_workflow_version_then_it_is_immutable` |
| Resubmit over an accepted document, or UPDATE a document row | refused (`NOT_IN_CHANGES_REQUESTED`; append-only trigger); the prior version is intact | `test_p02_test_06_*`, `test_resubmit_requires_a_rejection_and_keeps_the_prior_version` |
| Approve as the step's own (even past) assignee, or with the wrong role | 403 `SELF_APPROVAL` / `ROLE_MISMATCH` | `test_p02_test_10_*`, `test_approve_step_role_must_match_the_step` |
| Complete a case earlier than work already recorded on it | 422 `COMPLETION_BEFORE_RECORDED_WORK`; open waiting is closed at the completion instant; a pause before the case opened is 422 `PAUSE_OUTSIDE_CASE_SPAN` (D-07) | `test_q01_*` |
| Two commands race on one case (approve vs reject) | one lock order (case, then step); a deadlock is retried up to 3 times, then 409 `CONCURRENT_UPDATE`, never 500 (D-08) | `test_q02_*` |
| Same idempotency key from another actor, or the same instant spelled `+00:00` instead of `Z` | another actor: 409 `IDEMPOTENCY_KEY_REUSED`; an equal instant is the same payload and replays | `test_q06_*` |
| Publish with an unknown calendar; a calendar without working intervals | 422 `CALENDAR_UNKNOWN`; the case is unevaluated and counted in `sla_unevaluated_cases` (D-09) | `test_q05_*` |
| Reopen a completed case | 409 `CASE_REOPEN_FORBIDDEN`; a correction opens a linked new case | `test_p02_test_11_*` |
| Reassign work (C07) or migrate a workflow (C10) | 501 `NOT_IMPLEMENTED` (extension milestone) | `test_extension_commands_are_501_not_implemented` |
| Same idempotency key and payload | the stored result is returned with `Idempotent-Replay: true` | `test_same_key_same_payload_replays_the_stored_response` |
| Same idempotency key, different payload | 409 `IDEMPOTENCY_KEY_REUSED` | `test_same_key_different_payload_is_409` |
| Any failed command | no partial write and no audit row: the handler, the `audit_events` row and the `command_results` row are one transaction, serialised per key with `pg_advisory_xact_lock` | `test_atomicity_a_failed_command_leaves_no_trace`, `test_failed_command_stores_no_result_so_the_key_can_be_retried` |
| A database rule violated inside a command (trigger, unique key) | mapped to a 409 with a stable code (`DECISION_CONFLICT`, `CASE_EXISTS`, `INTEGRITY_RULE`), never a 500 | `api/commands.py` `execute` |

Error envelope: `{error: {code, message, details[]}, request_id}`; no stack traces or connection strings leave the server. Commands need `X-Actor-Id` and `X-Actor-Role` (`ops`, `reviewer`, `admin`): 401 without an id, 403 for another role.

## Reproducible setup
```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt            # Mode A; add -r requirements-artifacts.txt for the workbook
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<scratch db>
python data/migrate.py && python data/seed.py tests/fixtures/golden/inputs.json
python data/generate.py --seed 20261026 --out web/public/data                 # deterministic: same dataset_hash 3c20d296...2bc6a
python -I tests/reference_check.py                                           # stdlib oracle
python -m pytest -q                                                          # database tests skip cleanly without DATABASE_URL
(cd web && npm ci && npm run check && npm run e2e)                           # Mode B: typecheck + 150 golden checks; Playwright
# artifacts
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py && ../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json
../../.venv/bin/python artifacts/build_workbook.py --recalc && ../../.venv/bin/python -m pytest -q tests/test_artifacts.py
```
Tests that reset the schema must run against a scratch database, never one that holds work in progress (`tests/support_db.py` drops the project's tables).

## Measured evidence
Hosted runs and ledger entries (`docs/program/verification-ledger.json`):

| Evidence | Result | Code | Run |
|---|---|---|---|
| Mode A CI: reference check ALL OK; 256 tests with `postgres:16` | success | `0a24202` | https://github.com/mrrishit909/projects-site/actions/runs/40322386220 |
| Generator determinism, injected defects detected, designed relationships; 279 tests after the rounding fix | identical hash `3c20d296...2bc6a` on two runs; v2/v1 0.64; enterprise rework 0.290 against 0.172; `reg-north` 59.1 h | `2a60c40` | https://github.com/mrrishit909/projects-site/actions/runs/40326858638 |
| Mode A (279 tests) and Mode B (150 TypeScript golden checks, 35 Playwright tests at 360/768/1280/1920 and 200 % zoom, 0 overflow) | both jobs success | `eac63b9` | https://github.com/mrrishit909/projects-site/actions/runs/40328738179 |
| Live site: 200 on every route, served hash equals the manifest | success | `eac63b9` | https://github.com/mrrishit909/projects-site/actions/runs/40329082960 |
| Portfolio case study links to the site and the site links back | success | `a18f12e` | https://github.com/mrrishit909/projects-site/actions/runs/40329407956 |

Measured in this artifact pass (local, 2026-10-26, on a scratch PostgreSQL 16 database): the full existing suite, 279 passed (`pytest -q`, 109 s); `python3 -I tests/reference_check.py` ALL OK; `npm run check` in `web/` (typecheck + golden) ALL OK, 150 checks;
`tests/test_artifacts.py` (the artifact package, below); the ten analysis SQL files and the two BI export queries run with `psql -v ON_ERROR_STOP=1` (exit 0); `run_all.py` exit 0 with 37 reconciliation rows all equal, including the golden case's business hours (2.0000 from the analysis SQL, `reference_metrics.sql`
and the Python domain) and each of the 712 completed cases against the domain; the workbook recalculated by LibreOffice 24.2.7.2 headless with its pause switch flipped to prove the formulas are live. Excel and Power BI Desktop were not run; no `.pbix` exists.

## Open gaps
* **Reviewer findings Q-01..Q-07** (ledger entry 2026-10-26T13:25:24Z, status **failed**, fix task T-02-07 pending): Q-01 `complete-case` accepts an `occurred_at` before the recorded approvals and leaves a pause open on a completed case, where ingest would reject the same rows (HIGH); Q-02 `approve-step` locks step then case while reject, submit and resubmit lock case then step: `DeadlockDetected` surfaced as a 500 in 9 of 25 races (MEDIUM);
  Q-03 `reference_metrics.sql` divides per case before averaging and does not merge overlapping waits (LOW; the analysis here is unaffected, `sql-analysis.md`); suspected: Q-04 a document accepted on a prior version counts for completion, Q-05 an empty calendar yields zero durations and SLA "met" and `sla_rules.calendar_id` has no foreign key, Q-06 idempotent replay is not bound to the actor and `+00:00` against `Z` hash differently, Q-07 sub-millisecond timestamps diverge between Python and TypeScript.
  None is fixed in this package.
* **Extension commands and tests:** C07 reassign-work and C10 migrate-workflow return 501; P02-TEST-04, 07 and 12 are not checked, and P02-TEST-08 (weekend holiday) is covered at domain level only (the snapshot contains two weekend holidays that subtract nothing).
* **Web:** the intake, documents, bottlenecks, versions and simulation routes are stubs; unknown-route server status is not asserted; the keyboard pass is limited to the e2e tests (ledger, A-016).
* **Scale deviation:** 740 cases and 12,699 events (specification: about 900 and 15,000) to stay under the 5 MB limit of the published files; `document_accepted` events were dropped (acceptance lives on `document_versions`).
* **Artifacts:** the workbook covers the golden case only; no Excel run; the Power BI model is a design with no `.pbix`; the analysis is one seed with no confidence intervals beyond the rough one in `executive-memo.md`.
