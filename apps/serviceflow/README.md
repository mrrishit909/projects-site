# ServiceFlow — backend (Mode A: Python domain + PostgreSQL + FastAPI)

Contract v1 (`docs/contracts.md`, D-01..D-05), routes in `docs/api-contract.md`. The domain is standard library only;
the API adds FastAPI, pydantic and psycopg. Nothing here imports another lab app.

```
domain/serviceflow/   contract, errors, timeutil, models, events, ingest, metrics, simulation, pipeline
data/                 migrate.py, seed.py, migrations/0001_schema.sql, 0002_constraints.sql, sql/reference_metrics.sql
api/                  app, db, schemas, commands, reads, errors     (prefix /api/v1/serviceflow)
tests/                golden, variants, rules, migrations, SQL reference, API commands and reads, adversarial P04-TEST-01..12
```

Run: `DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/serviceflow ../../.venv/bin/python -m pytest -q`
(without `DATABASE_URL` the database tests skip and the pure-domain tests still run) and `python tests/reference_check.py`.

## Domain
* **Exact arithmetic.** Instants are UTC; minutes are `Fraction`s rendered with 4 decimals, rates with 6 (`ROUND_HALF_UP`
  once, at the end), so a tie rounds like the SQL.
* **events.py** replays one ticket's log ordered by `(occurred_at, event_id)` into cycles: created, queued, service
  intervals (open at `service_started`/`resumed`, close at `paused`/`transferred`/`resolved`/`abandoned`), pauses,
  transfers (the arrival never moves; the wait leg restarts per queue), resolutions and reopens (a reopen links the prior
  cycle; the ticket is still one customer contact). The replay is tolerant: golden t-001 carries a `queued` stamp one
  second AFTER its service began.
* **metrics.py** `compute_metrics(pop, window, cutoffs)` returns exactly the keys of `expected.json`; `group_metrics` by
  queue, priority, agent or channel; `disclosures` carries what must sit beside the numbers (reopens, bot events ignored,
  transfers, the P90 rule, open overdue, CSAT nonresponse).
* **simulation.py** discrete-event simulator: `agents` servers, `fifo` or `fifo_within_priority` (non-preemptive), deterministic
  or exponential service, explicit arrivals or Poisson, warm-up excluded from statistics, horizon, seeded `random.Random` with
  three independent streams (arrivals, priorities, service) generated before dispatch so two policies share a demand path
  (common random numbers), replications with seeds `seed + r`, `compare_policies`, and `holdout_report` (intensity fitted
  on the training window only; a change is reported, never hidden).
* **ingest.py** `validate_batch(raw, base=None)`; reasons AGENT_NOT_QUALIFIED, CONCURRENCY_EXCEEDED, BOT_AS_HUMAN_REPLY,
  TRANSFER_RESETS_ARRIVAL, UNKNOWN_REFERENCE, MALFORMED_RECORD, DUPLICATE_ID; dependents of a rejected ticket carry
  TICKET_REJECTED. BOT_AS_HUMAN_REPLY rejects that event only; the three ticket rules reject the ticket row and its events and surveys.

## Decisions the contract left open (assumptions)
1. **Overlap is an application rule, not a trigger** (`0002_constraints.sql` says why): intervals are derived from a log that accepts late
   arrivals, so a row trigger would refuse valid out-of-order loads. Domain ingest and C03/C05(resume) check it, serialised per agent by
   a row lock; `tests/test_adversarial.py::test_p04_test_04*` and the race test cover it.
2. Handling and occupancy numerators are service intervals clipped to the window (open ones run to the window end). Golden values are unchanged.
3. Resolution = final resolution minus the ORIGINAL arrival; first response = first human reply minus arrival; wait (to first service) = first service start minus the ORIGINAL arrival.
4. Backlog and open overdue exclude abandoned tickets (they left the queue); overdue is read at the window end.
5. CSAT, invitation and response rates are over the surveys of tickets completed in the window.
6. `queue` in a group is the ticket's current queue; `agent` is the agent of the ticket's last service interval. Staffing figures exist only for
   `agent` groups (null otherwise).
7. Simulation: arrivals at or after the horizon are not generated, no service starts at or after it (such tickets are `censored`), a service begun
   runs to completion. Events are listed in the golden order (all `service_started` by ticket, then all `resolved`).
8. Roles `analyst|supervisor|admin`: ingest, simulation and comparison are open to all; C02-C06 and `resolve-ticket` need supervisor or admin (403 `ROLE_FORBIDDEN`).
9. Recorded breaks (`shift_breaks`, loaded by data load only) block C03; metrics keep the D-05 rule (break deducted only when the window covers the shift).
10. C05 "SLA policy differentiates": pausing needs an SLA policy for the ticket's priority (422 `SLA_POLICY_MISSING`); handling stops, SLA clocks keep running.

## API
C01 `ingest-ticket-events`, C02 `assign-queue` (422 `QUEUE_SKILL_MISMATCH`), C03 `start-service` (422 `AGENT_NOT_IN_SHIFT`, `AGENT_ON_BREAK`,
`AGENT_NOT_QUALIFIED`, `CONCURRENCY_EXCEEDED`), C04 `transfer-ticket`, C05 `pause-work` and `resume-work`, C06 `reopen-ticket`, C08 `run-simulation`,
C09 `compare-policies`, addition `resolve-ticket`; `GET /data/{entity}`; `GET /metrics?from=&to=&cutoff=&group_by=`.
**C07 `build-shift-scenario` and C10 `export-recommendation` answer 501 `NOT_IMPLEMENTED`.** Same envelopes and status codes as the other apps; 401 without
`X-Actor-Id`, 403 for a role outside the three; actor-bound idempotency (same key, other actor or other payload: 409; instants normalised); a state conflict
is 409 `INVALID_STATE`; deadlock or serialization failure is retried three times, then 409 `CONCURRENT_UPDATE`.
**D-08 lock order:** idempotency key, then ticket rows sorted by id, then agent rows sorted by id.
