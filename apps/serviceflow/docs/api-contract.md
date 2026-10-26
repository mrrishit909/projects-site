# ServiceFlow — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles analyst|supervisor|admin) and status codes as the
other apps; lock order and 409 on deadlock; actor-bound idempotency. Prefix `/api/v1/serviceflow`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/ingest-ticket-events | raw history → canonical events | late arrivals preserved; duplicates rejected; a batch with events for an existing ticket needs a supervisor or admin (403 `ROLE_FORBIDDEN`); an agent starts service only inside a shift (`SERVICE_OUTSIDE_SHIFT`) | slice |
| C02 | POST …/commands/assign-queue | new → queued | skill eligibility of the queue | slice |
| C03 | POST …/commands/start-service | queued → in_service | agent available (shift, no break), qualified, under concurrency; `resume-work` applies the same availability checks | slice |
| C04 | POST …/commands/transfer-ticket | queue A → queue B | original arrival preserved | slice |
| C05 | POST …/commands/pause-work | in_service → waiting_customer | SLA policy differentiates | slice |
| C06 | POST …/commands/reopen-ticket | resolved → reopened | links prior cycle | slice |
| C07 | POST …/commands/build-shift-scenario | baseline → candidate schedule | availability and breaks respected | extension |
| C08 | POST …/commands/run-simulation | frozen config → replicated outcomes | warm-up and seeds fixed | slice (golden case) |
| C09 | POST …/commands/compare-policies | baseline vs proposal | same demand sample | extension |
| C10 | POST …/commands/export-recommendation | reviewed scenario → memo | uncertainty and targets embedded | extension |
| R | GET …/data/{entity} | reads | stable ordering | slice |
| M | GET …/metrics?from=&to=&cutoff=&group_by= | arrival/completion rates, backlog, first response, P90, SLA, occupancy, CSAT | half-open window; a cutoff counts events at its own instant; `group_by=queue` is the ticket's final queue; warnings: `SLA_CALENDAR_IGNORED`, `CUTOFF_AT_OR_AFTER_WINDOW_END`, `SERVICE_DURING_BREAK` | slice |

## Envelope and review corrections (D-09)
* `dataset_version` in the request envelope must equal the newest `dataset_versions` row (read it from `meta.dataset_version`):
  otherwise 409 `STALE_DATASET_VERSION` with `context.current` and `context.requested`, and nothing is written. It is part of
  the idempotency payload hash: the same `idempotency_key` with another version is 409 `IDEMPOTENCY_KEY_REUSED`. A database with
  no `dataset_versions` row accepts any version.
* Roles: C01 is open to analyst, supervisor and admin for NEW tickets, reference data and surveys; a batch that carries
  `ticket_events` for a ticket that already exists is 403 `ROLE_FORBIDDEN` for an analyst (C02-C06 and `resolve-ticket` already
  were). The check runs before any write.
* Ingest reason codes added: `SERVICE_OUTSIDE_SHIFT`, `RESUME_BEFORE_SERVICE`. Instants need seconds (`...T09:20:00Z`); integer
  fields take integral numbers; seeds are within +-(2^53 - 1) (422 `FIELD_INVALID` otherwise).
* Wait means wait to first service.
