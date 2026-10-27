# ProductSignal — UAT evidence for the review corrections (A-051 -> A-053/A-054, T-06-07)

Branch `business-data-lab`, directory `apps/productsignal/`. Decisions are in `docs/contracts.md` D-10; this file is the finding table
with before and after values and the commands that produced them. Nothing here is committed or pushed. "Before" values are the
reviewer's findings as briefed (harness, cases and API scripts in `review06/`; not re-run against the old code here); "After" values come from the commands in the last
section. Golden fixtures (`tests/fixtures/*`) are untouched and every published metric key is unchanged.

Harness: `harness.py case.json` runs hand / Python / SQL (scratch database `review06_a`) / TypeScript on one case; `api1..api4.py`
drive the API (scratch database `review06_b`).

| Finding | Before | After | Tests (Python / SQL / TypeScript / e2e) |
|---|---|---|---|
| R6-01 `conclusive` ignores `plan_frozen` | I_frozen_late: plan frozen after the first run read outcomes, `plan_frozen` false, `conclusive` true (+30.00 pp, 10/100 vs 40/100). L_equal: 0/2 vs 2/2, no logged run, `conclusive` true | `conclusive` = interval excludes 0 AND final AND hash valid AND `plan_frozen` AND SRM OK: false for I and L in Python, SQL, TypeScript and `reference_check.py`; the same data with the plan frozen first is true; no logged run is a preview (false) | `test_R6_01_*` x2, `test_the_sql_reference_equals_the_domain_on_the_review_cases`, review-check "R6-01", e2e verdict text |
| R6-02 SRM df always 1 with three arms | H_three (100/33/67 vs 0.5/0.25/0.25) accepted, p from df 1 (0.000674; df 2 would be 0.003088) | `VARIANTS_NOT_TWO` (422) in `parse_plan` (Python, TypeScript), C06 (api2 12a: 422) and the seed; the harness gives one identical rejection from all four layers | `test_R6_02_*` x3, review-check "R6-02" |
| R6-03 SQL depends on session TimeZone | K_dst_sql and B_maturity: the SQL reference gave different answers under a non-UTC session TimeZone (a `days` interval follows the zone's calendar across a DST change) | hour-based intervals (`hours => 24 * n`); K, B, C and F give 0 disagreements under America/New_York, Europe/London, Pacific/Kiritimati (tzrun.py) and the pytest cases run under all of them | `test_R6_03_*` x2 (SQL) |
| R6-04 cutoff in the future accepted | C07, C08 and GET /metrics at a cutoff after the clock: 200, run `created_at` before `cutoff_at` (api1 2a, 7; api2 13a) | 422 `CUTOFF_IN_FUTURE` on all three (api1 2a, 7; api2 13a), nothing written; the clock's own second is accepted; `created_at >= cutoff_at` for every run | `test_R6_04_*` |
| R6-05 client-controlled fact instants | `assigned_at`, `exposed_at`, `decided_at` taken from the client; event dated in the future accepted; `received_at` before `event_at`; assignment dated before a published run changed it (api2 11a-11e, api3 B/C, api4 F/H) | all three stamped with the API clock; stated instants need admin plus `backfill: true` (403 `BACKFILL_ADMIN_ONLY`, 422 `BACKFILL_FLAG_REQUIRED`, 422 `*_IN_FUTURE`), audited; `EVENT_IN_FUTURE`, `RECEIVED_BEFORE_EVENT`; `ASSIGNMENT_BEFORE_PUBLISHED_RUN` / `EXPOSURE_BEFORE_PUBLISHED_RUN`; `DECIDED_BEFORE_RUN`; a second C08 at the same cutoff returns the same figures (api2 11f) | `test_R6_05_*` x4 |
| R6-06 outcomes readable before the freeze, backdated freeze | `GET /metrics?group_by=variant` returned per-arm activation before any plan (api1 1a: 200); freeze dated 2026-09-01 after that read accepted (api3 A) | 409 `PLAN_NOT_FROZEN` with no per-arm figure (api1 1a, api3 A); plain read: `metrics.experiment` null plus warning `EXPERIMENT_WITHHELD_PLAN_NOT_FROZEN`; `FROZEN_AT_BACKDATED` when `frozen_at` precedes the latest audit instant of the version, `FROZEN_AT_IN_FUTURE` after the clock. A freeze dated in the past is still accepted when nothing was recorded for the version (api3 A: 200, nothing was read) | `test_R6_06_*` x2 |
| R6-07 refusals without audit rows | `record-decision` refusals for a segment basis, review mismatch, second decision and the ship blockers wrote no row | one central `record-decision-refused` row for every `ApiError` of C10 (rule id, role, message): 4 rows for api1 3b..4d, and DECISION_INVALID, BACKFILL_ADMIN_ONLY, ANALYSIS_UNKNOWN, REVIEW_UNKNOWN, DECIDED_BEFORE_RUN, PLAN_NOT_FROZEN too. Refusals before the handler (role, schema, idempotency) keep none | `test_R6_07_*` x2 (counts rows) |
| R6-09 outcome before assignment | J_pre_treatment: 10 accounts activated before assignment, pre-assignment activations counted in the experiment's activation, and the guardrail counted units whose window was still open | experiment activation 0/5 vs 0/5 in all four (the generic activation metric stays 10/10); guardrail eligible 0 (window incomplete); C04 refuses an account that already activated (422 `OUTCOME_BEFORE_ASSIGNMENT`, admin backfill excepted); observations and segments use the same rule. Golden exact; snapshot v1 unchanged; v2 (SRM MISMATCH, lift withheld) loses one pre-assignment activation: treatment 39/87 (was 40/87) | `test_R6_09_*` x4, review-check "R6-09" |
| R6-13 Bonferroni k | k = segments tested in the one split shown (3) | the segments page uses k = 9 across plan, segment and timezone (threshold 0.005556); the API keeps its per-split k; documented in D-10 | `test_R6_13_*`, golden-check "segments_family", e2e |
| R6-14 `conclusive` and SRM | `conclusive` true under an SRM MISMATCH | `conclusive` also requires SRM OK; NOT_CONCLUSIVE warning lists the five reasons; the decision page lists them | `test_R6_14_*` |
| R6-08 INJ-10 gap | disclosed only for the 2026-04-15 read | 11 v1 accounts (control 5, treatment 6) are affected at the as-of; control 63/200 unchanged, treatment 82/200 published vs 86/200 drawn: published +9.50, drawn +11.50, +9.96 without the gap accounts. In `data/README-generator.md` (DR-01, INJ-10), `manifest.json` DR-01 `instrumentation_gap_disclosure`, `injection-manifest.json` INJ-10 `reaches_the_as_of_read`, and the result and case-study pages (`gap-note`) beside "conclusive by a hair". Entity files byte-identical (`python data/generate.py` leaves them unchanged; `dataset_hash` unchanged, `generated_at` moves) | `test_R6_08_*`, review-check "R6-08", e2e |
| R6-10 secondary intervals, linked share | week-4, guardrail and revenue differences were manifest figures only | computed in the browser: week-4 -4.50 pp, Newcombe including 0 (equal to the generator's DR-02, 71/200 vs 62/200); guardrail -0.50 pp including 0; revenue 97.83 vs 130.95 with a Welch interval including 0 (Python restates and the independent snapshot reference agrees); the tracking page shows linked real users of all real users | `test_R6_10_*` x3, golden-check "secondary", review-check, e2e |
| R6-11 / R6-12 wording | "identity links" unqualified; "on-or-after" accounts unlabeled; "p 0.000001" | forward-only identity links, exact day 7 against on-or-after day 7, "p < 0.000001" (exact 5.7e-7) | review-check, e2e (`cs-p`) |

## Reviewer harness after the fixes (hand / Python / SQL / TypeScript)

| Case | Result |
|---|---|
| A, B, C, D, E, F, G, M | 0 disagreements |
| H_three | rejected by all four with `VARIANTS_NOT_TWO` (the text differs only in the language wrapper) |
| I_frozen_late | 0 disagreements; `plan_frozen` false, `conclusive` false |
| J_pre_treatment | 0 disagreements; experiment activation 0/5 vs 0/5, guardrail eligible 0 (hand values) |
| K_dst_sql, B_maturity | 0 disagreements under UTC, America/New_York, Europe/London, Pacific/Kiritimati |
| L_equal | 0 disagreements; `conclusive` false |

## Not changed and why

* A plan frozen in the past is accepted when nothing was recorded for the version (the lower bound is the latest audit instant).
* The API's single-split segment read keeps k = segments tested in that split (R6-13 documented, the site uses the family).
* Refusals before the C10 handler (forbidden role, schema, idempotency conflicts) keep no audit row.
* The DB suite takes about three and a half minutes; the deadlock retry is tested by injection.

## Commands and results (from `apps/productsignal`, 2026-10-27)

| Command | Exit | Result |
|---|---|---|
| `../../.venv/bin/python -I tests/reference_check.py` | 0 | ALL OK (706 checks) |
| `DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/productsignal ../../.venv/bin/python -m pytest -q -p no:cacheprovider` | 0 | 357 passed |
| `harness.py` on cases A..M (scratch database), `tzrun.py` | 0 | see the table above |
| `api1.py` .. `api4.py` (and `api1b.py`, api1 with the clock moved on after section 3) | 0 | new statuses as in the findings table |
| `../../.venv/bin/python data/generate.py` | 0 | entity files byte-identical (git shows no change under `web/public/data/<entity>.json`) |
| `../../.venv/bin/python web/scripts/make-snapshot-reference.py` | 0 | written; v1 digests equal, v2 digests changed (R6-09), segments_family and secondary added |
| `npm run check` (web/) | 0 | typecheck clean; golden ALL OK (2519 checks); review OK (36 checks) |
| `npm run build:pages` (web/) | 0 | built, 12 route copies |
| `npm run e2e` (web/) | 0 | 77 passed |


# Entry-journey evidence (P06-ART-08; artifact worker A-056, task T-06-05)

Appended to this file; nothing above was changed. It adds what P06-ART-08 asks for beyond the review evidence: business scenarios with expected answers, actual observations and defect disposition for the **entry journey** (P06-GOAL-09: one source-to-decision journey on the reference fixture, then the snapshot experiment), with the routes, the screenshot names that `npm run e2e` writes and the hosted run links.
**Synthetic data only** (dataset `ps-20261026-20261026`, generator hash `12672f9c39402517083bbbbe9164cbefe3435361dff086eb0d9e16e60f9b66f8`, contract v1). Observed results, constructed (designed) relationships and hypothetical benefits are kept apart: everything below is OBSERVED in a synthetic history or on the fixture; nothing is a measured effect on a real product; the designed treatment effect, v2's sample-ratio mismatch and the INJ-10 instrumentation gap are constructed by the generator; no benefit is claimed. The v1 result is **conclusive by a hair** (the lower bound of its Newcombe interval is +0.000812), and the published lift sits inside the gap: published +9.50 pp, drawn +11.50 pp, +9.96 pp excluding the 11 gap accounts.
Code revisions: the entry-journey runs of the first publication are for **`d7111f1`** (the site commit; portfolio `6e381bf`); the reviewer fixes above are **`fdf911a`**, republished to the portfolio as **`e360bf1`**.

## Provenance of each observation (what was run, and by whom)
| Source | What it is | Run by |
|---|---|---|
| Hosted CI run **40426536267** (`productsignal-ci.yml`, code `d7111f1`): https://github.com/mrrishit909/projects-site/actions/runs/40426536267 | Mode A and Mode B both success; evidence artifact uploaded (2,510 TypeScript golden and snapshot checks and 77 Playwright tests at four widths and 200% zoom at that commit) | GitHub-hosted runner, recorded in `docs/program/verification-ledger.json` |
| Hosted live-check run **40426869172** (`live-check.yml`, matrix, code `ccf70f5`, portfolio `6e381bf`): https://github.com/mrrishit909/projects-site/actions/runs/40426869172 | deploy-wait matched the code sha, 12 routes 200, the manifest served, the case study links to the site and the site links back, a 360 / 1280 browser journey with no console errors; all jobs success | GitHub-hosted runner, recorded in the ledger |
| The local `npm run e2e` of the fixed code (`fdf911a`), `web/evidence/playwright-report.json` | 77 expected, 0 unexpected, 0 flaky, 0 skipped; started 2026-10-27T01:51:47Z, 78.4 s | recorded by the fix workers (A-053/A-054); this artifact pass **read** the report and the 65-screenshot index and did **not** run `npm run e2e` |
| `tests/reference_check.py`, `data/sql/analysis/run_all.py` (golden and snapshot reconciliation), `build_workbook.py --recalc`, `tests/test_artifacts.py` | the golden figures and the snapshot figures re-observed independently of the browser | this artifact pass, results in `release-package.md` |

**The republish `fdf911a` / `e360bf1` has its own CI and live-check runs, pending when this pass was dispatched.** The committed ledger now records them (`docs/program/verification-ledger.json` and `release-manifest.json`, HEAD `2c741e6`, 2026-10-27T01:56:15Z): CI run **40435203915** (both jobs success, code `fdf911a`) and live-check run **40435315836** (code `fdf911a`, portfolio `e360bf1`, all jobs success). Those two ids are copied from the ledger and were **not fetched** by this pass; any statement of hosted verification for the fixed release rests on that record, and the browser and hosted evidence beyond it is the earlier recorded runs.

## Routes (base `/projects-site/labs/productsignal/`; live site https://mrrishit909.github.io/projects-site/labs/productsignal/, not fetched by this pass)
| Route | Screen | Entry route (`web/src/routes.ts`) | What it shows (read from the view, the spec and the recorded run) |
|---|---|---|---|
| `/` | landing | no | the decision, the honesty labels (synthetic, static snapshot, simulated actions), the manifest strip (dataset version, hash, generated time, code sha) |
| `/overview/` | journey overview (P06-UI-01) | **yes** | the twelve metrics with windows, populations and exclusions, equal to the Python domain; a cutoff picker over the five runs and the as-of that shows the D-08 rule |
| `/funnel/` | funnel explorer (P06-UI-02) | **yes** | ordered events, the funnel (154 / 51 / 41 / 4) and its exclusions |
| `/cohorts/` | cohort laboratory (P06-UI-03) | **yes** | the maturity-aware retention grid by signup week in the account timezone; immature cells blank, exact day 7 and on-or-after-day-7 as separate columns |
| `/tracking/` | tracking quality (P06-UI-04) | no | duplicates, delayed, unknown identity, the linked share and the injected problems |
| `/experiments/` | experiment registry (P06-UI-05) | no | plans verified in the browser, every run with its interim or final label and prior-run count; the "freeze a plan" draft is a simulation |
| `/result/` | experiment result (P06-UI-06) | **yes** | the sample ratio before any lift; the golden case (`?dataset=golden`) reproduced in the browser; the snapshot: v1 final conclusive by a hair with the INJ-10 disclosure, v2 MISMATCH in place of a lift, the interim runs |
| `/population/` | assigned and exposed (P06-UI-07) | no | the denominators: assigned, exposed, mature |
| `/segments/` | segment analysis (P06-UI-08) | no | exploratory label, the number tested (k = 9) and the Bonferroni threshold |
| `/decision/` | decision memo (P06-UI-09) | **yes** | the evidence, the inconclusive option, the blocked options with their reasons; a simulation in browser memory |
| `/evidence/` | evidence | no | a live golden check, provenance, the hash |
| `/case-study/` | case study (P06-UI-10) | **yes** | what is built, what is simulated, the disclosures, the modes |

## Screenshot names (`npm run e2e`, `web/e2e/screens.spec.ts`, written to `web/evidence/`, not tracked by git; CI uploads them as the evidence artifact)
`<view>-<width>.png` at 360, 768, 1280 and 1920 CSS pixels and `<view>-zoom200.png` at 640 CSS pixels with device scale 2 (200% zoom), for thirteen views: `home`, `overview`, `funnel`, `cohorts`, `tracking`, `experiments`, `result`, `result-golden`, `population`, `segments`, `decision`, `evidence`, `case-study`: **65 files**, plus `index.json` (route, width, scroll width, inner width, device scale per shot) and `playwright-report.json`. The suite has 77 tests: 12 journey tests (`web/e2e/journey.spec.ts`) and 65 screen tests.
In the recorded local run every shot has `scrollWidth` at most `innerWidth` (no horizontal overflow at any of the five widths) and every test watches the browser console for errors.

## Business scenarios: expected answer, actual observation, disposition
Expected answers come from the hand calculation (`tests/fixtures/golden/CALCULATION.md`) or from the independent reference (`data/sql/reference_metrics.sql` and the Python domain over the snapshot); "actual" is what was observed in the named run.

| # | Scenario (the decision it supports) | Expected answer | Actual observation | Disposition |
|---|---|---|---|---|
| S1 | **Known answer.** 100 mature control and 100 mature treatment accounts, 20 and 30 activated (is the lift conclusive?) | 0.200000 and 0.300000, **+10.00 pp**, relative lift 0.500000, Newcombe -0.020249 to +0.216734 (includes zero): **not conclusive**; sample ratio 100 / 100 OK | Browser (e2e "result under ?dataset=golden: the golden case, sample ratio before the lift"): the same figures, the sample ratio shown first; `tests/reference_check.py` ALL OK (706 checks); SQL 09 and the reference SQL on the golden database equal `expected.json` on every key | passed, no defect |
| S2 | **Is the sample ratio checked before the lift?** (v1 and v2) | v1 200 / 200 against 0.50 / 0.50: OK; v2 62 / 92 against 0.60 / 0.40: chi-square 25.004329, p below 0.000001, **MISMATCH**, shown in place of a lift; ship and stop blocked | e2e "result on the snapshot: v1 final conclusive by a hair with the disclosure; v2 SRM MISMATCH in place of a lift; interim runs" passed; SQL 06 gives the same observed, expected, statistic and p; the workbook shows `withheld` for run an-005 | passed |
| S3 | **Can an interim look be called final?** (v1's four runs) | the three interim runs (2026-05-18, 2026-06-15, 2026-07-13) read +11.37, +11.91 and +9.15 pp and none excludes zero; the final run an-004 reads 63 / 200 against 82 / 200, +9.50 pp, relative lift 0.301587, interval **+0.000812 to +0.186863**, conclusive by a hair | e2e (the same test) shows each run with its label and prior-run count; SQL 05 equals the reference SQL and the domain at each cutoff; the workbook's five-run switch equals the domain | passed |
| S4 | **How much does the instrumentation gap move the lift?** (INJ-10, R6-08) | published +9.50 pp; drawn +11.50 pp (86 of 200 against 63 of 200, a constructed figure); +9.96 pp excluding the 11 gap accounts (63 of 195 against 82 of 194, interval +0.35 to +19.32) | e2e checks the `gap-note` beside "conclusive by a hair"; SQL 05 `gap_accounts` and `gap_lift` give 5 and 6 gap accounts and +9.50 / +9.96; `run_all.py` recomputes +11.50 from the manifest's drawn counts | passed; the gap is disclosed, not corrected (the domain cannot see it) |
| S5 | **Are immature accounts kept out of a rate?** (maturity) | 76 signups in the activation window, 17 immature, 59 mature, 21 activated (0.355932); the cohort grid shows blank cells where no account is mature | e2e "cohorts: the maturity-aware grid has blank immature cells, in the account timezone" passed; SQL 01 and 02 equal the reference SQL and the domain | passed |
| S6 | **Exact day 7 or on or after day 7?** (never mixed) | the cohort of local signup dates 2026-08-24 to 2026-08-31: 5 of 16 on exact day 7 (0.312500), 11 of 16 on or after (0.687500), week 4 7 of 16 (0.437500); by the UTC calendar the day-7 count would differ for 8 and 5 accounts | e2e (cohorts) passed; SQL 02 `window_check` and `timezone_effect` equal the domain; the BI facts carry both flags | passed |
| S7 | **What did the tracking lose or delay?** | 12,552 rows: 124 duplicates dropped, 237 delayed over 24 h (0.019070), 30 unknown identity, 305 bot, 114 internal, 11,979 analysed; 0.697121 of real users linked | e2e "tracking: the counts equal Python and the injected problems are listed" passed; SQL 04 equals the reference SQL and the domain | passed |
| S8 | **Does a run count only what existed by its cutoff?** (D-08) | the first interim run (2026-05-18) counts 155 accounts (77 control, 78 treatment), SRM statistic 0.006452, revenue totals 5,322.00 and 5,481.00 (means 81.88 and 85.64) | e2e "overview: the twelve metrics equal the Python domain's figures; the cutoff picker shows the D-08 rule" passed; `test_snapshot_interim_cutoff_counts_only_the_accounts_assigned_by_then`; SQL 05 and 07 give the same | passed |
| S9 | **What can be decided?** (C10, the decision screen) | v1 final: `ship` permitted (all five conclusive conditions hold), `stop` and `inconclusive` allowed; v1 interim runs: ship refused; v2: only `inconclusive`; every refusal is audited and nothing ships | e2e "decision: evidence, the inconclusive option, blocked options, the simulation is labelled and in memory" passed; API tests `test_c10_a_sample_ratio_mismatch_blocks_ship_and_stop`, `test_c10_refuses_an_interim_run_for_ship_but_not_for_stop_or_inconclusive` and `test_R6_07_every_refused_decision_leaves_an_audit_row` (357 passed locally at `fdf911a`; Mode A success on the hosted run per the ledger) | passed; no `decisions` row exists in the snapshot database (by design) |
| S10 | **Honesty** (is it clear nothing is live and nothing ships?) | synthetic label, the static snapshot note, the registry draft and the decision screen labelled simulations, segments labelled exploratory | e2e landing, experiments, population and segments, decision and case-study tests passed, and the screens tests passed at four widths and at 200% zoom with no overflow and no console errors | passed |

## Defect disposition
| Defect or gap | Where found | Disposition |
|---|---|---|
| R6-01 .. R6-14 (conclusive ignoring the freeze and the sample ratio, df with three arms, session timezone, future cutoffs, client-stated instants, outcomes before the freeze, unaudited refusals, pre-assignment outcomes, Bonferroni family, the INJ-10 gap, secondary intervals, wording) | the independent review A-051 | **fixed** at `fdf911a`, held by regression tests in Python, SQL, TypeScript and the API (the table at the top of this file) |
| The INJ-10 instrumentation gap reaches the published v1 lift (+9.50 against drawn +11.50 and +9.96 excluding the gap accounts) | review finding R6-08 | **open (accepted limitation, disclosed)**: the domain cannot see the gap; stated beside "conclusive by a hair" on the result and case-study pages, in the manifest and in the artifact documents |
| The v1 result is conclusive only by a hair (lower bound +0.000812) | this pass's reconciliation (`sql-analysis.md` section 5) | **documented**: the memo recommends a staged ship and says how thin the evidence is |
| v2's sample ratio is a MISMATCH | constructed (INJ-08, DR-06) | **by design**: the lift is withheld, ship and stop are blocked, `inconclusive` is the only decision |
| The public case study's "Not built yet" line still says there is no Welch interval on the revenue difference | found by this pass reading `productsignal/project.json` | **reported to the coordinator**: the site computes it (R6-10) and this package states what is built; the file belongs to `unified-portfolio` and was not touched |
| Daylight-saving edges are not pinned by the fixture; three-variant experiments are refused; the API's single-split segment read keeps its own Bonferroni k; refusals before the C10 handler leave no audit row | the review and the contract (D-10 "Not fixed") | **open (accepted limitations)**, listed in `requirements.md` section 5 |
| The registry and decision screens of the public site act on nothing | Mode B design | **accepted**: a static demo; the transactional behaviour is verified on hosted runners against PostgreSQL |
| Hosted evidence for the republish `fdf911a` / `e360bf1` | release manifest | **recorded in the ledger** (CI `40435203915`, live check `40435315836`), copied not fetched by this pass; pending when this pass was dispatched |
| No hosted run of `tests/test_artifacts.py`; Excel and Power BI not run | this package | **open**: the artifact tests run inside the existing `pytest -q` step on the next push (LibreOffice and database parts skipped when unavailable); the workbook was recalculated by LibreOffice only and no `.pbix` exists |
