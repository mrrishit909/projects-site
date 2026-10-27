# Release package (P07-ART-10)

Dataset `tl-20261026-20261026` (generator `dataset_hash` `a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff`), contract v1, code revision (published source) **`0b5d686869f289681a795b022e185a1eb614c1d0`** (`0b5d686`). **Synthetic data only.** This package **committed and pushed nothing**; every id below marked "ledger" is copied from the committed ledgers (`docs/program/release-manifest.json`, `verification-ledger.json`, `delegation-ledger.jsonl`, `task-queue.json`, `program-status.json`) and was **not fetched** by this pass.
The decision it supports: **which data issues should be fixed first, and who is accountable?** (`executive-memo.md`).

**How to read it without installing anything:** where everything lives, the release and rollback commits copied from the ledgers, the rollback procedure (not executed), the portfolio metadata and the case-study claims checked against the reconciliation, what this pass ran, and the checksums.

## Where it lives
| What | Where |
|---|---|
| Individual site (static, Mode B) | https://mrrishit909.github.io/projects-site/labs/trustledger/ (`labs/trustledger/` on `unified-portfolio`, 49 files, published tree sha256 `7221af120c136f7c1c39d7b953a6fe5699594173798938e94889a896ec7a796d`); not fetched by this pass |
| Source | `apps/trustledger/` on branch `business-data-lab` of https://github.com/mrrishit909/projects-site (the `repo` field of the portfolio record: https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/trustledger) |
| Contracts and decisions | `docs/contracts.md` D-01..D-10, `README.md`, `docs/api-contract.md`, `docs/web-brief.md`, `docs/data-generator.md` |
| Golden fixture and hashes | `tests/fixtures/golden/` (`HASHES.json`, `CALCULATION.md`), `tests/reference_check.py` |
| Published data and manifests | `web/public/data/` (`manifest.json`, `injection-manifest.json`) |
| Analysis | `data/sql/analysis/` (ten numbered investigations, the golden known answer, BI queries, `run_all.py`), `artifacts/analysis-results.json` |
| Workbook | `artifacts/trustledger-analyst-workbook.xlsx` (`workbook.md`) |
| BI package | `artifacts/bi/*.csv` (`bi-package.md`) |
| Documents | `docs/{business-case,requirements,data-dictionary,erd,sql-analysis,workbook,bi-package,executive-memo,uat-evidence,technical-case-study,release-package,resume-bullets}.md` |
| Checksums | `artifacts/CHECKSUMS.txt` (`sha256sum -c artifacts/CHECKSUMS.txt` from `apps/trustledger`), and the table below |
| Evidence area of the site | the site's `/evidence/` route (golden check, provenance, disclosures) is source code of the published site and was **not changed** by this package; linking these documents from it (P07-ART-xx-R14) is left to the coordinator: the documents are safe to link (synthetic, no credentials) |

## Release and rollback commits (branch `unified-portfolio`)
| Release | Portfolio commit | Source (`business-data-lab`) | Hosted verification (ledger) | Rollback target |
|---|---|---|---|---|
| First publication | `77665db` "Publish TrustLedger (labs/trustledger) and add its case study to the portfolio" | `78a4390` (the web hand-back) | CI `40439001518` green in both modes; live-check run `40439868137` (all seven sites success; trustledger live code `78a4390`) | the commit before `77665db` (not recorded in the manifest) |
| Case-study correction | `031705d` "TrustLedger case study: correct the claims the review disproved (commands named, DR-03 wording, oldest-claims framing, precision scope); state the open defects" | unchanged `78a4390` | covered by the portfolio build | `77665db` |
| **Republish after review R7 (current)** | **`e205202`** "Republish TrustLedger after the review fixes; case study states what was found and fixed" (2026-10-27T04:11:34Z) | **`0b5d686869f289681a795b022e185a1eb614c1d0`** (code fixes `1e0283f`, ledger commit on top) | CI **`40448066870`** green in both modes on `0b5d686`; **live check: pending at dispatch** of this package (the ledger then held `live_verification: null`); recorded afterwards as run **`40448466520`**, success for all seven sites, live code sha `0b5d686869f289681a795b022e185a1eb614c1d0`, verified 2026-10-27T04:22:33Z | **`031705d`** (release manifest `rollback_commit_unified_portfolio`) |
`program-status.json` first recorded `verified: pending live check on e205202` and now `verified: {live_check_run 40448466520, at 2026-10-27T04:22:33Z, release e205202}`; it records `published: {release e205202, rollback 031705d, source 0b5d686, at 2026-10-27T04:12:33Z}`, `integrated: true`. The published manifest `labs/trustledger/data/manifest.json` carries `code_sha` `0b5d686869f289681a795b022e185a1eb614c1d0` and the dataset hash above. A source commit is not labelled a verified live release by itself: `e205202` is **built, published and integrated, and live-verified by the recorded run `40448466520`** (copied from the ledger, not fetched by this package; the check matched the live code sha to `0b5d686`).

## Rollback procedure (not executed; nothing was committed or pushed by this package)
1. On `unified-portfolio`, find the release commit: `git log --oneline -- labs/trustledger trustledger` shows `e205202` (and `031705d`, `77665db` before it).
2. Revert the republish rather than rewrite history: `git revert e205202` (this restores `labs/trustledger/` and `trustledger/project.json` to the state at `031705d`, the release manifest's rollback target). If only the case-study text must go back, `git revert` leaves the site files and the record in step.
3. Push to the **private** repository only (`git push private unified-portfolio`); do not push to `origin` or merge into `main` (the owner decides when the public site is updated).
4. Re-run the live check for the reverted commit before calling it verified; record the new run in the ledger.
Rollback of this package's documents is deletion of the new files (they change no application code, no migration and no fixture).

## Main-portfolio metadata (from `/trustledger/project.json` on `unified-portfolio`)
| Field | Value |
|---|---|
| title | Which Data Issues Should Be Fixed First, and Who Is Accountable? |
| kind | Dashboard · Data governance · FastAPI · React |
| order | 306 |
| date | 2026-10 |
| repo | https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/trustledger |
| demo | https://mrrishit909.github.io/projects-site/labs/trustledger/ (label "Open TrustLedger") |
| cover | `cover.jpg` (with `loop.mp4`, `loop.webm` and `shots/` in the same directory) |
| tech | Python 3.11; PostgreSQL 16; FastAPI 0.162; SQL reference recomputation; TypeScript + React 18 + Vite; Playwright 1.55; GitHub Actions; "405 Python tests, 2,539 TypeScript golden and snapshot checks plus 58 review checks, 80 browser tests" |
The record was read, not changed. It is consistent with the stored results except for the two wording points below.

### Claims of the public case study checked against this package's reconciliation
| Claim (`project.json`) | This package | Result |
|---|---|---|
| ds-customers 0.990175 under w2 (0.990329 under w1), override set; 2 failing rows, 1 critical issue | investigation 01 | equal |
| three inactive owners leave five of forty datasets uncovered, coverage 0.875000 | investigation 02 | equal |
| 13 of 29 differ, seven by 0.005 or more, largest -0.167477; no rule version within fourteen days, two rules disabled in that window | investigation 03 | equal |
| 574 issues: 315 resolved, 99 claimed, 160 open; the 64 oldest unresolved issues are all claims | investigation 04 | equal |
| Data Platform 34.4202 h against 86.1833 h | investigation 04 | equal |
| 80 declared edges, 58 observed (0.725000), 12 undeclared observed, 10 inferred never counted | investigation 05 | equal |
| 23 of 30 definitions pass (0.766667); fifteen carry more than one version | investigation 06 | equal |
| 220 of 400 reviewed, 174 approved, 46 rejected, 15 reversed; 172 of 174 right: precision 0.988506 | investigation 07 | equal |
| "205 of the 220 reviews, approvals and rejections together, agree with the truth" | investigation 07 | **true but ambiguous**: 205 is the decision-agreement count (172 + 33 = 0.931818); the contract's `reviewed_correct_share` (manifest, reference SQL, domain) is 185 of 220 = 0.840909. The sentence should say which it quotes Corrected on the portfolio at `eecd593`: the page now quotes 185 of 220 = 0.840909 as the reviewed-correct share and names the 205 of 220 decision-agreement count beside it. |
| Built section: "relationship integrity 0.947368 with two null foreign keys counted apart" for the known-answer fixture | investigation 09 | **stale**: after the empty-string key was pinned as missing (D-10 R7-11) the golden relationship figure is 35 of 37 = 0.945946 with three null or empty keys counted apart; the same record's review paragraph already says it moved from 36 of 38 to 35 of 37. The known-answer, uniqueness (0.010204 and 0.020000), timeliness (3 of 4), weighted scores (0.963932 and 0.958116), resolution (38.4444 h), ownership, definitions, lineage and precision (2 of 3) figures are equal Corrected on the portfolio at `eecd593`: the page now says 35 of 37 = 0.945946 with three null or empty keys. |
| 40 datasets, 420 fields, 18 owners, 60 rules, 4,609 runs, 574 issues, 160 edges, 45 metric versions, 2,000 records, 400 candidates | `manifest.json` `row_counts`, `run_all.py` row E | equal |
Both wording points are reported to the coordinator; the file lives on `unified-portfolio` and was not touched.

## What this artifact pass ran (2026-10-27, scratch databases `artifacts07_*`; never the shared `trustledger` database)
Commands, from `apps/trustledger`, with `../../.venv/bin/python`; `<creds>` stands for the local development login of the CI workflow's throwaway `postgres:16` service (127.0.0.1:5432), which is not written in any document. Scratch databases created for this pass: `artifacts07_run_snapshot` and `artifacts07_run_golden` (created, loaded and dropped by `run_all.py` itself), and `artifacts07_snapshot`, `artifacts07_golden`, `artifacts07_suite`, `artifacts07_explore`, `artifacts07_goldx` (created with `createdb`, all dropped when the pass ended). The shared `trustledger` database was neither read nor written.
| Command | Result (last line) |
|---|---|
| `python -I tests/reference_check.py` | `ALL OK (805 checks)`, exit 0 |
| `DATABASE_URL=<scratch> python -m pytest -q -ra --ignore=tests/test_artifacts.py` (baseline, before this package's test existed) | `405 passed, 2 warnings in 119.63s (0:01:59)` |
| `python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi` | `RESULT: OK (175 reconciliation rows, 175 equal; 51 result sets, 233 rows)`, exit 0; `wrote 13 CSV files to artifacts/bi`; stored last scheduled runs against the row-level measurement: `47 row-based rules compared, differing: ['r-contacts-fk-customer_key']` |
| mutation check: a changed threshold in `03_weight_shift_dr03.sql` (restored afterwards) | `RESULT: FAILED (168 reconciliation rows, 164 equal)` (the row count at that time) in the C, D and E families; the restored run is `RESULT: OK` |
| `python artifacts/render_sql_analysis.py` | `rendered docs/sql-analysis.md`, `rendered docs/bi-package.md` |
| `python artifacts/build_workbook.py --recalc` | `recalculated with LibreOffice headless; cached values written`; `Checks!B2` TRUE (also with the switch at `w1`, by the tests) |
| `python artifacts/checksums.py --table` and `sha256sum -c artifacts/CHECKSUMS.txt` | `wrote artifacts/CHECKSUMS.txt (56 files)`; every file `OK` |
| `DATABASE_URL=<scratch> ARTIFACTS_DATABASE_URL=<scratch> ARTIFACTS_GOLDEN_DATABASE_URL=<scratch> python -m pytest -q -ra tests/test_artifacts.py` | `38 passed in 19.37s` |
| the same with only `DATABASE_URL` (and with none) | `37 passed, 1 skipped (re-run after the last test was added)`; `SKIPPED [1] tests/test_artifacts.py:256: ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts07_*; the test prepares them with data/sql/analysis/prepare_snapshot.py) are not set` |
| `DATABASE_URL=<scratch> ARTIFACTS_DATABASE_URL=<scratch> ARTIFACTS_GOLDEN_DATABASE_URL=<scratch> python -m pytest -q -ra` (the whole suite) | `443 passed, 3 warnings in 154.17s (0:02:34)` (the 405 existing tests plus the 38 of this package; no existing test changed; an earlier whole-suite run before the 38th test was added gave `442 passed in 150.36s`) |
| `git diff --stat 0b5d686 -- domain api data/migrations data/seed.py data/migrate.py data/generate.py data/sql/reference_metrics.sql web/public web/src tests ':(exclude)tests/test_artifacts.py' docs/contracts.md README.md` | empty (`test_provenance_the_analysed_code_and_data_equal_revision_0b5d686`) |
No existing domain, API, migration, loader, reference-SQL, web, fixture, generator, test or contract file was modified; `git status` shows only new files (`artifacts/`, `data/sql/analysis/`, `docs/*.md` of this package, `requirements-artifacts.txt`, `tests/test_artifacts.py`).

## Artifacts and checksums (sha256; also `artifacts/CHECKSUMS.txt`, verifiable with `sha256sum -c artifacts/CHECKSUMS.txt` from `apps/trustledger`)
This document carries the checksums of every other artifact, so it cannot contain its own; `artifacts/CHECKSUMS.txt` cannot list itself.
<!-- BEGIN:checksums -->
| File | sha256 |
|---|---|
| `artifacts/analysis-results.json` | `91c926a36a596d0d799cd8f65152baa5d9652e8407e769f81f10499a69ed5bfa` |
| `artifacts/bi/dim_dataset.csv` | `aaa110d16af951d53ae84664f77c2996eab486063feb25702547c8557dcaf09e` |
| `artifacts/bi/dim_date.csv` | `847708c64e077f426288ba4867931890de9ff2993f4e921f3b1f284b640784a8` |
| `artifacts/bi/dim_metric.csv` | `8e126c9812be5d6c98e821213333b3a3299f71eb50196d91fa4e19239bbd61e5` |
| `artifacts/bi/dim_owner.csv` | `2f221437d1f218ffd1e1be540c95bf772c77fa78ab950a29ec87174baceb3c38` |
| `artifacts/bi/dim_rule.csv` | `f79bddb35ef4f8ec4c6db321851210cd46a94f2581a271ce4e49f4d728f6aeea` |
| `artifacts/bi/dim_weight_version.csv` | `5b5e2c5576766a83167e7e072e4c1f6c9ac3fc49552686789a261a7c62855f78` |
| `artifacts/bi/fact_candidate.csv` | `39241e3d47bfdf6cf35e83efa945cfe70a519cad117e5fd7c219a8ebf90559d4` |
| `artifacts/bi/fact_dataset_score.csv` | `732f538ffc71455dec9f0b3eea625e49a9487cfaf7fb413b7e454d052a4ad304` |
| `artifacts/bi/fact_issue.csv` | `ee5736e6e4ce8a29bdd267973c00021c22db7c56ff4796e6206b912af4ec2599` |
| `artifacts/bi/fact_lineage_edge.csv` | `045a1208ba76e2090e4ae759353e3efd40bf7777e985166bd67bc67af5591708` |
| `artifacts/bi/fact_rule_measure.csv` | `3ed572ff694040d29ee4e30735dd5da129236537b192ef4adbe5768a196e8bd5` |
| `artifacts/bi/fact_timeliness.csv` | `a7c412b6dbc0128bc1966a567b448b10c0e4dea4a76ec53c26d7a2522ffa44b1` |
| `artifacts/bi/measures_recomputed.csv` | `ead7fd8c767184c79173fff1ba082a5e551338c168d7bfb083f9e8713d29e12b` |
| `artifacts/build_workbook.py` | `8425bbf2023ef3a9f2a955e0d6eb78ff69b9678920f4e0c8dd4f384d37729008` |
| `artifacts/checksums.py` | `101824e393eb0603f73aac6079c43381999e15b4a8bd4ae278e07d1e8209cccb` |
| `artifacts/render_sql_analysis.py` | `cab528a207eb9543e38d78c17308f97fef3eb30ed4edcb1a64eac826057f8f49` |
| `artifacts/trustledger-analyst-workbook.xlsx` | `d3c19b46a51fa2a7b227e5b6d84ef35d530b5289f1114847e9f07f2d9ff7c478` |
| `data/sql/analysis/00_measure_rules.sql` | `ea70aa8a46eda9b1dba71887521fd3a54dba022472be88996cbecef837462d86` |
| `data/sql/analysis/01_ds_customers_override_both_weights.sql` | `7358fc163bd44eba88d5d28d045038a096dc61de653950f1bb0a1d14a630a89a` |
| `data/sql/analysis/02_ownership_coverage.sql` | `a33a4c7628b57b730a0eff4087e7cccb2d9a70cdc5197b9de6ab1160c52658de` |
| `data/sql/analysis/03_weight_shift_dr03.sql` | `708d0dfcf9a6dd34cc7f91f135ee8420bcb1f072a4da5231d09ca33e6b348001` |
| `data/sql/analysis/04_issue_classes_and_resolution.sql` | `5ae11c31d7ec18c420820227bd8966df002d69e7d3109fc3f10bd70dbb39abbf` |
| `data/sql/analysis/05_lineage_coverage_evidence.sql` | `71505bf2a908ccfa74d75c05c40db07611dd2feaba93f2d155e0a2ae5aa00d23` |
| `data/sql/analysis/06_definition_coverage.sql` | `b57789e5ce6b07842a086ae808d9feebff571e3d6d3d248cf4d7d519b08b89f3` |
| `data/sql/analysis/07_match_precision.sql` | `7cba618002efc8e2940a464af195c19efe77ee1e3a701f155d40188904ca0c6b` |
| `data/sql/analysis/08_timeliness_states.sql` | `b3ebd7e931a6f0bcefce56aa3a46780b13f35d4d5683466a34adbde4562421c3` |
| `data/sql/analysis/09_golden_known_answer.sql` | `528a88b09c3734cfb3649a35eb31c388ff66c02055f5e52bc2b6394b45b29699` |
| `data/sql/analysis/10_fix_first_queue.sql` | `86731e6e72b44cce85d41e99c863361a0700a79dff3b125dd1516d86c31035a3` |
| `data/sql/analysis/bi_dimensions.sql` | `43945b4074063df3e2a9af67f16575e34db6e265ac2055263a3c4eeb45bcb1ef` |
| `data/sql/analysis/bi_fact_candidate.sql` | `99c6e45dc3225b47c2ad416bc7abe8f9254453fa0b53724387bf0de951120023` |
| `data/sql/analysis/bi_fact_dataset_score.sql` | `7e9ac65a61a56ac90bacb9e7e43e5accb2d2e11524c3730d25958cd710be4041` |
| `data/sql/analysis/bi_fact_issue.sql` | `d3651747c8d55df77c7d08c6c3446c628600fd26d7f57180cbbb7cbea80f9375` |
| `data/sql/analysis/bi_fact_lineage_edge.sql` | `2b415bc9867de40c053cfa8de1594b68db57b0aecfaa7a2019734005504eb3e5` |
| `data/sql/analysis/bi_fact_rule_measure.sql` | `84f28dbb55df254170fb67f78e4c6c7be995a519e6ece44661c25cafd143fe70` |
| `data/sql/analysis/bi_fact_timeliness.sql` | `41d58cdbbe63e24c7c72bd3f6eab0243e678a25c0a76878cd9bbeaedb14b1475` |
| `data/sql/analysis/prepare_snapshot.py` | `334f95a46afbcc0ba73dc397d2669d7a99c71e4b8374e91f11a1050824988ccb` |
| `data/sql/analysis/python_side.py` | `d55ca9ff3d0217620971153fb311bf751823da5fd419576cbe717b8ae7100745` |
| `data/sql/analysis/run_all.py` | `3b287344e46d2cab59c491038c9522a629b71b75233a7f6f011b7c92ca8ca3d4` |
| `docs/api-contract.md` | `33b91a39f2be2c56aa58df2a4d16be77d915c6d7fe2134450cb797bf8c8bc069` |
| `docs/bi-package.md` | `496384b18d04d642c876c8a8b46c44b0af61dbacd1382df15e514947591ca12e` |
| `docs/business-case.md` | `e86a987a33d695eac53fab90fb5d2fc493e54ba827ace0c907bfe50d0ac4c061` |
| `docs/contracts.md` | `ac48af0677ad1900f335a7857af4c280c72ae1d645a96ad2f8021f0da5f065a6` |
| `docs/data-dictionary.md` | `fbea4ff500ac10622e33126080428178419e18bfcd553d9ecef632015c1e6da4` |
| `docs/data-generator.md` | `63ab3910286afb7ff813ee9092e0acdfb0845e65bb5ad6407bcc95052b55b528` |
| `docs/erd.md` | `5b933876f60d2c81d921c722fccd83b36cdcf57d9175101bf4113f458aa3af00` |
| `docs/executive-memo.md` | `e7a19c52f031a0e3affdeb4d98731bfd17d65b3c18025adb3d169e3c164bcdc6` |
| `docs/requirements.md` | `573fd32c198e7581d4441d8e95fee5063164b23c6d07e29746cbcb2416183c3c` |
| `docs/resume-bullets.md` | `7f469df2df0e013df4b5d3dfbd428439066a08ba6fc45da70ff195d0d9888097` |
| `docs/sql-analysis.md` | `9744a0e884d26c7a99a7575ad7f651b89c2b4e8e4effafa54ee7e88e0ab5b610` |
| `docs/technical-case-study.md` | `e5a3e74b6ba4a092124a9595e02ed21b5cd08ef1fc7235a15a1323339890a077` |
| `docs/uat-evidence.md` | `231e3672de4ef8ef78b326e54f467d46173d86d4a48f5bbb5bed95e46c523642` |
| `docs/web-brief.md` | `c1a51b02000959c469fb2f1d9cd71edf1813825c086276ab8ccbb967b0e0639b` |
| `docs/workbook.md` | `ae5e4623b28f449751295210e50261c5af35111f7a21243da1751801e5a48bd4` |
| `requirements-artifacts.txt` | `06d28d69e958deafb09f0a44fcae9b548f15e4debc14ebc39aad5f0934856fbf` |
| `tests/test_artifacts.py` | `4d744cf0504b0a583ecb67d3179f1da9c64f14f8a6c08ca67d03df1251c7789e` |
<!-- END:checksums -->

## Verification status of this package (stated plainly)
* **Verified locally in this pass:** the reconciliation (175 rows, all equal), the workbook check cell (TRUE after LibreOffice recalculation, under both switch positions), the BI measures recomputed from the CSV files, the documents quoted from the stored results, the checksums, the independent oracle and the existing suite (see above).
* **Not verified:** Excel, Power BI Desktop and any DAX engine (no `.pbix`); any hosted run of `tests/test_artifacts.py`; the live site itself (the live check of `e205202` is the ledger's run `40448466520`, copied not fetched); `npm run check` and `npm run e2e` by this pass (their results are the recorded runs in `uat-evidence.md`).
* **Binary artifacts** (the workbook) were generated in the session's cloud container, not on a GitHub-hosted runner, and are not attached to a GitHub release (P07-ART-xx-R06): a durable release asset needs a hosted workflow run, which this package did not start.
* **CI gate:** the next push of `apps/trustledger/**` runs `pytest -q -ra` followed by the junit no-skip gate (D-10 R7-15); `tests/test_artifacts.py` skips its LibreOffice and scratch-database tests without them, which the gate would count. The remedy is in `requirements.md` section 5.
