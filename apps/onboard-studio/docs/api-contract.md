# Onboard Studio — API route inventory (backend contract, Mode A only)

Same envelopes, status codes and identity headers as Revenue Atlas (`apps/revenue-atlas/docs/api-contract.md`).
Prefix `/api/v1/onboard-studio`. Not served by GitHub Pages; the static site reads `web/public/data/`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/create-case | absent → open | binds an immutable published workflow version | slice |
| C02 | POST …/commands/submit-document | missing → submitted | synthetic placeholder hash only; new version row | slice |
| C03 | POST …/commands/reject-submission | submitted → changes_requested | reviewer reason required | slice |
| C04 | POST …/commands/resubmit-document | changes_requested → submitted | prior version preserved | slice |
| C05 | POST …/commands/unlock-dependent-step | blocked → ready | all mandatory prerequisites approved | slice |
| C06 | POST …/commands/approve-step | in_review → approved | reviewer role matches, not the assignee, no prior decision on this version | slice |
| C07 | POST …/commands/reassign-work | assigned → reassigned | closes the prior assignment interval | extension |
| C08 | POST …/commands/pause-sla | active → waiting_external | configured pause reason only | slice |
| C09 | POST …/commands/complete-case | open → complete | required steps approved and required documents accepted | slice |
| C10 | POST …/commands/migrate-workflow | old version → migrated | step mapping audited; accepted documents carried | extension |
| P | POST …/commands/publish-workflow-version | draft → published | no dependency cycle (Kahn) | slice |
| R | GET …/data/{entity} | reads with filters, limit ≤ 200, cursor | stable ordering | slice |
| M | GET …/metrics?from=&to=&cutoff=&group_by= | metrics over completed/open cases | half-open window on opened_at; cutoff for backlog | slice |
