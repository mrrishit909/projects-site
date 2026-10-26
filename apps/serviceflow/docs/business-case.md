# ServiceFlow: business case (P04-ART-01)

**Every stakeholder, scenario and number here is synthetic or simulated.** Nothing is a claim about a real employer, a real support team, real customers or measured savings (P04-DOMAIN-06, P04-GOAL-12).
Dataset `sf-20261026-20261026` (seed 20261026, generator `dataset_hash` `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4`), contract v1, code revision `43de7f8`.
Three kinds of statement are kept apart throughout: **observed** (the synthetic history, reconciled to `data/sql/reference_metrics.sql` and the Python domain), **simulated** (estimates of a seeded queue model, labelled as estimates) and **hypothetical** (what a real desk might gain; none is claimed).

**How to read it:** this file needs nothing installed. The numbers are quoted from `sql-analysis.md` (observed, query numbers 01-08) and `executive-memo.md` (simulated); `requirements.md` traces each requirement id to code and tests.

## The business decision
**Which staffing or routing change meets support targets under uncertain workload?** (P04-GOAL-01.) The primary user is an operations analyst planning next quarter's shifts and queue routing; the other portfolio roles are BI analyst and transformation analyst (P04-GOAL-02).
Non-goals: a live ticketing system, real customer data, vendor commitments, operational writes, any claim of a realised staffing benefit.

## Business problem
A synthetic support desk ("the desk") runs three queues (billing `q-001`, technical `q-002`, onboarding `q-003`) with 18 agents in Berlin and Santiago, three priorities (P1, P2, P3), four channels (chat, email, phone, web_form) and SLA targets in minutes
(first response / resolution: P1 15 / 240, P2 60 / 1440, P3 240 / 4320). The weekly service review argues from one number, the average wait, and the numbers behind it are wrong in ways the generator plants on purpose (nine injected defects, `data/injection-manifest.json`):
a bot acknowledgement counts as a first response, a transfer restarts the clock, a break counts as capacity, an overlapping assignment is accepted, a clock-change shift is mis-sized, a reopen becomes a new customer, a simulation keeps its warm-up, and survey non-response hides unhappy customers.
The staffing proposal that follows is an estimate whose history and whose model are measured differently, so nobody can say whether one more agent on Monday morning would meet the target. ServiceFlow fixes the measurement first (one event log, one set of definitions, an independent recomputation) and then compares changes on the same demand.

What the synthetic history shows (OBSERVED, accepted tickets, 2026-07-06 to 2026-09-27; `sql-analysis.md`):
* 3,817 accepted tickets (9 more rejected with their dependants, 70 rows in all), 3,608 completions, mean first response 28.0046 minutes with a **P90 of 44.1500**, mean wait to first service 25.5073, mean resolution 164.5909 (P90 294.5833).
* SLA compliance 0.950498 for the first response and 0.978104 for the resolution overall, but **P1 is at 0.823789** and the technical queue is the weakest (first response 0.923291, resolution 0.959525; technical P1 resolution 0.767606).
* Agent occupancy 0.424263 overall, from 0.207308 to 0.649409 by agent; the Monday 09-11 UTC block carries 1.3259 arrivals per staffed hour against 0.4292 for the median block; the holdout weeks arrive 20 % harder.
* The designed relationships are present: a technical P1 resolution tail with a P90 of 619.4167 minutes against a mean of 247.1852, a Monday bind, and a holdout at +20 %.

## Simulated stakeholders (roles, not people)
| Role (simulated) | Need | Decision criterion | Entities, metrics, commands |
|---|---|---|---|
| Operations analyst (primary user) | A comparison of staffing or routing changes on the same demand, with the evidence behind it | A change is preferred when its paired simulated improvement has a 95 % interval that excludes zero and it does not worsen the P90 | `simulation_runs`, `simulation_events`; P04-MET-12; C08 `run-simulation`, C09 `compare-policies` |
| Support supervisor | Assign, start, pause, transfer, reopen, resolve without breaking the rules | Skill, shift, break and concurrency rules hold; the arrival never moves | `tickets`, `ticket_events`, `agent_skills`, `shifts`; C02-C06, `resume-work`, `resolve-ticket` |
| Workforce planner | Shifts and breaks that count as capacity honestly | Staffed time = shift minus the declared break (D-03, D-05); a break is never capacity | `shifts`, `shift_breaks`; P04-MET-09; C07 `build-shift-scenario` (501, not built) |
| Support agent | Work that matches skill and a bounded concurrency | `agent_skills.effective_from`, `agents.max_concurrent` | `agents`, `agent_skills`, `queue_skills` |
| Customer (simulated) | A reply and a resolution inside the target; not to wait until giving up | First-response and resolution compliance; abandonment on chat and phone | `tickets`, `surveys`; P04-MET-04, 05, 08, 10, 11 |
| BI analyst | A reusable metric model with its definitions | Every measure equals the independent recomputation | `bi-package.md`, `artifacts/bi/` |
| Data steward / QA | Defects found and refused, not hidden | Every refused row has a reason; the injected defects are found | `rejected_records`; C01 `ingest-ticket-events`; query 08 |

## Scope
In scope: an immutable ordered event log reconstructed into a state per ticket (a reopen is one customer contact); FIFO within priority; wait, first response and resolution measured from the original arrival; staffed time with breaks deducted; SLA compliance with open overdue tickets counted separately; P90 always beside the mean;
arrival intensities estimated on the training weeks and validated on the holdout weeks; a seeded simulator with a declared warm-up and horizon, replications and a paired comparison on common random numbers; an independent SQL recomputation of every metric; a static interactive demo over a published snapshot.
Out of scope: submitting or persisting anything from the public site, real customer data, forecasts of staffing cost, the shift-scenario builder (C07) and the recommendation export (C10), which return 501.

## Current-state and future-state process
**Current (simulated):** a spreadsheet and a dashboard of averages; a ticket's clock restarts on transfer; a bot reply counts as first response; breaks are counted as available time; the staffing proposal is a simulation with its warm-up left in.
**Future:**
| Step | Command or read | What it does | Rule | Built |
|---|---|---|---|---|
| 1 | C01 `ingest-ticket-events` | raw history to ordered canonical events; late arrivals keep their time; duplicates and defects refused with a reason | P04-FLOW-01, P04-TEST-01/03/04/08 | yes |
| 2 | C02 `assign-queue` | new to queued, only to an active queue that at least one active agent can serve (every required skill effective at that instant; else 422 `QUEUE_SKILL_MISMATCH`) | P04-FLOW-02 | yes |
| 3 | C03 `start-service` | queued to in service: agent inside a shift, not on a break, qualified, under concurrency | P04-FLOW-03, P04-TEST-03/04/05 | yes |
| 4 | C05 `pause-work`, `resume-work` | in service to waiting_customer and back; handling stops, SLA clocks keep running | P04-FLOW-05 | yes |
| 5 | C04 `transfer-ticket` | queue A to B; the arrival is preserved, only the per-queue wait restarts | P04-FLOW-04, P04-TEST-08 | yes |
| 6 | `resolve-ticket`, C06 `reopen-ticket` | resolved and reopened; the reopen links the prior cycle | P04-FLOW-06, P04-TEST-02 | yes |
| 7 | `GET /metrics` | arrival and completion rate, backlog, first response, P90, SLA, occupancy, abandonment, CSAT for a window, cutoff and grouping | P04-MET-01..11 | yes |
| 8 | C08 `run-simulation` | a frozen config, a declared warm-up, seeds; replicated outcomes | P04-FLOW-08, P04-MET-12, P04-TEST-09 | yes |
| 9 | C09 `compare-policies` | baseline against proposal on the same seeds; a paired 95 % interval, labelled an estimate | P04-FLOW-09, P04-DOMAIN-05 | yes |
| 10 | C07 `build-shift-scenario`, C10 `export-recommendation` | a candidate schedule; the memo export with uncertainty embedded | P04-FLOW-07, P04-FLOW-10 | **no: 501** |
Exceptions owned: a refused row (data steward), a shift with a declared break of 0 (workforce planner), a conflicting concurrency (supervisor), a replay with a stale dataset version (409).

## Decision criteria
1. **A change is only credited from a comparison on the same demand.** Policies are compared on the same seeds (common random numbers); a scenario with another arrival intensity (the holdout) is not a policy comparison.
2. **The target is the per-ticket SLA in minutes; the compliance share a business requires is an input the data does not supply.** The package reports compliance by priority and queue so any threshold can be applied; an illustration at 0.95 is in the memo and is labelled an assumption.
3. **Means never travel alone.** Every wait and resolution mean is shown with its nearest-rank P90, occupancy is shown beside the waiting tail, and open overdue tickets are counted apart (P04-DOMAIN-04, P04-TEST-06, P04-TEST-10).
4. **A simulated improvement is an estimate with a seed, a warm-up, a horizon, a replication count and an interval, and is never a realised benefit** (P04-DOMAIN-06, P04-MET-12).
5. **Satisfaction is evidence only beside its response rate and its bounds** (P04-TEST-11).
6. **A routing change is credited only for what routing does**: transfers and reopens are separated before a change is compared (query 05).

## Decision supported
The memo (`executive-memo.md`) applies these criteria: add one qualified agent to the technical queue first (a simulated paired mean wait difference of -10.8932 minutes, half-width 3.4329, on 50 shared demand paths), treat transfer reduction as a weak lever, evaluate cross-skilling of the under-used onboarding-only agents (0.279726 occupancy) with a multi-queue model before acting, and do not use CSAT as a target.
That is a simulated direction on a synthetic desk; the hypothetical real-world benefit of any of it is not claimed.

## Limits and honesty
* The simulation is a single-queue, dedicated-server picture of the technical queue at the Monday 09-11 bind (28.9 % of the technical-skilled agents' handling in that bind went to other queues); its improvement is an estimate with those limits.
* The holdout's +20 % intensity is a chosen realisation of a seeded series; the horizon of the simulation is twelve hours at the bind intensity.
* C07 and C10 are not built (501); the queues, compare and surveys screens are stubs; the Excel workbook was recalculated by LibreOffice only and there is no `.pbix`.
* Claims stay consistent with the public case study (`serviceflow/project.json`) and the resume bullets (`resume-bullets.md`).
