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
* Known limitation (Q-07, documented, not fixed): instants are exact to the microsecond in Python and to the
  millisecond in the TypeScript domain (epoch milliseconds). Sub-millisecond timestamps can therefore differ by up to
  0.999 ms between the two implementations; the generator, the fixtures and the API's own clock all work in whole
  seconds or milliseconds, so no published figure is affected.

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
  type `accepted` on its latest version (D-06; P02-FLOW-09, P02-TEST-01). A completed case cannot be reopened; a
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

## D-06 Schema clarifications (2026-10-26, adopted from A-013)
`calendar_intervals.kind` ∈ {working, holiday}; `workflow_requirements` table holds the
required document types per version; `document_reviews` is a separate append-only table
(the effective review status is the latest review); `approvals.version_number` with a
unique (step_instance_id, version_number) makes a second decision a `DECISION_CONFLICT`;
`cases.linked_case_id` records the correction case opened instead of a reopen. Waiting
intervals are clipped to the case span and merged before deduction; active hours floor at 0.

## D-06 amendment: the latest version decides (2026-10-26, finding Q-04)
A document type counts as `accepted` only when its latest version (highest `version_number`) has the effective status
`accepted`. Accepted on v1 and rejected or still submitted on v2 means the type is not accepted: the case cannot
complete (API `MISSING_REQUIRED_DOCUMENT`, ingest rejects a completed case with that reason) and `document_completeness`
does not count the type. This is the same in Python ingest/metrics, the API and the TypeScript domain. Rework rate
(any rejected version) and first-pass approval (the first version) are unchanged. The golden fixture has one version
per type, so its numbers are unchanged and `CONTRACT_VERSION` stays `v1`.

## D-07 Completion ordering and pause bounds (2026-10-26, finding Q-01)
* `complete-case` rejects an `occurred_at` earlier than the latest instant recorded on the case, with 422
  `COMPLETION_BEFORE_RECORDED_WORK` (`details[].context.latest_recorded_at`). "Recorded" means any `case_events.occurred_at`,
  approval `decided_at`, document review `decided_at`, assignment `ended_at` and waiting interval start or end. Equality is
  allowed (`occurred_at >= latest`).
* Open waiting at completion: **choose close**. Every waiting interval still open when the case completes is closed at
  the completion instant (`ends_at = completed_at`). Because completion cannot precede any waiting start, none can start
  after the completion instant, so nothing stays open on a completed case.
* `pause-sla` on an open case rejects an interval that starts before `opened_at` with 422 `PAUSE_OUTSIDE_CASE_SPAN`
  (`details[].context` carries `opened_at`, `completed_at`). The same rule refuses an interval that starts at or after
  `completed_at` or ends after it. A pause on an already completed case is refused first by the case state, 409
  `CASE_ALREADY_COMPLETE` (P02-TEST-11).
* Database backstop: a trigger refuses to set `cases.completed_at` earlier than any `case_events.occurred_at` of the
  case, and refuses a `case_events` row later than the case's `completed_at` (`integrity_constraint_violation`, mapped by
  the API to 409 `INTEGRITY_RULE`). Ingest already rejects the same shape with `CASE_ALREADY_COMPLETE`.

## D-08 Concurrency (2026-10-26, finding Q-02)
* Lock order is the same for every command: advisory lock on the idempotency key, then the **case row**, then the
  **step instance row** (`FOR UPDATE`). Commands that start from a step (`approve-step`, `unlock-dependent-step`) find the
  step's case first and lock it before the step, so they cannot deadlock with `submit`, `reject`, `resubmit` or `complete`.
* A command is one transaction. A PostgreSQL deadlock (`40P01`) or serialization failure (`40001`) rolls the whole
  attempt back and the command is retried, at most 3 attempts in all with a short randomised back-off. If the third
  attempt fails too the answer is 409 `CONCURRENT_UPDATE`; the client may retry with the same idempotency key. No
  concurrent pair of commands produces a 500.
* Idempotency is bound to the actor (Q-06): the same key from a different `X-Actor-Id` is 409 `IDEMPOTENCY_KEY_REUSED`
  (rule `IDEMPOTENCY_ACTOR_MISMATCH`). The payload hash normalises every instant (`occurred_at`, `starts_at`, `ends_at`) to
  UTC with `Z`, so `...10:00:00+00:00`, `...10:00:00Z` and `...11:00:00+01:00` are one payload.

## D-09 Unevaluated SLA cases (2026-10-26, finding Q-05)
* `calendars` is a table; `sla_rules.calendar_id` and `calendar_intervals.calendar_id` are foreign keys to it.
  `publish-workflow-version` with an unknown `sla_rule.calendar_id` is 422 `CALENDAR_UNKNOWN` and writes nothing.
* A calendar with no `working` interval (none at all, or only holidays) cannot measure business time. A completed case
  whose SLA rule points at such a calendar is **unevaluated**: it is excluded from `completed_eligible_cases`, from every
  mean and from the SLA denominator, and it is counted in `sla_unevaluated_cases`. It is never "met with 0 hours".
* The count is reported beside the metrics, not inside the golden metric set: `PipelineResult.sla_unevaluated_cases`
  (Python) and `.sla_unevaluated_cases` (TypeScript), one flag `SLA_UNEVALUATED_NO_WORKING_TIME` per case in `flags`, the
  `sla_unevaluated_cases` column of `data/sql/reference_metrics.sql`, and `data.sla_unevaluated_cases` plus one warning
  per case in `GET /metrics`. Python, SQL and TypeScript apply the same rule.
* SQL reference (Q-03): per-case seconds are summed first and divided once per metric (`SUM(seconds) / (3600 * cases)`,
  numeric, rounded half-up to 4 decimals), and the waiting intervals of a case are clipped and merged (gaps and islands)
  before deduction, which is the D-06 merge rule.
