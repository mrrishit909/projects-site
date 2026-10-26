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
