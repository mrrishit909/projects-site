# Onboard Studio — business case (P02-ART-01)

**Every stakeholder, interview and number here is simulated.** Nothing is a claim about a
real employer, real adoption or measured savings (P02-DOMAIN-06, master 10).

## Business problem
"Harbor Financial Services" (synthetic) onboards 40 business customers a month through a
multi-step workflow: collect documents, verify identity, assess risk, open the account.
Two workflow versions are in use. Reviews argue from calendar time (a Friday-afternoon case
"took three days"), count customer waiting as employee work, lose waiting history when work
is reassigned, and cannot say whether the newer workflow is faster or just measured
differently. Onboard Studio supports the decision: which onboarding workflow should be
adopted, and how should exceptions be handled? (P02-GOAL-01)

## Simulated stakeholders
| Role (simulated) | Need | Decision criterion |
|---|---|---|
| Head of onboarding | Adopt v1 or v2 | Active elapsed time and handoffs per case, same calendar, same population |
| Compliance lead | Exceptions handled without skipping controls | No completion with a missing required document; independent approver |
| Team lead | Where work waits | Step waiting time by step and assignee, business hours |
| Customer success | Customer waiting separated from processing | Paused time by reason, pause-eligible policy versioned |
| Analyst (primary user) | A timeline that reconciles to the SLA figure | Timeline business-hours axis equals the SLA explorer's numbers |

## Scope and non-goals
In scope: cases bound to immutable published workflow versions, dependency-ordered steps,
append-only document versions, independent approvals, working calendars with explicit
timezone and holidays, pause policies, SLA attainment on active elapsed time, backlog as-of a
cutoff, rework and first-pass rates, handoffs, step waiting, version comparison, a what-if
throughput simulation labelled as a model. Out of scope: real document storage, e-signature,
identity verification vendors, real stakeholder interviews, measured adoption.

## Current-state and future-state process
Current (simulated): intake by e-mail; a spreadsheet tracker with one row per case; waiting
time overwritten on reassignment; SLA judged on calendar days; the workflow template edited in
place while cases are open. Future: C01 binds the published version; C02–C06 move documents
and steps through explicit states with reasons; C08 pauses only for configured reasons;
C09 completes only when every required step and document is satisfied; C07/C10 (extension)
reassign and migrate with audit mappings. Exceptions are owned: missing documents by the
case owner, conflicting decisions by the compliance lead, pauses outside working hours by
the team lead (flagged, counted as zero business hours).

## Decision criteria for the recommendation
Adopt the version with lower active elapsed time and fewer handoffs on the same calendar and
population, provided its first-pass approval and document completeness are not worse; treat
the simulated capacity gain as a modelled direction with its assumptions printed, never as a
realised saving (P02-MET-12).
