# RetentionLab — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles scientist|analyst|admin) and status codes as the other apps; lock order
(idempotency key, then training-run rows by id, then scenario rows by id), 409 `CONCURRENT_UPDATE` after three
deadlock retries; actor-bound idempotency with `dataset_version` and the role in the binding (409
`STALE_DATASET_VERSION`); server-stamped instants. Prefix `/api/v1/retentionlab`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/build-point-in-time-features | cutoff → features | event_at and available_at both before the cutoff; registry only | slice |
| C02 | POST …/commands/define-label | mature horizon → outcome | censored rows excluded | slice |
| C03 | POST …/commands/split-evaluation | time ranges → train / validation / test | label-window and group purge | slice |
| C04 | POST …/commands/fit-preprocessing | training only → fitted transformer | refuses non-training rows | slice |
| C05 | POST …/commands/train-baseline | training rows → rule, random, logistic | simple reference kept | slice |
| C06 | POST …/commands/calibrate-model | validation only → calibration mapping | test untouched | slice |
| C07 | POST …/commands/score-accounts | frozen model → probabilities | model and feature versions cited | slice |
| C08 | POST …/commands/prioritize-outreach | scores → capacity-limited draft queue | K ≤ population; drafts only | slice |
| C09 | POST …/commands/simulate-economics | queue + assumptions → expected value | labelled hypothetical | slice |
| C10 | POST …/commands/monitor-refresh | new cohort → drift and performance | immature labels counted | slice |
| R | GET …/data/{entity} | reads (12 entities of section 03 plus feature_registry, split_assignments, scoring_publications) | stable ordering, cursor | slice |
| M | GET …/metrics?training_run_id=&cutoff_id=&scenario_id=&from=&to=&as_of= | the twelve metrics | half-open window | slice |

Roles: C01–C07, C10 scientist, admin; C08, C09 scientist, analyst, admin. Reads need no actor.
