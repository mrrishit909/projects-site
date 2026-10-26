# SQL analysis on the seeded snapshot (P02-ART-04)

Everything here is **synthetic**: the generated snapshot `os-20261026-20261026` (seed 20261026, generator `dataset_hash`
`3c20d296bcf178065e9178cae04f763994b4d7197026af2c021ab55b4cc2bc6a`, contract v1) seeded into PostgreSQL 16 through the domain's `validate_batch`, and the golden
fixture seeded into a second database. The generator **designed in** four relationships (`data/injection-manifest.json`: v2 faster with fewer handoffs, enterprise rework about 2x, `reg-north`
longer customer waiting, a bottleneck at `approve_account` for `rev-004`), so these queries show whether the data contains what was put there, not facts about a business. Every table below is the
observed output of the named file, rendered from `artifacts/analysis-results.json`, which `run_all.py` writes from the same run; no figure is typed in. Contract rules are cited as D-01..D-06 and
requirement ids as P02-MET-nn / P02-TEST-nn.

## Reproduce
```sh
cd apps/onboard-studio
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<empty snapshot database>
export GOLDEN_DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<empty golden database>
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py            # reset + migrate + seed web/public/data (about 8 s)
DATABASE_URL=$GOLDEN_DATABASE_URL ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json   # 00 views, 01..08, golden 09, reconciliations; exit 0 only if every check holds
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f data/sql/analysis/00_case_facts.sql -f data/sql/analysis/01_cycle_time_by_opening_month.sql   # any file also runs alone in psql after 00
```
Prepared snapshot database: 733 cases (712 completed, 21 open), 3,665 step instances, 4,362 assignments, 2,153 document versions, 3,601 approvals, 874 waiting intervals, 12,699 events, 398 calendar
intervals; 7 of the 740 generated cases and 2 single approvals were refused at ingest (269 rows in `rejected_records`, query 08). `run_all.py` took about 25 s. All ten SQL files were also run with
`psql -v ON_ERROR_STOP=1` (exit 0 each).

## Method (shared by every query, defined in `00_case_facts.sql`)
* **Population** = rows that survived ingest. Rejected cases are not in the tables; they are in `rejected_records` (query 08). Open cases (`completed_at IS NULL`) are listed beside completed-case metrics and never inside them (D-04).
* **Calendar cycle time** = `completed_at - opened_at` (P02-MET-01). **Business cycle time** = length of the case span intersected with the calendar's effective working set (P02-MET-02, D-01). The effective working set is
  `range_agg(working) - range_agg(holiday)` as a PostgreSQL multirange, so a holiday on a weekend subtracts nothing without a special case.
* **Paused time** = eligible waiting intervals (reason in `sla_rules.pause_policy`), **clipped to the case span and merged with `range_agg` before measuring** (D-06), so overlapping waits cannot be double counted.
  **Active elapsed** = business time minus the business overlap of the merged pauses, floored at 0 (P02-MET-04). SLA met when `active x 60 <= business_minutes` (D-05).
* Durations are exact numeric seconds; hours = seconds / 3600 only when displayed; means are sum / count; rounding is `round(x, 4)` (PostgreSQL rounds a numeric half away from zero, equal to ROUND_HALF_UP for positive hours).
* **Why a different method from `data/sql/reference_metrics.sql`:** the reference does plain interval-overlap arithmetic with no multirange; sharing no technique with it (and no code with the Python domain) is what makes agreement meaningful.

## Reconciliation (the check that makes the rest trustworthy)

### A. The golden case, per-case business hours from three sources
The golden case `case-001` (opened Fri 2026-03-06 16:00Z, completed Mon 2026-03-09 10:00Z; the waiting interval Fri 16:30Z to Mon 09:30Z) from `09_golden_case_business_hours.sql` (this directory), `data/sql/reference_metrics.sql`
(run on the same golden database) and the Python domain `run_pipeline` (both pause states), against the hand-derived `tests/fixtures/golden/expected.json`:

| quantity | analysis_sql_09 | reference_metrics_sql | python_domain | expected_json |
|---|---|---|---|---|
| calendar hours | 66.0000 | 66.0000 | 66.0000 | 66.0000 |
| BUSINESS hours | 2.0000 | 2.0000 | 2.0000 | 2.0000 |
| paused hours | 65.0000 | 65.0000 | 65.0000 | 65.0000 |
| paused business overlap | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| active, pause eligible | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| active, not eligible | 2.0000 | n/a (policy fixed in the rule) | 2.0000 | 2.0000 |

**Business hours of the golden case: 2.0000 from the analysis SQL, 2.0000 from `reference_metrics.sql`, 2.0000 from the Python domain, 2.0000 hand-derived.** Calendar 66, paused 65 (business overlap 1), active 1 with the pause
eligible and 2 when not. The reference SQL has no "not eligible" switch (it reads the rule's policy), so its last cell is `n/a`; the other three sources agree.

### B. The whole snapshot, three sources, and every case
Population means over the 712 completed cases from the view, from `reference_metrics.sql` and from the domain (`run_pipeline` over `web/public/data`, no database), then the domain recomputed for **each of the 712 completed cases
on its own** and compared with the view's four durations to 4 decimals:

| check | sql_view | second_source | third_source | equal |
|---|---|---|---|---|
| B snapshot population: completed_eligible_cases | 712 | 712 | 712 | True |
| B snapshot population: calendar_cycle_time_hours | 79.9529 | 79.9529 | 79.9529 | True |
| B snapshot population: business_cycle_time_hours | 18.5028 | 18.5028 | 18.5028 | True |
| B snapshot population: paused_time_hours | 35.4966 | 35.4966 | 35.4966 | True |
| B snapshot population: paused_business_overlap_hours | 10.6008 | 10.6008 | 10.6008 | True |
| B snapshot population: active_elapsed_hours | 7.9020 | 7.9020 | 7.9020 | True |
| B snapshot population: within_sla_cases | 380 | 380 | 380 | True |
| B per-case calendar/business/paused/active hours, cases differing (domain, 712 cases) | 0 | 0 |  | True |
| B completed cases compared per case | 712 | 712 |  | True |

### C and D. Groups, backlog, step waiting, rework, rejections
Per-version, per-segment and per-region counts, active hours, SLA attainment, handoffs and paused hours equal the domain's `group_metrics`; the 18 month-end backlog counts equal the domain's `open_backlog_at_cutoff`; the ten per-step-definition
waiting means equal the domain's; rework and first-pass equal the domain's; the rejected and flagged ids equal `data/injection-manifest.json` (INJ-01, 02, 03, 09, 10):

| check | sql_view | second_source | third_source | equal |
|---|---|---|---|---|
| C workflow_version=wfv-001: n / active / SLA / handoffs / paused | 430 / 9.2352 / 0.260465 / 484 / 34.5585 | 430 / 9.2352 / 0.260465 / 484 / 34.5585 |  | True |
| C workflow_version=wfv-002: n / active / SLA / handoffs / paused | 282 / 5.8690 / 0.950355 / 255 / 36.9271 | 282 / 5.8690 / 0.950355 / 255 / 36.9271 |  | True |
| C segment=enterprise: n / active / SLA / handoffs / paused | 158 / 8.1103 / 0.500000 / 160 / 39.7320 | 158 / 8.1103 / 0.500000 / 160 / 39.7320 |  | True |
| C segment=mid_market: n / active / SLA / handoffs / paused | 262 / 7.9557 / 0.515267 / 263 / 34.8602 | 262 / 7.9557 / 0.515267 / 263 / 34.8602 |  | True |
| C segment=smb: n / active / SLA / handoffs / paused | 292 / 7.7410 / 0.568493 / 316 / 33.7759 | 292 / 7.7410 / 0.568493 / 316 / 33.7759 |  | True |
| C region=reg-east: n / active / SLA / handoffs / paused | 195 / 7.7571 / 0.569231 / 217 / 29.6538 | 195 / 7.7571 / 0.569231 / 217 / 29.6538 |  | True |
| C region=reg-north: n / active / SLA / handoffs / paused | 156 / 7.7799 / 0.544872 / 142 / 59.0534 | 156 / 7.7799 / 0.544872 / 142 / 59.0534 |  | True |
| C region=reg-south: n / active / SLA / handoffs / paused | 186 / 8.2476 / 0.462366 / 204 / 30.5270 | 186 / 8.2476 / 0.462366 / 204 / 30.5270 |  | True |
| C region=reg-west: n / active / SLA / handoffs / paused | 175 / 7.8049 / 0.560000 / 176 / 26.2899 | 175 / 7.8049 / 0.560000 / 176 / 26.2899 |  | True |
| C 02 wfv-001 (all window): rework / first-pass vs domain | 0.180995 / 0.920849 | 0.180995 / 0.920849 |  | True |
| C 02 wfv-002 (all window): rework / first-pass vs domain | 0.193772 / 0.941718 | 0.193772 / 0.941718 |  | True |
| C backlog at 18 month-end cutoffs (sum of open_at_end) | 206 | 206 |  | True |
| C backlog per cutoff, cutoffs differing | 0 | 0 |  | True |
| C step waiting per step_definition (10), differing | 0 | 0 |  | True |
| C rework rate / first-pass approval (all cases) | 0.186047 / 0.930983 | 0.186047 / 0.930983 |  | True |
| D INJ-01 MISSING_REQUIRED_DOCUMENT cases | case-000218, case-000545 | case-000218, case-000545 |  | True |
| D INJ-02 DECISION_CONFLICT approvals | apr-000623, apr-003152 | apr-000623, apr-003152 |  | True |
| D INJ-03 PAUSE_OUTSIDE_WORKING_INTERVAL waits | wi-00396, wi-00704, wi-00753 | wi-00396, wi-00704, wi-00753 |  | True |
| D INJ-09 PAUSE_REASON_NOT_CONFIGURED cases | case-000138, case-000473, case-000541 | case-000138, case-000473, case-000541 |  | True |
| D INJ-10 SELF_APPROVAL cases | case-000075, case-000685 | case-000075, case-000685 |  | True |
| D domain flags equal SQL flags | 3 | 3 |  | True |
| D rejected rows kept (domain vs table) | 269 | 269 |  | True |

`run_all.py` ends with `RESULT: OK` and exit code 0 only when every row above is `True`.

## 01 Calendar against business cycle time by month of opening: `01_cycle_time_by_opening_month.sql` (P02-MET-01, P02-MET-02)
Completed cases grouped by the UTC month of `opened_at`; `cal_to_bus` = mean calendar hours / mean business hours.

| period | completed_cases | calendar_h | business_h | cal_to_bus | active_h |
|---|---|---|---|---|---|
| 2025-04 | 48 | 79.3858 | 19.5469 | 4.06 | 9.1330 |
| 2025-05 | 43 | 100.6601 | 22.2647 | 4.52 | 9.4512 |
| 2025-06 | 42 | 82.3552 | 18.8683 | 4.36 | 8.9230 |
| 2025-07 | 43 | 89.8244 | 22.1333 | 4.06 | 9.6740 |
| 2025-08 | 36 | 78.3065 | 17.3954 | 4.50 | 8.8218 |
| 2025-09 | 40 | 88.0121 | 20.2433 | 4.35 | 9.2867 |
| 2025-10 | 34 | 79.4838 | 18.3074 | 4.34 | 6.5716 |
| 2025-11 | 35 | 76.8433 | 17.2624 | 4.45 | 7.0233 |
| 2025-12 | 40 | 74.5975 | 17.1975 | 4.34 | 6.5600 |
| 2026-01 | 43 | 85.3535 | 18.4484 | 4.63 | 7.2535 |
| 2026-02 | 32 | 66.8760 | 16.3729 | 4.08 | 6.9604 |
| 2026-03 | 40 | 73.6108 | 17.0958 | 4.31 | 7.3067 |
| 2026-04 | 43 | 81.2508 | 18.3671 | 4.42 | 7.3721 |
| 2026-05 | 42 | 69.1893 | 16.4083 | 4.22 | 6.9956 |
| 2026-06 | 45 | 72.0448 | 17.1744 | 4.19 | 7.5315 |
| 2026-07 | 29 | 100.0540 | 21.2994 | 4.70 | 7.7989 |
| 2026-08 | 36 | 69.2806 | 17.2657 | 4.01 | 7.1569 |
| 2026-09 | 41 | 72.1634 | 16.8679 | 4.28 | 7.5492 |
| TOTAL | 712 | 79.9529 | 18.5028 | 4.32 | 7.9020 |

Observed: a completed case takes 79.9529 wall-clock hours on average but 18.5028 business hours, a factor of 4.32 (monthly factors 4.01 to 4.70). The wall-clock mean moves more than the business mean: 66.8760 (2026-02) to 100.6601 (2025-05)
against 16.3729 to 22.2647. Active elapsed time steps down from 8.8218-9.6740 in 2025-04..2025-09 to 6.5600-7.7989 from 2025-10, the month version 2 starts (query 02), while business hours move less (17.3954-22.2647 before, 16.3729-21.2994 after). A calendar-day SLA
would therefore misjudge Friday-afternoon cases that the working calendar treats as a couple of hours.

## 02 Version comparison on comparable windows: `02_version_comparison_comparable_window.sql` (P02-MET-04, 06, 07, 08, 10)
Version 2 exists only from 2025-10-01. The `all` rows compare v1 over 18 months with v2 over 12; the `overlap` rows keep cases opened from 2025-10-01 on, when both versions ran side by side. `paused_business_h` is the pause deduction, so
`active_h = business_h - paused_business_h` (individually rounded); `active_sd_h` is the sample standard deviation of active hours per case, `sla_if_no_pause` is attainment under the contract's other state, where no waiting reason is pause-eligible and active equals business time.

| window | version | completed_cases | open_cases | business_h | paused_business_h | active_h | active_sd_h | handoffs_per_case | sla_attainment | sla_if_no_pause | rework_rate | first_pass_rate | pct_enterprise | pct_reg_north |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all (2025-04..2026-09) | wfv-001 | 430 | 13 | 19.5686 | 10.3334 | 9.2352 | 1.7442 | 1.1093 | 0.260465 | 0.074419 | 0.180995 | 0.920849 | 24.7 | 22.1 |
| all (2025-04..2026-09) | wfv-002 | 282 | 8 | 16.8776 | 11.0086 | 5.8690 | 1.2797 | 0.8865 | 0.950355 | 0.290780 | 0.193772 | 0.941718 | 18.4 | 21.6 |
| overlap (2025-10..2026-09) | wfv-001 | 178 | 10 | 18.7568 | 9.5066 | 9.2503 | 1.7311 | 1.2135 | 0.258427 | 0.056180 | 0.160428 | 0.933036 | 20.2 | 22.5 |
| overlap (2025-10..2026-09) | wfv-002 | 282 | 8 | 16.8776 | 11.0086 | 5.8690 | 1.2797 | 0.8865 | 0.950355 | 0.290780 | 0.193772 | 0.941718 | 18.4 | 21.6 |

Observed, overlap window: v2 active elapsed time is 5.8690 h against 9.2503 h for v1, 3.3813 h (36.6 %) lower; handoffs per completed case are 0.8865 against 1.2135 (26.9 % fewer; 20.1 % fewer against the all-window v1 mean 1.1093);
SLA attainment is 0.950355 against 0.258427. Treating cases as independent, the standard error of the 3.3813 h difference is sqrt(1.7311^2/178 + 1.2797^2/282) = 0.1505 h, a rough 95 % interval of 3.0864 to 3.6762 h (sampling variation only). The gap is not all workflow speed: business hours differ by 1.8792 (18.7568 against 16.8776, 10.0 %), and v2 has 1.5020 more business hours deducted as customer waiting (11.0086 against 9.5066), which is
44 % of the active-time gap. With no pause deduction, SLA attainment is 0.290780 (v2) against 0.056180 (v1): v2 is ahead in both states, by a very different margin. The populations are not identical (enterprise 18.4 % of v2 against 20.2 % of v1 in the overlap window;
24.7 % of v1 in the all window; 252 of the 430 completed v1 cases, about 58 %, were opened before v2 existed). v2's rework rate is higher (0.193772 against 0.160428 in the overlap window) and its first-pass rate similar (0.941718 against 0.933036); `document_completeness` is 1 for all 712 completed cases (checked: none has a required type without an accepted version; the 0.997153 over all cases comes from 2 open cases), so it cannot separate the versions.
Handoff means are over completed cases only; the domain's `handoff_count` sums all cases (open ones included), which is the figure `run_all.py` reconciles.

## 03 SLA attainment by segment and region, open cases beside the rate: `03_sla_by_segment_region.sql` (P02-MET-05)
Attainment = completed cases with active <= 480 business minutes / completed cases. `open_cases_not_in_rate` are cases without `completed_at`; `pct_v2` is the share of the cell's completed cases on workflow v2.

| segment | region | completed_cases | within_sla | sla_attainment | open_cases_not_in_rate | active_h | pct_v2 |
|---|---|---|---|---|---|---|---|
| enterprise | reg-east | 50 | 25 | 0.500000 | 2 | 8.0280 | 34.0 |
| enterprise | reg-north | 29 | 15 | 0.517241 | 1 | 8.1408 | 37.9 |
| enterprise | reg-south | 43 | 20 | 0.465116 | 1 | 8.3554 | 30.2 |
| enterprise | reg-west | 36 | 19 | 0.527778 | 0 | 7.9074 | 30.6 |
| enterprise | ALL | 158 | 79 | 0.500000 | 4 | 8.1103 | 32.9 |
| mid_market | reg-east | 64 | 38 | 0.593750 | 1 | 7.6661 | 46.9 |
| mid_market | reg-north | 61 | 25 | 0.409836 | 1 | 8.1500 | 31.1 |
| mid_market | reg-south | 66 | 32 | 0.484848 | 3 | 8.3442 | 37.9 |
| mid_market | reg-west | 71 | 40 | 0.563380 | 0 | 7.6885 | 45.1 |
| mid_market | ALL | 262 | 135 | 0.515267 | 5 | 7.9557 | 40.5 |
| smb | reg-east | 81 | 48 | 0.592593 | 5 | 7.6617 | 45.7 |
| smb | reg-north | 66 | 45 | 0.681818 | 3 | 7.2793 | 47.0 |
| smb | reg-south | 77 | 34 | 0.441558 | 3 | 8.1045 | 39.0 |
| smb | reg-west | 68 | 39 | 0.573529 | 1 | 7.8721 | 38.2 |
| smb | ALL | 292 | 166 | 0.568493 | 12 | 7.7410 | 42.5 |
| ALL | reg-east | 195 | 111 | 0.569231 | 8 | 7.7571 | 43.1 |
| ALL | reg-north | 156 | 85 | 0.544872 | 5 | 7.7799 | 39.1 |
| ALL | reg-south | 186 | 86 | 0.462366 | 7 | 8.2476 | 36.6 |
| ALL | reg-west | 175 | 98 | 0.560000 | 1 | 7.8049 | 39.4 |
| ALL | ALL | 712 | 380 | 0.533708 | 21 | 7.9020 | 39.6 |

Observed: overall attainment is 0.533708 (380 of 712 completed cases), with 21 open cases beside it. Segment margins run 0.500000 (enterprise, 79 of 158) to 0.568493 (smb, 166 of 292); region margins run 0.462366 (reg-south) to 0.569231 (reg-east).
Cell values range from 0.409836 (mid_market, reg-north, 25 of 61) to 0.681818 (smb, reg-north, 45 of 66) on 29 to 81 completed cases per cell, and `pct_v2` ranges 30.2 to 47.0 across cells. Because attainment is 0.26 on v1 and 0.95 on v2 (query 02), differences between cells
mix version share with noise; no adjustment is made here and no confidence interval is computed.

## 04 Step waiting by step and by person: `04_step_waiting_by_step_assignee.sql` (P02-MET-09, P02-GOLD-05)
`wait_bh` is the contract's step waiting (business hours from `ready_at` to `started_at`); `started_to_decision_*` is started to approval decision in business hours and on the wall clock. Lens `assignee` is the person holding the step when it started (`assignments`);
lens `reviewer` is the person who decided it (`approvals`); `undecided` steps belong to open cases.

| lens | step_name | who | step_instances | wait_bh | started_to_decision_bh | started_to_decision_cal_h |
|---|---|---|---|---|---|---|
| step | approve_account | ALL | 718 | 1.0491 | 1.4059 | 4.5903 |
| step | compliance_review | ALL | 725 | 0.5163 | 4.7131 | 22.6184 |
| step | verify_identity | ALL | 441 | 0.4992 | 3.2435 | 13.2986 |
| step | collect_documents | ALL | 733 | 0.3788 | 6.0432 | 28.6076 |
| step | collect_address_proof | ALL | 290 | 0.3339 | 4.7291 | 21.1443 |
| step | activate_account | ALL | 716 | 0.2989 | 0.6023 | 2.4450 |
| assignee | approve_account | acc-002 | 162 | 1.1281 | 1.4202 | 5.4695 |
| assignee | approve_account | acc-003 | 181 | 1.0848 | 1.4078 | 4.8995 |
| assignee | approve_account | acc-004 | 183 | 1.0259 | 1.3978 | 3.9473 |
| assignee | approve_account | acc-001 | 192 | 0.9711 | 1.3998 | 4.1642 |
| reviewer | approve_account | rev-004 | 292 | 1.7855 | 1.9605 | 7.6865 |
| reviewer | approve_account | undecided | 2 | 0.9583 |  |  |
| reviewer | approve_account | rev-006 | 212 | 0.5451 | 1.0287 | 2.0098 |
| reviewer | approve_account | rev-005 | 212 | 0.5398 | 1.0193 | 2.9061 |

Observed: `approve_account` has the longest step waiting, 1.0491 business hours, against 0.5163 for `compliance_review` and 0.2989 for `activate_account`. Within it the **bottleneck is a reviewer, not an assignee**: rev-004 waits 1.7855 h over 292 steps against 0.5398 (rev-005) and 0.5451 (rev-006),
about 3.3 times; decisions take 1.9605 business hours against 1.0193 and 1.0287 and 7.6865 wall-clock hours against 2.9061 and 2.0098. By assignee (acc-001 to acc-004) the same step waits 0.9711 to 1.1281 h, so an analysis of `assignments` alone would not show the bottleneck;
it appears only when `approvals.reviewer_id` is joined. The generator's designed factor was 3.6 for the queue; the observed 3.3 is in business hours.

## 05 Rework and first pass by segment: `05_rework_first_pass_by_segment.sql` (P02-MET-06, P02-MET-07)
Rework rate = cases with a rejected document version / cases with a submission; first-pass rate = accepted first submissions / reviewed first submissions. All cases (open included), as the contract defines them.

| lens | segment | document_type | cases_with_submission | cases_reworked | rework_rate | first_reviewed | first_accepted | first_pass_rate |
|---|---|---|---|---|---|---|---|---|
| segment | enterprise | ALL | 162 | 47 | 0.290123 | 424 | 377 | 0.889151 |
| segment | mid_market | ALL | 267 | 46 | 0.172285 | 740 | 692 | 0.935135 |
| segment | smb | ALL | 302 | 43 | 0.142384 | 850 | 806 | 0.948235 |
| segment | ALL | ALL | 731 | 136 | 0.186047 | 2014 | 1875 | 0.930983 |
| document_type | enterprise | address_proof |  |  |  | 54 | 53 | 0.981481 |
| document_type | mid_market | address_proof |  |  |  | 107 | 100 | 0.934579 |
| document_type | smb | address_proof |  |  |  | 128 | 119 | 0.929688 |
| document_type | ALL | address_proof |  |  |  | 289 | 272 | 0.941176 |
| document_type | enterprise | approval_form |  |  |  | 46 | 46 | 1.000000 |
| document_type | mid_market | approval_form |  |  |  | 99 | 99 | 1.000000 |
| document_type | smb | approval_form |  |  |  | 118 | 118 | 1.000000 |
| document_type | ALL | approval_form |  |  |  | 263 | 263 | 1.000000 |
| document_type | enterprise | business_registration |  |  |  | 162 | 155 | 0.956790 |
| document_type | mid_market | business_registration |  |  |  | 267 | 261 | 0.977528 |
| document_type | smb | business_registration |  |  |  | 302 | 298 | 0.986755 |
| document_type | ALL | business_registration |  |  |  | 731 | 714 | 0.976744 |
| document_type | enterprise | identity_proof |  |  |  | 162 | 123 | 0.759259 |
| document_type | mid_market | identity_proof |  |  |  | 267 | 232 | 0.868914 |
| document_type | smb | identity_proof |  |  |  | 302 | 271 | 0.897351 |
| document_type | ALL | identity_proof |  |  |  | 731 | 626 | 0.856361 |

Observed: overall rework 0.186047 (136 of 731 cases with a submission) and first pass 0.930983 (1,875 of 2,014). Enterprise rework is 0.290123 against 0.172285 (mid_market) and 0.142384 (smb), 2.0 times smb and 1.7 times mid_market. The difference sits in `identity_proof`:
first-pass 0.759259 for enterprise against 0.868914 and 0.897351; `approval_form` was accepted on the first submission every time (263 of 263) and `business_registration` 0.976744.

## 06 Paused time by reason and region: `06_paused_time_by_reason_region.sql` (P02-MET-03, P02-DOMAIN-03)
Lens `reason_region`: waits of completed cases (clipped to the case span), mean wall-clock and business hours per wait. Lens `region`: the contract's `paused_time_hours` per completed case (eligible waits merged per case).

| lens | reason | region | in_pause_policy | waits | completed_cases | cases_with_wait | wait_h | wait_business_h | paused_h_per_case |
|---|---|---|---|---|---|---|---|---|---|
| region | ALL eligible | reg-east | true |  | 195 | 137 |  |  | 29.6538 |
| region | ALL eligible | reg-north | true |  | 156 | 132 |  |  | 59.0534 |
| region | ALL eligible | reg-south | true |  | 186 | 130 |  |  | 30.5270 |
| region | ALL eligible | reg-west | true |  | 175 | 119 |  |  | 26.2899 |
| region | ALL eligible | ALL | true |  | 712 | 518 |  |  | 35.4966 |
| reason_region | customer_info_requested | reg-east | true | 176 |  |  | 28.9410 | 8.6705 |  |
| reason_region | customer_info_requested | reg-north | true | 210 |  |  | 38.8533 | 11.1670 |  |
| reason_region | customer_info_requested | reg-south | true | 173 |  |  | 28.2356 | 8.4372 |  |
| reason_region | customer_info_requested | reg-west | true | 149 |  |  | 27.0348 | 7.5117 |  |
| reason_region | external_verification | reg-east | true | 33 |  |  | 20.8753 | 6.8677 |  |
| reason_region | external_verification | reg-north | true | 41 |  |  | 25.6862 | 8.3431 |  |
| reason_region | external_verification | reg-south | true | 36 |  |  | 22.0347 | 8.2181 |  |
| reason_region | external_verification | reg-west | true | 31 |  |  | 18.4694 | 7.5253 |  |

Observed: `reg-north` pauses 59.0534 h per completed case against 29.6538 (reg-east), 30.5270 (reg-south) and 26.2899 (reg-west). Two things add up: more cases wait (132 of 156 = 84.6 % against 68.0 % to 70.3 %) and each `customer_info_requested` wait is longer (38.8533 h against 27.0348 to 28.9410,
1.3 to 1.4 times). `external_verification` is 141 waits in completed cases and shorter (18.4694 to 25.6862 h). Both reasons are in the SLA rules' pause policy, so every one of these hours is deducted from active time where it overlaps working hours; across the snapshot 518 of 712 completed cases have at least one eligible wait.

## 07 Backlog as of month-ends: `07_backlog_month_ends.sql` (P02-MET-11)
Open cases at the first instant of the next month (UTC); `opened` and `completed` count the month itself, so `open_at_end` = previous + opened - completed on every row.

| month | cutoff | opened | completed | open_at_end | open_v1 | open_v2 |
|---|---|---|---|---|---|---|
| 2025-04 | 2025-05-01T00:00Z | 48 | 43 | 5 | 5 | 0 |
| 2025-05 | 2025-06-01T00:00Z | 44 | 40 | 9 | 9 | 0 |
| 2025-06 | 2025-07-01T00:00Z | 43 | 47 | 5 | 5 | 0 |
| 2025-07 | 2025-08-01T00:00Z | 44 | 42 | 7 | 7 | 0 |
| 2025-08 | 2025-09-01T00:00Z | 36 | 39 | 4 | 4 | 0 |
| 2025-09 | 2025-10-01T00:00Z | 40 | 37 | 7 | 7 | 0 |
| 2025-10 | 2025-11-01T00:00Z | 35 | 34 | 8 | 4 | 4 |
| 2025-11 | 2025-12-01T00:00Z | 35 | 34 | 9 | 6 | 3 |
| 2025-12 | 2026-01-01T00:00Z | 41 | 42 | 8 | 6 | 2 |
| 2026-01 | 2026-02-01T00:00Z | 45 | 44 | 9 | 5 | 4 |
| 2026-02 | 2026-03-01T00:00Z | 32 | 33 | 8 | 5 | 3 |
| 2026-03 | 2026-04-01T00:00Z | 43 | 34 | 17 | 8 | 9 |
| 2026-04 | 2026-05-01T00:00Z | 44 | 44 | 17 | 11 | 6 |
| 2026-05 | 2026-06-01T00:00Z | 44 | 42 | 19 | 12 | 7 |
| 2026-06 | 2026-07-01T00:00Z | 46 | 47 | 18 | 12 | 6 |
| 2026-07 | 2026-08-01T00:00Z | 29 | 29 | 18 | 11 | 7 |
| 2026-08 | 2026-09-01T00:00Z | 37 | 38 | 17 | 11 | 6 |
| 2026-09 | 2026-10-01T00:00Z | 47 | 43 | 21 | 13 | 8 |

Observed: the backlog sits at 4 to 9 cases through 2026-02, jumps to 17 at 2026-03 (43 opened, 34 completed), stays at 17 to 19 and ends at 21 on 2026-10-01T00:00Z, equal to the 21 cases without a completion instant (13 on v1, 8 on v2). The data do not say why completions fell behind in
2026-03. The generator stalls about 3 % of cases on purpose (`data/README-generator.md`), so some stock is designed, but nothing in these queries explains the size of the one-month step.

## 08 Flags and rejections by reason: `08_flags_and_rejections_by_reason.sql` (P02-TEST-01, 02, 03, 09, 10)
`rejection` rows come from `rejected_records`; the `flag` row is accepted data the contract marks (an eligible wait with zero business time).

| lens | reason | cases | approvals | other_child_rows | total_rows | ids |
|---|---|---|---|---|---|---|
| rejection | DECISION_CONFLICT | 0 | 2 | 0 | 2 | apr-000623, apr-003152 |
| rejection | MISSING_REQUIRED_DOCUMENT | 2 | 10 | 58 | 70 | case-000218, case-000545 |
| rejection | PAUSE_REASON_NOT_CONFIGURED | 3 | 15 | 95 | 113 | case-000138, case-000473, case-000541 |
| rejection | SELF_APPROVAL | 2 | 10 | 72 | 84 | case-000075, case-000685 |
| flag | PAUSE_OUTSIDE_WORKING_INTERVAL | 3 | 0 | 0 | 3 | wi-00396, wi-00704, wi-00753 |

Observed: 269 rows kept = 2 + 70 + 113 + 84. The ids equal `data/injection-manifest.json` exactly (INJ-01: 2 cases, INJ-02: 2 later approvals, INJ-03: 3 flagged waits, INJ-09: 3 cases, INJ-10: 2 cases), and the domain's own flag list has the same 3 members (reconciliation row D above).
INJ-08 (two weekend holidays, 2026-02-14 and 2026-07-04) leaves no trace in these tables by design: they subtract nothing.

## 09 Golden case: `09_golden_case_business_hours.sql`
Run on the golden database only (on the snapshot it returns 0 rows). Output and the three-source comparison are in the reconciliation above.

## Limits of this analysis
* One synthetic dataset, one seed, no confidence intervals; designed-in relationships are being rediscovered, not discovered.
* Query 04's reviewer lens depends on `approvals.reviewer_id`; in the data model assignees and reviewers are different people, which is itself the finding.
* The reconciliation proves three implementations agree on this data; it does not prove the contract is the right definition. The independent review (`docs/program/verification-ledger.json`, entry of 2026-10-26T13:25:24Z) records open defects in other parts, listed in `technical-case-study.md`, including Q-03: `reference_metrics.sql`
  divides per case before averaging and does not merge overlapping waits. Neither affects these figures: the snapshot's eligible waits never overlap within a case, and this directory sums exact seconds before dividing. Population means agree with the reference to 4 decimals (rows above).
