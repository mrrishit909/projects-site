# ProductSignal — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles analyst|experimenter|admin) and status codes as the other apps; lock order
(idempotency key, then experiment version rows by id, then unit rows by id), 409 `CONCURRENT_UPDATE` after three
deadlock retries; actor-bound idempotency with `dataset_version` in the payload hash (409 `STALE_DATASET_VERSION`).
Prefix `/api/v1/productsignal`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/validate-tracking | raw → canonical events | schema, dedup, unknown identity, delayed | slice |
| C02 | POST …/commands/resolve-identity | anonymous → linked | time-aware link, rule version | slice |
| C03 | POST …/commands/define-funnel | draft → versioned funnel | ordered steps, max gap, window | slice |
| C04 | POST …/commands/assign-experiment | eligible unit → fixed variant | idempotent per unit; conflict 409 | slice |
| C05 | POST …/commands/record-exposure | assigned → exposed | exposed_at ≥ assigned_at | slice |
| C06 | POST …/commands/freeze-analysis-plan | draft → registered plan | before any outcome read; config_hash | slice |
| C07 | POST …/commands/check-maturity | cohort → eligible observation | 7-day / 35-day windows complete | slice |
| C08 | POST …/commands/analyze-experiment | frozen plan → results | ITT, SRM first, interval, run log | slice |
| C09 | POST …/commands/review-guardrails | result → decision evidence | prespecified windows | slice |
| C10 | POST …/commands/record-decision | evidence → ship/stop/inconclusive | frozen plan, SRM OK, no product write | slice |
| R | GET …/data/{entity} | reads | stable ordering, cursor | slice |
| M | GET …/metrics?from=&to=&cutoff=&experiment_version_id=&group_by= | the twelve metrics | half-open window | slice |

Roles: C01–C03 analyst, experimenter, admin; C04–C06 experimenter, admin; C07–C09 analyst, experimenter, admin;
C10 experimenter, admin. Reads need no actor.

## D-10 additions (second review)
* C04, C05, C10: `assigned_at`, `exposed_at`, `decided_at` are stamped with the API clock. An admin may pass the field together with
  `"backfill": true` (403 `BACKFILL_ADMIN_ONLY` for any other role, 422 `BACKFILL_FLAG_REQUIRED` for one without the other, 422
  `ASSIGNED_AT_IN_FUTURE` / `EXPOSED_AT_IN_FUTURE` / `DECIDED_AT_IN_FUTURE`); the audit row records `backfill` and the instant.
* C04: 422 `OUTCOME_BEFORE_ASSIGNMENT` (the unit already has an `activated` event; admin backfill excepted), 422
  `ASSIGNMENT_BEFORE_PUBLISHED_RUN`; C05: 422 `EXPOSURE_BEFORE_PUBLISHED_RUN`; C10: 422 `DECIDED_BEFORE_RUN`.
* C01: `event_at` after the clock is a rejected row `EVENT_IN_FUTURE`; an admin-stated `received_at` before `event_at` is
  `RECEIVED_BEFORE_EVENT`.
* C06: 422 `VARIANTS_NOT_TWO` (allocation must be exactly control and treatment), 422 `FROZEN_AT_BACKDATED` (before the latest audit
  instant of the version), `FROZEN_AT_IN_FUTURE`.
* C07, C08 and GET /metrics: 422 `CUTOFF_IN_FUTURE`.
* GET /metrics: `group_by=variant` with an experiment_version_id that has no frozen plan is 409 `PLAN_NOT_FROZEN`; without a frozen
  plan `metrics.experiment` is null and the warning `EXPERIMENT_WITHHELD_PLAN_NOT_FROZEN` says why.
* C10: every refusal writes a `record-decision-refused` audit row.
