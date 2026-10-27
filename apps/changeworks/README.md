# ChangeWorks (project 09) — backend (Mode A: Python domain + PostgreSQL + FastAPI)

Decision: which transformation initiative should be funded, and how will success be established? Contracts in `docs/contracts.md` (D-01..D-09; D-05 adopts the
fixture's decisions D-P9-01..24, full text in `tests/fixtures/golden/CALCULATION.md`), API inventory in `docs/api-contract.md`, site brief in `docs/web-brief.md`,
generator spec in `docs/data-generator.md`. Layout and conventions follow `apps/trustledger`. The domain is standard library only (`fractions.Fraction` for every
ratio, rate and discount factor, `decimal`/integers for money, no float in any published figure); the API adds FastAPI, pydantic and psycopg. Nothing imports another
lab app. Nothing here funds anything: a selected scenario is a **proposal**. The Mode B web mirror (`web/`) is separate.

```
domain/changeworks/  contract, errors, numbers, timeutil, ingest, context, cashflow, measures, people, roadmap, metrics, snapshot, pipeline
data/                migrate.py, seed.py, sql/migrations/0001_schema.sql, 0002_constraints.sql, 0003_review9.sql, sql/reference_metrics.sql
api/                 app, clock, db, schemas, commands, reads, errors     (prefix /api/v1/changeworks)
tests/               golden (domain), variants, rules, migrations, SQL reference, API commands, API reads, adversarial; reference_check.py (stdlib only)
tests/fixtures/      golden/ (the pack's fixture, never edited here), adversarial/ (the smallest dataset of each P09-TEST-01..12, detect and recover)
```

## Run

```
pip install -r requirements.txt
python -I tests/reference_check.py                                   # independent recomputation, ALL OK (3156 checks)
DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/changeworks python -m pytest -q -ra        # 454 tests, 0 skips, 3 to 4 minutes
python -m pytest -q tests/test_golden_domain.py tests/test_variants.py tests/test_rules.py  # the pure-domain tests need no database
DATABASE_URL=... python data/migrate.py [--reset]                    # apply the migrations (empty database or second run)
DATABASE_URL=... python data/seed.py tests/fixtures/golden/inputs.json [--dataset-version NAME]
DATABASE_URL=... CODE_SHA=$(git rev-parse HEAD) uvicorn --factory api.app:create_app      # docs at /api/v1/changeworks/docs
```

The database tests **fail** (they do not skip) when `DATABASE_URL` is unset, so a green run always means PostgreSQL was exercised. Every database test starts from
`migrate.reset` + `apply_migrations`. `pytest.ini` puts `domain` and the app root on the path. Tests use a fixed API clock (`tests/conftest.py`, 2026-10-27T12:00Z;
the command tests re-freeze it at 2028-07-01T12:00Z, after the golden `as_of`).

## Domain

`run_pipeline(inputs, as_of=None, window=None, scenario_ids=None)` returns `PipelineResult(ingest, population, as_of, metrics, warnings)`; `.golden()` is the whole shape
of `expected.json` (counts, rejected records, `metrics`). `metrics` has the key nesting of `expected.json`: `summary`; `scenarios.<id>.{status, baseline_version,
horizon_periods, rate_basis, declared_rate, effective_period_rate(_exact), rate_source, initiatives.<id>.{cash_flow[], expanded_planned_costs[],
excluded_from_cash_flow, converted_capacity[], ramp, unramped_net_cash_flow, planned_money_benefits, npv, payback.{simple,discounted}, capacity_released,
cost_variance, benefit_realization.<type>, immature_observation_ids}, double_count, npv_total}`; `initiatives.<id>.{roadmap, adoption, training, risk, forecast}`;
`groups.<id>`; `resources.<id>`. All three fixtures reproduce it leaf for leaf (643, 2277 and 57 leaves).

* **Four benefit classes, never summed into one number.** Cash and revenue enter the net cash flow; avoided cost only with `cash_realisation` **and** an
  `evidence_ref` (otherwise `avoided_cost_beside`, reason `NOT_CASH_REALISED` / `NO_EVIDENCE_REF`); capacity hours never, unless a `capacity_hourly_rate` assumption
  with a `staffing_change_evidence_ref` exists, when each row becomes a separate derived cash item (`converted_capacity`) citing the assumption.
* **Exact arithmetic.** NPV is `sum CF_t / (1 + r)^t` as a `Fraction` (`npv.exact` is `n/d`), shown to 2 places ROUND_HALF_UP; discount factors, readiness and every
  ratio are Fractions; the monthly rate is a declared 6-place decimal assumption (`monthly_rate_conversion`), never the irrational twelfth root.
* **Paybacks** (simple and discounted, labelled separately): the first period with cumulative >= 0 (exactly 0 counts), an integer and a 4-place interpolation, 0.0000
  at period 0, **null** (not 0, not rejected) when never reached or when there are no flows.
* **Import (`ingest.py`)**: parents first; per record shape (`MALFORMED_RECORD` with the failing fields), duplicate id, foreign keys (`UNKNOWN_*` / `DEPENDENT_REJECTED`),
  then the business rules; the later of two repeats is rejected; nothing is dropped silently. `Validator.check` is the same code the API commands use on one new row.
* **Roadmap**: feasible start = the longest chain of (prerequisite feasible start [+ its duration for finish_to_start] + lag), never earlier than the requested start;
  delay never negative; first dependency by id binds a tie; a cycle is `DEPENDENCY_CYCLE` with the cycle listed (the rejected edge's initiative first). Allocations
  are checked against `capacity_per_period` (exactly at capacity is allowed; the crossing row is rejected with its periods).
* **Double count**: claims sharing a `benefit_source_key` in one period across two or more initiatives count once, at the largest claim; the rest is the residual and
  the overlaps are listed. Hours are never claims; converted capacity is.

## Data (PostgreSQL 16)

`0001_schema.sql` (tables), `0002_constraints.sql` (checks, unique indexes, append-only triggers, `cw_dec` / `cw_iso` helpers); both idempotent (`IF NOT EXISTS`, a
changed applied file is refused by `migrate.py`). Money is `NUMERIC(20,6)` (JSON shows 2 places or more, never fewer: `1000.000000` reads as `1000.00`, `0.125` stays
`0.125`), proportions `NUMERIC(7,6)`, instants `TIMESTAMPTZ`. Append-only (UPDATE, DELETE and TRUNCATE refused, with the rule in the message): baselines
(`BASELINE_FROZEN`), baseline approvals, assumption versions, forecast versions (`FORECAST_OVERWRITE`), opportunity scores, resources, scenario children, costs,
expanded costs, benefits, dependencies, groups, impact mappings, allocations, readiness, adoption, training, benefit observations, risks, rejected records, audit,
idempotency results, dataset versions. `initiatives` change only status, schedule and the approved baseline (each change bumps `version` by one; the approved
baseline must have an approval row, checked at commit); `scenario_versions` change only draft -> proposed, once.

`data/sql/reference_metrics.sql` is an independent recomputation (path/value rows) of net cash flow, NPV, both paybacks, capacity released, adoption, training, cost
variance, benefit realization, risk exposure, readiness, dependency delay, the double-count residual and the summary pools. It reads facts only. The one tolerance in the
project: the NPV is also emitted to 6 places and compared with the domain's exact rational within **0.000001 USD** (PostgreSQL's `power(numeric, integer)` keeps a bounded
number of digits); every other figure, the 2-place NPV included, is compared for equality. Run it with `SET jit = off` (the planner over-estimates the cross joins and JIT then
costs ~8 s for a 10 ms statement).

## API (prefix `/api/v1/changeworks`)

Headers `X-Actor-Id`, `X-Actor-Role` (analyst, sponsor, admin). Commands are `POST /commands/<name>` with `{request_id, dataset_version, idempotency_key, input}` and answer
`{command_id, status, result, warnings, version}`; errors are `{error: {code, message, details[{path, rule_id, message, context?}]}, request_id}` (401 no actor, 403 role,
404, 409, 422). Each command runs in one transaction with its audit row and stored result; **every row is checked before the first write**, so a refusal writes nothing
(except the deliberate `<command>-refused` audit row of a role, frozen-baseline or unexplained-residual refusal). Clients never supply an instant: `created_at`,
`assessed_at`, `observed_at`, `approved_at`, `proposed_at` are the server's clock (`FIELD_UNEXPECTED` if sent); an evidence date is a plain date (`measured_on`,
`observed_on`) that may not lie in the future.

| ID | Command | Roles | Effect |
|---|---|---|---|
| C01 | establish-baseline | create: all; `action: approve`: sponsor, admin | `create`: measured evidence only (volume, minutes per case, error rate, evidence ref, `measured_on`); a field that is an assumption is 422 `ASSUMPTION_IN_EVIDENCE`; a correction of an approved baseline is a new version with a reason; rewriting an approved version is 409 `BASELINE_FROZEN`. `approve`: that set becomes the initiative's approved baseline, its rows are frozen, the earlier version stays readable (403 + refusal audit for an analyst) |
| C02 | assess-opportunity | all | a scored option: criteria with scores 1..5 and positive weights, a rationale; exact weighted score (4 places + `n/d`), versioned per initiative; candidate -> assessed; can create the candidate |
| C03 | build-cash-flows | all | a NEW scenario version (an edit is a new `scenario_id`), optional new assumption versions, cost and benefit rows; recurring costs expanded explicitly into `expanded_costs`; returns the dated model (net cash flow, NPV, paybacks) labelled an estimate. 422 `RATE_PERIOD_MISMATCH`, `BENEFIT_BEFORE_DEPLOYMENT`, `ONE_TIME_COST_REPEATED`, `CAPACITY_WITHOUT_CONVERSION`, ... all rejected rows together |
| C04 | map-impacts | all | operating changes per synthetic stakeholder group (groups can be created in the same call); validated and counted only |
| C05 | assess-readiness | all | readiness-dimension assessments (scores 1..5, weights), server-stamped; returns the group's readiness score ("assessment, not a probability") |
| C06 | plan-roadmap | all | schedule edits (`expected_version`), dependencies (a cycle is 422 with the cycle listed), resources and allocations (422 `RESOURCE_OVERALLOCATED` with the periods); returns feasible starts, delay, binding dependency, resource view; atomic |
| C07 | select-scenario | sponsor, admin | scenario -> `proposed` with the comparison it was chosen from; `status: funded` is 422 `STATUS_NOT_ALLOWED`; a non-zero double-count residual without a written explanation is 422 `DOUBLE_COUNT_UNEXPLAINED` (overlaps listed, refusal audited); a proposal is final (409 `ALREADY_PROPOSED`) |
| C08 | record-adoption | all | an adoption observation with its denominator and eligibility rule version (`ADOPTED_EXCEEDS_ELIGIBLE`, `ELIGIBILITY_RULE_MISMATCH`); optional training completion, always a separate series |
| C09 | track-benefits | all | an observed value for one benefit, compared within its benefit type on matured periods; the unit must match (`BENEFIT_TYPE_MISMATCH`); a claim of full attribution is 422 `ATTRIBUTION_NOT_ESTABLISHED`; the result says "observed, not attributed" |
| C10 | revise-forecast | sponsor, admin | forecast version n+1 (the first forecast is version 1, the original); never overwrites; `expected_version` (409 `STALE_FORECAST_VERSION`); the comparison lists every version and the observed values |

Reads (no actor): `GET /data/{entity}` for `initiatives`, `process_baselines`, `assumption_versions`, `cost_items`, `benefit_items`, `dependencies`, `stakeholder_groups`,
`readiness_assessments`, `adoption_observations`, `benefit_observations`, `risk_items`, `scenario_versions`, `resources`, `resource_allocations`, `impact_mappings`,
`training_completions`, `forecast_versions`, plus `baseline_approvals`, `opportunity_scores`, `expanded_costs`, `rejected_records`, `audit_events`, `dataset_versions`
(stable order by key in code-point order, opaque cursor, `limit` 1..200, whitelisted equality filters, `from` inclusive / `to` exclusive on the entity's time field).
`GET /metrics?scenario_id=&from=&to=&as_of=` returns `{data: {as_of, window, scenario_id, period_basis, period_start, empty_population, ingest, metrics}, meta, warnings}`.

Conventions: lock order idempotency key, initiative rows by id, group / resource rows by id, scenario rows by id; 3 attempts on deadlock or serialization failure then 409
`CONCURRENT_UPDATE`; actor-bound idempotency (the payload hash includes the command and `dataset_version`, the binding includes actor id and role; a different payload, actor or
role under the same key is 409 `IDEMPOTENCY_KEY_REUSED`; a refused command stores nothing, so its key is free); a `dataset_version` that is not the current one is 409
`STALE_DATASET_VERSION`.

## What is proven by which test

| Claim | Test file / test |
|---|---|
| golden figures, key nesting, every leaf of the three expected files; the spec sentence NPV 5000/121 = 41.32 | `test_golden_domain.py` (29), `test_variants.py` (10): 643 / 2277 / 57 leaves |
| ingest codes and cascades, shapes, ramps, avoided cost, capacity conversion, monthly rates, paybacks, variance, realization, adoption, risk, readiness, roadmap, ties, window, as_of | `test_rules.py` (104) |
| migrations from empty and on a second run, append-only, frozen baseline, forecast overwrite, scenario immutability, checks, seed idempotency | `test_migrations.py` (39) |
| the SQL recomputation equals `expected.json` leaf for leaf, equals the domain at other `as_of`, and on 60 seeded random populations; NPV tolerance 0.000001 | `test_sql_reference.py` (18) |
| C01..C10 happy paths, hard validation, roles, idempotency, stale dataset, audit, atomicity, no client instants | `test_api_commands.py` (103) |
| metrics endpoint = `expected.json` for all three fixtures (ingest included); window, as_of, entity reads (no records, one, many pages, filters, order, reconciliation) | `test_api_reads.py` (46) |
| P09-TEST-01..12 detect and recover on the smallest fixtures (`tests/fixtures/adversarial/`), races, deadlock retry, rollback, interrupted command, hostile input | `test_adversarial.py` (51) |

| P09-TEST | Detect | Recover |
|---|---|---|
| 01 time savings counted as cash | `test_01_detect_*` (`CAPACITY_WITHOUT_CONVERSION`, hours excluded) | `test_01_recover_*` (derived cash items; through C03) |
| 02 same capacity claimed twice | `test_02_detect_*` (residual 300.00, C07 refused) | `test_02_recover_*` (scenario without the overlap; explained proposal) |
| 03 annual rate on monthly periods | `test_03_detect_*` (`RATE_PERIOD_MISMATCH`) | `test_03_recover_*` (recorded conversion, exact NPV) |
| 04 benefits before deployment | `test_04_detect_*` | `test_04_recover_*` (ramp, unramped beside) |
| 05 training mistaken for adoption | `test_05_detect_*` | `test_05_recover_*` (two numbers, through C08) |
| 06 forecast overwrite | `test_06_detect_*` (data, command and SQL all refused) | `test_06_recover_*` (version 2 through C10) |
| 07 dependency cycle | `test_07_detect_*` (cycle listed) | `test_07_recover_*` |
| 08 never pays back | `test_08_detect_*` (null, not 0) | `test_08_recover_*` (new scenario, longer horizon) |
| 09 specialist overallocated | `test_09_detect_*` (periods listed) | `test_09_recover_*` |
| 10 improvement attributed to the rollout | `test_10_detect_*` | `test_10_recover_*` |
| 11 one-time cost recurs | `test_11_detect_*` (first kept) | `test_11_recover_*` (explicit recurring rows) |
| 12 cost avoidance added to realized cash | `test_12_detect_*` (beside 1000.00) | `test_12_recover_*` (evidenced budget line enters) |

## Assumptions where the contract is silent (input to D-06)

1. **Result shape.** `/metrics` returns the whole `ingest` block (accepted counts from the tables, rejected records from `rejected_records` in load order) and `metrics` in the
   nesting of `expected.json`; the dataset's `period_basis` / `period_start` live in the one-row `dataset_config`. Without a row the domain assumes annual from 2026-01-01.
2. **As-of.** `as_of` defaults to the server's now on the API and to the inputs' `as_of` in the pipeline. Adoption, training, readiness, benefit observations and forecast
   versions dated after `as_of` do not exist yet (listed in `excluded_after_as_of`, `immature_observation_ids`). Plan rows (costs, benefits, scenarios, assumptions) are
   declarations and are not clipped by their `created_at`.
3. **Window.** `from` / `to` (half-open, ISO date or instant, UTC) narrow adoption, training, readiness and the observed cash values by their instants and cost variance and
   realization by period start; the dated model is not windowed and `MODEL_NOT_WINDOWED` says so.
4. **Which baseline.** Metrics read the initiative's CURRENT approved `baseline_version`; the scenario's `baseline_version` is its label. When they differ the warning
   `BASELINE_VERSION_DIFFERS` is returned. Approving a version that was approved before is 409 `ALREADY_APPROVED`.
5. **Baseline rows.** One row per (initiative, version), `volume` and `minutes_per_case` whole numbers; a second row for an approved version is `BASELINE_FROZEN`, for an unapproved
   one `VERSION_EXISTS`; `EVIDENCE_REQUIRED` for a blank evidence reference.
6. **Evidence vs assumption (C01).** A field of the C01 input whose name contains `target`, `assum`, `expect`, `ramp`, `forecast`, `discount`, `rate_basis`, `savings`, `benefit`
   or `scenario` is 422 `ASSUMPTION_IN_EVIDENCE`.
7. **Instants.** `measured_on` / `observed_on` are plain dates (midnight UTC), not in the future (`DATE_IN_FUTURE`); with no `observed_on` the observation is stamped now. Back-dated
   history enters through the seeder only.
8. **Assumption names the domain reads:** `adoption_ramp` (non-decreasing fractions in [0, 1], `INVALID_RAMP`), `target_minutes_per_case`, `capacity_hourly_rate` (needs a
   `staffing_change_evidence_ref` to convert), `monthly_rate_conversion` (the only name a scenario's `rate_conversion_assumption_id` may cite, `INVALID_CONVERSION`). A version
   number is server-assigned (next per initiative and name) unless sent; a taken number is 409 `VERSION_EXISTS`. The author is the actor. Exactly one of `value` and `values`.
9. **Ranges.** discount rate in [0, 1] (`INVALID_RATE`), horizon 1..600, periods 0..100000 (`INVALID_PERIOD`), decimals at most 14 integer and 6 decimal digits, durations >= 1,
   a benefit's `unit` is `hours` for capacity and `USD` otherwise (`INVALID_UNIT`).
10. **C02.** Weighted score = sum(w x s) / sum(w), exact, a ranking aid; `new_initiative` creates a candidate (deployment period 1, rule `elig-v1` by default) as `assessed`.
11. **C03.** One scenario per call, all-or-nothing; the model returned covers every planned cost and benefit row of the scenario's initiatives, including rows that existed
    before the call; `expanded_costs` holds the explicit expansion of the planned costs of the scenario's initiatives within its horizon.
12. **C04.** A stakeholder label must be synthetic: no `@`, no run of 6+ digits (`LABEL_NOT_SYNTHETIC`). Mappings are counted, no numeric metric is derived (D-P9-24).
13. **C05.** Default weight 1.00; one assessment per dimension per request; the latest per dimension at or before as_of counts.
14. **C06.** Allocations are checked in the order sent (the fixture loader checks them in id order, D-P9-15); the resource-constrained start equals the dependency-feasible start
    (resource levelling is not implemented), so `resource_delay` is 0 and an overallocation can only be refused, never stored.
15. **C07.** The residual is computed at the server's now over the scenario's initiatives; an explanation is free text, stored with the proposal; `compared_scenario_ids` are stored
    in `comparison` with their NPV totals, residuals and paybacks; `status` accepts only `proposed`.
16. **C08 / C09.** Training travels beside adoption (optional block), never substituted; `unit` of a tracked value must equal the benefit's unit; the attribution value is
    `observed_not_attributed` only; the observation of an unmatured period is kept and excluded from the realization (`PERIOD_NOT_MATURED`).
17. **C10.** Versions are per initiative; the first call creates version 1 (warning `FIRST_FORECAST`); the lock on the initiative row serialises concurrent revisions.
18. **Roles.** Identity (401) and the role inventory (403) are checked before the body is read; a command's own role set is checked before the body too; C01's approval role is
    checked after the body (403 `ROLE_FORBIDDEN` with a refusal audit row).
19. **Entities.** Besides the 17 entities, the reads expose `baseline_approvals`, `opportunity_scores`, `expanded_costs`, `rejected_records`, `audit_events` and `dataset_versions`.
20. **Ingest codes beyond D-05:** `MALFORMED_RECORD`, `INVALID_PERIOD`, `INVALID_DURATION`, `INVALID_AMOUNT`, `INVALID_UNIT`, `INVALID_RAMP`, `INVALID_ASSUMPTION`, `INVALID_VERSION`,
    `RATIONALE_REQUIRED`, `INVALID_HORIZON`, `INVALID_RATE`, `INVALID_RATE_BASIS`, `INVALID_CONVERSION`, `INVALID_SCENARIO`, `EVIDENCE_REQUIRED`, `BASELINE_FROZEN`, `LABEL_NOT_SYNTHETIC`,
    `OPERATING_CHANGE_REQUIRED`, `INVALID_COUNT`, `INVALID_LAG`, `INVALID_DEPENDENCY_TYPE`, `INVALID_IMPACT_LEVEL`, `INVALID_COST_TYPE`.
21. **Seed.** An initiative naming a baseline version with no accepted baseline row is loaded without an approved baseline (warning `BASELINE_NOT_LOADED`); approvals found in an
    inputs file are recorded as approved by `seed`.
22. **Instants sort as instants.** Observations, assessments and records are ordered by their parsed instant (ties by id), never as strings (`...00Z` sorts after `...00.5Z`).
23. **Partial trend coverage.** `observed_above_trend` is null with the warning `PARTIAL_TREND_COVERAGE` (and `trend_coverage.rows_without_trend`) unless every compared observed row carries a trend
    (D-09 R9-13). C09 warns `NO_BASELINE_TREND` for the row it tracks.

## Not implemented / open gaps

* Resource levelling: no resource-constrained start shift and no non-zero `resource_delay` (the fixture does not exercise it); allocations are absolute roadmap periods.
* The double-count rule of C07 is enforced by the command, not by a database trigger (a direct SQL `UPDATE` to `proposed` bypasses it); the database does forbid `funded`.
* Initiative status moves only by C02 (candidate -> assessed); no command moves it to in_delivery / adopted / closed. Initiatives are created only by C02.
* No command edits or removes a cost, benefit, dependency, resource or allocation (rows are append-only; a correction is a new scenario or row).
* No workbook, export or recommendation endpoint (P09-DOMAIN-06 belongs to the artifact work packages).
* A "safe rejected-attempt security log" beyond the `*-refused` audit rows is not written; malformed input writes nothing.
* The metrics endpoint is not paged and recomputes from the tables on every call (fine at the fixture's size; the generator profiles in `docs/data-generator.md` were not benchmarked).
* The SQL reference needs `SET jit = off` for speed. Its NPV computes each discount factor by exact recursion (no `power()`), is exact to 0.000001 for horizons up to 36 periods and 14-digit amounts (tested on the published 36-period world and on a 14-digit case), and every other figure is compared exactly. Beyond that bound the tolerance is not claimed.

## Review R9 (D-09)

The fixes adopted from review R9 are listed one by one in `docs/contracts.md` D-09. In short: scenario figures come from the rows and assumption versions that existed at the scenario's `created_at`
(migration `0003_review9.sql`, `recorded_at` on every plan and observation row, a snapshot hash on a proposed scenario); `npv_total` and the class totals are attributable with the plain sum and the
amount counted twice beside them; the overlap rule also runs on hours; evidence references must be non-blank; payback is the last crossing with the reasons `NO_INVESTMENT`, `NOT_RECOVERED` and `NO_FLOWS`;
`observed_above_trend` is null under `PARTIAL_TREND_COVERAGE`; `DEPLOYMENT_BEFORE_FEASIBLE_START` is a warning, not a re-timing; `period_start` days are 1 to 28; C07 explanations need 20 characters and C10 needs
`expected_version`. The published world is unchanged in size class (990,783 bytes, dataset hash `6bf7ebaa…`), and its headline figures moved only where the rules above say: attributable NPV 1,243,149.05 against
a plain sum of 1,438,382.25 in scn-025.
