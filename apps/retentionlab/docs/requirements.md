# RetentionLab: requirements and traceability (P10-ART-02)

**Synthetic data throughout; the economics are hypothetical; no retention improvement is claimed.** Dataset `rl-20261026-20261026`, `dataset_hash` `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`, contract v1, code revision `ce96e65`.

**How to read it:** this file can be read without installing anything. Section 1 gives the user stories and acceptance criteria, section 2 the functional requirements, section 3 the non-functional ones, section 4 traces every P10 requirement family to the code that implements it, the test that proves it and the artifact that reports it, and section 5 lists what is deferred or open. Paths are relative to `apps/retentionlab`. Result kinds are kept apart: **simulated** (one draw of the synthetic world), **hypothetical** (an assumed economic value) and **constructed** (what the generator built in).

The organising question is **which accounts deserve limited retention attention under uncertain intervention value** (P10-GOAL-01). Numbers below are quoted from `sql-analysis.md` and reconcile to `data/sql/reference_metrics.sql`, the Python domain, `tests/fixtures/golden/expected.json` and the manifest (393 reconciliation rows printed by `data/sql/analysis/run_all.py`).

## 1. User stories and acceptance criteria

| Story | As a ... I want ... so that ... | Acceptance criteria (answer, observed in) |
|---|---|---|
| US-01 | data scientist, features that use only what was known at the cutoff, so that the model cannot see the future | A late event is counted and excluded (golden: 2 arrived-late events; `09`); all 765 stored cohort feature rows equal the recomputation from events (`05`); a request naming `cancellation_reason` is refused `POST_OUTCOME_FIELD` (`tests/test_adversarial.py`, P10-TEST-01) |
| US-02 | data scientist, labels that say "unknown" while a window is open, so that censored accounts are never counted as retained | 3,594 of 9,039 eligible world rows (0.397610) are censored, mature churn 0.104500 (`04`); four injected labels of false for an open window are refused `CENSORED_LABEL` (P10-TEST-07) |
| US-03 | data scientist, chronological splits with purges, so that no account is on both sides | World: train loses 879 + 124 + 52 rows, validation 1,291 + 13, test none (`06`); 0 cohort accounts retained in two ranges; the cohort assignment is recomputed in SQL row for row |
| US-04 | data analyst, models compared on one population, so that a margin is not a mirage | AP 0.238552 / Brier 0.105019 (logistic, Platt) against 0.136653 / 0.109255 (rule), 0.126793 / 0.326543 (random), 0.124917 / 0.109664 (prevalence) on 1,513 rows from 442 accounts (`01`); every margin is labelled met **by construction** (`08`) |
| US-05 | data analyst, calibration with the sample behind each point, so that I know where the probabilities can be used | Ten bins with counts, six empty for the Platt-calibrated model; Platt made the model worse on test (Brier 0.104515 to 0.105019; gap -2.26 to -2.86 pp) (`02`); the starter gap is -8.07 pp, apac -10.68 pp (not designed) (`10`) |
| US-06 | retention lead, precision, recall and lift at the capacity I have, so that I can judge the very top of the list | Logistic: 0 churners in the top 5, 2 in the top 10 (0.200000), 5 in the top 20 (0.250000, lift 2.001323), on the test table (`03`); ties across the cut are flagged |
| US-07 | finance partner, a contact budget and a value clearly labelled hypothetical and by population | Budgets 40.00 / 80.00 / 160.00; +21.38 / -6.87 / -95.46 on the 97 scored cohort accounts and +81.13 / +71.04 / -29.12 on the 1,241 scored world accounts (`03`) |
| US-08 | customer success manager, a draft queue that is never sent and an account view with no causal claim | `outreach_events.status` can only be `draft` (constraint); the 35 queue rows equal the top K of my own ranking (`03`); `RISK_NOT_RESPONSIVENESS` is refused (P10-TEST-09) |
| US-09 | data owner, drift by region with false positives named | apac exceeds 0.2 at 2026-05-01 (0.513545), peaks 0.765053 in 2026-08; five apac exceedances before the change, four with a floored bin, none for the whole population (maximum 0.043730) (`07`) |
| US-10 | BI analyst, a metric model that withholds nothing silently | `artifacts/bi/measures_recomputed.csv` has a row for every measure x population cell, with the reason when the value is null (censored, empty bin, withheld) (`bi-package.md`) |
| US-11 | reviewer, the known answer reproduced from the source records | Risks .8 .6 .4 .1, outcomes 1 0 1 0: precision 0.500000, recall 0.500000 at K = 2, Brier 0.192500, AP 0.833333, lift 1.000000, budget 10.00, value 8.45 (`09`, workbook `Golden case`) |
| US-12 | executive, a recommendation that says what is not known | `executive-memo.md`: no retention improvement is claimed; the margin is not evidence; a randomised experiment is designed |

## 2. Functional requirements

| Id | Requirement | Implemented by |
|---|---|---|
| FR-01 | Build point-in-time features from `event_at` and `available_at`, prove `max_available_at < prediction_at`, count late events (P10-FLOW-01) | C01, `domain/retentionlab/world.py`, trigger `rl_feature_row_guard` |
| FR-02 | Define labels with a 90-day horizon and 14-day grace; censored rows are NULL and excluded (P10-FLOW-02) | C02, `world.py`, trigger `rl_label_guard` |
| FR-03 | Chronological split with label-window purge, then group purge; publish dropped counts (P10-FLOW-03) | C03, `domain/retentionlab/split.py` |
| FR-04 | Fit preprocessing on retained training rows only; refuse `LEAKAGE` otherwise (P10-FLOW-04) | C04, `fitting.py`, `rules.py` |
| FR-05 | Train a seeded random baseline, a prevalence constant, a rule and a logistic regression on frozen 6-place strings (P10-FLOW-05) | C05, `fitting.py` |
| FR-06 | Fit Platt scaling on validation rows only; evaluate on test (P10-FLOW-06) | C06, `fitting.py` |
| FR-07 | Score accounts citing run, config hash, feature version and label version; derive publication status (P10-FLOW-07) | C07, trigger `rl_prediction_guard` |
| FR-08 | Prioritise a capacity-limited DRAFT queue; refuse capacity above the population and risk-as-responsiveness (P10-FLOW-08) | C08, `api/commands.py`, `rules.py` |
| FR-09 | Simulate economics: budget = K x cost, value = sum(p x effect x margin - cost) rounded once; labelled hypothetical (P10-FLOW-09) | C09, `domain/retentionlab/metrics.py` |
| FR-10 | Monitor a refresh: drift as a diagnostic, missingness, two freshness clocks, performance only on mature rows (P10-FLOW-10) | C10, `metrics.py` |
| FR-11 | Refuse a future `as_of` on a metrics read (`AS_OF_IN_FUTURE`) and never report a stored censored label as mature (D-09 R10-01) | `GET /metrics`, `rules.check_as_of`, `tests/test_review10.py` |
| FR-12 | Report every metric exactly, from frozen strings, with ties broken by account id (D-03, D-P10-03) | `metrics.py`, `data/sql/reference_metrics.sql` |
| FR-13 | Serve a static site of 12 routes over the published snapshot, labelling every browser-memory action as simulated | `web/src/routes.ts`, `web/src/views/` |
| FR-14 | Provide an independent recomputation of the metrics in SQL, including average precision and the stability index (this package) | `data/sql/analysis/*.sql`, `python_side.py` |

## 3. Non-functional requirements

| Id | Requirement | Evidence |
|---|---|---|
| NFR-01 | No floating point in any published figure; floats only inside fitting loops, frozen to 6-place strings | `tests/test_golden_domain.py` (no float), `tests/test_generator.py` (no float literal in the published files) |
| NFR-02 | Determinism: same seed, same bytes, under different `PYTHONHASHSEED`; fitting byte-stable | `tests/test_generator.py::test_two_runs_are_byte_identical_and_equal_to_the_committed_files`, `tests/test_fitting.py` |
| NFR-03 | The fit depends on no account identifier and no row order (P10-TEST-12 reinterpreted, D-09 R10-10) | `tests/test_generator.py::test_r10_10_*` |
| NFR-04 | Append-only evidence: events, predictions, queue rows, audit are immutable by trigger | `tests/test_migrations.py` |
| NFR-05 | Idempotent commands bound to actor, role and dataset version; deadlock retry; role boundaries | `tests/test_api_commands.py` |
| NFR-06 | Accessibility: contrast >= 4.5:1 for text under 18 px on every route; no word broken at 360 px; keyboard operation | `web/e2e/review10.spec.ts`, `web/e2e/journey.spec.ts` |
| NFR-07 | No credentials, no real personal data in any document or export; every account synthetic | `tests/test_artifacts.py::test_no_credentials_or_secrets_in_the_artifact_documents_and_files` |
| NFR-08 | Artifact reproducibility: scratch databases only (`artifacts10_*`), the shared `retentionlab` database is never touched; locale-independent ordering | `data/sql/analysis/prepare_snapshot.py` (safety), `tests/test_artifacts.py` |
| NFR-09 | Binary outputs (the workbook) rebuilt by script and checksummed | `artifacts/build_workbook.py`, `artifacts/CHECKSUMS.txt` |
| NFR-10 | Size: published data under 5,000,000 bytes (4,614,525 published) | `tests/test_generator.py::test_the_published_data_is_under_five_megabytes_and_the_cap_is_declared` |

## 4. Traceability matrix

Columns: requirement, what it asks, implemented in, proved by, reported in. The artifact column cites the investigation (`01`..`10` in `data/sql/analysis/`), the workbook sheet or the document.

| Id | Requirement | Implemented in | Proved by | Reported in |
|---|---|---|---|---|
| P10-GOAL-01 | the decision: which accounts deserve limited retention attention | whole product | `executive-memo.md` | `business-case.md` |
| P10-GOAL-02 | roles: data scientist, data analyst, BI analyst | routes and artifacts | n/a | `business-case.md` |
| P10-GOAL-06 | static interactive synthetic demo; backend evidence from CI | `web/`, `../../.github/workflows/retentionlab-ci.yml` | CI runs | `release-package.md` |
| P10-GOAL-12 | nothing real: no customer data, no payment, no operational write | `accounts.synthetic` CHECK | `tests/test_migrations.py` | all documents |
| P10-DOMAIN-01 | point-in-time uses `available_at` as well as `event_at` | `world.py` | `05`, `tests/test_rules.py` | `sql-analysis.md` section 5 |
| P10-DOMAIN-02 | chronological split with label-window purge | `split.py` | `06`, P10-TEST-03/04 | section 6 |
| P10-DOMAIN-03 | latent truth never enters a predictor | `rules.py` (`LATENT_TRUTH`) | P10-TEST-08, P10-TEST-12 | `technical-case-study.md` |
| P10-DOMAIN-04 | logistic regression compared with random and rule baselines (and a prevalence constant) | `fitting.py` | `01`, `08` | `executive-memo.md` |
| P10-DOMAIN-05 | no claim of real retention improvement | wording on every route | `tests/test_artifacts.py::test_executive_memo_*` | `executive-memo.md` |
| P10-DOMAIN-06 | randomised experiment designed separately, never simulated as evidence | `supported_by_randomised_experiment` always false | `tests/test_api_commands.py` | `executive-memo.md` section "The experiment that would be needed" |
| P10-GOLD-01 | four accounts: precision .5, recall .5, Brier .1925, no treatment effect | `tests/fixtures/golden/` | `tests/reference_check.py`, `09`, workbook `Golden case` | section 9 of `sql-analysis.md` |
| P10-GOLD-02 | reference inputs and human-readable calculation | `tests/fixtures/golden/inputs.json`, `CALCULATION.md` | `tests/test_golden_domain.py` | this file |
| P10-GOLD-03..07 | independent expected file; hash-checked; tolerances never enlarged | `tests/fixtures/golden/HASHES.json` | `tests/reference_check.py` (7 hashes) | `release-package.md` |
| P10-GOLD-08 | rejected-record variant | `tests/fixtures/golden/variant-rejected/` | `tests/test_variants.py` | `uat-evidence.md` |
| P10-GOLD-09 | empty-population variant: zero denominators are null | `tests/fixtures/golden/variant-empty/` | `tests/test_variants.py` | `uat-evidence.md` |
| P10-GOLD-10 | fixture hashes with the code revision | `tests/fixtures/golden/HASHES.json` | `tests/reference_check.py` | `release-package.md` |
| P10-GOLD-11 | definition gaps resolved by versioned decisions | `docs/contracts.md` D-05 | `tests/reference_check.py` | `technical-case-study.md` |
| P10-DATA-01 | `accounts` | `0001_schema.sql` | `tests/test_migrations.py` | `data-dictionary.md` |
| P10-DATA-02..05 | the four event tables with `available_at >= event_at` | `0001_schema.sql` | `tests/test_migrations.py` | `data-dictionary.md` |
| P10-DATA-06 | `prediction_cutoffs` | `0001_schema.sql` | `tests/test_migrations.py` | `data-dictionary.md` |
| P10-DATA-07 | `feature_rows` with the availability proof | `0002_constraints.sql` | `tests/test_migrations.py` | `data-dictionary.md` |
| P10-DATA-08 | `labels` with censoring | `0002_constraints.sql` | `04` | `data-dictionary.md` |
| P10-DATA-09 | `training_runs` frozen configuration | `0002_constraints.sql` | `tests/test_migrations.py` | `data-dictionary.md` |
| P10-DATA-10 | `predictions` citing run, hash, versions | `0002_constraints.sql`, `0003_prevalence_model.sql` | `tests/test_migrations.py` | `data-dictionary.md` |
| P10-DATA-11 | `intervention_scenarios` immutable | `0001_schema.sql` | `tests/test_api_commands.py` | `data-dictionary.md` |
| P10-DATA-12 | `outreach_events` draft only | `0001_schema.sql` | `03` | `data-dictionary.md` |
| P10-MET-01 | churn rate = mature eligible churned / mature eligible | `metrics.py`, `reference_metrics.sql` | `04`, golden | workbook `Censored tail` |
| P10-MET-02 | precision at K | `metrics.py` | `03`, golden | workbook `Capacity` |
| P10-MET-03 | recall at K | `metrics.py` | `03`, golden | workbook `Capacity` |
| P10-MET-04 | average precision (step form) | `metrics.py` | `01` (SQL window functions), `python_side.py`, domain | workbook `Models` |
| P10-MET-05 | Brier score on one population | `metrics.py` | `01`, `02` | workbook `Models` |
| P10-MET-06 | calibration gap with counts | `metrics.py` | `02`, `10` | workbook `Calibration` |
| P10-MET-07 | contact budget = K x cost | `metrics.py::economics` | `03` | workbook `Economics` |
| P10-MET-08 | expected intervention value, hypothetical | `metrics.py::economics` | `03` | workbook `Economics` |
| P10-MET-09 | risk lift at K (not uplift) | `metrics.py` | `03` | workbook `Capacity` |
| P10-MET-10 | feature missingness | `metrics.py` | golden, reference SQL on 84 sets | `bi-package.md` |
| P10-MET-11 | population drift as PSI | `metrics.py::psi` | `07` (SQL `ln()`), `python_side.py` | workbook `Drift` |
| P10-MET-12 | scoring freshness apart from data freshness | `metrics.py::freshness` | reconciliation B (812 h scoring, 1 h data on the cohort) | `uat-evidence.md` |
| P10-FLOW-01 | build point-in-time features (C01) | `api/commands.py`, `world.py` | `tests/test_api_commands.py`, `05` | `business-case.md` |
| P10-FLOW-02 | define label (C02) | `api/commands.py`, `world.py` | `tests/test_api_commands.py`, `04` | `business-case.md` |
| P10-FLOW-03 | split evaluation (C03) | `api/commands.py`, `split.py` | `tests/test_api_commands.py`, `06` | `business-case.md` |
| P10-FLOW-04 | fit preprocessing (C04) | `api/commands.py`, `fitting.py` | `tests/test_fitting.py` | `business-case.md` |
| P10-FLOW-05 | train baseline (C05) | `api/commands.py`, `fitting.py` | `tests/test_fitting.py`, `01` | `business-case.md` |
| P10-FLOW-06 | calibrate model (C06) | `api/commands.py`, `fitting.py` | `tests/test_fitting.py`, `02` | `business-case.md` |
| P10-FLOW-07 | score accounts (C07) | `api/commands.py` | `tests/test_api_commands.py` | `business-case.md` |
| P10-FLOW-08 | prioritize outreach (C08) | `api/commands.py` | `tests/test_api_commands.py`, `03` | `business-case.md` |
| P10-FLOW-09 | simulate economics (C09) | `api/commands.py` | `tests/test_api_commands.py`, `03` | `business-case.md` |
| P10-FLOW-10 | monitor refresh (C10) | `api/commands.py` | `tests/test_api_commands.py`, `07` | `business-case.md` |
| P10-UI-01 | retention overview | `web/src/views/overview.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-02 | cohort explorer | `web/src/views/cohorts.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-03 | feature evidence | `web/src/views/features.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-04 | model comparison | `web/src/views/models.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-05 | calibration lab | `web/src/views/calibration.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-06 | capacity planner | `web/src/views/capacity.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-07 | account explanation | `web/src/views/account.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-08 | outreach queue | `web/src/views/queue.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-09 | monitoring view | `web/src/views/monitoring.tsx` | `web/e2e/journey.spec.ts` | `uat-evidence.md` |
| P10-UI-10 | case study | `web/src/views/case-study.tsx` | `web/e2e/review10.spec.ts` | `uat-evidence.md` |
| P10-TEST-01 | cancellation reason as a feature: detect, recover | `rules.py` | `tests/test_adversarial.py`, `tests/fixtures/adversarial/p10-test-01.json` | `uat-evidence.md` |
| P10-TEST-02 | event arrived after the cutoff: detect, recover | `world.py` | `tests/test_adversarial.py`, `05` | `uat-evidence.md` |
| P10-TEST-03 | same account across the split | `split.py` | `tests/test_adversarial.py`, `06` | `uat-evidence.md` |
| P10-TEST-04 | label windows crossing a boundary | `split.py` | `tests/test_adversarial.py`, `06` | `uat-evidence.md` |
| P10-TEST-05 | preprocessing fitted on everything | `rules.py` | `tests/test_adversarial.py` | `uat-evidence.md` |
| P10-TEST-06 | threshold chosen on test | `rules.py` | `tests/test_adversarial.py` | `uat-evidence.md` |
| P10-TEST-07 | immature outcomes labelled retained | `ingest.py` | `tests/test_adversarial.py`, `04` | `uat-evidence.md` |
| P10-TEST-08 | latent truth as a feature | `rules.py` | `tests/test_adversarial.py` | `uat-evidence.md` |
| P10-TEST-09 | risk mistaken for responsiveness | `api/commands.py` (`RISK_NOT_RESPONSIVENESS`) | `tests/test_adversarial.py` | `uat-evidence.md` |
| P10-TEST-10 | capacity above the population | `rules.py` | `tests/test_adversarial.py`, `03` | `uat-evidence.md` |
| P10-TEST-11 | calibration judged on its own rows | `rules.py` | `tests/test_adversarial.py`, `02` | `uat-evidence.md` |
| P10-TEST-12 | the fit depends on no identifier and no row order (reinterpreted, D-09 R10-10) | `fitting.py` | `tests/test_generator.py::test_r10_10_*` | `technical-case-study.md` |
| P10-ART-01 | business case | `docs/business-case.md` | `tests/test_artifacts.py` | this package |
| P10-ART-02 | requirements and traceability | `docs/requirements.md` | `tests/test_artifacts.py::test_requirements_trace_every_requirement_family` | this package |
| P10-ART-03 | data dictionary and ERD | `docs/data-dictionary.md`, `docs/erd.md` | `tests/test_artifacts.py::test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations` | this package |
| P10-ART-04 | SQL investigations with reconciled totals | `data/sql/analysis/` | `tests/test_artifacts.py`, `run_all.py` (393 rows) | `docs/sql-analysis.md` |
| P10-ART-05 | formula-driven analyst workbook | `artifacts/build_workbook.py` | LibreOffice recalculation, `Checks!B2` | `docs/workbook.md` |
| P10-ART-06 | BI package | `artifacts/bi/`, `data/sql/analysis/bi_*.sql` | `tests/test_artifacts.py` | `docs/bi-package.md` |
| P10-ART-07 | executive memo | `docs/executive-memo.md` | `tests/test_artifacts.py` | this package |
| P10-ART-08 | UAT evidence | `docs/uat-evidence.md` | `tests/test_artifacts.py` | this package |
| P10-ART-09 | technical case study | `docs/technical-case-study.md` | `tests/test_artifacts.py` | this package |
| P10-ART-10 | release package | `docs/release-package.md`, `artifacts/CHECKSUMS.txt` | `sha256sum -c`, `tests/test_artifacts.py` | this package |
| P10-REL-05 | backend acceptance suite on a transient PostgreSQL in CI | `../../.github/workflows/retentionlab-ci.yml` | the CI run recorded in `../../docs/program/release-manifest.json` | `release-package.md` |
| P10-REL-06 | verified backend execution vs browser-only simulated actions | wording on every route | `web/e2e/journey.spec.ts` | `release-package.md` |
| P10-REL-08 | durable outputs with checksums and code revision | `artifacts/CHECKSUMS.txt` | `tests/test_artifacts.py::test_checksums_file_matches_files_and_the_release_package_table` | `release-package.md` |
| P10-REL-23 | rollback to the preceding known-good artifact | release manifest `rollback_commit_unified_portfolio` | not executed | `release-package.md` |

## 5. Deferred and open (stated, not hidden)

* **No randomised experiment exists.** P10-DOMAIN-06 asks for a separate design; `executive-memo.md` gives one with planning arithmetic. It is a design, not a result.
* **The by-construction margin.** Until the model is evaluated on data it did not shape, its margins over the baselines are not evidence of anything about real accounts (D-G02).
* **Four features only** (D-G07): eight registered fields are refused; the brief's "about twenty" is not met.
* **Platt calibration** was fitted on 289 rows from one cutoff and made the test result worse; refitting after seeing test outcomes was rejected as an outcome-informed change (D-09 R10-08).
* **Cursors** are not bound to a `dataset_version`; **no monitoring history table**; **no non-UTC zones**; **not benchmarked at 10,000 accounts** (README gaps).
* **Excel and Power BI Desktop were not run** for the workbook and the BI package; LibreOffice recalculated the workbook; DAX is pseudocode (`bi-package.md`).
* **Tests that skip.** `tests/test_artifacts.py` skips its database re-run, with a printed reason, unless `ARTIFACTS_DATABASE_URL` and `ARTIFACTS_GOLDEN_DATABASE_URL` name scratch databases `artifacts10_*`; its LibreOffice tests skip where `soffice` is missing, and the provenance test skips where the commit `ce96e65` is absent. The CI workflow provisions all three so none skips there.
