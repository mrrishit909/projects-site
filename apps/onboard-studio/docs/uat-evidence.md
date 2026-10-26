# Onboard Studio: UAT evidence (P02-TEST-01..12) and the master-18 reviewer fixes

Run on 2026-10-26 against PostgreSQL 16 (`DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/onboard_studio`), Python 3.11,
local run (not the hosted runner). Status vocabulary: `verified (local)` = the named tests pass in this run;
`not_checked` = no test exercises it. Commands: `python -m pytest -q tests/test_adversarial.py tests/test_review_findings.py`.

## P02-TEST status
| Id | Rule attacked | Status | Where |
|---|---|---|---|
| P02-TEST-01 | complete with a required document missing or only rejected | verified (local) | `tests/test_adversarial.py::test_p02_test_01_*` (2 tests); latest-version rule added by Q-04 |
| P02-TEST-02 | two decisions on one step version | verified (local) | `test_p02_test_02_*` (2 tests) |
| P02-TEST-03 | pause outside a working interval contributes 0 business hours and is flagged | verified (local) | `test_p02_test_03_*` (2 tests) |
| P02-TEST-04 | a case binds only a published workflow version | verified (local), outside test_adversarial | `tests/test_api_commands.py::test_create_case_binds_only_a_published_version`, `tests/test_rules.py::test_case_bound_to_an_unpublished_version_is_rejected` |
| P02-TEST-05 | dependency cycle is refused (Kahn) | verified (local) | `test_p02_test_05_*` (2 tests) |
| P02-TEST-06 | resubmission keeps the prior version, documents are append-only | verified (local) | `test_p02_test_06_resubmission_preserves_the_prior_version` |
| P02-TEST-07 | reassignment closes the prior assignment | not_checked | C07 `reassign-work` answers 501 (extension milestone); the closed-interval data rule is exercised only through `test_p02_test_10_a_past_assignee_is_still_an_assignee` |
| P02-TEST-08 | a holiday on a weekend subtracts nothing | verified (local), outside test_adversarial | `tests/test_rules.py::test_holiday_on_a_weekend_subtracts_nothing`, `tests/test_sql_reference.py` (holiday cases) |
| P02-TEST-09 | customer waiting is not active time | verified (local) | `test_p02_test_09_customer_waiting_is_not_active_time` |
| P02-TEST-10 | self-approval, including a past assignee | verified (local) | `test_p02_test_10_*` (2 tests) |
| P02-TEST-11 | a completed case cannot be reopened; a correction is a linked case | verified (local) | `test_p02_test_11_*` (2 tests) |
| P02-TEST-12 | workflow migration carries accepted documents | not_checked | C10 `migrate-workflow` answers 501 (extension milestone) |

`tests/test_adversarial.py` holds 15 tests (including `test_atomicity_a_failed_command_leaves_no_trace`); all 15 pass.
`docs/requirements.md` still lists 04 and 08 as `not_checked (extension)`; the tests above exist and pass, so that row is conservative.

## Master-18 reviewer findings (verification-ledger entry "master 18 reviewer disproof pass (Onboard Studio)")
| Finding | Status | Regression test | Before, after |
|---|---|---|---|
| Q-01 completion before recorded work; pause bounds | fixed (D-07) | `test_q01_*` (8 tests), DB trigger `cases_completion_order` | A2: complete at 03-10 09:30 was 200 (calendar 33.25 h, paused 32.5 h, ingest rejected the rows); now 422 `COMPLETION_BEFORE_RECORDED_WORK`, the case stays open and the pause stays open; ingest accepts every API-produced row |
| Q-02 lock order, deadlock to 500 | fixed (D-08) | `test_q02_*` (3 tests) | 25 approve/reject races: 7 of 50 responses were 500 (9/25 in the review); now 0 of 50 |
| Q-03 SQL reference rounding and overlapping waits | fixed (D-09 note) | `test_q03_*` (5 tests) | tie fixture (150 cases, mean exactly 0.00005 h): `0.0000` now `0.0001`; overlapping waits 10-12 and 11-13: paused 4.0000 / active 4.0000, now 3.0000 / 5.0000 |
| Q-04 latest document version decides | fixed (D-06 amendment) | `test_q04_*` (4 tests), `web/scripts/review-check.ts` | v1 accepted + v2 rejected: case accepted and completeness 1.000000, now case rejected `MISSING_REQUIRED_DOCUMENT`, completeness 0.000000 (Python and TypeScript) |
| Q-05 calendar FK and empty calendar | fixed (D-09) | `test_q05_*` (5 tests), `review-check.ts` | unknown calendar was published; now 422 `CALENDAR_UNKNOWN` and an FK. Empty calendar: SLA "met" with 0 hours (Python) or case dropped silently (SQL/TS, no count); now unevaluated and counted in `sla_unevaluated_cases` in all three |
| Q-06 idempotency bound to actor, instant spelling | fixed (D-08) | `test_q06_*` (4 tests) | other actor with the same key replayed the result; now 409 `IDEMPOTENCY_KEY_REUSED`. `+00:00` vs `Z` was 409 payload mismatch; now an `Idempotent-Replay` of the same result |
| Q-07 sub-millisecond instants differ Python vs TypeScript | documented limitation | none (by decision) | sentence added to D-01 |

Totals of the last full run: `python -m pytest -q` 330 passed, 1 skipped; `tests/reference_check.py` ALL OK;
`web`: `npm run check` ALL OK (150 golden checks, 16 review checks), `npm run build:pages` ok, `npm run e2e` 35 passed.
