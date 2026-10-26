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
  index ⌈0.9 n⌉), documented on screen (P04-MET-07). Wait means wait to first service (D-09). Average waits are always shown beside
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
realisation is the first of a fixed, disclosed series of attempts within 1.5 points of +20 % (a chosen
realisation, see D-09 R4-13). 15 % of technical
P1 tickets are major incidents paused 2.7–5 h. Chat and phone customers may abandon before service. One survey
per ticket on the final resolution with response skewed by score (INJ-09). Three simulation runs from
training-window data; the cold-start run is replay-only (EV-07). INJ-02 (a reopen recorded as a new customer)
is not detectable by the domain and stays an analyst check in the manifest. Event ids follow receive order, so
about 1 % of replies and pauses are late arrivals. Known behaviour, not fixed: D-05 deducts no break from a
shift a window cuts, so the staffed minutes of adjacent windows add up to more than those of the window that holds
them: training 297,870 + holdout 149,640 = 447,510 against 447,450 for the full window (corrected in D-09: 447,450 is
the full window's `staffed_available_minutes`; 447,990 is `staffed_shift_minutes_whole`, every shift net of its
break, which is a different quantity and not the whole of anything adjacent); a declared-interval rule over
`shift_breaks` is a later decision.

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

## D-09 Review corrections (2026-10-26, from the independent review A-031; fixes T-04-07)
Every item names its finding. Where a finding allowed a choice, the choice is here.

**Ingest (Python `ingest.py`, TypeScript `ingest.ts`, one rule set).**
* R4-02 Concurrency is resolved to a fixed point. The sequential pass keeps "earlier start wins; a rejected ticket
  occupies nobody"; afterwards every new ticket rejected for CONCURRENCY_EXCEEDED is re-tried against the tickets that
  stay accepted and is accepted again when all its intervals fit; repeat until nothing changes. A ticket already stored
  (the API's `base`) keeps the verdict of the batch's new events. The snapshot's 70 rejections are unchanged.
* R4-03 Availability (D-01: "an agent may start service only when available"). New reason code
  **SERVICE_OUTSIDE_SHIFT**: a service interval (`service_started` or `resumed`) that opens at an instant inside none of
  the agent's shifts (half-open `[starts_at, ends_at)`, as C03) rejects the ticket and its events and surveys carry
  TICKET_REJECTED. Choice: REJECT, not flag, because the published snapshot has 0 such intervals (checked: 4,976
  intervals, 70 rejections before and after). Only the instant a service opens is tested, not its end. **Breaks**: the
  domain has no break entity (the 12 ingest entities and the golden ingest counts are fixed), so breaks are FLAGGED, not
  rejected: `diagnostics.break_flags` / `breakFlags` list intervals that open inside a recorded break, and the metrics
  read adds a `SERVICE_DURING_BREAK` warning. The snapshot has 0 such intervals, so rejection would also have left it
  unchanged, but it would need a thirteenth ingest entity and a golden change; C03 and `resume-work` refuse it already
  (`AGENT_ON_BREAK`). D-05 keeps the break rule for the staffed-time metric.
* R4-03 `resume-work` applies the same availability checks as C03 (`AGENT_NOT_IN_SHIFT`, `AGENT_ON_BREAK`, 422), then
  concurrency.
* R4-16 New reason code **RESUME_BEFORE_SERVICE**: the first service opener of a ticket's ordered log is a `resumed`.
  The ticket is rejected, so `first_service_at` is never left unset beside an open interval. (A resume that follows a
  `service_started` is untouched; a stricter "a resume needs a pause" rule is not adopted.)
* R4-17 One parsing rule. An instant is `YYYY-MM-DDTHH:MM:SS[.f]` plus `Z` or an offset: **seconds are required** in
  both domains (`09:20Z` is MALFORMED_RECORD in both; the API's `occurred_at` follows the same form). An integer field
  takes a JSON number whose **value** is an integer: `30` and `30.0` are accepted, `30.5`, NaN, a boolean and a string
  are refused, in both. The instruction was "refuse floats", but a JavaScript runtime cannot tell `30.0` from `30` after
  `JSON.parse`, so the only rule both domains can keep is the value rule; Python now accepts `30.0` where it used to refuse
  it. **Seeds** are bounded to +-(2^53 - 1) in both (`SEED_MAX`; the API schema too); the old Python bound was 2^62.
  Sub-second precision stays as D-08 says (Python keeps microseconds, TypeScript refuses a non-zero fraction).

**Metrics and SQL.**
* R4-01 `reference_metrics.sql` `staff` sums over an inner join: with no shift overlapping the window the staffed time is
  0.0000 and the occupancy null (it was the whole window, because `least`/`greatest` ignore NULLs).
* R4-15 The SQL decides "final resolution" on `(occurred_at, event_id)` as Python and TypeScript do; a resolve and a
  reopen at one instant are ordered by event id.
* R4-09 `disclosures.reopened_tickets` and `reopen_events` count the tickets that ARRIVED in the window and those
  COMPLETED in it (once each); `reopened_among_completions` and `reopened_basis` are added. Resolution compliance is
  measured from the ORIGINAL arrival, so a reopened ticket is charged its dormant gap (the time between its resolution and
  its reopen); the SLA and overview pages say so beside the figure.
* R4-10 **Wait means wait to first service** (first `service_started` minus the original arrival, tickets that arrived in
  the window and were served), everywhere: site labels, definitions, docs. `group_by=queue` groups by the ticket's FINAL
  queue (a transferred ticket counts only where it ended); the read says so in `data.group_basis` and the overview page
  says so when grouped by queue.
* R4-18 Calendars are ignored (D-07) and the domain says so: `SLA_CALENDAR_IGNORED` for every SLA policy whose
  `calendar_id` is not `cal-001`, the 24x7 calendar, in the pipeline result's `warnings` (Python and TypeScript) and in
  `warnings` of the metrics read. **Window edge**: the window is half-open `[from, to)` but a backlog cutoff is an
  instant that includes events at that instant, so a cutoff equal to the window end counts an arrival AT the end and drops
  a resolution AT the end, neither of which the window counts (reviewer case c11: backlog 1, not the 2 that
  reconciling to the half-open window would give). Choice: keep the golden semantics and DOCUMENT the edge, and warn
  (`CUTOFF_AT_OR_AFTER_WINDOW_END`) when a cutoff is not before the window end AND counts an arrival or a closing event
  there; a cutoff at the end with nothing there (the usual case, and the metrics read's default) is silent. Making every cutoff strictly inside the window would change golden backlog values.

**API.**
* R4-04 C01 `ingest-ticket-events` needs a supervisor or admin when a batch carries events for a ticket that already
  exists (403 `ROLE_FORBIDDEN`, nothing written); an analyst ingests new tickets, reference data and surveys. The
  recorded replay EV-01 in `data/injection-events.json` therefore runs as a supervisor.
* R4-05 `dataset_version` is checked and hashed as in SupplyScope: a request naming a version other than the newest
  `dataset_versions` row is 409 `STALE_DATASET_VERSION` before the handler runs (nothing written); a database with no row
  accepts any version; the version is part of the idempotency payload hash, so the same key and body with another version is
  409 `IDEMPOTENCY_KEY_REUSED`. The table and the seeded row already existed (migration 0001, `data/seed.py`): no
  migration 0003.

**Simulation page and replications (R4-11, R4-14).** One run is one draw. The reference file now holds 50 replications per
published run on seeds `seed + r` with the mean of the replication means and a 95 % Student-t interval, and the paired
difference sim-002 (plus one agent) minus sim-001 (baseline) on the same 50 seeds; the browser recomputes all of it and the
golden check compares. sim-003 does NOT share the demand path, by design (another arrival intensity); the reference states
it. The model gives the technical queue five dedicated servers; in the snapshot four of the five technical agents on shift at
the first training Monday bind also hold another queue's skill, and about 29 % of the handling minutes started in the Monday
09:00-11:00 bind of the training weeks by technical-skilled agents went to other queues (`docs/uat-evidence.md`). Censored
tickets (still waiting at the horizon) are EXCLUDED from the wait statistics and counted separately. The Student-t table now
runs to 50 degrees of freedom (2.010 at 49, which 50 replications use) and uses 2.000 beyond; it used 1.96 above 30, which made a 50-replication
interval 2.5 % too narrow.

**Data (R4-13).** The +20 % holdout is a chosen realisation: the generator kept attempt 7 of a fixed series (attempts 0 to 6
gave +12.86, +14.58, +22.82, +16.92, +12.69, +22.02 and +30.46 %; attempt 7 gave +20.10 %; the Poisson noise sd of the
ratio is about 4.3 points over attempts 0..39). `manifest.json` `generator.parameters.arrival_realisation` records the
attempt index and the discarded ratios; `dataset_hash` covers the entity files only and is unchanged
(`944ef91b...cba4`), the thirteen entity files are byte-identical. The case-study, overview and SLA pages label it
"chosen realisation; noise sd about 4 pts".

**Documentation (R4-12).** The D-07 sentence about staffed minutes is corrected above. The Mode-B statement in D-08 stands.
