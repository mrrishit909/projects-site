# Onboard Studio — business contracts, version 1 (2026-10-26)

Decision owner: coordinator (Fable 5.1). Spec: `projects/02-onboard-studio.md`, SHA-256
`e26d1733…df9` at pack commit `fe5f7981`. Every rule cites the requirement it satisfies.
Changing a rule bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
Which onboarding workflow should be adopted and how should exceptions be handled?
(P02-GOAL-01). Primary user: a business systems analyst comparing two workflow versions on
cycle time, waiting, rework and SLA attainment. Non-goals: real document storage, e-signature,
real stakeholder interviews or measured adoption (P02-DOMAIN-06).

## D-01 Time, calendars and intervals
* All timestamps are UTC instants. A working calendar is a set of `calendar_intervals`
  `[starts_at, ends_at)` with an explicit IANA `timezone` (P02-DOMAIN-04); the fixture
  calendar is Monday–Friday 09:00–17:00 UTC with no holidays. A holiday is an interval
  subtracted from the working set; a holiday on a weekend subtracts nothing (P02-TEST-08).
* Durations are hours as decimal strings with 4 decimals; never negative (P02-MET-04).
* Calendar cycle time = `completed_at − opened_at` for completed cases (P02-MET-01).
* Business cycle time = Σ overlap of `[opened_at, completed_at)` with the calendar intervals
  (P02-MET-02).
* Paused time = Σ waiting intervals whose reason is configured as pause-eligible in the
  case's `sla_rules.pause_policy` (P02-MET-03, P02-FLOW-08); a pause interval outside any
  working interval contributes 0 business hours and is flagged (P02-TEST-03).
* Active elapsed = business cycle time − business overlap of eligible paused intervals
  (P02-MET-04). Golden (P02-GOLD-01): opened Fri 16:00, completed Mon 10:00 → calendar 66 h,
  business 2 h; waiting Fri 16:30 → Mon 09:30 overlaps 1 business hour → active 1 h when the
  reason is pause-eligible, 2 h when it is not.
* Customer waiting (`waiting_external`) is never counted as employee processing
  (P02-DOMAIN-03, P02-TEST-09).

## D-02 Workflow versions and cases
* A `workflow_versions` row is immutable once `published_at` is set; its `definition_hash` is
  the sha256 of its ordered step definitions and dependencies. A case binds one
  `workflow_version_id` at creation and keeps it (P02-DOMAIN-01, P02-FLOW-01, P02-TEST-04).
* Publishing a version with a dependency cycle is rejected with `DEPENDENCY_CYCLE`
  (Kahn's algorithm over `dependencies`) (P02-DOMAIN-02, P02-TEST-05).
* Migration to a new version is an explicit command that writes a step mapping and lists
  unresolved steps; accepted documents are carried by `document_type` and never dropped
  (P02-FLOW-10, P02-TEST-12).

## D-03 Steps, documents, approvals
* Step instance states: `blocked → ready → in_progress → in_review → approved | changes_requested → ready`.
  A step becomes `ready` only when every mandatory prerequisite is `approved`
  (P02-FLOW-05).
* Documents are append-only versions; a resubmission creates a new `document_versions`
  row and leaves the prior row intact (P02-FLOW-04, P02-TEST-06). Content is a synthetic
  placeholder hash, never a real file (P02-FLOW-02).
* Approval requires a reviewer whose role matches `step_definitions.role_key` and who is
  not the step's current assignee (P02-FLOW-06, P02-TEST-10). Two decisions on the same
  step version conflict: the second is rejected with `DECISION_CONFLICT` unless it carries
  the new version number (P02-TEST-02).
* Case completion requires every `required` step `approved` and every required document
  type `accepted` (P02-FLOW-09, P02-TEST-01). A completed case cannot be reopened; a
  correction opens a linked new case (P02-TEST-11).
* Reassignment closes the prior assignment interval (`ended_at`) and never deletes it,
  so waiting time is preserved (P02-FLOW-07, P02-TEST-07). Handoff count = number of
  assignment rows − 1 per step, excluding exact replays (P02-MET-08).

## D-04 Rates and backlog
| Metric | Formula | Zero/empty |
|---|---|---|
| SLA attainment | completed eligible cases within SLA ÷ completed eligible cases | null when 0 completed |
| Rework rate | cases with ≥1 rejected submission ÷ cases with ≥1 submission | null |
| First-pass approval | approved first submissions ÷ first submissions reviewed | null (pending excluded) |
| Document completeness | required accepted types present ÷ required types | null when 0 required |
| Open backlog | count of cases open at the cutoff instant (as-of reconstruction from events) | 0 |
| Step waiting time | first `in_progress` instant − `ready` instant, business hours | null when never started |
| Simulated capacity gain | proposed modeled throughput − baseline modeled throughput, cases/period, labelled estimate | null when no model |

Rates are proportions in [0,1] to six decimals, computed from aggregated numerators and
denominators. Open cases are shown beside, never inside, SLA attainment.

## Mode disclosure
Mode A: Python domain + PostgreSQL + FastAPI commands verified on GitHub-hosted runners.
Mode B: TypeScript re-implementation over a published synthetic snapshot; all case actions
are browser-memory simulations; a reload restores the snapshot.

## D-05 Fixture-driven clarifications (2026-10-26, adopted from A-012)
* Required document types per workflow version are carried in a `workflow_requirements`
  block (`{workflow_version_id: {required_document_types: [...]}}`) until a table exists.
* `SELF_APPROVAL` (reviewer equals any assignee ever on the step) rejects the case and all
  its child rows at ingest with that reason.
* SLA test: `active_elapsed_hours × 60 ≤ business_minutes`. Backlog: a case is open when
  `opened_at ≤ cutoff < completed_at` (null `completed_at` counts as open).
* Population durations are the mean over accepted completed cases; rates are aggregated
  numerators over denominators.
* `definition_hash` = sha256 of compact sorted-key JSON `{"steps": [[id, name, required,
  role_key, sequence]…], "dependencies": [[step_definition_id, prerequisite_id, type]…]}`.
* Step waiting = `started_at − ready_at` in business hours.
