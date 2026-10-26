# ServiceFlow — business contracts, version 1 (2026-10-26)

Decision owner: coordinator (Fable 5.1). Spec: `projects/04-serviceflow.md`, SHA-256
`ee79cf36…d40a` at pack commit `fe5f7981`. Rules cite the requirement they satisfy; changing one
bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
Which staffing or routing change meets support targets under uncertain workload?
(P04-GOAL-01). Primary user: an operations analyst planning next quarter's shifts and queue
routing. Non-goals: a live ticketing system, real customer data, claims of realised staffing
benefits (P04-DOMAIN-06).

## D-01 Events, queues and discipline
* Ticket history is an ordered canonical event log (`ticket_events`, immutable, late arrivals
  preserved with their occurred_at, P04-FLOW-01). States: `created → queued → in_service ↔
  waiting_customer → resolved → reopened → queued …`; a reopen links the prior resolution cycle
  and the ticket stays ONE customer contact (P04-TEST-02).
* Within a queue, service discipline is **FIFO within priority class** unless the queue's
  `priority_policy` overrides it (P04-DOMAIN-01). A transfer preserves the original arrival
  instant; waiting restarts in the new queue but the first-response and resolution clocks
  do not (P04-FLOW-04, P04-TEST-08).
* An agent may start service only when available (inside a shift, not on break) and qualified
  (`agent_skills` effective at that instant, P04-FLOW-03, P04-TEST-03); concurrency is bounded
  per agent by a declared `max_concurrent` (default 1, P04-TEST-04).

## D-02 Durations and clocks
* All instants are UTC; display calendars by IANA zone; shift durations are computed from
  UTC instants so a daylight-saving day does not stretch or shrink a shift (P04-TEST-07).
* First response = first **human** reply − arrival; automated acknowledgements (`actor_id`
  of a bot) never count (P04-MET-04, P04-TEST-01).
* Resolution duration = final resolution − arrival; reopened tickets report the last cycle
  with the reopen count disclosed (P04-MET-05). Handling duration = Σ active service
  intervals (idle and `waiting_customer` excluded, P04-MET-06).
* P90 first response = the 90th percentile with the nearest-rank method (sort ascending,
  index ⌈0.9 n⌉), documented on screen (P04-MET-07). Average waits are always shown beside
  the P90 and the per-priority tail (P04-TEST-10).
* SLA compliance = eligible tickets within policy ÷ eligible tickets; open overdue tickets
  are counted and shown separately, never dropped (P04-MET-08, P04-TEST-06).

## D-03 Capacity and occupancy
* Staffed available time = Σ (shift length − break minutes) inside the window; breaks are
  never capacity (P04-TEST-05). Agent occupancy = active handling ÷ staffed available time,
  bounded by concurrency; null when staffed time is 0 (P04-MET-09).
* Abandonment rate only on channels that can abandon; CSAT = positive (score ≥ 4 of 5)
  ÷ valid responses with invitation and response rates shown (P04-MET-10/11, P04-TEST-11).

## D-04 Simulation
* The golden case (P04-GOLD-01): one agent, three tickets at minute 0, deterministic
  10-minute service, FIFO → service starts 0, 10, 20; waits 0, 10, 20; mean wait 10; last
  completion 30. The simulator must reproduce this before random arrivals are used.
* Arrival distributions are estimated on the training window only and validated on a
  separate holdout window; a changed intensity in the holdout is reported, not hidden
  (P04-DOMAIN-02/03, P04-TEST-12).
* Runs declare seed, warm-up minutes and horizon; warm-up observations are excluded from
  every statistic (P04-TEST-09); policies are compared on the same seeds and demand paths
  (P04-DOMAIN-05); results carry replication count and a confidence interval (P04-MET-12).
* Simulated wait improvement is an estimate and is labelled as one everywhere.

## Mode disclosure
Mode A: Python domain (event log, metrics, discrete-event simulator) + PostgreSQL + FastAPI
verified on GitHub-hosted runners. Mode B: TypeScript mirror over the published snapshot; the
simulation studio runs in the browser on a copy with the published seed; nothing persists.
