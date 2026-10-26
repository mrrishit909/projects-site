# Executive memo: which staffing or routing change meets support targets under uncertain workload? (P04-ART-07)

**Synthetic.** The three queues, 18 agents and 3,817 accepted tickets are generated (seed 20261026, dataset `sf-20261026-20261026`, generator hash `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4`, contract v1, code revision `43de7f8`). Nothing below is a measured effect on a real support team:
**no realised staffing benefit, saving, service level or adoption is claimed**, and the relationships the data shows (a long technical P1 tail, a Monday 09-11 UTC bind, a +20 % holdout) were designed into it (`web/public/data/manifest.json`). Three kinds of statement are kept apart and labelled:
**OBSERVED** (what the synthetic history shows; SQL investigations 01-08 in `sql-analysis.md`, reconciled to `data/sql/reference_metrics.sql` and the Python domain), **SIMULATED** (estimates of a seeded queue model; `web/public/reference/simulation-runs.json`) and **HYPOTHETICAL** (what a real desk might gain; none is claimed).
Query numbers are the files of `data/sql/analysis/`; P04 ids and command ids C01-C10 are in `requirements.md`.

## Decision
Question (P04-GOAL-01): which staffing or routing change meets support targets under uncertain workload?

**Options considered below (A to E).** **Of the changes this package can evaluate, add one qualified agent to the technical queue (q-002) first; do not count a transfer-reduction routing change as an equivalent lever; and test cross-skilling the under-used onboarding-only agents next, because the observed slack points there but nothing here simulates it.**
This is a recommendation about a synthetic desk and a simulated direction, not an instruction: its simulated improvement is a model estimate with the limits listed below.

| Option | Evidence | Status |
|---|---|---|
| **A. Do nothing** (baseline, 5 technical agents) | Observed: the technical queue misses most; at the holdout intensity (+20 % arrivals) the simulated wait rises (below). | the reference point |
| **B. Add one qualified agent to the technical queue** (5 to 6) | **Simulated** paired mean wait difference **-10.8932 minutes, 95 % interval +-3.4329**, on the same 50 demand paths; the interval excludes zero. | recommended first; SIMULATED |
| **C. Cross-skill onboarding-only agents into the technical queue** (a routing change) | Observed slack: onboarding-only agents run at 0.279726 occupancy, agents holding billing and technical at 0.539443 (query 04). Not simulated: C07 `build-shift-scenario` returns 501 and the simulator has one queue. | untested hypothesis |
| **D. Reduce transfers** (a routing change) | Observed: a transferred-only ticket resolves in 93.1684 minutes against 89.9202 for tickets with neither (query 05); the resolution tail is made by reopens (mean 1,188.3935 minutes), not transfers. | not supported by this evidence |
| **E. Use CSAT as the target** | Observed: 0.349325 of invitations are answered; CSAT 0.864000 among responders lies between 0.301816 and 0.952492 once non-response is bounded (query 07). | not usable as evidence |

## Evidence (OBSERVED, twelve weeks 2026-07-06 to 2026-09-27, accepted tickets)
| What | Number | Query |
|---|---|---|
| Overall targets | first-response compliance 0.950498 (3,437 of 3,616 with a human reply); resolution compliance 0.978104 (3,529 of 3,608 completions); open overdue 0 at every Monday cutoff and at the window end | 03 |
| The weakest priority | P1: first response 0.823789 and resolution 0.823789 (187 of 227 each); P2 first response 0.932576 | 03 |
| The weakest queue | technical q-002: first response 0.923291, resolution 0.959525; technical P1 resolution **0.767606 (109 of 142)**; billing 0.971519 / 0.991270, onboarding 0.964052 / 0.989071 | 03 |
| Waiting is a technical-queue phenomenon | mean first response 43.8355 minutes (P90 68.4500) in q-002 against 18.9573 (34.6000) in billing and 15.7325 (26.7500) in onboarding; overall mean 28.0046, P90 44.1500 | 02 |
| The tail is not in the mean | technical P1 resolution: 142 tickets, mean 247.1852, **P90 619.4167** (2.506 times the mean) | 02 |
| Workload is uncertain in a specific place | the Monday 09-11 UTC block has 1.3259 arrivals per staffed hour against 0.9737 for the next block and 0.4292 for the median block; the holdout weeks arrive 1.20 times as hard (2.129464 against 1.775298 tickets per hour) | 01, 03 |
| The holdout is harder | mean wait to first service 20.8904 (training) to 33.2661 (holdout); first-response compliance 0.956330 to 0.940697; P1 resolution compliance 0.846154 to 0.793814; occupancy 0.399387 to 0.473609 | 03, reference windows |
| Load is uneven | occupancy 0.424263 overall, 0.207308 (agt-007) to 0.649409 (agt-012); onboarding-only agents 0.279726, billing-only 0.300276, billing and technical 0.539443, technical only 0.400426, technical and onboarding 0.480002 | 04 |
| Breaks are not capacity | three shifts declare no break although 30 minutes are recorded (90 minutes of capacity overstated); no handling interval overlaps a recorded break | 04 |
| Customers leave more often once waits pass about ten minutes | abandonment 0.118213 of chat and phone tickets (209 of 1,768); chat hazard 0.030100 in the first five minutes, 0.126354 at 10-20 minutes, 0.176471 at 40-80 | 06 |
| Data problems are found, not hidden | 70 rows refused (4 bot replies typed as human, 3 unqualified, 3 simultaneous services, 3 arrival resets, 57 dependants); the reopen recorded as a new customer is found by an analyst check (4 customers) | 08 |

## The three simulated scenarios (SIMULATED, 50 replications each)
A model of **the technical queue at the Monday 09-11 UTC bind**, built by the generator from the training weeks: five identical servers (the average number of technical-skilled agents on shift at Monday 10:00 across the eight training Mondays), arrivals at 3.12 tickets per hour (technical arrivals in the Monday 09-11 block per hour of those blocks), exponential service with mean 69.1 minutes
(the mean handling per resolved technical ticket), FIFO within priority, priority mix P1 0.09 / P2 0.37 / P3 0.54, **warm-up 120 minutes excluded from every statistic, horizon 720 minutes**, base seed 20261026; replication r uses seed 20261026 + r (r = 0..49). The mean wait is the wait of tickets that started service inside the horizon;
tickets still waiting at the horizon (**censored**) are excluded from the wait statistics and counted separately. Intervals are 95 % Student-t intervals over the 50 replication means (t = 2.010 at 49 degrees of freedom).

| Scenario | Agents | Arrivals per hour | Mean wait, mean of 50 replication means (min) | 95 % interval half-width | 95 % interval (min) | Censored tickets, all 50 replications |
|---|---|---|---|---|---|---|
| `sim-001` baseline-v1 | 5 | 3.12 | 18.8435 | 8.2004 | 10.6431 to 27.0439 | 57 |
| `sim-002` plus-one-agent-v1 | 6 | 3.12 | 7.9502 | 5.2231 | 2.7271 to 13.1733 | 16 |
| `sim-003` holdout-intensity-v1 | 5 | 3.74 (3.12 x 1.2) | 30.6253 | 8.3091 | 22.3162 to 38.9344 | 129 |

**Paired difference of the proposal.** `sim-002` minus `sim-001` on the same 50 seeds, hence the same demand paths: **-10.8932 minutes, half-width 3.4329, interval -14.3261 to -7.4603** (point estimate about 58 % of the baseline mean, 10.8932 / 18.8435 = 0.578). A single published run is one draw: the single-replication means (14.6140, 3.8776 and 33.6237 minutes) are the first replication of each of these fifty and sit far from the means, which is why the replications are the evidence.
**`sim-003` is not a policy comparison**: its arrival intensity differs, so it does not share the demand path; its difference from `sim-001` (+11.7818, half-width 5.9968) is shown only to size the effect of +20 % arrivals on five servers, and it is not a paired result.
Analytic cross-check (steady-state M/M/c mean wait, computed in `tests/test_artifacts.py`): 20.05, 5.61 and 67.68 minutes for utilisations 0.719, 0.599 and 0.861; the first two lie inside the simulated intervals, the third is far above the simulated 30.63 because 720 minutes with a 120-minute warm-up is nowhere near steady state at 0.861 and censored tickets are excluded; the horizon, not the queue, limits what `sim-003` can show.

## Uncertainty
* **Replication noise** is the interval above: 50 replications of a 12-hour run; the baseline half-width (8.2004) is 43.5 % of its mean, so the point estimates move by minutes between seeds. Only the paired difference is tight enough to exclude zero.
* **The holdout intensity is a chosen realisation**: the generator kept attempt 7 of a fixed series (+20.10 %); the first seven attempts ranged from +12.69 % to +30.46 %, and Poisson noise alone moves the ratio by about 4.3 points (`manifest.json` `generator.parameters.arrival_realisation`, D-09 R4-13). A different draw would give a different holdout.
* **Eight weeks to learn, four to validate**: the Monday bind rests on eight Mondays (144 arrivals) and four holdout Mondays (94 arrivals); the holdout Monday rate (23.5 per Monday) is +30.6 % over the training rate (18.0), more than the +20 % average, on a small sample.
* **The decision thresholds are not in the data.** The contract defines per-ticket targets in minutes, not a required compliance share. As an illustration only, against a bar of 0.95 the overall first-response compliance (0.950498) clears it by 0.000498 while P1 (0.823789), P2 (0.932576) and the technical queue (0.923291) do not; the bar is an assumption, not a finding.
* **Observed against simulated are not comparable**: the observed technical mean wait to first service over all twelve weeks is 41.3560 minutes; the simulated 18.8435 is a 12-hour picture at the bind intensity with censored tickets dropped. They answer different questions.

## Limitations
* **Synthetic.** The desk does not exist; costs, volumes and behaviour are generated, and the designed relationships were chosen, so finding them shows the queries work, not that a business has them.
* **Dedicated-server simplification.** The model treats the five technical servers as dedicated. Three of the five technical-skilled agents on shift at the first training Monday bind (Monday 2026-07-06 10:00 UTC: agt-001, agt-002 and agt-008 hold billing as well; agt-005 and agt-006 hold only technical) hold another queue's skill, four of five from 2026-08-03 when agt-005 gains onboarding (the case study and `contracts.md` D-09 say "four of the five", counting skills as at the end of the data). Independently of that count, **28.9 % of the handling minutes started in the Monday 09-11 bind of the training weeks by technical-skilled agents went to other queues** (2,434.7167 of 3,422.1500 minutes went to technical tickets; 950.7500 to billing and 36.6833 to onboarding; query 04).
  So the real technical capacity in the bind is lower than five servers and the baseline wait is likely understated; the direction and size of the bias in the improvement are not established.
* **Single-queue model.** One queue, one agent pool, no transfers, pauses, reopens, abandonment, breaks or shift boundaries, exponential service, no skill proficiency. Billing and onboarding are not modelled; a change that moves load between queues (option C) cannot be evaluated by it.
* **A stress picture, not a day.** The run holds the Monday 09-11 intensity for twelve hours; the real bind lasts two. It sizes how a queue under that pressure responds to one more server, nothing more.
* **Censoring.** Tickets still waiting at the horizon are excluded from the wait statistics (57, 16 and 129 across the fifty replications of the three scenarios), which biases all three means downward, most for `sim-003`.
* **Not built.** C07 `build-shift-scenario` (a candidate schedule with availability and breaks respected) and C10 `export-recommendation` return 501; the queues, compare and surveys screens are stubs. The decision above therefore comes from SQL and the seeded simulator, not from an exported scenario.
* **No Excel, no Power BI.** The workbook (`workbook.md`) was recalculated by LibreOffice only; the BI package (`bi-package.md`) has no `.pbix`; neither is evidence about those products.

## Recommendation
What the synthetic data supports: put the next unit of staffing in the technical queue (option B), because it is where first response and resolution miss most, where waits are longest and where the only simulated comparison whose interval excludes zero lives (-10.8932 +-3.4329 minutes on the same seeds, a simulated direction);
treat reducing transfers as a weak lever (their resolution effect is about 3 minutes, reopens are the tail); read the slack in the onboarding-only agents (0.279726 occupancy) as the case for evaluating cross-skilling (option C) with a multi-queue model and the shift-scenario builder before acting;
keep the P1 problem separate (P1 is missed in every queue); and never present CSAT without its response rate and bounds. Report every figure with its seed, window and the label synthetic. **The data does not support any statement about a realised benefit, real service levels or real staffing cost.**
