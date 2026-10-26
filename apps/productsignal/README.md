# ProductSignal (project 06) — backend (Mode A: Python domain + PostgreSQL + FastAPI)

Decision: should an onboarding change ship, stop, or receive more investigation? Contracts in `docs/contracts.md` (D-01..D-05; D-05 adopts the
fixture's 25 decisions, full text in `tests/fixtures/golden/CALCULATION.md`), API inventory in `docs/api-contract.md`, site brief in
`docs/web-brief.md`, generator spec in `docs/data-generator.md`. Layout and conventions follow `apps/serviceflow` and `apps/invoicebridge`. The domain
is standard library only (Fraction and Decimal, no float in any published figure); the API adds FastAPI, pydantic and psycopg. Nothing imports
another lab app. The Mode B web mirror (`web/`) is separate.

```
domain/productsignal/  contract, errors, timeutil, stats, models, events, ingest, metrics, pipeline
data/                  migrate.py, seed.py, migrations/0001_schema.sql, 0002_constraints.sql, sql/reference_metrics.sql, sql/t_quantiles.csv   (see data/README.md)
api/                   app, clock, db, schemas, commands, reads, errors     (prefix /api/v1/productsignal)
tests/                 golden (domain), variants, rules, migrations, SQL reference, API commands, API reads, adversarial; reference_check.py (stdlib only)
```

## Run

```
pip install -r requirements.txt
python -I tests/reference_check.py                                   # independent recomputation, ALL OK (706 checks)
DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/productsignal python -m pytest -q
python -m pytest -q                                                  # without DATABASE_URL the database tests skip, the pure-domain tests run
DATABASE_URL=... python data/migrate.py [--reset]                    # apply the migrations
DATABASE_URL=... python data/seed.py tests/fixtures/golden/inputs.json [--reference-only]
DATABASE_URL=... CODE_SHA=$(git rev-parse HEAD) uvicorn --factory api.app:create_app   # docs at /api/v1/productsignal/docs
```

The CI job (`.github/workflows/productsignal-ci.yml`, Mode A) runs the reference check, the hash-count check and `pytest -q` against a `postgres:16`
service. `pytest.ini` puts `domain` and the app root on the path. Tests use a fixed API clock (`tests/conftest.py`, 2026-10-26T22:00Z).

## Domain

* `run_pipeline(inputs, cutoff=...)` returns `PipelineResult(ingest, population, metrics, warnings)`; `metrics` has exactly the keys of `expected.json`
  (`METRIC_KEYS`, names and nesting per D-P6-15): `signup_conversion`, `funnel`, `activation`, `retention` (`day7`, `on_or_after_day7`, `week4`),
  `feature_adoption`, `experiment`; `tracking_quality` and `identity` travel beside them.
* **Cutoff rule (D-08):** a run at cutoff C sees only facts that existed by C: assignments with `assigned_at <= C`, exposures with
  `exposed_at <= C`, subscriptions with `starts_at <= C` (inside the plan's revenue window), observations with `window_end <= C`,
  in the domain, the SQL reference and the API (`GET /metrics`, C07, C08). An interim run therefore counts only the accounts assigned by then.
* **Events** are canonicalised per run: received by the cutoff, deduplicated (earliest `received_at` wins), unknown identity, bot, internal; events
  received after the cutoff are reported apart from delayed ones (> 24 h strictly). Identity is time-aware: a link attributes anonymous events with
  `event_at` >= `linked_at` only, never backward, and the earliest link of an anonymous id fixes its user.
* **Accounts** are the unit: users roll up to the account before any ratio. Activation window [signup, +7 d), maturity inclusive. Retention uses
  the account's IANA timezone (`zoneinfo`, so it needs system tzdata or the `tzdata` wheel) for day indices; exact day 7 and "on or after day 7" are separate figures.
* **Experiments**: idempotent assignment per (experiment version, unit), exposure >= assignment, intention-to-treat on mature assigned accounts,
  exposure rate beside it, SRM (chi-square, p = erfc by a Decimal series, verdict order INSUFFICIENT, MISMATCH, OK), Wilson and Newcombe intervals
  (integer-Newton square roots), absolute and relative lift (relative null at zero control), frozen plan with `config_hash`, interim vs final with the
  prior-run count, guardrail error rate, revenue per assigned account with a t-interval (Decimal CDF bisection), `conclusive`.
* **Segments** are exploratory: every result carries the label, the number of segments tested and the Bonferroni threshold; a segment is never a decision basis.

## API (prefix `/api/v1/productsignal`)

Headers `X-Actor-Id`, `X-Actor-Role` (analyst, experimenter, admin). Commands are `POST /commands/<name>` with `{request_id, dataset_version,
idempotency_key, input}` and answer `{command_id, status, result, warnings, version}`; errors are `{error: {code, message, details}, request_id}`
(401 no actor, 403 role, 404, 409, 422). Each command runs in one transaction with its audit row and stored result.

| ID | Command | Roles | Effect |
|---|---|---|---|
| C01 | validate-tracking | all | raw events (with properties) to the immutable log with canonical flags; rejected rows kept |
| C02 | resolve-identity | all | one anonymous-to-user link; forward only; reports both sides |
| C03 | define-funnel | all | a new funnel version (ordered steps, max gap, window); versions are never edited |
| C04 | assign-experiment | experimenter, admin | fixes the variant of an account (409 ASSIGNMENT_CONFLICT on another variant) |
| C05 | record-exposure | experimenter, admin | exposure needs an assignment and `exposed_at` >= `assigned_at` |
| C06 | freeze-analysis-plan | experimenter, admin | registers the plan and its `config_hash`; refused after any run read outcomes |
| C07 | check-maturity | all | cohort maturity at a cutoff; writes the eligible observations once |
| C08 | analyze-experiment | all | refused before the freeze (409 PLAN_NOT_FROZEN); SRM first; interim before `planned_end`; logs the run |
| C09 | review-guardrails | all | the prespecified guardrail of a run: OK, HARMFUL or INSUFFICIENT |
| C10 | record-decision | experimenter, admin | ship, stop or inconclusive citing one run and its review; writes no product state |

Reads (no actor): `GET /data/{entity}` (stable order, opaque cursor, whitelisted equality filters, `from`/`to` half-open),
`GET /data/analysis_runs/{id}` (the published result, never recomputed), `GET /data/experiment_versions/{id}/audit`, and
`GET /metrics?from=&to=&cutoff=&experiment_version_id=&group_by=none|variant|plan|segment|timezone` (all metrics, `retention_grid` per signup cohort,
`segment_analysis` for plan/segment/timezone).

Conventions: lock order idempotency key, experiment-version rows by id, unit rows by id; 3 attempts on deadlock then 409 `CONCURRENT_UPDATE`;
actor-bound idempotency (the payload hash includes `dataset_version`, the binding includes actor id and role; a different payload, actor or role
under the same key is 409 `IDEMPOTENCY_KEY_REUSED`); a `dataset_version` that is not the current one is 409 `STALE_DATASET_VERSION`.

## Assumptions where the contract is silent (input to D-06)

1. The event log is append-only; C01 stamps `received_at` with the API clock (only an admin may backfill it). A re-sent `event_id` with identical content is idempotent, with different content it is rejected.
2. Extra ingest rejection codes beyond D-05: MALFORMED_RECORD, DUPLICATE_ID, UNKNOWN_ACCOUNT, UNKNOWN_USER, UNKNOWN_EVENT, UNKNOWN_EXPERIMENT_VERSION, UNKNOWN_UNIT, UNKNOWN_VARIANT, INELIGIBLE_UNIT, INVALID_INTERVAL, IDENTITY_CONFLICT, UNSUPPORTED_UNIT_TYPE. A rejected row is kept raw in `rejected_records`; its dependents are rejected with DEPENDENT_REJECTED.
3. Default windows when none are stored or given: signup conversion, funnel and feature adoption the 7 days before the cutoff, activation 28 days, the retention cohort the seven local dates ending 35 days before the cutoff date; feature `export` for plans team and business.
4. Internal accounts are not eligible for assignment (422 INELIGIBLE_UNIT); experiments have exactly two variants, `control` and `treatment`; the allocation is two proportions summing to 1.
5. Subscriptions with status `trial` or `refunded` carry no revenue; only `active` and `ended` count (D-03), and money is USD only.
6. C06: one frozen plan per experiment version, never edited (409 PLAN_ALREADY_FROZEN); `unit_type` must equal the version's (422 UNIT_MISMATCH), `planned_end` and `primary_metric` must equal the version's, `frozen_at` defaults to the API clock and may not be in the future; the plan is refused once any analysis run exists (409 OUTCOME_ALREADY_READ).
7. C08 requires intention-to-treat on the account; an analysis unit other than `account`, an analysis other than intention-to-treat, or an exclusion on any field other than plan, segment, timezone or internal is refused. A pre-assignment exclusion is applied, disclosed, and blocks `ship` (PLAN_DEVIATION).
8. A later run whose cutoff includes events received after an earlier run's cutoff carries a `revision` block (the late events counted by name, whether the primary figure changed); the earlier published result is never rewritten.
9. Segment analysis tests only segments that have both arms; `segments_tested` is that count and the Bonferroni threshold is alpha divided by it. Each segment carries a pooled z-test p-value and a Newcombe interval at the Bonferroni-adjusted z.
10. C09 verdict: HARMFUL when the whole Newcombe interval of the treatment-minus-control error-rate difference lies above 0, INSUFFICIENT when a variant has no eligible unit, otherwise OK.
11. C10: one decision per analysis run (409 DECISION_ALREADY_RECORDED); the review must belong to the run (REVIEW_MISMATCH); `ship` is blocked by an interim run, an SRM MISMATCH, a HARMFUL guardrail, a plan deviation, or a config hash that does not match the plan; `stop` is also blocked by an SRM MISMATCH (the lift is not interpretable); `inconclusive` is always allowed. A `ship` on a non-conclusive final run is allowed with a NOT_CONCLUSIVE warning. A refused decision leaves a `record-decision-refused` audit row.
12. The Student t table (`t_critical_975`) covers df 1..2000 at 95 percent; beyond that, or for another confidence, the SQL reference returns a null interval rather than a wrong one (the domain computes any df).
13. Local-calendar days use the instant converted to the account's timezone, so a DST change moves no session to another day by itself; the DST edge cases are not pinned by the fixture.
14. `GET /metrics` defaults `cutoff` to the API clock; `from`/`to` replace the bounds of every windowed metric; `group_by` splits account-based metrics only (signup conversion, the visitor funnel and the experiment block are not split, and the response says so).
15. `dataset_version` is the most recent `dataset_versions` row; a command with another value is stale. Reads report `unversioned` when no data was loaded.
16. Listing limits: 1..200 rows per page; filters are equality on a per-entity whitelist; an unknown filter is 422 INVALID_FILTER.
