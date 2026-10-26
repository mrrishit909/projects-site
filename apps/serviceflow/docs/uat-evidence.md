# ServiceFlow — UAT evidence for the review corrections (A-031 -> T-04-07)

Branch `business-data-lab`, directory `apps/serviceflow/`. Decisions are in `docs/contracts.md` D-09; this file is the finding table
with before/after values and the commands that produced them. Nothing here is committed or pushed by the fix specialist.
"Before" values are the reviewer's (their harness, cases in `review04/cases`, outputs in `review04/cases_run.txt`) unless
marked "re-run". "After" values were produced by the commands in the last section.

Harness: `harness.py case.json hand.json` runs hand / Python / SQL (scratch database `review04_sf`) / TypeScript on one case.

| Finding | Before | After | Test (Python / SQL / TypeScript) |
|---|---|---|---|
| R4-01 SQL staffed time with no overlapping shift | c09: SQL `staffed_available_minutes` 10080.0000, `agent_occupancy` 0.027778; Python and TS 0.0000 and null. Also snapshot window 2026-07-05 00:00-01:00Z | SQL 0.0000 and null, equal to Python and TS (c09, and the four snapshot windows incl. `no_shift_hour`, `snap_sql.py`: no disagreement) | `test_R4_01_*` (domain), `test_R4_01_sql_*` x2, review-check "R4-01" |
| R4-02 concurrency fixed point | c08: hand `arrival_count` 3; Python, TS, SQL 2 (t-C stayed rejected after t-A was rejected) | 3 in all four; rejected tickets t-2, t-A only. Snapshot: 70 rejections, `expected_rejections` 70 of 70 met, no SERVICE_OUTSIDE_SHIFT / RESUME_BEFORE_SERVICE | `test_R4_02_*` x3, `test_R4_02_sql_*`, review-check "R4-02" |
| R4-03a `resume-work` availability | resume off shift or inside a break accepted (api_attack C1, C3) | 422 `AGENT_NOT_IN_SHIFT` / `AGENT_ON_BREAK`; a resume at the break's end (130) is 200. api_attack C3 now 422; C1 in the reviewer's script is 409 `INVALID_STATE` (t-1 is in service there, not paused): the paused case is the regression test | `test_R4_03_resume_work_*` x2 |
| R4-03b availability at ingest | c16: service 17:20 with the shift ending 17:00 accepted; handling 60.0000 | ticket rejected `SERVICE_OUTSIDE_SHIFT`, its events `TICKET_REJECTED`; handling 0.0000 in all four. Shift is half-open (start 479 ok, 480 rejected). Snapshot: 0 intervals outside a shift (4,976 intervals), accepted population unchanged. Breaks: flagged (`SERVICE_DURING_BREAK`), not rejected; 0 in the snapshot | `test_R4_03_*` x6, `test_R4_03_R4_16_sql_*`, review-check "R4-03" |
| R4-04 analyst changes state through C01 | api_attack I1: 200, t-1 resolved by an analyst | 403 `ROLE_FORBIDDEN`, nothing written (events 3 -> 3, no `command_results`); analyst ingest of new tickets 200; supervisor and admin 200 | `test_R4_04_*` x4 |
| R4-05 `dataset_version` | accepted unchecked and unhashed (B1, A4: 200) | stale version 409 `STALE_DATASET_VERSION` (`context.current`, `context.requested`), nothing written; same key and body with another version 409 `IDEMPOTENCY_KEY_REUSED`; no `dataset_versions` row: accepted. No migration 0003 (table and seeded row exist) | `test_R4_05_*` x3 |
| R4-15 same-instant reopen and resolve | c14: SQL `completion_count` 0, `resolution_minutes` {}; Python and TS 1 | SQL 1, `resolution_minutes` {t-1: 30.0000}, equal in all four; the reverse order (resolved, then reopened) is 0 in all four | `test_R4_15_*` x2, `test_R4_15_sql_*` x2, review-check "R4-15" |
| R4-16 `resumed` before `service_started` | c15: accepted; `first_service_at` unset in Python and TS (`wait_minutes` {}), SQL 10.0000 | ticket rejected `RESUME_BEFORE_SERVICE`; no wait in any of the four (the hand value 10.0000 assumed acceptance) | `test_R4_16_*` x2, review-check "R4-16" |
| R4-17 parsing | c17: Python rejects `break_minutes` 30.0, TS accepts (staffed 180 vs 360); c18: Python accepts `09:20Z`, TS rejects (completions 1 vs 0); seed range 2^62 vs 2^53 | one rule in both: seconds required, an integer field takes an integral number (`30` and `30.0`; `30.5` refused), seeds within +-(2^53 - 1). c17 and c18 agree in all four. Deviation: floats are accepted when integral, not refused (JS cannot tell `30.0` from `30`) | `test_R4_17_*` x3, review-check "R4-17" |
| R4-18 calendars and the window edge | calendars ignored silently; c11 backlog 1 (hand 2) undocumented | `SLA_CALENDAR_IGNORED` per non-`cal-001` policy (pipeline `warnings`, metrics read `warnings`, SLA page); the edge is documented in D-09 and warned (`CUTOFF_AT_OR_AFTER_WINDOW_END`) when the cutoff is not before the window end and counts something there. The cutoff semantics are unchanged (golden): c11 backlog stays 1 in all four, the hand value 2 is a different reading | `test_R4_18_*` x4, review-check "R4-18" |
| R4-09 reopen basis | `reopened_tickets` over arrivals only; a ticket that arrived before the window and was reopened and completed inside it (the c06 shape) counted 0 | over arrivals and completions (counted once): 1; `reopened_among_completions` 1; the SLA and overview pages state that resolution compliance is measured from the original arrival and a reopened ticket is charged its dormant gap | `test_R4_09_*`, review-check "R4-09", e2e `review.spec.ts` |
| R4-10 wait wording, `group_by=queue` | "wait", "wait for service" | "wait to first service" on the overview, tickets table, definitions, README, contracts; `group_by=queue` is the final queue (`data.group_basis`, overview note) | `test_R4_10_*`, e2e |
| R4-11 replications | single replications only | 50 replications per run (seeds seed + r) with 95 % intervals, and the paired difference: see below | `test_R4_11_*` x2, golden-check x7, review-check "R4-11", e2e |
| R4-12 D-07 sentence | "447,450 vs 447,990" as adjacent windows exceeding the whole | corrected: 447,450 = full window `staffed_available_minutes`, 447,990 = `staffed_shift_minutes_whole`; training 297,870 + holdout 149,640 = 447,510 against 447,450 | `test_R4_12_*`, review-check "R4-12" |
| R4-13 chosen realisation | attempt index and discarded ratios only in the reviewer's script | `manifest.json` `generator.parameters.arrival_realisation`: attempt 7 (+20.10 %), discarded +12.86, +14.58, +22.82, +16.92, +12.69, +22.02, +30.46 %; noise sd 4.3 points; `dataset_hash` unchanged `944ef91b...cba4`; thirteen entity files and the golden directory byte-identical; labelled on the case-study, overview and SLA pages | `test_R4_13_*`, review-check "R4-13", e2e |
| R4-14 censored wording | "reported as censored, not dropped" | "excluded from the wait statistics and counted separately" (page and definition); censored totals are in the replication table (57 / 16 / 129 over 50 replications of sim-001 / sim-002 / sim-003) | review-check "R4-14", e2e |

## R4-11 numbers (50 replications, seeds 20261026 + r, warm-up 120, horizon 720; Python reference = TypeScript, all strings equal)

| Run | Mean of replication means (min) | 95 % half-width (min) | Censored tickets, all replications |
|---|---|---|---|
| sim-001 baseline | 18.8435 | 8.2004 | 57 |
| sim-002 plus one agent | 7.9502 | 5.2231 | 16 |
| sim-003 holdout intensity | 30.6253 | 8.3091 | 129 |
| sim-002 minus sim-001, paired on the same seeds | -10.8932 | 3.4329 | same demand path in every pair: yes |
| sim-003 against sim-001 (not a policy comparison) | +11.7818 | 5.9968 | same demand path: **no**, by design |

One published run is one draw: the single-replication means the page showed before (sim-001 14.6140, sim-002 3.8776, sim-003
33.6237) are the first of these fifty. Student-t: the table now runs to 50 degrees of freedom (2.010 at 49) and uses 2.000
beyond; it used 1.96 above 30, 2.5 % too narrow at 50 replications.

**Dedicated-server simplification (measured here, `review04/mon10.py`).** On Monday 2026-07-06 10:00Z the technical agents on shift
are agt-001, agt-002, agt-005, agt-006 and agt-008. Four of the five (all but agt-006) also hold another queue's skill (billing for
agt-001, agt-002, agt-008; onboarding for agt-005). Of 3,423 handling minutes started in the Monday 09:00-11:00 bind of the training
weeks by technical-skilled agents, 988 (28.9 %) went to billing (951) or onboarding (37) tickets. The reviewer's brief said "3 of
the 5"; the count above is four of five holding another skill (the page says four of the five and about 29 %).

## Reviewer harness after the fixes (hand / Python / SQL / TypeScript)

Python, SQL and TypeScript agree on every one of the 20 cases (`harness.py case ../empty.hand.json -q`: `DISAGREEMENTS: 0` x 20).
Against the reviewer's hand values: c08, c09, c14, c17, c18 agree with the hand values too (0 disagreements). c03, c06, c15, c16 differ
from their hand values only because the hand values assume the off-shift or resume-first service was accepted, which D-09
rejects: c03 (t-2 serves from 08:40, shift opens 09:00) and c06 (t-1 serves outside the shift) lose that ticket, c15 has no wait,
c16 has no handling. c11 differs only on the documented cutoff edge (hand backlog 2, all four 1).

## Commands and results (from `apps/serviceflow`, 2026-10-26)

| Command | Exit | Result |
|---|---|---|
| `../../.venv/bin/python tests/reference_check.py` | 0 | `ALL OK` (golden fixtures, hashes unchanged) |
| `DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/serviceflow ../../.venv/bin/python -m pytest -q` | 0 | 377 passed (333 before: +38 in `test_review_findings.py`, +6 in `test_sql_reference.py`) |
| `DATABASE_URL=... ../../.venv/bin/python -m pytest -q tests/test_review_findings.py tests/test_sql_reference.py` against the code at HEAD (copy of `git archive HEAD`) | 1 | 31 failed, 23 passed: the new tests fail without the fixes |
| `cd web && npm run check` (typecheck, golden, review) | 0 | `ALL OK (303 checks)` (was 296; +7 for replications), `REVIEW OK (54 checks)` |
| `npm run build:pages` | 0 | 11 route copies written |
| `npm run e2e` | 0 | 70 passed (65 before + 5 in `e2e/review.spec.ts`) |
| `../../.venv/bin/python data/generate.py --out <tmp> --data-dir <tmp>` | 0 | the 13 entity files, `injection-manifest.json` and `web/public/data/golden/` byte-identical to the committed ones; `manifest.json` differs by `generated_at` only; `data/injection-events.json` changes EV-01's actor (supervisor, R4-04) |
| `../../.venv/bin/python data/simulation_reference.py --check` | 0 | the reference file equals the Python simulator |
| `review04/api_attack_current_version.py` (the reviewer's `api_attack.py` with the current dataset version, in the session scratchpad) | 0 | A4 409 `IDEMPOTENCY_KEY_REUSED`, B1 409 `STALE_DATASET_VERSION`, C3 422, I1 403 `ROLE_FORBIDDEN`, G rows unchanged (403 `ROLE_FORBIDDEN` for an analyst on every state command), F concurrent start: one 200 and two 422 in each of 5 trials |

The unchanged `api_attack.py` now answers 409 `STALE_DATASET_VERSION` to every command because it sends `ds-test` to a database
whose version is `ds-...`: that is finding R4-05 working.
