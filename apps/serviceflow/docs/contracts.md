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

## D-05 Fixture-driven clarifications (2026-10-26, adopted from A-027)
Backlog at a cutoff counts arrived tickets not yet resolved, including those in service.
First-response eligibility = tickets with a human reply; bot replies never count. The break is
deducted from staffed time only when the window covers the whole shift (a pro-rata or
declared-interval rule is a later decision). `abandonable_channels` is declared in the
inputs; the survey invitation rate is over resolved tickets. Dependents of a rejected ticket
carry `TICKET_REJECTED`.

## D-06 Backend clarifications (2026-10-26, adopted from A-028)
Overlap of an agent's intervals is an application check (domain ingest and C03/resume under an
agent row lock, race-tested), not a row trigger, because the log accepts late arrivals. Lock
order: idempotency key, then ticket rows by id, then agent rows by id; a deadlock is retried
three times, then 409 `CONCURRENT_UPDATE`. Roles: ingest, simulation and compare are open to
analyst, supervisor and admin; C02–C06 and `resolve-ticket` need supervisor or admin (403
`ROLE_FORBIDDEN`). Handling is clipped to the window; resolution and wait are measured from the
original arrival; backlog and overdue exclude abandoned tickets; CSAT counts only tickets
completed in the window; staffing figures exist only for `group_by=agent`. Simulation services
start only before the horizon and tickets still waiting are reported as censored; events are
listed as all starts, then all resolves. `resume-work` and `resolve-ticket` are added commands;
`shift_breaks` is a data-load-only table that blocks C03 inside a break. A ticket whose priority
has no SLA policy is refused with 422 `SLA_POLICY_MISSING`; handling stops on pause, SLA clocks
keep running. C09 `compare-policies` pairs replications on one seed and reports a 95% t-interval
labelled an estimate. C07 and C10 return 501 `NOT_IMPLEMENTED`. Open: the metrics default
window (currently first arrival to last event plus one second, echoed in `meta`) and the ingest
command's full-population reload, which is lab-scale only.

## D-07 Synthetic world (2026-10-26, adopted from A-029)
The published snapshot holds 3,826 tickets, not the specification's "about 6,000": with every event field
present (nulls included, so the files match the fixture's exact shape) one event row costs about 165 bytes and
6,000 tickets would exceed the 5 MB cap the same specification sets, so the cap wins and the deviation is
disclosed here and in `data/README-generator.md` (knob `TICKETS_TARGET`). `created` carries the queue; `queued`
appears only when a reopened ticket re-enters its queue; one human reply per ticket. `shift_breaks.json` is a
thirteenth entity file, hashed with the rest (no loader in `seed.py` yet). Zones: Europe/Berlin and
America/Santiago, shifts declared in local wall-clock time and converted with zoneinfo; the DST weekend is
2026-09-05/06 in Santiago (switch 2026-09-06T04:00Z); the night crew's Saturday shift is 420 real minutes and
agt-018's 480-minute row is INJ-08. Onboarding is `fifo`, billing and technical `fifo_within_priority`; across
queues `fifo` tickets rank as P2; a transfer restarts the wait in the new queue; dispatch takes the longest-idle
agent; breaks start at the first idle moment after 42–55 % of the shift. SLA targets (first response /
resolution, wall clock): P1 15/240, P2 60/1440, P3 240/4320 minutes. Holdout arrivals are Poisson × 1.2; the
realisation is the first of a fixed, disclosed series of attempts within 1.5 points of +20 %. 15 % of technical
P1 tickets are major incidents paused 2.7–5 h. Chat and phone customers may abandon before service. One survey
per ticket on the final resolution with response skewed by score (INJ-09). Three simulation runs from
training-window data; the cold-start run is replay-only (EV-07). INJ-02 (a reopen recorded as a new customer)
is not detectable by the domain and stays an analyst check in the manifest. Event ids follow receive order, so
about 1 % of replies and pauses are late arrivals. Known behaviour, not fixed: D-05 deducts no break from a
shift a window cuts, so staffed minutes of adjacent windows exceed the whole (447,450 vs 447,990); a
declared-interval rule over `shift_breaks` is a later decision.

## D-08 Static site (2026-10-26, adopted from A-030)
The site serves the published snapshot over the window [2026-07-06T00:00Z, as_of + 1 s); training is weeks 1–8 and
holdout weeks 9–12 as the manifest's `training_weeks` declare. Timestamps are integer epoch seconds; a non-zero
sub-second part is refused at ingest. `contract_version` "v1" in the manifests maps to the integer 1 in the inputs.
The simulation studio compares the three published runs with `public/reference/simulation-runs.json`, produced by one
run of the Python simulator, and `scripts/snapshot-reference.json` holds Python digests of the snapshot metrics so the
TypeScript golden check needs no Python in CI; the seeded generator (SHA-512 seeding, Mersenne Twister, expovariate,
choices) is reimplemented and checked against CPython 3.11. P90 of wait and resolution, per-priority P90, abandoned
counts and the P90/mean ratio are additions beyond the 28 published keys and are labelled as such. The shift grid's
occupancy uses the recorded `shift_breaks` intervals and says that the published metric follows D-05 instead. The
simulation interval's square root is exact at 1e-8 where Python uses a float. Queues, Compare and Surveys are stubs
that show no figures. The evidence route runs the golden checks live and claims no CI result.
