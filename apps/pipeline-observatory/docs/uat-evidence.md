# Pipeline Observatory: UAT evidence (P08-ART-08)

Created by this pass: `docs/uat-evidence.md` did not exist before it (there is no earlier review text to preserve; had there been one, this file would be append-only). It records business scenarios with expected answers, actual observations and defect disposition for the **entry journey** (P08-GOAL-09: one source-to-decision journey on the reference fixture, then the snapshot), the findings of review R8, the routes, the screenshot names that `npm run e2e` writes and the hosted run links.
The decision it supports: **is this dataset safe, complete and fresh enough to publish?**
**Synthetic data only** (dataset `po-20261026-20261026`, generator hash `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`, contract v1, code revision `ed7eb5a`, published as `b326690`). Observed results, constructed (designed) relationships and hypothetical benefits are kept apart: everything below is OBSERVED in a synthetic world or on the fixture; nothing is a measured effect on a real platform; the five designed relationships and twelve injected defects are constructed by the generator; no benefit is claimed.
**How to read it without installing anything:** the provenance table first, then the routes and screenshots, then the scenarios (expected answer, actual observation, disposition), the review findings and the defect disposition; every figure is quoted from `sql-analysis.md` and carries its scope (complete world, 2,000-row sample, recorded).

## Provenance of each observation (what was run, and by whom)
| Source | What it is | Run by |
|---|---|---|
| Release manifest `publication_status` (`docs/program/release-manifest.json`) | CI **40468689563** green in both modes on `b326690` (Mode A: reference check, pytest with `postgres:16`; Mode B: site check and e2e) | GitHub-hosted runner, copied from the ledger, **not fetched** by this pass |
| Verification ledger, live check run **40469671918** | success for all ten sites; `pipeline-observatory` live code sha `b326690a791ca440e6c616dea361383cb8f7e665`, verified 2026-10-27T07:53:13Z, release commit `d58209f` | GitHub-hosted runner, copied, not fetched |
| Delegation ledger A-076 (accepted) | the coordinator re-ran `tests/reference_check.py` (ALL OK, 742 checks, 7 fixture hashes verified), the generator under `PYTHONHASHSEED=13` (byte-identical, 4,863,396 bytes), `pytest` with the database and the sandbox variable (**529 passed, no skips, about 9 minutes**), `npm run check` (1,180 golden checks plus 255 review checks over 51 worlds), `build:pages` and `npm run e2e` from clean on a private port (**90 passed**) | the coordinator, recorded in the ledger |
| Earlier CI runs in the verification ledger | **40442468507** (Mode A on `3f3fc11`, 381 tests), **40449388766** (Mode A on `97188de`, 422 tests incl. 41 generator tests), **40455458608** (web, both modes), live check **40456053215** for the first publication (`83b6a60`, source `a2ef4f4`), **40464667890** (workflow provisioning commit `7a748ac`, both modes green, no artifact tests yet) | GitHub-hosted runners, copied |
| The local `web/evidence/playwright-report.json` | 90 expected, 0 unexpected, 0 flaky, 0 skipped; started 2026-10-27T07:38:28Z, 155.3 s; 15 journey tests and 75 screen tests (75 screenshots plus `index.json`) | recorded by the fix worker; this pass **read** the report and the file list (`web/evidence/` is not tracked by git) and did **not** run `npm run e2e` |
| `tests/reference_check.py`, `data/sql/analysis/run_all.py` (golden and snapshot reconciliation), `build_workbook.py --recalc`, `pytest` | the golden figures and the snapshot figures re-observed independently of the browser | this pass; results in the last section and in `release-package.md` |

**The republish after the R8 fixes was pending when this pass was dispatched** (assignment A-080 was dispatched at 2026-10-27T07:51:33Z, the same instant the release was recorded as published); the ledger then recorded the live check at 07:53:13Z (run 40469671918, success). Those ids are copied from the committed ledgers and were **not fetched** by this pass.

## Routes (base `/projects-site/labs/pipeline-observatory/`; live site https://mrrishit909.github.io/projects-site/labs/pipeline-observatory/, not fetched by this pass)
| Route | Screen | Entry route (`web/src/routes.ts`) | What it shows (read from the route table and the recorded tests) |
|---|---|---|---|
| `/` | landing (the decision, the verdict) | no | the honesty labels (synthetic, static snapshot, simulations), the manifest strip, the printed verdict rule |
| `/overview/` | platform overview (P08-UI-01) | **yes** | freshness beside ingestion age, independent of job colour; the silent source hatched; the run funnel |
| `/dag/` | dependency graph (P08-UI-02) | **yes** | sources, models and the publication with freshness drawn on every node; keyboard isolation of a node |
| `/runs/` | run detail (P08-UI-03) | **yes** | steps, attempts, quality results and logs of one run; the golden batch and its replay |
| `/sources/` | source contract (P08-UI-04) | no | schema, version comparison and the checkpoint of each source |
| `/quarantine/` | quarantine desk (P08-UI-05) | **yes** | invalid rows and their retry disposition, simulated in browser memory |
| `/gate/` | quality gate (P08-UI-06) | **yes** | critical checks and the decision; a failed run never replaces the publication; fault injection simulated |
| `/backfill/` | backfill console (P08-UI-07) | no | partitions, overlaps and progress; requests simulated in browser memory |
| `/incidents/` | incident timeline (P08-UI-08) | no | detection, diagnosis and verified recovery |
| `/benchmark/` | benchmark evidence (P08-UI-09) | no | measured hardware, size and duration, with what each number can and cannot say |
| `/evidence/` | evidence | no | hashes recomputed in the browser, designed relationships, injected defects, scope tags |
| `/case-study/` | case study (P08-UI-10) | **yes** | delivery guarantees and failure experiments |

## Screenshot names (`npm run e2e`, `web/e2e/screens.spec.ts`, written to `web/evidence/`, not tracked by git; CI uploads them as the evidence artifact)
`<view>-<width>.png` at 360, 768, 1280 and 1920 CSS pixels and `<view>-zoom200.png` at 640 CSS pixels with device scale 2 (200% zoom), for fifteen views: `home`, `overview`, `dag`, `dag-isolated`, `runs`, `sources`, `quarantine`, `gate`, `backfill`, `incidents`, `benchmark`, `evidence`, `case-study`, `golden-runs`, `golden-gate`: **75 files**, plus `index.json` (route, width, scroll width, inner width, device scale per shot) and `playwright-report.json`. In the recorded report every screen test passed, which includes `scrollWidth <= innerWidth` (no horizontal overflow at any of the five settings) and an empty browser console.

## Business scenarios: expected answer, actual observation, disposition
Expected answers come from the hand calculation (`tests/fixtures/golden/CALCULATION.md`) or from the independent reference (`data/sql/reference_metrics.sql`, the Python domain, the manifest's record); "actual" is what was observed in the named run. "SQL nn" is an investigation of `sql-analysis.md`.

| # | Scenario (the decision it supports) | Expected answer | Actual observation | Disposition |
|---|---|---|---|---|
| S1 | **Known answer.** Ten rows arrive (is a replay or a crash able to create a ninth record?) | 10 received, 8 accepted, 1 duplicate, 1 quarantined (0.100000 each); the replay leaves 8; the crash leaves 8 and version 2; freshness 52,200 s against an ingestion age of 42,900 s; completeness 8 of 9; task success 1.000000 against attempt success 0.800000; pub-001, pub-001, pub-003; residual 0.00; 475.0000 minutes; coverage 0.666667; 0.666667 records/s | Browser (e2e "golden case, recomputed in the browser ...", recorded as passed): the same figures; `tests/reference_check.py` ALL OK (742 checks, re-run in this pass); SQL 09 and the reference SQL on the golden database equal `expected.json` on every key (family A of the reconciliation, 38 rows) | passed, no defect. The golden crash case is vacuous by itself (every key of the crashed batch is already known): the backend test crashes a batch with a new key (D-09 R8-16) |
| S2 | **Is the latest run safe to publish?** | latest gate allowed; pointer on the latest publication | `run-1343` allowed; pointer `pub-1343`; 0 publications of failed or blocked runs (SQL 05, complete world); e2e "landing" shows the verdict | passed |
| S3 | **Does a green job hide a stale source?** | `src-refunds` stale while its 72 runs are green | freshness 262,378 s (recorded) against an ingestion age of 17,363 s (complete world); 72 of 72 runs succeeded, allowed, freshness check passed (SQL 04, equals DR-01 of the manifest); e2e "overview: ... the silent source is hatched while its jobs are green" passed | passed; the declared 7-day target is the cause and the overview says so |
| S4 | **Does a failed run replace the publication?** | a blocked run leaves the pointer; incident closes on a verified recovery | `run-1187` blocked on `relationships_intact` (1 of 206), pointer stays `pub-1186`, `inc-022` recovered by `run-1188` after 67.8833 minutes (SQL 05, 06; equals DR-02); all 25 runs that failed left the pointer; e2e "runs" and "gate" passed | passed |
| S5 | **Is every received row accounted for?** | received = accepted + duplicate + quarantined + deleted; the schema-quarantined batch apart | 39,901 = 37,248 + 2,101 + 429 + 123 (0 unclassified); rejection rate 0.010752, duplicate rate 0.052655; the 17 rows of `b-0847` in no rate (SQL 01, complete world) | passed (wording fixed by D-09 R8-10) |
| S6 | **Does a crash double-count?** | replay accepts each key once | 8 of 8 crashed batches replayed from the same cursor with version step 1; 273 rows written and classified once (SQL 01 `crash_replay`; INJ-01 `b-0596`: 71 rows, replay `b-0597` accepted 69) | passed |
| S7 | **Do retries honour retry-after?** | no retry sooner than the hint | 49 rate-limited responses (all `src-shipments`), 49 retries, 0 too soon, slack 0 to 25 s (SQL 08; equals DR-03) | passed |
| S8 | **Can a loop be told from a re-poll?** | the loop stops the fetch; a refetch does not | 1 `cursor_loop` row (fetch 577, `src-web-events:47`, no batch created) and 48 `refetch` rows, none repeating a cursor inside its session (SQL 08; INJ-10) | passed (this was review finding R8-06) |
| S9 | **Are late events lost?** | counted and included next time | **recorded** 757 (707 backfill, 41 corrections, 9 designed), 0 lost; **sample** 141 (reference SQL = domain); the two are never mixed | passed, scope labelled |
| S10 | **Does the published total reconcile?** | residual 0.00 with its parts | 1,318 of 1,318 publications at 0.00 (recorded); the one blocked candidate `run-0731` recomputed from its parts: 23,694.91 - 22,698.71 - 1,137.66 = -141.46 (SQL 06) | passed |
| S11 | **How long is recovery?** | verified recovery minus detection | 25 of 25 verified; mean 60.6827, from 50.7500 to 72.4000 minutes (SQL 06) | passed |
| S12 | **Is backfill coverage honest?** | 11 of 15 partitions; the refusals beside it | 0.733333 over 13 accepted requests; bf-006 and bf-012 refused (4 partitions) while bf-004 and bf-010 were running (SQL 07) | passed (wording fixed by R8-11) |
| S13 | **Does the sample mislead?** | each figure says what it is a number of | the sample's duplicate rate 0.012247 against the pipeline's 0.052655; accepted overstated by 53; 0 of 1,318 content hashes verifiable (SQL 10); the site tags every figure | passed, scope tags verified by e2e "D-09 wording" |
| S14 | **Honesty.** Is it clear nothing is live and nothing is published from the browser? | synthetic label; simulations labelled | e2e landing, quarantine, gate and backfill tests passed; screens at four widths and 200% zoom with no overflow and no console errors (recorded) | passed |
| S15 | **Who may do what?** | identity is header-asserted; the sandbox is off by default | stated on README, `contracts.md` D-09 R8-13/R8-14 and the evidence page; `tests/test_api_protocol.py`, `test_review_fixes.py::test_the_sandbox_is_only_the_exact_word` | passed |

## Review R8: findings, before and after
Review A-073 (independent, briefed to disprove the site and its case study) confirmed eight defects and eight documentation findings; they were fixed in `ed7eb5a` (A-076) with the decisions of `docs/contracts.md` D-09. "Before" is the reviewer's finding as recorded in the ledger; "after" is the regression test in this tree.
| Finding | Before | After | Test |
|---|---|---|---|
| R8-01 future events | one future-dated event made freshness negative and kept the gate green | `EVENT_IN_FUTURE`; freshness never negative (null with a reason) | `test_review_fixes.py::test_a_future_dated_row_is_quarantined_and_cannot_mask_a_stale_source`, `::test_freshness_is_null_with_a_reason_when_no_accepted_event_exists_never_negative` |
| R8-02 omission | a publication could omit committed batches, so a late event could be lost while the gate allowed it | critical checks `scope_complete` and `late_events_included`; `WATERMARK_REGRESSION` | `::test_a_publication_that_omits_a_committed_batch_is_blocked_by_scope_complete`, `::test_a_late_event_that_no_publication_includes_is_blocked_by_late_events_included`, `::test_a_watermark_never_goes_back` |
| R8-03 repeated id | a repeated `batch_id` silently sent a source's accepted count to zero | `DUPLICATE_ID` at import | `test_domain_rules.py::test_r8_03_*` |
| R8-04 patterns | Python, SQL and TypeScript classified Unicode digits and trailing newlines differently | one ASCII pattern set, full match; `3.0` and integers above 2^53 are `INVALID_FIELD` | `tests/test_divergence.py` (44 cases), `test_review_fixes.py::test_unicode_digits_and_a_trailing_newline_are_not_money_through_the_api` |
| R8-05 dates and fractions | the SQL reference crashed on an impossible date and rounded sub-microsecond fractions | date validation and truncation in SQL | `tests/test_divergence.py` |
| R8-06 fetch sessions | a re-fetch of a cursor was refused as a loop by the application while the world relied on it; no loop was detected without a session | `fetch_session` required; a loop is a repeated cursor inside one session; a new session is a refetch | `test_review_fixes.py::test_a_to_b_to_a_is_a_loop_inside_one_session_and_a_refetch_across_sessions`, `::test_judge_fetch_is_the_one_pure_rule`; SQL 08 |
| R8-07 funnel | "25 blocked" was false: 10 were blocked at the gate, 15 failed before it | the funnel is computed and stated everywhere | `test_generator.py` funnel check; SQL 02 |
| R8-08 payload guard | the TypeScript mirror did not reproduce the non-object payload crash it claimed to | `INVALID_FIELD` in both implementations | `test_domain_rules.py::test_a_payload_that_is_not_an_object_is_quarantined_and_the_pipeline_does_not_crash` |
| R8-09..R8-16 documentation | scope tags, quarantine scope, backfill coverage wording, sandbox default, header-asserted identity, units, case-study wording | fixed in the site, the case study and D-09 | `web/e2e/journey.spec.ts` "D-09 wording ..." |
The world was regenerated under the new gate checks (9,296 quality results instead of 6,640; the dataset hash moved from `d9f0aa18...` to `0a906877...`; the two refused backfills were re-timed to overlap requests that were running).

## Defect disposition
| Defect or gap | Where found | Disposition |
|---|---|---|
| R8-01 .. R8-08 (future events, omission, repeated ids, patterns, dates, fetch sessions, funnel, payload guard) | independent review A-073 | **fixed** at `ed7eb5a`, held by regression tests in Python, SQL and TypeScript (table above) |
| R8-09 .. R8-16 (documentation) | the same review | **fixed** (D-09) or case-study wording fixed live by the coordinator (portfolio `3558f84`) |
| The reference SQL does not model delete events | `contracts.md` D-06; this pass's reconciliation | **known gap, reconciled exactly**: on the sample it differs from the domain by the ten `op` rows and by nothing else (`sql-analysis.md` section 11) |
| The domain labels 25 runs `blocked` in `pointer_history` | this pass's reconciliation (family B) | **observed, not a defect of the product**: a run with no critical result is not allowed; the funnel separates the 10 from the 15 |
| `completeness_vs_expectation` fails in 1,304 of 1,328 gates | SQL 02 | **observed**: a warning with little signal, stated on the gate page (D-09 R8-16) |
| `src-refunds` target (7 days) looser than its silence | SQL 04 | **constructed on purpose** (DR-01); recommendation in `executive-memo.md` |
| The public case study says "529 Python tests" | `release-package.md` | **will read N after this package's `tests/test_artifacts.py` lands**; reported to the coordinator, the file belongs to `unified-portfolio` and was not touched |
| No hosted run of `tests/test_artifacts.py` yet; Excel and Power BI not run | this package | **open**: the workflow provisions LibreOffice and the scratch databases; the workbook was recalculated by LibreOffice only and no `.pbix` exists |

## Commands and results (from `apps/pipeline-observatory`, 2026-10-27, scratch databases `artifacts08_*` only)
See `release-package.md` ("What this artifact pass ran") for the exact commands and their last lines.
