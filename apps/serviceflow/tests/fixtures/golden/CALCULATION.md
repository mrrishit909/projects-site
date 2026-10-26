# ServiceFlow golden calculation (contract v1, decisions D-01..D-04)

Independent of application code. `../../reference_check.py` recomputes every number below from `inputs.json`
and compares it with `expected.json`. Durations are decimal strings with 4 decimals in MINUTES, rates 6 decimals.

## The spec sentence [P04-GOLD-01]

> One agent and three tickets arriving at minute 0 with deterministic 10-minute service under FIFO: service starts at
> 0, 10, 20; waits are 0, 10, 20; mean wait = 10 minutes; final completion at minute 30.

## Part (a): the same case as observed history, 2026-07-06

Tickets t-001..t-003, queue q-001 (FIFO within priority), priority P2, all created 09:00:00Z, channel email.
Each has a bot acknowledgement at 09:00:05Z (actor bot-001, never a first response, D-02). agt-001 starts service
at 09:00, 09:10, 09:20, replies as a human at the same instants, resolves at 09:10, 09:20, 09:30.
Shift 09:00-17:00Z, break 30, max_concurrent 1; skill s-001 required by q-001 and held by agt-001.
SLA P2: first response 15 min, resolution 60 min. Window [09:00Z, 10:00Z) = 1 hour.

| Ticket | First response | Wait (start - created) | Resolution | Handling |
|---|---|---|---|---|
| t-001 | 0 | 0 | 10 | 10 |
| t-002 | 10 | 10 | 20 | 10 |
| t-003 | 20 | 20 | 30 | 10 |

* Rates: 3 arrivals / 1 h = "3.000000"; 3 completions / 1 h = "3.000000".
* Backlog = created at or before the cutoff and not resolved by it (a ticket in service is unresolved):
  09:05 -> 3; 09:25 -> 1 (only t-003); 10:00 -> 0.
* Mean first response (0+10+20)/3 = "10.0000"; P90 nearest rank, n=3, ceil(0.9*3)=3rd value = "20.0000".
* Mean wait "10.0000"; mean resolution (10+20+30)/3 = "20.0000"; handling total "30.0000".
* SLA first response (<= 15): t-001, t-002 within, t-003 at 20 breaches, 2/3 = "0.666667" (the honest figure).
  SLA resolution (<= 60): 3/3 = "1.000000". Open overdue at cutoff: 0.
* Staffed available minutes in the window: shift overlap 60; no break interval is recorded, so the break is
  deducted only when the window covers the whole shift (assumption) -> "60.0000". Whole shift 480 - 30 = "450.0000".
* Occupancy 30 / 60 = "0.500000". Abandonment: email cannot abandon -> null. CSAT: one valid response (score 5,
  positive when >= 4) -> "1.000000". Invitation rate: 2 invited (t-001, t-003) of 3 resolved = "0.666667";
  response rate 1 of 2 invited = "0.500000".

## Part (b): the simulation

sim-001: seed 1, warm-up 0, horizon 60, config {agents 1, service_minutes 10, arrivals [0,0,0], fifo}.
Service starts 0, 10, 20; resolved 10, 20, 30; waits 0, 10, 20; mean wait 10; final completion minute 30
("0.0000" ... "30.0000"). Part (b) is the same arithmetic as part (a), by a different route.

## Variants

* variant-rejected: adds t-004 (service_started by agt-002, who lacks s-001: AGENT_NOT_QUALIFIED) and t-005
  (second service_started for agt-001 at 09:05 while t-001 is in service until 09:10: CONCURRENCY_EXCEEDED).
  Both tickets, their 6 events and t-004's survey are rejected (events and survey: TICKET_REJECTED); every metric
  and the simulation equal the golden values. agt-002 has no shift, so staffed time is unchanged.
* variant-empty: queues, agents, shifts and SLA policies only. Rates "0.000000", backlog 0, means/P90/compliance/
  CSAT/invitation/response/abandonment null, handling "0.0000", occupancy 0 / 60 = "0.000000", staffed "60.0000",
  empty_population true, no simulation.
