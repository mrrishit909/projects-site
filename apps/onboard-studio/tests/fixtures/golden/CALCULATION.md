# Onboard Studio golden calculation (contract v1)

Independent of application code. `../../reference_check.py` recomputes every number below from `inputs.json`
and compares it with `expected.json`. Durations are hours, exact at 4 decimal places; rates exact at 6.

## The spec sentence [P02-GOLD-01]

> Calendar Monday-Friday 09:00-17:00 UTC, no holidays: case opens Friday 16:00 and completes Monday 10:00. Calendar elapsed=66 hours,
> working elapsed=2 hours. Waiting interval Friday 16:30 to Monday 09:30 overlaps one working hour, so active working elapsed=1 hour
> when that reason is pause-eligible.

Records: org-001, wfv-001 (sd-001 collect_documents role ops; sd-002 approve_account role reviewer; sd-002 depends on sd-001),
SLA sla-001 480 business minutes on cal-001, case-001 opened Fri 2026-03-06T16:00Z, completed Mon 2026-03-09T10:00Z.
Working intervals of cal-001 (ci-001..ci-010): 09:00-17:00 UTC on 03-02..03-06 and 03-09..03-13.

## Interval arithmetic

Only two working intervals touch the case: ci-005 Fri 03-06 09:00-17:00 and ci-006 Mon 03-09 09:00-17:00.

| Quantity | Interval | Overlap with ci-005 (Fri) | Overlap with ci-006 (Mon) | Result |
|---|---|---|---|---|
| Calendar cycle time | Fri 16:00 -> Mon 10:00 | n/a (wall clock) | n/a | 8 h (Fri 16:00-24:00) + 24 h (Sat) + 24 h (Sun) + 10 h (Mon 00:00-10:00) = **66.0000** |
| Business cycle time | Fri 16:00 -> Mon 10:00 | 16:00-17:00 = 1 h | 09:00-10:00 = 1 h | 1 + 1 = **2.0000** |
| Paused calendar time | Fri 16:30 -> Mon 09:30 (wi-001) | n/a | n/a | 7.5 h + 24 h + 24 h + 9.5 h = **65.0000** |
| Paused business overlap | Fri 16:30 -> Mon 09:30 | 16:30-17:00 = 0.5 h | 09:00-09:30 = 0.5 h | 0.5 + 0.5 = **1.0000** |

Sat and Sun contain no working interval, so they add 0 to every business figure.

## State A: pause-eligible (pause_policy = ["customer_info_requested"])

| Metric | Arithmetic | Result |
|---|---|---|
| calendar_cycle_time_hours | 66 | **66.0000** |
| business_cycle_time_hours | 2 | **2.0000** |
| paused_time_hours | wi-001 is eligible: 65 | **65.0000** |
| paused_business_overlap_hours | 1 | **1.0000** |
| active_elapsed_hours | 2.0000 - 1.0000 | **1.0000** |
| sla_attainment | active 1 h x 60 = 60 min <= 480 min; 1 within / 1 completed eligible | **1.000000** |
| completed_eligible_cases / within_sla_cases | | 1 / 1 |

## State B: pause-not-eligible (pause_policy = [])

wi-001 is not eligible, so no paused time is deducted: paused_time_hours **0.0000** (the 65 h waiting interval is still
recorded as a waiting interval, it is just not an eligible pause), paused_business_overlap_hours **0.0000**,
active_elapsed_hours 2.0000 - 0.0000 = **2.0000**; SLA: 120 min <= 480 min, sla_attainment **1.000000**.
Calendar and business cycle time are unchanged (66.0000, 2.0000).

## Metrics that do not depend on the state

| Metric | Arithmetic | Result |
|---|---|---|
| open_backlog_at_cutoff 2026-03-07T12:00Z | case-001 opened 03-06 16:00 <= cutoff < completed 03-09 10:00: open | **1** |
| open_backlog_at_cutoff 2026-03-09T12:00Z | completed 03-09 10:00 <= cutoff: closed | **0** |
| rework_rate | cases with a rejected submission 0 / cases with a submission 1 | **0.000000** |
| handoff_count | one assignment per step: (1-1) + (1-1) | **0** |
| step_waiting_time_hours sd-001 | ready Fri 16:00 -> started Fri 16:05, inside ci-005: 5 min = 5/60 | **0.0833** |
| step_waiting_time_hours sd-002 | ready Mon 09:40 -> started 09:45, inside ci-006: 5 min = 5/60 | **0.0833** |
| first_pass_approval | doc-001 v1 is a first submission, reviewed, accepted: 1 / 1 | **1.000000** |
| document_completeness | required type identity_proof accepted (doc-001): 1 / 1 | **1.000000** |

The workflow's required document types are carried in `inputs.json` as `workflow_requirements` (the entity list has no table for them).
The approval of sd-001 by rev-001 (assignee ops-001) and of sd-002 by rev-002 (assignee ops-002) are not self-approvals.

## Rejected variant (`variant-rejected/`)

case-002 (Tue 2026-03-10 09:00-11:00) has an approval on sd-002 (si-202, apr-202) made by ops-002, who is the step's own
assignee (asg-202). Ingest rejects apr-202 with `SELF_APPROVAL`, and with it the case it would complete: case-002, its two step
instances, two assignments, document doc-201, both approvals and two events (10 rejected rows, all `SELF_APPROVAL`). The accepted
population is case-001 only, so every metric equals the golden values in both states.

## Empty variant (`variant-empty/`)

Organizations, workflow, SLA rule and calendar only; no cases. Durations, SLA attainment, rework, first-pass and completeness
are `null` (zero denominators), step waiting times are `null` per step, open_backlog is 0 at both cutoffs, counts (handoffs,
completed eligible cases, within-SLA cases) are 0 and `empty_population` is true.
