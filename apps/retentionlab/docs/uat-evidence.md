# RetentionLab: UAT evidence (P10-ART-08; artifact worker A-079, task T-10-06)

**Synthetic data; economics hypothetical; no retention improvement is claimed.** Dataset `rl-20261026-20261026`, `dataset_hash` `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`, contract v1, code revision `ce96e65`. **How to read it without installing anything:** every row says what a business reader should see (**expected answer**, with its independent source), what was seen (**actual observation**, with where) and what became of it (**disposition**). Nothing here needs to be re-run to be read.

## Provenance of each observation (what was run, and by whom)
This file was created by this pass (the artifacts worker, in a sandbox, 2026-10-27). It separates three kinds of evidence:

| Kind | What | Status in this pass |
|---|---|---|
| Run by this pass | SQL investigations 01..10 on scratch databases `artifacts10_*`, the Python side, `reference_check.py`, the LibreOffice-recalculated workbook, the BI exports, the full `pytest` suite against a scratch database | executed; results in "Commands and results" below |
| Read, not re-run | the browser evidence of the site: `web/evidence/index.json` (60 screenshots) and `web/evidence/playwright-report.json` (90 tests), untracked files written by the coordinator's run of `npm run e2e` after the R10 fixes (A-077) | this pass did **not** run `npm run e2e`; the files were read and their counts checked by `tests/test_artifacts.py` where present |
| Recorded elsewhere, not fetched | CI run `40464123151` (green in both modes on `c17fa32`, per the release manifest); live-check run `40464668157` of the R10 republish `cf04a0e` (success, live code_sha `c17fa321f28605ac56e24b59837441c29cc16d41`, recorded in the ledgers at 2026-10-27T07:04:14Z: this was **pending at dispatch** of this pass and was recorded while it ran); CI run `40464667982` on the workflow-provisioning commit `7a748ac` (success in both modes, no artifact tests yet); the earlier live-check run `40456970303` (release `b5168a2`) | **not fetched** by this pass: the sandbox has no route to the run pages and the pass asserts nothing the ledgers do not show |

## Routes (base `/projects-site/labs/retentionlab/`; live site https://mrrishit909.github.io/projects-site/labs/retentionlab/, not fetched by this pass)

| Route | View | Contract | What a reader should find |
|---|---|---|---|
| `/` | Start | P10-GOAL-01 | the decision, the snapshot manifest strip, the honesty labels |
| `/overview/` | Retention overview | P10-UI-01 | mature churn, the censored tail hatched and never zero |
| `/cohorts/` | Cohort explorer | P10-UI-02 | plan, region, tenure: who churns and what the model expected |
| `/features/` | Feature evidence | P10-UI-03 | availability proof, what arrived late, refusals by reason |
| `/models/` | Model comparison | P10-UI-04 | the four models, the margins marked "met, by construction", the golden case recomputed |
| `/calibration/` | Calibration lab | P10-UI-05 | the reliability curve with the rows behind each point, the Platt effect |
| `/capacity/` | Capacity planner | P10-UI-06 | precision, recall, lift at K, contact budget, simulated economics |
| `/account/` | Account explanation | P10-UI-07 | risk factors with no causal claim |
| `/queue/` | Outreach queue | P10-UI-08 | synthetic draft actions, never sent |
| `/monitoring/` | Monitoring | P10-UI-09 | drift by region with false positives, maturity, two freshness clocks |
| `/evidence/` | Evidence | P10-TEST-01..12 | designed relationships, injected defects, disclosures |
| `/case-study/` | Case study | P10-UI-10 | model card, evaluation and the limits of the intervention |

## Screenshot names (`npm run e2e`, `web/e2e/screens.spec.ts`, written to `web/evidence/`, not tracked by git)
60 files: each route at 360, 768, 1280 and 1920 px plus one 200 % zoom capture, named `<route>-<width>.png` and `<route>-zoom200.png` for the routes `home`, `overview`, `cohorts`, `features`, `models`, `calibration`, `capacity`, `account`, `queue`, `monitoring`, `evidence`, `case-study`. The index records `scrollWidth <= innerWidth` for all 60 (no horizontal overflow). The 90 browser tests (expected 90, unexpected 0, flaky 0, skipped 0) include a contrast measurement on every route and a word-break check on the model card.

## Business scenarios: expected answer, actual observation, disposition

| # | Scenario | Expected answer (independent source) | Actual observation (where) | Disposition |
|---|---|---|---|---|
| S1 | The known answer: four accounts, risks .8 .6 .4 .1, outcomes 1 0 1 0, capacity 2 | precision 0.500000, recall 0.500000, Brier 0.192500, AP 0.833333, lift 1.000000, budget 10.00, value 8.45 hypothetical (`CALCULATION.md`, hand arithmetic) | the SQL of investigation 09, the domain, `expected.json` and the workbook sheet `Golden case` give exactly these (reconciliation A) | pass |
| S2 | A late event must not be used | golden: 2 events arrived late (1 usage, 1 support) and are excluded; cohort: stored features = point-in-time rebuild | SQL 09: 1, 1, 0, 0; SQL 05: all 765 stored feature rows equal the recomputation; ignoring arrival would change a feature on 97 of 765 cohort rows (world: 175 of 1,513 test rows, 0.115664, published) | pass |
| S3 | Unknown outcomes are unknown | a fully censored February cohort has null ranking metrics; the world's censored share is 0.397610 (3,594 of 9,039) with mature churn 0.104500; counting censored rows as retained would show 9.4 %, 6.9 %, 3.9 % | SQL 09: 4 eligible, 0 mature, churn null; SQL 04: 3,594 / 9,039; four injected labels of false for open windows refused CENSORED_LABEL | pass |
| S4 | No account on both sides of a boundary | chronological split, label-window purge then group purge; test rows never purged | SQL 06: 0 cohort accounts retained in two ranges, 0 retained rows crossing a boundary, the assignment recomputed in SQL differs from the stored one on 0 of 970 rows; world: train loses 879 + 124 + 52, validation 1,291 + 13, test none | pass |
| S5 | Which model is better | logistic (Platt) AP 0.238552 / Brier 0.105019 against the rule 0.136653 / 0.109255, random 0.126793 / 0.326543, prevalence 0.124917 / 0.109664 on 1,513 rows (manifest DR-01) | SQL 01, `python_side.py`, the domain and the workbook `Models` sheet agree; every margin is met **by construction** | pass; the margin is not evidence (see S5 note) |
| S6 | Can I trust the probabilities | Platt made the model worse on test (Brier 0.104515 to 0.105019); six of ten bins empty; starter gap -8.07 pp; apac gap -10.68 pp not designed (D-09 R10-08/09) | SQL 02 and 10 agree with `calibration.json` bin by bin; the frozen mapping reproduces all 1,513 stored probabilities | pass |
| S7 | What does a capacity of 5, 10 or 20 get | no published expectation; derived independently by `python_side.py` | the logistic model's top 5 holds **0** churners, top 10 holds 2 (0.200000), top 20 holds 5 (0.250000, lift 2.001323); the rule's and constant's top K are ties | pass; finding F1 below |
| S8 | What is a contact programme worth, and for whom | budgets 40.00 / 80.00 / 160.00; +21.38 / -6.87 / -95.46 on the 97 scored cohort accounts; +81.13 / +71.04 / -29.12 on the 1,241 scored world accounts; all hypothetical (manifest, D-09 R10-04) | SQL 03 reproduces the cohort values from the predictions, the generator rebuild reproduces the world values (reconciliation F); the break-even removal shares are 0.195496, 0.218788, 0.247894 | pass |
| S9 | The queue is a draft and risk is not responsiveness | `outreach_events.status` only `draft`; `RISK_NOT_RESPONSIVENESS` refused; capacity above the population refused | 35 stored queue rows are all draft and equal the top K of the SQL ranking; `tests/test_adversarial.py` and `tests/test_api_commands.py` pass in the full run | pass |
| S10 | Where does the population drift | apac from 2026-05-01 (0.513545, 0.551353, 0.579740, 0.765053, 0.491035); the whole population stays small; the diagnostic has false positives before the change | SQL 07 recomputes the four test cutoffs for every region and equals the published series; five apac exceedances before the change, four on a floored bin; whole-population maximum 0.043730 | pass; finding F2 below |
| S11 | Rejected variant | 18 rejected rows and 9 refused requests (a cancellation reason as a feature, a latent column, an identifier, a fit on validation rows, calibration on its own rows, a threshold on test, a censored row labelled retained, a capacity above the population) | `tests/test_variants.py` and `tests/reference_check.py` (ALL OK, 1,823 checks) pass | pass |
| S12 | Empty variant | every count 0, every ratio and score null, `empty_population` true | `tests/test_variants.py` passes against `variant-empty/expected.json` | pass |
| S13 | A future as-of must not turn censored rows into labelled ones (R10-01) | `GET /metrics` with an `as_of` later than the server clock is refused 422 `AS_OF_IN_FUTURE`; a stored censored label stays censored | `tests/test_review10.py` and `tests/test_api_reads.py` pass in the full run | pass |
| S14 | The fit depends on no identifier and no row order (P10-TEST-12 reinterpreted, R10-10) | the world refitted with every account id permuted and every row list shuffled gives byte-identical frozen preprocessing, coefficients, rule rates, prevalence, Platt mapping and probabilities | `tests/test_generator.py::test_r10_10_*` pass in the full run | pass |

S5 note: a met margin in a world whose generator was tuned to meet it carries no information about real accounts; the disposition "pass" says the figures are reproduced, not that the model is good.

## Review R10: findings, before and after

| Id | Finding (independent disproof review A-075) | Fix (A-077, commit `ce96e65`, decision D-09) |
|---|---|---|
| R10-01 | a future `as_of` on `GET /metrics` labelled censored rows (a 2027 as-of on the golden cohort gave churn 1.000000) | 422 `AS_OF_IN_FUTURE`; stored labels authoritative; mismatches reported as `labels_mismatched` |
| R10-02 | contrast below 4.5:1 on the cream panels | dark brass / plum / coral inks; a browser test measures every route |
| R10-03 | the model card broke words at 360 px | stacked pairs, breaks only after `_` or `-`; a browser test |
| R10-04 | economics of the 97-account cohort quoted as full-world | every figure names its population; the world values are published beside them |
| R10-05 | stale test count | the evidence and case-study routes read one count source |
| R10-06 | rows presented as churner counts | rows and distinct accounts stated (1,513 / 442; 189 / 95) |
| R10-07 | drift series without its false positives | all 21 values, the floor artefact, `floored_bins` published |
| R10-08 | Platt made the model worse without saying so | stated: Brier 0.104515 to 0.105019; `platt_effect` published |
| R10-09 | apac's gap unexplained | named as the largest gap and labelled not designed |
| R10-10 | P10-TEST-12 implemented without a decision | reinterpreted and checked by a permutation refit |
| R10-11 | incomplete outcome-informed choice list | D-G02 and D-G03 carry `items`; all eleven listed |
| R10-12 | wrong figures in D-07 | corrected (prevalence 0.124917, mature churn 0.104500) |
| R10-13 | "744 training rows" ambiguous | "1,088 retained rows, 744 eligible and mature for fitting" |
| R10-14 | no honest reference for the Brier margin | a prevalence-constant baseline (fourth model, migration 0003) |
| R10-15 | smaller defects | `DUPLICATE_FIELD`, `num.ts` comments, a snapshot reference leaf |

Before the fixes the review reported 1 code defect, 2 accessibility defects and 12 documentation findings; 249 of 250 snapshot mutations and all 180 `expected.json` mutations were caught (ledger A-075). After: the fixes are accepted (ledger A-077: pytest 342 passed with no skips, reference check 1,823, 3,197 golden + 95 review checks, 90 browser tests).

## Defect disposition
Defects and findings of THIS pass (the package found no defect in the domain, API, migrations, loaders, generator, fixtures or site; the protected paths are unchanged from `ce96e65`):

| Id | Finding | Disposition |
|---|---|---|
| F1 | The logistic model's top 5 on the test table holds no churner (0 of 5); the hypothetical value at K = 5 multiplies predicted probabilities averaging 0.204607 over the top 5 cohort accounts, while the top 5 of the test table contained no churner | not a defect (a result); stated in `executive-memo.md`; no change |
| F2 | The public case study says the whole population "stays at 0.017043"; that is its value at 2026-05-01 only (range 0.000000 at the reference month to 0.043730 over the series; 0.002069 in September). It also says "five of the thirteen months before the change": five of the 13 cutoffs before the reference cohort, or five of 14 comparison cutoffs before the change | wording, for the coordinator; the figures are right; no change made (the case study is read-only for this pass) |
| F3 | The README, `docs/contracts.md` D-06 and the case study ("Not built yet") say average precision and the stability index have no SQL recomputation; this package adds one (investigations 01, 02, 07, 08, 09) | overtaken, not wrong when written; for the coordinator to update when this package is published |
| F4 | `docs/contracts.md` D-07 says "data freshness 0 h"; the manifest and the reference SQL give 1 hour for the published cohort (latest `available_at` 2026-10-04T22:09:42Z); 0 h may hold for the whole world, which is not published | for the coordinator; no change made |
| F5 | During this pass a freshly loaded scratch database made the reference SQL plan badly (about 0.6 s a call, 52 s in all) because it had no planner statistics | fixed in `prepare_snapshot.py` (`ANALYZE` after the load); 20 s now |
| F6 | During this pass a first draft of a full-world check compared a value with itself | caught, replaced by a comparison with the rebuilt world; the comparison is now mutation-tested (`test_the_comparison_detects_a_one_leaf_change`, and a one-row change of the test table fails 11 result sets) |

Open and carried: no randomised experiment exists; the by-construction margin; four features; Platt on one cutoff; cursors not bound to a dataset version.

## Commands and results (from `apps/retentionlab`, 2026-10-27, scratch databases `artifacts10_*` only)
The commands and their last lines are in the table "What this artifact pass ran" of `release-package.md`. In short: the reference check `ALL OK (1823 checks)`; the baseline suite `342 passed`; `run_all.py` `RESULT: OK (393 reconciliation rows, 393 equal; 43 result sets, 229 rows)`; `Checks!B2` TRUE in the delivered workbook; the whole suite with this package gives 383 passed (342 existing + 41 of this package).

## Erratum recorded by the coordinator (2026-10-27)

* `docs/contracts.md` D-07 states "data freshness 0 h". The published manifest and the reference SQL give **1 h** for the cohort
  (latest `available_at` 2026-10-04T22:09:42Z against the 2026-10-05 as-of; `freshness.data_hours` = 1). The contract file is a
  protected path of the provenance test (it must equal the published commit ce96e65), so the line is left as published and
  corrected here; the next republish of RetentionLab carries the correction into the contract.
