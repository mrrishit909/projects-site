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

---

# P04-ART-08: entry-journey UAT evidence (added by the artifacts pass, T-04-05)

The section above is the finding table of the review corrections and is unchanged. This section adds what P04-ART-08 requires on top of it: business scenarios with expected answers, the actual observations, the defect disposition, the route list, the screenshot names and the hosted run links.
Dataset `sf-20261026-20261026` (generator hash `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4`), code revision `43de7f8`. **Synthetic data.** Observed, simulated and hypothetical results are kept apart: scenarios UAT-01..UAT-09 are observed behaviour of a synthetic demo; UAT-06 quotes simulated estimates, labelled as such; nothing is a realised benefit.

**What this pass ran and did not run.** The pass ran the artifact commands listed in `release-package.md`. It did **not** re-run `npm run e2e`, `npm run check` or the hosted workflows: the browser results below are those recorded by the earlier run (`web/evidence/playwright-report.json`: started 2026-10-26T18:09:13Z, 70 expected, 0 unexpected, 0 flaky, 0 skipped, 104 s) and by the hosted runs named in section 4. "Actual observation" therefore states what each recorded test asserted and its recorded outcome.

## 1. Route list (the static site, base `/projects-site/labs/serviceflow/`)
| Route | Screen (P04-UI) | Built | Entry route | Screenshot names in `web/evidence/` |
|---|---|---|---|---|
| `/` | Start: honesty labels, manifest strip, the 6-step entry journey | yes | no | `home-360.png`, `home-768.png`, `home-1280.png`, `home-1920.png`, `home-zoom200.png` |
| `/overview/` | Operations overview (UI-01): the 28 contract metrics, P90 beside every mean | yes | yes | `overview-*.png` |
| `/queues/` | Queue explorer (UI-02) | **stub, no figures** | no | `queues-*.png` |
| `/tickets/` | Ticket timeline (UI-03): tickets as bars from arrival through waiting, service, pauses and resolution | yes | yes | `tickets-*.png` |
| `/staffing/` | Shift grid (UI-04): agents by hour with breaks and occupancy, the Santiago clock-change weekend | yes | yes | `staffing-*.png` |
| `/sla/` | SLA review (UI-05): compliance by priority, open overdue counted separately | yes | yes | `sla-*.png` |
| `/simulation/` | Simulation studio (UI-06): the golden case, the three published runs, 50 replications with intervals, seeded runs | yes | yes | `simulation-*.png` |
| `/compare/` | Scenario comparison (UI-07) | **stub, no figures** | no | `compare-*.png` |
| `/surveys/` | Survey analysis (UI-08) | **stub, no figures** | no | `surveys-*.png` |
| `/evidence/` | Evidence ledger (UI-09): the golden checks run live, CI and source links | yes | no | `evidence-*.png` |
| `/case-study/` | Case study (UI-10): what is built and not built, the 501 commands, the injected defects | yes | yes | `case-study-*.png` |

The `*` stands for the four widths and the zoom: `<route>-360.png`, `-768.png`, `-1280.png`, `-1920.png` and `<route>-zoom200.png` (a 640 css px viewport at device scale 2). Eleven routes x five = **55 screenshots**, written by `web/e2e/screens.spec.ts` during `npm run e2e` together with `web/evidence/index.json` (`count` 55; every shot records `scrollWidth <= innerWidth`, so no horizontal overflow at any of the five settings)
and `web/evidence/playwright-report.json`. `web/evidence/` is **git-ignored** (`web/.gitignore`): the images exist in the working tree that ran `npm run e2e` and in the `serviceflow-mode-b-<sha>` artifact uploaded by the hosted workflow (30-day retention); they are not in the repository, so they are not in `artifacts/CHECKSUMS.txt`.
Route names come from `web/src/routes.ts`; every route is also reachable by direct entry and reload on the nested base path (`journey.spec.ts`, "every route is reachable by direct entry and reload").

## 2. Business scenarios, expected answers, observations and disposition
The expected answers come from the independent sources (the golden fixture's hand calculation, `data/sql/reference_metrics.sql`, the Python domain, `web/public/reference/simulation-runs.json`), not from the page.

| ID | Scenario (as the operations analyst) | Expected answer | Actual observation (recorded run) | Disposition |
|---|---|---|---|---|
| UAT-01 | Open the landing page and read what the demo is | The badge reads "Synthetic data, demo mode"; the manifest strip shows the dataset version `sf-20261026-20261026`, the hash and `code_sha`; the footer says nothing is live; the decision question is shown; a back-link to the portfolio; six journey steps | `journey.spec.ts` "landing: honesty labels, the manifest strip, the back-link and the entry journey" passed | no defect |
| UAT-02 | Reproduce the known answer before any random arrival (Simulation studio) | waits 0.0000 / 10.0000 / 20.0000, mean 10.0000, last completion 30.0000, events `se-001..se-006`, four golden checks ok and none bad | `journey.spec.ts` "simulation: the golden case in the browser..." passed; the same figures equal in Python, SQL (`sql-analysis.md` section 09) and the workbook's `Golden case` sheet | no defect |
| UAT-03 | Read the overview for the whole window | 28 metric keys; arrivals 3,817, completions 3,608, mean first response 28.0046 with P90 44.1500 beside it, mean wait to first service 25.5073; the window toggle (full, training, holdout) and the group-by (queue is the FINAL queue) | `journey.spec.ts` "overview: 28 metric keys, window toggle, group_by and the tail beside the mean" and `review.spec.ts` passed; the figures equal `reference_metrics.sql` and the domain (`sql-analysis.md` section 10) | no defect (R4-10 wording fixed earlier) |
| UAT-04 | Inspect the shift grid across the Santiago clock-change weekend | the night crew's shift is 420 real minutes, agt-018's recorded 480-minute row is flagged (INJ-08); occupancy uses recorded breaks and says the published metric follows D-05 | `journey.spec.ts` "staffing: the shift grid on the daylight-saving weekend, 420 against 480 minutes" passed; query 04 shows the 420-minute row and query 08 finds the 480-minute crossing shift (1) | no defect |
| UAT-05 | Review SLA compliance by priority | first response 3,437 of 3,616 (0.950498), resolution 3,529 of 3,608 (0.978104); P1 187 of 227 each; open overdue shown apart (0); the page says resolution is measured from the original arrival and the holdout is a chosen realisation | `journey.spec.ts` "sla: compliance per priority, open overdue separately, P90 beside the mean" and `review.spec.ts` passed; `sql-analysis.md` section 03 reproduces every count | no defect (R4-09, R4-13 fixed earlier) |
| UAT-06 | Compare the baseline, plus one agent and the holdout intensity | `sim-001` 18.8435 +-8.2004, `sim-002` 7.9502 +-5.2231, `sim-003` 30.6253 +-8.3091 over 50 replications; paired difference -10.8932 +-3.4329; `sim-003` marked as not sharing the demand path; single-run means 14.6140 / 3.8776 / 33.6237; "Estimate from a seeded model" | `review.spec.ts` "simulation: 50 replications with 95 % intervals, the paired difference and the caveats" and `journey.spec.ts` passed; `data/simulation_reference.py --check` exit 0; the BI package recomputes the same means and intervals from the replication CSV | no defect (SIMULATED estimates) |
| UAT-07 | Open the evidence page | the golden checks run live and equal their expected values; CI and source links present; no CI result is claimed by the page | `journey.spec.ts` "evidence: live golden checks equal their expected values and the CI and source links are present" passed | no defect |
| UAT-08 | Read the case study | what is built and not built (C07 and C10 return 501), the recomputed technical P1 tail (142 tickets, P90 619.4167 against a mean of 247.1852), the injected defects, the review corrections | `journey.spec.ts` "case study: what is built and not built, the 501 commands, the recomputed tail and the injected defects" and `review.spec.ts` passed | no defect |
| UAT-09 | Use the site at a phone width, at 200 % zoom, after a reload | no horizontal overflow at 360, 768, 1280 and 1920 px or at 200 % zoom, no console errors, no broken asset on the nested base path | `screens.spec.ts` 55 tests passed (every shot `scrollWidth <= innerWidth`); `journey.spec.ts` route reload passed | no defect |
| UAT-10 | Open the stub routes (queues, compare, surveys) | each says plainly that it is a stub and shows no figure | `screens.spec.ts` waits on `[data-testid=stub]` for the three routes and passed | **deferred**: the screens are not built (P04-UI-02, 07, 08); the metrics they would show are in the API reads, the SQL investigations and this package |

## 3. Defect disposition
* **R4-01..R4-18** (independent review A-031): fixed at `43de7f8` with regression tests in Python, SQL and TypeScript; the finding table with before and after values is the first section of this file. The ledger entry of 2026-10-26T18:12:13Z records `reference_check.py` ALL OK, 377 passed, 303 golden and 54 review checks, 70 e2e.
* **Found while building the artifact package (none changes an application figure; (3) is a wording correction owed by other files):** (1) `manifest.json` `median_block_ratio` (0.4292) is the statistical median of the 124 ranked blocks, while `tests/test_generator.py` asserts against the upper middle; `sql-analysis.md` query 01 reproduces 0.4292; no number changes, the definition is now written down. (2) The manifest's next-best block ratio (0.9844) and `INJ-09` record count (318) are over the 3,826 published tickets and their own definition; the accepted-ticket figures are 0.9737 and 315 (listed as known differences in `sql-analysis.md` section 10, not as reconciled).
  (3) **A count in D-09 R4-14, in the public case study and in the first section of this file needs a date:** "four of the five technical agents on shift at the first training Monday bind also hold another queue's skill" holds only with skills counted as at the end of the data. On Monday 2026-07-06 10:00 UTC the five technical-skilled agents on shift are agt-001, agt-002, agt-005, agt-006 and agt-008 and **three** of them (agt-001, agt-002, agt-008) hold another queue's skill: agt-005's onboarding skill is effective only from 2026-08-03 (`agent_skills.effective_from`), so four of five hold one from that date (the reviewer's original "3 of the 5" was right for the first Monday). The 28.9 % share of handling minutes that went to other queues is unaffected (it is measured per interval with the skill effective at that instant, query 04) and the executive memo states both counts. `docs/contracts.md` and the public case study were not changed by this pass (outside its file ownership); the correction is recorded here and in the hand-back.
  (4) D-09 quotes "988 of 3,423 handling minutes" for the Monday-bind routing; the exact total is 3,422.15 (the reviewer summed rounded parts), the share 28.9 % is unchanged. (5) `data/seed.py` has no loader for `shift_breaks` (known, D-07); the analysis package loads the 1,018 rows itself. None of these needs a code change.
* **Open and deferred:** C07 and C10 return 501; queues, compare and surveys are stubs; the hosted CI and live-check runs for `43de7f8` / `e44d15d` are pending (manifest: "CI and live check pending").

## 4. Hosted evidence and links
| What | Result | Code | Link |
|---|---|---|---|
| CI: Mode A (reference check, domain, PostgreSQL, API) and Mode B (296 TypeScript golden checks, 65 Playwright tests at 360 / 768 / 1280 / 1920 and 200 % zoom, screenshots) | both jobs success, evidence artifact uploaded | `6a753e8` | https://github.com/mrrishit909/projects-site/actions/runs/40364940392 |
| Live check: 11 routes HTTP 200, manifest served, case study links to the site and the site links back, 360 / 1280 browser journey with no console errors | all jobs success (the deploy-wait matched `6a753e8` on attempt 2) | `6a753e8`, portfolio `e3bd4a4` | https://github.com/mrrishit909/projects-site/actions/runs/40367109366 |

Both runs predate the reviewer fixes (`43de7f8`, republished as `e44d15d`): their browser counts (296 golden, 65 Playwright) are the earlier ones; the current local counts are 303 golden, 54 review checks and 70 Playwright tests. The same live-check run covers the other labs as well (a matrix). Do not read these links as verification of `e44d15d`.

## 5. Public case study cross-check
The figures of `/serviceflow/project.json` (the public case study) were compared with the stored analysis results by `tests/test_artifacts.py`: 3,817 accepted tickets and 3,608 completions; mean wait to first service 25.5, mean first response 28.0 with a P90 of 44.2, mean resolution 164.6; first-response compliance 95.0 % overall and 82.4 % for P1 (187 of 227); resolution compliance 97.8 % with 54 of the 79 misses reopened; occupancy 0.42 over 447,450 staffed minutes; abandonment 11.8 % (201 before any service, 8 after service began); surveys invited on 59.5 % of completions, answered by 34.9 %, CSAT 0.864;
the simulation means and intervals 18.8 +-8.2, 8.0 +-5.2, 30.6 +-8.3 and the paired -10.9 +-3.4; the dedicated-server share 28.9 %. All agree with the stored results. The case study's "8 after a transfer while mid-service" is confirmed: all 8 abandonments after a service had begun belong to transferred tickets (`of_which_transferred` in query 06).
