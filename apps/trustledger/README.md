# TrustLedger (project 07) — backend (Mode A: Python domain + PostgreSQL + FastAPI)

Decision: which data issues should be fixed first and who is accountable? Contracts in `docs/contracts.md` (D-01..D-06; D-06 adopts the fixture's 11
decisions, full text in `tests/fixtures/golden/CALCULATION.md`), API inventory in `docs/api-contract.md`, site brief in `docs/web-brief.md`, generator
spec in `docs/data-generator.md`. Layout and conventions follow `apps/productsignal` and `apps/invoicebridge`. The domain is standard library only
(`fractions.Fraction` for every ratio, no float in any published figure); the API adds FastAPI, pydantic and psycopg. Nothing imports another lab app.
The Mode B web mirror (`web/`) is separate.

```
domain/trustledger/  contract, errors, numbers, timeutil, models, ingest, measure, issues, matching, verification, scoring, structure, metrics, pipeline
data/                migrate.py, seed.py, migrations/0001_schema.sql, 0002_constraints.sql, 0003_review_r7.sql, sql/reference_metrics.sql, sql/verification_truth.sql   (see data/README.md)
api/                 app, clock, db, schemas, commands, reads, errors     (prefix /api/v1/trustledger)
tests/               golden (domain), variants, rules, migrations, SQL reference, API commands, API reads, adversarial; reference_check.py (stdlib only)
```

## Run

```
pip install -r requirements.txt
python -I tests/reference_check.py                                   # independent recomputation, ALL OK (805 checks)
DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/trustledger python -m pytest -q -ra   # no skips with the database
python -m pytest -q                                                  # without DATABASE_URL the database tests skip, the pure-domain tests run
DATABASE_URL=... python data/migrate.py [--reset]                    # apply the migrations
DATABASE_URL=... python data/seed.py tests/fixtures/golden/inputs.json [--dataset-version NAME]
DATABASE_URL=... CODE_SHA=$(git rev-parse HEAD) uvicorn --factory api.app:create_app   # docs at /api/v1/trustledger/docs
```

The CI job (`.github/workflows/trustledger-ci.yml`, Mode A) runs the reference check, the hash-count check and `pytest -q -ra` (then fails on any skipped test: the junit file must say `skipped="0"`) against a `postgres:16`
service on a runner with system tzdata (the domain uses `zoneinfo`). `pytest.ini` puts `domain` and the app root on the path. Tests use a fixed API
clock (`tests/conftest.py`, 2026-10-26T22:00Z; individual tests re-freeze it, e.g. at the fixture's `as_of`).

## Domain

* `run_pipeline(inputs, as_of=None, weight_version=None, window=None, truth=None)` returns `PipelineResult(ingest, population, metrics, warnings)`;
  `metrics` has exactly the keys of `expected.json` (`METRIC_KEYS`, D-06): `completeness`, `validity`, `uniqueness`, `relationship_integrity` (each keyed by
  rule id), `timeliness`, `weighted_score`, `critical_failures`, `resolution_time`, `ownership_coverage`, `definition_coverage`, `match_precision`,
  `lineage_coverage`. `result.golden()` is the whole shape of `expected.json` (the ingest counts and rejected records, `rules`, `metrics`, `definitions`,
  `matching`); all three fixtures reproduce it leaf by leaf (435, 234 and 99 leaves).
* **Five dimensions on their own denominators**, never blended: completeness (missing = null or trimmed-empty under the whitespace policy), validity
  (all-eligible and populated-only, both labelled; format validity, never correctness), uniqueness (duplicate-group share and duplicate-row share; null keys fail,
  are listed apart and lower the score: (eligible - null-key rows - duplicate rows) / eligible), relationship integrity (null, empty and whitespace-only foreign keys
  excluded from the denominator and counted apart), timeliness (the dataset's local daily schedule in its IANA zone plus a grace, half-open `[occurrence, deadline)`;
  on time / late / pending, a pending open window is outside the denominator).
* **Score and override.** Weighted score = sum(score x weight) / sum(weights of the measured dimensions) under the named weight version; unmeasured
  dimensions leave both sums; null if none is measured. `critical_failures` (failures of active critical rules, plus the live failure of a critical rule disabled while its latest run fails, `carried`) and open
  critical issues (open, reopened or claimed) are counted apart and set `critical_override` whatever the score is.
* **Issues.** `resolved` only after a successful rerun of the same rule version over the issue's records (`resolved_at` = that rerun's `run_at`); a close
  without it is `claimed` and listed apart; reopen cycles are counted and the first `detected_at` is kept; open issues age to `as_of`.
* **Matching.** Candidates are stored once in canonical order (`DUPLICATE_PAIR`, `NON_CANONICAL_ORDER`); a merge maps the right record to the left and needs a
  reviewer other than the proposer (`REVIEWER_IS_PROPOSER`); a reversal restores both identities and keeps the history. **Match precision** (approved
  decisions confirmed by the synthetic truth / approved decisions) is computed only in `verification.py` from the truth the caller passes; the matcher never
  reads it, and without a truth block precision is null.
* **As-of semantics.** Facts after `as_of` do not exist yet (datasets, runs, issues, observed edges, candidates, decisions, versions); a rule disabled after
  `as_of` was still active. The optional half-open window narrows the time-stamped facts (issues by `detected_at`, observed edges, candidates, decisions).

## API (prefix `/api/v1/trustledger`)

Headers `X-Actor-Id`, `X-Actor-Role` (analyst, steward, admin). The actor is a registered, active owner named by the exact id; the role is the register's, and a different header is
403 `ROLE_MISMATCH` (401 `UNKNOWN_ACTOR`, 403 `ACTOR_INACTIVE`; D-10 R7-03). Commands are `POST /commands/<name>` with `{request_id, dataset_version,
idempotency_key, input}` and answer `{command_id, status, result, warnings, version}`; errors are `{error: {code, message, details}, request_id}` (401 no
actor, 403 role or separation of duties, 404, 409, 422). Each command runs in one transaction with its audit row and stored result. Instants that are
decisions are stamped by the server's clock, never chosen by the client.

| ID | Command | Roles | Effect |
|---|---|---|---|
| C01 | register-dataset | all | a dataset with an ACTIVE owner and a classification (and optional schedule, fields, rows); 422 OWNER_REQUIRED / OWNER_INACTIVE / CLASSIFICATION_REQUIRED |
| C02 | publish-definition | steward, admin | draft -> reviewed -> published, each step a NEW metric version row (valid_from = now) plus a change record for v2+; the reviewer is not the drafter (409 SELF_REVIEW), no step is skipped (409 INVALID_TRANSITION), the content is the reviewed content (409 CONTENT_CHANGED); an existing `metric_version_id` is refused (409 DEFINITION_IMMUTABLE) |
| C03 | run-rule | all | measures an active rule: eligible and failing counts, rule version, weight version; stored; compared with the previous run (RULE_VERSION_DIFFERS) |
| C04 | open-issue | all | an owned issue on a failing scheduled run, with the rule's severity; `detected_at` = the run's time |
| C05 | triage-issue | all | `investigate` (owner and due date), `claim` (closed without a rerun = claimed) or `reopen` (a reopen cycle) |
| C06 | suggest-match | all | a candidate in canonical order with score, features, explanation; a reverse or repeated pair is 409 DUPLICATE_PAIR; never a merge |
| C07 | approve-merge | steward, admin | approve or reject by a reviewer other than the proposer (409 SELF_REVIEW; the database and the domain keep REVIEWER_IS_PROPOSER); the right record maps to the left; audited |
| C08 | reverse-merge | steward, admin | a reversal decision (reason required): both identities restored, history kept |
| C09 | disable-rule | steward, admin | active -> disabled with a reason and date; runs and issues stay, open issues stay open |
| C10 | verify-remediation | steward, admin | reruns the rule over the issue's records: a successful rerun of the same rule version resolves it, anything else leaves it claimed; a disabled rule is still rerun (disabling is not repair) |
| C11 | correct-dataset-rows | all | append-only: new row versions (`row_version`, `supersedes_row_id`, `reason`, actor, server instant) for named records; measurement and C03/C10 use the latest version of each record; nothing is edited and earlier reads keep their answers |
| C12 | record-refresh | all | appends a refresh of a dataset (`refreshed_at`, not in the future, not before registration; 409 REFRESH_EXISTS) to its history; timeliness reads the latest refresh not after its as-of |

Reads (no actor): `GET /data/{entity}` (stable order, opaque cursor, whitelisted equality filters, `from`/`to` half-open; issues carry `class` and
`resolved_at`, lineage edges carry `evidence_type`), `GET /data/comparable_runs[?rule_id=]`, `GET /data/identity_map[?as_of=]`, `GET /data/quality_rule_versions[?rule_id=]` (the definition of every rule version, so an earlier version's eligibility is readable), `GET /data/dataset_refreshes`, and
`GET /metrics?from=&to=&as_of=&dataset_id=&weight_version=&group_by=none|dataset|owner|source_system|severity` (the twelve metrics, plus `rules`,
`definitions` and `matching`; each group carries the metrics over its own part of the portfolio).

Conventions: lock order idempotency key, dataset rows by id, issue/candidate rows by id; 3 attempts on deadlock then 409 `CONCURRENT_UPDATE`; actor-bound
idempotency (the payload hash includes `dataset_version`, the binding includes actor id and role; a different payload, actor or role under the same key is
409 `IDEMPOTENCY_KEY_REUSED`); a `dataset_version` that is not the current one is 409 `STALE_DATASET_VERSION`.

## Assumptions where the contract is silent (input to D-07)

1. **Result shape.** `metrics` is exactly the twelve keys of `expected.json`; the rule runs and comparisons (`rules`), the version facts (`definitions`) and
   the identity map and history (`matching`) travel beside it, as in `expected.json`.
2. **As-of.** `as_of` defaults to the server's now on the API and to the inputs' `as_of` in the pipeline. Datasets registered, runs made, issues detected,
   versions valid, candidates proposed, decisions made and edges observed after `as_of` do not exist yet. A rule disabled after `as_of` is still active at it.
   Issue lifecycle fields are taken as stored but clipped by `as_of` (a close, a verifying rerun or a reopen after `as_of` has not happened).
3. **Window.** `from`/`to` (half-open) narrow issues by `detected_at`, observed lineage by `observed_at`, candidates by `proposed_at` and merge decisions by
   `decided_at`; the measurements over the dataset rows, timeliness, ownership and definitions are snapshots at `as_of` and are not windowed.
4. **Weight version.** The one in force at `as_of` is the latest `valid_from` not after it; a caller may name another (unknown: 422 UNKNOWN_WEIGHT_VERSION).
   Weights, like checklists, definitions and runs, are append-only: C03 refuses `weights` that differ from the named version (422
   WEIGHT_CHANGE_REQUIRES_VERSION), and the database refuses an UPDATE. A weight set must name the five dimensions and sum to 1.
5. **Scores.** Several active rules of one dimension on one dataset contribute the plain mean of their scores. A timeliness rule on an unmonitored dataset
   is not measured (eligible 0, no score). A validity rule with no pattern is not measured (`RULE_NOT_MEASURABLE`). A relationship rule whose parent dataset
   has no rows matches nothing.
6. **Cells.** A cell is compared as exact text: text as is, `true`/`false`, integers in decimal. Dataset rows are flat objects with a unique `row_id` and text,
   integer, boolean or null values; floats and nested values are rejected (MALFORMED_RECORD). A populated non-text value fails a text pattern. The closing
   `$` of a pattern does not match before a final newline (PostgreSQL's behaviour; the domain emulates it). A validity pattern may not use `\s \d \w \b` (or their negations): the ingest
   refuses it as PATTERN_NOT_PORTABLE and the database checks it; use explicit classes (`[ \t\r\n\f\v]`, `[0-9]`). The trim set of the whitespace policy comes from the configuration (default space, tab, CR, LF).
7. **Filters.** A rule may declare `definition.filter = {field, equals}`; the eligible rows are those whose cell equals the text. Without one, all rows.
8. **Timeliness.** The judged occurrence is the latest daily local time that has started by `as_of` (searched up to 5 days back); a refresh not after `as_of` in
   [occurrence, occurrence + grace) is on time, with none the dataset is pending while the deadline is in the future (outside the denominator, `pending_count`) and late
   after it; grace is 0..1439 minutes; a
   monitored dataset must declare zone, local time and grace (SCHEDULE_REQUIRED); a never-refreshed monitored dataset is pending until its deadline, then late. A local time that occurs twice
   is the LATER instant and one that does not exist uses the earlier offset (both are PostgreSQL's `AT TIME ZONE`, so SQL and domain agree on clock-change days).
9. **Issues.** Statuses are open, investigating and closed; `resolved` and `claimed` are derived. detected_at = the failing run's `run_at`. C05 carries `claim`
   and `reopen` (the contract names no close or reopen command); a reopen keeps `closed_at` and the old verification, and a verification only counts if it is
   not older than the latest reopen. An issue whose `verification_run_id` is not a successful rerun of the same rule and rule version for that issue is
   rejected at ingest (VERIFICATION_RUN_INVALID) and refused by the database (a verification is replaced only after a reopen by a later rerun).
10. **C04.** Only a scheduled run with failures opens an issue (RUN_NOT_SCHEDULED, NO_FAILURE); one issue per run (409 ISSUE_ALREADY_OPEN); the owner defaults
    to the dataset's owner and must be active. The issue records the run's failing record ids.
11. **C05.** `investigate` needs an active owner and a due date after detection; only open or investigating issues; `claim` is open to analysts (it is a claim,
    not a resolution); `reopen` only from closed.
12. **C10.** The command performs the rerun itself over the issue's recorded records (the whole rule when none are recorded) and stores it (kind `rerun`). Not
    verified is HTTP 200 with status `claimed` and the reasons RERUN_STILL_FAILING, RULE_VERSION_DIFFERS
    (the rule changed version; no rerun is made), RULE_NOT_MEASURABLE (a disabled validity rule with no pattern; no rerun) or NO_RECORDS_TO_CHECK. A disabled rule is still rerun
    (a passing rerun resolves the issue and clears the failure a disabled critical rule carries; the response says `rule_disabled` and warns RULE_DISABLED). An issue that is not closed is 409 INVALID_STATE; an already verified one 409 ALREADY_RESOLVED.
13. **C06.** `score` is a decimal string in [0, 1] with at most 6 places; `features` a non-empty map of decimal strings; a pair that exists in either orientation is
    409 DUPLICATE_PAIR; a first-seen pair with left > right is 422 NON_CANONICAL_ORDER (the response names the canonical order); equal records 422 SAME_RECORD;
    unknown records 422 UNKNOWN_RECORD. Records that share a normalized name and an address get the uncertainty "Shared name and address; possible household"
    when the caller gave none, with a warning; a candidate never produces a decision.
14. **C07/C08.** The reviewer is the actor id; separation of duties is `proposed_by` (an actor id) against the reviewer, 409 SELF_REVIEW with a refusal audit row. One
    approve/reject per candidate (409 ALREADY_REVIEWED, also under a race); an approval is refused when either record is already merged away, or when the record that
    would be merged away is itself the target of another merge (409 RECORD_ALREADY_MERGED); a reversal needs a reason, an approval of the candidate, once (409 ALREADY_REVERSED), and a candidate is not
    re-reviewed after a reversal. The actor is resolved against the owners register (exact id, active) and the role is the register's (D-10 R7-03).
15. **C09.** A disabled rule stays disabled (no re-enable); the reason is required.
16. **C02.** `valid_from` is the server's time and the approver is the actor; statuses are draft, reviewed and published, each step a new version row (D-10 R7-12);
    a change to an existing metric needs a reason; an incomplete checklist is allowed with a warning and counts as incomplete in definition coverage; an
    unknown owner is 422, an inactive one is allowed; `expected_version` is optional optimistic concurrency (409 STALE_METRIC_VERSION).
17. **C01.** `registered_at` is the server's time; `last_refreshed_at` may not be in the future; up to 1000 rows may be loaded with the dataset.
18. **Precision.** `verification.py` is the only reader of the truth. The API reads the table `verification_truth` if (and only if) a test or reviewer created
    and loaded it (`data/sql/verification_truth.sql`); the seeder never loads the truth. If a decided record has no truth row the correct counts and shares are
    null with a `MATCH_TRUTH_UNAVAILABLE` warning, never 0.
19. **Ingest codes** beyond D-06: MALFORMED_RECORD, DUPLICATE_ID, SCHEDULE_REQUIRED, INVALID_COUNTS (failures above eligible), ALREADY_REVIEWED, INVALID_REVERSAL,
    ALREADY_REVERSED, VERIFICATION_RUN_INVALID, UNKNOWN_OWNER on an issue. A rejected record is kept raw in `rejected_records`; its dependents are DEPENDENT_REJECTED.
20. **Groups.** `group_by` narrows the portfolio per dataset, owner, source system or rule severity and returns the ten dataset-scoped metrics per group; definition
    coverage and match precision are portfolio-wide and appear once at the top (also when `dataset_id` narrows the response, with a warning).
21. **Dataset version.** The most recent `dataset_versions` row; a command with another value is stale; commands do not bump it (only a load does); reads report
    `unversioned` when nothing was loaded. The seeder's `dataset_version` argument names a load; the hash excludes the synthetic truth.
22. **Listing.** 1..200 rows per page; equality filters on a per-entity whitelist (unknown: 422 INVALID_FILTER); keys sort in code-point order.
23. **Several rows per rule.** `quality_rules` holds one current row per rule (version_number); runs record the version they were made under. There is no command
    that creates or versions a rule; C03 therefore never sees two versions of one rule at once. `quality_rule_versions` (append-only) holds the definition of each
    version, the current one taken from the rule itself.
24. **Corrections and refreshes.** C11 and C12 are the only ways to change measured rows or a dataset's last refresh after the load; both append (row versions, a refresh
    history) and the loaded `datasets.last_refreshed_at` stays as loaded. Reads and the SQL reference take, per dataset, the latest refresh not after `as_of` and, per
    record, the latest version recorded by `as_of`.
25. **Instants on reads.** `from`, `to` and `as_of` need a zone (`Z` or an offset); a naive value or a date is 422 TIMESTAMP_INVALID.
