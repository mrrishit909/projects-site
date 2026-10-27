# ChangeWorks: release package (P09-ART-10)

**Synthetic data only.** Dataset `cw-20261026-20261026` (generator `dataset_hash` `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`), contract v1, analysed source revision `29948f9` = `29948f92f0c3839f070e4b6499b99f3810d1361b` on `business-data-lab`. The decision it supports: **which transformation initiative should be funded, and how will success be established?** Nothing in it is a measured benefit of a real organisation; nothing is funded.

**How to read it without installing anything:** the individual site and its source, the release and rollback commits as the ledgers record them, the main-portfolio metadata and where it disagrees with this package, what this artifact pass ran (with the exact commands and last lines), and the checksums of every artifact. Statuses are those the ledgers show; anything not recorded there is "pending at dispatch" or "pending".

## Individual site and source links
| Field | Value | Source of the value |
|---|---|---|
| Site | https://mrrishit909.github.io/projects-site/labs/changeworks/ (`labs/changeworks/` on `unified-portfolio`) | `docs/program/release-manifest.json` |
| Source | https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/changeworks | the case study `repo` field |
| Source commit (business-data-lab) | `29948f92f0c3839f070e4b6499b99f3810d1361b` | release manifest `source_commit_business_data_lab` |
| Release commit (unified-portfolio) | `8b9bcd3` ("labs/changeworks: republish after the review fixes; case study states what was fixed") | release manifest; `git show 8b9bcd3` |
| Rollback commit (unified-portfolio) | `d58209f` ("Republish Pipeline Observatory after the review fixes; case study states what was found and fixed") | release manifest `rollback_commit_unified_portfolio` |
| Published tree sha256 | `74c310decb2c226c20a52ffda92c79f927cc094287f6b37ecde135e2ac5a8439` (36 files) | release manifest |
| Previous release | `7c6e357` (source `d9e76fa9c3ee49043044be9d2d191ba902baeb65`, tree `527313e7d6e357ecdf7fa770a87a223c555118cc58f9498969daaeb7b307e2b3`), superseded 2026-10-27T08:38:29Z | release manifest `previous_releases` |
| CI on the source commit | run 40474351325, both modes green on `29948f9` | release manifest `publication_status` |
| Live verification | run 40474949237, verified 2026-10-27T08:41:13Z, live code_sha `29948f92f0c3839f070e4b6499b99f3810d1361b` | release manifest `live_verification`; verification ledger |
| This artifact package | built in the session container on uncommitted files; **committed and pushed nothing**; its hosted CI run and its release integration: pending | this pass |

At dispatch the coordinator's brief said the live check was "pending at dispatch"; the ledger now in the worktree (`43459db`) records it (run 40474949237), and this document cites what the ledger shows.

## Rollback procedure
1. The release is one commit on `unified-portfolio`: `git revert 8b9bcd3` restores the previous published tree (the rollback target `d58209f` is the commit before it), then republish through the portfolio build and run the live check for the ChangeWorks routes.
2. This artifact package changes no published file: removing it is deleting the untracked `apps/changeworks/artifacts/`, `apps/changeworks/data/sql/analysis/`, the new documents of `apps/changeworks/docs/` and `apps/changeworks/tests/test_artifacts.py` and `requirements-artifacts.txt`; nothing of the domain, API, migrations, loaders, reference SQL, web, fixtures, generator, the other tests or `docs/contracts.md` was modified (`test_provenance_the_analysed_code_and_data_equal_revision_29948f9`).
3. The scratch databases (`artifacts09_*`) are dropped after use; the shared `changeworks` database was only read by the existing suite.

## Main-portfolio metadata (`changeworks/project.json`, identical on `unified-portfolio` and in the main checkout, sha256 `4c69ec12...`)
The figures of the case study's `results` agree with this package: 25,914,200.00 of costs, 15,288,067.20 cash, 6,074,000.13 revenue, 5,516,433.35 avoided cost, 1,774,010.55 converted capacity, 207,146.32 counted twice, 4,025,383.47 beside the flow, 145,045.62 hours, 1,438,382.25 and 1,243,149.05, 195,233.20, six initiatives never reaching either payback, 32,677,894.70 and 32,470,748.38, 5,974.80 hours, 2,920.48 hours and -761,535.73, 0.531465 and 0.620043, 745,800.06 / 598,900.05 / 534,207.54, periods 12 to 16, 0.888443 (0.963778 over the eleven) and 0.532881, 0.848744, and the golden 41.32, 1.6667, 1.9167. Where it disagrees, reported to the coordinator (this package edits no case study):
1. **`tech` says "399 Python tests"** while `built` and the README say 454 and the suite at `29948f9` has 454 (verification ledger 2026-10-27T08:33:31Z): the `tech` entry is **stale**.
2. **"One initiative never pays back in any scenario"** is true but ambiguous: six initiatives (`init-006`, `init-009`, `init-015`, `init-019`, `init-021`, `init-022`) never pay back in any scenario that contains them (investigation 04); the sentence describes `init-015` (DR-03) only.
3. **"six initiatives never reach simple payback ... largely because the window ends before their benefits do"** is contradicted by the analysis: four of the six (`init-006`, `init-009`, `init-019`, `init-021`) have **no benefit that enters the cash flow at all** (avoided cost without realisation evidence, capacity without conversion), and two (`init-015`, `init-022`) have benefits that enter and stay below cost; all six have their benefit rows inside the 36-period horizon (investigation 11, `waiting`).
4. **`built` describes payback as "the first period whose cumulative flow reaches zero"**; since R9-12 it is the last crossing from below zero (null with `NO_INVESTMENT` for a series that is never negative). On this world the two give the same periods (investigation 04), so no figure moves, but the wording is **stale**.
5. "A shared specialist is at capacity in five periods (12 to 16)" agrees; it is not the only full resource: the change manager pool `res-02` is at capacity in 18 periods (0..17).

## What this artifact pass ran (session container, local PostgreSQL 16 on 127.0.0.1, LibreOffice; scratch databases `artifacts09_snapshot`, `artifacts09_golden`)
```
cd apps/changeworks
export PGPASSWORD=<password>; createdb -h 127.0.0.1 -U <user> artifacts09_snapshot; createdb -h 127.0.0.1 -U <user> artifacts09_golden
export ARTIFACTS_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/artifacts09_snapshot ARTIFACTS_GOLDEN_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/artifacts09_golden
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi
    RESULT: OK (763 reconciliation rows, 763 equal; 56 result sets, 567 rows; 48476 + 167 leaves equal to the reference SQL and the domain)
../../.venv/bin/python artifacts/render_sql_analysis.py && ../../.venv/bin/python artifacts/build_workbook.py --recalc && ../../.venv/bin/python artifacts/checksums.py --table
    recalculated with LibreOffice headless; cached values written / wrote artifacts/CHECKSUMS.txt (63 files)
DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/changeworks ../../.venv/bin/python -m pytest -q -ra tests/test_artifacts.py
    41 passed in 49.58s (no skip; without the two scratch URLs the database re-run test is SKIPPED with its printed reason, checked separately: 2 passed, 1 skipped)
DATABASE_URL=... ARTIFACTS_DATABASE_URL=... ARTIFACTS_GOLDEN_DATABASE_URL=... ../../.venv/bin/python -m pytest -q -ra
    495 passed, 7 warnings in 273.37s (0:04:33)   (454 before this package + 41 artifact tests; 0 skipped)
sha256sum -c artifacts/CHECKSUMS.txt
    63 files: OK
../../.venv/bin/python -I tests/reference_check.py
    ALL OK (3156 checks)
```
The scratch databases were dropped afterwards. No test was skipped in these runs: the junit no-skip gate of the CI workflow would fail a skip, and the artifact tests skip (with a printed reason) only without the scratch URLs, without LibreOffice, without git history or without the case study.

Excel and Power BI were not run. The workbook and the BI files are not attached to a GitHub release (pending: the package is not committed). This pass did not fetch the live site and did not run `npm run e2e`.

## Artifacts and checksums
`artifacts/CHECKSUMS.txt` (`sha256sum -c` format) lists every file below; this document carries the same list (it cannot list itself, and `CHECKSUMS.txt` does not list itself).

<!-- BEGIN:checksums -->
| File | sha256 |
|---|---|
| `artifacts/analysis-results.json` | `675b3a87a839a0292b1cfca446463c426bc1a4149ed437366177cd766cd85c80` |
| `artifacts/bi/dim_benefit_class.csv` | `2f731839c5b3c9ed3ef1fb43760297891e1af5b7262f9649fbbd1c5ce58135ba` |
| `artifacts/bi/dim_initiative.csv` | `0067154b6e3fd3a2b8a36128ad0e1032b8157bf9fe1caae961e31ccb796df220` |
| `artifacts/bi/dim_period.csv` | `fd6326f68495a691a54f3981573c90d2289e67472f903aa969662ce0c21e50f9` |
| `artifacts/bi/dim_resource.csv` | `06dd31298857dc9b256540dd9eeb10be904ed2f3be2fd15449aa75f2e4f173f8` |
| `artifacts/bi/dim_scenario.csv` | `a7af8585921a948ae42496bed884a9cc9ff9e22a5dbb69bd003599a14be5801d` |
| `artifacts/bi/fact_adoption.csv` | `dcd4ad59009ab93caaeed358fe1a9023e8cd2130283df2535a2d917b8269ef67` |
| `artifacts/bi/fact_cash_flow.csv` | `4863e069a61a697f00c364324bfdb55ede4bb4d0bdf34679b032e27d7dab1345` |
| `artifacts/bi/fact_double_count.csv` | `b03049d600bb796c01f21c5d4896941dbcf332f2bf01c90db8a1233f7c810ba3` |
| `artifacts/bi/fact_forecast.csv` | `d3c7fd0f46d79d18c8b0e447bce01229d12bc1a572150543972c042cda3e478f` |
| `artifacts/bi/fact_realisation.csv` | `d58a511eb1c2c71b8ab7f14a6b8a8458668fd7a44d6312817f2e5758b2fa6842` |
| `artifacts/bi/fact_resource.csv` | `0b2571a44b817f23f6c055d2b283a2caf3cf5dc261d82915f9eae32e5cb5296f` |
| `artifacts/bi/fact_risk.csv` | `cddf7f0a08cd29fccbcdfaf33bcb4f46a567e4294ac6c10567096825aaf8b2a6` |
| `artifacts/bi/fact_scenario.csv` | `1ab865a000dc8f9b1b96200e9f178bfb3c9212d8e13ae26dc689deaa8503c8e3` |
| `artifacts/bi/fact_scenario_initiative.csv` | `6bb008f8e16c376dc4da64e96a6f62e8771f93350941e6a144fdf7e0fce4e72f` |
| `artifacts/bi/measures_recomputed.csv` | `b2c654f71d3b526a30752ccf77f8772f9dc9f4562cef3f9154be9432c264f223` |
| `artifacts/build_workbook.py` | `c494c591d049760e514639c9995c47187a840f82b260dec7edff622a5999bccc` |
| `artifacts/changeworks-analyst-workbook.xlsx` | `f4bcc6265838138d6923a899db0e6b4951e3ee060c46fc5213dab025543bf824` |
| `artifacts/checksums.py` | `42e969967bba81edffb48237515cd23121341a6dbb1c9f0084b41fbaa44caf65` |
| `artifacts/render_sql_analysis.py` | `e5c9a605eb98b29e71eb65b5e12d888eb46f6a72daddeb60673490405202ef7d` |
| `data/sql/analysis/00_portfolio_model.sql` | `4087c69d8649e36f1b417aca7a238615fbb2547ed37a43a2119b417585ceedc5` |
| `data/sql/analysis/01_portfolio_ledger.sql` | `474a7587f2542dcf87155b60739b4410ff642d4d1a7eef8fe1eb8566c7e590d6` |
| `data/sql/analysis/02_initiative_npv.sql` | `7d14a503af7a075975f4f7e911591473f9d953d856f34978b07e662d63ed9b78` |
| `data/sql/analysis/03_double_count.sql` | `4a8d335e48f7371b27c80c663da0f99ba65c91c054cf681bebf5fc51ccf6eecd` |
| `data/sql/analysis/04_payback.sql` | `e70099f2443e57f4b00d7ce3ead98423ae6f7d48a67ef10dfeb36dbc9a122b1b` |
| `data/sql/analysis/05_cost_expansion.sql` | `8427f0b90302f3918618d858718a79236382b507ce2f96ad92b71ae8070481a4` |
| `data/sql/analysis/06_variance_realisation.sql` | `a6788ebaf56f91f47d6ab4b3e050cd00737c2968002378cb4a6e2d5639db168a` |
| `data/sql/analysis/07_adoption_training.sql` | `f17ac0e5029a7497e0deca6fe64dfcf4e3a83e3ea019133be0230d3f12dcde96` |
| `data/sql/analysis/08_forecast_revisions.sql` | `e26aa8d04b9f77a0974f87d4418b087beb739930855532a3407427eb73219980` |
| `data/sql/analysis/09_roadmap_capacity.sql` | `db9067a6cff0a0338632fc96b17a32a695419c6c37b1c7e68dd5de805523d740` |
| `data/sql/analysis/10_golden_known_answer.sql` | `b79f89d46d625849326049e509bab692c4b4bccb8a13fc92e52fbb98f260be17` |
| `data/sql/analysis/11_proposal_screen.sql` | `0da5b50dbf1bd6f6265d818d15e33c146e267774c39d7628b335fbacb723677a` |
| `data/sql/analysis/bi_dimensions.sql` | `2c171781204490cef1022a2b9a0d1ea61c49888bb19e425ab7956aa37ed8e13e` |
| `data/sql/analysis/bi_fact_adoption.sql` | `77984f8322f6768ef771884f9c739585119d0339dedb989ca3621274d5c81853` |
| `data/sql/analysis/bi_fact_cash_flow.sql` | `3af9031c90eab5d3d57d7ee7d957dc314303b120434169a14590e27c8a9bd3f4` |
| `data/sql/analysis/bi_fact_double_count.sql` | `49a518517dfbc7fbd1f3108792e4a6bfe1f32e14612f0f36d1d52e9b88b96c8e` |
| `data/sql/analysis/bi_fact_forecast.sql` | `d728f6d8e073a46bf0d95441e9c3322979efd5ade75410cbb84d34129d293c4b` |
| `data/sql/analysis/bi_fact_realisation.sql` | `ac49bd9e9174a8b0c993b82fa5de0fca541065180b097bf3248087ba23d1bd2d` |
| `data/sql/analysis/bi_fact_resource.sql` | `22bdfbd700dbea06524d5b4e0d0c58d033ecdac5e0b1c51874b074af83d17434` |
| `data/sql/analysis/bi_fact_risk.sql` | `289be3324ddb719055f6a33c80c4414cbb51b867ee2ae66d359ba1899c9cb2b1` |
| `data/sql/analysis/bi_fact_scenario.sql` | `d77472d06c2f1310e8965eb2970782a7bf1d1585605bfe30be72a9b606e8c60b` |
| `data/sql/analysis/bi_fact_scenario_initiative.sql` | `bae52ba7dc903842db6c54ae502bb0b68690e795baab438c56cdbe8a559ff138` |
| `data/sql/analysis/leaves.sql` | `dfe94d460aae6e8d042e3509a992dd8875a81ac72c4b4e63aaea3ce5d689d5a8` |
| `data/sql/analysis/prepare_snapshot.py` | `071134009d93be8260afc5218044bea6e21e46255bbf6722f76dacebfcb263b2` |
| `data/sql/analysis/python_side.py` | `51e8fc1a7017180c974f5ac96162f724bd4fc241d2b7fbb0d4a842adfc730129` |
| `data/sql/analysis/run_all.py` | `42beb1e58c8d43b6eb3b7bd9e4282c32d071ab5ea32aed69f7675b2f6770601a` |
| `docs/api-contract.md` | `2455c873fe04623c67276a4060fcc7c33e8ef535cab490abce00b35d278386b7` |
| `docs/bi-package.md` | `f4e0f21511f5bf0e33d7f424c32e0d2b01c8bafdced0a987079dff43646de060` |
| `docs/business-case.md` | `f678857d2de8dd60f524c40118e38a3deea13fa69506bba65aa40cc9e4419e1c` |
| `docs/contracts.md` | `08195d73667ece4927471a697e74cc16c53f2cf1e8f755a90cbe6e759a41c4d7` |
| `docs/data-dictionary.md` | `a5830e1f89d8b1b449822aa7b18ab3964c3cd8b5c7253118ef03a99d2e119b5a` |
| `docs/data-generator.md` | `e647ea19d08a0e551ff1f481a083499958992802cb16110fa42998b204782fed` |
| `docs/erd.md` | `74a0ec616328dcb65b848f0e387ef7b68d45f3deeee20025e2d0bcdc2c2d1e7b` |
| `docs/executive-memo.md` | `4250c8ec17129a4df03d0052240ff2dc2efb2892e95b2b21ee68d267304c396a` |
| `docs/requirements.md` | `cbc31ddfcae8275c62f7156c8fa97ef7b9cd6407d4a2be2799d25db9089f432e` |
| `docs/resume-bullets.md` | `5e8562d70ba6f9f10cecd90274c8c1c3967431068ca268b201bb227cbd93693e` |
| `docs/sql-analysis.md` | `b648b3a0e7a370d074c70f5f2123be8f448ba776fb9d667483073ed39bfebbbb` |
| `docs/technical-case-study.md` | `162a0908e30ec25ead13bb82307a936392b45aebdcb940d40d92dd75e369e5dd` |
| `docs/uat-evidence.md` | `91fe68c37b2b26b4334b463e59b2350ca6888117493b3828adadd0686f75e6d5` |
| `docs/web-brief.md` | `ac048e227ed01ad2a6ae307141ba9e3849f2d6cc32d1516a18ed9c533ff7ad9d` |
| `docs/workbook.md` | `3bef0ce509fa0ca80b7fc1fb9575aafd09ad7251f7c32555d4649dc3114f97bd` |
| `requirements-artifacts.txt` | `06d28d69e958deafb09f0a44fcae9b548f15e4debc14ebc39aad5f0934856fbf` |
| `tests/test_artifacts.py` | `647d802cdeca0392647ab2cdcfeaf70f51d2f160f3d53f07c0a3009d339547dd` |
<!-- END:checksums -->
