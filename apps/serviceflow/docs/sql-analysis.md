# SQL analysis on the seeded snapshot (P04-ART-04)

Everything here is **synthetic**: the generated snapshot `sf-20261026-20261026` (seed 20261026, generator `dataset_hash`
`944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4`, contract v1, code revision `43de7f8`) seeded into PostgreSQL 16 through the domain's `validate_batch`,
and the golden fixture seeded into a second database. The generator **designed in** four relationships and nine defects (`web/public/data/manifest.json` `designed_relationships`,
`data/injection-manifest.json`: a long technical P1 tail, a Monday 09-11 UTC capacity bind, faster handling above proficiency 4, a +20 % holdout; a bot acknowledgement typed as a human reply,
a reopen recorded as a new customer, an unqualified assignment, two simultaneous services, a break counted as capacity, a transfer that resets the arrival, a warm-up left in a simulation,
a clock-change shift, survey nonresponse skew). These queries therefore show whether the data contains what was put there and whether the metrics read it correctly; they are **observed results
in a synthetic history**, not facts about a real support team, and they say nothing about a realised staffing benefit. Simulated outcomes are in `executive-memo.md`, kept apart.
Every table below is the observed output of the named file, rendered from `artifacts/analysis-results.json`, which `run_all.py` writes from the same run
(`artifacts/render_sql_analysis.py` fills the tables; no figure inside a table is typed). The sentences around the tables quote them and are checked by `tests/test_artifacts.py`.
Contract rules are cited as D-01..D-09 and requirement ids as P04-MET-nn / P04-TEST-nn / P04-GOLD-nn.

The organising question is the one of the whole package: **which staffing or routing change meets support targets under uncertain workload?** (P04-GOAL-01). Each investigation says
what it contributes to it.

## Reproduce

```sh
cd apps/serviceflow
# one command: creates the scratch databases artifacts04_run_snapshot and artifacts04_run_golden, seeds them (data/migrate.py, data/seed.py), runs everything, drops them
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi    # exit 0 only if every reconciliation row is equal
../../.venv/bin/python artifacts/render_sql_analysis.py                                                              # refresh the tables below

# or step by step on databases you made (names must start with artifacts04_; the shared serviceflow database is refused)
export ARTIFACTS_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/artifacts04_snapshot
export ARTIFACTS_GOLDEN_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/artifacts04_golden
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py             # reset + migrate + seed web/public/data + the 1,018 break rows (about 12 s)
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden
psql -v ON_ERROR_STOP=1 "$ARTIFACTS_DATABASE_URL" -f data/sql/analysis/00_event_views.sql -f data/sql/analysis/01_arrivals_by_hour_of_week.sql   # any file runs alone in psql after 00
psql -v ON_ERROR_STOP=1 "$ARTIFACTS_GOLDEN_DATABASE_URL" -f data/sql/analysis/00_event_views.sql -f data/sql/analysis/09_golden_known_answer.sql
```

The credentials are placeholders: the local development login of the repository's CI workflow is the default of `run_all.py` and can be replaced with `ARTIFACTS_ADMIN_URL`. No other credential exists and none is stored in this package.
Files with several blocks (`-- @@ name`) hold several statements; `run_all.py` runs each block and stores it as `<file>__<name>`.

Prepared snapshot database (counts from `data-dictionary.md`): 3,817 tickets (of 3,826 generated), 21,893 events (of 21,948), 2,147 surveys (of 2,153), 1,020 shifts, 1,018 recorded breaks,
18 agents, 3 queues, 4,976 service intervals; **70 rows rejected** and kept in `rejected_records` (query 08). Analysis window: the whole twelve weeks `[2026-07-06T00:00:00Z, 2026-09-28T00:00:00Z)`;
training weeks 1-8 end at `2026-08-31T00:00:00Z`, holdout weeks 9-12 follow (D-08).

| File | Question | Requirement |
|---|---|---|
| `00_event_views.sql` | views `sf_window` (three windows), `sf_ev` (replay order), `sf_ticket` (per-ticket instants and counts), `sf_interval` (service intervals) | D-01, D-02 |
| `01_arrivals_by_hour_of_week.sql` | arrivals against staffed hours by two-hour block of the UTC week; the Monday 09-11 bind | P04-MET-01, P04-DOMAIN-02/03 |
| `02_wait_and_response_distributions.sql` | first response, wait to first service and resolution by queue and priority, mean beside P90 | P04-MET-04/05/07, P04-TEST-10 |
| `03_sla_compliance_and_open_overdue.sql` | SLA compliance per priority and window; open overdue kept apart | P04-MET-08, P04-TEST-06 |
| `04_occupancy_by_agent_and_shift.sql` | occupancy by agent, breaks declared against recorded, the Monday bind's handling by queue | P04-MET-09, P04-TEST-05/07 |
| `05_transfer_and_reopen_effects.sql` | what a transfer and a reopen do to resolution, wait and handling | P04-FLOW-04/06, P04-TEST-02/08 |
| `06_abandonment_by_channel_and_patience.sql` | abandonment by channel and the hazard by time waited | P04-MET-10 |
| `07_survey_response_skew.sql` | survey response by experience, CSAT and its bounds | P04-MET-11, P04-TEST-11 |
| `08_rejections_and_defects_by_reason.sql` | rejections by reason; the nine injected defects and their SQL checks | P04-TEST-01/03/04/08 |
| `09_golden_known_answer.sql` | the golden fixture, reconciled in section 10 | P04-GOLD-01 |
| `bi_fact_ticket.sql`, `bi_fact_service_interval.sql`, `bi_fact_shift.sql`, `bi_fact_survey.sql`, `bi_dimensions.sql` | the fact and dimension tables of `bi-package.md` (CSV under `artifacts/bi/`) | P04-ART-06 |

Assumptions used by the queries (each is also stated in the file header):
* **A-1 original arrival.** Waits, first responses and resolutions are measured from `tickets.created_at`, which a transfer never moves; a reopened ticket is one customer contact and is charged its dormant gap (D-09 R4-09).
* **A-2 final queue.** A queue figure groups by the ticket's FINAL queue (`group_by=queue` basis, D-09 R4-10); the first queue is `sf_ticket.first_queue_id`.
* **A-3 UTC.** All instants and calendar groupings are UTC; the two agent zones (Europe/Berlin, America/Santiago) matter only for the declared shifts, already stored as UTC instants.
* **A-4 means and P90.** A mean is the exact sum of seconds divided by 60 n, rounded half up once; P90 is nearest rank, index `ceil(0.9 n)`, written `(9n + 9) / 10` in integers.
* **A-5 no calendars.** Every SLA target is wall clock on the 24x7 calendar (D-07, D-09 R4-18).

## 00 The views (`00_event_views.sql`)
Read-only over the base tables. `sf_ticket` has one row per accepted ticket (3,817), `sf_interval` one row per service interval (4,976, none open, every interval has an agent). They share no code with the
Python domain: the replay is window functions over the event log, as in `data/sql/reference_metrics.sql`.

## 01 Arrivals against staffed hours by hour of week (`01_arrivals_by_hour_of_week.sql`)
Blocks are two consecutive UTC clock hours; staffed hours spread each shift's declared break pro rata over the shift; blocks with fewer than 24 staffed hours (about two staffed agent-hours a week) are excluded from the ranking (124 of 168 are ranked).
Contribution to the decision: it shows **where** capacity is thin, so a staffing change is aimed at hours, not at the average.

<!-- BEGIN:01_arrivals_by_hour_of_week -->
| note | block_utc | arrivals | arrivals_training | arrivals_holdout | staffed_hours | arrivals_per_staffed_hour | blocks_ranked |
|---|---|---|---|---|---|---|---|
| top 1 | Mon 09-11 | 238 | 144 | 94 | 179.50 | 1.3259 | 124 |
| top 2 | Mon 10-12 | 183 | 108 | 75 | 187.94 | 0.9737 | 124 |
| top 3 | Mon 08-10 | 151 | 98 | 53 | 157.00 | 0.9618 | 124 |
| top 4 | Tue 14-16 | 139 | 93 | 46 | 152.90 | 0.9091 | 124 |
| top 5 | Mon 13-15 | 142 | 88 | 54 | 157.50 | 0.9016 | 124 |
| top 6 | Thu 14-16 | 129 | 77 | 52 | 145.25 | 0.8881 | 124 |
| median of the blocks | (mean of the two middle blocks) |  |  |  |  | 0.4292 | 124 |
| lowest block | Sun 00-02 | 0 | 0 | 0 | 44.98 | 0.0000 | 124 |
<!-- END:01_arrivals_by_hour_of_week -->

Observed: the Monday 09-11 UTC block takes 238 arrivals (144 in the training weeks, 94 in the holdout weeks) over 179.50 staffed hours, **1.3259 arrivals per staffed hour**, against 0.9737 for the next block (Mon 10-12) and 0.4292 for the median block, about 3.1 times the median.
Per Monday that is 18.0 arrivals in the training weeks (144 / 8) and 23.5 in the holdout weeks (94 / 4), +30.6 % against +20.0 % for all arrivals; four holdout Mondays are a small sample (the holdout intensity itself is a chosen realisation of a seeded series, D-09 R4-13).
The figure 1.3259 and the median 0.4292 equal the manifest's `designed.monday_block` (reconciled in section 10); the manifest's next-best 0.9844 is over all 3,826 published tickets, this table's 0.9737 over the 3,817 accepted ones (9 tickets are rejected at ingest; both are reproduced).

## 02 Wait and response distributions by queue and priority (`02_wait_and_response_distributions.sql`)
First response = first human reply minus arrival (a bot never counts; 201 arrivals have no human reply and are outside that population); wait = first service start minus arrival (D-09 R4-10); resolution = final resolution minus the original arrival.
Queue = the ticket's final queue. The mean is always beside the P90 (P04-TEST-10).

<!-- BEGIN:02_wait_and_response_distributions__first_response_and_wait -->
| queue_id | priority | arrivals | with_human_reply | mean_first_response_min | p90_first_response_min | served | mean_wait_min | p90_wait_min |
|---|---|---|---|---|---|---|---|---|
| q-001 | P1 | 45 | 44 | 9.1602 | 26.5833 | 44 | 6.8803 | 22.6000 |
| q-001 | P2 | 431 | 419 | 21.7240 | 24.7500 | 419 | 19.2497 | 23.5500 |
| q-001 | P3 | 846 | 801 | 18.0483 | 41.0333 | 801 | 15.5235 | 37.9833 |
| q-001 | ALL | 1322 | 1264 | 18.9573 | 34.6000 | 1264 | 16.4578 | 32.0833 |
| q-002 | P1 | 148 | 142 | 22.8731 | 25.6000 | 142 | 20.4291 | 23.1167 |
| q-002 | P2 | 586 | 545 | 38.2414 | 57.5833 | 545 | 35.7298 | 55.6167 |
| q-002 | P3 | 809 | 747 | 51.9017 | 87.1167 | 747 | 49.4389 | 85.1333 |
| q-002 | ALL | 1543 | 1434 | 43.8355 | 68.4500 | 1434 | 41.3560 | 66.2333 |
| q-003 | P1 | 43 | 41 | 12.4260 | 27.3000 | 41 | 9.9244 | 23.9500 |
| q-003 | P2 | 370 | 356 | 14.6941 | 29.7667 | 356 | 12.1977 | 28.6500 |
| q-003 | P3 | 539 | 521 | 16.7022 | 24.5167 | 521 | 14.1611 | 22.5167 |
| q-003 | ALL | 952 | 918 | 15.7325 | 26.7500 | 918 | 13.2105 | 23.6000 |
| ALL | P1 | 236 | 227 | 18.3282 | 26.9667 | 227 | 15.9056 | 23.8833 |
| ALL | P2 | 1387 | 1320 | 26.6477 | 37.6833 | 1320 | 24.1521 | 35.4333 |
| ALL | P3 | 2194 | 2069 | 29.9319 | 50.4833 | 2069 | 27.4254 | 47.9833 |
| ALL | ALL | 3817 | 3616 | 28.0046 | 44.1500 | 3616 | 25.5073 | 41.5167 |
<!-- END:02_wait_and_response_distributions__first_response_and_wait -->

<!-- BEGIN:02_wait_and_response_distributions__resolution_tail -->
| queue_id | priority | completions | mean_resolution_min | p90_resolution_min | p90_over_mean |
|---|---|---|---|---|---|
| q-001 | P1 | 44 | 110.7451 | 109.7000 | 0.991 |
| q-001 | P2 | 417 | 147.2024 | 249.0500 | 1.692 |
| q-001 | P3 | 799 | 115.3849 | 137.3833 | 1.191 |
| q-001 | ALL | 1260 | 125.7529 | 152.9333 | 1.216 |
| q-002 | P1 | 142 | 247.1852 | 619.4167 | 2.506 |
| q-002 | P2 | 544 | 254.4592 | 621.7000 | 2.443 |
| q-002 | P3 | 747 | 191.1319 | 368.2167 | 1.927 |
| q-002 | ALL | 1433 | 220.7269 | 531.4500 | 2.408 |
| q-003 | P1 | 41 | 155.9711 | 256.7500 | 1.646 |
| q-003 | P2 | 354 | 132.8001 | 188.4167 | 1.419 |
| q-003 | P3 | 520 | 126.3225 | 173.3500 | 1.372 |
| q-003 | ALL | 915 | 130.1571 | 188.0500 | 1.445 |
| ALL | P1 | 227 | 204.2639 | 586.6667 | 2.872 |
| ALL | P2 | 1315 | 187.6961 | 349.3833 | 1.861 |
| ALL | P3 | 2066 | 145.5255 | 215.6833 | 1.482 |
| ALL | ALL | 3608 | 164.5909 | 294.5833 | 1.790 |
<!-- END:02_wait_and_response_distributions__resolution_tail -->

Observed: over the twelve weeks the mean first response is 28.0046 minutes with a P90 of 44.1500 (3,616 tickets with a human reply) and the mean wait to first service 25.5073 with a P90 of 41.5167.
The waiting is concentrated in the **technical queue q-002**: mean first response 43.8355 and P90 68.4500, against 18.9573 / 34.6000 in billing and 15.7325 / 26.7500 in onboarding; its P3 tickets wait longest (mean first response 51.9017, P90 87.1167).
The resolution tail is the other shape: technical P1 resolution has 142 completions, a mean of 247.1852 minutes and a **P90 of 619.4167 (2.506 times the mean)**; over all priorities the P90 is 294.5833 against a mean of 164.5909 (1.790), and P1 alone 586.6667 against 204.2639 (2.872).
The mean alone would hide both; this is the designed technical P1 tail (15 % of technical P1 tickets are major incidents paused 2.7-5 hours, D-07).

## 03 SLA compliance, with open overdue tickets kept apart (`03_sla_compliance_and_open_overdue.sql`)
Targets: P1 15 / 240, P2 60 / 1440, P3 240 / 4320 minutes. A ticket still open and overdue is in neither denominator; it is counted in its own block (P04-TEST-06). The second block reads the open-overdue state at ten-thirty UTC on the twelve Mondays;
the third samples it every hour on the hour.

<!-- BEGIN:03_sla_compliance_and_open_overdue__compliance_by_priority_and_window -->
| window_name | priority | arrivals | first_response_within | first_response_eligible | first_response_compliance | arrivals_without_human_reply | if_no_reply_counted_as_miss | resolution_within | resolution_eligible | resolution_compliance | resolution_misses | misses_that_were_reopened |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| full | P1 | 236 | 187 | 227 | 0.823789 | 9 | 0.792373 | 187 | 227 | 0.823789 | 40 | 18 |
| full | P2 | 1387 | 1231 | 1320 | 0.932576 | 67 | 0.887527 | 1276 | 1315 | 0.970342 | 39 | 36 |
| full | P3 | 2194 | 2019 | 2069 | 0.975834 | 125 | 0.920237 | 2066 | 2066 | 1.000000 | 0 | 0 |
| full | ALL | 3817 | 3437 | 3616 | 0.950498 | 201 | 0.900445 | 3529 | 3608 | 0.978104 | 79 | 54 |
| training | P1 | 135 | 108 | 130 | 0.830769 | 5 | 0.800000 | 110 | 130 | 0.846154 | 20 | 10 |
| training | P2 | 859 | 765 | 817 | 0.936353 | 42 | 0.890570 | 791 | 813 | 0.972940 | 22 | 20 |
| training | P3 | 1392 | 1295 | 1320 | 0.981061 | 72 | 0.930316 | 1317 | 1317 | 1.000000 | 0 | 0 |
| training | ALL | 2386 | 2168 | 2267 | 0.956330 | 119 | 0.908634 | 2218 | 2260 | 0.981416 | 42 | 30 |
| holdout | P1 | 101 | 79 | 97 | 0.814433 | 4 | 0.782178 | 77 | 97 | 0.793814 | 20 | 8 |
| holdout | P2 | 528 | 466 | 503 | 0.926441 | 25 | 0.882576 | 485 | 502 | 0.966135 | 17 | 16 |
| holdout | P3 | 802 | 724 | 749 | 0.966622 | 53 | 0.902743 | 749 | 749 | 1.000000 | 0 | 0 |
| holdout | ALL | 1431 | 1269 | 1349 | 0.940697 | 82 | 0.886792 | 1311 | 1348 | 0.972552 | 37 | 24 |
<!-- END:03_sla_compliance_and_open_overdue__compliance_by_priority_and_window -->

<!-- BEGIN:03_sla_compliance_and_open_overdue__compliance_by_queue_and_priority -->
| queue_id | priority | first_response_within | first_response_eligible | first_response_compliance | resolution_within | resolution_eligible | resolution_compliance |
|---|---|---|---|---|---|---|---|
| q-001 | P1 | 37 | 44 | 0.840909 | 42 | 44 | 0.954545 |
| q-001 | P2 | 397 | 419 | 0.947494 | 408 | 417 | 0.978417 |
| q-001 | P3 | 794 | 801 | 0.991261 | 799 | 799 | 1.000000 |
| q-001 | ALL | 1228 | 1264 | 0.971519 | 1249 | 1260 | 0.991270 |
| q-002 | P1 | 117 | 142 | 0.823944 | 109 | 142 | 0.767606 |
| q-002 | P2 | 494 | 545 | 0.906422 | 519 | 544 | 0.954044 |
| q-002 | P3 | 713 | 747 | 0.954485 | 747 | 747 | 1.000000 |
| q-002 | ALL | 1324 | 1434 | 0.923291 | 1375 | 1433 | 0.959525 |
| q-003 | P1 | 33 | 41 | 0.804878 | 36 | 41 | 0.878049 |
| q-003 | P2 | 340 | 356 | 0.955056 | 349 | 354 | 0.985876 |
| q-003 | P3 | 512 | 521 | 0.982726 | 520 | 520 | 1.000000 |
| q-003 | ALL | 885 | 918 | 0.964052 | 905 | 915 | 0.989071 |
<!-- END:03_sla_compliance_and_open_overdue__compliance_by_queue_and_priority -->

<!-- BEGIN:03_sla_compliance_and_open_overdue__open_overdue_at_monday_cutoffs -->
| week | cutoff_utc | backlog | open_overdue |
|---|---|---|---|
| 1 | 2026-07-06T10:30:00Z | 15 | 0 |
| 2 | 2026-07-13T10:30:00Z | 7 | 0 |
| 3 | 2026-07-20T10:30:00Z | 1 | 0 |
| 4 | 2026-07-27T10:30:00Z | 12 | 0 |
| 5 | 2026-08-03T10:30:00Z | 9 | 0 |
| 6 | 2026-08-10T10:30:00Z | 7 | 0 |
| 7 | 2026-08-17T10:30:00Z | 12 | 0 |
| 8 | 2026-08-24T10:30:00Z | 9 | 0 |
| 9 | 2026-08-31T10:30:00Z | 8 | 0 |
| 10 | 2026-09-07T10:30:00Z | 13 | 0 |
| 11 | 2026-09-14T10:30:00Z | 16 | 0 |
| 12 | 2026-09-21T10:30:00Z | 7 | 0 |
<!-- END:03_sla_compliance_and_open_overdue__open_overdue_at_monday_cutoffs -->

<!-- BEGIN:03_sla_compliance_and_open_overdue__overdue_exposure_by_priority -->
| priority | could_be_overdue | tickets_open_overdue_at_a_sample | hours_with_any | peak_open_overdue_at_one_hour |
|---|---|---|---|---|
| P1 | 40 | 31 | 165 | 3 |
| P2 | 39 | 31 | 93 | 2 |
| P3 | 0 | 0 | 0 | 0 |
| ALL | 79 | 62 | 233 | 3 |
<!-- END:03_sla_compliance_and_open_overdue__overdue_exposure_by_priority -->

Observed: first-response compliance is 0.950498 (3,437 of 3,616) over the twelve weeks, 0.956330 in the training weeks and 0.940697 in the holdout weeks; resolution compliance is 0.978104 (3,529 of 3,608), 0.981416 and 0.972552.
**P1 is the weakest priority**: 187 of 227 within target for the first response (0.823789) and 187 of 227 for the resolution (0.823789; two different counts that happen to be equal), 0.793814 for the resolution in the holdout weeks.
The 201 arrivals with no human reply (abandoned before any reply) are outside the first-response denominator; counting them as misses the overall rate would be 0.900445.
Of the 79 resolution misses (P1 40, P2 39) **54 are reopened tickets**, charged their dormant gap since the original arrival (P1 18, P2 36).
Open overdue is **0 at every Monday cutoff and at the window end**, but the hourly sample finds **62 tickets** (P1 31, P2 31) open and overdue at some sampled hour, in 233 of 2,016 sampled hours, at most 3 at one hour: a point-in-time count of zero does not mean no exposure.
The sampling is hourly, so shorter episodes are missed and the figures are lower bounds.
By queue, the misses sit in **technical (q-002)**: first-response compliance 0.923291 and resolution compliance 0.959525 for the queue, and for technical P1 0.823944 (117 of 142) and **0.767606 (109 of 142)**;
billing is at 0.971519 / 0.991270 and onboarding at 0.964052 / 0.989071. P1 first response is missed in every queue (0.840909, 0.823944, 0.804878), so P1 is a priority problem as well as a queue problem.
Inside the Monday 09-11 bind the first-response compliance is not worse (P2 75 of 76, P3 129 of 129 within target; recomputed in `tests/test_artifacts.py`): the bind is a load peak, not where this history misses its first-response targets.

## 04 Occupancy by agent and shift, with breaks (`04_occupancy_by_agent_and_shift.sql`)
Staffed available time follows D-05; handling is the service intervals attributed to the agent named on the opening event. Occupancy and the waiting tail are different numbers (P04-DOMAIN-04).

<!-- BEGIN:04_occupancy_by_agent_and_shift__occupancy_by_agent -->
| agent_id | timezone | employment_type | shifts | staffed_available_min | declared_break_min | recorded_break_min | service_intervals | handling_min | occupancy |
|---|---|---|---|---|---|---|---|---|---|
| agt-001 | Europe/Berlin | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 350 | 11912.6500 | 0.456423 |
| agt-002 | Europe/Berlin | full_time | 58 | 26130.0000 | 1710.0000 | 1740.0000 | 366 | 11568.5167 | 0.442729 |
| agt-003 | Europe/Berlin | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 145 | 6180.4333 | 0.236798 |
| agt-004 | Europe/Berlin | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 341 | 10039.7333 | 0.384664 |
| agt-005 | Europe/Berlin | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 276 | 12430.8000 | 0.476276 |
| agt-006 | Europe/Berlin | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 215 | 10572.8667 | 0.405091 |
| agt-007 | Europe/Berlin | part_time | 46 | 15180.0000 | 1380.0000 | 1380.0000 | 101 | 3146.9333 | 0.207308 |
| agt-008 | Europe/Berlin | full_time | 58 | 26130.0000 | 1710.0000 | 1740.0000 | 456 | 16282.1333 | 0.623120 |
| agt-009 | Europe/Berlin | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 251 | 9520.6000 | 0.364774 |
| agt-010 | America/Santiago | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 375 | 13374.6500 | 0.512439 |
| agt-011 | America/Santiago | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 403 | 16586.9000 | 0.635513 |
| agt-012 | America/Santiago | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 364 | 16949.5833 | 0.649409 |
| agt-013 | America/Santiago | part_time | 46 | 15180.0000 | 1380.0000 | 1380.0000 | 191 | 4558.1833 | 0.300276 |
| agt-014 | America/Santiago | full_time | 58 | 26130.0000 | 1710.0000 | 1740.0000 | 292 | 13323.4500 | 0.509891 |
| agt-015 | America/Santiago | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 280 | 10684.1833 | 0.409356 |
| agt-016 | America/Santiago | full_time | 58 | 26100.0000 | 1740.0000 | 1740.0000 | 255 | 7293.5833 | 0.279448 |
| agt-017 | America/Santiago | contractor | 58 | 25770.0000 | 1710.0000 | 1710.0000 | 149 | 7336.8833 | 0.284706 |
| agt-018 | America/Santiago | full_time | 58 | 25830.0000 | 1710.0000 | 1710.0000 | 166 | 8074.1833 | 0.312589 |
| ALL |  |  | 1020 | 447450.0000 | 30450.0000 | 30540.0000 | 4976 | 189836.2667 | 0.424263 |
<!-- END:04_occupancy_by_agent_and_shift__occupancy_by_agent -->

<!-- BEGIN:04_occupancy_by_agent_and_shift__breaks_declared_vs_recorded -->
| shift_min | declared_break_min | recorded_break_min | shifts | staffed_min_declared | staffed_min_recorded | capacity_overstated_by_declared_min | handling_min | handling_inside_a_recorded_break_min |
|---|---|---|---|---|---|---|---|---|
| 360 | 30 | 30 | 92 | 30360.0000 | 30360.0000 | 0.0000 | 7705.1167 | 0.0000 |
| 420 | 30 | 30 | 1 | 390.0000 | 390.0000 | 0.0000 | 149.0000 | 0.0000 |
| 480 | 0 | 30 | 3 | 1440.0000 | 1350.0000 | 90.0000 | 785.2333 | 0.0000 |
| 480 | 30 | 0 | 2 | 900.0000 | 960.0000 | -60.0000 | 232.6500 | 0.0000 |
| 480 | 30 | 30 | 922 | 414900.0000 | 414900.0000 | 0.0000 | 180964.2667 | 0.0000 |
<!-- END:04_occupancy_by_agent_and_shift__breaks_declared_vs_recorded -->

<!-- BEGIN:04_occupancy_by_agent_and_shift__occupancy_by_skill_set -->
| skill_set | agents | agent_ids | staffed_available_min | handling_min | occupancy |
|---|---|---|---|---|---|
| q-001 | 1 | agt-013 | 15180.0000 | 4558.1833 | 0.300276 |
| q-001 + q-002 | 4 | agt-001, agt-002, agt-008, agt-011 | 104460.0000 | 56350.2000 | 0.539443 |
| q-001 + q-003 | 4 | agt-004, agt-010, agt-015, agt-016 | 104400.0000 | 41392.1500 | 0.396477 |
| q-002 | 3 | agt-006, agt-014, agt-017 | 78000.0000 | 31233.2000 | 0.400426 |
| q-002 + q-003 | 3 | agt-005, agt-012, agt-018 | 78030.0000 | 37454.5667 | 0.480002 |
| q-003 | 3 | agt-003, agt-007, agt-009 | 67380.0000 | 18847.9667 | 0.279726 |
<!-- END:04_occupancy_by_agent_and_shift__occupancy_by_skill_set -->

<!-- BEGIN:04_occupancy_by_agent_and_shift__monday_bind_handling_by_queue -->
| queue_id | intervals | handling_min | share_pct |
|---|---|---|---|
| q-001 | 48 | 950.7500 | 27.8 |
| q-002 | 51 | 2434.7167 | 71.1 |
| q-003 | 1 | 36.6833 | 1.1 |
| ALL | 100 | 3422.1500 | 100.0 |
<!-- END:04_occupancy_by_agent_and_shift__monday_bind_handling_by_queue -->

Observed: overall occupancy is 0.424263 (189,836.2667 handling minutes over 447,450.0000 staffed minutes). By agent it runs from 0.207308 (agt-007, part time) and 0.236798 (agt-003) to 0.649409 (agt-012), 0.635513 (agt-011) and 0.623120 (agt-008): the load is very uneven, so an average occupancy of 0.42 hides agents near two thirds.
Breaks: three 480-minute shifts declare no break although a 30-minute break is recorded (the injected defect INJ-05), which would overstate capacity by 90 minutes if the declared value were trusted; two shifts declare 30 minutes and record none (-60); **no handling interval overlaps a recorded break** (0.0000 minutes).
The 420-minute row is the Santiago night shift across the clock change; the 480-minute night shift of agt-018 (INJ-08) sits in the 480 / 30 / 30 row and is found by query 08.
Grouped by the queues an agent can serve, the slack is visible: the three onboarding-only agents (agt-003, agt-007, agt-009) run at 0.279726 and the one billing-only agent (agt-013) at 0.300276, while the four agents who hold billing and technical (agt-001, agt-002, agt-008, agt-011)
run at 0.539443 and those holding technical and onboarding at 0.480002; the three technical-only agents are at 0.400426. Skills are read at the end of the window (agt-005 gained onboarding on 2026-08-03 and agt-015 billing on 2026-08-17).
Finally, the Monday-bind block measures the **dedicated-server simplification** of the simulation: of the 3,422.1500 handling minutes started in the Monday 09-11 bind of the training weeks by agents holding the technical skill, 2,434.7167 (71.1 %) went to technical tickets,
950.7500 (27.8 %) to billing and 36.6833 (1.1 %) to onboarding, i.e. **28.9 % went to other queues** (`docs/uat-evidence.md` quotes the reviewer's figure of 988 of 3,423 minutes, a sum of rounded parts; the exact total is 3,422.15).

## 05 Transfer and reopen effects (`05_transfer_and_reopen_effects.sql`)
Population: tickets whose final resolution is in the window. A transfer never moves the arrival; a reopen charges the dormant gap. Contribution to the decision: it separates what **routing** (transfers) and what **rework** (reopens) cost, so a routing change is not credited with a rework effect.

<!-- BEGIN:05_transfer_and_reopen_effects__by_transfer_and_reopen -->
| ticket_group | completions | share_of_completions_pct | mean_resolution_min | p90_resolution_min | mean_wait_to_first_service_min | mean_handling_min | mean_dormant_gap_min |
|---|---|---|---|---|---|---|---|
| neither | 3095 | 85.8 | 89.9202 | 171.9500 | 26.2743 | 50.7405 | 0.0000 |
| transferred only | 272 | 7.5 | 93.1684 | 165.0667 | 17.5408 | 49.7816 | 0.0000 |
| reopened only | 222 | 6.2 | 1188.3935 | 1887.4333 | 26.9570 | 79.8590 | 932.8268 |
| transferred and reopened | 19 | 0.5 | 1388.2053 | 1933.6000 | 6.9904 | 76.5860 | 1124.1509 |
| ALL | 3608 | 100.0 | 164.5909 | 294.5833 | 25.5564 | 52.5960 | 63.3166 |
<!-- END:05_transfer_and_reopen_effects__by_transfer_and_reopen -->

<!-- BEGIN:05_transfer_and_reopen_effects__transfer_routes -->
| from_queue | to_queue | transfers | mean_min_arrival_to_transfer | with_a_later_service | mean_min_transfer_to_next_service |
|---|---|---|---|---|---|
| q-001 | q-002 | 81 | 20.6315 | 80 | 24.1577 |
| q-001 | q-003 | 42 | 21.1706 | 39 | 9.1577 |
| q-002 | q-001 | 48 | 30.3858 | 47 | 25.4791 |
| q-002 | q-003 | 66 | 37.3846 | 66 | 21.1154 |
| q-003 | q-001 | 36 | 17.3370 | 33 | 6.6081 |
| q-003 | q-002 | 26 | 11.1622 | 26 | 19.1859 |
<!-- END:05_transfer_and_reopen_effects__transfer_routes -->

Observed: 272 tickets were transferred only, 222 reopened only and 19 both, of 3,608 completions. A transfer alone leaves the resolution almost unchanged (mean 93.1684 minutes against 89.9202 for tickets with neither, P90 165.0667 against 171.9500) and the wait to first service is shorter (17.5408 against 26.2743; this is a statement about these tickets, not a claim that transferring causes the shorter wait).
A reopen changes the figure completely: mean resolution 1,188.3935 minutes (P90 1,887.4333), of which a mean of 932.8268 minutes is the gap between a resolution and the reopen, and handling rises from 50.7405 to 79.8590 minutes.
The 299 transfers go mostly from billing to technical (81) and from technical to onboarding (66); after a transfer into q-002 the next service starts after 24.1577 and 19.1859 minutes on average, into q-001 after 25.4791 and 6.6081.
The transfer count equals the tickets with a transfer (299), so no ticket was transferred twice.

## 06 Abandonment by channel and patience (`06_abandonment_by_channel_and_patience.sql`)
Only chat and phone can abandon; email and web_form have no rate (empty, never 0). Patience is arrival to the abandonment event.

<!-- BEGIN:06_abandonment_by_channel_and_patience__abandonment_by_channel -->
| channel | can_abandon | arrivals | abandoned | abandonment_rate | abandoned_before_first_service | abandoned_after_service_began | of_which_transferred | mean_patience_min | p90_patience_min |
|---|---|---|---|---|---|---|---|---|---|
| chat | true | 1196 | 138 | 0.115385 | 133 | 5 | 5 | 18.8343 | 42.4000 |
| email | false | 1496 | 0 |  | 0 | 0 | 0 |  |  |
| phone | true | 572 | 71 | 0.124126 | 68 | 3 | 3 | 12.4519 | 29.8000 |
| web_form | false | 553 | 0 |  | 0 | 0 | 0 |  |  |
| ALL abandonable | true | 1768 | 209 | 0.118213 | 201 | 8 | 8 | 16.6661 | 40.6000 |
<!-- END:06_abandonment_by_channel_and_patience__abandonment_by_channel -->

<!-- BEGIN:06_abandonment_by_channel_and_patience__abandonment_hazard_by_wait -->
| channel | wait_band_min | at_risk | abandoned_in_band | served_in_band | abandonment_hazard |
|---|---|---|---|---|---|
| chat | 0-5 | 1196 | 36 | 810 | 0.030100 |
| chat | 5-10 | 350 | 18 | 55 | 0.051429 |
| chat | 10-20 | 277 | 35 | 72 | 0.126354 |
| chat | 20-40 | 170 | 28 | 57 | 0.164706 |
| chat | 40-80 | 85 | 15 | 37 | 0.176471 |
| chat | 80-more | 33 | 1 | 32 | 0.030303 |
| phone | 0-5 | 572 | 29 | 392 | 0.050699 |
| phone | 5-10 | 151 | 13 | 23 | 0.086093 |
| phone | 10-20 | 115 | 14 | 27 | 0.121739 |
| phone | 20-40 | 74 | 8 | 31 | 0.108108 |
| phone | 40-80 | 35 | 4 | 11 | 0.114286 |
| phone | 80-more | 20 | 0 | 20 | 0.000000 |
<!-- END:06_abandonment_by_channel_and_patience__abandonment_hazard_by_wait -->

Observed: 209 of 1,768 chat and phone tickets abandoned (0.118213; chat 0.115385, phone 0.124126), 201 before any service and 8 after a service had begun (all 8 on tickets that had been transferred). Mean patience is 16.6661 minutes (P90 40.6000): chat customers wait longer (18.8343, P90 42.4000) than phone customers (12.4519, P90 29.8000).
The hazard of leaving rises with the time already waited: for chat from 0.030100 inside the first five minutes to 0.126354 between 10 and 20 minutes and 0.176471 between 40 and 80; for phone from 0.050699 to 0.121739 at 10-20 minutes, then about 0.11.
The final band (80 minutes or more) is low because only the patient remain (a selection effect), so it must not be read as "long waits are safe". This is a descriptive hazard of a synthetic history, not a causal estimate.

## 07 Survey response skew (`07_survey_response_skew.sql`)
CSAT is positive (score 4 or 5) over valid responses (D-03). A poor experience is a missed target, a transfer or a reopen. The bounds put every non-responder at the lowest and at the highest possible answer; they are arithmetic limits, not estimates.

<!-- BEGIN:07_survey_response_skew__response_by_experience -->
| experience | completions | invited | invitation_rate | valid_responses | response_rate | positive | csat |
|---|---|---|---|---|---|---|---|
| good experience | 2923 | 1745 | 0.596989 | 663 | 0.379943 | 585 | 0.882353 |
| poor experience | 685 | 402 | 0.586861 | 87 | 0.216418 | 63 | 0.724138 |
| ALL | 3608 | 2147 | 0.595067 | 750 | 0.349325 | 648 | 0.864000 |
<!-- END:07_survey_response_skew__response_by_experience -->

<!-- BEGIN:07_survey_response_skew__csat_and_its_bounds -->
| reading | positive | denominator | value |
|---|---|---|---|
| CSAT among valid responses (the contract figure) | 648 | 750 | 0.864000 |
| lower bound: every non-responder not positive | 648 | 2147 | 0.301816 |
| upper bound: every non-responder positive | 2045 | 2147 | 0.952492 |
<!-- END:07_survey_response_skew__csat_and_its_bounds -->

<!-- BEGIN:07_survey_response_skew__score_distribution_by_queue -->
| queue_id | invited | valid_responses | response_rate | score_1 | score_2 | score_3 | score_4 | score_5 | csat |
|---|---|---|---|---|---|---|---|---|---|
| q-001 | 741 | 263 | 0.354926 | 0 | 2 | 37 | 121 | 103 | 0.851711 |
| q-002 | 858 | 287 | 0.334499 | 2 | 3 | 32 | 129 | 121 | 0.871080 |
| q-003 | 548 | 200 | 0.364964 | 1 | 4 | 21 | 89 | 85 | 0.870000 |
| ALL | 2147 | 750 | 0.349325 | 3 | 9 | 90 | 339 | 309 | 0.864000 |
<!-- END:07_survey_response_skew__score_distribution_by_queue -->

Observed: 2,147 of 3,608 completions were invited (0.595067) and 750 answered (0.349325); CSAT is 0.864000 among those who answered. After a good experience 0.379943 answer, after a poor one 0.216418 (about 57 % as often), and the CSAT of the poor-experience responders is 0.724138 against 0.882353.
Because non-responders are not random, the true figure could lie anywhere between 0.301816 and 0.952492: **CSAT cannot be used as evidence for a staffing change without its response rate**, and the queue differences (0.851711, 0.871080, 0.870000) are small against that gap.
The generator's own figures (`manifest.json` `stats`: 0.3799 after a good experience, 0.864 CSAT among responders) are reproduced; its 0.2148 after a poor experience is over another population and definition (section 10, known differences).

## 08 Rejections and injected defects (`08_rejections_and_defects_by_reason.sql`)
`rejected_records` holds every refused raw row with its reason; a rejected ticket takes its events and surveys with it (`TICKET_REJECTED`, D-05).

<!-- BEGIN:08_rejections_and_defects_by_reason__rejected_by_reason -->
| entity | reason_code | injected_defect | rejected_rows | distinct_ids | first_and_last_id |
|---|---|---|---|---|---|
| tickets | AGENT_NOT_QUALIFIED | INJ-03 | 3 | 3 | t-0630 .. t-2422 |
| tickets | CONCURRENCY_EXCEEDED | INJ-04 | 3 | 3 | t-1295 .. t-2799 |
| tickets | TRANSFER_RESETS_ARRIVAL | INJ-06 | 3 | 3 | t-1066 .. t-3206 |
| ticket_events | BOT_AS_HUMAN_REPLY | INJ-01 | 4 | 4 | e-00006 .. e-10283 |
| ticket_events | TICKET_REJECTED | dependants of INJ-03 / INJ-04 / INJ-06 | 51 | 51 | e-03624 .. e-18340 |
| surveys | TICKET_REJECTED | dependants of INJ-03 / INJ-04 / INJ-06 | 6 | 6 | sv-0576 .. sv-1793 |
<!-- END:08_rejections_and_defects_by_reason__rejected_by_reason -->

<!-- BEGIN:08_rejections_and_defects_by_reason__injected_defects_found -->
| injection_id | defect | sql_check | found |
|---|---|---|---|
| INJ-01 | bot acknowledgement typed as a human reply | rejected_records BOT_AS_HUMAN_REPLY | 4 |
| INJ-02 | reopen recorded as a new ticket from a new customer | customers whose created_at equals the created_at of their earliest ticket | 4 |
| INJ-03 | service by an agent without the queue skill | rejected_records AGENT_NOT_QUALIFIED | 3 |
| INJ-04 | two simultaneous services for one agent | rejected_records CONCURRENCY_EXCEEDED | 3 |
| INJ-05 | shift whose break is counted as available time | shifts with break_minutes 0 and a recorded break | 3 |
| INJ-06 | transfer that resets the arrival | rejected_records TRANSFER_RESETS_ARRIVAL | 3 |
| INJ-07 | simulation run with its warm-up included (replay-only) | simulation_runs rows with warmup_minutes = 0 | 0 |
| INJ-08 | shift across the clock change built with naive wall-clock arithmetic | shifts that cross a UTC-offset change of the agent zone and last 480 real minutes (a crossing shift of 8 wall-clock hours is 420) | 1 |
| INJ-09 | survey nonresponse skewed by a poor experience | invitations without a valid response after a poor experience (completed tickets) | 315 |
<!-- END:08_rejections_and_defects_by_reason__injected_defects_found -->

<!-- BEGIN:08_rejections_and_defects_by_reason__published_vs_loaded -->
| entity | loaded_rows | rejected_rows | published_rows |
|---|---|---|---|
| tickets | 3817 | 9 | 3826 |
| ticket_events | 21893 | 55 | 21948 |
| surveys | 2147 | 6 | 2153 |
<!-- END:08_rejections_and_defects_by_reason__published_vs_loaded -->

Observed: **70 rows refused** (9 tickets, 55 events, 6 surveys): 4 bot replies typed as human (INJ-01), 3 tickets served by an unqualified agent (INJ-03), 3 with simultaneous services (INJ-04), 3 whose transfer reset the arrival (INJ-06), and 57 dependants of the nine rejected tickets.
Accepted plus rejected rows equal the published row counts for tickets (3,826), events (21,948) and surveys (2,153). Eight of the nine injected defects are found by an SQL check that equals the manifest's own count; INJ-07 (a simulation with its warm-up included) is replay-only, so the table has no such run by design;
the ninth figure, INJ-09 (unanswered invitations after a poor experience), is 315 here against 318 in the manifest (other population and definition, section 10).

## 09 The golden fixture (`09_golden_known_answer.sql`)
One agent, three tickets created at 09:00:00Z, deterministic 10-minute service, FIFO: starts 0, 10, 20; waits 0, 10, 20; mean wait 10; last completion at minute 30 (P04-GOLD-01; `tests/fixtures/golden/CALCULATION.md`).

<!-- BEGIN:09_golden_known_answer__golden_per_ticket -->
| ticket_id | first_response_min | wait_min | resolution_min | handling_min |
|---|---|---|---|---|
| t-001 | 0.0000 | 0.0000 | 10.0000 | 10.0000 |
| t-002 | 10.0000 | 10.0000 | 20.0000 | 10.0000 |
| t-003 | 20.0000 | 20.0000 | 30.0000 | 10.0000 |
<!-- END:09_golden_known_answer__golden_per_ticket -->

<!-- BEGIN:09_golden_known_answer__golden_totals -->
| source | mean_wait_min | handling_min_total | last_completion_min |
|---|---|---|---|
| event log (this directory) | 10.0000 | 30.0000 | 30.0000 |
| simulation sim-001 (simulation_events) | 10.0000 |  | 30.0000 |
<!-- END:09_golden_known_answer__golden_totals -->

## 10 Reconciliation
Four kinds of check, all in `run_all.py`: **A** the golden fixture (`data/sql/reference_metrics.sql`, the Python domain and `expected.json` agree on all 28 metric keys; the per-ticket figures of 09 equal the hand calculation typed from `CALCULATION.md`; the seeded simulation events equal `expected.json`);
**B** snapshot headline figures (each investigation against `reference_metrics.sql` and the domain, and the two against each other on all 28 keys for the whole, training and holdout windows);
**C** every result set cell by cell against `data/sql/analysis/python_side.py` (exact rationals over the domain's replay, no SQL: the stored numbers equal the Python domain without a database);
**D** group figures against the domain's `group_metrics` (queue, priority, agent, channel) and the twelve Monday cutoffs against the reference and the domain; **E** rejections and injected defects against `data/injection-manifest.json` and `manifest.json`, and the BI measures recomputed from the CSV facts.
Columns: the investigation's value, then the other sources; `equal` is true only if every present source prints the same text.

<!-- BEGIN:reconciliation -->
| check | analysis_sql | second_source | third_source | fourth_source | equal |
|---|---|---|---|---|---|
| B reference_metrics.sql vs Python domain, full window: metric keys differing (of 28) | 0 | 0 |  |  | true |
| B reference_metrics.sql vs Python domain, training window: metric keys differing (of 28) | 0 | 0 |  |  | true |
| B reference_metrics.sql vs Python domain, holdout window: metric keys differing (of 28) | 0 | 0 |  |  | true |
| B snapshot arrivals + rejected tickets = published tickets (manifest row_counts) | 3826 | 3826 |  |  | true |
| B whole window arrival_count: query 02 ALL vs reference_metrics.sql vs domain | 3817 | 3817 | 3817 |  | true |
| B whole window mean_first_response_minutes: query 02 ALL vs reference_metrics.sql vs domain | 28.0046 | 28.0046 | 28.0046 |  | true |
| B whole window p90_first_response_minutes: query 02 ALL vs reference_metrics.sql vs domain | 44.1500 | 44.1500 | 44.1500 |  | true |
| B whole window mean_wait_minutes: query 02 ALL vs reference_metrics.sql vs domain | 25.5073 | 25.5073 | 25.5073 |  | true |
| B whole window completion_count: query 02 ALL vs reference_metrics.sql vs domain | 3608 | 3608 | 3608 |  | true |
| B whole window mean_resolution_minutes: query 02 ALL vs reference_metrics.sql vs domain | 164.5909 | 164.5909 | 164.5909 |  | true |
| B whole window first-response tickets with a human reply (02) vs sla_first_response_eligible | 3616 | 3616 | 3616 |  | true |
| B full window SLA first response within / eligible / compliance: query 03 vs reference vs domain | 3437 / 3616 / 0.950498 | 3437 / 3616 / 0.950498 | 3437 / 3616 / 0.950498 |  | true |
| B full window SLA resolution within / eligible / compliance: query 03 vs reference vs domain | 3529 / 3608 / 0.978104 | 3529 / 3608 / 0.978104 | 3529 / 3608 / 0.978104 |  | true |
| B full window arrivals: query 03 vs reference vs domain | 3817 | 3817 | 3817 |  | true |
| B training window SLA first response within / eligible / compliance: query 03 vs reference vs domain | 2168 / 2267 / 0.956330 | 2168 / 2267 / 0.956330 | 2168 / 2267 / 0.956330 |  | true |
| B training window SLA resolution within / eligible / compliance: query 03 vs reference vs domain | 2218 / 2260 / 0.981416 | 2218 / 2260 / 0.981416 | 2218 / 2260 / 0.981416 |  | true |
| B training window arrivals: query 03 vs reference vs domain | 2386 | 2386 | 2386 |  | true |
| B holdout window SLA first response within / eligible / compliance: query 03 vs reference vs domain | 1269 / 1349 / 0.940697 | 1269 / 1349 / 0.940697 | 1269 / 1349 / 0.940697 |  | true |
| B holdout window SLA resolution within / eligible / compliance: query 03 vs reference vs domain | 1311 / 1348 / 0.972552 | 1311 / 1348 / 0.972552 | 1311 / 1348 / 0.972552 |  | true |
| B holdout window arrivals: query 03 vs reference vs domain | 1431 | 1431 | 1431 |  | true |
| B whole window staffed_available_minutes: query 04 ALL vs reference_metrics.sql vs domain | 447450.0000 | 447450.0000 | 447450.0000 |  | true |
| B whole window handling_minutes_total: query 04 ALL vs reference_metrics.sql vs domain | 189836.2667 | 189836.2667 | 189836.2667 |  | true |
| B whole window agent_occupancy: query 04 ALL vs reference_metrics.sql vs domain | 0.424263 | 0.424263 | 0.424263 |  | true |
| B whole window abandonment_rate: query 06 vs reference_metrics.sql vs domain | 0.118213 | 0.118213 | 0.118213 |  | true |
| B whole window csat: query 07 vs reference_metrics.sql vs domain | 0.864000 | 0.864000 | 0.864000 |  | true |
| B whole window survey_invitation_rate: query 07 vs reference_metrics.sql vs domain | 0.595067 | 0.595067 | 0.595067 |  | true |
| B whole window survey_response_rate: query 07 vs reference_metrics.sql vs domain | 0.349325 | 0.349325 | 0.349325 |  | true |
| B surveys invited / valid / positive among completions: query 07 vs disclosures() | 2147 / 750 | 2147 / 750 |  |  | true |
| B open overdue at the window end (the reference's one open-overdue figure) vs domain vs the last Monday cutoff query | 0 | 0 | 0 |  | true |
| C 01_arrivals_by_hour_of_week: 8 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 02_wait_and_response_distributions__first_response_and_wait: 16 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 02_wait_and_response_distributions__resolution_tail: 16 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_sla_compliance_and_open_overdue__compliance_by_priority_and_window: 12 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_sla_compliance_and_open_overdue__compliance_by_queue_and_priority: 12 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_sla_compliance_and_open_overdue__open_overdue_at_monday_cutoffs: 12 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 03_sla_compliance_and_open_overdue__overdue_exposure_by_priority: 4 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_occupancy_by_agent_and_shift__occupancy_by_agent: 19 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_occupancy_by_agent_and_shift__breaks_declared_vs_recorded: 5 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_occupancy_by_agent_and_shift__monday_bind_handling_by_queue: 4 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 04_occupancy_by_agent_and_shift__occupancy_by_skill_set: 6 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 05_transfer_and_reopen_effects__by_transfer_and_reopen: 5 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 05_transfer_and_reopen_effects__transfer_routes: 6 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 06_abandonment_by_channel_and_patience__abandonment_by_channel: 5 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 06_abandonment_by_channel_and_patience__abandonment_hazard_by_wait: 12 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 07_survey_response_skew__response_by_experience: 3 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 07_survey_response_skew__csat_and_its_bounds: 3 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 07_survey_response_skew__score_distribution_by_queue: 4 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 08_rejections_and_defects_by_reason__rejected_by_reason: 6 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 08_rejections_and_defects_by_reason__injected_defects_found: 9 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| C 08_rejections_and_defects_by_reason__published_vs_loaded: 3 rows, cells differing from the Python side | 0 | 0 |  |  | true |
| D queue q-001: mean first response / P90 / mean wait / mean resolution (queue = final queue): queries 02 vs group_metrics | 18.9573 / 34.6000 / 16.4578 / 125.7529 | 18.9573 / 34.6000 / 16.4578 / 125.7529 |  |  | true |
| D queue q-002: mean first response / P90 / mean wait / mean resolution (queue = final queue): queries 02 vs group_metrics | 43.8355 / 68.4500 / 41.3560 / 220.7269 | 43.8355 / 68.4500 / 41.3560 / 220.7269 |  |  | true |
| D queue q-003: mean first response / P90 / mean wait / mean resolution (queue = final queue): queries 02 vs group_metrics | 15.7325 / 26.7500 / 13.2105 / 130.1571 | 15.7325 / 26.7500 / 13.2105 / 130.1571 |  |  | true |
| D priority P1: mean first response / P90 / mean wait / mean resolution (queue = final queue): queries 02 vs group_metrics | 18.3282 / 26.9667 / 15.9056 / 204.2639 | 18.3282 / 26.9667 / 15.9056 / 204.2639 |  |  | true |
| D priority P2: mean first response / P90 / mean wait / mean resolution (queue = final queue): queries 02 vs group_metrics | 26.6477 / 37.6833 / 24.1521 / 187.6961 | 26.6477 / 37.6833 / 24.1521 / 187.6961 |  |  | true |
| D priority P3: mean first response / P90 / mean wait / mean resolution (queue = final queue): queries 02 vs group_metrics | 29.9319 / 50.4833 / 27.4254 / 145.5255 | 29.9319 / 50.4833 / 27.4254 / 145.5255 |  |  | true |
| D priority P1: SLA first response and resolution within / eligible: query 03 vs group_metrics | 187/227 187/227 | 187/227 187/227 |  |  | true |
| D priority P2: SLA first response and resolution within / eligible: query 03 vs group_metrics | 1231/1320 1276/1315 | 1231/1320 1276/1315 |  |  | true |
| D priority P3: SLA first response and resolution within / eligible: query 03 vs group_metrics | 2019/2069 2066/2066 | 2019/2069 2066/2066 |  |  | true |
| D training priority P1: SLA within / eligible (first response, resolution): query 03 vs group_metrics | 108/130 110/130 | 108/130 110/130 |  |  | true |
| D training priority P2: SLA within / eligible (first response, resolution): query 03 vs group_metrics | 765/817 791/813 | 765/817 791/813 |  |  | true |
| D training priority P3: SLA within / eligible (first response, resolution): query 03 vs group_metrics | 1295/1320 1317/1317 | 1295/1320 1317/1317 |  |  | true |
| D holdout priority P1: SLA within / eligible (first response, resolution): query 03 vs group_metrics | 79/97 77/97 | 79/97 77/97 |  |  | true |
| D holdout priority P2: SLA within / eligible (first response, resolution): query 03 vs group_metrics | 466/503 485/502 | 466/503 485/502 |  |  | true |
| D holdout priority P3: SLA within / eligible (first response, resolution): query 03 vs group_metrics | 724/749 749/749 | 724/749 749/749 |  |  | true |
| D Monday cutoff 2026-07-06T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 15 / 0 | 15 / 0 | 15 / 0 |  | true |
| D Monday cutoff 2026-07-13T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 7 / 0 | 7 / 0 | 7 / 0 |  | true |
| D Monday cutoff 2026-07-20T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 1 / 0 | 1 / 0 | 1 / 0 |  | true |
| D Monday cutoff 2026-07-27T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 12 / 0 | 12 / 0 | 12 / 0 |  | true |
| D Monday cutoff 2026-08-03T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 9 / 0 | 9 / 0 | 9 / 0 |  | true |
| D Monday cutoff 2026-08-10T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 7 / 0 | 7 / 0 | 7 / 0 |  | true |
| D Monday cutoff 2026-08-17T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 12 / 0 | 12 / 0 | 12 / 0 |  | true |
| D Monday cutoff 2026-08-24T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 9 / 0 | 9 / 0 | 9 / 0 |  | true |
| D Monday cutoff 2026-08-31T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 8 / 0 | 8 / 0 | 8 / 0 |  | true |
| D Monday cutoff 2026-09-07T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 13 / 0 | 13 / 0 | 13 / 0 |  | true |
| D Monday cutoff 2026-09-14T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 16 / 0 | 16 / 0 | 16 / 0 |  | true |
| D Monday cutoff 2026-09-21T10:30:00Z: backlog / open overdue: query 03 vs reference_metrics.sql vs domain | 7 / 0 | 7 / 0 | 7 / 0 |  | true |
| D agent agt-001: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 11912.6500 / 0.456423 | 26100.0000 / 11912.6500 / 0.456423 |  |  | true |
| D agent agt-002: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26130.0000 / 11568.5167 / 0.442729 | 26130.0000 / 11568.5167 / 0.442729 |  |  | true |
| D agent agt-003: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 6180.4333 / 0.236798 | 26100.0000 / 6180.4333 / 0.236798 |  |  | true |
| D agent agt-004: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 10039.7333 / 0.384664 | 26100.0000 / 10039.7333 / 0.384664 |  |  | true |
| D agent agt-005: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 12430.8000 / 0.476276 | 26100.0000 / 12430.8000 / 0.476276 |  |  | true |
| D agent agt-006: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 10572.8667 / 0.405091 | 26100.0000 / 10572.8667 / 0.405091 |  |  | true |
| D agent agt-007: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 15180.0000 / 3146.9333 / 0.207308 | 15180.0000 / 3146.9333 / 0.207308 |  |  | true |
| D agent agt-008: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26130.0000 / 16282.1333 / 0.623120 | 26130.0000 / 16282.1333 / 0.623120 |  |  | true |
| D agent agt-009: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 9520.6000 / 0.364774 | 26100.0000 / 9520.6000 / 0.364774 |  |  | true |
| D agent agt-010: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 13374.6500 / 0.512439 | 26100.0000 / 13374.6500 / 0.512439 |  |  | true |
| D agent agt-011: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 16586.9000 / 0.635513 | 26100.0000 / 16586.9000 / 0.635513 |  |  | true |
| D agent agt-012: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 16949.5833 / 0.649409 | 26100.0000 / 16949.5833 / 0.649409 |  |  | true |
| D agent agt-013: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 15180.0000 / 4558.1833 / 0.300276 | 15180.0000 / 4558.1833 / 0.300276 |  |  | true |
| D agent agt-014: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26130.0000 / 13323.4500 / 0.509891 | 26130.0000 / 13323.4500 / 0.509891 |  |  | true |
| D agent agt-015: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 10684.1833 / 0.409356 | 26100.0000 / 10684.1833 / 0.409356 |  |  | true |
| D agent agt-016: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 26100.0000 / 7293.5833 / 0.279448 | 26100.0000 / 7293.5833 / 0.279448 |  |  | true |
| D agent agt-017: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 25770.0000 / 7336.8833 / 0.284706 | 25770.0000 / 7336.8833 / 0.284706 |  |  | true |
| D agent agt-018: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics | 25830.0000 / 8074.1833 / 0.312589 | 25830.0000 / 8074.1833 / 0.312589 |  |  | true |
| D channel chat: abandonment rate: query 06 vs group_metrics | 0.115385 | 0.115385 |  |  | true |
| D channel email: abandonment rate: query 06 vs group_metrics |  |  |  |  | true |
| D channel phone: abandonment rate: query 06 vs group_metrics | 0.124126 | 0.124126 |  |  | true |
| D channel web_form: abandonment rate: query 06 vs group_metrics |  |  |  |  | true |
| D queue q-001: CSAT / response rate (completions by final queue): query 07 vs group_metrics | 0.851711 / 0.354926 | 0.851711 / 0.354926 |  |  | true |
| D queue q-002: CSAT / response rate (completions by final queue): query 07 vs group_metrics | 0.871080 / 0.334499 | 0.871080 / 0.334499 |  |  | true |
| D queue q-003: CSAT / response rate (completions by final queue): query 07 vs group_metrics | 0.870000 / 0.364964 | 0.870000 / 0.364964 |  |  | true |
| D transfers: query 05 routes total vs 'transferred' events vs tickets with a transfer (domain disclosures, arrivals) | 299 | 299 | 299 |  | true |
| D reopened completions: query 05 groups with a reopen vs disclosures reopened_among_completions | 241 | 241 |  |  | true |
| D service intervals: query 04 ALL vs bi_fact_service_interval rows vs the domain replay | 4976 | 4976 | 4976 |  | true |
| D Monday 09-11 bind, training weeks: share of the technical-skilled agents' started handling that went to other queues (1 dp): query 04 vs docs/uat-evidence.md (reviewer harness: 988 of 3,423 minutes, 28.9 %) | 28.9 | 28.9 |  |  | true |
| E rejected_records rows vs the manifest's expected_rejections (rows in the symmetric difference) | 0 | 0 | 0 |  | true |
| E rejected rows kept: table vs domain ingest | 70 | 70 | 70 |  | true |
| E published tickets rows (loaded + rejected) vs manifest row_counts | 3826 | 3826 |  |  | true |
| E published ticket_events rows (loaded + rejected) vs manifest row_counts | 21948 | 21948 |  |  | true |
| E published surveys rows (loaded + rejected) vs manifest row_counts | 2153 | 2153 |  |  | true |
| E INJ-01 found by its SQL check vs the manifest's own count | 4 | 4 |  |  | true |
| E INJ-02 found by its SQL check vs the manifest's own count | 4 | 4 |  |  | true |
| E INJ-03 found by its SQL check vs the manifest's own count | 3 | 3 |  |  | true |
| E INJ-04 found by its SQL check vs the manifest's own count | 3 | 3 |  |  | true |
| E INJ-05 found by its SQL check vs the manifest's own count | 3 | 3 |  |  | true |
| E INJ-06 found by its SQL check vs the manifest's own count | 3 | 3 |  |  | true |
| E INJ-07 found by its SQL check vs the manifest's own count (replay-only: the cold-start run is not in simulation_runs) | 0 | 0 |  |  | true |
| E INJ-08 found by its SQL check vs the manifest's own count | 1 | 1 |  |  | true |
| E Monday 09-11 block ratio: query 01 (accepted tickets) vs the same block over all published tickets vs manifest stats.designed | 1.3259 | 1.3259 | 1.3259 |  | true |
| E median block ratio: query 01 (accepted tickets) vs the same over all published tickets vs manifest stats.designed.median_block_ratio | 0.4292 | 0.4292 | 0.4292 |  | true |
| E response rate after a good experience: query 07 (4 dp) vs manifest stats.response_rate_after_good_experience | 0.3799 | 0.3799 |  |  | true |
| E CSAT among responders: query 07 vs manifest stats.csat_among_responders (3 dp) | 0.864 | 0.864 |  |  | true |
| A golden arrival_count: reference_metrics.sql vs Python domain vs expected.json | 3 | 3 | 3 |  | true |
| A golden completion_count: reference_metrics.sql vs Python domain vs expected.json | 3 | 3 | 3 |  | true |
| A golden arrival_rate_per_hour: reference_metrics.sql vs Python domain vs expected.json | 3.000000 | 3.000000 | 3.000000 |  | true |
| A golden completion_rate_per_hour: reference_metrics.sql vs Python domain vs expected.json | 3.000000 | 3.000000 | 3.000000 |  | true |
| A golden backlog: reference_metrics.sql vs Python domain vs expected.json | {'2026-07-06T09:05:00Z': 3, '2026-07-06T09:25:00Z': 1, '2026-07-06T10:00:00Z': 0} | {'2026-07-06T09:05:00Z': 3, '2026-07-06T09:25:00Z': 1, '2026-07-06T10:00:00Z': 0} | {'2026-07-06T09:05:00Z': 3, '2026-07-06T09:25:00Z': 1, '2026-07-06T10:00:00Z': 0} |  | true |
| A golden first_response_minutes: reference_metrics.sql vs Python domain vs expected.json | {'t-001': '0.0000', 't-002': '10.0000', 't-003': '20.0000'} | {'t-001': '0.0000', 't-002': '10.0000', 't-003': '20.0000'} | {'t-001': '0.0000', 't-002': '10.0000', 't-003': '20.0000'} |  | true |
| A golden mean_first_response_minutes: reference_metrics.sql vs Python domain vs expected.json | 10.0000 | 10.0000 | 10.0000 |  | true |
| A golden p90_first_response_minutes: reference_metrics.sql vs Python domain vs expected.json | 20.0000 | 20.0000 | 20.0000 |  | true |
| A golden wait_minutes: reference_metrics.sql vs Python domain vs expected.json | {'t-001': '0.0000', 't-002': '10.0000', 't-003': '20.0000'} | {'t-001': '0.0000', 't-002': '10.0000', 't-003': '20.0000'} | {'t-001': '0.0000', 't-002': '10.0000', 't-003': '20.0000'} |  | true |
| A golden mean_wait_minutes: reference_metrics.sql vs Python domain vs expected.json | 10.0000 | 10.0000 | 10.0000 |  | true |
| A golden resolution_minutes: reference_metrics.sql vs Python domain vs expected.json | {'t-001': '10.0000', 't-002': '20.0000', 't-003': '30.0000'} | {'t-001': '10.0000', 't-002': '20.0000', 't-003': '30.0000'} | {'t-001': '10.0000', 't-002': '20.0000', 't-003': '30.0000'} |  | true |
| A golden mean_resolution_minutes: reference_metrics.sql vs Python domain vs expected.json | 20.0000 | 20.0000 | 20.0000 |  | true |
| A golden handling_minutes_total: reference_metrics.sql vs Python domain vs expected.json | 30.0000 | 30.0000 | 30.0000 |  | true |
| A golden sla_first_response_compliance: reference_metrics.sql vs Python domain vs expected.json | 0.666667 | 0.666667 | 0.666667 |  | true |
| A golden sla_first_response_within: reference_metrics.sql vs Python domain vs expected.json | 2 | 2 | 2 |  | true |
| A golden sla_first_response_eligible: reference_metrics.sql vs Python domain vs expected.json | 3 | 3 | 3 |  | true |
| A golden sla_resolution_compliance: reference_metrics.sql vs Python domain vs expected.json | 1.000000 | 1.000000 | 1.000000 |  | true |
| A golden sla_resolution_within: reference_metrics.sql vs Python domain vs expected.json | 3 | 3 | 3 |  | true |
| A golden sla_resolution_eligible: reference_metrics.sql vs Python domain vs expected.json | 3 | 3 | 3 |  | true |
| A golden open_overdue_at_cutoff: reference_metrics.sql vs Python domain vs expected.json | 0 | 0 | 0 |  | true |
| A golden staffed_available_minutes: reference_metrics.sql vs Python domain vs expected.json | 60.0000 | 60.0000 | 60.0000 |  | true |
| A golden staffed_shift_minutes_whole: reference_metrics.sql vs Python domain vs expected.json | 450.0000 | 450.0000 | 450.0000 |  | true |
| A golden agent_occupancy: reference_metrics.sql vs Python domain vs expected.json | 0.500000 | 0.500000 | 0.500000 |  | true |
| A golden abandonment_rate: reference_metrics.sql vs Python domain vs expected.json |  |  |  |  | true |
| A golden csat: reference_metrics.sql vs Python domain vs expected.json | 1.000000 | 1.000000 | 1.000000 |  | true |
| A golden survey_invitation_rate: reference_metrics.sql vs Python domain vs expected.json | 0.666667 | 0.666667 | 0.666667 |  | true |
| A golden survey_response_rate: reference_metrics.sql vs Python domain vs expected.json | 0.500000 | 0.500000 | 0.500000 |  | true |
| A golden empty_population: reference_metrics.sql vs Python domain vs expected.json | false | false | false |  | true |
| A golden t-001: first response / wait / resolution / handling (09 vs expected.json vs CALCULATION.md) | 0.0000 / 0.0000 / 10.0000 / 10.0000 | 0.0000 / 0.0000 / 10.0000 / 10.0000 | 0.0000 / 0.0000 / 10.0000 / 10.0000 |  | true |
| A golden t-002: first response / wait / resolution / handling (09 vs expected.json vs CALCULATION.md) | 10.0000 / 10.0000 / 20.0000 / 10.0000 | 10.0000 / 10.0000 / 20.0000 / 10.0000 | 10.0000 / 10.0000 / 20.0000 / 10.0000 |  | true |
| A golden t-003: first response / wait / resolution / handling (09 vs expected.json vs CALCULATION.md) | 20.0000 / 20.0000 / 30.0000 / 10.0000 | 20.0000 / 20.0000 / 30.0000 / 10.0000 | 20.0000 / 20.0000 / 30.0000 / 10.0000 |  | true |
| A golden mean wait / handling total / last completion: event log (09) vs expected.json | 10.0000 / 30.0000 / 30.0000 | 10.0000 / 30.0000 / 30.0000 |  |  | true |
| A golden simulation sim-001 mean wait / last completion: simulation_events (09) vs expected.json | 10.0000 / 30.0000 | 10.0000 / 30.0000 |  |  | true |
| A golden simulation events (6): seeded rows vs expected.json (rows differing) | 0 | 0 |  |  | true |
| E BI measure Arrivals: recomputed from the CSV facts vs reference_metrics.sql vs domain | 3817 | 3817 | 3817 |  | true |
| E BI measure Completions: recomputed from the CSV facts vs reference_metrics.sql vs domain | 3608 | 3608 | 3608 |  | true |
| E BI measure Arrival Rate per Hour: recomputed from the CSV facts vs reference_metrics.sql vs domain | 1.893353 | 1.893353 | 1.893353 |  | true |
| E BI measure Completion Rate per Hour: recomputed from the CSV facts vs reference_metrics.sql vs domain | 1.789683 | 1.789683 | 1.789683 |  | true |
| E BI measure Mean First Response (min): recomputed from the CSV facts vs reference_metrics.sql vs domain | 28.0046 | 28.0046 | 28.0046 |  | true |
| E BI measure P90 First Response (min): recomputed from the CSV facts vs reference_metrics.sql vs domain | 44.1500 | 44.1500 | 44.1500 |  | true |
| E BI measure Mean Wait to First Service (min): recomputed from the CSV facts vs reference_metrics.sql vs domain | 25.5073 | 25.5073 | 25.5073 |  | true |
| E BI measure Mean Resolution (min): recomputed from the CSV facts vs reference_metrics.sql vs domain | 164.5909 | 164.5909 | 164.5909 |  | true |
| E BI measure SLA First Response Compliance: recomputed from the CSV facts vs reference_metrics.sql vs domain | 0.950498 | 0.950498 | 0.950498 |  | true |
| E BI measure SLA Resolution Compliance: recomputed from the CSV facts vs reference_metrics.sql vs domain | 0.978104 | 0.978104 | 0.978104 |  | true |
| E BI measure Handling Minutes: recomputed from the CSV facts vs reference_metrics.sql vs domain | 189836.2667 | 189836.2667 | 189836.2667 |  | true |
| E BI measure Staffed Available Minutes: recomputed from the CSV facts vs reference_metrics.sql vs domain | 447450.0000 | 447450.0000 | 447450.0000 |  | true |
| E BI measure Agent Occupancy: recomputed from the CSV facts vs reference_metrics.sql vs domain | 0.424263 | 0.424263 | 0.424263 |  | true |
| E BI measure Abandonment Rate: recomputed from the CSV facts vs reference_metrics.sql vs domain | 0.118213 | 0.118213 | 0.118213 |  | true |
| E BI measure Survey Invitation Rate: recomputed from the CSV facts vs reference_metrics.sql vs domain | 0.595067 | 0.595067 | 0.595067 |  | true |
| E BI measure Survey Response Rate: recomputed from the CSV facts vs reference_metrics.sql vs domain | 0.349325 | 0.349325 | 0.349325 |  | true |
| E BI measure CSAT: recomputed from the CSV facts vs reference_metrics.sql vs domain | 0.864000 | 0.864000 | 0.864000 |  | true |
| E BI measure Staffed Shift Minutes (whole shifts): recomputed from the CSV facts vs reference_metrics.sql staffed_shift_minutes_whole vs domain | 447990.0000 | 447990.0000 | 447990.0000 |  | true |
| E BI measure Open at End of Data vs reference open_overdue_at_cutoff (nothing open, so nothing open and overdue) | 0 | 0 | 0 |  | true |
| E BI measure Reopen Rate of Completions vs domain disclosures (reopened_among_completions / completion_count) | 0.066796 | 0.066796 |  |  | true |
| E BI measure Transfer Share of Arrivals vs domain disclosures (transferred_tickets / arrival_count) | 0.078334 | 0.078334 |  |  | true |
| E BI measure P90 Resolution vs query 02 ALL | 294.5833 | 294.5833 |  |  | true |
| E BI simulated sim-001 mean wait / 95 % half-width over 50 replications vs web/public/reference/simulation-runs.json | 18.8435 / 8.2004 | 18.8435 / 8.2004 |  |  | true |
| E BI simulated sim-002 mean wait / 95 % half-width over 50 replications vs web/public/reference/simulation-runs.json | 7.9502 / 5.2231 | 7.9502 / 5.2231 |  |  | true |
| E BI simulated sim-003 mean wait / 95 % half-width over 50 replications vs web/public/reference/simulation-runs.json | 30.6253 / 8.3091 | 30.6253 / 8.3091 |  |  | true |
| E BI simulated paired difference sim-002 minus sim-001 / half-width vs simulation-runs.json | -10.8932 / 3.4329 | -10.8932 / 3.4329 |  |  | true |
| E BI measures over the training dates (15 measures: arrivals, completions, means, P90, SLA, handling, staffed, occupancy, abandonment, survey): recomputed from the CSV facts vs reference_metrics.sql vs domain | 2386 / 2260 / 23.4036 / 37.5500 / 20.8904 / 155.2115 / 0.956330 / 0.981416 / 118965.3833 / 297870.0000 / 0.399387 / 0.112108 / 0.591150 / 0.352545 / 0.872611 | 2386 / 2260 / 23.4036 / 37.5500 / 20.8904 / 155.2115 / 0.956330 / 0.981416 / 118965.3833 / 297870.0000 / 0.399387 / 0.112108 / 0.591150 / 0.352545 / 0.872611 | 2386 / 2260 / 23.4036 / 37.5500 / 20.8904 / 155.2115 / 0.956330 / 0.981416 / 118965.3833 / 297870.0000 / 0.399387 / 0.112108 / 0.591150 / 0.352545 / 0.872611 |  | true |
| E BI measures over the holdout dates (15 measures: arrivals, completions, means, P90, SLA, handling, staffed, occupancy, abandonment, survey): recomputed from the CSV facts vs reference_metrics.sql vs domain | 1431 / 1348 / 35.7365 / 59.3833 / 33.2661 / 180.3161 / 0.940697 / 0.972552 / 70870.8833 / 149640.0000 / 0.473609 / 0.128637 / 0.601632 / 0.344020 / 0.849462 | 1431 / 1348 / 35.7365 / 59.3833 / 33.2661 / 180.3161 / 0.940697 / 0.972552 / 70870.8833 / 149640.0000 / 0.473609 / 0.128637 / 0.601632 / 0.344020 / 0.849462 | 1431 / 1348 / 35.7365 / 59.3833 / 33.2661 / 180.3161 / 0.940697 / 0.972552 / 70870.8833 / 149640.0000 / 0.473609 / 0.128637 / 0.601632 / 0.344020 / 0.849462 |  | true |
<!-- END:reconciliation -->

Where this package's figure and the generator's manifest differ, they are listed here with the reason and are **not** counted as reconciled:

<!-- BEGIN:known_differences -->
| item | this_package | manifest | why |
|---|---|---|---|
| INJ-09 unanswered invitations after a poor experience | 315 | 318 | the manifest counts over all 2,153 published surveys (6 belong to rejected tickets) and its own definition of a poor experience; this package counts completed accepted tickets and the definition printed in 07 |
| 01 next-best block | Mon 10-12 0.9737 (accepted tickets) | Mon 10-12 0.9844; over all published tickets here: Mon 10-12 0.9844 | the manifest counts the 3,826 published tickets; 9 are rejected at ingest, so the accepted arrivals of the block are fewer |
| 07 response rate after a poor experience | 0.216418 | 0.2148 (invited 405) | other population (all published tickets and surveys) and the generator's own definition of a poor experience |
<!-- END:known_differences -->

`reference_metrics.sql` over the whole snapshot, the training window and the holdout window (cross-check of the headline figures; the per-ticket maps are not repeated):

<!-- BEGIN:reference_metrics_snapshot -->
| window | arrival_count | completion_count | arrival_rate_per_hour | completion_rate_per_hour | mean_first_response_minutes | p90_first_response_minutes | mean_wait_minutes | mean_resolution_minutes | handling_minutes_total | sla_first_response_compliance | sla_first_response_within | sla_first_response_eligible | sla_resolution_compliance | sla_resolution_within | sla_resolution_eligible | open_overdue_at_cutoff | staffed_available_minutes | staffed_shift_minutes_whole | agent_occupancy | abandonment_rate | csat | survey_invitation_rate | survey_response_rate | empty_population | backlog |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| full | 3817 | 3608 | 1.893353 | 1.789683 | 28.0046 | 44.1500 | 25.5073 | 164.5909 | 189836.2667 | 0.950498 | 3437 | 3616 | 0.978104 | 3529 | 3608 | 0 | 447450.0000 | 447990.0000 | 0.424263 | 0.118213 | 0.864000 | 0.595067 | 0.349325 | false | {"2026-09-28T00:00:00Z": 0} |
| training | 2386 | 2260 | 1.775298 | 1.681548 | 23.4036 | 37.5500 | 20.8904 | 155.2115 | 118965.3833 | 0.956330 | 2168 | 2267 | 0.981416 | 2218 | 2260 | 0 | 297870.0000 | 447990.0000 | 0.399387 | 0.112108 | 0.872611 | 0.591150 | 0.352545 | false | {"2026-08-31T00:00:00Z": 1} |
| holdout | 1431 | 1348 | 2.129464 | 2.005952 | 35.7365 | 59.3833 | 33.2661 | 180.3161 | 70870.8833 | 0.940697 | 1269 | 1349 | 0.972552 | 1311 | 1348 | 0 | 149640.0000 | 447990.0000 | 0.473609 | 0.128637 | 0.849462 | 0.601632 | 0.344020 | false | {"2026-09-28T00:00:00Z": 0} |
<!-- END:reference_metrics_snapshot -->

The golden fixture, `reference_metrics.sql` against the Python domain against `expected.json` (28 keys; the golden database, window `[2026-07-06T09:00:00Z, 2026-07-06T10:00:00Z)`):

<!-- BEGIN:golden_reference_metrics -->
| quantity | reference_metrics_sql | python_domain | expected_json |
|---|---|---|---|
| arrival_count | 3 | 3 | 3 |
| completion_count | 3 | 3 | 3 |
| arrival_rate_per_hour | 3.000000 | 3.000000 | 3.000000 |
| completion_rate_per_hour | 3.000000 | 3.000000 | 3.000000 |
| backlog | {"2026-07-06T09:05:00Z": 3, "2026-07-06T09:25:00Z": 1, "2026-07-06T10:00:00Z": 0} | {"2026-07-06T09:05:00Z": 3, "2026-07-06T09:25:00Z": 1, "2026-07-06T10:00:00Z": 0} | {"2026-07-06T09:05:00Z": 3, "2026-07-06T09:25:00Z": 1, "2026-07-06T10:00:00Z": 0} |
| first_response_minutes | {"t-001": "0.0000", "t-002": "10.0000", "t-003": "20.0000"} | {"t-001": "0.0000", "t-002": "10.0000", "t-003": "20.0000"} | {"t-001": "0.0000", "t-002": "10.0000", "t-003": "20.0000"} |
| mean_first_response_minutes | 10.0000 | 10.0000 | 10.0000 |
| p90_first_response_minutes | 20.0000 | 20.0000 | 20.0000 |
| wait_minutes | {"t-001": "0.0000", "t-002": "10.0000", "t-003": "20.0000"} | {"t-001": "0.0000", "t-002": "10.0000", "t-003": "20.0000"} | {"t-001": "0.0000", "t-002": "10.0000", "t-003": "20.0000"} |
| mean_wait_minutes | 10.0000 | 10.0000 | 10.0000 |
| resolution_minutes | {"t-001": "10.0000", "t-002": "20.0000", "t-003": "30.0000"} | {"t-001": "10.0000", "t-002": "20.0000", "t-003": "30.0000"} | {"t-001": "10.0000", "t-002": "20.0000", "t-003": "30.0000"} |
| mean_resolution_minutes | 20.0000 | 20.0000 | 20.0000 |
| handling_minutes_total | 30.0000 | 30.0000 | 30.0000 |
| sla_first_response_compliance | 0.666667 | 0.666667 | 0.666667 |
| sla_first_response_within | 2 | 2 | 2 |
| sla_first_response_eligible | 3 | 3 | 3 |
| sla_resolution_compliance | 1.000000 | 1.000000 | 1.000000 |
| sla_resolution_within | 3 | 3 | 3 |
| sla_resolution_eligible | 3 | 3 | 3 |
| open_overdue_at_cutoff | 0 | 0 | 0 |
| staffed_available_minutes | 60.0000 | 60.0000 | 60.0000 |
| staffed_shift_minutes_whole | 450.0000 | 450.0000 | 450.0000 |
| agent_occupancy | 0.500000 | 0.500000 | 0.500000 |
| abandonment_rate |  |  |  |
| csat | 1.000000 | 1.000000 | 1.000000 |
| survey_invitation_rate | 0.666667 | 0.666667 | 0.666667 |
| survey_response_rate | 0.500000 | 0.500000 | 0.500000 |
| empty_population | false | false | false |
<!-- END:golden_reference_metrics -->

Provenance of this run:

<!-- BEGIN:meta -->
| dataset_hash | dataset_version | code_revision | seeded_database_version | seeded_database_hash | seed | analysis_window_utc | reconciliation_rows |
|---|---|---|---|---|---|---|---|
| 944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4 | sf-20261026-20261026 | 43de7f8 | ds-d5d7a5e1b7df | d5d7a5e1b7dffdec089785448e3ae1241fd12bdbce67f5c14eccad767c6c174c | 20261026 | [2026-07-06T00:00:00Z, 2026-09-28T00:00:00Z) | 185 |
<!-- END:meta -->

## What the queries do not show
* **Nothing here is a measured effect on a real support team.** The queues, agents, tickets and every figure are generated; relationships the data shows were designed into it, so finding them shows the queries work, not that a business has them.
* **Observed is not simulated.** None of the figures above is a simulation result; the three simulated scenarios and their 50-replication intervals are in `executive-memo.md`, labelled as estimates.
* **Windows and cutoffs.** Open overdue is read at the window end, at twelve Monday cutoffs and at hourly samples; an episode shorter than an hour between samples is not seen. The training and holdout windows are weeks 1-8 and 9-12; the holdout's +20 % intensity is a chosen realisation, not a measurement.
* **Dormant gap.** Resolution is measured from the original arrival (D-09 R4-09), so a reopened ticket is charged the time it lay closed; query 05 shows how much of the resolution tail that is.
* **Staffed time** follows D-05 (a window that cuts a shift keeps the break in); the pro-rata break of query 01 is a different, disclosed choice for hours of the week. Calendars are ignored (A-5).
* **Defects and decisions open elsewhere** are in `technical-case-study.md`; C07 and C10 are 501 and are not analysed here.
