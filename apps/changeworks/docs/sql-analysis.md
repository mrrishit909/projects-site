# ChangeWorks: SQL analysis with reconciled totals (P09-ART-04)

**Synthetic data only.** One generated world (seed 20261026, dataset `cw-20261026-20261026`, generator `dataset_hash` `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`), contract v1, code revision `29948f9` (`29948f92f0c3839f070e4b6499b99f3810d1361b`), as-of 2026-10-05T00:00:00Z, 36 monthly periods from 2026-01. Nothing is a claim about a real organisation. Three kinds of statement are kept apart: **observed** (what this one draw of the world holds, and what is recorded as observed in it: adoption, training, benefit observations, actual costs), **constructed** (what the generator built in on purpose: the designed relationships DR-01..DR-07 and the injections INJ-01..INJ-12; every NPV, payback and benefit total is a **plan estimate** of a scenario, not an observation) and **hypothetical** (any benefit to a real organisation: not claimed anywhere).

The decision the analysis serves: **which transformation initiative should be funded, and how will success be established?** (P09-GOAL-01). Nothing in the product funds anything: a selected scenario is a proposal (P09-FLOW-07).

**How to read it without installing anything:** each section states the question, the rule from `docs/contracts.md`, the finding with its figures, and the result tables. Every table between a BEGIN and an END marker named after its result key is rendered from `artifacts/analysis-results.json` by `artifacts/render_sql_analysis.py`, so no figure in a table is typed by hand; `tests/test_artifacts.py` re-renders in memory and fails on any drift. Money is USD with 2 places, capacity is hours, proportions are decimal fractions with 6 places, paybacks are period indexes (a period is a calendar month) with a 4-place interpolation. Scope: scenario `scn-025` (all 24 initiatives, 8 % annual converted to 0.006434 per month, 36 periods) unless a table says otherwise.

**How it was run:**
```
cd apps/changeworks
export ARTIFACTS_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/artifacts09_snapshot      # scratch databases only: prepare_snapshot.py refuses any other name
export ARTIFACTS_GOLDEN_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/artifacts09_golden
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi
../../.venv/bin/python artifacts/render_sql_analysis.py
```
`run_all.py` resets the two scratch databases (`data/migrate.py`, never the whole schema), loads the published snapshot and the golden fixture through `data/seed.py` (the domain's validation; 0 rejected rows), runs `ANALYZE`, builds the scenario model (`00_portfolio_model.sql`, 23 temporary tables `cw_*`, written for this package from the contracts and not copied from `data/sql/reference_metrics.sql`), runs the investigations 01..09 and 11 on the snapshot and 10 on the golden database, and reconciles (section 13). Every ORDER BY is locale independent (text keys `COLLATE "C"`, numbers, or booleans), so the rows are the same on the CI service (`postgres:16`, en_US.utf8) and on a C-locale server. Excel and Power BI were not run anywhere in this package.

**Exactness.** No float is used. A discount factor is never divided early: the powers q^k of q = 1 + r are built by multiplication only, the cumulative discounted flow of period t is D_t / q^t with D_t = sum over s <= t of net_s x q^(t-s), and the NPV is D_(h-1) / q^(h-1), one division at the end; the exact rational, reduced by `gcd`, is published beside every 2-place NPV (`02_initiative_npv__scn025_exact`, `__by_scenario_exact`) and equals the domain's `npv.exact` string for all 210 scenario-initiative pairs and all 30 portfolio totals. Totals are exact sums rounded once, half away from zero.

## 1. The portfolio ledger per scenario, four benefit classes kept apart (investigation 01; D-01, D-09 R9-02, R9-03, R9-07)
In `scn-025` the 24 initiatives plan **25,914,200.00** of costs inside the horizon against **15,288,067.20** cash, **6,074,000.13** revenue, **5,516,433.35** avoided cost realised (cash_realisation and an evidence reference) and **1,774,010.55** capacity converted to money (a conversion rate with staffing evidence): the four classes that enter the cash flow. Beside the flow sit **4,025,383.47** of avoided cost that no budget line removed and **145,045.62** capacity hours that have no conversion. The plain sum of the money claims is **32,677,894.70**; counting the claims that share a source key once leaves **32,470,748.38** attributable, a residual of **207,146.32**. Capacity is a second rule in hours: **194,875.92** planned, **5,974.80** counted twice. The identity planned = entering + beside holds exactly in all 30 scenarios and no hour is ever added to a dollar (`class_identity`). Constructed: the classes and their sizes are the generator's; observed: nothing in this section (all plan).

<!-- BEGIN:01_portfolio_ledger__by_scenario -->
| scenario_id | initiatives | horizon_periods | rate_basis | declared_rate | period_rate | planned_costs | cash | revenue | avoided_cost_realised | capacity_converted | avoided_cost_beside | planned_benefits | double_counted_amount | attributable_benefits | capacity_hours_planned | hours_residual | capacity_hours_attributable | capacity_hours_not_converted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scn-001 | 6 | 36 | annual | 0.080000 | 0.006434 | 5564850.00 | 5111800.12 | 0.00 | 1675266.64 | 0.00 | 837400.02 | 7624466.78 | 0.00 | 7624466.78 | 81230.96 | 7302.53 | 73928.43 | 81230.96 |
| scn-002 | 6 | 36 | annual | 0.120000 | 0.009489 | 5564850.00 | 4988733.57 | 0.00 | 1524866.79 | 1657551.89 | 837400.02 | 9008552.27 | 253178.85 | 8755373.42 | 78996.66 | 7302.53 | 71694.12 | 32429.32 |
| scn-003 | 6 | 24 | annual | 0.080000 | 0.006434 | 5526650.00 | 4839200.16 | 0.00 | 1425200.08 | 1601650.95 | 769300.02 | 8635351.21 | 253178.85 | 8382172.36 | 70915.16 | 7302.53 | 63612.63 | 26109.04 |
| scn-004 | 4 | 36 | annual | 0.100000 | 0.007974 | 3571000.00 | 2860599.95 | 0.00 | 977599.92 | 0.00 | 476199.99 | 4314399.87 | 0.00 | 4314399.87 | 59608.33 | 0.00 | 59608.33 | 59608.33 |
| scn-005 | 6 | 36 | annual | 0.100000 | 0.007974 | 5564850.00 | 5111800.12 | 0.00 | 1675266.64 | 0.00 | 837400.02 | 7624466.78 | 0.00 | 7624466.78 | 81230.96 | 7302.53 | 73928.43 | 81230.96 |
| scn-006 | 6 | 36 | monthly | 0.007000 | 0.007000 | 5564850.00 | 4531533.55 | 0.00 | 1425200.08 | 1495687.35 | 745133.37 | 8197554.34 | 207146.32 | 7990408.03 | 73960.63 | 5974.80 | 67985.83 | 32429.32 |
| scn-007 | 6 | 36 | annual | 0.080000 | 0.006434 | 6772650.00 | 1377066.72 | 6573733.08 | 0.00 | 0.00 | 1772416.58 | 9723216.38 | 0.00 | 9723216.38 | 51825.80 | 0.00 | 51825.80 | 51825.80 |
| scn-008 | 6 | 36 | annual | 0.120000 | 0.009489 | 6772650.00 | 1377066.72 | 6573733.08 | 0.00 | 196125.53 | 1772416.58 | 9919341.91 | 0.00 | 9919341.91 | 51825.80 | 0.00 | 51825.80 | 45414.38 |
| scn-009 | 6 | 24 | annual | 0.080000 | 0.006434 | 6687700.00 | 1261200.00 | 5872466.38 | 0.00 | 196125.53 | 1585166.58 | 8914958.48 | 0.00 | 8914958.48 | 36891.24 | 0.00 | 36891.24 | 30479.81 |
| scn-010 | 2 | 36 | annual | 0.100000 | 0.007974 | 2347700.00 | 0.00 | 2122033.17 | 0.00 | 0.00 | 636566.62 | 2758599.79 | 0.00 | 2758599.79 | 11441.31 | 0.00 | 11441.31 | 11441.31 |
| scn-011 | 6 | 36 | annual | 0.100000 | 0.007974 | 6772650.00 | 1377066.72 | 6573733.08 | 0.00 | 0.00 | 1772416.58 | 9723216.38 | 0.00 | 9723216.38 | 51825.80 | 0.00 | 51825.80 | 51825.80 |
| scn-012 | 6 | 36 | monthly | 0.007000 | 0.007000 | 6772650.00 | 1261200.00 | 6074000.13 | 0.00 | 165952.40 | 1645683.37 | 9146835.90 | 0.00 | 9146835.90 | 49261.27 | 0.00 | 49261.27 | 43836.21 |
| scn-013 | 6 | 36 | annual | 0.080000 | 0.006434 | 6189550.00 | 5324500.14 | 0.00 | 2010466.68 | 0.00 | 728466.72 | 8063433.53 | 0.00 | 8063433.53 | 49795.74 | 0.00 | 49795.74 | 49795.74 |
| scn-014 | 6 | 36 | annual | 0.120000 | 0.009489 | 6189550.00 | 5324500.14 | 0.00 | 2010466.68 | 132801.84 | 728466.72 | 8196235.37 | 0.00 | 8196235.37 | 49795.74 | 0.00 | 49795.74 | 46399.27 |
| scn-015 | 6 | 24 | annual | 0.080000 | 0.006434 | 6121500.00 | 4470233.63 | 0.00 | 1736833.45 | 112370.80 | 693933.37 | 7013371.25 | 0.00 | 7013371.25 | 44119.03 | 0.00 | 44119.03 | 41245.09 |
| scn-016 | 3 | 36 | annual | 0.100000 | 0.007974 | 3328800.00 | 2986666.88 | 0.00 | 457333.37 | 0.00 | 728466.72 | 4172466.96 | 0.00 | 4172466.96 | 38540.98 | 0.00 | 38540.98 | 38540.98 |
| scn-017 | 6 | 36 | annual | 0.100000 | 0.007974 | 6189550.00 | 5324500.14 | 0.00 | 2010466.68 | 0.00 | 728466.72 | 8063433.53 | 0.00 | 8063433.53 | 49795.74 | 0.00 | 49795.74 | 49795.74 |
| scn-018 | 6 | 36 | monthly | 0.007000 | 0.007000 | 6189550.00 | 4641500.18 | 0.00 | 1807133.45 | 112370.80 | 624400.00 | 7185404.43 | 0.00 | 7185404.43 | 43767.35 | 0.00 | 43767.35 | 40893.41 |
| scn-019 | 6 | 36 | annual | 0.080000 | 0.006434 | 7387150.00 | 4853833.47 | 0.00 | 2284099.82 | 0.00 | 1010166.73 | 8148100.02 | 0.00 | 8148100.02 | 27886.67 | 0.00 | 27886.67 | 27886.67 |
| scn-020 | 6 | 36 | annual | 0.120000 | 0.009489 | 7387150.00 | 4853833.47 | 0.00 | 2284099.82 | 0.00 | 1010166.73 | 8148100.02 | 0.00 | 8148100.02 | 27886.67 | 0.00 | 27886.67 | 27886.67 |
| scn-021 | 6 | 24 | annual | 0.080000 | 0.006434 | 6993000.00 | 3454666.74 | 0.00 | 2284099.82 | 0.00 | 799716.73 | 6538483.30 | 0.00 | 6538483.30 | 13466.00 | 0.00 | 13466.00 | 13466.00 |
| scn-022 | 2 | 36 | annual | 0.100000 | 0.007974 | 4330500.00 | 3129000.00 | 0.00 | 2284099.82 | 0.00 | 482066.70 | 5895166.52 | 0.00 | 5895166.52 | 7812.00 | 0.00 | 7812.00 | 7812.00 |
| scn-023 | 6 | 36 | annual | 0.100000 | 0.007974 | 7387150.00 | 4853833.47 | 0.00 | 2284099.82 | 0.00 | 1010166.73 | 8148100.02 | 0.00 | 8148100.02 | 27886.67 | 0.00 | 27886.67 | 27886.67 |
| scn-024 | 6 | 36 | monthly | 0.007000 | 0.007000 | 7387150.00 | 4853833.47 | 0.00 | 2284099.82 | 0.00 | 1010166.73 | 8148100.02 | 0.00 | 8148100.02 | 27886.67 | 0.00 | 27886.67 | 27886.67 |
| scn-025 | 24 | 36 | annual | 0.080000 | 0.006434 | 25914200.00 | 15288067.20 | 6074000.13 | 5516433.35 | 1774010.55 | 4025383.47 | 32677894.70 | 207146.32 | 32470748.38 | 194875.92 | 5974.80 | 188901.12 | 145045.62 |
| scn-026 | 23 | 36 | annual | 0.080000 | 0.006434 | 25083450.00 | 14255667.20 | 6074000.13 | 5516433.35 | 1497815.46 | 3715783.47 | 31059699.61 | 0.00 | 31059699.61 | 186909.52 | 0.00 | 186909.52 | 145045.62 |
| scn-027 | 5 | 24 | annual | 0.100000 | 0.007974 | 6704050.00 | 4034633.46 | 2787166.88 | 1357000.07 | 889923.76 | 1006633.40 | 10075357.56 | 207146.32 | 9868211.24 | 33381.15 | 5974.80 | 27406.35 | 6548.48 |
| scn-028 | 7 | 36 | annual | 0.100000 | 0.007974 | 8209100.00 | 5954133.49 | 0.00 | 2940233.20 | 0.00 | 892266.73 | 9786633.43 | 0.00 | 9786633.43 | 44237.80 | 0.00 | 44237.80 | 44237.80 |
| scn-029 | 10 | 36 | annual | 0.120000 | 0.009489 | 7128200.00 | 4141766.94 | 1164800.08 | 656133.38 | 0.00 | 1052050.07 | 7014750.47 | 0.00 | 7014750.47 | 86695.45 | 0.00 | 86695.45 | 86695.45 |
| scn-030 | 10 | 36 | annual | 0.100000 | 0.007974 | 13531550.00 | 8526300.26 | 2585633.17 | 4262299.97 | 996457.60 | 1759500.01 | 18130191.00 | 0.00 | 18130191.00 | 70709.65 | 0.00 | 70709.65 | 44838.09 |
<!-- END:01_portfolio_ledger__by_scenario -->

<!-- BEGIN:01_portfolio_ledger__class_identity -->
| scenario_id | entering_the_cash_flow | beside_the_cash_flow | planned_benefits | identity_holds_exactly | hour_rows_never_added_to_dollars |
|---|---|---|---|---|---|
| scn-001 | 6787066.76 | 837400.02 | 7624466.78 | true | 72 |
| scn-002 | 8171152.25 | 837400.02 | 9008552.27 | true | 24 |
| scn-003 | 7866051.19 | 769300.02 | 8635351.21 | true | 20 |
| scn-004 | 3838199.88 | 476199.99 | 4314399.87 | true | 48 |
| scn-005 | 6787066.76 | 837400.02 | 7624466.78 | true | 72 |
| scn-006 | 7452420.97 | 745133.37 | 8197554.34 | true | 24 |
| scn-007 | 7950799.81 | 1772416.58 | 9723216.38 | true | 71 |
| scn-008 | 8146925.33 | 1772416.58 | 9919341.91 | true | 59 |
| scn-009 | 7329791.90 | 1585166.58 | 8914958.48 | true | 53 |
| scn-010 | 2122033.17 | 636566.62 | 2758599.79 | true | 24 |
| scn-011 | 7950799.81 | 1772416.58 | 9723216.38 | true | 71 |
| scn-012 | 7501152.53 | 1645683.37 | 9146835.90 | true | 59 |
| scn-013 | 7334966.82 | 728466.72 | 8063433.53 | true | 60 |
| scn-014 | 7467768.65 | 728466.72 | 8196235.37 | true | 48 |
| scn-015 | 6319437.88 | 693933.37 | 7013371.25 | true | 46 |
| scn-016 | 3444000.25 | 728466.72 | 4172466.96 | true | 36 |
| scn-017 | 7334966.82 | 728466.72 | 8063433.53 | true | 60 |
| scn-018 | 6561004.43 | 624400.00 | 7185404.43 | true | 48 |
| scn-019 | 7137933.29 | 1010166.73 | 8148100.02 | true | 58 |
| scn-020 | 7137933.29 | 1010166.73 | 8148100.02 | true | 58 |
| scn-021 | 5738766.57 | 799716.73 | 6538483.30 | true | 34 |
| scn-022 | 5413099.82 | 482066.70 | 5895166.52 | true | 12 |
| scn-023 | 7137933.29 | 1010166.73 | 8148100.02 | true | 58 |
| scn-024 | 7137933.29 | 1010166.73 | 8148100.02 | true | 58 |
| scn-025 | 28652511.23 | 4025383.47 | 32677894.70 | true | 189 |
| scn-026 | 27343916.14 | 3715783.47 | 31059699.61 | true | 189 |
| scn-027 | 9068724.16 | 1006633.40 | 10075357.56 | true | 12 |
| scn-028 | 8894366.70 | 892266.73 | 9786633.43 | true | 72 |
| scn-029 | 5962700.40 | 1052050.07 | 7014750.47 | true | 105 |
| scn-030 | 16370690.99 | 1759500.01 | 18130191.00 | true | 72 |
<!-- END:01_portfolio_ledger__class_identity -->

<!-- BEGIN:01_portfolio_ledger__scn025_by_initiative -->
| initiative_id | planned_costs | cash | revenue | avoided_cost_realised | capacity_converted | avoided_cost_beside | capacity_hours_not_converted |
|---|---|---|---|---|---|---|---|
| init-001 | 1163100.00 | 897200.00 | 0.00 | 598000.00 | 335405.47 | 0.00 | 0.00 |
| init-002 | 830750.00 | 1032400.00 | 0.00 | 0.00 | 276195.09 | 309600.00 | 0.00 |
| init-003 | 652800.00 | 745800.07 | 0.00 | 0.00 | 329621.20 | 223666.69 | 0.00 |
| init-004 | 1422150.00 | 676866.73 | 0.00 | 827200.08 | 554465.59 | 0.00 | 0.00 |
| init-005 | 907200.00 | 1179266.75 | 0.00 | 0.00 | 0.00 | 0.00 | 17682.00 |
| init-006 | 588850.00 | 0.00 | 0.00 | 0.00 | 0.00 | 211866.68 | 14747.32 |
| init-007 | 1961550.00 | 0.00 | 2323566.88 | 0.00 | 165952.40 | 697033.40 | 0.00 |
| init-008 | 1039700.00 | 695200.00 | 463600.00 | 0.00 | 0.00 | 0.00 | 6548.48 |
| init-009 | 775800.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 2920.48 |
| init-010 | 1571900.00 | 0.00 | 2122033.17 | 0.00 | 0.00 | 636566.62 | 8034.09 |
| init-011 | 452900.00 | 566000.00 | 0.00 | 0.00 | 0.00 | 0.00 | 3913.50 |
| init-012 | 970800.00 | 0.00 | 1164800.08 | 0.00 | 0.00 | 312083.36 | 22419.67 |
| init-013 | 1708950.00 | 1409833.46 | 0.00 | 759000.07 | 112370.80 | 0.00 | 0.00 |
| init-014 | 1247650.00 | 1390400.00 | 0.00 | 0.00 | 0.00 | 417200.00 | 12213.60 |
| init-015 | 1299050.00 | 690400.00 | 0.00 | 0.00 | 0.00 | 207200.00 | 13512.08 |
| init-016 | 782100.00 | 479200.00 | 0.00 | 392000.00 | 0.00 | 0.00 | 7309.44 |
| init-017 | 525050.00 | 0.00 | 0.00 | 656133.38 | 0.00 | 0.00 | 7858.29 |
| init-018 | 626750.00 | 671666.72 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| init-019 | 1093600.00 | 0.00 | 0.00 | 0.00 | 0.00 | 410200.03 | 1689.33 |
| init-020 | 899850.00 | 1079866.74 | 0.00 | 0.00 | 0.00 | 0.00 | 5282.67 |
| init-021 | 379200.00 | 0.00 | 0.00 | 0.00 | 0.00 | 117900.00 | 5886.00 |
| init-022 | 684000.00 | 644966.73 | 0.00 | 0.00 | 0.00 | 0.00 | 7216.67 |
| init-023 | 3045600.00 | 1522733.22 | 0.00 | 2284099.82 | 0.00 | 0.00 | 0.00 |
| init-024 | 1284900.00 | 1606266.78 | 0.00 | 0.00 | 0.00 | 482066.70 | 7812.00 |
<!-- END:01_portfolio_ledger__scn025_by_initiative -->

## 2. The NPV of every initiative in scn-025 and the attributable portfolio NPV (investigation 02; D-01, D-09 R9-02)
The sum of the 24 initiative NPVs is **1,438,382.25**; it counts the shared capacity claim of `init-001` and `init-002` twice, and that claim's present value inside the flow is **195,233.20**, so the portfolio NPV counted once is **1,243,149.05** (the plain sum overstates it by exactly the double-counted PV). Eighteen initiatives have a positive NPV; six are negative (`init-006` -535,631.92, `init-009` -761,535.73, `init-015` -618,556.03, `init-019` -1,002,807.01, `init-021` -337,229.75, `init-022` -61,430.84). Across the 30 scenarios the attributable NPV runs from -1,380,296.98 (`scn-021`) to 1,850,194.72 (`scn-002`); scenarios differ in members, horizon (24 or 36) and rate, so their totals are not comparable with each other as they stand (section 12 compares options on one rate and one set of pins).

<!-- BEGIN:02_initiative_npv__scn025 -->
| initiative_id | planned_costs | cash_benefits_entering | undiscounted_net | has_flows | npv |
|---|---|---|---|---|---|
| init-001 | 1163100.00 | 1830605.47 | 667505.47 | true | 578533.26 |
| init-002 | 830750.00 | 1308595.09 | 477845.09 | true | 413388.43 |
| init-003 | 652800.00 | 1075421.27 | 422621.27 | true | 363049.68 |
| init-004 | 1422150.00 | 2058532.40 | 636382.40 | true | 523302.08 |
| init-005 | 907200.00 | 1179266.75 | 272066.75 | true | 209002.21 |
| init-006 | 588850.00 | 0.00 | -588850.00 | true | -535631.92 |
| init-007 | 1961550.00 | 2489519.27 | 527969.27 | true | 415366.00 |
| init-008 | 1039700.00 | 1158800.00 | 119100.00 | true | 65253.91 |
| init-009 | 775800.00 | 0.00 | -775800.00 | true | -761535.73 |
| init-010 | 1571900.00 | 2122033.17 | 550133.17 | true | 423409.74 |
| init-011 | 452900.00 | 566000.00 | 113100.00 | true | 84012.76 |
| init-012 | 970800.00 | 1164800.08 | 194000.08 | true | 126524.02 |
| init-013 | 1708950.00 | 2281204.33 | 572254.33 | true | 463582.30 |
| init-014 | 1247650.00 | 1390400.00 | 142750.00 | true | 76930.78 |
| init-015 | 1299050.00 | 690400.00 | -608650.00 | true | -618556.03 |
| init-016 | 782100.00 | 871200.00 | 89100.00 | true | 46285.40 |
| init-017 | 525050.00 | 656133.38 | 131083.38 | true | 93546.29 |
| init-018 | 626750.00 | 671666.72 | 44916.72 | true | 15040.08 |
| init-019 | 1093600.00 | 0.00 | -1093600.00 | true | -1002807.01 |
| init-020 | 899850.00 | 1079866.74 | 180016.74 | true | 112711.77 |
| init-021 | 379200.00 | 0.00 | -379200.00 | true | -337229.75 |
| init-022 | 684000.00 | 644966.73 | -39033.27 | true | -61430.84 |
| init-023 | 3045600.00 | 3806833.04 | 761233.04 | true | 515502.07 |
| init-024 | 1284900.00 | 1606266.78 | 321366.78 | true | 230132.79 |
<!-- END:02_initiative_npv__scn025 -->

<!-- BEGIN:02_initiative_npv__portfolio_scn025 -->
| scenario_id | initiatives_with_flows | sum_of_initiatives | double_counted_pv | attributable_npv | plain_sum_overstates_by |
|---|---|---|---|---|---|
| scn-025 | 24 | 1438382.25 | 195233.20 | 1243149.05 | 195233.20 |
<!-- END:02_initiative_npv__portfolio_scn025 -->

<!-- BEGIN:02_initiative_npv__by_scenario -->
| scenario_id | initiatives_with_flows | sum_of_initiatives | double_counted_pv | attributable_npv |
|---|---|---|---|---|
| scn-001 | 6 | 953382.86 | 0.00 | 953382.86 |
| scn-002 | 6 | 2083397.09 | 233202.37 | 1850194.72 |
| scn-003 | 6 | 1980952.24 | 239423.08 | 1741529.16 |
| scn-004 | 4 | 99957.44 | 0.00 | 99957.44 |
| scn-005 | 6 | 892632.76 | 0.00 | 892632.76 |
| scn-006 | 6 | 1523563.61 | 194223.83 | 1329339.78 |
| scn-007 | 6 | 791876.77 | 0.00 | 791876.77 |
| scn-008 | 6 | 804919.25 | 0.00 | 804919.25 |
| scn-009 | 6 | 334667.51 | 0.00 | 334667.51 |
| scn-010 | 2 | -362653.93 | 0.00 | -362653.93 |
| scn-011 | 6 | 706407.57 | 0.00 | 706407.57 |
| scn-012 | 6 | 322261.60 | 0.00 | 322261.60 |
| scn-013 | 6 | 817592.33 | 0.00 | 817592.33 |
| scn-014 | 6 | 796700.44 | 0.00 | 796700.44 |
| scn-015 | 6 | -47204.81 | 0.00 | -47204.81 |
| scn-016 | 3 | -61970.90 | 0.00 | -61970.90 |
| scn-017 | 6 | 744598.77 | 0.00 | 744598.77 |
| scn-018 | 6 | 52603.38 | 0.00 | 52603.38 |
| scn-019 | 6 | -543120.97 | 0.00 | -543120.97 |
| scn-020 | 6 | -661017.95 | 0.00 | -661017.95 |
| scn-021 | 6 | -1380296.98 | 0.00 | -1380296.98 |
| scn-022 | 2 | 673071.47 | 0.00 | 673071.47 |
| scn-023 | 6 | -604162.03 | 0.00 | -604162.03 |
| scn-024 | 6 | -565945.30 | 0.00 | -565945.30 |
| scn-025 | 24 | 1438382.25 | 195233.20 | 1243149.05 |
| scn-026 | 23 | 1024993.83 | 0.00 | 1024993.83 |
| scn-027 | 5 | 1838021.19 | 192501.02 | 1645520.17 |
| scn-028 | 7 | 147903.44 | 0.00 | 147903.44 |
| scn-029 | 10 | -1343076.84 | 0.00 | -1343076.84 |
| scn-030 | 10 | 1748559.44 | 0.00 | 1748559.44 |
<!-- END:02_initiative_npv__by_scenario -->

## 3. The double-count residual and the hours residual by shared source key (investigation 03; D-01, R9-02, R9-03, DR-02, INJ-02)
One key carries the whole overlap in `scn-025`: `src-fin-ap-shared-team`, claimed by `init-001` and `init-002` in the 10 periods 3..12. In money the claims total 536,562.41, the larger claim of each period counts once (329,416.09) and **207,146.32** is the residual; in hours the same claims are 16,353.38 hours, 10,378.58 counted once, **5,974.80** the hours residual. Five scenarios carry a money residual (`scn-002`, `scn-003`, `scn-006`, `scn-025`, `scn-027`) and seven an hours residual (the five plus `scn-001` and `scn-005`, where the capacity is not converted so only hours overlap). C07 refuses to propose any of these seven without a written explanation (DOUBLE_COUNT_UNEXPLAINED; replayed in EV-02).

<!-- BEGIN:03_double_count__by_source_key -->
| rule | benefit_source_key | overlapping_periods | first_period | last_period | initiatives | claimed | counted_once | residual |
|---|---|---|---|---|---|---|---|---|
| money (USD) | src-fin-ap-shared-team | 10 | 3 | 12 | init-001,init-002 | 536562.41 | 329416.09 | 207146.32 |
| hours | src-fin-ap-shared-team | 10 | 3 | 12 | init-001,init-002 | 16353.38 | 10378.58 | 5974.80 |
<!-- END:03_double_count__by_source_key -->

<!-- BEGIN:03_double_count__by_period -->
| benefit_source_key | period_index | claims | money_claimed | money_counted_once | money_residual | hours_claimed | hours_counted_once | hours_residual |
|---|---|---|---|---|---|---|---|---|
| src-fin-ap-shared-team | 3 | init-001:b-0027 + init-002:b-0061 | 10217.09 | 8984.09 | 1233.00 | 318.62 | 283.05 | 35.56 |
| src-fin-ap-shared-team | 4 | init-001:b-0028 + init-002:b-0062 | 18672.51 | 14973.46 | 3699.05 | 578.45 | 471.75 | 106.69 |
| src-fin-ap-shared-team | 5 | init-001:b-0029 + init-002:b-0063 | 29858.27 | 22460.18 | 7398.09 | 921.02 | 707.63 | 213.39 |
| src-fin-ap-shared-team | 6 | init-001:b-0030 + init-002:b-0064 | 43774.41 | 31444.26 | 12330.14 | 1346.33 | 990.68 | 355.64 |
| src-fin-ap-shared-team | 7 | init-001:b-0031 + init-002:b-0065 | 60420.88 | 41925.68 | 18495.20 | 1854.37 | 1320.91 | 533.46 |
| src-fin-ap-shared-team | 8 | init-001:b-0032 + init-002:b-0066 | 67818.97 | 41925.68 | 25893.29 | 2067.76 | 1320.91 | 746.85 |
| src-fin-ap-shared-team | 9 | init-001:b-0033 + init-002:b-0067 | 76450.07 | 41925.68 | 34524.39 | 2316.71 | 1320.91 | 995.80 |
| src-fin-ap-shared-team | 10 | init-001:b-0034 + init-002:b-0068 | 76450.07 | 41925.68 | 34524.39 | 2316.71 | 1320.91 | 995.80 |
| src-fin-ap-shared-team | 11 | init-001:b-0035 + init-002:b-0069 | 76450.07 | 41925.68 | 34524.39 | 2316.71 | 1320.91 | 995.80 |
| src-fin-ap-shared-team | 12 | init-001:b-0036 + init-002:b-0070 | 76450.07 | 41925.68 | 34524.39 | 2316.71 | 1320.91 | 995.80 |
<!-- END:03_double_count__by_period -->

<!-- BEGIN:03_double_count__present_value_scn025 -->
| scenario_id | double_counted_amount | double_counted_pv | npv_sum_of_initiatives | npv_attributable | planned_benefits | attributable_benefits | planned_hours | attributable_hours | hours_residual |
|---|---|---|---|---|---|---|---|---|---|
| scn-025 | 207146.32 | 195233.20 | 1438382.25 | 1243149.05 | 32677894.70 | 32470748.38 | 194875.92 | 188901.12 | 5974.80 |
<!-- END:03_double_count__present_value_scn025 -->

<!-- BEGIN:03_double_count__by_scenario -->
| scenario_id | residual | hours_residual | double_counted_pv | explanation_required | explanation_required_for |
|---|---|---|---|---|---|
| scn-001 | 0.00 | 7302.53 | 0.00 | true | hours |
| scn-002 | 253178.85 | 7302.53 | 233202.37 | true | money,hours |
| scn-003 | 253178.85 | 7302.53 | 239423.08 | true | money,hours |
| scn-004 | 0.00 | 0.00 | 0.00 | false |  |
| scn-005 | 0.00 | 7302.53 | 0.00 | true | hours |
| scn-006 | 207146.32 | 5974.80 | 194223.83 | true | money,hours |
| scn-007 | 0.00 | 0.00 | 0.00 | false |  |
| scn-008 | 0.00 | 0.00 | 0.00 | false |  |
| scn-009 | 0.00 | 0.00 | 0.00 | false |  |
| scn-010 | 0.00 | 0.00 | 0.00 | false |  |
| scn-011 | 0.00 | 0.00 | 0.00 | false |  |
| scn-012 | 0.00 | 0.00 | 0.00 | false |  |
| scn-013 | 0.00 | 0.00 | 0.00 | false |  |
| scn-014 | 0.00 | 0.00 | 0.00 | false |  |
| scn-015 | 0.00 | 0.00 | 0.00 | false |  |
| scn-016 | 0.00 | 0.00 | 0.00 | false |  |
| scn-017 | 0.00 | 0.00 | 0.00 | false |  |
| scn-018 | 0.00 | 0.00 | 0.00 | false |  |
| scn-019 | 0.00 | 0.00 | 0.00 | false |  |
| scn-020 | 0.00 | 0.00 | 0.00 | false |  |
| scn-021 | 0.00 | 0.00 | 0.00 | false |  |
| scn-022 | 0.00 | 0.00 | 0.00 | false |  |
| scn-023 | 0.00 | 0.00 | 0.00 | false |  |
| scn-024 | 0.00 | 0.00 | 0.00 | false |  |
| scn-025 | 207146.32 | 5974.80 | 195233.20 | true | money,hours |
| scn-026 | 0.00 | 0.00 | 0.00 | false |  |
| scn-027 | 207146.32 | 5974.80 | 192501.02 | true | money,hours |
| scn-028 | 0.00 | 0.00 | 0.00 | false |  |
| scn-029 | 0.00 | 0.00 | 0.00 | false |  |
| scn-030 | 0.00 | 0.00 | 0.00 | false |  |
<!-- END:03_double_count__by_scenario -->

<!-- BEGIN:03_double_count__outcome -->
| scenarios_with_a_money_residual | scenarios_with_no_money_residual | scenarios_with_an_hours_residual | money_residual_scenarios | hours_residual_scenarios |
|---|---|---|---|---|
| 5 | 25 | 7 | scn-002,scn-003,scn-006,scn-025,scn-027 | scn-001,scn-002,scn-003,scn-005,scn-006,scn-025,scn-027 |
<!-- END:03_double_count__outcome -->

## 4. Simple and discounted payback by the last crossing, and what never pays back (investigation 04; D-01, R9-12, DR-03, INJ-08)
In `scn-025` 18 initiatives recover inside the window (simple paybacks from period 10, `init-001` at 9.2751 interpolated, to period 28, `init-018` at 27.3606); the discounted payback is the same period or one later. Six never recover: **both paybacks null with the reason `NOT_RECOVERED`**, never 0 and never refused. Over all 210 scenario-initiative series, 156 recover and 54 do not; **six initiatives never pay back in any scenario they appear in**: `init-006`, `init-009`, `init-015`, `init-019`, `init-021` and `init-022` (8 or 9 scenarios each). `init-015` (DR-03) returns **0.531465** of its 1,299,050.00 cost in the four scenarios that pin the ramp `a-015-adopti-2` (`scn-015`, `scn-018`, `scn-025`, `scn-026`) and **0.620043** in the four that pin `a-015-adopti-1`. The last-crossing rule never changes a figure here: in all 156 recovered series the first crossing after the first negative is the last one, and no series is never negative (the period-0 discovery cost, a disclosed outcome-informed choice, gives every series an investment).

<!-- BEGIN:04_payback__scn025 -->
| initiative_id | npv | simple_payback_period | simple_interpolated | simple_reason | discounted_payback_period | discounted_interpolated | discounted_reason |
|---|---|---|---|---|---|---|---|
| init-001 | 578533.26 | 10 | 9.2751 |  | 10 | 9.4881 |  |
| init-002 | 413388.43 | 10 | 9.9761 |  | 11 | 10.1813 |  |
| init-003 | 363049.68 | 12 | 11.1517 |  | 12 | 11.3518 |  |
| init-004 | 523302.08 | 14 | 13.0991 |  | 14 | 13.3330 |  |
| init-005 | 209002.21 | 19 | 18.4347 |  | 19 | 18.7401 |  |
| init-006 | -535631.92 |  |  | NOT_RECOVERED |  |  | NOT_RECOVERED |
| init-007 | 415366.00 | 11 | 10.2556 |  | 11 | 10.5167 |  |
| init-008 | 65253.91 | 13 | 12.3875 |  | 13 | 12.7625 |  |
| init-009 | -761535.73 |  |  | NOT_RECOVERED |  |  | NOT_RECOVERED |
| init-010 | 423409.74 | 18 | 17.3724 |  | 18 | 17.6973 |  |
| init-011 | 84012.76 | 21 | 20.5648 |  | 21 | 20.8920 |  |
| init-012 | 126524.02 | 27 | 26.2243 |  | 27 | 26.6165 |  |
| init-013 | 463582.30 | 11 | 10.3102 |  | 11 | 10.5628 |  |
| init-014 | 76930.78 | 15 | 14.9491 |  | 16 | 15.3225 |  |
| init-015 | -618556.03 |  |  | NOT_RECOVERED |  |  | NOT_RECOVERED |
| init-016 | 46285.40 | 17 | 16.4576 |  | 17 | 16.8431 |  |
| init-017 | 93546.29 | 22 | 21.7597 |  | 23 | 22.1197 |  |
| init-018 | 15040.08 | 28 | 27.3606 |  | 28 | 27.7438 |  |
| init-019 | -1002807.01 |  |  | NOT_RECOVERED |  |  | NOT_RECOVERED |
| init-020 | 112711.77 | 27 | 26.2203 |  | 27 | 26.6686 |  |
| init-021 | -337229.75 |  |  | NOT_RECOVERED |  |  | NOT_RECOVERED |
| init-022 | -61430.84 |  |  | NOT_RECOVERED |  |  | NOT_RECOVERED |
| init-023 | 515502.07 | 22 | 21.3888 |  | 22 | 21.8053 |  |
| init-024 | 230132.79 | 20 | 19.7406 |  | 21 | 20.1194 |  |
<!-- END:04_payback__scn025 -->

<!-- BEGIN:04_payback__reasons -->
| simple | discounted | series |
|---|---|---|
| NOT_RECOVERED | NOT_RECOVERED | 54 |
| RECOVERED | RECOVERED | 156 |
<!-- END:04_payback__reasons -->

<!-- BEGIN:04_payback__never_pays_back -->
| initiative_id | scenarios | scenarios_simple_null | scenarios_discounted_null | never_in_any_scenario | npv_lowest | npv_highest | simple_reasons |
|---|---|---|---|---|---|---|---|
| init-006 | 9 | 9 | 9 | true | -535631.92 | -503194.27 | NOT_RECOVERED |
| init-009 | 9 | 9 | 9 | true | -761535.73 | -754989.99 | NOT_RECOVERED |
| init-012 | 8 | 1 | 1 | false | -335847.97 | 126524.02 | NOT_RECOVERED,RECOVERED |
| init-015 | 8 | 8 | 8 | true | -619344.67 | -508801.53 | NOT_RECOVERED |
| init-018 | 8 | 1 | 1 | false | -282274.63 | 15040.08 | NOT_RECOVERED,RECOVERED |
| init-019 | 9 | 9 | 9 | true | -1002807.01 | -957317.14 | NOT_RECOVERED |
| init-020 | 9 | 1 | 1 | false | -315379.09 | 112711.77 | NOT_RECOVERED,RECOVERED |
| init-021 | 8 | 8 | 8 | true | -337229.75 | -300898.74 | NOT_RECOVERED |
| init-022 | 8 | 8 | 8 | true | -441825.82 | -61430.84 | NOT_RECOVERED |
<!-- END:04_payback__never_pays_back -->

<!-- BEGIN:04_payback__init015_by_scenario -->
| scenario_id | ramp_assumption_id | planned_cost | benefits_entering_the_cash_flow | benefit_to_cost | npv | simple_payback_period | discounted_payback_period | simple_reason |
|---|---|---|---|---|---|---|---|---|
| scn-013 | a-015-adopti-1 | 1299050.00 | 805466.72 | 0.620043 | -508801.53 |  |  | NOT_RECOVERED |
| scn-014 | a-015-adopti-1 | 1299050.00 | 805466.72 | 0.620043 | -515329.28 |  |  | NOT_RECOVERED |
| scn-015 | a-015-adopti-2 | 1299050.00 | 690400.00 | 0.531465 | -618556.03 |  |  | NOT_RECOVERED |
| scn-016 | a-015-adopti-1 | 1299050.00 | 805466.72 | 0.620043 | -512146.04 |  |  | NOT_RECOVERED |
| scn-017 | a-015-adopti-1 | 1299050.00 | 805466.72 | 0.620043 | -512146.04 |  |  | NOT_RECOVERED |
| scn-018 | a-015-adopti-2 | 1299050.00 | 690400.00 | 0.531465 | -619344.67 |  |  | NOT_RECOVERED |
| scn-025 | a-015-adopti-2 | 1299050.00 | 690400.00 | 0.531465 | -618556.03 |  |  | NOT_RECOVERED |
| scn-026 | a-015-adopti-2 | 1299050.00 | 690400.00 | 0.531465 | -618556.03 |  |  | NOT_RECOVERED |
<!-- END:04_payback__init015_by_scenario -->

<!-- BEGIN:04_payback__last_crossing_rule -->
| series | series_that_went_negative | series_that_recovered | recovered_series_where_first_and_last_crossing_differ | never_negative | no_flows |
|---|---|---|---|---|---|
| 210 | 210 | 156 | 0 | 0 | 0 |
<!-- END:04_payback__last_crossing_rule -->

## 5. Recurring costs over half-open ranges, one-time costs in exactly one period (investigation 05; D-01, D-P9-16, INJ-11, P09-TEST-11)
The 144 recurring cost items expand to **915** period rows (5,301,200.00 over their ranges, against 826,250.00 of per-period amounts); the 756 one-time items are 756 rows, each with exactly one `period_index`. The 72 pairs of adjacent ranges of one cost line (`[1, 7)` then `[7, 14)`) carry their boundary period exactly once, in the later range, and no range contains its own end. No one-time cost key appears in two periods and no key is of two kinds; the INJ-11 repeat of `ck-001-licence-setup-1` (`c-inj-11`, period 5) exists only as a refused replay event: `c-0042` is stored once, in period 1.

<!-- BEGIN:05_cost_expansion__by_type -->
| cost_type | cost_basis | items | expanded_rows | expanded_total | item_amount_total |
|---|---|---|---|---|---|
| one_time | actual | 288 | 288 | 14611324.35 | 14611324.35 |
| one_time | planned | 468 | 468 | 20613000.00 | 20613000.00 |
| recurring | planned | 144 | 915 | 5301200.00 | 826250.00 |
<!-- END:05_cost_expansion__by_type -->

<!-- BEGIN:05_cost_expansion__recurring_by_initiative -->
| initiative_id | recurring_items | expanded_rows | first_period | last_period | first_period_after_the_last_range | expanded_total |
|---|---|---|---|---|---|---|
| init-001 | 6 | 39 | 1 | 13 | 14 | 236100.00 |
| init-002 | 6 | 39 | 2 | 14 | 15 | 161250.00 |
| init-003 | 6 | 39 | 3 | 15 | 16 | 132800.00 |
| init-004 | 6 | 39 | 4 | 16 | 17 | 289150.00 |
| init-005 | 6 | 39 | 10 | 22 | 23 | 186200.00 |
| init-006 | 6 | 39 | 15 | 27 | 28 | 120850.00 |
| init-007 | 6 | 39 | 1 | 13 | 14 | 401550.00 |
| init-008 | 6 | 39 | 2 | 14 | 15 | 215700.00 |
| init-009 | 6 | 36 | 3 | 14 | 15 | 145800.00 |
| init-010 | 6 | 39 | 9 | 21 | 22 | 323900.00 |
| init-011 | 6 | 39 | 12 | 24 | 25 | 92400.00 |
| init-012 | 6 | 36 | 17 | 28 | 29 | 183300.00 |
| init-013 | 6 | 39 | 1 | 13 | 14 | 343950.00 |
| init-014 | 6 | 39 | 5 | 17 | 18 | 250150.00 |
| init-015 | 6 | 39 | 4 | 16 | 17 | 372050.00 |
| init-016 | 6 | 39 | 6 | 18 | 19 | 158100.00 |
| init-017 | 6 | 39 | 13 | 25 | 26 | 105050.00 |
| init-018 | 6 | 33 | 18 | 28 | 29 | 111750.00 |
| init-019 | 6 | 39 | 14 | 26 | 27 | 226600.00 |
| init-020 | 6 | 39 | 16 | 28 | 29 | 185850.00 |
| init-021 | 6 | 36 | 19 | 30 | 31 | 73200.00 |
| init-022 | 6 | 33 | 24 | 34 | 35 | 123000.00 |
| init-023 | 6 | 39 | 12 | 24 | 25 | 597600.00 |
| init-024 | 6 | 39 | 11 | 23 | 24 | 264900.00 |
<!-- END:05_cost_expansion__recurring_by_initiative -->

<!-- BEGIN:05_cost_expansion__half_open_boundaries -->
| adjacent_range_pairs | boundary_periods_with_exactly_one_row | ranges_that_do_not_contain_their_own_end |
|---|---|---|
| 72 | 72 | 72 |
<!-- END:05_cost_expansion__half_open_boundaries -->

<!-- BEGIN:05_cost_expansion__one_time_rule -->
| one_time_items | with_exactly_one_period | with_no_period | cost_keys_in_more_than_one_period | cost_keys_of_two_kinds |
|---|---|---|---|---|
| 756 | 756 | 0 | 0 | 0 |
<!-- END:05_cost_expansion__one_time_rule -->

<!-- BEGIN:05_cost_expansion__inj11_key -->
| cost_id | initiative_id | cost_key | cost_type | amount | period_index | rows_with_this_key | rows_in_period_5 |
|---|---|---|---|---|---|---|---|
| c-0042 | init-001 | ck-001-licence-setup-1 | one_time | 13500.00 | 1 | 1 | 0 |
<!-- END:05_cost_expansion__inj11_key -->

<!-- BEGIN:05_cost_expansion__scn025_by_initiative -->
| initiative_id | one_time_total | recurring_total | planned_costs | expanded_planned_rows |
|---|---|---|---|---|
| init-001 | 927000.00 | 236100.00 | 1163100.00 | 60 |
| init-002 | 669500.00 | 161250.00 | 830750.00 | 57 |
| init-003 | 520000.00 | 132800.00 | 652800.00 | 60 |
| init-004 | 1133000.00 | 289150.00 | 1422150.00 | 60 |
| init-005 | 721000.00 | 186200.00 | 907200.00 | 58 |
| init-006 | 468000.00 | 120850.00 | 588850.00 | 62 |
| init-007 | 1560000.00 | 401550.00 | 1961550.00 | 54 |
| init-008 | 824000.00 | 215700.00 | 1039700.00 | 59 |
| init-009 | 630000.00 | 145800.00 | 775800.00 | 53 |
| init-010 | 1248000.00 | 323900.00 | 1571900.00 | 61 |
| init-011 | 360500.00 | 92400.00 | 452900.00 | 59 |
| init-012 | 787500.00 | 183300.00 | 970800.00 | 57 |
| init-013 | 1365000.00 | 343950.00 | 1708950.00 | 60 |
| init-014 | 997500.00 | 250150.00 | 1247650.00 | 58 |
| init-015 | 927000.00 | 372050.00 | 1299050.00 | 57 |
| init-016 | 624000.00 | 158100.00 | 782100.00 | 57 |
| init-017 | 420000.00 | 105050.00 | 525050.00 | 54 |
| init-018 | 515000.00 | 111750.00 | 626750.00 | 54 |
| init-019 | 867000.00 | 226600.00 | 1093600.00 | 63 |
| init-020 | 714000.00 | 185850.00 | 899850.00 | 59 |
| init-021 | 306000.00 | 73200.00 | 379200.00 | 54 |
| init-022 | 561000.00 | 123000.00 | 684000.00 | 53 |
| init-023 | 2448000.00 | 597600.00 | 3045600.00 | 55 |
| init-024 | 1020000.00 | 264900.00 | 1284900.00 | 59 |
<!-- END:05_cost_expansion__scn025_by_initiative -->

## 6. Cost variance and benefit realisation on matured periods, the trend beside the raw change (investigation 06; D-02, D-P9-05, D-P9-12, R9-11, R9-13, DR-06, INJ-10)
Nine periods (0..8) are matured at the as-of; period 9 (October 2026) is not. Observed: of the 24 initiatives in `scn-025`, 13 have an approved baseline and actual costs in the window: 7 are over their baseline, 6 under, net **+253,802.33**; 11 have no variance (no actuals yet, or no matured period of their plan), shown as null with the reason, never 0. Benefit realisation compares 150 matured rows with an observation in 31 initiative-type comparisons (20 matured rows have no observation and are listed, not counted as 0); every compared row carries a recorded trend, so `observed_above_trend` is always published and `PARTIAL_TREND_COVERAGE` never fires. `init-008` (DR-06) realises **0.975795** of its planned cash (169,593.13 observed against 173,800.00), but **0.848744** of the observed change is the baseline trend recorded before deployment (143,941.18); only 25,651.95 is above the trend. The next-largest trend share is 0.215600 (`init-013`). Every figure is "observed, not attributed".

<!-- BEGIN:06_variance_realisation__matured -->
| as_of | period_basis | matured_periods | last_matured_period | first_unmatured_period | first_unmatured_period_starts | first_unmatured_period_ends |
|---|---|---|---|---|---|---|
| 2026-10-05T00:00:00+00:00 | monthly | 9 | 8 | 9 | 2026-10-01 | 2026-11-01 |
<!-- END:06_variance_realisation__matured -->

<!-- BEGIN:06_variance_realisation__cost_variance_scn025 -->
| initiative_id | window_to_period | approved_baseline_version | approved_baseline_cost | actual_cost | variance | reason |
|---|---|---|---|---|---|---|
| init-001 | 9 | v2 | 1071600.00 | 1106861.71 | 35261.71 |  |
| init-002 | 9 | v2 | 754250.00 | 716804.41 | -37445.59 |  |
| init-003 | 9 | v2 | 580000.00 | 611430.68 | 31430.68 |  |
| init-004 | 9 | v2 | 1243000.00 | 1179990.61 | -63009.39 |  |
| init-005 | 9 | v2 | 357650.00 | 298561.41 | -59088.59 |  |
| init-006 | 9 | v2 | 9000.00 |  |  | NO_ACTUALS |
| init-007 | 9 | v2 | 1803300.00 | 1826626.08 | 23326.08 |  |
| init-008 | 9 | v2 | 937100.00 | 900019.66 | -37080.34 |  |
| init-009 | 9 | v2 | 702000.00 | 628639.42 | -73360.58 |  |
| init-010 | 9 | v2 | 895350.00 | 1017083.80 | 121733.80 |  |
| init-011 | 9 | v2 | 7000.00 |  |  | NO_ACTUALS |
| init-012 | 9 | v2 | 15000.00 |  |  | NO_ACTUALS |
| init-013 | 9 | v1 | 1574700.00 | 1745196.08 | 170496.08 |  |
| init-014 | 9 | v1 | 1073500.00 | 1157941.17 | 84441.17 |  |
| init-015 | 9 | v1 | 1067000.00 | 1160702.86 | 93702.86 |  |
| init-016 | 9 | v1 | 660000.00 | 623394.44 | -36605.56 |  |
| init-017 | 9 | v1 | 8000.00 |  |  | NO_ACTUALS |
| init-018 | 9 | v1 | 10000.00 |  |  | NO_ACTUALS |
| init-019 | 9 |  |  |  |  | NO_APPROVED_BASELINE |
| init-020 | 9 |  |  |  |  | NO_APPROVED_BASELINE |
| init-021 | 9 |  |  |  |  | NO_APPROVED_BASELINE |
| init-022 | 9 |  |  |  |  | NO_APPROVED_BASELINE |
| init-023 | 9 |  |  |  |  | NO_APPROVED_BASELINE |
| init-024 | 9 |  |  |  |  | NO_APPROVED_BASELINE |
<!-- END:06_variance_realisation__cost_variance_scn025 -->

<!-- BEGIN:06_variance_realisation__variance_summary_scn025 -->
| initiatives_with_a_variance | over_baseline | under_baseline | on_baseline | initiatives_with_no_variance | net_variance |
|---|---|---|---|---|---|
| 13 | 7 | 6 | 0 | 11 | 253802.33 |
<!-- END:06_variance_realisation__variance_summary_scn025 -->

<!-- BEGIN:06_variance_realisation__realisation_scn025 -->
| initiative_id | benefit_type | unit | compared_rows | matured_unobserved_rows | planned_comparable | observed_comparable | realisation | baseline_trend | observed_above_trend | trend_share_of_observed | attribution |
|---|---|---|---|---|---|---|---|---|---|---|---|
| init-001 | avoided_cost | USD | 8 | 0 | 299000.00 | 261005.63 | 0.872929 | 29284.83 | 231720.80 | 0.112200 | observed, not attributed |
| init-001 | capacity | hours | 8 | 0 | 5283.64 | 4885.25 | 0.924599 | 977.04 | 3908.21 | 0.199998 | observed, not attributed |
| init-001 | cash | USD | 6 | 1 | 224300.00 | 233147.05 | 1.039443 | 16320.29 | 216826.76 | 0.070000 | observed, not attributed |
| init-002 | avoided_cost | USD | 5 | 1 | 48375.00 | 38290.87 | 0.791543 | 2182.58 | 36108.29 | 0.057000 | observed, not attributed |
| init-002 | capacity | hours | 5 | 1 | 1244.75 | 1171.06 | 0.940799 | 258.56 | 912.50 | 0.220791 | observed, not attributed |
| init-002 | cash | USD | 6 | 1 | 258100.00 | 265890.46 | 1.030184 | 52486.77 | 213403.69 | 0.197400 | observed, not attributed |
| init-003 | avoided_cost | USD | 4 | 1 | 16944.46 | 17366.72 | 1.024920 | 1986.75 | 15379.97 | 0.114400 | observed, not attributed |
| init-003 | capacity | hours | 4 | 1 | 811.28 | 668.97 | 0.824582 | 92.72 | 576.25 | 0.138601 | observed, not attributed |
| init-003 | cash | USD | 6 | 0 | 158200.05 | 105568.01 | 0.667307 | 11960.84 | 93607.17 | 0.113300 | observed, not attributed |
| init-004 | avoided_cost | USD | 5 | 0 | 109666.75 | 111859.47 | 1.019994 | 17617.87 | 94241.60 | 0.157500 | observed, not attributed |
| init-004 | capacity | hours | 3 | 1 | 465.48 | 361.63 | 0.776895 | 87.66 | 273.97 | 0.242402 | observed, not attributed |
| init-004 | cash | USD | 4 | 0 | 51277.82 | 52472.86 | 1.023305 | 11239.69 | 41233.17 | 0.214200 | observed, not attributed |
| init-007 | avoided_cost | USD | 6 | 1 | 147855.60 | 131169.04 | 0.887143 | 26915.88 | 104253.16 | 0.205200 | observed, not attributed |
| init-007 | capacity | hours | 6 | 1 | 1150.77 | 1105.09 | 0.960305 | 112.73 | 992.36 | 0.102010 | observed, not attributed |
| init-007 | revenue | USD | 7 | 1 | 739316.88 | 632485.59 | 0.855500 | 68181.95 | 564303.64 | 0.107800 | observed, not attributed |
| init-008 | capacity | hours | 5 | 1 | 1023.20 | 821.49 | 0.802864 | 177.61 | 643.88 | 0.216205 | observed, not attributed |
| init-008 | cash | USD | 6 | 1 | 173800.00 | 169593.13 | 0.975795 | 143941.18 | 25651.95 | 0.848744 | observed, not attributed |
| init-008 | revenue | USD | 6 | 0 | 115900.00 | 86335.17 | 0.744911 | 5680.85 | 80654.32 | 0.065800 | observed, not attributed |
| init-009 | capacity | hours | 5 | 1 | 456.33 | 387.77 | 0.849767 | 63.95 | 323.82 | 0.164917 | observed, not attributed |
| init-013 | avoided_cost | USD | 6 | 1 | 161000.05 | 158010.04 | 0.981429 | 16117.02 | 141893.02 | 0.102000 | observed, not attributed |
| init-013 | capacity | hours | 7 | 0 | 914.43 | 835.33 | 0.913494 | 132.07 | 703.26 | 0.158105 | observed, not attributed |
| init-013 | cash | USD | 7 | 1 | 448583.46 | 383883.31 | 0.855768 | 82765.25 | 301118.06 | 0.215600 | observed, not attributed |
| init-014 | avoided_cost | USD | 2 | 1 | 7449.99 | 7500.85 | 1.006827 | 802.59 | 6698.26 | 0.107000 | observed, not attributed |
| init-014 | capacity | hours | 2 | 1 | 218.10 | 155.24 | 0.711784 | 22.85 | 132.39 | 0.147191 | observed, not attributed |
| init-014 | cash | USD | 4 | 0 | 124142.91 | 92781.29 | 0.747375 | 13508.96 | 79272.33 | 0.145600 | observed, not attributed |
| init-015 | avoided_cost | USD | 4 | 0 | 18500.01 | 13587.33 | 0.734450 | 733.71 | 12853.62 | 0.054000 | observed, not attributed |
| init-015 | capacity | hours | 3 | 1 | 603.22 | 567.60 | 0.940953 | 54.49 | 513.11 | 0.096001 | observed, not attributed |
| init-015 | cash | USD | 5 | 0 | 107875.00 | 103693.76 | 0.961240 | 9799.06 | 93894.70 | 0.094500 | observed, not attributed |
| init-016 | avoided_cost | USD | 1 | 1 | 1749.99 | 1606.49 | 0.918002 | 380.58 | 1225.91 | 0.236902 | observed, not attributed |
| init-016 | capacity | hours | 2 | 0 | 130.53 | 136.45 | 1.045389 | 14.47 | 121.98 | 0.106046 | observed, not attributed |
| init-016 | cash | USD | 2 | 1 | 8557.13 | 7509.96 | 0.877626 | 1606.38 | 5903.58 | 0.213900 | observed, not attributed |
<!-- END:06_variance_realisation__realisation_scn025 -->

<!-- BEGIN:06_variance_realisation__trend_beside_raw -->
| initiative_id | observed_comparable | baseline_trend | observed_above_trend | trend_share_of_observed | realisation |
|---|---|---|---|---|---|
| init-008 | 169593.13 | 143941.18 | 25651.95 | 0.848744 | 0.975795 |
| init-013 | 383883.31 | 82765.25 | 301118.06 | 0.215600 | 0.855768 |
| init-004 | 52472.86 | 11239.69 | 41233.17 | 0.214200 | 1.023305 |
| init-016 | 7509.96 | 1606.38 | 5903.58 | 0.213900 | 0.877626 |
| init-002 | 265890.46 | 52486.77 | 213403.69 | 0.197400 | 1.030184 |
<!-- END:06_variance_realisation__trend_beside_raw -->

<!-- BEGIN:06_variance_realisation__coverage -->
| comparisons | with_complete_trend_coverage | with_partial_trend_coverage | rows_compared | matured_rows_with_no_observation |
|---|---|---|---|---|
| 31 | 31 | 0 | 150 | 20 |
<!-- END:06_variance_realisation__coverage -->

## 7. Adoption against training, with the denominators (investigation 07; D-03, R9-11, R9-16, DR-07, INJ-05, P09-TEST-05)
Observed: pooled adoption is **0.532881** (3,063 adopted of 5,748 eligible, the latest observation of 11 initiatives) and pooled training completion **0.888443** (6,427 of 7,234, 15 initiatives). The two pools are different populations: on the 11 initiatives that have both series training completion is **0.963778** (5,561 of 5,770). Five of the eleven reached half adoption 4, 4, 5, 5 and 6 calendar months after training passed 90 %; six have not (`init-003`, `init-004`, `init-009`, `init-014`, `init-015`, `init-016`), `init-003` at 0.232258 adoption with 0.977918 of its trainees trained. Adoption and training are never substituted; an initiative with no observation is null, not 0.

<!-- BEGIN:07_adoption_training__by_initiative -->
| initiative_id | eligibility_rule_version | adoption_eligible | adopted | adoption_rate | training_eligible | training_completed | training_completion | training_minus_adoption | has_both_series |
|---|---|---|---|---|---|---|---|---|---|
| init-001 | elig-v1 | 416 | 350 | 0.841346 | 425 | 403 | 0.948235 | 0.106889 | true |
| init-002 | elig-v1 | 726 | 420 | 0.578512 | 705 | 683 | 0.968794 | 0.390282 | true |
| init-003 | elig-v1 | 310 | 72 | 0.232258 | 317 | 310 | 0.977918 | 0.745660 | true |
| init-004 | elig-v1 | 747 | 332 | 0.444444 | 771 | 740 | 0.959792 | 0.515348 | true |
| init-005 | elig-v1 |  |  |  | 421 | 10 | 0.023753 |  |  |
| init-006 | elig-v1 |  |  |  |  |  |  |  |  |
| init-007 | elig-v1 | 753 | 557 | 0.739708 | 739 | 724 | 0.979702 | 0.239994 | true |
| init-008 | elig-v2 | 411 | 292 | 0.710462 | 411 | 398 | 0.968370 | 0.257908 | true |
| init-009 | elig-v1 | 361 | 149 | 0.412742 | 365 | 350 | 0.958904 | 0.546162 | true |
| init-010 | elig-v1 |  |  |  | 508 | 482 | 0.948819 |  |  |
| init-011 | elig-v1 |  |  |  |  |  |  |  |  |
| init-012 | elig-v1 |  |  |  |  |  |  |  |  |
| init-013 | elig-v2 | 855 | 606 | 0.708772 | 847 | 804 | 0.949233 | 0.240461 | true |
| init-014 | elig-v1 | 427 | 98 | 0.229508 | 441 | 432 | 0.979592 | 0.750084 | true |
| init-015 | elig-v1 | 329 | 115 | 0.349544 | 340 | 333 | 0.979412 | 0.629868 | true |
| init-016 | elig-v1 | 413 | 72 | 0.174334 | 409 | 384 | 0.938875 | 0.764541 | true |
| init-017 | elig-v1 |  |  |  |  |  |  |  |  |
| init-018 | elig-v1 |  |  |  |  |  |  |  |  |
| init-019 | elig-v1 |  |  |  |  |  |  |  |  |
| init-020 | elig-v1 |  |  |  |  |  |  |  |  |
| init-021 | elig-v1 |  |  |  |  |  |  |  |  |
| init-022 | elig-v1 |  |  |  |  |  |  |  |  |
| init-023 | elig-v1 |  |  |  | 220 | 213 | 0.968182 |  |  |
| init-024 | elig-v1 |  |  |  | 315 | 161 | 0.511111 |  |  |
<!-- END:07_adoption_training__by_initiative -->

<!-- BEGIN:07_adoption_training__pooled -->
| initiatives_with_adoption | adopted | adoption_eligible | adoption_rate_pooled | initiatives_with_training | training_completed | training_eligible | training_completion_pooled |
|---|---|---|---|---|---|---|---|
| 11 | 3063 | 5748 | 0.532881 | 15 | 6427 | 7234 | 0.888443 |
<!-- END:07_adoption_training__pooled -->

<!-- BEGIN:07_adoption_training__common_population -->
| initiatives_with_both_series | adopted | adoption_eligible | adoption_rate_pooled | training_completed | training_eligible | training_completion_pooled | reached_half_adoption | not_yet_half_adoption |
|---|---|---|---|---|---|---|---|---|
| 11 | 3063 | 5748 | 0.532881 | 5561 | 5770 | 0.963778 | 5 | 6 |
<!-- END:07_adoption_training__common_population -->

<!-- BEGIN:07_adoption_training__lag_to_half_adoption -->
| initiative_id | training_90_percent_on | adoption_50_percent_on | lag_periods | periods_since_training_90_percent | training_completion_now | adoption_rate_now |
|---|---|---|---|---|---|---|
| init-001 | 2026-03-20T15:00:00Z | 2026-07-07T06:00:00Z | 4 | 7 | 0.948235 | 0.841346 |
| init-002 | 2026-03-26T15:00:00Z | 2026-09-11T12:00:00Z | 6 | 7 | 0.968794 | 0.578512 |
| init-003 | 2026-05-02T15:00:00Z |  |  | 5 | 0.977918 | 0.232258 |
| init-004 | 2026-05-18T15:00:00Z |  |  | 5 | 0.959792 | 0.444444 |
| init-007 | 2026-03-15T15:00:00Z | 2026-07-22T03:00:00Z | 4 | 7 | 0.979702 | 0.739708 |
| init-008 | 2026-03-13T15:00:00Z | 2026-08-06T19:00:00Z | 5 | 7 | 0.968370 | 0.710462 |
| init-009 | 2026-04-25T15:00:00Z |  |  | 6 | 0.958904 | 0.412742 |
| init-013 | 2026-03-17T15:00:00Z | 2026-08-01T05:00:00Z | 5 | 7 | 0.949233 | 0.708772 |
| init-014 | 2026-06-12T15:00:00Z |  |  | 4 | 0.979592 | 0.229508 |
| init-015 | 2026-05-16T15:00:00Z |  |  | 5 | 0.979412 | 0.349544 |
| init-016 | 2026-07-22T15:00:00Z |  |  | 3 | 0.938875 | 0.174334 |
<!-- END:07_adoption_training__lag_to_half_adoption -->

<!-- BEGIN:07_adoption_training__lag_summary -->
| initiatives_with_both_series | reached_half_adoption | not_yet_half_adoption | lag_periods_sorted | never_reached_half_adoption |
|---|---|---|---|---|
| 11 | 5 | 6 | 4,4,5,5,6 | init-003,init-004,init-009,init-014,init-015,init-016 |
<!-- END:07_adoption_training__lag_summary -->

## 8. Forecast revisions with the original preserved (investigation 08; D-02, D-P9-17, R9-10, DR-04, INJ-06, P09-TEST-06)
Twelve forecast versions over eight initiatives (144 rows). `init-003`'s approved forecast (version 1, **745,800.06**, 2026-03-12) is kept beside its revisions: version 2 (**598,900.05**, 2026-06-12) after April and May came in at 0.672385 and 0.678912 of it, version 3 (**534,207.54**, 2026-09-09) after June to August came in at 0.849750, 0.824670 and 0.792000 of version 2; latest minus original **-211,592.52**. Every version covers every period of the original. Two other revisions read differently: `init-004`'s version 2 lowers the total by 52,098.22 although the two periods observed by then were within 3 % of the forecast, and `init-013`'s version 2 ("a change of scope") raises it by 97,833.89 although periods 1..3 had come in 14 to 20 % below; the stored reasons, not a rule, explain them.

<!-- BEGIN:08_forecast_revisions__versions -->
| initiative_id | version_number | created_at | periods | first_period | last_period | total | reason |
|---|---|---|---|---|---|---|---|
| init-001 | 1 | 2026-01-30T10:00:00Z | 12 | 2 | 13 | 897200.01 | Approved forecast |
| init-002 | 1 | 2026-01-30T10:00:00Z | 12 | 2 | 13 | 1032399.99 | Approved forecast |
| init-003 | 1 | 2026-03-12T10:00:00Z | 12 | 3 | 14 | 745800.06 | Approved forecast |
| init-003 | 2 | 2026-06-12T10:00:00Z | 12 | 3 | 14 | 598900.05 | Revised after April and May fell short of the approved forecast |
| init-003 | 3 | 2026-09-09T10:00:00Z | 12 | 3 | 14 | 534207.54 | Revised again after June, July and August fell short of the revised forecast |
| init-004 | 1 | 2026-01-29T10:00:00Z | 12 | 5 | 16 | 676866.73 | Approved forecast |
| init-004 | 2 | 2026-08-23T10:00:00Z | 12 | 5 | 16 | 624768.51 | Revised after the first months of operation |
| init-008 | 1 | 2026-01-22T10:00:00Z | 12 | 2 | 13 | 695200.01 | Approved forecast |
| init-013 | 1 | 2026-01-26T10:00:00Z | 12 | 1 | 12 | 1409833.46 | Approved forecast |
| init-013 | 2 | 2026-06-06T10:00:00Z | 12 | 1 | 12 | 1507667.35 | Revised for a change of scope in the second wave |
| init-014 | 1 | 2026-01-22T10:00:00Z | 12 | 5 | 16 | 1390399.99 | Approved forecast |
| init-016 | 1 | 2026-01-29T10:00:00Z | 12 | 6 | 17 | 479200.01 | Approved forecast |
<!-- END:08_forecast_revisions__versions -->

<!-- BEGIN:08_forecast_revisions__original_preserved -->
| initiative_id | versions | original_rows | original_version | every_version_covers_the_original_periods | original_total | latest_minus_original |
|---|---|---|---|---|---|---|
| init-001 | 1 | 12 | 1 | true | 897200.01 | 0.00 |
| init-002 | 1 | 12 | 1 | true | 1032399.99 | 0.00 |
| init-003 | 3 | 12 | 1 | true | 745800.06 | -211592.52 |
| init-004 | 2 | 12 | 1 | true | 676866.73 | -52098.22 |
| init-008 | 1 | 12 | 1 | true | 695200.01 | 0.00 |
| init-013 | 2 | 12 | 1 | true | 1409833.46 | 97833.89 |
| init-014 | 1 | 12 | 1 | true | 1390399.99 | 0.00 |
| init-016 | 1 | 12 | 1 | true | 479200.01 | 0.00 |
<!-- END:08_forecast_revisions__original_preserved -->

<!-- BEGIN:08_forecast_revisions__init003_versions -->
| version_number | created_at | total | change_vs_original | change_vs_previous | reason |
|---|---|---|---|---|---|
| 1 | 2026-03-12T10:00:00Z | 745800.06 | 0.00 | 0.00 | Approved forecast |
| 2 | 2026-06-12T10:00:00Z | 598900.05 | -146900.01 | -146900.01 | Revised after April and May fell short of the approved forecast |
| 3 | 2026-09-09T10:00:00Z | 534207.54 | -211592.52 | -64692.51 | Revised again after June, July and August fell short of the revised forecast |
<!-- END:08_forecast_revisions__init003_versions -->

<!-- BEGIN:08_forecast_revisions__init003_by_period -->
| period_index | v1 | v2 | v3 | latest_observed | observed_over_v1 |
|---|---|---|---|---|---|
| 3 | 2825.02 | 2825.02 | 2825.02 | 1844.17 | 0.652799 |
| 4 | 8474.97 | 8474.97 | 8474.97 | 5993.50 | 0.707200 |
| 5 | 16950.03 | 13560.02 | 13560.02 | 11522.63 | 0.679800 |
| 6 | 28250.02 | 22600.02 | 22600.02 | 19017.91 | 0.673200 |
| 7 | 42375.03 | 33900.02 | 33900.02 | 26848.82 | 0.633600 |
| 8 | 59324.97 | 47459.98 | 41527.48 | 40340.98 | 0.680000 |
| 9 | 79100.02 | 63280.02 | 55370.01 |  |  |
| 10 | 101700.00 | 81360.00 | 71190.00 |  |  |
| 11 | 101700.00 | 81360.00 | 71190.00 |  |  |
| 12 | 101700.00 | 81360.00 | 71190.00 |  |  |
| 13 | 101700.00 | 81360.00 | 71190.00 |  |  |
| 14 | 101700.00 | 81360.00 | 71190.00 |  |  |
<!-- END:08_forecast_revisions__init003_by_period -->

<!-- BEGIN:08_forecast_revisions__revision_triggers -->
| initiative_id | revision | revises_version | created_at | periods_checked | periods_more_than_10_percent_below | lowest_observed_over_forecast | highest_observed_over_forecast |
|---|---|---|---|---|---|---|---|
| init-003 | 2 | 1 | 2026-06-12T10:00:00Z | 3,4 | 3,4 | 0.672385 | 0.678912 |
| init-003 | 3 | 2 | 2026-09-09T10:00:00Z | 5,6,7 | 5,6,7 | 0.792000 | 0.849750 |
| init-004 | 2 | 1 | 2026-08-23T10:00:00Z | 5,6 |  | 0.979118 | 0.999307 |
| init-013 | 2 | 1 | 2026-06-06T10:00:00Z | 1,2,3 | 1,2,3 | 0.799680 | 0.858499 |
<!-- END:08_forecast_revisions__revision_triggers -->

## 9. Dependency delays, the refused cycle, the shared specialist at capacity, deployment before the feasible start (investigation 09; D-03, D-P9-08, D-P9-15, R9-06, DR-05, INJ-07, INJ-09)
Four of the 24 initiatives are delayed by their dependencies: `init-017` by 3 periods (`d-029`), `init-018` by 7 (`d-031`), `init-019` by 10 (`d-033`), `init-020` by 6 (`d-035`). Three of them book benefits from a deployment period earlier than their feasible start, flagged **`DEPLOYMENT_BEFORE_FEASIBLE_START`**: `init-018` (deployment 18, feasible 22, 4 periods early), `init-019` (14 vs 19, 5) and `init-020` (16 vs 18, 2); the cash flow is not re-timed (D-P9-08), so their NPVs are optimistic by construction. The 40 stored dependencies form no cycle (402 paths walked, 0 cycles); the refused INJ-07 edge (init-001 to depend on init-004) would close `init-001 -> init-004 -> init-001` through the stored `d-003`. The data migration specialist `res-03` (2.00 FTE) is allocated to capacity in **periods 12..16**; the three further requests of `init-012` (0.50 FTE in periods 14, 15, 16) would take it to 2.50 and are refused `RESOURCE_OVERALLOCATED`; nothing over capacity is stored. `res-03` is not the only full resource: the change manager pool `res-02` (3.00 FTE) is at capacity in 18 consecutive periods (0..17), the test lead `res-08` in 9, the training developers `res-05` in 7; resource levelling is not implemented, so those constraints are reported, not resolved.

<!-- BEGIN:09_roadmap_capacity__dependency_delay -->
| initiative_id | requested_start | duration_periods | dependency_feasible_start | dependency_delay | binding_dependency_id | finish | deployment_period | deployment_before_feasible_start |
|---|---|---|---|---|---|---|---|---|
| init-001 | 0 | 4 | 0 | 0 |  | 4 | 1 | false |
| init-002 | 0 | 5 | 0 | 0 |  | 5 | 2 | false |
| init-003 | 1 | 6 | 1 | 0 |  | 7 | 3 | false |
| init-004 | 2 | 7 | 2 | 0 |  | 9 | 4 | false |
| init-005 | 8 | 6 | 8 | 0 |  | 14 | 10 | false |
| init-006 | 12 | 6 | 12 | 0 |  | 18 | 15 | false |
| init-007 | 0 | 3 | 0 | 0 |  | 3 | 1 | false |
| init-008 | 0 | 4 | 0 | 0 |  | 4 | 2 | false |
| init-009 | 1 | 6 | 1 | 0 |  | 7 | 3 | false |
| init-010 | 3 | 6 | 3 | 0 |  | 9 | 9 | false |
| init-011 | 9 | 5 | 9 | 0 |  | 14 | 12 | false |
| init-012 | 14 | 6 | 14 | 0 |  | 20 | 17 | false |
| init-013 | 0 | 4 | 0 | 0 |  | 4 | 1 | false |
| init-014 | 3 | 6 | 3 | 0 |  | 9 | 5 | false |
| init-015 | 2 | 6 | 2 | 0 |  | 8 | 4 | false |
| init-016 | 4 | 7 | 4 | 0 |  | 11 | 6 | false |
| init-017 | 10 | 6 | 13 | 3 | d-029 | 19 | 13 | false |
| init-018 | 15 | 6 | 22 | 7 | d-031 | 28 | 18 | true |
| init-019 | 9 | 7 | 19 | 10 | d-033 | 26 | 14 | true |
| init-020 | 12 | 8 | 18 | 6 | d-035 | 26 | 16 | true |
| init-021 | 16 | 6 | 16 | 0 |  | 22 | 19 | false |
| init-022 | 18 | 6 | 18 | 0 |  | 24 | 24 | false |
| init-023 | 6 | 12 | 6 | 0 |  | 18 | 12 | false |
| init-024 | 7 | 8 | 7 | 0 |  | 15 | 11 | false |
<!-- END:09_roadmap_capacity__dependency_delay -->

<!-- BEGIN:09_roadmap_capacity__delay_summary -->
| initiatives | delayed | not_delayed | longest_delay | dependencies | finish_to_start | start_to_start | delayed_without_a_binding_dependency |
|---|---|---|---|---|---|---|---|
| 24 | 4 | 20 | 10 | 40 | 12 | 28 | 0 |
<!-- END:09_roadmap_capacity__delay_summary -->

<!-- BEGIN:09_roadmap_capacity__deployment_before_feasible_start -->
| initiative_id | deployment_period | dependency_feasible_start | periods_early | binding_dependency_id |
|---|---|---|---|---|
| init-018 | 18 | 22 | 4 | d-031 |
| init-019 | 14 | 19 | 5 | d-033 |
| init-020 | 16 | 18 | 2 | d-035 |
<!-- END:09_roadmap_capacity__deployment_before_feasible_start -->

<!-- BEGIN:09_roadmap_capacity__cycle_check -->
| dependencies | paths_walked | cycles_found | self_dependencies | longest_chain_of_initiatives |
|---|---|---|---|---|
| 40 | 402 | 0 | 0 | 10 |
<!-- END:09_roadmap_capacity__cycle_check -->

<!-- BEGIN:09_roadmap_capacity__refused_cycle -->
| rejected_edge_initiative | rejected_edge_prerequisite | cycle_it_would_close | stored_edges_on_the_path |
|---|---|---|---|
| init-001 | init-004 | init-001 -> init-004 -> init-001 | d-003 |
<!-- END:09_roadmap_capacity__refused_cycle -->

<!-- BEGIN:09_roadmap_capacity__resource_at_capacity -->
| resource_id | capacity | period_index | allocated | headroom | initiatives |
|---|---|---|---|---|---|
| res-03 | 2.00 | 12 | 2.00 | 0.00 | init-017,init-019,init-020,init-023 |
| res-03 | 2.00 | 13 | 2.00 | 0.00 | init-017,init-019,init-023 |
| res-03 | 2.00 | 14 | 2.00 | 0.00 | init-017,init-019,init-023 |
| res-03 | 2.00 | 15 | 2.00 | 0.00 | init-017,init-019,init-023 |
| res-03 | 2.00 | 16 | 2.00 | 0.00 | init-020,init-023 |
<!-- END:09_roadmap_capacity__resource_at_capacity -->

<!-- BEGIN:09_roadmap_capacity__resources -->
| resource_id | name | capacity | unit | allocation_rows | periods_exactly_at_capacity | periods_over_capacity | first_period_at_capacity | last_period_at_capacity |
|---|---|---|---|---|---|---|---|---|
| res-01 | Process analyst pool | 6.00 | FTE | 133 | 0 | 0 |  |  |
| res-02 | Change manager pool | 3.00 | FTE | 99 | 18 | 0 | 0 | 17 |
| res-03 | Data migration specialist | 2.00 | FTE | 34 | 5 | 0 | 12 | 16 |
| res-04 | Integration engineer pool | 4.00 | FTE | 83 | 5 | 0 | 1 | 6 |
| res-05 | Training developer pool | 2.50 | FTE | 45 | 7 | 0 | 1 | 7 |
| res-06 | Finance subject-matter expert | 2.00 | FTE | 51 | 0 | 0 |  |  |
| res-07 | Operations subject-matter expert | 3.00 | FTE | 64 | 4 | 0 | 3 | 6 |
| res-08 | Test lead | 2.00 | FTE | 48 | 9 | 0 | 2 | 12 |
<!-- END:09_roadmap_capacity__resources -->

<!-- BEGIN:09_roadmap_capacity__refused_requests -->
| resource_id | initiative_id | period_index | requested | allocated_before | capacity | would_be | refused_overallocated |
|---|---|---|---|---|---|---|---|
| res-03 | init-012 | 14 | 0.50 | 2.00 | 2.00 | 2.50 | true |
| res-03 | init-012 | 15 | 0.50 | 2.00 | 2.00 | 2.50 | true |
| res-03 | init-012 | 16 | 0.50 | 2.00 | 2.00 | 2.50 | true |
<!-- END:09_roadmap_capacity__refused_requests -->

## 10. The golden known answer: NPV 5000/121 = 41.32 with both paybacks (investigation 10, on the golden database; P09-GOLD-01)
Cost 1,000 at period 0, net inflows 600 at periods 1 and 2, 10 % annual on annual periods: NPV **41.32**, exactly **5000/121**; simple payback period **2** (interpolated **1.6667**), discounted payback period **2** (interpolated **1.9167**), labelled separately; the 800.00 capacity hours of the same initiative stay out of the cash flow. The other two initiatives give -7000/121 = -57.85 (discounted payback `NOT_RECOVERED`) and -81800/121 = -676.03 (never recovers); the plain sum -83800/121 = -692.56 less the present value 7500/121 = 61.98 of the 75.00 claimed twice is the attributable **-8300/11 = -754.55**. Every figure equals `expected.json` and the hand calculation of `CALCULATION.md`.

<!-- BEGIN:10_golden_known_answer__cash_flow_init001 -->
| period_index | costs | cash_benefits | net_cash_flow | cumulative | discount_factor | discounted_cash_flow | cumulative_discounted |
|---|---|---|---|---|---|---|---|
| 0 | 1000.00 | 0.00 | -1000.00 | -1000.00 | 1.000000 | -1000.00 | -1000.00 |
| 1 | 0.00 | 600.00 | 600.00 | -400.00 | 0.909091 | 545.45 | -454.55 |
| 2 | 0.00 | 600.00 | 600.00 | 200.00 | 0.826446 | 495.87 | 41.32 |
<!-- END:10_golden_known_answer__cash_flow_init001 -->

<!-- BEGIN:10_golden_known_answer__init001_answer -->
| initiative_id | npv | npv_exact | simple_payback_period | simple_payback_interpolated | discounted_payback_period | discounted_payback_interpolated | capacity_hours_excluded |
|---|---|---|---|---|---|---|---|
| init-001 | 41.32 | 5000/121 | 2 | 1.6667 | 2 | 1.9167 | 800.00 |
<!-- END:10_golden_known_answer__init001_answer -->

<!-- BEGIN:10_golden_known_answer__initiatives -->
| initiative_id | npv | npv_exact | simple_payback_period | simple_payback_interpolated | simple_reason | discounted_payback_period | discounted_payback_interpolated | discounted_reason |
|---|---|---|---|---|---|---|---|---|
| init-001 | 41.32 | 5000/121 | 2 | 1.6667 |  | 2 | 1.9167 |  |
| init-002 | -57.85 | -7000/121 | 2 | 1.9412 |  |  |  | NOT_RECOVERED |
| init-003 | -676.03 | -81800/121 |  |  | NOT_RECOVERED |  |  | NOT_RECOVERED |
<!-- END:10_golden_known_answer__initiatives -->

<!-- BEGIN:10_golden_known_answer__portfolio -->
| scenario_id | sum_of_initiatives | double_counted_pv | attributable_npv | attributable_exact | planned_benefits | residual | attributable_benefits | planned_hours | hours_residual |
|---|---|---|---|---|---|---|---|---|---|
| scn-001 | -692.56 | 61.98 | -754.55 | -8300/11 | 2195.00 | 75.00 | 2120.00 | 800.00 | 0.00 |
<!-- END:10_golden_known_answer__portfolio -->

## 11. The proposal screen (investigation 11; D-01, D-03, D-09; P09-GOAL-01, P09-FLOW-07)
The stated screen: an initiative **carries** a cash case in `scn-025` when its NPV is above zero and both paybacks are found inside the window; otherwise it **waits**. Eighteen carry, six wait. Four of the six have **no benefit that enters the cash flow at all** (`init-006`, `init-019` and `init-021`: avoided cost with no realisation evidence and unconverted capacity; `init-009`: capacity only); two have benefits that enter but stay below cost (`init-015` 0.531465, `init-022` 0.942934). The constructed options (exact sums of the stored NPVs of `scn-025`, labelled constructed; not stored scenarios):

* **A**, `scn-025` as stored: 24 initiatives, attributable NPV **1,243,149.05** on 25,914,200.00 of planned costs, six with a negative NPV.
* **B**, the 18 that carry: **4,560,340.34**, but **4 dependencies** lead from a carrying initiative to a waiting one (`init-010` and `init-017` on `init-009`, `init-018` on `init-019`, `init-023` on `init-015`), so B cannot be delivered as planned.
* **C**, the 18 plus the prerequisites they need: 21 initiatives, **2,177,441.56**, three of them negative.
* **D**, the carrying initiatives that need no waiting prerequisite, transitively: **10 initiatives** (`init-001`, `init-002`, `init-003`, `init-004`, `init-007`, `init-008`, `init-012`, `init-013`, `init-014`, `init-016`), attributable NPV **2,876,982.64** on **11,779,550.00** of planned costs, no prerequisite outside, the shared claim of `init-001` / `init-002` inside it (double-counted PV 195,233.20, still to be explained before C07).

The screen is a judgement written down so that it can be changed; it reads plan estimates beside what has been observed and does not combine the two.

<!-- BEGIN:11_proposal_screen__initiative_screen -->
| initiative_id | npv | simple_payback_period | discounted_payback_period | cash_benefit_to_cost | capacity_hours_not_converted | avoided_cost_beside | adoption_rate | cash_realisation | cost_variance | risk_exposure | dependency_delay | screen |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| init-001 | 578533.26 | 10 | 10 | 1.573902 | 0.00 | 0.00 | 0.841346 | 1.039443 | 35261.71 | 208360.24 | 0 | CARRIES |
| init-002 | 413388.43 | 10 | 11 | 1.575197 | 0.00 | 309600.00 | 0.578512 | 1.030184 | -37445.59 | 145565.89 | 0 | CARRIES |
| init-003 | 363049.68 | 12 | 12 | 1.647398 | 0.00 | 223666.69 | 0.232258 | 0.667307 | 31430.68 | 342656.33 | 0 | CARRIES |
| init-004 | 523302.08 | 14 | 14 | 1.447479 | 0.00 | 0.00 | 0.444444 | 1.023305 | -63009.39 | 440993.63 | 0 | CARRIES |
| init-005 | 209002.21 | 19 | 19 | 1.299897 | 17682.00 | 0.00 |  |  | -59088.59 | 252616.97 | 0 | CARRIES |
| init-006 | -535631.92 |  |  | 0.000000 | 14747.32 | 211866.68 |  |  |  | 82379.87 | 0 | WAITS |
| init-007 | 415366.00 | 11 | 11 | 1.269159 | 0.00 | 697033.40 | 0.739708 |  | 23326.08 | 295112.49 | 0 | CARRIES |
| init-008 | 65253.91 | 13 | 13 | 1.114552 | 6548.48 | 0.00 | 0.710462 | 0.975795 | -37080.34 | 357251.72 | 0 | CARRIES |
| init-009 | -761535.73 |  |  | 0.000000 | 2920.48 | 0.00 | 0.412742 |  | -73360.58 | 459451.10 | 0 | WAITS |
| init-010 | 423409.74 | 18 | 18 | 1.349980 | 8034.09 | 636566.62 |  |  | 121733.80 | 305503.93 | 0 | CARRIES |
| init-011 | 84012.76 | 21 | 21 | 1.249724 | 3913.50 | 0.00 |  |  |  | 189094.36 | 0 | CARRIES |
| init-012 | 126524.02 | 27 | 27 | 1.199835 | 22419.67 | 312083.36 |  |  |  | 175983.24 | 0 | CARRIES |
| init-013 | 463582.30 | 11 | 11 | 1.334857 | 0.00 | 0.00 | 0.708772 | 0.855768 | 170496.08 | 468552.25 | 0 | CARRIES |
| init-014 | 76930.78 | 15 | 16 | 1.114415 | 12213.60 | 417200.00 | 0.229508 | 0.747375 | 84441.17 | 349000.46 | 0 | CARRIES |
| init-015 | -618556.03 |  |  | 0.531465 | 13512.08 | 207200.00 | 0.349544 | 0.961240 | 93702.86 | 386126.29 | 0 | WAITS |
| init-016 | 46285.40 | 17 | 17 | 1.113924 | 7309.44 | 0.00 | 0.174334 | 0.877626 | -36605.56 | 221238.35 | 0 | CARRIES |
| init-017 | 93546.29 | 22 | 23 | 1.249659 | 7858.29 | 0.00 |  |  |  | 307078.26 | 3 | CARRIES |
| init-018 | 15040.08 | 28 | 28 | 1.071666 | 0.00 | 0.00 |  |  |  | 175392.44 | 7 | CARRIES |
| init-019 | -1002807.01 |  |  | 0.000000 | 1689.33 | 410200.03 |  |  |  | 425891.03 | 10 | WAITS |
| init-020 | 112711.77 | 27 | 27 | 1.200052 | 5282.67 | 0.00 |  |  |  | 333380.00 | 6 | CARRIES |
| init-021 | -337229.75 |  |  | 0.000000 | 5886.00 | 117900.00 |  |  |  | 67682.66 | 0 | WAITS |
| init-022 | -61430.84 |  |  | 0.942934 | 7216.67 | 0.00 |  |  |  | 327861.93 | 0 | WAITS |
| init-023 | 515502.07 | 22 | 22 | 1.249945 | 0.00 | 0.00 |  |  |  | 908693.93 | 0 | CARRIES |
| init-024 | 230132.79 | 20 | 21 | 1.250110 | 7812.00 | 482066.70 |  |  |  | 259912.21 | 0 | CARRIES |
<!-- END:11_proposal_screen__initiative_screen -->

<!-- BEGIN:11_proposal_screen__waiting -->
| initiative_id | npv | cash_benefit_to_cost | planned_costs | capacity_hours_not_converted | avoided_cost_beside | reason |
|---|---|---|---|---|---|---|
| init-006 | -535631.92 | 0.000000 | 588850.00 | 14747.32 | 211866.68 | NO_BENEFIT_ENTERS_THE_CASH_FLOW |
| init-009 | -761535.73 | 0.000000 | 775800.00 | 2920.48 | 0.00 | NO_BENEFIT_ENTERS_THE_CASH_FLOW |
| init-015 | -618556.03 | 0.531465 | 1299050.00 | 13512.08 | 207200.00 | BENEFITS_ENTER_BUT_STAY_BELOW_COST |
| init-019 | -1002807.01 | 0.000000 | 1093600.00 | 1689.33 | 410200.03 | NO_BENEFIT_ENTERS_THE_CASH_FLOW |
| init-021 | -337229.75 | 0.000000 | 379200.00 | 5886.00 | 117900.00 | NO_BENEFIT_ENTERS_THE_CASH_FLOW |
| init-022 | -61430.84 | 0.942934 | 684000.00 | 7216.67 | 0.00 | BENEFITS_ENTER_BUT_STAY_BELOW_COST |
<!-- END:11_proposal_screen__waiting -->

<!-- BEGIN:11_proposal_screen__options -->
| option_id | label | kind | initiatives | planned_costs | sum_of_initiatives | double_counted_pv | attributable_npv | prerequisites_outside_the_option | shared_claims_crossing_the_boundary | initiatives_with_a_negative_npv | members |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | all 24 initiatives of scn-025 | stored scenario | 24 | 25914200.00 | 1438382.25 | 195233.20 | 1243149.05 | 0 | 0 | 6 |  |
| B | the initiatives that carry a cash case | constructed | 18 | 21093700.00 | 4755573.54 | 195233.20 | 4560340.34 | 4 | 0 | 0 | init-001,init-002,init-003,init-004,init-005,init-007,init-008,init-010,init-011,init-012,init-013,init-014,init-016,init-017,init-018,init-020,init-023,init-024 |
| C | the carrying initiatives and the prerequisites they depend on | constructed | 21 | 24262150.00 | 2372674.76 | 195233.20 | 2177441.56 | 0 | 0 | 3 | init-001,init-002,init-003,init-004,init-005,init-007,init-008,init-009,init-010,init-011,init-012,init-013,init-014,init-015,init-016,init-017,init-018,init-019,init-020,init-023,init-024 |
| D | the carrying initiatives that need no waiting prerequisite | constructed | 10 | 11779550.00 | 3072215.84 | 195233.20 | 2876982.64 | 0 | 0 | 0 | init-001,init-002,init-003,init-004,init-007,init-008,init-012,init-013,init-014,init-016 |
<!-- END:11_proposal_screen__options -->

<!-- BEGIN:11_proposal_screen__dependency_ties -->
| dependency_id | initiative_id | prerequisite_id | dependency_type | lag_periods | initiative_npv | prerequisite_npv |
|---|---|---|---|---|---|---|
| d-016 | init-010 | init-009 | start_to_start | 0 | 423409.74 | -761535.73 |
| d-027 | init-017 | init-009 | finish_to_start | 3 | 93546.29 | -761535.73 |
| d-031 | init-018 | init-019 | start_to_start | 3 | 15040.08 | -1002807.01 |
| d-038 | init-023 | init-015 | start_to_start | 0 | 515502.07 | -618556.03 |
<!-- END:11_proposal_screen__dependency_ties -->

## 12. What the figures do not show
* The NPVs describe the **twelve-period benefit window** each stream has (D-07, R9-17), discounted over each scenario's 24- or 36-period horizon; nothing after the window is planned.
* The double count is the contract's rule (a shared key in one period); a claim on the same capacity under two different keys would not be caught, and the data carries one shared key.
* Observed benefit realisation is not attribution: the trend beside it is a recorded assumption of the plan, and the synthetic truth of the attributable share (`synthetic_truth` in the manifest) is never read by the analysis.
* The roadmap reports resource limits and dependency delays beside the cash flows; it does not re-time them, and no resource levelling exists (D-06 gaps).

## 13. Reconciliation
Each row compares the analysis SQL with one to three independent sources; equality is on the printed text (2-place money, 4-place paybacks and hours, 6-place proportions, exact rationals as `n/d`), with digests for the families of leaves. Families:
* **A** (golden): the analysis model's 167 leaves on the golden database equal the reference SQL, the Python domain and `expected.json` leaf for leaf, family by family; investigation 10 equals `expected.json` and the hand answers of `CALCULATION.md`; the domain's whole `result.golden()` equals the file.
* **B** (snapshot): the analysis model's **48,476 leaves** (cash flow of every period, NPV, paybacks, beside-the-flow totals, capacity released, cost variance, realisation, double count and portfolio NPV of every scenario and initiative; adoption, training, roadmap; summary) equal `data/sql/reference_metrics.sql` and the Python domain, scenario by scenario and family by family, and the headline result sets equal the domain row by row (each `scn-025` initiative's NPV with its exact rational, both paybacks, the ledger and the portfolio NPV of every scenario, adoption, training and the roadmap of every initiative, the forecast versions, the resource view and the deployment warnings). The 6-place NPV of the reference SQL is within its documented 0.000001 USD of the exact rational for every `scn-025` initiative.
* **C**: every one of the 56 result sets equals, cell by cell, the plain-Python recomputation of `data/sql/analysis/python_side.py` from the raw JSON (no SQL, no domain code, Fractions only).
* **D**: the designed relationships DR-01..DR-07 of the injection manifest, the 30 per-scenario and 24 per-initiative statistics of `manifest.json`, the three deployment warnings, and the 63 dataset checks of INJ-01..INJ-12 whose paths the analysis leaves cover (the other 34 check paths are lists or identities that only the domain tests read), plus the refused cycle of EV-07 and the single key of INJ-11.
* **E**: the BI measures recomputed from the CSV facts alone (`artifacts/bi/`) equal the analysis and the domain for all 30 scenarios and the pooled people measures; nothing is withheld silently.

Mutation check: the sources are independent in code (the analysis SQL, the reference SQL, the Python domain and `python_side.py` share no code), so a one-leaf change to any of them, or to a stored figure, breaks at least one row; this was exercised while the package was written: the workbook's first reference for the attributable benefits was the difference of two rounded figures and failed its check on `scn-006` by 0.01, and it was replaced by the domain's own figure rather than by a wider tolerance.

<!-- BEGIN:reconciliation -->
| check | analysis_sql | second_source | third_source | fourth_source | equal |
|---|---|---|---|---|---|
| A golden whole shape of expected.json: the Python domain's result.golden() vs the file (digest of all leaves) | e96ee6e3e8b7107d | e96ee6e3e8b7107d |  |  | true |
| A golden leaves of the analysis model that are not in the reference SQL output (count) | 0 | 0 |  |  | true |
| A golden leaves of the analysis model that are not leaves of expected.json (count) | 0 | 0 |  |  | true |
| A golden cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-001: 54 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | 116b8260de9285c3 | 116b8260de9285c3 | 116b8260de9285c3 | 116b8260de9285c3 | true |
| A golden NPV in scn-001: 3 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | c8639183f1bf687a | c8639183f1bf687a | c8639183f1bf687a | c8639183f1bf687a | true |
| A golden simple and discounted payback (period, interpolation, reason) in scn-001: 18 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | 7b85f40b2f3289a7 | 7b85f40b2f3289a7 | 7b85f40b2f3289a7 | 7b85f40b2f3289a7 | true |
| A golden beside the cash flow (capacity hours not converted, avoided cost) in scn-001: 6 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | 1287f1e685c21d18 | 1287f1e685c21d18 | 1287f1e685c21d18 | 1287f1e685c21d18 | true |
| A golden capacity released in scn-001: 6 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | f790ad4bff7253af | f790ad4bff7253af | f790ad4bff7253af | f790ad4bff7253af | true |
| A golden cost variance in scn-001: 15 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | af608f147d6eee3a | af608f147d6eee3a | af608f147d6eee3a | af608f147d6eee3a | true |
| A golden benefit realisation within a type in scn-001: 20 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | 171d866e481663a9 | 171d866e481663a9 | 171d866e481663a9 | 171d866e481663a9 | true |
| A golden double count (money and hours) in scn-001: 8 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | ff45b4855a8aff71 | ff45b4855a8aff71 | ff45b4855a8aff71 | ff45b4855a8aff71 | true |
| A golden portfolio NPV (attributable and plain sum) in scn-001: 2 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | c9023d4c1068e80f | c9023d4c1068e80f | c9023d4c1068e80f | c9023d4c1068e80f | true |
| A golden adoption: 9 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | f8e5ad89de45d703 | f8e5ad89de45d703 | f8e5ad89de45d703 | f8e5ad89de45d703 | true |
| A golden training completion: 9 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | 30f0bd9b9fb20be8 | 30f0bd9b9fb20be8 | 30f0bd9b9fb20be8 | 30f0bd9b9fb20be8 | true |
| A golden roadmap (feasible start, delay, binding dependency): 9 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | f2a3467d8254060f | f2a3467d8254060f | f2a3467d8254060f | f2a3467d8254060f | true |
| A golden summary pools: 8 leaves (analysis leaves vs reference SQL vs Python domain vs expected.json, digest) | c42bf3e141d6ca9a | c42bf3e141d6ca9a | c42bf3e141d6ca9a | c42bf3e141d6ca9a | true |
| A golden init-001 NPV / exact / simple period / simple interpolated / discounted period / discounted interpolated / hours excluded (10 vs expected.json vs the spec's hand answer) | 41.32/5000/121/2/1.6667/2/1.9167/800.00 | 41.32/5000/121/2/1.6667/2/1.9167/800.00 | 41.32/5000/121/2/1.6667/2/1.9167/800.00 |  | true |
| A golden init-001 cash flow period 0: costs / benefits / net / cumulative / discount factor / discounted / cumulative discounted (10 vs expected.json) | 1000.00/0.00/-1000.00/-1000.00/1.000000/-1000.00/-1000.00 | 1000.00/0.00/-1000.00/-1000.00/1.000000/-1000.00/-1000.00 |  |  | true |
| A golden init-001 cash flow period 1: costs / benefits / net / cumulative / discount factor / discounted / cumulative discounted (10 vs expected.json) | 0.00/600.00/600.00/-400.00/0.909091/545.45/-454.55 | 0.00/600.00/600.00/-400.00/0.909091/545.45/-454.55 |  |  | true |
| A golden init-001 cash flow period 2: costs / benefits / net / cumulative / discount factor / discounted / cumulative discounted (10 vs expected.json) | 0.00/600.00/600.00/200.00/0.826446/495.87/41.32 | 0.00/600.00/600.00/200.00/0.826446/495.87/41.32 |  |  | true |
| A golden init-001 NPV / exact / both paybacks and reasons (10 vs expected.json; NPV vs CALCULATION.md parts a-c) | 41.32/5000/121/2/1.6667//2/1.9167/ | 41.32/5000/121/2/1.6667//2/1.9167/ |  |  | true |
| A golden init-001 NPV and exact rational (10 vs the hand answer) | 41.32/5000/121 | 41.32/5000/121 |  |  | true |
| A golden init-002 NPV / exact / both paybacks and reasons (10 vs expected.json; NPV vs CALCULATION.md parts a-c) | -57.85/-7000/121/2/1.9412////NOT_RECOVERED | -57.85/-7000/121/2/1.9412////NOT_RECOVERED |  |  | true |
| A golden init-002 NPV and exact rational (10 vs the hand answer) | -57.85/-7000/121 | -57.85/-7000/121 |  |  | true |
| A golden init-003 NPV / exact / both paybacks and reasons (10 vs expected.json; NPV vs CALCULATION.md parts a-c) | -676.03/-81800/121///NOT_RECOVERED///NOT_RECOVERED | -676.03/-81800/121///NOT_RECOVERED///NOT_RECOVERED |  |  | true |
| A golden init-003 NPV and exact rational (10 vs the hand answer) | -676.03/-81800/121 | -676.03/-81800/121 |  |  | true |
| A golden portfolio: plain sum / double-counted PV / attributable NPV / exact / planned / residual / attributable benefits / hours / hours residual (10 vs expected.json vs the hand answer) | -692.56/61.98/-754.55/-8300/11/2195.00/75.00/2120.00/800.00/0.00 | -692.56/61.98/-754.55/-8300/11/2195.00/75.00/2120.00/800.00/0.00 | -692.56/61.98/-754.55/-8300/11/2195.00/75.00/2120.00/800.00/0.00 |  | true |
| B loaded row counts equal the manifest row_counts (every entity) | 5e28dc49360bf9c0 | 5e28dc49360bf9c0 |  |  | true |
| B leaves of the analysis model that are not in the reference SQL output (count) | 0 | 0 |  |  | true |
| B leaves of the analysis model that are not leaves of the domain's metrics tree (count) | 0 | 0 |  |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-001: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 5ed5991ee5ae2d92 | 5ed5991ee5ae2d92 | 5ed5991ee5ae2d92 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-002: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 7ee29e2ef611421b | 7ee29e2ef611421b | 7ee29e2ef611421b |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-003: 864 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0285ab6998ff4118 | 0285ab6998ff4118 | 0285ab6998ff4118 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-004: 864 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f1b4725fed876580 | f1b4725fed876580 | f1b4725fed876580 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-005: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2d17ded24cfdc344 | 2d17ded24cfdc344 | 2d17ded24cfdc344 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-006: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b801347f4d0581f2 | b801347f4d0581f2 | b801347f4d0581f2 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-007: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4770a85336c30d71 | 4770a85336c30d71 | 4770a85336c30d71 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-008: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0373551d8c7a6e06 | 0373551d8c7a6e06 | 0373551d8c7a6e06 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-009: 864 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 48d4e81ee421e40b | 48d4e81ee421e40b | 48d4e81ee421e40b |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-010: 432 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 1fb7fd45d95efea6 | 1fb7fd45d95efea6 | 1fb7fd45d95efea6 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-011: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e39b320282949089 | e39b320282949089 | e39b320282949089 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-012: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a26425b9523c9b0f | a26425b9523c9b0f | a26425b9523c9b0f |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-013: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 7be2292f62bd0b5e | 7be2292f62bd0b5e | 7be2292f62bd0b5e |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-014: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 42633002913faac3 | 42633002913faac3 | 42633002913faac3 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-015: 864 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9acaa92335c850de | 9acaa92335c850de | 9acaa92335c850de |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-016: 648 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b5350e31996bb7b8 | b5350e31996bb7b8 | b5350e31996bb7b8 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-017: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e23fa9d016db1b11 | e23fa9d016db1b11 | e23fa9d016db1b11 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-018: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | df07615613c0f91c | df07615613c0f91c | df07615613c0f91c |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-019: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e1adf91d382e7a62 | e1adf91d382e7a62 | e1adf91d382e7a62 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-020: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 50835dd05338f35d | 50835dd05338f35d | 50835dd05338f35d |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-021: 864 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c9e4a2278e0d56a4 | c9e4a2278e0d56a4 | c9e4a2278e0d56a4 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-022: 432 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 01a022cd7cde991a | 01a022cd7cde991a | 01a022cd7cde991a |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-023: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 26a973c603d0fd59 | 26a973c603d0fd59 | 26a973c603d0fd59 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-024: 1296 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 1c05f4e8d96bd4a3 | 1c05f4e8d96bd4a3 | 1c05f4e8d96bd4a3 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-025: 5184 leaves (analysis leaves vs reference SQL vs Python domain, digest) | cbb52d4cd3f4fb0a | cbb52d4cd3f4fb0a | cbb52d4cd3f4fb0a |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-026: 4968 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 135d8c22dab74d97 | 135d8c22dab74d97 | 135d8c22dab74d97 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-027: 720 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 10f05780558d746b | 10f05780558d746b | 10f05780558d746b |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-028: 1512 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 94a19f7eec9d6d2f | 94a19f7eec9d6d2f | 94a19f7eec9d6d2f |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-029: 2160 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 00314b3a4fa4d6d1 | 00314b3a4fa4d6d1 | 00314b3a4fa4d6d1 |  | true |
| B snapshot cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted) in scn-030: 2160 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 7a1948f6bb06bd06 | 7a1948f6bb06bd06 | 7a1948f6bb06bd06 |  | true |
| B snapshot NPV in scn-001: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a5e1d4696a096d8a | a5e1d4696a096d8a | a5e1d4696a096d8a |  | true |
| B snapshot NPV in scn-002: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f7d88133ae7afebc | f7d88133ae7afebc | f7d88133ae7afebc |  | true |
| B snapshot NPV in scn-003: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 6f17430cd1917df7 | 6f17430cd1917df7 | 6f17430cd1917df7 |  | true |
| B snapshot NPV in scn-004: 4 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 07db537926e26ed9 | 07db537926e26ed9 | 07db537926e26ed9 |  | true |
| B snapshot NPV in scn-005: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9c3447a9705b91c2 | 9c3447a9705b91c2 | 9c3447a9705b91c2 |  | true |
| B snapshot NPV in scn-006: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 894ac66dccc6e23d | 894ac66dccc6e23d | 894ac66dccc6e23d |  | true |
| B snapshot NPV in scn-007: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 5d9a698ae6409d87 | 5d9a698ae6409d87 | 5d9a698ae6409d87 |  | true |
| B snapshot NPV in scn-008: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | d1b1f0328a0ae96f | d1b1f0328a0ae96f | d1b1f0328a0ae96f |  | true |
| B snapshot NPV in scn-009: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 47e1a74000b3a816 | 47e1a74000b3a816 | 47e1a74000b3a816 |  | true |
| B snapshot NPV in scn-010: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | d1c893d6fb56e767 | d1c893d6fb56e767 | d1c893d6fb56e767 |  | true |
| B snapshot NPV in scn-011: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f69ddd2b8aa10f79 | f69ddd2b8aa10f79 | f69ddd2b8aa10f79 |  | true |
| B snapshot NPV in scn-012: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c2b422271e9f844c | c2b422271e9f844c | c2b422271e9f844c |  | true |
| B snapshot NPV in scn-013: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 52b6f7e836a007f7 | 52b6f7e836a007f7 | 52b6f7e836a007f7 |  | true |
| B snapshot NPV in scn-014: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | ab7bad3e9d054ca5 | ab7bad3e9d054ca5 | ab7bad3e9d054ca5 |  | true |
| B snapshot NPV in scn-015: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | ebcb5057225b7e75 | ebcb5057225b7e75 | ebcb5057225b7e75 |  | true |
| B snapshot NPV in scn-016: 3 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 236b6ecd46676e8c | 236b6ecd46676e8c | 236b6ecd46676e8c |  | true |
| B snapshot NPV in scn-017: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | d4b044a5c6f4f1a2 | d4b044a5c6f4f1a2 | d4b044a5c6f4f1a2 |  | true |
| B snapshot NPV in scn-018: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 65eb47ba976c553b | 65eb47ba976c553b | 65eb47ba976c553b |  | true |
| B snapshot NPV in scn-019: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 532159b1d9a891af | 532159b1d9a891af | 532159b1d9a891af |  | true |
| B snapshot NPV in scn-020: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 47e7f17b233b5c87 | 47e7f17b233b5c87 | 47e7f17b233b5c87 |  | true |
| B snapshot NPV in scn-021: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c88fa825eba47576 | c88fa825eba47576 | c88fa825eba47576 |  | true |
| B snapshot NPV in scn-022: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0b535acfffd35b74 | 0b535acfffd35b74 | 0b535acfffd35b74 |  | true |
| B snapshot NPV in scn-023: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a5b10a3f77b4d641 | a5b10a3f77b4d641 | a5b10a3f77b4d641 |  | true |
| B snapshot NPV in scn-024: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 369ae1676093e820 | 369ae1676093e820 | 369ae1676093e820 |  | true |
| B snapshot NPV in scn-025: 24 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b70e8451ba5f8acd | b70e8451ba5f8acd | b70e8451ba5f8acd |  | true |
| B snapshot NPV in scn-026: 23 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c863a6299b7c9483 | c863a6299b7c9483 | c863a6299b7c9483 |  | true |
| B snapshot NPV in scn-027: 5 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f6277c4fcf2c96c5 | f6277c4fcf2c96c5 | f6277c4fcf2c96c5 |  | true |
| B snapshot NPV in scn-028: 7 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e3189d8824294835 | e3189d8824294835 | e3189d8824294835 |  | true |
| B snapshot NPV in scn-029: 10 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e55f610dd1dc9535 | e55f610dd1dc9535 | e55f610dd1dc9535 |  | true |
| B snapshot NPV in scn-030: 10 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 06ad7ddfc131d7dc | 06ad7ddfc131d7dc | 06ad7ddfc131d7dc |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-001: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 762e5a4980776b91 | 762e5a4980776b91 | 762e5a4980776b91 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-002: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 7d454b8bd76bdc2a | 7d454b8bd76bdc2a | 7d454b8bd76bdc2a |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-003: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2d4b4f9706f30be2 | 2d4b4f9706f30be2 | 2d4b4f9706f30be2 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-004: 24 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 061d8f9251ebf0ac | 061d8f9251ebf0ac | 061d8f9251ebf0ac |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-005: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 12211fa8ea317e2d | 12211fa8ea317e2d | 12211fa8ea317e2d |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-006: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 7eab3168641063f0 | 7eab3168641063f0 | 7eab3168641063f0 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-007: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a320a9e135bfc1db | a320a9e135bfc1db | a320a9e135bfc1db |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-008: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b5f4d815481c0d91 | b5f4d815481c0d91 | b5f4d815481c0d91 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-009: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0f6ec4874dcf2701 | 0f6ec4874dcf2701 | 0f6ec4874dcf2701 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-010: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 41c137fc982d33b7 | 41c137fc982d33b7 | 41c137fc982d33b7 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-011: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 888d9e53555b6dc4 | 888d9e53555b6dc4 | 888d9e53555b6dc4 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-012: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 647c435bf871a70a | 647c435bf871a70a | 647c435bf871a70a |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-013: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4cd7e0630118d30e | 4cd7e0630118d30e | 4cd7e0630118d30e |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-014: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 5f9c7c1938791348 | 5f9c7c1938791348 | 5f9c7c1938791348 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-015: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 29ce4914634395ed | 29ce4914634395ed | 29ce4914634395ed |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-016: 18 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 00853af197fd106c | 00853af197fd106c | 00853af197fd106c |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-017: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 8282af679281b797 | 8282af679281b797 | 8282af679281b797 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-018: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 3139438070606a03 | 3139438070606a03 | 3139438070606a03 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-019: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2bebc838332ab3c2 | 2bebc838332ab3c2 | 2bebc838332ab3c2 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-020: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4037865757a2dcea | 4037865757a2dcea | 4037865757a2dcea |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-021: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 570da98f1a442a7e | 570da98f1a442a7e | 570da98f1a442a7e |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-022: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 5e92cf1d1730d54c | 5e92cf1d1730d54c | 5e92cf1d1730d54c |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-023: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2ee6dd47f51e8e55 | 2ee6dd47f51e8e55 | 2ee6dd47f51e8e55 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-024: 36 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e9170940d7c1ab9b | e9170940d7c1ab9b | e9170940d7c1ab9b |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-025: 144 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e71e966695258e9a | e71e966695258e9a | e71e966695258e9a |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-026: 138 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 90608608d4b16f35 | 90608608d4b16f35 | 90608608d4b16f35 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-027: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9dd18f841ac6c040 | 9dd18f841ac6c040 | 9dd18f841ac6c040 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-028: 42 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2d1d945d6c8d9006 | 2d1d945d6c8d9006 | 2d1d945d6c8d9006 |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-029: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 99c354398e460c9a | 99c354398e460c9a | 99c354398e460c9a |  | true |
| B snapshot simple and discounted payback (period, interpolation, reason) in scn-030: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 6eafa292e0cceaf3 | 6eafa292e0cceaf3 | 6eafa292e0cceaf3 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-001: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0e1706d6789dff6a | 0e1706d6789dff6a | 0e1706d6789dff6a |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-002: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f2fac67d4ef25aff | f2fac67d4ef25aff | f2fac67d4ef25aff |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-003: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e220f35ae71eebcf | e220f35ae71eebcf | e220f35ae71eebcf |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-004: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0de2040dd38f8321 | 0de2040dd38f8321 | 0de2040dd38f8321 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-005: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 99a274e20da098c1 | 99a274e20da098c1 | 99a274e20da098c1 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-006: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 80397cd47abc1af8 | 80397cd47abc1af8 | 80397cd47abc1af8 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-007: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 6e5cf42055bdf405 | 6e5cf42055bdf405 | 6e5cf42055bdf405 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-008: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 57966f3954c9125f | 57966f3954c9125f | 57966f3954c9125f |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-009: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e8d8e1151d1e69bb | e8d8e1151d1e69bb | e8d8e1151d1e69bb |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-010: 4 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 7d52224c9466845c | 7d52224c9466845c | 7d52224c9466845c |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-011: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a9cfd520508e836d | a9cfd520508e836d | a9cfd520508e836d |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-012: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 496cb9bcd7a91903 | 496cb9bcd7a91903 | 496cb9bcd7a91903 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-013: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 488bd44c5d6e7e49 | 488bd44c5d6e7e49 | 488bd44c5d6e7e49 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-014: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 812cf2c569ed2b90 | 812cf2c569ed2b90 | 812cf2c569ed2b90 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-015: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 140191a994b4c540 | 140191a994b4c540 | 140191a994b4c540 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-016: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 71655efa7907b852 | 71655efa7907b852 | 71655efa7907b852 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-017: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 37a6fd8adb3353c6 | 37a6fd8adb3353c6 | 37a6fd8adb3353c6 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-018: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 33410cfd2d53497d | 33410cfd2d53497d | 33410cfd2d53497d |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-019: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 700518f32ce2e5b3 | 700518f32ce2e5b3 | 700518f32ce2e5b3 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-020: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | df09248fe88d4adb | df09248fe88d4adb | df09248fe88d4adb |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-021: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c36422f6e9811b14 | c36422f6e9811b14 | c36422f6e9811b14 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-022: 4 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9331306020c42b2d | 9331306020c42b2d | 9331306020c42b2d |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-023: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4d6acc0e4bdf8793 | 4d6acc0e4bdf8793 | 4d6acc0e4bdf8793 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-024: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 76e3839f63e7e413 | 76e3839f63e7e413 | 76e3839f63e7e413 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-025: 48 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 929f4723b2ef2f9e | 929f4723b2ef2f9e | 929f4723b2ef2f9e |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-026: 46 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a96656c709a5aca0 | a96656c709a5aca0 | a96656c709a5aca0 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-027: 10 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 51d9f9614c869212 | 51d9f9614c869212 | 51d9f9614c869212 |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-028: 14 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e6b52ad1faa55efa | e6b52ad1faa55efa | e6b52ad1faa55efa |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-029: 20 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c405619b0d270fed | c405619b0d270fed | c405619b0d270fed |  | true |
| B snapshot beside the cash flow (capacity hours not converted, avoided cost) in scn-030: 20 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9ef112cd869f382e | 9ef112cd869f382e | 9ef112cd869f382e |  | true |
| B snapshot capacity released in scn-001: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 80a166cde17d6f79 | 80a166cde17d6f79 | 80a166cde17d6f79 |  | true |
| B snapshot capacity released in scn-002: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | fea16830213603c3 | fea16830213603c3 | fea16830213603c3 |  | true |
| B snapshot capacity released in scn-003: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c0b3cb70f6e00b7f | c0b3cb70f6e00b7f | c0b3cb70f6e00b7f |  | true |
| B snapshot capacity released in scn-004: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | aaa4a7d9001ac6f6 | aaa4a7d9001ac6f6 | aaa4a7d9001ac6f6 |  | true |
| B snapshot capacity released in scn-005: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a68099adf8ed436d | a68099adf8ed436d | a68099adf8ed436d |  | true |
| B snapshot capacity released in scn-006: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | ad573d3d06589b07 | ad573d3d06589b07 | ad573d3d06589b07 |  | true |
| B snapshot capacity released in scn-007: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 3ad963d7a23e24d3 | 3ad963d7a23e24d3 | 3ad963d7a23e24d3 |  | true |
| B snapshot capacity released in scn-008: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 8b3ac408f8cb83bf | 8b3ac408f8cb83bf | 8b3ac408f8cb83bf |  | true |
| B snapshot capacity released in scn-009: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2cd13074783c194c | 2cd13074783c194c | 2cd13074783c194c |  | true |
| B snapshot capacity released in scn-010: 4 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 8bb2f82541c07b09 | 8bb2f82541c07b09 | 8bb2f82541c07b09 |  | true |
| B snapshot capacity released in scn-011: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 15faa7bc87eaecc2 | 15faa7bc87eaecc2 | 15faa7bc87eaecc2 |  | true |
| B snapshot capacity released in scn-012: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 1222cc69286ac075 | 1222cc69286ac075 | 1222cc69286ac075 |  | true |
| B snapshot capacity released in scn-013: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b53ba0555b92b7ee | b53ba0555b92b7ee | b53ba0555b92b7ee |  | true |
| B snapshot capacity released in scn-014: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f7c0e18298a1852 | 4f7c0e18298a1852 | 4f7c0e18298a1852 |  | true |
| B snapshot capacity released in scn-015: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 31524f27db3c9cbb | 31524f27db3c9cbb | 31524f27db3c9cbb |  | true |
| B snapshot capacity released in scn-016: 6 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 87f9ba5f515ccd1a | 87f9ba5f515ccd1a | 87f9ba5f515ccd1a |  | true |
| B snapshot capacity released in scn-017: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 99530ac137f6984d | 99530ac137f6984d | 99530ac137f6984d |  | true |
| B snapshot capacity released in scn-018: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e7eb8a4ffd2c55c6 | e7eb8a4ffd2c55c6 | e7eb8a4ffd2c55c6 |  | true |
| B snapshot capacity released in scn-019: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | af87c9044ac250e7 | af87c9044ac250e7 | af87c9044ac250e7 |  | true |
| B snapshot capacity released in scn-020: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 624cf5e843e64c88 | 624cf5e843e64c88 | 624cf5e843e64c88 |  | true |
| B snapshot capacity released in scn-021: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 3d6550641fde81a1 | 3d6550641fde81a1 | 3d6550641fde81a1 |  | true |
| B snapshot capacity released in scn-022: 4 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 1d74eb04269affce | 1d74eb04269affce | 1d74eb04269affce |  | true |
| B snapshot capacity released in scn-023: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 74488f0a11353411 | 74488f0a11353411 | 74488f0a11353411 |  | true |
| B snapshot capacity released in scn-024: 12 leaves (analysis leaves vs reference SQL vs Python domain, digest) | d29864483dbaafca | d29864483dbaafca | d29864483dbaafca |  | true |
| B snapshot capacity released in scn-025: 48 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c35183a52d6f420f | c35183a52d6f420f | c35183a52d6f420f |  | true |
| B snapshot capacity released in scn-026: 46 leaves (analysis leaves vs reference SQL vs Python domain, digest) | bb193d81414f3276 | bb193d81414f3276 | bb193d81414f3276 |  | true |
| B snapshot capacity released in scn-027: 10 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c2c91b3ba982e93c | c2c91b3ba982e93c | c2c91b3ba982e93c |  | true |
| B snapshot capacity released in scn-028: 14 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 825e3f4a9618ecb8 | 825e3f4a9618ecb8 | 825e3f4a9618ecb8 |  | true |
| B snapshot capacity released in scn-029: 20 leaves (analysis leaves vs reference SQL vs Python domain, digest) | cb1fdaa8b26ad726 | cb1fdaa8b26ad726 | cb1fdaa8b26ad726 |  | true |
| B snapshot capacity released in scn-030: 20 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9e415ce67e046319 | 9e415ce67e046319 | 9e415ce67e046319 |  | true |
| B snapshot cost variance in scn-001: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 6c81af20c71c203a | 6c81af20c71c203a | 6c81af20c71c203a |  | true |
| B snapshot cost variance in scn-002: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 6da29223b4ccda69 | 6da29223b4ccda69 | 6da29223b4ccda69 |  | true |
| B snapshot cost variance in scn-003: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | af225cd1717be516 | af225cd1717be516 | af225cd1717be516 |  | true |
| B snapshot cost variance in scn-004: 20 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9f8ef35eadddc747 | 9f8ef35eadddc747 | 9f8ef35eadddc747 |  | true |
| B snapshot cost variance in scn-005: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c2399909ec52485e | c2399909ec52485e | c2399909ec52485e |  | true |
| B snapshot cost variance in scn-006: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e12d295186419885 | e12d295186419885 | e12d295186419885 |  | true |
| B snapshot cost variance in scn-007: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | db7f53b176d7a57a | db7f53b176d7a57a | db7f53b176d7a57a |  | true |
| B snapshot cost variance in scn-008: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a25d744d26f5a26e | a25d744d26f5a26e | a25d744d26f5a26e |  | true |
| B snapshot cost variance in scn-009: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c5a65e9f3a219284 | c5a65e9f3a219284 | c5a65e9f3a219284 |  | true |
| B snapshot cost variance in scn-010: 10 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 939839142768e0bb | 939839142768e0bb | 939839142768e0bb |  | true |
| B snapshot cost variance in scn-011: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 243abd13210ecfe0 | 243abd13210ecfe0 | 243abd13210ecfe0 |  | true |
| B snapshot cost variance in scn-012: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 5af26869eaa7df3a | 5af26869eaa7df3a | 5af26869eaa7df3a |  | true |
| B snapshot cost variance in scn-013: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | fbfab096a813e7ab | fbfab096a813e7ab | fbfab096a813e7ab |  | true |
| B snapshot cost variance in scn-014: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9f9b3c201d480940 | 9f9b3c201d480940 | 9f9b3c201d480940 |  | true |
| B snapshot cost variance in scn-015: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a0d3945a18580e14 | a0d3945a18580e14 | a0d3945a18580e14 |  | true |
| B snapshot cost variance in scn-016: 15 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 3dcc0cbb638ead0d | 3dcc0cbb638ead0d | 3dcc0cbb638ead0d |  | true |
| B snapshot cost variance in scn-017: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 74271eaa550d9751 | 74271eaa550d9751 | 74271eaa550d9751 |  | true |
| B snapshot cost variance in scn-018: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 38ac3e18ee9eec75 | 38ac3e18ee9eec75 | 38ac3e18ee9eec75 |  | true |
| B snapshot cost variance in scn-019: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | d62f00bb71205d40 | d62f00bb71205d40 | d62f00bb71205d40 |  | true |
| B snapshot cost variance in scn-020: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2017c71773e8692d | 2017c71773e8692d | 2017c71773e8692d |  | true |
| B snapshot cost variance in scn-021: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4911dc462108713f | 4911dc462108713f | 4911dc462108713f |  | true |
| B snapshot cost variance in scn-022: 10 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 32cc6ea9ca5d1783 | 32cc6ea9ca5d1783 | 32cc6ea9ca5d1783 |  | true |
| B snapshot cost variance in scn-023: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 35bce1234d0a0024 | 35bce1234d0a0024 | 35bce1234d0a0024 |  | true |
| B snapshot cost variance in scn-024: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 797617b018a34b78 | 797617b018a34b78 | 797617b018a34b78 |  | true |
| B snapshot cost variance in scn-025: 120 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 263e4c0caabd6bd3 | 263e4c0caabd6bd3 | 263e4c0caabd6bd3 |  | true |
| B snapshot cost variance in scn-026: 115 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 8f91852462d2eef2 | 8f91852462d2eef2 | 8f91852462d2eef2 |  | true |
| B snapshot cost variance in scn-027: 25 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 8a8aa9aabbe8a146 | 8a8aa9aabbe8a146 | 8a8aa9aabbe8a146 |  | true |
| B snapshot cost variance in scn-028: 35 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 32aa2180fe0d211a | 32aa2180fe0d211a | 32aa2180fe0d211a |  | true |
| B snapshot cost variance in scn-029: 50 leaves (analysis leaves vs reference SQL vs Python domain, digest) | baa29cd84136e261 | baa29cd84136e261 | baa29cd84136e261 |  | true |
| B snapshot cost variance in scn-030: 50 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2523319c1e2869fc | 2523319c1e2869fc | 2523319c1e2869fc |  | true |
| B snapshot benefit realisation within a type in scn-001: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9f1fc81fa25b3a60 | 9f1fc81fa25b3a60 | 9f1fc81fa25b3a60 |  | true |
| B snapshot benefit realisation within a type in scn-002: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f0db184f0e16c443 | f0db184f0e16c443 | f0db184f0e16c443 |  | true |
| B snapshot benefit realisation within a type in scn-003: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 343f3eb67949d9a0 | 343f3eb67949d9a0 | 343f3eb67949d9a0 |  | true |
| B snapshot benefit realisation within a type in scn-004: 30 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 72e4c3f9b7dc09d5 | 72e4c3f9b7dc09d5 | 72e4c3f9b7dc09d5 |  | true |
| B snapshot benefit realisation within a type in scn-005: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c986c6408d042d44 | c986c6408d042d44 | c986c6408d042d44 |  | true |
| B snapshot benefit realisation within a type in scn-006: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 5dff093a4a86d0a8 | 5dff093a4a86d0a8 | 5dff093a4a86d0a8 |  | true |
| B snapshot benefit realisation within a type in scn-007: 35 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4584d7fa7219e94a | 4584d7fa7219e94a | 4584d7fa7219e94a |  | true |
| B snapshot benefit realisation within a type in scn-008: 35 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 79a319496cac3655 | 79a319496cac3655 | 79a319496cac3655 |  | true |
| B snapshot benefit realisation within a type in scn-009: 35 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 5670dccf21527626 | 5670dccf21527626 | 5670dccf21527626 |  | true |
| B snapshot benefit realisation within a type in scn-010: 5 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e20894cb1a8ad080 | e20894cb1a8ad080 | e20894cb1a8ad080 |  | true |
| B snapshot benefit realisation within a type in scn-011: 35 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 6550958422ca1eb1 | 6550958422ca1eb1 | 6550958422ca1eb1 |  | true |
| B snapshot benefit realisation within a type in scn-012: 35 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2e173d2e3bf66d3c | 2e173d2e3bf66d3c | 2e173d2e3bf66d3c |  | true |
| B snapshot benefit realisation within a type in scn-013: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e717f4c870d86b36 | e717f4c870d86b36 | e717f4c870d86b36 |  | true |
| B snapshot benefit realisation within a type in scn-014: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 968633f1c72705b7 | 968633f1c72705b7 | 968633f1c72705b7 |  | true |
| B snapshot benefit realisation within a type in scn-015: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | bef81d1975cd15d7 | bef81d1975cd15d7 | bef81d1975cd15d7 |  | true |
| B snapshot benefit realisation within a type in scn-016: 45 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 13f300f68179cc98 | 13f300f68179cc98 | 13f300f68179cc98 |  | true |
| B snapshot benefit realisation within a type in scn-017: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 1e77e0b1ef776072 | 1e77e0b1ef776072 | 1e77e0b1ef776072 |  | true |
| B snapshot benefit realisation within a type in scn-018: 60 leaves (analysis leaves vs reference SQL vs Python domain, digest) | ec1481454c14e9cd | ec1481454c14e9cd | ec1481454c14e9cd |  | true |
| B snapshot benefit realisation within a type in scn-019: 0 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f53cda18c2baa0c | 4f53cda18c2baa0c | 4f53cda18c2baa0c |  | true |
| B snapshot benefit realisation within a type in scn-020: 0 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f53cda18c2baa0c | 4f53cda18c2baa0c | 4f53cda18c2baa0c |  | true |
| B snapshot benefit realisation within a type in scn-021: 0 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f53cda18c2baa0c | 4f53cda18c2baa0c | 4f53cda18c2baa0c |  | true |
| B snapshot benefit realisation within a type in scn-022: 0 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f53cda18c2baa0c | 4f53cda18c2baa0c | 4f53cda18c2baa0c |  | true |
| B snapshot benefit realisation within a type in scn-023: 0 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f53cda18c2baa0c | 4f53cda18c2baa0c | 4f53cda18c2baa0c |  | true |
| B snapshot benefit realisation within a type in scn-024: 0 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f53cda18c2baa0c | 4f53cda18c2baa0c | 4f53cda18c2baa0c |  | true |
| B snapshot benefit realisation within a type in scn-025: 155 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f94f5aa80f73762f | f94f5aa80f73762f | f94f5aa80f73762f |  | true |
| B snapshot benefit realisation within a type in scn-026: 140 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 032a86a0601f7c7c | 032a86a0601f7c7c | 032a86a0601f7c7c |  | true |
| B snapshot benefit realisation within a type in scn-027: 75 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 1f73d165fb061b87 | 1f73d165fb061b87 | 1f73d165fb061b87 |  | true |
| B snapshot benefit realisation within a type in scn-028: 0 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f53cda18c2baa0c | 4f53cda18c2baa0c | 4f53cda18c2baa0c |  | true |
| B snapshot benefit realisation within a type in scn-029: 0 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f53cda18c2baa0c | 4f53cda18c2baa0c | 4f53cda18c2baa0c |  | true |
| B snapshot benefit realisation within a type in scn-030: 95 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e773fd6fa0eddc8d | e773fd6fa0eddc8d | e773fd6fa0eddc8d |  | true |
| B snapshot double count (money and hours) in scn-001: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 8540f1a2b56a0782 | 8540f1a2b56a0782 | 8540f1a2b56a0782 |  | true |
| B snapshot double count (money and hours) in scn-002: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | cdb5fa121021d113 | cdb5fa121021d113 | cdb5fa121021d113 |  | true |
| B snapshot double count (money and hours) in scn-003: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e41a550d65fb5e2a | e41a550d65fb5e2a | e41a550d65fb5e2a |  | true |
| B snapshot double count (money and hours) in scn-004: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 5b6e9aa9fdc39bf0 | 5b6e9aa9fdc39bf0 | 5b6e9aa9fdc39bf0 |  | true |
| B snapshot double count (money and hours) in scn-005: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 24dac481e1682e9f | 24dac481e1682e9f | 24dac481e1682e9f |  | true |
| B snapshot double count (money and hours) in scn-006: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0b569cd746294053 | 0b569cd746294053 | 0b569cd746294053 |  | true |
| B snapshot double count (money and hours) in scn-007: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | cb425c7d9d098e79 | cb425c7d9d098e79 | cb425c7d9d098e79 |  | true |
| B snapshot double count (money and hours) in scn-008: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0d71a18764f5e53b | 0d71a18764f5e53b | 0d71a18764f5e53b |  | true |
| B snapshot double count (money and hours) in scn-009: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f413c973168aa9d7 | f413c973168aa9d7 | f413c973168aa9d7 |  | true |
| B snapshot double count (money and hours) in scn-010: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f5e49e7cedaffa16 | f5e49e7cedaffa16 | f5e49e7cedaffa16 |  | true |
| B snapshot double count (money and hours) in scn-011: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | fec4979de1f8667f | fec4979de1f8667f | fec4979de1f8667f |  | true |
| B snapshot double count (money and hours) in scn-012: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | a5d38886d68af1e3 | a5d38886d68af1e3 | a5d38886d68af1e3 |  | true |
| B snapshot double count (money and hours) in scn-013: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 36b78959984e9435 | 36b78959984e9435 | 36b78959984e9435 |  | true |
| B snapshot double count (money and hours) in scn-014: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 977286be5fb43e86 | 977286be5fb43e86 | 977286be5fb43e86 |  | true |
| B snapshot double count (money and hours) in scn-015: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b3ca3197c04a95ce | b3ca3197c04a95ce | b3ca3197c04a95ce |  | true |
| B snapshot double count (money and hours) in scn-016: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b8584aa8a85e1a97 | b8584aa8a85e1a97 | b8584aa8a85e1a97 |  | true |
| B snapshot double count (money and hours) in scn-017: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 7390d9967e4df779 | 7390d9967e4df779 | 7390d9967e4df779 |  | true |
| B snapshot double count (money and hours) in scn-018: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e48baae4a123a245 | e48baae4a123a245 | e48baae4a123a245 |  | true |
| B snapshot double count (money and hours) in scn-019: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9ae9d3913d791e85 | 9ae9d3913d791e85 | 9ae9d3913d791e85 |  | true |
| B snapshot double count (money and hours) in scn-020: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b195fc78076eda7d | b195fc78076eda7d | b195fc78076eda7d |  | true |
| B snapshot double count (money and hours) in scn-021: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | bf91d43be8ecfd3c | bf91d43be8ecfd3c | bf91d43be8ecfd3c |  | true |
| B snapshot double count (money and hours) in scn-022: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f9f5b37b3048f60 | 4f9f5b37b3048f60 | 4f9f5b37b3048f60 |  | true |
| B snapshot double count (money and hours) in scn-023: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | d492d8e8161d4347 | d492d8e8161d4347 | d492d8e8161d4347 |  | true |
| B snapshot double count (money and hours) in scn-024: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 527246b7257af5cd | 527246b7257af5cd | 527246b7257af5cd |  | true |
| B snapshot double count (money and hours) in scn-025: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e0e2712a7d74551b | e0e2712a7d74551b | e0e2712a7d74551b |  | true |
| B snapshot double count (money and hours) in scn-026: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c771083e5ee2810b | c771083e5ee2810b | c771083e5ee2810b |  | true |
| B snapshot double count (money and hours) in scn-027: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9d661f2e4831e371 | 9d661f2e4831e371 | 9d661f2e4831e371 |  | true |
| B snapshot double count (money and hours) in scn-028: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 1ede7bd92014b6aa | 1ede7bd92014b6aa | 1ede7bd92014b6aa |  | true |
| B snapshot double count (money and hours) in scn-029: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 0850b3cea0bd0e4f | 0850b3cea0bd0e4f | 0850b3cea0bd0e4f |  | true |
| B snapshot double count (money and hours) in scn-030: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4f3db83e6a1471d7 | 4f3db83e6a1471d7 | 4f3db83e6a1471d7 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-001: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | edcff4df28a6e8c6 | edcff4df28a6e8c6 | edcff4df28a6e8c6 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-002: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 800d948a3e34939e | 800d948a3e34939e | 800d948a3e34939e |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-003: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | de062695d1aa2525 | de062695d1aa2525 | de062695d1aa2525 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-004: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 6253d95d59c47b96 | 6253d95d59c47b96 | 6253d95d59c47b96 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-005: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 1e5aac5620f5be0a | 1e5aac5620f5be0a | 1e5aac5620f5be0a |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-006: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | b52921362ec115fa | b52921362ec115fa | b52921362ec115fa |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-007: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 783d678a45152b3c | 783d678a45152b3c | 783d678a45152b3c |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-008: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 9da3d509924ea3a3 | 9da3d509924ea3a3 | 9da3d509924ea3a3 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-009: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 6666d9fe21739c47 | 6666d9fe21739c47 | 6666d9fe21739c47 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-010: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 58db432c9d2c06af | 58db432c9d2c06af | 58db432c9d2c06af |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-011: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 82395d6093a42200 | 82395d6093a42200 | 82395d6093a42200 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-012: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 764807e770253a64 | 764807e770253a64 | 764807e770253a64 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-013: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 89fd48d0209122cb | 89fd48d0209122cb | 89fd48d0209122cb |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-014: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c00856d98bc18646 | c00856d98bc18646 | c00856d98bc18646 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-015: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 86f405ee7a811c8c | 86f405ee7a811c8c | 86f405ee7a811c8c |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-016: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 32197c242ebf23a7 | 32197c242ebf23a7 | 32197c242ebf23a7 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-017: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 8228d0f39b45cd81 | 8228d0f39b45cd81 | 8228d0f39b45cd81 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-018: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 7c615b9d903971f0 | 7c615b9d903971f0 | 7c615b9d903971f0 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-019: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | db0b6886e08dfb45 | db0b6886e08dfb45 | db0b6886e08dfb45 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-020: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 2439529f6a921c17 | 2439529f6a921c17 | 2439529f6a921c17 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-021: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | e35d5bd105615bc4 | e35d5bd105615bc4 | e35d5bd105615bc4 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-022: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 00e23d450f1dff65 | 00e23d450f1dff65 | 00e23d450f1dff65 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-023: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f791fdb157f77ec7 | f791fdb157f77ec7 | f791fdb157f77ec7 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-024: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 779f152266e5d805 | 779f152266e5d805 | 779f152266e5d805 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-025: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | c5e0d8ba5c13676d | c5e0d8ba5c13676d | c5e0d8ba5c13676d |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-026: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 79953e1fba30f14a | 79953e1fba30f14a | 79953e1fba30f14a |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-027: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | aa55818a388f5767 | aa55818a388f5767 | aa55818a388f5767 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-028: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 94a575dc7f86cba2 | 94a575dc7f86cba2 | 94a575dc7f86cba2 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-029: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 162db51539fa9e98 | 162db51539fa9e98 | 162db51539fa9e98 |  | true |
| B snapshot portfolio NPV (attributable and plain sum) in scn-030: 2 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 558958ed4deff626 | 558958ed4deff626 | 558958ed4deff626 |  | true |
| B snapshot adoption: 72 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 29b9e4497b4a68d1 | 29b9e4497b4a68d1 | 29b9e4497b4a68d1 |  | true |
| B snapshot training completion: 72 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 4bd2262efbee985b | 4bd2262efbee985b | 4bd2262efbee985b |  | true |
| B snapshot roadmap (feasible start, delay, binding dependency): 72 leaves (analysis leaves vs reference SQL vs Python domain, digest) | 271394a1782d9fb6 | 271394a1782d9fb6 | 271394a1782d9fb6 |  | true |
| B snapshot summary pools: 8 leaves (analysis leaves vs reference SQL vs Python domain, digest) | f8efd93ae8b2ea36 | f8efd93ae8b2ea36 | f8efd93ae8b2ea36 |  | true |
| B scn-025 init-001: NPV and its exact rational (02 vs Python domain) | 578533.26/383810891549476977699647500479478449841920942763940656197239704127987467337053840609/663420611434589300610355292649553379288513668660980279304277455838096117685000 | 578533.26/383810891549476977699647500479478449841920942763940656197239704127987467337053840609/663420611434589300610355292649553379288513668660980279304277455838096117685000 |  |  | true |
| B scn-025 init-001: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 578533.26/True | 578533.26/True |  |  | true |
| B scn-025 init-002: NPV and its exact rational (02 vs Python domain) | 413388.43/27601492882239646861637204249343617260875293170884798579765253322166492584348265989150/66768905964855944817048231860246060573085596560514502642132117698895842810618529 | 413388.43/27601492882239646861637204249343617260875293170884798579765253322166492584348265989150/66768905964855944817048231860246060573085596560514502642132117698895842810618529 |  |  | true |
| B scn-025 init-002: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 413388.43/True | 413388.43/True |  |  | true |
| B scn-025 init-003: NPV and its exact rational (02 vs Python domain) | 363049.68/717540961882968709054077482351394294053936797690563974954770493294873060769550440155710000/1976426385465700822529444711295143639023906743787789792709752816005015843037119076929 | 363049.68/717540961882968709054077482351394294053936797690563974954770493294873060769550440155710000/1976426385465700822529444711295143639023906743787789792709752816005015843037119076929 |  |  | true |
| B scn-025 init-003: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 363049.68/True | 363049.68/True |  |  | true |
| B scn-025 init-004: NPV and its exact rational (02 vs Python domain) | 523302.08/8847841361425969639875730794641786105975352760192054941485751067905336660446062652724917258218000/16907713059053190703783592847824741042177785758107223674006402607797132977255369159094670081 | 523302.08/8847841361425969639875730794641786105975352760192054941485751067905336660446062652724917258218000/16907713059053190703783592847824741042177785758107223674006402607797132977255369159094670081 |  |  | true |
| B scn-025 init-004: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 523302.08/True | 523302.08/True |  |  | true |
| B scn-025 init-005: NPV and its exact rational (02 vs Python domain) | 209002.21/57380928359227912365423874543473801836051039305241616871748563935757666554816551427576517740612551079319175420875443217627887154000/274546995011876493867952603438135661269866631297630832938326819533167114915127746565404982813389208620058898508896913026579489 | 209002.21/57380928359227912365423874543473801836051039305241616871748563935757666554816551427576517740612551079319175420875443217627887154000/274546995011876493867952603438135661269866631297630832938326819533167114915127746565404982813389208620058898508896913026579489 |  |  | true |
| B scn-025 init-005: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 209002.21/True | 209002.21/True |  |  | true |
| B scn-025 init-006: NPV and its exact rational (02 vs Python domain) | -535631.92/-4745256234369645251852315933595541749474673595902711453977922383624561057950017276147423858994885947159993337172399706462065027636398106171312385127166053657000/8859173684004665516658749199228777540747205253877379842903626799793167601050654187900958291098438573332593019155522940229447515155345130145820569685117073 | -535631.92/-4745256234369645251852315933595541749474673595902711453977922383624561057950017276147423858994885947159993337172399706462065027636398106171312385127166053657000/8859173684004665516658749199228777540747205253877379842903626799793167601050654187900958291098438573332593019155522940229447515155345130145820569685117073 |  |  | true |
| B scn-025 init-006: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | -535631.92/True | -535631.92/True |  |  | true |
| B scn-025 init-007: NPV and its exact rational (02 vs Python domain) | 415366.00/5010224840834739015137291109898963365729833154227099676805754149085215390797950/12062192935174350920188278048173697805245703066563277805532317378874474867 | 415366.00/5010224840834739015137291109898963365729833154227099676805754149085215390797950/12062192935174350920188278048173697805245703066563277805532317378874474867 |  |  | true |
| B scn-025 init-007: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 415366.00/True | 415366.00/True |  |  | true |
| B scn-025 init-008: NPV and its exact rational (02 vs Python domain) | 65253.91/4356931929296908838814170499659061002104553115227141905867673188932069850991744715950/66768905964855944817048231860246060573085596560514502642132117698895842810618529 | 65253.91/4356931929296908838814170499659061002104553115227141905867673188932069850991744715950/66768905964855944817048231860246060573085596560514502642132117698895842810618529 |  |  | true |
| B scn-025 init-008: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 65253.91/True | 65253.91/True |  |  | true |
| B scn-025 init-009: NPV and its exact rational (02 vs Python domain) | -761535.73/-16948969258525200178123277834922553631482181056807788486708307233556498367052249116000/22256301988285314939016077286748686857695198853504834214044039232965280936872843 | -761535.73/-16948969258525200178123277834922553631482181056807788486708307233556498367052249116000/22256301988285314939016077286748686857695198853504834214044039232965280936872843 |  |  | true |
| B scn-025 init-009: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | -761535.73/True | -761535.73/True |  |  | true |
| B scn-025 init-010: NPV and its exact rational (02 vs Python domain) | 423409.74/231005452259100353838295918619332071323829821214805353011018109469206095077341168529219657902425126967141550774067597253992000/545583704469198166731156943104338011771992264366328706975970246500350971678476177405383726729004005468930696913850114417 | 423409.74/231005452259100353838295918619332071323829821214805353011018109469206095077341168529219657902425126967141550774067597253992000/545583704469198166731156943104338011771992264366328706975970246500350971678476177405383726729004005468930696913850114417 |  |  | true |
| B scn-025 init-010: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 423409.74/True | 423409.74/True |  |  | true |
| B scn-025 init-011: NPV and its exact rational (02 vs Python domain) | 84012.76/8012075277988128862846604995707820222257195099422617579131659926784771961740449752543409319221779037968175968966841123222122344888516257000/95367363164894911678536902305260851456412036323837607669579595524686437616444489007610052611174423147403433004736982396839665015926249 | 84012.76/8012075277988128862846604995707820222257195099422617579131659926784771961740449752543409319221779037968175968966841123222122344888516257000/95367363164894911678536902305260851456412036323837607669579595524686437616444489007610052611174423147403433004736982396839665015926249 |  |  | true |
| B scn-025 init-011: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 84012.76/True | 84012.76/True |  |  | true |
| B scn-025 init-012: NPV and its exact rational (02 vs Python domain) | 126524.02/24524133057494913253286209668129112157507545126593139808766350744060948570099961914108372440735858936810842960008444703860798767238743058463093876337889853397495000/193829861032338076838976773729926423814008103749583193582888450752674713943387262977085066450942737545943802666103686409280082184083796102460408244140676440167 | 126524.02/24524133057494913253286209668129112157507545126593139808766350744060948570099961914108372440735858936810842960008444703860798767238743058463093876337889853397495000/193829861032338076838976773729926423814008103749583193582888450752674713943387262977085066450942737545943802666103686409280082184083796102460408244140676440167 |  |  | true |
| B scn-025 init-012: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 126524.02/True | 126524.02/True |  |  | true |
| B scn-025 init-013: NPV and its exact rational (02 vs Python domain) | 463582.30/61510010068930593149735997005700434841372141145025540231896748514744187709389100/132684122286917860122071058529910675857702733732196055860855491167619223537 | 463582.30/61510010068930593149735997005700434841372141145025540231896748514744187709389100/132684122286917860122071058529910675857702733732196055860855491167619223537 |  |  | true |
| B scn-025 init-013: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 463582.30/True | 463582.30/True |  |  | true |
| B scn-025 init-014: NPV and its exact rational (02 vs Python domain) | 76930.78/654546165291438534574573688219320642639189314848703522807190912540177682199868949540739290711139037000/8508248642437569466385868242103822713021578815837442775562479901087849865415515102132142594150577 | 76930.78/654546165291438534574573688219320642639189314848703522807190912540177682199868949540739290711139037000/8508248642437569466385868242103822713021578815837442775562479901087849865415515102132142594150577 |  |  | true |
| B scn-025 init-014: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 76930.78/True | 76930.78/True |  |  | true |
| B scn-025 init-015: NPV and its exact rational (02 vs Python domain) | -618556.03/-950760722073274731505048076065983449698703426044042128427795883873789116839953802667154914678000/1537064823550290063980326622529521912925253250737020334000582055254284816114124469008606371 | -618556.03/-950760722073274731505048076065983449698703426044042128427795883873789116839953802667154914678000/1537064823550290063980326622529521912925253250737020334000582055254284816114124469008606371 |  |  | true |
| B scn-025 init-015: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | -618556.03/True | -618556.03/True |  |  | true |
| B scn-025 init-016: NPV and its exact rational (02 vs Python domain) | 46285.40/198170708085448123636482797158694010807299752924389501006690287882016233824210462170329435202391949125492000/4281495357101506394166297459186759354178579826969270441190224448385724545724799263149630399800670906209 | 46285.40/198170708085448123636482797158694010807299752924389501006690287882016233824210462170329435202391949125492000/4281495357101506394166297459186759354178579826969270441190224448385724545724799263149630399800670906209 |  |  | true |
| B scn-025 init-016: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 46285.40/True | 46285.40/True |  |  | true |
| B scn-025 init-017: NPV and its exact rational (02 vs Python domain) | 93546.29/3272722512783389524487886952172440994420343887523049805044911056627751842155043319559525675108283518270616961364117534227150003977417496894631544000/34985058746126964699430823883795561967871804552741217686205206949115532471887038543783088218886435216172879829485308221606249502822812888171057 | 93546.29/3272722512783389524487886952172440994420343887523049805044911056627751842155043319559525675108283518270616961364117534227150003977417496894631544000/34985058746126964699430823883795561967871804552741217686205206949115532471887038543783088218886435216172879829485308221606249502822812888171057 |  |  | true |
| B scn-025 init-017: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 93546.29/True | 93546.29/True |  |  | true |
| B scn-025 init-018: NPV and its exact rational (02 vs Python domain) | 15040.08/67049986364941498402204383186263813527559534455476859232210976555984742763905634105114184716283170364432925386796152125865581097660726896434106103847644418761590000/4458086803743775767296465795788307747722186386240413452406434367311518420697907048472956528371682963556707461320384787413441890233927310356589389615235558123841 | 15040.08/67049986364941498402204383186263813527559534455476859232210976555984742763905634105114184716283170364432925386796152125865581097660726896434106103847644418761590000/4458086803743775767296465795788307747722186386240413452406434367311518420697907048472956528371682963556707461320384787413441890233927310356589389615235558123841 |  |  | true |
| B scn-025 init-018: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 15040.08/True | 15040.08/True |  |  | true |
| B scn-025 init-019: NPV and its exact rational (02 vs Python domain) | -1002807.01/-17654493913467372055646073721180069306241750172435998325795382883529181221867524202537182003881507448245350507175619841904984544953053786363495171436273000/17605076307049772795153480902331951306786545871616777340399125625313070903905579874886894304243375270176868069154108347352032056061987433146774790369 | -1002807.01/-17654493913467372055646073721180069306241750172435998325795382883529181221867524202537182003881507448245350507175619841904984544953053786363495171436273000/17605076307049772795153480902331951306786545871616777340399125625313070903905579874886894304243375270176868069154108347352032056061987433146774790369 |  |  | true |
| B scn-025 init-019: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | -1002807.01/True | -1002807.01/True |  |  | true |
| B scn-025 init-020: NPV and its exact rational (02 vs Python domain) | 112711.77/1738681198341668793179566353766120219993059744587468892842749932221048629398851420911711500279371394607114517444687242132220808085553694307985289084383052547634000/15425905895307182585800919708610061410803413101177901219399426876510444362276494977415074492635581188777534468236625561984227993889021835143907922544067675169 | 112711.77/1738681198341668793179566353766120219993059744587468892842749932221048629398851420911711500279371394607114517444687242132220808085553694307985289084383052547634000/15425905895307182585800919708610061410803413101177901219399426876510444362276494977415074492635581188777534468236625561984227993889021835143907922544067675169 |  |  | true |
| B scn-025 init-020: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 112711.77/True | 112711.77/True |  |  | true |
| B scn-025 init-021: NPV and its exact rational (02 vs Python domain) | -337229.75/-380701872587077026367675004332949554632329460998336125442034311974816167800113521205323494418115386167330050552131368260604892217455696385346713438613184116419949808803185094000/1128909503320689338336120973826033991977009436618824563592215842640960725528722871175335007185897694555008425355228043434148702909282730891118906435530686069991634800530849 | -337229.75/-380701872587077026367675004332949554632329460998336125442034311974816167800113521205323494418115386167330050552131368260604892217455696385346713438613184116419949808803185094000/1128909503320689338336120973826033991977009436618824563592215842640960725528722871175335007185897694555008425355228043434148702909282730891118906435530686069991634800530849 |  |  | true |
| B scn-025 init-021: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | -337229.75/True | -337229.75/True |  |  | true |
| B scn-025 init-022: NPV and its exact rational (02 vs Python domain) | -61430.84/-4446996318352577766649102068494822374381426401369605905904402751177191487787341419808386190880236198460437721819681204515378621739831321741920284652861363521513343341592863638382073174537643762219000/72390294961540743800507923275654767119585558495545122493227558572585282954723761194650109515262478224741497438152836774125329249075574703810934968441942138319394849235714876216552106776149432929 | -61430.84/-4446996318352577766649102068494822374381426401369605905904402751177191487787341419808386190880236198460437721819681204515378621739831321741920284652861363521513343341592863638382073174537643762219000/72390294961540743800507923275654767119585558495545122493227558572585282954723761194650109515262478224741497438152836774125329249075574703810934968441942138319394849235714876216552106776149432929 |  |  | true |
| B scn-025 init-022: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | -61430.84/True | -61430.84/True |  |  | true |
| B scn-025 init-023: NPV and its exact rational (02 vs Python domain) | 515502.07/35839151181804882316329991807409443597962380252892280526371357896645858221414796382765709152053304552372279384798243511969786441762708694992000/69522807747208390613653401780535160711724374480077615991123525137496413022388032486547728353546154474457102660453260167296115796610235521 | 515502.07/35839151181804882316329991807409443597962380252892280526371357896645858221414796382765709152053304552372279384798243511969786441762708694992000/69522807747208390613653401780535160711724374480077615991123525137496413022388032486547728353546154474457102660453260167296115796610235521 |  |  | true |
| B scn-025 init-023: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 515502.07/True | 515502.07/True |  |  | true |
| B scn-025 init-024: NPV and its exact rational (02 vs Python domain) | 230132.79/51198695223168703291394596864131869389070162387483331920850818988520531579209567016017918932313713892297578784832477362882568414940000/222474581624623918864330926319369264182348593561513518291024166095043085452891850633499837739783055385121060758376131855871579253 | 230132.79/51198695223168703291394596864131869389070162387483331920850818988520531579209567016017918932313713892297578784832477362882568414940000/222474581624623918864330926319369264182348593561513518291024166095043085452891850633499837739783055385121060758376131855871579253 |  |  | true |
| B scn-025 init-024: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV | 230132.79/True | 230132.79/True |  |  | true |
| B scn-025 init-001: simple and discounted payback, interpolation and reason (04 vs Python domain) | 10/9.2751//10/9.4881/ | 10/9.2751//10/9.4881/ |  |  | true |
| B scn-025 init-002: simple and discounted payback, interpolation and reason (04 vs Python domain) | 10/9.9761//11/10.1813/ | 10/9.9761//11/10.1813/ |  |  | true |
| B scn-025 init-003: simple and discounted payback, interpolation and reason (04 vs Python domain) | 12/11.1517//12/11.3518/ | 12/11.1517//12/11.3518/ |  |  | true |
| B scn-025 init-004: simple and discounted payback, interpolation and reason (04 vs Python domain) | 14/13.0991//14/13.3330/ | 14/13.0991//14/13.3330/ |  |  | true |
| B scn-025 init-005: simple and discounted payback, interpolation and reason (04 vs Python domain) | 19/18.4347//19/18.7401/ | 19/18.4347//19/18.7401/ |  |  | true |
| B scn-025 init-006: simple and discounted payback, interpolation and reason (04 vs Python domain) | //NOT_RECOVERED///NOT_RECOVERED | //NOT_RECOVERED///NOT_RECOVERED |  |  | true |
| B scn-025 init-007: simple and discounted payback, interpolation and reason (04 vs Python domain) | 11/10.2556//11/10.5167/ | 11/10.2556//11/10.5167/ |  |  | true |
| B scn-025 init-008: simple and discounted payback, interpolation and reason (04 vs Python domain) | 13/12.3875//13/12.7625/ | 13/12.3875//13/12.7625/ |  |  | true |
| B scn-025 init-009: simple and discounted payback, interpolation and reason (04 vs Python domain) | //NOT_RECOVERED///NOT_RECOVERED | //NOT_RECOVERED///NOT_RECOVERED |  |  | true |
| B scn-025 init-010: simple and discounted payback, interpolation and reason (04 vs Python domain) | 18/17.3724//18/17.6973/ | 18/17.3724//18/17.6973/ |  |  | true |
| B scn-025 init-011: simple and discounted payback, interpolation and reason (04 vs Python domain) | 21/20.5648//21/20.8920/ | 21/20.5648//21/20.8920/ |  |  | true |
| B scn-025 init-012: simple and discounted payback, interpolation and reason (04 vs Python domain) | 27/26.2243//27/26.6165/ | 27/26.2243//27/26.6165/ |  |  | true |
| B scn-025 init-013: simple and discounted payback, interpolation and reason (04 vs Python domain) | 11/10.3102//11/10.5628/ | 11/10.3102//11/10.5628/ |  |  | true |
| B scn-025 init-014: simple and discounted payback, interpolation and reason (04 vs Python domain) | 15/14.9491//16/15.3225/ | 15/14.9491//16/15.3225/ |  |  | true |
| B scn-025 init-015: simple and discounted payback, interpolation and reason (04 vs Python domain) | //NOT_RECOVERED///NOT_RECOVERED | //NOT_RECOVERED///NOT_RECOVERED |  |  | true |
| B scn-025 init-016: simple and discounted payback, interpolation and reason (04 vs Python domain) | 17/16.4576//17/16.8431/ | 17/16.4576//17/16.8431/ |  |  | true |
| B scn-025 init-017: simple and discounted payback, interpolation and reason (04 vs Python domain) | 22/21.7597//23/22.1197/ | 22/21.7597//23/22.1197/ |  |  | true |
| B scn-025 init-018: simple and discounted payback, interpolation and reason (04 vs Python domain) | 28/27.3606//28/27.7438/ | 28/27.3606//28/27.7438/ |  |  | true |
| B scn-025 init-019: simple and discounted payback, interpolation and reason (04 vs Python domain) | //NOT_RECOVERED///NOT_RECOVERED | //NOT_RECOVERED///NOT_RECOVERED |  |  | true |
| B scn-025 init-020: simple and discounted payback, interpolation and reason (04 vs Python domain) | 27/26.2203//27/26.6686/ | 27/26.2203//27/26.6686/ |  |  | true |
| B scn-025 init-021: simple and discounted payback, interpolation and reason (04 vs Python domain) | //NOT_RECOVERED///NOT_RECOVERED | //NOT_RECOVERED///NOT_RECOVERED |  |  | true |
| B scn-025 init-022: simple and discounted payback, interpolation and reason (04 vs Python domain) | //NOT_RECOVERED///NOT_RECOVERED | //NOT_RECOVERED///NOT_RECOVERED |  |  | true |
| B scn-025 init-023: simple and discounted payback, interpolation and reason (04 vs Python domain) | 22/21.3888//22/21.8053/ | 22/21.3888//22/21.8053/ |  |  | true |
| B scn-025 init-024: simple and discounted payback, interpolation and reason (04 vs Python domain) | 20/19.7406//21/20.1194/ | 20/19.7406//21/20.1194/ |  |  | true |
| B scn-001 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 7624466.78/7624466.78/0.00/81230.96/7302.53 | 7624466.78/7624466.78/0.00/81230.96/7302.53 |  |  | true |
| B scn-001 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-002 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 9008552.27/8755373.42/253178.85/78996.66/7302.53 | 9008552.27/8755373.42/253178.85/78996.66/7302.53 |  |  | true |
| B scn-002 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-003 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8635351.21/8382172.36/253178.85/70915.16/7302.53 | 8635351.21/8382172.36/253178.85/70915.16/7302.53 |  |  | true |
| B scn-003 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-004 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 4314399.87/4314399.87/0.00/59608.33/0.00 | 4314399.87/4314399.87/0.00/59608.33/0.00 |  |  | true |
| B scn-004 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-005 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 7624466.78/7624466.78/0.00/81230.96/7302.53 | 7624466.78/7624466.78/0.00/81230.96/7302.53 |  |  | true |
| B scn-005 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-006 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8197554.34/7990408.03/207146.32/73960.63/5974.80 | 8197554.34/7990408.03/207146.32/73960.63/5974.80 |  |  | true |
| B scn-006 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-007 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 9723216.38/9723216.38/0.00/51825.80/0.00 | 9723216.38/9723216.38/0.00/51825.80/0.00 |  |  | true |
| B scn-007 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-008 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 9919341.91/9919341.91/0.00/51825.80/0.00 | 9919341.91/9919341.91/0.00/51825.80/0.00 |  |  | true |
| B scn-008 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-009 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8914958.48/8914958.48/0.00/36891.24/0.00 | 8914958.48/8914958.48/0.00/36891.24/0.00 |  |  | true |
| B scn-009 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-010 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 2758599.79/2758599.79/0.00/11441.31/0.00 | 2758599.79/2758599.79/0.00/11441.31/0.00 |  |  | true |
| B scn-010 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-011 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 9723216.38/9723216.38/0.00/51825.80/0.00 | 9723216.38/9723216.38/0.00/51825.80/0.00 |  |  | true |
| B scn-011 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-012 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 9146835.90/9146835.90/0.00/49261.27/0.00 | 9146835.90/9146835.90/0.00/49261.27/0.00 |  |  | true |
| B scn-012 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-013 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8063433.53/8063433.53/0.00/49795.74/0.00 | 8063433.53/8063433.53/0.00/49795.74/0.00 |  |  | true |
| B scn-013 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-014 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8196235.37/8196235.37/0.00/49795.74/0.00 | 8196235.37/8196235.37/0.00/49795.74/0.00 |  |  | true |
| B scn-014 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-015 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 7013371.25/7013371.25/0.00/44119.03/0.00 | 7013371.25/7013371.25/0.00/44119.03/0.00 |  |  | true |
| B scn-015 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-016 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 4172466.96/4172466.96/0.00/38540.98/0.00 | 4172466.96/4172466.96/0.00/38540.98/0.00 |  |  | true |
| B scn-016 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-017 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8063433.53/8063433.53/0.00/49795.74/0.00 | 8063433.53/8063433.53/0.00/49795.74/0.00 |  |  | true |
| B scn-017 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-018 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 7185404.43/7185404.43/0.00/43767.35/0.00 | 7185404.43/7185404.43/0.00/43767.35/0.00 |  |  | true |
| B scn-018 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-019 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8148100.02/8148100.02/0.00/27886.67/0.00 | 8148100.02/8148100.02/0.00/27886.67/0.00 |  |  | true |
| B scn-019 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-020 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8148100.02/8148100.02/0.00/27886.67/0.00 | 8148100.02/8148100.02/0.00/27886.67/0.00 |  |  | true |
| B scn-020 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-021 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 6538483.30/6538483.30/0.00/13466.00/0.00 | 6538483.30/6538483.30/0.00/13466.00/0.00 |  |  | true |
| B scn-021 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-022 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 5895166.52/5895166.52/0.00/7812.00/0.00 | 5895166.52/5895166.52/0.00/7812.00/0.00 |  |  | true |
| B scn-022 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-023 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8148100.02/8148100.02/0.00/27886.67/0.00 | 8148100.02/8148100.02/0.00/27886.67/0.00 |  |  | true |
| B scn-023 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-024 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 8148100.02/8148100.02/0.00/27886.67/0.00 | 8148100.02/8148100.02/0.00/27886.67/0.00 |  |  | true |
| B scn-024 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-025 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 32677894.70/32470748.38/207146.32/194875.92/5974.80 | 32677894.70/32470748.38/207146.32/194875.92/5974.80 |  |  | true |
| B scn-025 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-026 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 31059699.61/31059699.61/0.00/186909.52/0.00 | 31059699.61/31059699.61/0.00/186909.52/0.00 |  |  | true |
| B scn-026 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-027 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 10075357.56/9868211.24/207146.32/33381.15/5974.80 | 10075357.56/9868211.24/207146.32/33381.15/5974.80 |  |  | true |
| B scn-027 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-028 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 9786633.43/9786633.43/0.00/44237.80/0.00 | 9786633.43/9786633.43/0.00/44237.80/0.00 |  |  | true |
| B scn-028 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-029 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 7014750.47/7014750.47/0.00/86695.45/0.00 | 7014750.47/7014750.47/0.00/86695.45/0.00 |  |  | true |
| B scn-029 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-030 ledger: planned benefits / attributable / residual / planned hours / hours residual (01 vs Python domain double_count) | 18130191.00/18130191.00/0.00/70709.65/0.00 | 18130191.00/18130191.00/0.00/70709.65/0.00 |  |  | true |
| B scn-030 ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (/01 - sum of rounded rows/ <= 0.005 x initiatives) | true | true |  |  | true |
| B scn-001 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 953382.86/953382.86/0.00 | 953382.86/953382.86/0.00 | 953382.86/953382.86/0.00 |  | true |
| B scn-002 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 1850194.72/2083397.09/233202.37 | 1850194.72/2083397.09/233202.37 | 1850194.72/2083397.09/233202.37 |  | true |
| B scn-003 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 1741529.16/1980952.24/239423.08 | 1741529.16/1980952.24/239423.08 | 1741529.16/1980952.24/239423.08 |  | true |
| B scn-004 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 99957.44/99957.44/0.00 | 99957.44/99957.44/0.00 | 99957.44/99957.44/0.00 |  | true |
| B scn-005 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 892632.76/892632.76/0.00 | 892632.76/892632.76/0.00 | 892632.76/892632.76/0.00 |  | true |
| B scn-006 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 1329339.78/1523563.61/194223.83 | 1329339.78/1523563.61/194223.83 | 1329339.78/1523563.61/194223.83 |  | true |
| B scn-007 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 791876.77/791876.77/0.00 | 791876.77/791876.77/0.00 | 791876.77/791876.77/0.00 |  | true |
| B scn-008 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 804919.25/804919.25/0.00 | 804919.25/804919.25/0.00 | 804919.25/804919.25/0.00 |  | true |
| B scn-009 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 334667.51/334667.51/0.00 | 334667.51/334667.51/0.00 | 334667.51/334667.51/0.00 |  | true |
| B scn-010 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -362653.93/-362653.93/0.00 | -362653.93/-362653.93/0.00 | -362653.93/-362653.93/0.00 |  | true |
| B scn-011 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 706407.57/706407.57/0.00 | 706407.57/706407.57/0.00 | 706407.57/706407.57/0.00 |  | true |
| B scn-012 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 322261.60/322261.60/0.00 | 322261.60/322261.60/0.00 | 322261.60/322261.60/0.00 |  | true |
| B scn-013 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 817592.33/817592.33/0.00 | 817592.33/817592.33/0.00 | 817592.33/817592.33/0.00 |  | true |
| B scn-014 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 796700.44/796700.44/0.00 | 796700.44/796700.44/0.00 | 796700.44/796700.44/0.00 |  | true |
| B scn-015 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -47204.81/-47204.81/0.00 | -47204.81/-47204.81/0.00 | -47204.81/-47204.81/0.00 |  | true |
| B scn-016 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -61970.90/-61970.90/0.00 | -61970.90/-61970.90/0.00 | -61970.90/-61970.90/0.00 |  | true |
| B scn-017 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 744598.77/744598.77/0.00 | 744598.77/744598.77/0.00 | 744598.77/744598.77/0.00 |  | true |
| B scn-018 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 52603.38/52603.38/0.00 | 52603.38/52603.38/0.00 | 52603.38/52603.38/0.00 |  | true |
| B scn-019 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -543120.97/-543120.97/0.00 | -543120.97/-543120.97/0.00 | -543120.97/-543120.97/0.00 |  | true |
| B scn-020 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -661017.95/-661017.95/0.00 | -661017.95/-661017.95/0.00 | -661017.95/-661017.95/0.00 |  | true |
| B scn-021 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -1380296.98/-1380296.98/0.00 | -1380296.98/-1380296.98/0.00 | -1380296.98/-1380296.98/0.00 |  | true |
| B scn-022 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 673071.47/673071.47/0.00 | 673071.47/673071.47/0.00 | 673071.47/673071.47/0.00 |  | true |
| B scn-023 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -604162.03/-604162.03/0.00 | -604162.03/-604162.03/0.00 | -604162.03/-604162.03/0.00 |  | true |
| B scn-024 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -565945.30/-565945.30/0.00 | -565945.30/-565945.30/0.00 | -565945.30/-565945.30/0.00 |  | true |
| B scn-025 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 1243149.05/1438382.25/195233.20 | 1243149.05/1438382.25/195233.20 | 1243149.05/1438382.25/195233.20 |  | true |
| B scn-026 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 1024993.83/1024993.83/0.00 | 1024993.83/1024993.83/0.00 | 1024993.83/1024993.83/0.00 |  | true |
| B scn-027 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 1645520.17/1838021.19/192501.02 | 1645520.17/1838021.19/192501.02 | 1645520.17/1838021.19/192501.02 |  | true |
| B scn-028 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 147903.44/147903.44/0.00 | 147903.44/147903.44/0.00 | 147903.44/147903.44/0.00 |  | true |
| B scn-029 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | -1343076.84/-1343076.84/0.00 | -1343076.84/-1343076.84/0.00 | -1343076.84/-1343076.84/0.00 |  | true |
| B scn-030 portfolio NPV: attributable / plain sum / double-counted PV (02 vs Python domain vs reference SQL) | 1748559.44/1748559.44/0.00 | 1748559.44/1748559.44/0.00 | 1748559.44/1748559.44/0.00 |  | true |
| B the exact attributable NPV of all 30 scenarios (02 vs Python domain npv_total.exact, digest) | ac2436a2c0798b40 | ac2436a2c0798b40 |  |  | true |
| B init-001 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 416/350/0.841346/425/403/0.948235 | 416/350/0.841346/425/403/0.948235 |  |  | true |
| B init-002 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 726/420/0.578512/705/683/0.968794 | 726/420/0.578512/705/683/0.968794 |  |  | true |
| B init-003 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 310/72/0.232258/317/310/0.977918 | 310/72/0.232258/317/310/0.977918 |  |  | true |
| B init-004 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 747/332/0.444444/771/740/0.959792 | 747/332/0.444444/771/740/0.959792 |  |  | true |
| B init-005 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///421/10/0.023753 | ///421/10/0.023753 |  |  | true |
| B init-006 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-007 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 753/557/0.739708/739/724/0.979702 | 753/557/0.739708/739/724/0.979702 |  |  | true |
| B init-008 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 411/292/0.710462/411/398/0.968370 | 411/292/0.710462/411/398/0.968370 |  |  | true |
| B init-009 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 361/149/0.412742/365/350/0.958904 | 361/149/0.412742/365/350/0.958904 |  |  | true |
| B init-010 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///508/482/0.948819 | ///508/482/0.948819 |  |  | true |
| B init-011 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-012 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-013 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 855/606/0.708772/847/804/0.949233 | 855/606/0.708772/847/804/0.949233 |  |  | true |
| B init-014 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 427/98/0.229508/441/432/0.979592 | 427/98/0.229508/441/432/0.979592 |  |  | true |
| B init-015 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 329/115/0.349544/340/333/0.979412 | 329/115/0.349544/340/333/0.979412 |  |  | true |
| B init-016 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | 413/72/0.174334/409/384/0.938875 | 413/72/0.174334/409/384/0.938875 |  |  | true |
| B init-017 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-018 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-019 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-020 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-021 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-022 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///// | ///// |  |  | true |
| B init-023 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///220/213/0.968182 | ///220/213/0.968182 |  |  | true |
| B init-024 adoption eligible / adopted / rate / training eligible / completed / rate (07 vs Python domain) | ///315/161/0.511111 | ///315/161/0.511111 |  |  | true |
| B init-001 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 0/0//4/false | 0/0//4/false |  |  | true |
| B init-002 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 0/0//5/false | 0/0//5/false |  |  | true |
| B init-003 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 1/0//7/false | 1/0//7/false |  |  | true |
| B init-004 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 2/0//9/false | 2/0//9/false |  |  | true |
| B init-005 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 8/0//14/false | 8/0//14/false |  |  | true |
| B init-006 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 12/0//18/false | 12/0//18/false |  |  | true |
| B init-007 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 0/0//3/false | 0/0//3/false |  |  | true |
| B init-008 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 0/0//4/false | 0/0//4/false |  |  | true |
| B init-009 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 1/0//7/false | 1/0//7/false |  |  | true |
| B init-010 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 3/0//9/false | 3/0//9/false |  |  | true |
| B init-011 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 9/0//14/false | 9/0//14/false |  |  | true |
| B init-012 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 14/0//20/false | 14/0//20/false |  |  | true |
| B init-013 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 0/0//4/false | 0/0//4/false |  |  | true |
| B init-014 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 3/0//9/false | 3/0//9/false |  |  | true |
| B init-015 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 2/0//8/false | 2/0//8/false |  |  | true |
| B init-016 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 4/0//11/false | 4/0//11/false |  |  | true |
| B init-017 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 13/3/d-029/19/false | 13/3/d-029/19/false |  |  | true |
| B init-018 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 22/7/d-031/28/true | 22/7/d-031/28/true |  |  | true |
| B init-019 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 19/10/d-033/26/true | 19/10/d-033/26/true |  |  | true |
| B init-020 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 18/6/d-035/26/true | 18/6/d-035/26/true |  |  | true |
| B init-021 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 16/0//22/false | 16/0//22/false |  |  | true |
| B init-022 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 18/0//24/false | 18/0//24/false |  |  | true |
| B init-023 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 6/0//18/false | 6/0//18/false |  |  | true |
| B init-024 roadmap: feasible start / delay / binding dependency / finish / deployment before feasible start (09 vs Python domain) | 7/0//15/false | 7/0//15/false |  |  | true |
| B init-001 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 208360.24/35261.71/1.039443 | 208360.24/35261.71/1.039443 |  |  | true |
| B init-002 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 145565.89/-37445.59/1.030184 | 145565.89/-37445.59/1.030184 |  |  | true |
| B init-003 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 342656.33/31430.68/0.667307 | 342656.33/31430.68/0.667307 |  |  | true |
| B init-004 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 440993.63/-63009.39/1.023305 | 440993.63/-63009.39/1.023305 |  |  | true |
| B init-005 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 252616.97/-59088.59/ | 252616.97/-59088.59/ |  |  | true |
| B init-006 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 82379.87// | 82379.87// |  |  | true |
| B init-007 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 295112.49/23326.08/ | 295112.49/23326.08/ |  |  | true |
| B init-008 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 357251.72/-37080.34/0.975795 | 357251.72/-37080.34/0.975795 |  |  | true |
| B init-009 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 459451.10/-73360.58/ | 459451.10/-73360.58/ |  |  | true |
| B init-010 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 305503.93/121733.80/ | 305503.93/121733.80/ |  |  | true |
| B init-011 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 189094.36// | 189094.36// |  |  | true |
| B init-012 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 175983.24// | 175983.24// |  |  | true |
| B init-013 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 468552.25/170496.08/0.855768 | 468552.25/170496.08/0.855768 |  |  | true |
| B init-014 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 349000.46/84441.17/0.747375 | 349000.46/84441.17/0.747375 |  |  | true |
| B init-015 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 386126.29/93702.86/0.961240 | 386126.29/93702.86/0.961240 |  |  | true |
| B init-016 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 221238.35/-36605.56/0.877626 | 221238.35/-36605.56/0.877626 |  |  | true |
| B init-017 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 307078.26// | 307078.26// |  |  | true |
| B init-018 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 175392.44// | 175392.44// |  |  | true |
| B init-019 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 425891.03// | 425891.03// |  |  | true |
| B init-020 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 333380.00// | 333380.00// |  |  | true |
| B init-021 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 67682.66// | 67682.66// |  |  | true |
| B init-022 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 327861.93// | 327861.93// |  |  | true |
| B init-023 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 908693.93// | 908693.93// |  |  | true |
| B init-024 screen inputs: risk exposure / cost variance / cash realisation (11 vs Python domain) | 259912.21// | 259912.21// |  |  | true |
| B init-001 forecast: versions / original preserved / covers the original periods / latest minus original (08 vs Python domain) | 1/true/true/0.00 | 1/true/true/0.00 |  |  | true |
| B init-002 forecast: versions / original preserved / covers the original periods / latest minus original (08 vs Python domain) | 1/true/true/0.00 | 1/true/true/0.00 |  |  | true |
| B init-003 forecast: versions / original preserved / covers the original periods / latest minus original (08 vs Python domain) | 3/true/true/-211592.52 | 3/true/true/-211592.52 |  |  | true |
| B init-004 forecast: versions / original preserved / covers the original periods / latest minus original (08 vs Python domain) | 2/true/true/-52098.22 | 2/true/true/-52098.22 |  |  | true |
| B init-008 forecast: versions / original preserved / covers the original periods / latest minus original (08 vs Python domain) | 1/true/true/0.00 | 1/true/true/0.00 |  |  | true |
| B init-013 forecast: versions / original preserved / covers the original periods / latest minus original (08 vs Python domain) | 2/true/true/97833.89 | 2/true/true/97833.89 |  |  | true |
| B init-014 forecast: versions / original preserved / covers the original periods / latest minus original (08 vs Python domain) | 1/true/true/0.00 | 1/true/true/0.00 |  |  | true |
| B init-016 forecast: versions / original preserved / covers the original periods / latest minus original (08 vs Python domain) | 1/true/true/0.00 | 1/true/true/0.00 |  |  | true |
| B res-03 periods at capacity and their allocation (09 vs Python domain) | 12:2.00,13:2.00,14:2.00,15:2.00,16:2.00 | 12:2.00,13:2.00,14:2.00,15:2.00,16:2.00 |  |  | true |
| B resources: periods over capacity in every resource (09 vs Python domain) | 0 | 0 |  |  | true |
| B DEPLOYMENT_BEFORE_FEASIBLE_START warnings (09 vs Python domain warnings) | init-018,init-019,init-020 | init-018,init-019,init-020 |  |  | true |
| C 01_portfolio_ledger__by_scenario: 30 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 52a70f6127688156 | 52a70f6127688156 |  |  | true |
| C 01_portfolio_ledger__class_identity: 30 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 0a97b83e7c94472d | 0a97b83e7c94472d |  |  | true |
| C 01_portfolio_ledger__scn025_by_initiative: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 27e56b1624b000cd | 27e56b1624b000cd |  |  | true |
| C 02_initiative_npv__scn025: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 05afa2a4796d4bc3 | 05afa2a4796d4bc3 |  |  | true |
| C 02_initiative_npv__scn025_exact: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 78dbb3e645c1dbd9 | 78dbb3e645c1dbd9 |  |  | true |
| C 02_initiative_npv__portfolio_scn025: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 2f4cd11975da7f01 | 2f4cd11975da7f01 |  |  | true |
| C 02_initiative_npv__by_scenario: 30 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 5176f316cdcc7896 | 5176f316cdcc7896 |  |  | true |
| C 02_initiative_npv__by_scenario_exact: 30 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 0785004901e2dfb7 | 0785004901e2dfb7 |  |  | true |
| C 03_double_count__by_source_key: 2 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 01bd293bddac5855 | 01bd293bddac5855 |  |  | true |
| C 03_double_count__by_period: 10 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 0b2bd5924a9fdf95 | 0b2bd5924a9fdf95 |  |  | true |
| C 03_double_count__present_value_scn025: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 2c57fd32dc371240 | 2c57fd32dc371240 |  |  | true |
| C 03_double_count__by_scenario: 30 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 61cfee35e59d705d | 61cfee35e59d705d |  |  | true |
| C 03_double_count__outcome: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 689f6d6fc92480f5 | 689f6d6fc92480f5 |  |  | true |
| C 04_payback__scn025: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | c4674d9ebb60e996 | c4674d9ebb60e996 |  |  | true |
| C 04_payback__reasons: 2 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 632a046db01e72ee | 632a046db01e72ee |  |  | true |
| C 04_payback__never_pays_back: 9 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 1d59fb3957302423 | 1d59fb3957302423 |  |  | true |
| C 04_payback__init015_by_scenario: 8 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 95d35cfe011fa56c | 95d35cfe011fa56c |  |  | true |
| C 04_payback__last_crossing_rule: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 6491354a72a01fc9 | 6491354a72a01fc9 |  |  | true |
| C 05_cost_expansion__by_type: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 887c2ea21e204fa9 | 887c2ea21e204fa9 |  |  | true |
| C 05_cost_expansion__recurring_by_initiative: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 1ca2f100fcb1f564 | 1ca2f100fcb1f564 |  |  | true |
| C 05_cost_expansion__half_open_boundaries: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 3f9f594a89d8d31b | 3f9f594a89d8d31b |  |  | true |
| C 05_cost_expansion__one_time_rule: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | cdc979e41b9d95ca | cdc979e41b9d95ca |  |  | true |
| C 05_cost_expansion__inj11_key: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | abee86fd35b9c5bc | abee86fd35b9c5bc |  |  | true |
| C 05_cost_expansion__scn025_by_initiative: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 40453c4e5edd708b | 40453c4e5edd708b |  |  | true |
| C 06_variance_realisation__matured: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 8c767b129c7902ea | 8c767b129c7902ea |  |  | true |
| C 06_variance_realisation__cost_variance_scn025: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 9a77a7dbade033f7 | 9a77a7dbade033f7 |  |  | true |
| C 06_variance_realisation__variance_summary_scn025: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | ba0c6fb067eaf4cf | ba0c6fb067eaf4cf |  |  | true |
| C 06_variance_realisation__realisation_scn025: 31 row(s), every cell (SQL result set vs plain Python from the raw JSON) | e845fcb5cb741d46 | e845fcb5cb741d46 |  |  | true |
| C 06_variance_realisation__trend_beside_raw: 5 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 624fa546818ea8b1 | 624fa546818ea8b1 |  |  | true |
| C 06_variance_realisation__coverage: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 3aeaa6071cd9a50b | 3aeaa6071cd9a50b |  |  | true |
| C 07_adoption_training__by_initiative: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 6e514ebf879550cc | 6e514ebf879550cc |  |  | true |
| C 07_adoption_training__pooled: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 0ff921855c9d4881 | 0ff921855c9d4881 |  |  | true |
| C 07_adoption_training__common_population: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 52e457473b6954f3 | 52e457473b6954f3 |  |  | true |
| C 07_adoption_training__lag_to_half_adoption: 11 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 675c97289058b9e5 | 675c97289058b9e5 |  |  | true |
| C 07_adoption_training__lag_summary: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 866c45476b8fb6d0 | 866c45476b8fb6d0 |  |  | true |
| C 08_forecast_revisions__versions: 12 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 2c933c5d70689841 | 2c933c5d70689841 |  |  | true |
| C 08_forecast_revisions__original_preserved: 8 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 81fb3d901f6b2514 | 81fb3d901f6b2514 |  |  | true |
| C 08_forecast_revisions__init003_versions: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | d0dc1563c06c78ed | d0dc1563c06c78ed |  |  | true |
| C 08_forecast_revisions__init003_by_period: 12 row(s), every cell (SQL result set vs plain Python from the raw JSON) | b2fc857139c055b2 | b2fc857139c055b2 |  |  | true |
| C 08_forecast_revisions__revision_triggers: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | d6b4b2c9a50828ab | d6b4b2c9a50828ab |  |  | true |
| C 09_roadmap_capacity__dependency_delay: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 9db6cb5ad944e8de | 9db6cb5ad944e8de |  |  | true |
| C 09_roadmap_capacity__delay_summary: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 16bf2ec5d0158dfa | 16bf2ec5d0158dfa |  |  | true |
| C 09_roadmap_capacity__deployment_before_feasible_start: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 70c0df269939a88a | 70c0df269939a88a |  |  | true |
| C 09_roadmap_capacity__cycle_check: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | b4979144bf262b63 | b4979144bf262b63 |  |  | true |
| C 09_roadmap_capacity__refused_cycle: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | e1d63637b68664db | e1d63637b68664db |  |  | true |
| C 09_roadmap_capacity__resource_at_capacity: 5 row(s), every cell (SQL result set vs plain Python from the raw JSON) | bc0dac70de3318e4 | bc0dac70de3318e4 |  |  | true |
| C 09_roadmap_capacity__resources: 8 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 8e3b40e589ac87f1 | 8e3b40e589ac87f1 |  |  | true |
| C 09_roadmap_capacity__refused_requests: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 4bc7efa4c6b82646 | 4bc7efa4c6b82646 |  |  | true |
| C 11_proposal_screen__initiative_screen: 24 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 6bc19c88c6483238 | 6bc19c88c6483238 |  |  | true |
| C 11_proposal_screen__waiting: 6 row(s), every cell (SQL result set vs plain Python from the raw JSON) | c9c01bcdb2f8f385 | c9c01bcdb2f8f385 |  |  | true |
| C 11_proposal_screen__options: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | cb75d01fce25dc03 | cb75d01fce25dc03 |  |  | true |
| C 11_proposal_screen__dependency_ties: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 3243cbbbd9911d95 | 3243cbbbd9911d95 |  |  | true |
| C 10_golden_known_answer__cash_flow_init001: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 1d82059f9edf94d9 | 1d82059f9edf94d9 |  |  | true |
| C 10_golden_known_answer__init001_answer: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 0d9014ea5829019a | 0d9014ea5829019a |  |  | true |
| C 10_golden_known_answer__initiatives: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | a0a07b3750c18dee | a0a07b3750c18dee |  |  | true |
| C 10_golden_known_answer__portfolio: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 0ebcf98cc91fd51f | 0ebcf98cc91fd51f |  |  | true |
| D injection manifest and manifest carry the dataset hash and version of this package | 6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9/cw-20261026-20261026 | 6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9/cw-20261026-20261026 | 6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9/cw-20261026-20261026 |  | true |
| D DR-01 init-009 capacity only: hours not converted / cash benefits / NPV / simple payback (01, 02, 04 vs the manifest) | 2920.48/0.00/-761535.73/ | 2920.48/0.00/-761535.73/ |  |  | true |
| D DR-02 shared capacity in scn-025: planned / attributable / residual / PV / hours residual / plain NPV sum / attributable NPV (03 vs the manifest) | 32677894.70/32470748.38/207146.32/195233.20/5974.80/1438382.25/1243149.05 | 32677894.70/32470748.38/207146.32/195233.20/5974.80/1438382.25/1243149.05 |  |  | true |
| D DR-02 the key, its initiatives and periods: key / initiatives / first / last / overlapping periods (03 vs the manifest) | src-fin-ap-shared-team/init-001,init-002/3/12/10 | src-fin-ap-shared-team/init-001,init-002/3/12/10 |  |  | true |
| D DR-02 scenarios with a money residual / with an hours residual (03 vs the manifest) | scn-002,scn-003,scn-006,scn-025,scn-027/scn-001,scn-002,scn-003,scn-005,scn-006,scn-025,scn-027 | scn-002,scn-003,scn-006,scn-025,scn-027/scn-001,scn-002,scn-003,scn-005,scn-006,scn-025,scn-027 |  |  | true |
| D DR-03 init-015 in scn-013: ramp / cost / benefits entering / benefit-to-cost / NPV / both paybacks null (04 vs the manifest) | a-015-adopti-1/1299050.00/805466.72/0.620043/-508801.53/True | a-015-adopti-1/1299050.00/805466.72/0.620043/-508801.53/True |  |  | true |
| D DR-03 init-015 in scn-014: ramp / cost / benefits entering / benefit-to-cost / NPV / both paybacks null (04 vs the manifest) | a-015-adopti-1/1299050.00/805466.72/0.620043/-515329.28/True | a-015-adopti-1/1299050.00/805466.72/0.620043/-515329.28/True |  |  | true |
| D DR-03 init-015 in scn-015: ramp / cost / benefits entering / benefit-to-cost / NPV / both paybacks null (04 vs the manifest) | a-015-adopti-2/1299050.00/690400.00/0.531465/-618556.03/True | a-015-adopti-2/1299050.00/690400.00/0.531465/-618556.03/True |  |  | true |
| D DR-03 init-015 in scn-016: ramp / cost / benefits entering / benefit-to-cost / NPV / both paybacks null (04 vs the manifest) | a-015-adopti-1/1299050.00/805466.72/0.620043/-512146.04/True | a-015-adopti-1/1299050.00/805466.72/0.620043/-512146.04/True |  |  | true |
| D DR-03 init-015 in scn-017: ramp / cost / benefits entering / benefit-to-cost / NPV / both paybacks null (04 vs the manifest) | a-015-adopti-1/1299050.00/805466.72/0.620043/-512146.04/True | a-015-adopti-1/1299050.00/805466.72/0.620043/-512146.04/True |  |  | true |
| D DR-03 init-015 in scn-018: ramp / cost / benefits entering / benefit-to-cost / NPV / both paybacks null (04 vs the manifest) | a-015-adopti-2/1299050.00/690400.00/0.531465/-619344.67/True | a-015-adopti-2/1299050.00/690400.00/0.531465/-619344.67/True |  |  | true |
| D DR-03 init-015 in scn-025: ramp / cost / benefits entering / benefit-to-cost / NPV / both paybacks null (04 vs the manifest) | a-015-adopti-2/1299050.00/690400.00/0.531465/-618556.03/True | a-015-adopti-2/1299050.00/690400.00/0.531465/-618556.03/True |  |  | true |
| D DR-03 init-015 in scn-026: ramp / cost / benefits entering / benefit-to-cost / NPV / both paybacks null (04 vs the manifest) | a-015-adopti-2/1299050.00/690400.00/0.531465/-618556.03/True | a-015-adopti-2/1299050.00/690400.00/0.531465/-618556.03/True |  |  | true |
| D DR-04 init-003 forecast totals v1 / v2 / v3 / latest minus original (08 vs the manifest) | 745800.06/598900.05/534207.54/-211592.52 | 745800.06/598900.05/534207.54/-211592.52 |  |  | true |
| D DR-04 the misses behind each revision: periods checked / periods more than 10 % below / lowest and highest observed over forecast (08 vs the manifest) | 3,4/3,4/0.672385/0.678912;5,6,7/5,6,7/0.792000/0.849750 | 3,4/3,4/0.672385/0.678912;5,6,7/5,6,7/0.792000/0.849750 |  |  | true |
| D DR-04 the latest observed cash value of each matured period (08 vs the manifest) | 3:1844.17,4:5993.50,5:11522.63,6:19017.91,7:26848.82,8:40340.98 | 3:1844.17,4:5993.50,5:11522.63,6:19017.91,7:26848.82,8:40340.98 |  |  | true |
| D DR-05 res-03 at capacity: periods / allocated / headroom / refused requests / refused periods (09 vs the manifest) | 12,13,14,15,16/2.00,2.00,2.00,2.00,2.00/0.00,0.00,0.00,0.00,0.00/3/14,15,16 | 12,13,14,15,16/2.00,2.00,2.00,2.00,2.00/0.00,0.00,0.00,0.00,0.00/3/14,15,16 |  |  | true |
| D DR-06 init-008 cash: planned / observed / realisation / trend / above trend / trend share / rows / attribution (06 vs the manifest) | 173800.00/169593.13/0.975795/143941.18/25651.95/0.848744/6/observed, not attributed | 173800.00/169593.13/0.975795/143941.18/25651.95/0.848744/6/observed, not attributed |  |  | true |
| D DR-07 pooled adoption / pooled training / lags / never reached half adoption (07 vs the manifest) | 0.532881/0.888443/4,4,5,5,6/init-003,init-004,init-009,init-014,init-015,init-016 | 0.532881/0.888443/4,4,5,5,6/init-003,init-004,init-009,init-014,init-015,init-016 |  |  | true |
| D DR-07 per initiative: training 90 % on / adoption 50 % on / lag / periods since / training now / adoption now (07 vs the manifest, digest) | 4d98ecb0615c2b0f | 4d98ecb0615c2b0f |  |  | true |
| D manifest stats.scenarios scn-001: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 953382.86/0.00/0.006434/36 | 953382.86/0.00/0.006434/36 |  |  | true |
| D manifest stats.scenarios scn-002: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 1850194.72/253178.85/0.009489/36 | 1850194.72/253178.85/0.009489/36 |  |  | true |
| D manifest stats.scenarios scn-003: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 1741529.16/253178.85/0.006434/24 | 1741529.16/253178.85/0.006434/24 |  |  | true |
| D manifest stats.scenarios scn-004: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 99957.44/0.00/0.007974/36 | 99957.44/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-005: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 892632.76/0.00/0.007974/36 | 892632.76/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-006: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 1329339.78/207146.32/0.007000/36 | 1329339.78/207146.32/0.007000/36 |  |  | true |
| D manifest stats.scenarios scn-007: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 791876.77/0.00/0.006434/36 | 791876.77/0.00/0.006434/36 |  |  | true |
| D manifest stats.scenarios scn-008: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 804919.25/0.00/0.009489/36 | 804919.25/0.00/0.009489/36 |  |  | true |
| D manifest stats.scenarios scn-009: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 334667.51/0.00/0.006434/24 | 334667.51/0.00/0.006434/24 |  |  | true |
| D manifest stats.scenarios scn-010: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -362653.93/0.00/0.007974/36 | -362653.93/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-011: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 706407.57/0.00/0.007974/36 | 706407.57/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-012: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 322261.60/0.00/0.007000/36 | 322261.60/0.00/0.007000/36 |  |  | true |
| D manifest stats.scenarios scn-013: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 817592.33/0.00/0.006434/36 | 817592.33/0.00/0.006434/36 |  |  | true |
| D manifest stats.scenarios scn-014: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 796700.44/0.00/0.009489/36 | 796700.44/0.00/0.009489/36 |  |  | true |
| D manifest stats.scenarios scn-015: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -47204.81/0.00/0.006434/24 | -47204.81/0.00/0.006434/24 |  |  | true |
| D manifest stats.scenarios scn-016: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -61970.90/0.00/0.007974/36 | -61970.90/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-017: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 744598.77/0.00/0.007974/36 | 744598.77/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-018: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 52603.38/0.00/0.007000/36 | 52603.38/0.00/0.007000/36 |  |  | true |
| D manifest stats.scenarios scn-019: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -543120.97/0.00/0.006434/36 | -543120.97/0.00/0.006434/36 |  |  | true |
| D manifest stats.scenarios scn-020: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -661017.95/0.00/0.009489/36 | -661017.95/0.00/0.009489/36 |  |  | true |
| D manifest stats.scenarios scn-021: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -1380296.98/0.00/0.006434/24 | -1380296.98/0.00/0.006434/24 |  |  | true |
| D manifest stats.scenarios scn-022: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 673071.47/0.00/0.007974/36 | 673071.47/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-023: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -604162.03/0.00/0.007974/36 | -604162.03/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-024: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -565945.30/0.00/0.007000/36 | -565945.30/0.00/0.007000/36 |  |  | true |
| D manifest stats.scenarios scn-025: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 1243149.05/207146.32/0.006434/36 | 1243149.05/207146.32/0.006434/36 |  |  | true |
| D manifest stats.scenarios scn-026: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 1024993.83/0.00/0.006434/36 | 1024993.83/0.00/0.006434/36 |  |  | true |
| D manifest stats.scenarios scn-027: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 1645520.17/207146.32/0.007974/24 | 1645520.17/207146.32/0.007974/24 |  |  | true |
| D manifest stats.scenarios scn-028: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 147903.44/0.00/0.007974/36 | 147903.44/0.00/0.007974/36 |  |  | true |
| D manifest stats.scenarios scn-029: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | -1343076.84/0.00/0.009489/36 | -1343076.84/0.00/0.009489/36 |  |  | true |
| D manifest stats.scenarios scn-030: attributable NPV / residual / period rate / horizon (02, 03, 01 vs the manifest) | 1748559.44/0.00/0.007974/36 | 1748559.44/0.00/0.007974/36 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-001: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 578533.26/10/10/35261.71/0.841346/0.948235 | 578533.26/10/10/35261.71/0.841346/0.948235 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-002: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 413388.43/10/11/-37445.59/0.578512/0.968794 | 413388.43/10/11/-37445.59/0.578512/0.968794 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-003: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 363049.68/12/12/31430.68/0.232258/0.977918 | 363049.68/12/12/31430.68/0.232258/0.977918 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-004: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 523302.08/14/14/-63009.39/0.444444/0.959792 | 523302.08/14/14/-63009.39/0.444444/0.959792 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-005: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 209002.21/19/19/-59088.59//0.023753 | 209002.21/19/19/-59088.59//0.023753 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-006: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | -535631.92///// | -535631.92///// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-007: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 415366.00/11/11/23326.08/0.739708/0.979702 | 415366.00/11/11/23326.08/0.739708/0.979702 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-008: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 65253.91/13/13/-37080.34/0.710462/0.968370 | 65253.91/13/13/-37080.34/0.710462/0.968370 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-009: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | -761535.73///-73360.58/0.412742/0.958904 | -761535.73///-73360.58/0.412742/0.958904 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-010: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 423409.74/18/18/121733.80//0.948819 | 423409.74/18/18/121733.80//0.948819 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-011: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 84012.76/21/21/// | 84012.76/21/21/// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-012: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 126524.02/27/27/// | 126524.02/27/27/// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-013: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 463582.30/11/11/170496.08/0.708772/0.949233 | 463582.30/11/11/170496.08/0.708772/0.949233 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-014: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 76930.78/15/16/84441.17/0.229508/0.979592 | 76930.78/15/16/84441.17/0.229508/0.979592 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-015: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | -618556.03///93702.86/0.349544/0.979412 | -618556.03///93702.86/0.349544/0.979412 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-016: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 46285.40/17/17/-36605.56/0.174334/0.938875 | 46285.40/17/17/-36605.56/0.174334/0.938875 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-017: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 93546.29/22/23/// | 93546.29/22/23/// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-018: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 15040.08/28/28/// | 15040.08/28/28/// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-019: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | -1002807.01///// | -1002807.01///// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-020: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 112711.77/27/27/// | 112711.77/27/27/// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-021: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | -337229.75///// | -337229.75///// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-022: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | -61430.84///// | -61430.84///// |  |  | true |
| D manifest stats initiatives_in_scn-025 init-023: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 515502.07/22/22///0.968182 | 515502.07/22/22///0.968182 |  |  | true |
| D manifest stats initiatives_in_scn-025 init-024: NPV / simple / discounted payback / cost variance / adoption / training (02, 04, 06, 07 vs the manifest) | 230132.79/20/21///0.511111 | 230132.79/20/21///0.511111 |  |  | true |
| D manifest stats.deployment_before_feasible_start: initiative / deployment / feasible start / periods early (09 vs the manifest) | init-018/18/22/4;init-019/14/19/5;init-020/16/18/2 | init-018/18/22/4;init-019/14/19/5;init-020/16/18/2 |  |  | true |
| D manifest stats.summary: npv_total / hours residual / adoption / training (leaves of the summary scenario scn-001 vs the manifest) | 953382.86/7302.53/0.532881/0.888443 | 953382.86/7302.53/0.532881/0.888443 |  |  | true |
| D manifest stats.forecast_version_sets (08 vs the manifest) | 12 | 12 |  |  | true |
| D INJ-01 (time savings booked as cash without a staffing change): the 3 dataset checks the analysis leaves cover (analysis vs the injection manifest, digest) | fa8dca13da99b85c | fa8dca13da99b85c |  |  | true |
| D INJ-02 (two initiatives claim the same released capacity): the 20 dataset checks the analysis leaves cover (analysis vs the injection manifest, digest) | 6cffad9c751a5c42 | 6cffad9c751a5c42 |  |  | true |
| D INJ-05 (training completion substituted for adoption): the 4 dataset checks the analysis leaves cover (analysis vs the injection manifest, digest) | d32badd4aed30cc5 | d32badd4aed30cc5 |  |  | true |
| D INJ-07 (a dependency cycle): the 3 dataset checks the analysis leaves cover (analysis vs the injection manifest, digest) | d58323061c0cb749 | d58323061c0cb749 |  |  | true |
| D INJ-08 (a case that never pays back presented with a payback): the 24 dataset checks the analysis leaves cover (analysis vs the injection manifest, digest) | fabbf549c56bb948 | fabbf549c56bb948 |  |  | true |
| D INJ-10 (an improvement attributed entirely to the rollout): the 5 dataset checks the analysis leaves cover (analysis vs the injection manifest, digest) | cb566f53d7a72cca | cb566f53d7a72cca |  |  | true |
| D INJ-12 (cost avoidance added to realised cash savings): the 4 dataset checks the analysis leaves cover (analysis vs the injection manifest, digest) | e8ceaa0d5b830d91 | e8ceaa0d5b830d91 |  |  | true |
| D INJ-07 the refused edge closes the cycle the replay event lists (09 vs the injection manifest) | init-001,init-004,init-001 | init-001,init-004,init-001 |  |  | true |
| D INJ-07 the stored graph has no cycle (09 cycle_check) | 0 | 0 |  |  | true |
| D INJ-11 the one-time cost key is stored once, in its first period (05 vs the injection manifest) | c-0042/1/1/0 | c-0042/1/1/0 |  |  | true |
| D INJ-11 no one-time cost key repeats and no key is of two kinds (05) | 0/0 | 0/0 |  |  | true |
| E BI row counts: dim_initiative / dim_scenario / dim_period / dim_resource / fact_scenario / fact_scenario_initiative / fact_forecast / fact_risk / fact_adoption | 24/30/36/8/30/210/144/120/24 | 24/30/36/8/30/210/144/120/24 |  |  | true |
| E BI fact_cash_flow rows equal the sum of the scenario horizons over their initiatives | 7212 | 7212 |  |  | true |
| E BI scn-001: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 953382.86/953382.86/0.00/7624466.78/0.00/7302.53 | 953382.86/953382.86/0.00/7624466.78/0.00/7302.53 | 953382.86/953382.86/0.00/7624466.78/0.00/7302.53 |  | true |
| E BI scn-001: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 5564850.00/5111800.12/0.00/1675266.64/0.00/837400.02/81230.96 | 5564850.00/5111800.12/0.00/1675266.64/0.00/837400.02/81230.96 |  |  | true |
| E BI scn-002: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 1850194.72/2083397.09/233202.37/9008552.27/253178.85/7302.53 | 1850194.72/2083397.09/233202.37/9008552.27/253178.85/7302.53 | 1850194.72/2083397.09/233202.37/9008552.27/253178.85/7302.53 |  | true |
| E BI scn-002: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 5564850.00/4988733.57/0.00/1524866.79/1657551.89/837400.02/32429.32 | 5564850.00/4988733.57/0.00/1524866.79/1657551.89/837400.02/32429.32 |  |  | true |
| E BI scn-003: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 1741529.16/1980952.24/239423.08/8635351.21/253178.85/7302.53 | 1741529.16/1980952.24/239423.08/8635351.21/253178.85/7302.53 | 1741529.16/1980952.24/239423.08/8635351.21/253178.85/7302.53 |  | true |
| E BI scn-003: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 5526650.00/4839200.16/0.00/1425200.08/1601650.95/769300.02/26109.04 | 5526650.00/4839200.16/0.00/1425200.08/1601650.95/769300.02/26109.04 |  |  | true |
| E BI scn-004: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 99957.44/99957.44/0.00/4314399.87/0.00/0.00 | 99957.44/99957.44/0.00/4314399.87/0.00/0.00 | 99957.44/99957.44/0.00/4314399.87/0.00/0.00 |  | true |
| E BI scn-004: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 3571000.00/2860599.95/0.00/977599.92/0.00/476199.99/59608.33 | 3571000.00/2860599.95/0.00/977599.92/0.00/476199.99/59608.33 |  |  | true |
| E BI scn-005: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 892632.76/892632.76/0.00/7624466.78/0.00/7302.53 | 892632.76/892632.76/0.00/7624466.78/0.00/7302.53 | 892632.76/892632.76/0.00/7624466.78/0.00/7302.53 |  | true |
| E BI scn-005: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 5564850.00/5111800.12/0.00/1675266.64/0.00/837400.02/81230.96 | 5564850.00/5111800.12/0.00/1675266.64/0.00/837400.02/81230.96 |  |  | true |
| E BI scn-006: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 1329339.78/1523563.61/194223.83/8197554.34/207146.32/5974.80 | 1329339.78/1523563.61/194223.83/8197554.34/207146.32/5974.80 | 1329339.78/1523563.61/194223.83/8197554.34/207146.32/5974.80 |  | true |
| E BI scn-006: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 5564850.00/4531533.55/0.00/1425200.08/1495687.35/745133.37/32429.32 | 5564850.00/4531533.55/0.00/1425200.08/1495687.35/745133.37/32429.32 |  |  | true |
| E BI scn-007: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 791876.77/791876.77/0.00/9723216.38/0.00/0.00 | 791876.77/791876.77/0.00/9723216.38/0.00/0.00 | 791876.77/791876.77/0.00/9723216.38/0.00/0.00 |  | true |
| E BI scn-007: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6772650.00/1377066.72/6573733.08/0.00/0.00/1772416.58/51825.80 | 6772650.00/1377066.72/6573733.08/0.00/0.00/1772416.58/51825.80 |  |  | true |
| E BI scn-008: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 804919.25/804919.25/0.00/9919341.91/0.00/0.00 | 804919.25/804919.25/0.00/9919341.91/0.00/0.00 | 804919.25/804919.25/0.00/9919341.91/0.00/0.00 |  | true |
| E BI scn-008: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6772650.00/1377066.72/6573733.08/0.00/196125.53/1772416.58/45414.38 | 6772650.00/1377066.72/6573733.08/0.00/196125.53/1772416.58/45414.38 |  |  | true |
| E BI scn-009: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 334667.51/334667.51/0.00/8914958.48/0.00/0.00 | 334667.51/334667.51/0.00/8914958.48/0.00/0.00 | 334667.51/334667.51/0.00/8914958.48/0.00/0.00 |  | true |
| E BI scn-009: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6687700.00/1261200.00/5872466.38/0.00/196125.53/1585166.58/30479.81 | 6687700.00/1261200.00/5872466.38/0.00/196125.53/1585166.58/30479.81 |  |  | true |
| E BI scn-010: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -362653.93/-362653.93/0.00/2758599.79/0.00/0.00 | -362653.93/-362653.93/0.00/2758599.79/0.00/0.00 | -362653.93/-362653.93/0.00/2758599.79/0.00/0.00 |  | true |
| E BI scn-010: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 2347700.00/0.00/2122033.17/0.00/0.00/636566.62/11441.31 | 2347700.00/0.00/2122033.17/0.00/0.00/636566.62/11441.31 |  |  | true |
| E BI scn-011: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 706407.57/706407.57/0.00/9723216.38/0.00/0.00 | 706407.57/706407.57/0.00/9723216.38/0.00/0.00 | 706407.57/706407.57/0.00/9723216.38/0.00/0.00 |  | true |
| E BI scn-011: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6772650.00/1377066.72/6573733.08/0.00/0.00/1772416.58/51825.80 | 6772650.00/1377066.72/6573733.08/0.00/0.00/1772416.58/51825.80 |  |  | true |
| E BI scn-012: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 322261.60/322261.60/0.00/9146835.90/0.00/0.00 | 322261.60/322261.60/0.00/9146835.90/0.00/0.00 | 322261.60/322261.60/0.00/9146835.90/0.00/0.00 |  | true |
| E BI scn-012: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6772650.00/1261200.00/6074000.13/0.00/165952.40/1645683.37/43836.21 | 6772650.00/1261200.00/6074000.13/0.00/165952.40/1645683.37/43836.21 |  |  | true |
| E BI scn-013: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 817592.33/817592.33/0.00/8063433.53/0.00/0.00 | 817592.33/817592.33/0.00/8063433.53/0.00/0.00 | 817592.33/817592.33/0.00/8063433.53/0.00/0.00 |  | true |
| E BI scn-013: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6189550.00/5324500.14/0.00/2010466.68/0.00/728466.72/49795.74 | 6189550.00/5324500.14/0.00/2010466.68/0.00/728466.72/49795.74 |  |  | true |
| E BI scn-014: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 796700.44/796700.44/0.00/8196235.37/0.00/0.00 | 796700.44/796700.44/0.00/8196235.37/0.00/0.00 | 796700.44/796700.44/0.00/8196235.37/0.00/0.00 |  | true |
| E BI scn-014: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6189550.00/5324500.14/0.00/2010466.68/132801.84/728466.72/46399.27 | 6189550.00/5324500.14/0.00/2010466.68/132801.84/728466.72/46399.27 |  |  | true |
| E BI scn-015: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -47204.81/-47204.81/0.00/7013371.25/0.00/0.00 | -47204.81/-47204.81/0.00/7013371.25/0.00/0.00 | -47204.81/-47204.81/0.00/7013371.25/0.00/0.00 |  | true |
| E BI scn-015: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6121500.00/4470233.63/0.00/1736833.45/112370.80/693933.37/41245.09 | 6121500.00/4470233.63/0.00/1736833.45/112370.80/693933.37/41245.09 |  |  | true |
| E BI scn-016: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -61970.90/-61970.90/0.00/4172466.96/0.00/0.00 | -61970.90/-61970.90/0.00/4172466.96/0.00/0.00 | -61970.90/-61970.90/0.00/4172466.96/0.00/0.00 |  | true |
| E BI scn-016: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 3328800.00/2986666.88/0.00/457333.37/0.00/728466.72/38540.98 | 3328800.00/2986666.88/0.00/457333.37/0.00/728466.72/38540.98 |  |  | true |
| E BI scn-017: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 744598.77/744598.77/0.00/8063433.53/0.00/0.00 | 744598.77/744598.77/0.00/8063433.53/0.00/0.00 | 744598.77/744598.77/0.00/8063433.53/0.00/0.00 |  | true |
| E BI scn-017: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6189550.00/5324500.14/0.00/2010466.68/0.00/728466.72/49795.74 | 6189550.00/5324500.14/0.00/2010466.68/0.00/728466.72/49795.74 |  |  | true |
| E BI scn-018: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 52603.38/52603.38/0.00/7185404.43/0.00/0.00 | 52603.38/52603.38/0.00/7185404.43/0.00/0.00 | 52603.38/52603.38/0.00/7185404.43/0.00/0.00 |  | true |
| E BI scn-018: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6189550.00/4641500.18/0.00/1807133.45/112370.80/624400.00/40893.41 | 6189550.00/4641500.18/0.00/1807133.45/112370.80/624400.00/40893.41 |  |  | true |
| E BI scn-019: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -543120.97/-543120.97/0.00/8148100.02/0.00/0.00 | -543120.97/-543120.97/0.00/8148100.02/0.00/0.00 | -543120.97/-543120.97/0.00/8148100.02/0.00/0.00 |  | true |
| E BI scn-019: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 7387150.00/4853833.47/0.00/2284099.82/0.00/1010166.73/27886.67 | 7387150.00/4853833.47/0.00/2284099.82/0.00/1010166.73/27886.67 |  |  | true |
| E BI scn-020: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -661017.95/-661017.95/0.00/8148100.02/0.00/0.00 | -661017.95/-661017.95/0.00/8148100.02/0.00/0.00 | -661017.95/-661017.95/0.00/8148100.02/0.00/0.00 |  | true |
| E BI scn-020: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 7387150.00/4853833.47/0.00/2284099.82/0.00/1010166.73/27886.67 | 7387150.00/4853833.47/0.00/2284099.82/0.00/1010166.73/27886.67 |  |  | true |
| E BI scn-021: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -1380296.98/-1380296.98/0.00/6538483.30/0.00/0.00 | -1380296.98/-1380296.98/0.00/6538483.30/0.00/0.00 | -1380296.98/-1380296.98/0.00/6538483.30/0.00/0.00 |  | true |
| E BI scn-021: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6993000.00/3454666.74/0.00/2284099.82/0.00/799716.73/13466.00 | 6993000.00/3454666.74/0.00/2284099.82/0.00/799716.73/13466.00 |  |  | true |
| E BI scn-022: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 673071.47/673071.47/0.00/5895166.52/0.00/0.00 | 673071.47/673071.47/0.00/5895166.52/0.00/0.00 | 673071.47/673071.47/0.00/5895166.52/0.00/0.00 |  | true |
| E BI scn-022: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 4330500.00/3129000.00/0.00/2284099.82/0.00/482066.70/7812.00 | 4330500.00/3129000.00/0.00/2284099.82/0.00/482066.70/7812.00 |  |  | true |
| E BI scn-023: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -604162.03/-604162.03/0.00/8148100.02/0.00/0.00 | -604162.03/-604162.03/0.00/8148100.02/0.00/0.00 | -604162.03/-604162.03/0.00/8148100.02/0.00/0.00 |  | true |
| E BI scn-023: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 7387150.00/4853833.47/0.00/2284099.82/0.00/1010166.73/27886.67 | 7387150.00/4853833.47/0.00/2284099.82/0.00/1010166.73/27886.67 |  |  | true |
| E BI scn-024: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -565945.30/-565945.30/0.00/8148100.02/0.00/0.00 | -565945.30/-565945.30/0.00/8148100.02/0.00/0.00 | -565945.30/-565945.30/0.00/8148100.02/0.00/0.00 |  | true |
| E BI scn-024: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 7387150.00/4853833.47/0.00/2284099.82/0.00/1010166.73/27886.67 | 7387150.00/4853833.47/0.00/2284099.82/0.00/1010166.73/27886.67 |  |  | true |
| E BI scn-025: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 1243149.05/1438382.25/195233.20/32677894.70/207146.32/5974.80 | 1243149.05/1438382.25/195233.20/32677894.70/207146.32/5974.80 | 1243149.05/1438382.25/195233.20/32677894.70/207146.32/5974.80 |  | true |
| E BI scn-025: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 25914200.00/15288067.20/6074000.13/5516433.35/1774010.55/4025383.47/145045.62 | 25914200.00/15288067.20/6074000.13/5516433.35/1774010.55/4025383.47/145045.62 |  |  | true |
| E BI scn-026: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 1024993.83/1024993.83/0.00/31059699.61/0.00/0.00 | 1024993.83/1024993.83/0.00/31059699.61/0.00/0.00 | 1024993.83/1024993.83/0.00/31059699.61/0.00/0.00 |  | true |
| E BI scn-026: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 25083450.00/14255667.20/6074000.13/5516433.35/1497815.46/3715783.47/145045.62 | 25083450.00/14255667.20/6074000.13/5516433.35/1497815.46/3715783.47/145045.62 |  |  | true |
| E BI scn-027: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 1645520.17/1838021.19/192501.02/10075357.56/207146.32/5974.80 | 1645520.17/1838021.19/192501.02/10075357.56/207146.32/5974.80 | 1645520.17/1838021.19/192501.02/10075357.56/207146.32/5974.80 |  | true |
| E BI scn-027: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 6704050.00/4034633.46/2787166.88/1357000.07/889923.76/1006633.40/6548.48 | 6704050.00/4034633.46/2787166.88/1357000.07/889923.76/1006633.40/6548.48 |  |  | true |
| E BI scn-028: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 147903.44/147903.44/0.00/9786633.43/0.00/0.00 | 147903.44/147903.44/0.00/9786633.43/0.00/0.00 | 147903.44/147903.44/0.00/9786633.43/0.00/0.00 |  | true |
| E BI scn-028: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 8209100.00/5954133.49/0.00/2940233.20/0.00/892266.73/44237.80 | 8209100.00/5954133.49/0.00/2940233.20/0.00/892266.73/44237.80 |  |  | true |
| E BI scn-029: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | -1343076.84/-1343076.84/0.00/7014750.47/0.00/0.00 | -1343076.84/-1343076.84/0.00/7014750.47/0.00/0.00 | -1343076.84/-1343076.84/0.00/7014750.47/0.00/0.00 |  | true |
| E BI scn-029: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 7128200.00/4141766.94/1164800.08/656133.38/0.00/1052050.07/86695.45 | 7128200.00/4141766.94/1164800.08/656133.38/0.00/1052050.07/86695.45 |  |  | true |
| E BI scn-030: attributable NPV / plain sum / PV / planned benefits / residual / hours residual (CSV facts vs 02/01 vs Python domain) | 1748559.44/1748559.44/0.00/18130191.00/0.00/0.00 | 1748559.44/1748559.44/0.00/18130191.00/0.00/0.00 | 1748559.44/1748559.44/0.00/18130191.00/0.00/0.00 |  | true |
| E BI scn-030: costs and the four classes and beside and hours not converted (CSV facts vs 01) | 13531550.00/8526300.26/2585633.17/4262299.97/996457.60/1759500.01/44838.09 | 13531550.00/8526300.26/2585633.17/4262299.97/996457.60/1759500.01/44838.09 |  |  | true |
| E BI pooled adoption / pooled training / common-population training (CSV facts vs 07 vs Python domain summary) | 0.532881/0.888443/0.963778 | 0.532881/0.888443/0.963778 | 0.532881/0.888443/0.963778 |  | true |
| E BI init-003 forecast totals and latest minus original (CSV facts vs 08) | 745800.06/598900.05/534207.54/-211592.52 | 745800.06/598900.05/534207.54/-211592.52 |  |  | true |
| E BI res-03 periods at capacity / periods over capacity (CSV facts vs 09) | 5/0 | 5/0 |  |  | true |
| E BI risk exposure (CSV facts vs Python domain summary vs reference SQL) | 7485779.58 | 7485779.58 | 7485779.58 |  | true |
| E BI scn-025 initiatives never paying back (CSV facts vs 04) | 6 | 6 |  |  | true |
| E BI scn-025 cash realisation of every initiative with a matured cash row (CSV facts vs 06, digest) | 78fc52fea80d5276 | 78fc52fea80d5276 |  |  | true |
| E BI nothing withheld silently: rows with an empty value / of them with a non-value status / rows with an empty scope | 19/19/0 | 19/19/0 |  |  | true |
<!-- END:reconciliation -->

All 763 rows are equal again on the final run (`RESULT: OK (763 reconciliation rows, 763 equal; 56 result sets, 567 rows; 48476 + 167 leaves equal to the reference SQL and the domain)`).
