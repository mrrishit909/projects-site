# ChangeWorks: user acceptance evidence (P09-ART-08)

**Synthetic data only.** Dataset `cw-20261026-20261026` (generator `dataset_hash` `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`), code revision `29948f9` (`29948f92f0c3839f070e4b6499b99f3810d1361b`), as-of 2026-10-05T00:00:00Z. Each scenario below is a business question of the decision **which transformation initiative should be funded, and how will success be established?**, with the expected answer (from the contract, the golden fixture or the generator's designed relationship), the actual observation (what the SQL analysis of this package found on the loaded snapshot, reconciled with the Python domain and the reference SQL) and the disposition. Figures are plan estimates or observations of one synthetic draw; none is a benefit to a real organisation.

**How to read it without installing anything:** the scenario table (section 1) is self-contained; the defect disposition (section 2) lists the review R9 findings and their fixes; section 3 lists the routes and screenshots of the public site and the runs that produced them. This document was **created by this pass** (it did not exist in `apps/changeworks/docs/` before).

## 1. Business scenarios
| # | Scenario (role) | Expected answer | Actual observation (this package) | Disposition |
|---|---|---|---|---|
| S1 | The known answer (financial analyst): cost 1,000 at 0, inflows 600 at 1 and 2, 10 % annual | NPV 5000/121 = 41.32; simple payback 2 (1.6667); discounted 2 (1.9167); 800 hours excluded (P09-GOLD-01) | 41.32, `5000/121`, 2 / 1.6667, 2 / 1.9167, 800.00 hours (investigation 10; equal to `expected.json`) | pass |
| S2 | What is the portfolio worth (transformation analyst), `scn-025` | the NPV counted once beside the plain sum (D-09 R9-02; DR-02: 1,243,149.05 and 1,438,382.25) | attributable 1,243,149.05, sum 1,438,382.25, double-counted PV 195,233.20 (investigation 02) | pass |
| S3 | Two initiatives claim the same capacity (sponsor) | residual 207,146.32 and hours residual 5,974.80 on `src-fin-ap-shared-team`, periods 3..12; a proposal needs an explanation (DR-02, INJ-02) | 207,146.32 and 5,974.80 on that key, periods 3..12, `init-001` and `init-002`; 5 scenarios with a money residual, 7 with an hours residual (investigation 03) | pass |
| S4 | Capacity only (financial analyst): `init-009` | 2,920.48 hours not converted; cash 0.00; NPV -761,535.73; no payback (DR-01, INJ-01) | 2,920.48 hours, 0.00 cash entering, NPV -761,535.73, `NOT_RECOVERED` (investigations 01, 02, 04) | pass |
| S5 | An initiative that never pays back (sponsor): `init-015` | both paybacks null in 8 scenarios; 0.531465 / 0.620043 by ramp (DR-03, INJ-08) | null with `NOT_RECOVERED` in all 8; 0.531465 in `scn-015`, `scn-018`, `scn-025`, `scn-026`; 0.620043 in the other four (investigation 04) | pass; also found: five more initiatives never pay back in any scenario (`init-006`, `init-009`, `init-019`, `init-021`, `init-022`) |
| S6 | Costs counted once (financial analyst) | recurring costs expanded over `[start, end)`; a one-time cost in one period; a repeat refused (INJ-11) | 144 recurring items to 915 rows; 72 adjacent boundaries carried once; 0 repeated one-time keys; `c-0042` stored once in period 1 (investigation 05) | pass |
| S7 | Are benefits arriving (business analyst) | realisation within a type on matured periods; trend beside; observed not attributed (DR-06: `init-008` 0.975795, trend share 0.848744) | 0.975795, trend 143,941.18 of 169,593.13 observed (0.848744), 25,651.95 above trend; 31 comparisons, 20 unobserved matured rows listed (investigation 06) | pass |
| S8 | Costs against baseline (financial analyst) | actual minus approved planned cost over the matured window; null without actuals (D-P9-05) | 13 variances, 7 over, 6 under, net +253,802.33; 11 null with a reason (investigation 06) | pass |
| S9 | Adoption versus training (business analyst) | adoption 0.532881, training 0.888443, denominators kept, lags 4, 4, 5, 5, 6 (DR-07, INJ-05) | 3,063 / 5,748 = 0.532881; 6,427 / 7,234 = 0.888443; 0.963778 on the 11 with both; lags 4,4,5,5,6; six below half (investigation 07) | pass |
| S10 | The forecast kept (sponsor) | 745,800.06 -> 598,900.05 -> 534,207.54, original preserved (DR-04, INJ-06) | the three totals, latest minus original -211,592.52, every version covers the original periods; misses 0.672385 / 0.678912 and 0.849750 / 0.824670 / 0.792000 (investigation 08) | pass |
| S11 | Can the roadmap be delivered (PMO) | no cycle; the EV-07 edge closes init-001 -> init-004 -> init-001; `res-03` at capacity in 12..16, three requests refused; three `DEPLOYMENT_BEFORE_FEASIBLE_START` (DR-05, INJ-07, INJ-09, R9-06, R9-08) | 0 cycles in 402 paths; the edge closes the cycle through `d-003`; `res-03` 2.00 of 2.00 in periods 12..16; three 0.50 requests would reach 2.50; `init-018`, `init-019`, `init-020` (4, 5, 2 periods early) (investigation 09) | pass; also found: `res-02` at capacity in 18 periods (0..17) |
| S12 | What to propose (decision owner) | a stated screen over the plan estimates with observed evidence beside it (P09-GOAL-01) | 18 carry a cash case, 6 wait; option D (10 initiatives) 2,876,982.64; option B breaks 4 dependencies (investigation 11; `executive-memo.md`) | pass (a judgement, labelled) |
| S13 | The analyst workbook checks itself (financial analyst) | `Checks!B2` TRUE after recalculation; the switch is live | TRUE as delivered (`scn-025`, attributable 1,243,149.05) and with the switch on `scn-001`, `scn-006`, `scn-015`, `scn-030` (`test_the_scenario_switch_is_live_and_the_check_cell_stays_true`) | pass (LibreOffice only; Excel not run) |

Every actual observation above is a row or a reconciled figure of `artifacts/analysis-results.json`; the 763 reconciliation rows are all equal.

## 2. Defect disposition (review R9, contract D-09)
The disproof review (assignment A-074) found 14 defects, fixed as R9-01..R9-22 by A-078 and accepted at `29948f9` (CI run 40474351325 green on both modes). This package re-checked what its SQL can see:
| Id | Defect | Fix (D-09) | Re-checked by this package |
|---|---|---|---|
| R9-01 | a proposed scenario's figures could move with later rows | figures as of `created_at`, snapshot hash, sealed sets | the analysis applies the `recorded_at <= created_at` rule and the pins; no row of the world carries a `recorded_at` |
| R9-02 | the portfolio NPV counted the shared claim twice | attributable NPV beside the sum | yes: 1,243,149.05 vs 1,438,382.25 in `scn-025`; all 30 scenarios equal the domain |
| R9-03 | hours overlap not reported | hours residual | yes: 5,974.80 in `scn-025`, 7 scenarios |
| R9-04 | blank evidence references accepted | stripped, non-blank evidence | yes: the analysis treats a blank evidence reference as none |
| R9-05 | one cost key of two kinds | `COST_KEY_BASIS_CONFLICT` | yes: 0 keys of two kinds (investigation 05) |
| R9-06 | deployment before the feasible start unreported | `DEPLOYMENT_BEFORE_FEASIBLE_START` | yes: the three initiatives (investigation 09) |
| R9-07 | sums of rounded rows | exact sums rounded once | yes: every analysis total is an exact sum rounded once |
| R9-08 | DR-05 periods stated as 14..16 | computed periods 12..16 | yes: 12..16 |
| R9-09 | DR-03 ratio without its scenario | each ratio names its scenarios | yes: 0.531465 / 0.620043 by scenario |
| R9-10 | a partial revision accepted | `REVISION_PERIODS_INCOMPLETE` | yes: every version covers the original periods |
| R9-11 | observation dates and late records | `recorded_at`, `late_recorded` | the analysis applies `recorded_at <= as-of`; none is late in the world |
| R9-12 | payback at the first crossing (0 for a series with no investment) | last crossing, `NO_INVESTMENT` / `NOT_RECOVERED` / `NO_FLOWS` | yes: 156 recovered, 54 `NOT_RECOVERED`, first and last crossing never differ in this world |
| R9-13 | partial trend coverage | `PARTIAL_TREND_COVERAGE` | yes: complete coverage in all 31 comparisons |
| R9-14 | period start after the 28th | `PERIOD_START_INVALID`, CHECK | not re-checked (no such row) |
| R9-15 | test counts | true counts | the suite count of this pass is in `release-package.md` |
| R9-16..R9-18 | training vs adoption wording, window wording, outcome-informed choices | site and case-study text | the case study's figures were compared (`release-package.md`, main-portfolio metadata) |
| R9-19..R9-22 | not-built list, SQL NPV bound, contrast, small rules | D-09 | the NPV bound: the reference's 6-place NPV is within 0.000001 of the exact rational for every `scn-025` initiative (reconciliation B) |

## 3. Routes, screenshots and runs
The public site has twelve routes: `/`, `/portfolio/`, `/baseline/`, `/business-case/`, `/sensitivity/`, `/roadmap/`, `/impact/`, `/readiness/`, `/benefits/`, `/forecast/`, `/evidence/`, `/case-study/`. The screenshot set (`web/evidence/`, not committed) has 65 files: `home`, `portfolio`, `baseline`, `business-case`, `business-case-golden`, `sensitivity`, `roadmap`, `impact`, `readiness`, `benefits`, `forecast`, `evidence`, `case-study`, each at 360, 768, 1280 and 1920 px and as `-zoom200.png`; `web/evidence/index.json` records no horizontal overflow on any of the 65. The local Playwright report in `web/evidence/playwright-report.json` (started 2026-10-27T08:30:12Z, run by the coordinator, not by this pass) records 81 expected, 0 unexpected, 0 flaky, 0 skipped. Browser journeys cited by the requirements: e2e "portfolio: every figure equals the Python domain's, class columns apart, nothing summed across classes", e2e "business case: the cash-flow table beside its assumption versions, NPV and both paybacks, the golden case recomputed", e2e "forecast: original, revisions and observed, with the original kept".

This pass did **not** run `npm run e2e` and did not fetch the live site. Hosted runs from the ledgers: CI 40474351325 (both modes green on `29948f9`); live verification 40474949237 (verified 2026-10-27T08:41:13Z, live code_sha `29948f9...`, portfolio release 8b9bcd3); earlier: 40447123155, 40450783026, 40464667889, 40456429847. A hosted run of `tests/test_artifacts.py`: pending (the package is not committed).

## Erratum recorded by the coordinator (2026-10-27)

* The hosted run of this package (CI run 40483802100 on 273a078) failed one pre-existing application test,
  `tests/test_api_commands.py::test_c03_builds_a_new_scenario_and_expands_recurring_costs_explicitly`, and no artifact test.
  Its assertion assumed the seeded cost `c-101` is the first row of `expanded_costs`, but the API orders the rows by `cost_id` and the
  new cost's id is server-generated hex, so about one run in sixteen sorted the new id before `c-101`. The assertion now finds the
  new id and checks the same rows (periods 1 and 2 at 50.00, `c-101` at period 0 for 1,000.00, rows ordered by cost id then period).
  The published code 29948f9 is unchanged; the provenance test excludes that one test file and says why.
