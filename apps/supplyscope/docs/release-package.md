# Release package (P03-ART-10)

SupplyScope, business-data-lab project 03. **Synthetic data only**; nothing here is a claim about a real company, real purchase orders, stockouts or savings. Facts below are copied from `../../docs/program/release-manifest.json` (updated 2026-10-26T15:24:58Z or later) and
`verification-ledger.json`; this package did not fetch `github.io` and **committed and pushed nothing**: the artifact files listed below are uncommitted files in the worktree (`CLAUDE.md`: work goes to the private remote on `unified-portfolio` only; the owner decides what reaches the public site).

## Where it lives
| Item | Value |
|---|---|
| Site URL | https://mrrishit909.github.io/projects-site/labs/supplyscope/ |
| Portfolio case study | https://mrrishit909.github.io/projects-site/supplyscope/ (`program-status.json` `portfolio_case_study`) |
| Source | https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/supplyscope (branch `business-data-lab`; manifest `source_commit_business_data_lab` `12f866f385202f93c90eaff3f3a68560b29356fa`, contract v1) |
| Dataset | `ss-20261026-20261026`, generator `dataset_hash` `5bdabb50eea4b192e3b17e1e5b1a79dc6b26feb4a2b8b78ad094acde9f8bcc8c` (seed 20261026, 60 SKUs, 3 locations, 4 suppliers, 548 days, 4.33 MB) |
| Published tree | 55 files under `labs/supplyscope/`, sha256 `7c25780b5586ec6ff10973bca78c4e5a4bea5b3bab7db674964e765b2f637a70` (manifest) |
| Live verification | https://github.com/mrrishit909/projects-site/actions/runs/40347873614 (all jobs success, 2026-10-26T15:23:27Z); portfolio link both ways: https://github.com/mrrishit909/projects-site/actions/runs/40348856013 |
| Hosted CI | https://github.com/mrrishit909/projects-site/actions/runs/40348560761 (Mode A 132 tests with `postgres:16`; Mode B 221 TypeScript checks and 36 Playwright tests; code `a4a4364`) |
| Status | published, live-verified and integrated; reviewer findings R3-01..R3-07 and S-02, S-03 **fixed in T-03-07 and awaiting a hosted run and a new ledger entry** (`docs/uat-evidence.md`), so the verification is provisional until then |

## Release and rollback commits (branch `unified-portfolio`)
| Commit | What it is | Role |
|---|---|---|
| `7df1914` | Publish the SupplyScope static site at `labs/supplyscope` (55 files) | **release commit** (manifest) |
| `244acba` | the last `unified-portfolio` state without SupplyScope | **rollback commit** (manifest) |
| `a27b151`, `a1185b9` | integration commits named by the ledger entry for run 40348856013 (portfolio case study links to the site and the site links back) | integration |

The branch history was not inspected by this package (read-only use of the manifest and ledger only), so the order of any later commits is not asserted here.

## Rollback procedure (not executed; nothing was committed or pushed by this package)
Per `CLAUDE.md`, work goes to the private remote on `unified-portfolio` only; the owner decides what reaches the public site.
1. `git switch unified-portfolio && git pull private unified-portfolio`
2. Remove SupplyScope: `git revert --no-edit 7df1914` and the integration commits, newest first (`git revert --no-edit a1185b9 a27b151 7df1914`; confirm each hash with `git log` first); the tree should then equal `244acba` for these paths (check with `git diff 244acba -- supplyscope labs/supplyscope`), then `python3 build.py` and confirm `index.html` and `all.html` no longer list it.
3. `git push private unified-portfolio` (never `origin`, never `main`). Verify with the live-check workflow after the owner publishes.
Use `git revert`, not a reset or force push, so history stays auditable.

## Main-portfolio metadata
| Field | Value |
|---|---|
| Title | SupplyScope |
| Slug / case study | `supplyscope` |
| Kind | Business data lab: decision-support analytics (synthetic data) |
| Tagline | What should be ordered, when, and under which service and working-capital assumptions? |
| Tools | Python, PostgreSQL 16, FastAPI, TypeScript, React, Vite, Playwright, GitHub Actions, LibreOffice (workbook recalculation) |
| Evidence | Golden fixture (position 60 gives an order of 72; position 80 gives none), the golden position and order reconciled from three sources (analysis SQL, `reference_metrics.sql`, Python domain), 91 snapshot reconciliation checks, 132 local Python tests, 221 TypeScript golden checks, 36 Playwright tests, hosted CI runs in `technical-case-study.md` |
| Disclosure | Synthetic data; designed-in relationships (`web/public/data/manifest.json`); static demo (the simulator runs in the browser and nothing is persisted); decision S-04; S-02, S-03 and reviewer findings R3-01..R3-07 fixed in T-03-07 (not yet re-reviewed); no real savings claimed |

## What this artifact pass ran (2026-10-26, scratch databases `supplyscope_artifacts`, `supplyscope_artifacts_golden`, `supplyscope_artifacts_tests`; never the shared `supplyscope`)
| Command | Exit code |
|---|---|
| `prepare_snapshot.py` (snapshot and `--golden`) | 0 and 0 |
| `psql -v ON_ERROR_STOP=1 -f` each of `00_ledger_views.sql` .. `08_rejections_and_defects_by_reason.sql`, `bi_fact_movement_day.sql`, `bi_fact_draft_order.sql` (snapshot) and `09_golden_position_and_order.sql` (golden) | 0 for every file |
| `run_all.py --json artifacts/analysis-results.json` | 0 (`RESULT: OK`, 91 reconciliation rows equal) |
| `build_workbook.py --recalc` (LibreOffice headless) | 0 |
| `pytest -q tests/test_artifacts.py` with `ARTIFACTS_DATABASE_URL` set | 0 (25 passed, 18 s; 4 of them recalculate copies of the workbook with LibreOffice) |
| `pytest -q` (the whole suite, `DATABASE_URL` and `ARTIFACTS_DATABASE_URL` set) | 0 (157 passed in 94 s: the 132 of the existing suite plus 25) |
| `python3 -I tests/reference_check.py` | 0 (ALL OK) |

Not run: Microsoft Excel, Power BI Desktop (no `.pbix` exists), a hosted CI run of `tests/test_artifacts.py` (it is not part of `supplyscope-ci.yml`).

## Artifacts and checksums (sha256; also `artifacts/CHECKSUMS.txt`, verifiable with `sha256sum -c artifacts/CHECKSUMS.txt` from `apps/supplyscope`)
<!-- BEGIN:checksums -->
| File | sha256 |
|---|---|
| `artifacts/supplyscope-analyst-workbook.xlsx` | `50680a8704806cbbe32dd58e7cf8d8d52d5dd09a890f86a52d2a942f6c98d5c2` |
| `artifacts/analysis-results.json` | `2be6764fe2e204a1dbc80c8992524b17ccf1cc726e2451eb008a46707c0d1b63` |
| `artifacts/build_workbook.py` | `557b993297c4439e7a8ea81893e2e5c376a0d5408e4550f643dc122cce5bf244` |
| `artifacts/render_sql_analysis.py` | `d5a9b8baabdf445496dd328a82e1e3f22eb031bf8e3803b2a9ee1f75717f0c94` |
| `artifacts/checksums.py` | `d8c38ae48a2503704c0e03760d3cd0ab8ede128e45a3fecef1dd56fb162c9562` |
| `requirements-artifacts.txt` | `06d28d69e958deafb09f0a44fcae9b548f15e4debc14ebc39aad5f0934856fbf` |
| `data/sql/analysis/00_ledger_views.sql` | `95f87982d0bea333334956791b450b55f0163e040c983b5963ac0005d804a733` |
| `data/sql/analysis/01_stock_position_month_end_by_location.sql` | `041160d47f6f2554b2f97bd7c1c1dba574e95862b9714cb72b435c3dac3e681f` |
| `data/sql/analysis/02_draft_orders_arithmetic.sql` | `50b0391c95b1d5a55db6f2fa2b569fda79e1081957e9b5a129d1c56b14bb1f6e` |
| `data/sql/analysis/03_fill_rate_stockout_by_location_abc.sql` | `b181ab59f52f68b9001bfb2a5e214ed82e5a93c202f1085a125945861bb13c6c` |
| `data/sql/analysis/04_supplier_on_time_by_month.sql` | `4a19ca0e9e60026a4a4255036f1d4dde1419aa8879f74e54488084879c5c76d9` |
| `data/sql/analysis/05_censored_vs_latent_class_a.sql` | `c2c26cbfede647e8f49e69d22afdb386861bc879ced5cb23a4ed213cc6eaa0b6` |
| `data/sql/analysis/06_working_capital_by_location.sql` | `cca512b1408001fbc631208e626ab8c8d8511c1ced8d981e0f0d8a661440cafa` |
| `data/sql/analysis/07_forecast_wape_by_sku.sql` | `affefc41c4eeb44a2f28b3201d4c45cd067cf824a25b7ce59d150a80bcc5f411` |
| `data/sql/analysis/08_rejections_and_defects_by_reason.sql` | `8db36648b8b5627fd008b52d91ac00a3bcbd7802dfa95433ff318365ec7d0ad5` |
| `data/sql/analysis/09_golden_position_and_order.sql` | `5e73cf99bbd74cced7f7e71cdeec84345ace3cc342fb5e8ae93944423dcd60bf` |
| `data/sql/analysis/bi_fact_movement_day.sql` | `90bd2288585b4b8fe90ec2ef3c81f8b124ae3c0e0b9e4a03150599ea1b6d84cd` |
| `data/sql/analysis/bi_fact_draft_order.sql` | `2d1b70182d025bd68bbce3e9338d6b4caac0723c7e454a20c3354fa5e32cf26d` |
| `data/sql/analysis/prepare_snapshot.py` | `fd3b713b7c76caa9211119ebcc7debfedccde81dc5c3b23d01e15e6c9e945df7` |
| `data/sql/analysis/run_all.py` | `289243f68bb15cca719179dbc2d3ca7bf10a60bcfb213ff72162009b50bd2ea4` |
| `data/sql/analysis/options.py` | `a6d3a5f579e6c062a324532b4fc65feb3f1e6d77d68ed6b7a486aaa930e0a71f` |
| `tests/test_artifacts.py` | `5888168b2be1bb002cb9a514dca792bf44cdba7e88c5e27ab2b9f1bde359c2b3` |
| `docs/data-dictionary.md` | `0583a6b19278f5d77202625547caa288986fd2208534f12c6aa0fa5e4976ff99` |
| `docs/erd.md` | `617342ac7d465abdbab6d5aa5d6c1b2fed95071d1ecb36c2950efb5adb32b93b` |
| `docs/sql-analysis.md` | `2db6f85e7ebca3c4b93a8f2cba9c5c855aca206ec62d69c5868fd1756796f271` |
| `docs/workbook.md` | `e2fdca8f7e90e87b2107c7db9b669ff910565dc8784afdb8c4d4a11a8336c4ba` |
| `docs/bi-package.md` | `540922cdfb2670a0852e405456d9e2fc9f4588e5ba38efc1a8df971df5e47629` |
| `docs/executive-memo.md` | `19823516d9e96211a8d0abafb822fa8c1389dc37b4d2f9f0493bbf99a8102994` |
| `docs/technical-case-study.md` | `521d68ac1bcf72e4d5e63541693093b8f31b87baa6e62d9752b5dfa968f00015` |
| `docs/resume-bullets.md` | `9c9667b2077f8619cdd71852b5662e3ce867f6158a7763b2f2d8af816dcaff7f` |
<!-- END:checksums -->

`docs/release-package.md` is not listed: it carries these checksums, so it cannot contain its own. `artifacts/CHECKSUMS.txt` cannot list itself. Regenerate both with `../../.venv/bin/python artifacts/checksums.py --table` after any change to a listed file.

## Known limits of the package
* The workbook covers the golden case only and its snapshot summary is a paste; Excel was not run.
* The Power BI package is a design (no `.pbix`, no Desktop run); its expected values were computed in Python and SQL.
* The analysis is one seed; the decision options are simulated directions, not measured effects.
* `docs/data-dictionary.md` row counts are from the scratch snapshot database, not from a shared database.
