# Executive memo: which transformation initiative should be funded, and how will success be established? (P09-ART-07)

**Synthetic data throughout:** one transformation portfolio in a generated world (seed 20261026, dataset `cw-20261026-20261026`, generator hash `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`, code revision `29948f9`, as-of 2026-10-05T00:00:00Z). Nothing here is a claim about a real organisation, and **nothing is funded**: ChangeWorks can at most mark a scenario `proposed` (C07); the decision to fund is taken outside it.
Labels: **OBSERVED** = recorded as having happened in this synthetic world by the as-of (actual costs, adoption and training records, benefit observations); **SIMULATED** = a plan estimate of a scenario (every NPV, payback and benefit total) or a constructed option; **HYPOTHETICAL** = a benefit to a real organisation, which this memo does not claim.
How to read it without installing anything: the decision first, then the evidence table, the options, the uncertainty and the limits; money is USD with 2 places, proportions have 6 places, paybacks are calendar-month periods, and every figure names its scenario, quoted from `sql-analysis.md`.

## Decision
**Propose (not fund) the ten initiatives that carry a cash case and need no initiative that does not: `init-001`, `init-002`, `init-003`, `init-004`, `init-007`, `init-008`, `init-012`, `init-013`, `init-014`, `init-016`** (option D below), built as a new scenario on the assumptions of `scn-025` (C03 `build-cash-flows`) and proposed with C07 `select-scenario` once the shared-capacity residual of `init-001` / `init-002` is explained in writing.
1. **Why these ten (SIMULATED).** In `scn-025` each has a positive NPV and recovers its investment inside the window on both the simple and the discounted basis, and none depends, directly or through a chain, on an initiative that does not. Together: attributable NPV **2,876,982.64** on **11,779,550.00** of planned costs, against **1,243,149.05** on 25,914,200.00 for all 24 initiatives as stored in `scn-025` (option A).
2. **Hold six initiatives until their benefits can enter the cash flow.** `init-006`, `init-009`, `init-015`, `init-019`, `init-021`, `init-022` never pay back in any of the 8 or 9 scenarios that contain them. Four have **no benefit that enters the cash flow at all**: their avoided cost has no evidence that a budget line was removed and their capacity hours no staffing change (`init-009` plans only 2,920.48 hours: NPV -761,535.73). The case for each is evidence, not arithmetic: a finance evidence reference for a removed budget line, or a `capacity_hourly_rate` with a `staffing_change_evidence_ref`. `init-015` returns **0.531465** of its cost (0.620043 under the earlier ramp) and `init-022` 0.942934.
3. **Re-plan before proposing the other eight carriers.** `init-005`, `init-010`, `init-011`, `init-017`, `init-018`, `init-020`, `init-023`, `init-024` carry a cash case but depend (directly or through a chain) on a held initiative (directly: `init-010` and `init-017` on `init-009`, `init-018` on `init-019`, `init-023` on `init-015`; through `init-023` or `init-010`: `init-005`, `init-011`, `init-020`, `init-024`); two of them (`init-018`, `init-020`) also book benefits before their feasible start, as does the held `init-019`. Remove or replace those dependencies in C06 `plan-roadmap` first; then they can be added in a later scenario.
4. **Inside the ten, gate three on evidence (OBSERVED).** `init-003` has realised **0.667307** of its planned cash on matured periods, adoption is **0.232258** with 0.977918 trained, and its forecast was cut twice (745,800.06 to 598,900.05 to 534,207.54); `init-014` realises 0.747375 with adoption 0.229508; `init-016` realises 0.877626 with adoption 0.174334. Propose them with a stage gate (below), not as unconditional.

This is a judgement written down so that it can be changed; the screen (positive NPV, both paybacks found, no held prerequisite) is investigation 11's stated rule.

## How success will be established (set before the proposal)
For each proposed initiative, agreed with its sponsor and recorded with the proposal:
* **Benefit realisation within each benefit type** on matured periods (C09 `track-benefits`), with the baseline trend beside the raw change and the label "observed, not attributed". A gate is passed when, for two consecutive matured periods, observed comparable benefit over planned comparable benefit is at or above a threshold the sponsor states in the proposal (this memo suggests 0.85 for cash; that number is a proposal parameter, not a finding).
* **Adoption over its eligible population** (C08), on the initiative's eligibility rule version, never replaced by training completion. The world's evidence is that half adoption comes 4 to 6 months after 90 % training (DR-07), so the first adoption gate should sit no earlier than six months after training passes 90 %.
* **Cost variance against the approved baseline** on the matured window (actual minus planned, null while there are no actuals).
* **Forecast discipline**: revisions are new versions (C10) and the original stays beside them; a revision after a miss of more than 10 % is reported, as `init-003`'s two were.
* **Capacity becomes money only with staffing evidence**; until then it is reported in hours and never as a payroll reduction.
* **Counted once**: the money residual (207,146.32 in `scn-025`) and the hours residual (5,974.80) on `src-fin-ap-shared-team` are explained in writing in the C07 request, and the attributable NPV is the figure reported.

## Evidence
| Question | Figure | Population and basis | Kind | Where |
|---|---|---|---|---|
| What is the portfolio worth? | sum of NPVs 1,438,382.25; double-counted PV 195,233.20; attributable **1,243,149.05** | `scn-025`, 24 initiatives, 0.006434 per month, 36 periods | SIMULATED | investigation 02 |
| What is claimed twice? | residual **207,146.32** (hours 5,974.80) on `src-fin-ap-shared-team`, periods 3..12 | `init-001` and `init-002`; 5 scenarios carry a money residual, 7 an hours residual | SIMULATED | investigation 03 |
| Which classes enter the cash flow? | costs 25,914,200.00; cash 15,288,067.20; revenue 6,074,000.13; avoided realised 5,516,433.35; capacity converted 1,774,010.55; beside: 4,025,383.47 and 145,045.62 hours | `scn-025` | SIMULATED | investigation 01 |
| What never pays back? | 6 initiatives `NOT_RECOVERED` in every scenario; 54 of 210 series in all | all 30 scenarios | SIMULATED | investigation 04 |
| Which options are deliverable? | A 1,243,149.05; B 4,560,340.34 (breaks 4 dependencies); C 2,177,441.56; D **2,876,982.64** | `scn-025` NPVs, constructed except A | SIMULATED | investigation 11 |
| Is adoption following training? | adoption **0.532881** (3,063 of 5,748) vs training **0.888443** (6,427 of 7,234); 0.963778 on the 11 with both | latest record by the as-of | OBSERVED | investigation 07 |
| Are benefits arriving? | 31 comparisons over 150 matured rows; `init-008` 0.975795 of plan of which 0.848744 is trend | matured periods 0..8 | OBSERVED | investigation 06 |
| Are costs on baseline? | 13 with a variance: 7 over, 6 under, net **+253,802.33** | approved baselines, matured window | OBSERVED | investigation 06 |
| Were forecasts kept? | `init-003` 745,800.06 to 598,900.05 to 534,207.54, original preserved | 12 forecast versions, 8 initiatives | OBSERVED | investigation 08 |
| Does the roadmap fit? | 4 delayed (3 to 10 periods); 3 `DEPLOYMENT_BEFORE_FEASIBLE_START`; `res-03` at capacity in periods 12..16; `res-02` in 18 periods | 40 dependencies, 557 allocations | OBSERVED (plan rows) | investigation 09 |
| The golden case | NPV 5000/121 = **41.32**; simple payback 2 (1.6667); discounted 2 (1.9167); attributable -8300/11 = -754.55 | `tests/fixtures/golden` | constructed | investigation 10 |

* **The reconciliation is the evidence that these are the model's figures, not the query's:** 763 rows, all equal, between the analysis SQL, the independent reference SQL (48,476 leaves), the Python domain, the manifests and a plain-Python recomputation from the raw JSON (`sql-analysis.md` section 13).
* **Options are compared on one rate and one set of pins** (those of `scn-025`), because the 30 stored scenarios differ in members, horizon (24 or 36) and rate (0.006434 to 0.009489 per month), and their totals are not comparable as they stand.

## Options
| Option | What the evidence says | What it needs or risks |
|---|---|---|
| **D. The ten carriers that need no held initiative** (recommended) | Attributable NPV 2,876,982.64 on 11,779,550.00; no negative NPV; no prerequisite outside; the shared claim inside it | A new scenario (C03) and a written residual explanation (C07); three members are behind plan on observed evidence and need a stage gate |
| **A. Propose `scn-025` as stored** | 1,243,149.05 on 25,914,200.00; six members never pay back | Proposes 14,134,650.00 more planned costs than D: 4,820,500.00 for the six members that never pay back and the rest for eight carriers tied to them; needs the same residual explanation |
| **B. All 18 carriers** | 4,560,340.34 on 21,093,700.00 | Not deliverable as planned: 4 dependencies lead to held initiatives; the roadmap must change first |
| **C. The 18 carriers and the prerequisites they need** | 2,177,441.56 on 24,262,150.00; three negative members (`init-009`, `init-015`, `init-019`) | Takes on 2,382,898.77 of negative NPV (`init-009`, `init-015`, `init-019`) to keep 1,683,357.70 of NPV of the eight carriers that depend on them; 699,541.08 below D |
| **E. Propose a stored scenario with a higher attributable NPV** (`scn-002` 1,850,194.72 at 12 %, `scn-030` 1,748,559.44 at 10 %) | Different members, rates and horizons; `scn-002` contains `init-006` and a residual of 253,178.85 | Not comparable with A-D; proposing on a total from another rate is the comparison the product warns against |
| **F. Propose nothing until the evidence matures** | Nine periods have matured; adoption lags training by 4 to 6 months | Delays initiatives with observed delivery at or above plan (`init-001` 1.039443, `init-002` 1.030184, `init-004` 1.023305) |

## Uncertainty
* **One draw, designed relationships.** The world was drawn once from the seed; the shared capacity, the capacity-only initiative, `init-015`'s ratio, the forecast misses, the full specialist, the trend share of `init-008` and the adoption lag were chosen before the first run (DR-01..DR-07). Recovering them shows the measurement works, not that a real portfolio has them.
* **Outcome-informed choices are disclosed in the manifest** (a period-0 discovery cost on every initiative, normalised benefit shares, a volume floor, extra observation readings, the ramp range, one performance level and one revision date). The discovery cost is why every payback series has an investment.
* **Plan estimates, a twelve-period benefit window.** Each benefit stream runs for at most twelve periods; nothing after it is planned, so long-lived benefits are understated and NPVs describe the window, not a lifetime.
* **The rate and the ramp.** Options are valued at 8 % annual (0.006434 per month) with `scn-025`'s pinned ramps; both move an initiative's NPV: `init-015` runs from -508,801.53 to -619,344.67 across its 8 scenarios (rates 0.006434 to 0.009489 per month, two ramps).
* **Attribution.** Observed realisation is not caused by the initiative; `init-008`'s improvement is mostly trend (0.848744). The synthetic attributable share in the manifest is never used.
* **The roadmap is not levelled.** `res-02` (change managers, 3.00 FTE) is at capacity in 18 consecutive periods; any added scope needs those people, and no levelling exists to move starts.

## Limitations
* Synthetic portfolio, people and budgets: no real organisation, no inflation, no tax, no financing; risk exposure (7,485,779.58 in all) is a probability-weighted estimate, not a forecast, and is not netted into any NPV.
* The constructed options are exact sums of stored NPVs at `scn-025`'s rate and pins; a new scenario built with C03 would recompute them and could differ if its created_at picked later assumption versions.
* The public site is a static demo; its sensitivity lab, roadmap edits and proposal simulate their actions in browser memory, and nothing is proposed or funded from them. The commands C01..C10 are verified separately on hosted runners against a transient PostgreSQL.
* The review R9 found 14 defects (fixed as R9-01..R9-22 under D-09 at `29948f9`); this memo's figures are those of the corrected rules.
* **Excel and Power BI were not run.** The workbook was recalculated by LibreOffice headless only; the BI package has no `.pbix` and its DAX-like measures were not executed in any engine, only recomputed in Python from the CSV facts. This memo does not support any statement about a realised benefit to a real organisation.

## Recommendation
Build the ten-initiative scenario of option D on `scn-025`'s assumptions, explain the 207,146.32 money and 5,974.80 hours residual of `src-fin-ap-shared-team`, and propose it, with stage gates on `init-003`, `init-014` and `init-016`; hold the six initiatives that never pay back until their avoided cost has budget evidence or their capacity has a staffing change; re-plan the dependencies that tie eight carriers to them. Report the attributable NPV, never the plain sum, and judge success by observed realisation within each benefit type, adoption over its eligible population and cost variance on matured periods, each beside its plan and labelled observed, not attributed.
