# Onboard Studio — requirements and traceability (P02-ART-02)

Status values: verified | failed | blocked | not_checked. The verification ledger
(`docs/program/verification-ledger.json`) is the machine-readable record.

## User stories
1. As an analyst I open a case timeline and see its events, assignments, waiting intervals
   and document versions on a business-hours axis with calendar gaps shaded. *Accept:* the
   timeline's business and active hours equal `compute_metrics` for that case (golden: 2 h
   and 1 h).
2. As a team lead I compare workflow v1 and v2 on active elapsed time, handoffs and SLA
   attainment for the same window. *Accept:* figures equal `group_metrics` by
   workflow_version.
3. As a reviewer I cannot approve a step I am assigned to. *Accept:* 403 `SELF_APPROVAL`
   on the backend; the browser simulation shows the same message.
4. As a case owner I cannot complete a case with a required document missing. *Accept:*
   422 `MISSING_REQUIRED_DOCUMENT`.
5. As a reviewer I export the SLA explorer and the file carries the calendar id, pause
   policy version, window and dataset hash. *Accept:* header fields present.

## Traceability
| Requirement | Code | Test | Evidence | Status |
|---|---|---|---|---|
| P02-GOLD-01..10 | tests/fixtures/golden/* | tests/reference_check.py | CI Mode A | verified (local) |
| P02-MET-01..11 | domain/onboard_studio/metrics.py, data/sql/reference_metrics.sql | tests/test_golden_domain.py, test_sql_reference.py | CI Mode A | verified (local, 256 tests) |
| P02-FLOW-01..06, 08, 09 | api/commands.py | tests/test_api_commands.py | CI Mode A | verified (local) |
| P02-FLOW-07, 10 | api/commands.py (501) | tests/test_api_commands.py | — | blocked: extension |
| P02-TEST-01,02,03,05,06,09,10,11 | tests/test_adversarial.py | same | CI Mode A | verified (local) |
| P02-TEST-04,07,08,12 | — | — | — | not_checked (extension) |
| P02-UI-03/04/06/10 | web/src/views/* | web/e2e/* | CI Mode B | not_checked |
| P02-REL-* | .github/workflows/onboard-studio-ci.yml, live-check.yml | release-manifest.json | Actions | not_checked |
