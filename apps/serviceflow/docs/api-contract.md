# ServiceFlow — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles analyst|supervisor|admin) and status codes as the
other apps; lock order and 409 on deadlock; actor-bound idempotency. Prefix `/api/v1/serviceflow`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/ingest-ticket-events | raw history → canonical events | late arrivals preserved; duplicates rejected | slice |
| C02 | POST …/commands/assign-queue | new → queued | skill eligibility of the queue | slice |
| C03 | POST …/commands/start-service | queued → in_service | agent available, qualified, under concurrency | slice |
| C04 | POST …/commands/transfer-ticket | queue A → queue B | original arrival preserved | slice |
| C05 | POST …/commands/pause-work | in_service → waiting_customer | SLA policy differentiates | slice |
| C06 | POST …/commands/reopen-ticket | resolved → reopened | links prior cycle | slice |
| C07 | POST …/commands/build-shift-scenario | baseline → candidate schedule | availability and breaks respected | extension |
| C08 | POST …/commands/run-simulation | frozen config → replicated outcomes | warm-up and seeds fixed | slice (golden case) |
| C09 | POST …/commands/compare-policies | baseline vs proposal | same demand sample | extension |
| C10 | POST …/commands/export-recommendation | reviewed scenario → memo | uncertainty and targets embedded | extension |
| R | GET …/data/{entity} | reads | stable ordering | slice |
| M | GET …/metrics?from=&to=&cutoff=&group_by= | arrival/completion rates, backlog, first response, P90, SLA, occupancy, CSAT | half-open window | slice |
