# ChangeWorks: requirements and traceability (P09-ART-02)

**Synthetic data only.** Dataset `cw-20261026-20261026` (generator `dataset_hash` `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`), contract v1 (`docs/contracts.md` D-01..D-09), code revision `29948f9` (`29948f92f0c3839f070e4b6499b99f3810d1361b`). The organising question of every requirement: **which transformation initiative should be funded, and how will success be established?** (P09-GOAL-01). Figures quoted below are observed in one synthetic draw or are plan estimates (constructed); none is a hypothetical benefit to a real organisation.

**How to read it without installing anything:** section 1 lists the functional requirements by workflow and metric, section 2 the non-functional ones, section 3 the user stories with acceptance criteria, section 4 traces every requirement family to the code, the tests and the run that verified it, with a status: **verified** (a hosted run or the run of this package executed the named test), **deferred** (accepted as a gap in D-06 / D-09, not built), **not_checked** (no check exists), **pending** (waiting for a run that has not happened). Test names in backticks are functions in `tests/`.

## 1. Functional requirements
| Id | Requirement | Contract | Implementation |
|---|---|---|---|
| FR-01 (P09-FLOW-01) | Establish a baseline from measured evidence; approval freezes it; a correction is a new version with a reason | D-02, D-06 | C01 `establish-baseline` (`api/commands.py`), `process_baselines`, `baseline_approvals`, trigger `cw_forbid_mutation` |
| FR-02 (P09-FLOW-02) | Assess an opportunity with explicit criteria, weights and rationale; an exact versioned score | D-06 | C02 `assess-opportunity`, `opportunity_scores` |
| FR-03 (P09-FLOW-03) | Build cash flows: a new scenario version, recurring costs expanded over half-open ranges, the four classes, NPV and both paybacks | D-01, D-09 R9-01, R9-12 | C03 `build-cash-flows`, `domain/changeworks/cashflow.py`, `expanded_costs` |
| FR-04 (P09-FLOW-04) | Map operating changes to synthetic stakeholder groups | D-03 | C04 `map-impacts`, `impact_mappings` |
| FR-05 (P09-FLOW-05) | Assess readiness on five dimensions with weights | D-03 | C05 `assess-readiness`, `readiness_assessments` |
| FR-06 (P09-FLOW-06) | Plan the roadmap: feasible starts, delays, cycles refused, allocations up to capacity | D-03, D-P9-08, D-P9-15 | C06 `plan-roadmap`, `domain/changeworks/roadmap.py` |
| FR-07 (P09-FLOW-07) | Select a scenario as `proposed` with its comparison; a residual must be explained; never `funded` | D-03, D-09 R9-03 | C07 `select-scenario`, `snapshot.py` |
| FR-08 (P09-FLOW-08) | Record adoption with its denominator and eligibility rule; training a separate series | D-03 | C08 `record-adoption` |
| FR-09 (P09-FLOW-09) | Track benefits within one type on matured periods, the trend beside the raw change, observed not attributed | D-02 | C09 `track-benefits`, `measures.py` |
| FR-10 (P09-FLOW-10) | Revise a forecast as version n+1, never overwriting, covering every original period | D-02, R9-10 | C10 `revise-forecast` |
| FR-11 (P09-MET-01..12) | The twelve metrics: net cash flow, NPV, discounted payback (and simple), capacity released, adoption, benefit realisation, cost variance, readiness, risk exposure, dependency delay, training completion, double-count residual | D-01..D-03, D-09 | `domain/changeworks/metrics.py`; `data/sql/reference_metrics.sql`; this package's `data/sql/analysis/` |
| FR-12 (P09-DATA-01..12) | The twelve entities with their fields, types and keys | D-01..D-05 | `data/sql/migrations/0001_schema.sql`..`0003_review9.sql`; `data-dictionary.md` |
| FR-13 (P09-ART-01..10) | The artifact package: business case, requirements, dictionary, SQL analysis, workbook, BI, memo, UAT, technical case study, release package | this package | `docs/`, `data/sql/analysis/`, `artifacts/` |

## 2. Non-functional requirements
| Id | Requirement | How it is met | Status |
|---|---|---|---|
| NFR-01 | Exact arithmetic: no float in a published figure; money Decimal, NPV an exact rational | `fractions.Fraction` in the domain; NUMERIC in SQL with one division; `npv_exact` beside every NPV in the analysis | verified (`test_no_float_anywhere_in_inputs_or_outputs`, `test_sql_npv_is_within_the_documented_tolerance_of_the_exact_rational`, `test_the_analysis_npv_exact_rationals_equal_the_domains`) |
| NFR-02 | Append-only history: approved baselines, assumption and forecast versions, scenarios | triggers in `0002_constraints.sql`, `0003_review9.sql` | verified (`test_append_only_tables_refuse_update_delete_and_truncate`, `test_a_scenario_never_changes_except_draft_to_proposed_once_and_never_to_funded`) |
| NFR-03 | Locale-independent ordering of every analysis result | `COLLATE "C"`, numeric or boolean keys | verified (`test_every_sql_file_has_its_header_and_the_numbered_files_read_only`) |
| NFR-04 | Scratch-database safety: the analysis never resets the shared database | `prepare_snapshot.assert_scratch` refuses any name not `artifacts09_*` | verified (`test_scratch_guard_refuses_a_non_scratch_database`) |
| NFR-05 | Reproducible on hosted compute (P09-GOAL-05, P09-REL-05) | `.github/workflows/changeworks-ci.yml`: postgres:16 service, LibreOffice Calc, scratch databases, full history, the junit **no-skip gate** (`skipped="0"`) | verified for the suite at `29948f9` (run 40474351325); the artifact tests on a hosted runner: **pending** (this package is not committed) |
| NFR-06 | No credentials, no real personal data in any export | synthetic labels (`LABEL_NOT_SYNTHETIC`), document scan | verified (`test_no_credentials_or_secrets_in_the_artifact_documents_and_files`) |
| NFR-07 | Accessible headings, labels and tables (P09-ART-xx-R13) | Markdown headings and tables; workbook header rows; mermaid diagrams with text lists | verified by reading; no automated accessibility check of the documents (**not_checked**) |
| NFR-08 | Binary outputs regenerated on hosted compute and kept in GitHub releases (P09-ART-xx-R06) | the workbook is regenerable (`build_workbook.py --recalc`); checksums in `artifacts/CHECKSUMS.txt` | the workbook here was built in the session container, not on a hosted runner; not attached to a GitHub release: **pending** |

## 3. User stories and acceptance criteria
| Story | As a ... I want ... so that ... | Acceptance criteria (checked by) |
|---|---|---|
| US-01 | As a financial analyst I want the NPV of each initiative as an exact rational beside the 2-place figure, so that the business case can be audited | Golden NPV 5000/121 = 41.32, simple payback 2 (1.6667), discounted 2 (1.9167) (`test_spec_sentence_p09_gold_01`, `test_golden_known_answer_in_sql_equals_expected_json_the_domain_and_the_hand_figures`) |
| US-02 | As a transformation analyst I want the portfolio NPV counted once, so that a shared benefit does not inflate the case | `scn-025` attributable 1,243,149.05 beside the sum 1,438,382.25 (`test_the_portfolio_npv_counts_the_shared_claim_once_and_shows_the_sum_beside_it`, `test_headline_numbers_of_the_documents_are_the_stored_ones`) |
| US-03 | As a sponsor I want a residual explained before a proposal, so that nobody proposes a double count | C07 422 `DOUBLE_COUNT_UNEXPLAINED` (`test_c07_proposes_only_never_funds_and_needs_the_residual_explained`, `test_02_detect_the_overlap_is_counted_once_listed_and_blocks_the_proposal_until_explained`) |
| US-04 | As a business analyst I want adoption kept apart from training with both denominators | pooled 0.532881 vs 0.888443, 0.963778 on the common 11 (`test_05_detect_training_is_not_adoption_and_a_training_count_cannot_be_recorded_as_adoption`, `test_stored_reference_figures_equal_the_domain`) |
| US-05 | As a financial analyst I want hours never added to dollars without a conversion | `init-009` 2,920.48 hours, cash 0.00 (`test_01_detect_hours_claimed_as_cash_without_a_staffing_change_are_refused_and_hours_stay_out_of_the_cash_flow`, `test_designed_relationships_and_defects_are_present_in_the_results`) |
| US-06 | As a sponsor I want the original forecast kept when it is revised | `init-003` 745,800.06, 598,900.05, 534,207.54 (`test_06_detect_the_original_forecast_cannot_be_overwritten_by_data_command_or_sql`, `test_dr04_a_forecast_revised_twice_after_a_missed_target`) |
| US-07 | As a PMO lead I want the roadmap to refuse cycles and over-allocation | EV-07 cycle, `res-03` at capacity in 12..16 (`test_07_detect_the_closing_edge_is_refused_with_the_cycle_listed_and_the_rest_stays`, `test_09_detect_the_crossing_allocation_is_refused_with_its_periods_and_exactly_at_capacity_is_allowed`) |
| US-08 | As a financial analyst I want a spreadsheet I can change and that checks itself | `Checks!B2` TRUE after LibreOffice recalculation, for every scenario tried (`test_libreoffice_headless_recalculation_of_a_copy_as_delivered`, `test_the_scenario_switch_is_live_and_the_check_cell_stays_true`) |
| US-09 | As an analytics engineer I want a BI model that withholds nothing silently | every empty measure carries a status and a scope (`test_bi_measures_recomputed_from_the_csv_files_equal_the_stored_values_and_the_domain`) |
| US-10 | As a decision owner I want a recommendation with options, uncertainty and limits | `executive-memo.md` (`test_executive_memo_quotes_the_evidence_options_and_the_caveats`) |

## 4. Traceability
| Requirement family | Code | Tests | Run / evidence | Status |
|---|---|---|---|---|
| P09-GOAL-01..15 | the whole app; README | all suites | CI 40474351325 (both modes, `29948f9`); live check 40474949237 | verified (GOAL-07/08 model ids: recorded in the delegation ledger as "not observable") |
| P09-DOMAIN-01 (four classes) | `cashflow.py` | `test_avoided_cost_enters_only_with_cash_realisation_and_evidence`, `test_capacity_conversion_pinned_else_latest_needs_staffing_evidence` | CI 40474351325 | verified |
| P09-DOMAIN-02 (immutable baseline) | `0002_constraints.sql` | `test_an_approved_baseline_is_frozen_and_only_approvals_name_it` | CI 40474351325 | verified |
| P09-DOMAIN-03 (ramps and lags) | `cashflow.py` | `test_ramp_is_indexed_from_each_rows_own_starts_period_and_the_last_value_is_held` | CI 40474351325 | verified |
| P09-DOMAIN-04 (no double count) | `cashflow.double_count` | `test_double_count_residual_at_the_largest_claim`, `test_double_count_ties_three_claimants_same_initiative_repeats_and_other_periods` | CI 40474351325 | verified |
| P09-DOMAIN-05 (uncertainty as ranges and labels) | labels only ("estimate", "assessment, not a probability") | `test_the_documents_name_the_real_entities_metrics_and_commands_and_keep_result_kinds_apart` | this package | **deferred**: declared uncertainty ranges are not built (D-09 R9-19, "Not built") |
| P09-DOMAIN-06 (workbook and recommendation) | `artifacts/build_workbook.py`, `docs/executive-memo.md` | `test_cached_values_equal_the_domain_recomputed_here`, `test_executive_memo_quotes_the_evidence_options_and_the_caveats` | this package's local run | verified locally; hosted run **pending** |
| P09-GOLD-01..11 | `tests/fixtures/golden/`, `tests/reference_check.py` | `test_spec_sentence_p09_gold_01`, `test_variant_equals_expected_json_leaf_for_leaf`, `test_empty_population_counts_ratios_and_npv_are_null_not_zero` | `python -I tests/reference_check.py` ALL OK (3,156 checks) | verified |
| P09-DATA-01..12 | migrations, `data/seed.py`, `data/generate.py` | `test_every_table_exists_and_instants_are_timestamptz`, `test_row_counts_are_the_briefs`, `test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations` | CI 40474351325 | verified |
| P09-MET-01 net cash flow | `cashflow.py`; SQL `cw_flow` | `test_sql_equals_expected_for_every_fixture_leaf_by_leaf`; analysis leaves (48,476) | this package: 763 reconciliation rows | verified |
| P09-MET-02 NPV | `cashflow.py`; SQL `cw_dnum`, `cw_exact` | `test_sql_npv_bound_holds_on_the_published_world_36_monthly_periods`, `test_the_analysis_npv_exact_rationals_equal_the_domains` | CI; this package | verified |
| P09-MET-03 payback | `cashflow.payback` | `test_payback_is_the_last_crossing_and_a_series_that_ends_negative_has_none` | CI | verified |
| P09-MET-04 capacity released | `measures.capacity_released` | `test_capacity_released_reasons_and_decimal_targets` | CI | verified |
| P09-MET-05 adoption | `people.adoption` | `test_adoption_and_training_use_the_latest_record_at_or_before_as_of` | CI | verified |
| P09-MET-06 benefit realisation | `measures.benefit_realization` | `test_realization_unobserved_rows_are_listed_never_counted_as_zero_and_the_latest_observation_wins` | CI | verified |
| P09-MET-07 cost variance | `measures.cost_variance` | `test_cost_variance_matured_window_and_its_nulls` | CI | verified |
| P09-MET-08 readiness | `people.readiness` | `test_readiness_latest_per_dimension_weights_ties_and_incomplete_sets` | CI | verified (not in this package's SQL; reference SQL and domain only) |
| P09-MET-09 risk exposure | `people.risk` | `test_risk_exposure_probability_zero_and_one_are_inside_and_no_items_is_null` | CI | verified |
| P09-MET-10 dependency delay | `roadmap.feasible_starts` | `test_feasible_start_chain_ss_fs_binding_dependency_and_no_negative_delay` | CI | verified |
| P09-MET-11 training completion | `people.training` | `test_zero_eligible_is_null_and_no_records_is_null` | CI | verified |
| P09-MET-12 double-count residual | `cashflow.double_count` | `test_dr02_two_initiatives_claim_the_same_capacity` | CI | verified |
| P09-FLOW-01..10 | `api/commands.py` C01..C10 | `test_c01_creates_a_baseline_from_evidence_only_with_the_actor_and_the_servers_time` .. `test_c10_creates_version_n_plus_1_and_never_touches_the_original` | CI 40474351325 | verified |
| P09-UI-01..10 | `web/src/` (12 routes) | e2e "portfolio: every figure equals the Python domain's, class columns apart, nothing summed across classes", "business case: the cash-flow table beside its assumption versions, NPV and both paybacks, the golden case recomputed", "roadmap: bars with dependency arrows and resource lanes; keyboard navigation; simulated edits refused with their reasons; reset on reload", "forecast: original, revisions and observed, with the original kept", "case study: findings are computed from the data" | CI 40474351325 Mode B; local evidence 81 expected / 0 unexpected | verified (this package did not run `npm run e2e`) |
| P09-TEST-01..12 | `tests/test_adversarial.py` | `test_01_detect_hours_claimed_as_cash_without_a_staffing_change_are_refused_and_hours_stay_out_of_the_cash_flow` .. `test_12_recover_evidence_of_a_removed_budget_line_moves_it_into_the_cash_flow` | CI 40474351325 | verified |
| P09-ART-01..10 | `docs/`, `data/sql/analysis/`, `artifacts/` | `tests/test_artifacts.py` | this package's local run (pytest with the scratch URLs, LibreOffice) | verified locally; hosted run **pending** |
| P09-REL-01..24 | `docs/program/release-manifest.json` | live check | release 8b9bcd3, rollback d58209f, live run 40474949237 (verified 2026-10-27T08:41:13Z) | verified for the site; this package's release integration **pending** |
| P09-WORK | the delegation and verification ledgers | n/a | `docs/program/delegation-ledger.jsonl` (A-081 dispatched for this package) | verified by the coordinator, not by this package |

## 5. Gaps stated plainly
* **Deferred** (D-06, D-09 R9-19): resource levelling that moves starts; declared uncertainty ranges; the proposal transition under a database trigger; Excel and Power BI execution (`workbook.md`, `bi-package.md`).
* **not_checked**: automated accessibility checks of these Markdown documents; Excel's evaluation of the workbook; the DAX of `bi-package.md`.
* **pending**: a hosted run of `tests/test_artifacts.py` (the CI workflow provisions LibreOffice, `artifacts09_snapshot` / `artifacts09_golden` and the no-skip gate; the package is not committed by this pass); attaching the workbook and the BI files to a GitHub release.
* The reconciliation behind every figure: 763 rows, all equal (`sql-analysis.md` section 13).
