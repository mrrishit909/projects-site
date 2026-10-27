# ChangeWorks — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles analyst|sponsor|admin) and status codes as the other apps; lock order
(idempotency key, then initiative rows by id, then scenario rows by id), 409 `CONCURRENT_UPDATE` after three deadlock
retries; actor-bound idempotency with `dataset_version` and the role in the binding (409 `STALE_DATASET_VERSION`);
server-stamped instants. Prefix `/api/v1/changeworks`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/establish-baseline | unmeasured → versioned baseline | evidence and assumptions separated; approval freezes the version | slice |
| C02 | POST …/commands/assess-opportunity | candidate → scored option | weights and rationale explicit | slice |
| C03 | POST …/commands/build-cash-flows | assumptions → dated model | one-time vs recurring; rate basis = period basis; benefits after deployment | slice |
| C04 | POST …/commands/map-impacts | initiative → affected groups | operating changes described | slice |
| C05 | POST …/commands/assess-readiness | group → dimension assessment | synthetic labels; scores 1..5 | slice |
| C06 | POST …/commands/plan-roadmap | options → feasible schedule | cycle refused; shared capacity checked | slice |
| C07 | POST …/commands/select-scenario | compared options → proposed portfolio | double-count residual explained; never "funded" | slice |
| C08 | POST …/commands/record-adoption | observation → adoption series | denominator preserved | slice |
| C09 | POST …/commands/track-benefits | forecast → observed comparison | attribution caveat; same benefit type | slice |
| C10 | POST …/commands/revise-forecast | baseline → new forecast version | original approval never overwritten | slice |
| R | GET …/data/{entity} | reads (12 entities of section 03 plus resources, resource_allocations, impact_mappings, training_completions, forecast_versions) | stable ordering, cursor | slice |
| M | GET …/metrics?scenario_id=&from=&to=&as_of= | the twelve metrics | half-open window | slice |

Roles: C01 (create) analyst, sponsor, admin; C01 (approve) sponsor, admin; C02–C06, C08, C09 analyst, sponsor,
admin; C07, C10 sponsor, admin. Reads need no actor.
