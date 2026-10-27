# Release package (P10-ART-10)

Dataset `rl-20261026-20261026` (generator `dataset_hash` `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`), contract v1, code revision **`ce96e6544eb8a645236b081bf7dbd9f4a6c9e057`** (`ce96e65`, the app content of the lab branch after the review R10 fixes; the published `code_sha` is the lab HEAD at republish time, `c17fa321f28605ac56e24b59837441c29cc16d41`, whose `apps/retentionlab` equals `ce96e65`). **Synthetic data only.** This package **committed and pushed nothing**; every id below marked "ledger" is copied from the committed ledgers (`docs/program/release-manifest.json`, `verification-ledger.json`, `program-status.json`, `delegation-ledger.jsonl`) as they stood when this package was written; anything the ledgers did not yet show at dispatch is marked **pending at dispatch**.
The decision it supports: **which accounts deserve limited retention attention under uncertain intervention value?** (`executive-memo.md`: no retention improvement is claimed; the margin of the model over its baselines is met by construction; economics are hypothetical.)

Result kinds are kept apart: **simulated** (one draw of the synthetic world) and **hypothetical** (assumption-based economics).

**How to read it without installing anything:** where everything lives, the release and rollback commits copied from the ledgers, the rollback procedure and the rollback manifest (not executed), the portfolio metadata and the case-study claims checked against the reconciliation, what this pass ran, and the checksums.

## Where it lives
| What | Where |
|---|---|
| Individual site (static, Mode B) | https://mrrishit909.github.io/projects-site/labs/retentionlab/ (`labs/retentionlab/` on `unified-portfolio`, 39 files, published tree sha256 `4013064ff2bbc4bab4a482c7dc2b008a54292c2271635b9fee5f3935def12413`); not fetched by this pass |
| Source | `apps/retentionlab/` on branch `business-data-lab` of https://github.com/mrrishit909/projects-site (the `repo` field of the portfolio record: https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/retentionlab) |
| Contracts and decisions | `docs/contracts.md` D-01..D-09, `README.md`, `docs/api-contract.md`, `docs/web-brief.md`, `docs/data-generator.md` |
| Golden fixture and hashes | `tests/fixtures/golden/` (`HASHES.json`, `CALCULATION.md`), `tests/reference_check.py` |
| Published data and manifests | `web/public/data/` (`manifest.json`, `injection-manifest.json`, `test_cohort.json`, `cutoff_aggregates.json`, `calibration.json`, `split_summary.json`) |
| Analysis | `data/sql/analysis/` (ten numbered investigations, the golden known answer, BI queries, `run_all.py`, `python_side.py`), `data/sql/verification_layer.sql`, `artifacts/analysis-results.json` |
| Workbook | `artifacts/retentionlab-analyst-workbook.xlsx` (`workbook.md`) |
| BI package | `artifacts/bi/*.csv` (`bi-package.md`) |
| Documents | `docs/{business-case,requirements,data-dictionary,erd,sql-analysis,workbook,bi-package,executive-memo,uat-evidence,technical-case-study,release-package,resume-bullets}.md` |
| Checksums | `artifacts/CHECKSUMS.txt` (`sha256sum -c artifacts/CHECKSUMS.txt` from `apps/retentionlab`), and the table below |
| Evidence area of the site | the site's `/evidence/` route is source code of the published site and was **not changed** by this package; linking these documents from it (P10-ART-xx-R14) is left to the coordinator: the documents are safe to link (synthetic, no credentials) |

## Release and rollback commits (branch `unified-portfolio`)
| Release | Portfolio commit | Source (`business-data-lab`) | Hosted verification (ledger) | Rollback target |
|---|---|---|---|---|
| First publication | `b5168a2` "Publish RetentionLab (labs/retentionlab) and add its case study to the portfolio" (2026-10-27 05:42:47 UTC) | `3c6550efe301e23d53c21bf147d7ea6d1a5506cd` | CI `40456539440` green in both modes; live-check run `40456970303` (all ten sites success; retentionlab live code_sha `3c6550efe301e23d53c21bf147d7ea6d1a5506cd`) | the commit before `b5168a2` (not recorded in the manifest) |
| Case-study correction | `356be88` "RetentionLab case study: correct the economics population, test count, churner rows vs accounts, the drift series and its false positives, the Platt effect, the apac gap and the disclosed choices; state the open defects" (06:04:38) | unchanged `3c6550e` | covered by the portfolio build | `b5168a2` |
| **Republish after review R10 (current)** | **`cf04a0e`** "Republish RetentionLab after the review fixes; case study states what was found and fixed" (07:01:21; ledger `published.at` 07:02:05Z) | **`c17fa321f28605ac56e24b59837441c29cc16d41`** (app content `ce96e65`; ledger commit on top) | CI **`40464123151`** green in both modes on `c17fa32`; live-check run **`40464668157`** (success; live code_sha matched `c17fa321f28605ac56e24b59837441c29cc16d41`; recorded 2026-10-27T07:04:14Z) | **`28d974b`** (the manifest's `rollback_commit_unified_portfolio`) |

The live check of `cf04a0e` was **pending at dispatch** of this package (the release manifest then held `live_verification: null`, `publication_status` "live check pending"); it was recorded while this pass ran and is copied, not fetched. `program-status.json` records `published: {release cf04a0e, rollback 28d974b, source c17fa32, at 2026-10-27T07:02:05Z}`, `verified: {live_check_run 40464668157, at 2026-10-27T07:04:14Z, release cf04a0e}`, `integrated: true`. The CI run `40464667982` on the workflow-provisioning commit `7a748ac` (LibreOffice Calc, `artifacts10_*` scratch databases, full history, the portfolio case study) succeeded in both modes with no artifact tests yet; **no hosted run of `tests/test_artifacts.py` is recorded yet** (pending: the branch has not been pushed with this package).

## Rollback procedure (not executed; nothing was committed or pushed by this package)
1. On `unified-portfolio`, find the release commit: `git log --oneline -- labs/retentionlab retentionlab` shows `cf04a0e` (and `356be88`, `b5168a2` before it).
2. Revert the republish rather than rewrite history: `git revert cf04a0e` (this restores `labs/retentionlab/` and `retentionlab/project.json` to the state at `28d974b`, the release manifest's rollback target, which is the first publication with the corrected case study). If only the case-study text must go back, revert only `retentionlab/project.json`.
3. Push to the **private** repository only (`git push private unified-portfolio`); do not push to `origin` or merge into `main` (the owner decides when the public site is updated).
4. Re-run the live check for the reverted commit before calling it verified; record the new run in the ledger.
Rollback of this package's documents is deletion of the new files (they change no application code, no migration and no fixture).

### Rollback manifest (copied from the release manifest; nothing here was changed)

| Item | Current | Rollback target |
|---|---|---|
| portfolio commit | `cf04a0e` | `28d974b` |
| source commit (`business-data-lab`) | `c17fa321f28605ac56e24b59837441c29cc16d41` (app content `ce96e65`) | `3c6550efe301e23d53c21bf147d7ea6d1a5506cd` (previous release `b5168a2`) |
| published tree | 39 files, sha256 `4013064ff2bbc4bab4a482c7dc2b008a54292c2271635b9fee5f3935def12413` | not recorded in the manifest |
| dataset | `rl-20261026-20261026`, hash `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`, 4,614,525 bytes published | the earlier world (before the prevalence-constant model, D-09 R10-14): not recorded |
| live verification | run `40464668157` success | run `40456970303` success |

## Main-portfolio metadata (from `/retentionlab/project.json` on `unified-portfolio`)
| Field | Value |
|---|---|
| title | Which Accounts Deserve Limited Retention Attention Under Uncertain Intervention Value? |
| kind | Dashboard · Data science · Churn and calibration · FastAPI · React |
| order | 309 |
| date | 2026-10 |
| repo | https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/retentionlab |
| demo | https://mrrishit909.github.io/projects-site/labs/retentionlab/ (label "Open RetentionLab") |
| cover | `cover.jpg` (with `loop.mp4`, `loop.webm` and `shots/` in the same directory) |
| tech | Python 3.11; PostgreSQL 16; FastAPI 0.162; SQL reference recomputation; TypeScript + React 18 + Vite; Playwright 1.55; GitHub Actions; "342 Python tests, 3,197 TypeScript golden and snapshot checks plus 95 review checks over 31 worlds, 90 browser tests" |
The record was read, not changed. The 342 Python tests are the suite before this package; with `tests/test_artifacts.py` the suite is larger (see below), and the record states the count of the run it was built with.

### Claims of the public case study checked against this package's reconciliation
| Claim (`project.json`) | This package | Result |
|---|---|---|
| logistic AP 0.238552, Brier 0.105019; rule 0.136653 and 0.109255; random 0.126793 and 0.326543 on 1,513 rows from 442 accounts, 189 churning rows from 95 accounts, prevalence 0.124917 | investigations 01 and 08 | equal |
| Platt: Brier 0.104515 to 0.105019, overall gap -2.26 to -2.86 pp, all 289 calibration rows from one cutoff; starter -8.07 pp; apac -10.68 pp not designed; six of ten bins empty | investigations 02 and 10 | equal |
| apac PSI 0.513545 at 2026-05-01, peak 0.765053 in August, 0.491035 in September; five exceedances before the change up to 0.679573 | investigation 07 | equal |
| "the whole population stays at 0.017043" | investigation 07 | **imprecise**: 0.017043 is the whole-population value at 2026-05-01; over the series it ranges from 0.000000 (the reference month) to 0.043730 and is 0.002069 in September. Wording for the coordinator; no figure is wrong |
| "five of the thirteen months before the change" | investigation 07 | **ambiguous**: five of the 13 cutoffs before the reference cohort (2025-01..2026-01), or five of 14 comparison cutoffs before the change (the reference month excluded); both hold |
| 9,039 eligible rows, 3,594 censored (0.397610), mature churn 0.104500 | investigation 04 | equal |
| a feature changes on 11.57 percent of the test rows if arrival is ignored | investigation 05 (published figure: 175 of 1,513 = 0.115664; the cohort's own rate is 0.126797 of 765 rows) | equal (the published world figure) |
| 879 + 176 training rows dropped, 1,088 retained, 744 fitted, 289 validation rows from one cutoff | investigation 06 and the manifest | equal |
| +21.38 / -6.87 / -95.46 on the 97-account cohort and +81.13 / +71.04 / -29.12 on the 1,241-account world, hypothetical | investigation 03 and reconciliation F | equal |
| "Not built yet: ... an SQL recomputation of average precision and the stability index" | investigations 01, 02, 07, 08, 09 | **overtaken** by this package: AP and PSI are now recomputed in SQL (and in Python); the sentence and the README/D-06 gap should be updated when this package is published |
| 342 Python tests, 3,197 golden checks, 95 review checks, 90 browser tests | `pytest` baseline (342 passed), the ledger | equal for the suite before this package |
Wording points are reported to the coordinator; the record lives on `unified-portfolio` and was not touched.

## What this artifact pass ran (2026-10-27, scratch databases `artifacts10_*`; never the shared `retentionlab` database)
Commands, from `apps/retentionlab`, with `../../.venv/bin/python`; `<creds>` stands for the local development login of the CI workflow's throwaway `postgres:16` service (127.0.0.1:5432), which is not written in any document. Scratch databases created for this pass: `artifacts10_run_snapshot` and `artifacts10_run_golden` (created, loaded and dropped by `run_all.py` itself), `artifacts10_snapshot`, `artifacts10_golden` (the test's re-run) and `artifacts10_pytest` (the suite's `DATABASE_URL`, which the suite resets); all dropped at the end.
| Command | Result (last line) |
|---|---|
| `python -I tests/reference_check.py` | `ALL OK (1823 checks)`, exit 0 (7 fixture hashes `OK`) |
| `DATABASE_URL=<scratch> python -m pytest -q -ra -x` (baseline, before this package's test existed) | `342 passed, 1 warning in 318.78s (0:05:18)` |
| `python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi` | `RESULT: OK (393 reconciliation rows, 393 equal; 43 result sets, 229 rows)`, exit 0; `wrote 16 CSV files to artifacts/bi` |
| `python data/sql/analysis/run_all.py --skip-world` (no whole-world rebuild) | `RESULT: OK (366 reconciliation rows, 366 equal; 43 result sets, 229 rows)` |
| mutation check: one test-table outcome flipped in a scratch copy (restored afterwards) | 11 of 43 result sets differ from the Python side; the restored run is OK |
| `python artifacts/render_sql_analysis.py` | `rendered docs/sql-analysis.md`, `rendered docs/bi-package.md` |
| `python artifacts/build_workbook.py --recalc` | `wrote artifacts/retentionlab-analyst-workbook.xlsx (70 checks)`, `recalculated with LibreOffice headless; cached values written`; `Checks!B2` TRUE |
| `python artifacts/checksums.py --table` and `sha256sum -c artifacts/CHECKSUMS.txt` | every file `OK` |
| `DATABASE_URL=<scratch> ARTIFACTS_DATABASE_URL=<scratch> ARTIFACTS_GOLDEN_DATABASE_URL=<scratch> python -m pytest -q -ra tests/test_artifacts.py` | `41 passed` (about 3 minutes: three LibreOffice recalculations and the database re-run) |
| the same without the two ARTIFACTS URLs | `40 passed, 1 skipped`; `SKIPPED [1] tests/test_artifacts.py: ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts10_*; the test prepares them with data/sql/analysis/prepare_snapshot.py) are not set` |
| `DATABASE_URL=<scratch> ARTIFACTS_DATABASE_URL=<scratch> ARTIFACTS_GOLDEN_DATABASE_URL=<scratch> python -m pytest -q -ra` (the whole suite) | `383 passed` (the 342 existing tests plus the 41 test cases of this package; no existing test changed) |
| `git diff --stat ce96e65 -- domain api data/migrations data/seed.py data/migrate.py data/generate.py data/sql/reference_metrics.sql web/public web/src tests ':(exclude)tests/test_artifacts.py' docs/contracts.md README.md` | empty (`test_provenance_the_analysed_code_and_data_equal_revision_ce96e65`) |
No existing domain, API, migration, loader, reference-SQL, web, fixture, generator, test or contract file was modified; `git status` shows only new files (`artifacts/`, `data/sql/analysis/`, `data/sql/verification_layer.sql`, `docs/*.md` of this package, `requirements-artifacts.txt`, `tests/test_artifacts.py`).

## Artifacts and checksums (sha256; also `artifacts/CHECKSUMS.txt`, verifiable with `sha256sum -c artifacts/CHECKSUMS.txt` from `apps/retentionlab`)
<!-- BEGIN:checksums -->
| File | sha256 |
|---|---|
| `artifacts/analysis-results.json` | `e43857ac2d12fddbb341c756975621e71731b73e2fdf9deae4b8dd15a85d994b` |
| `artifacts/bi/dim_bin.csv` | `25da01ed126d073e264913eb7cac537c881af679b8f91edfd6ae498314522d94` |
| `artifacts/bi/dim_cutoff.csv` | `ab1b67273c289d7674e577c6ab00b1d92073a5696aa1bdfe829d93088850f3c8` |
| `artifacts/bi/dim_model.csv` | `d5cb2f02e69ff928c8142ebc6be27922aa2e1e8868888debbadc10d52386e7f2` |
| `artifacts/bi/dim_population.csv` | `3685e24aaec19fac3278505c17a7316573688bc28ccc138dbe2c0766641794ce` |
| `artifacts/bi/dim_region.csv` | `6c50811441a14e533160865de7e15f265354cffd960a0e5a768a24d8b6a010a8` |
| `artifacts/bi/dim_scenario.csv` | `a6621dac89a05931e8b57478253a2d702732f136a292dbe342089f11abe2aba6` |
| `artifacts/bi/dim_segment.csv` | `7ab48a54faa51484056a1b333fe2d4a7330a0dae48df0d9deee2d78dbbc42cb3` |
| `artifacts/bi/fact_calibration_bin.csv` | `a313a21802545d4cebbd01c3891cc769319c309346a2da0a977dd1725eb0ae2d` |
| `artifacts/bi/fact_capacity.csv` | `e712aa102d5159f5c093e520aada29518a2de9f12441de0e33f5b04b8336d1d0` |
| `artifacts/bi/fact_cutoff.csv` | `f121a7b23bbbd346fec1a0dc3cc2798f147fea1dcb1cdc521611be707490fa28` |
| `artifacts/bi/fact_drift.csv` | `728b76921dacec65010ee7532848e56c2e9b29f560d5e5007249bebe23afad16` |
| `artifacts/bi/fact_model_metric.csv` | `75b374138e95f704cab2feed312d1076495ffb16c5309892b15ae7a3f6a35d09` |
| `artifacts/bi/fact_purge.csv` | `8b9f9c54a0a12a49cdc3500ccd1e238f67de8821c2cb59896a82ec9ff6e304b1` |
| `artifacts/bi/fact_segment_gap.csv` | `3c9147dfde8ca6c153c503754d22113621dd1fe6bb6f714bc7478707d97bea81` |
| `artifacts/bi/fact_test_row.csv` | `f47cb3d1bd250bc6b37afe293d8b098435a0ff0f0b624174f5dcdc111aa70907` |
| `artifacts/bi/measures_recomputed.csv` | `32eed7e8e64fcd2c3c26ca34718402d9b37bde994c7f0baedce2bcfb75c73f3d` |
| `artifacts/build_workbook.py` | `4b39b5e36f1a5d90cc0617f9f36a075a8615093c6a9382678e1ed0c970858ef5` |
| `artifacts/checksums.py` | `af032a6817a500fffd5b055def83a2155f08dee541feed4ccd12ed80690dc4aa` |
| `artifacts/render_sql_analysis.py` | `cc7cf08f8280201ad68b7ff63b95638ac42daa4ea61b3bab0c66469aa26da40b` |
| `artifacts/retentionlab-analyst-workbook.xlsx` | `98e045ce77fa5b9a634cac7e3801d7fbc1169ef3f1a94e00c9925d8f9e980e96` |
| `data/sql/analysis/01_model_comparison.sql` | `354f00c03466358d1585c78bbadc8267b65f74844096b8beefb76b43bc9b9455` |
| `data/sql/analysis/02_calibration_platt.sql` | `f0fccca825e276a375e9f1d0103dfa2487965cde9f5d942ac35c6aebddaaa048` |
| `data/sql/analysis/03_capacity_economics.sql` | `87de45f1f6ba7412c72c3a3ad34a68fa5fec79315b37c986c067af488aeeb3ec` |
| `data/sql/analysis/04_censored_tail.sql` | `f9559b4819f7bc17b4ff6051f979f2084b705548f2717ceffef8d92eb61ae406` |
| `data/sql/analysis/05_arrived_late.sql` | `784ada52db1a9ef9acc6737fd009f55eed2d03f37f9bdd2c2f3415c4420caa18` |
| `data/sql/analysis/06_purge_counts.sql` | `cf55fd5f1091b5650b5d937f5d8e53a2d8666d09cb226d1fd54990404972cabd` |
| `data/sql/analysis/07_drift_by_region.sql` | `b06705d0706017cb47581590d70a2e69d331a3ce2f4b457e66554634e5f79bf2` |
| `data/sql/analysis/08_rows_and_margins.sql` | `94bf018fd65805082b0a77119b684fa32ab2355547592866c253f01807d9f308` |
| `data/sql/analysis/09_golden_known_answer.sql` | `f30072541964f7a3862f698f8861442674ac4f0b0b8b89c949b9e7047cd2ca6a` |
| `data/sql/analysis/10_segment_region_calibration.sql` | `7156dfc4befffa3fc31053ffa2b6503d540d991f6c27a819eeb4d243182449f4` |
| `data/sql/analysis/bi_dimensions.sql` | `e8c86a4a4c9c5c52219e6d1e62f046ec75923e427ab637d7d6a865835ac67388` |
| `data/sql/analysis/bi_fact_calibration_bin.sql` | `52e60aefbf972189d5c5f564ee522e70e1a146c8c6393bc0a922a3a3d9d36861` |
| `data/sql/analysis/bi_fact_capacity.sql` | `a10678de178210e1ece7cbcbb150554f233f658fd9d43d958ca0a9c941220943` |
| `data/sql/analysis/bi_fact_cutoff.sql` | `412772415ec28b61f2cde090e189e0f0e0d2fe152dd2e56755e033ac486a9d01` |
| `data/sql/analysis/bi_fact_drift.sql` | `e0d623a8bc687cb7b046eb19d730753d230b5a038bf730dadda1e039b270aa43` |
| `data/sql/analysis/bi_fact_model_metric.sql` | `09f6b5516c43dd95654cdd9a409fbb0f2ef247c0f34936f740a146b9643702d3` |
| `data/sql/analysis/bi_fact_purge.sql` | `fd024e1c2721943c512051ed84e1ad4f643c17656078e535d2414e0b87211cd0` |
| `data/sql/analysis/bi_fact_segment_gap.sql` | `680858d4b9dfc6496f04e76118becaee557eeea5fb1c64fd4114356986f35070` |
| `data/sql/analysis/bi_fact_test_row.sql` | `26f233594ed531694306df3545985931bd98e61f7b4cace85e5f50febdf52f47` |
| `data/sql/analysis/prepare_snapshot.py` | `8050f11548462e2bcf90ec706d56fb10411629274d8455391b5d721ad6147176` |
| `data/sql/analysis/python_side.py` | `0cb70cb89da7cedb9ae93fd868beb6c2c6356d7cfb0fa343055af5e4634ef654` |
| `data/sql/analysis/run_all.py` | `5413a156950070548a18c9e894f13a63b3d0ed35f5251c5234b7c5e90910a8d2` |
| `data/sql/verification_layer.sql` | `cc0f0f9b067922bf0be4cd2d63c6ad5724fe7cb32d1d153ce95a79b48898b5e6` |
| `docs/api-contract.md` | `6f26b78526d99c1235c33a5f6b90d88a00e67e6f96cb0ea98f9f8abf26c74150` |
| `docs/bi-package.md` | `89c3cdba30f48ddcd67e44e7ad9a7992997c834190164bf9d0dd64c7a2ac4281` |
| `docs/business-case.md` | `e0b34fa2a8d371958c15a4a5ef9f29c0e73f94df1e17010cc2eb7fd301921355` |
| `docs/contracts.md` | `e0c1ead53aed2f25dc97a528171f7e613e22408538ff10e11a65230c02874625` |
| `docs/data-dictionary.md` | `a5702137e48f5f613b45da40e6bcd123dafb289c3d5ddbe01e34ccc5e17ef55c` |
| `docs/data-generator.md` | `ba626f828ac100e92d6b21ab7c748649880a0e2794b168c23eb14ecf7c1d8d91` |
| `docs/erd.md` | `7f1c2ad86a975c2a4214d3659aac3f481d80ad187f187ad1962ab46f1118ead4` |
| `docs/executive-memo.md` | `ce2bb88b66eed696ab690d4c1b2525b40219bda325b2313f6e8c699b271d750a` |
| `docs/requirements.md` | `7b65fd8ca3b138e9082ac89f6eeac65e2fbf021f491d4b6776dc417550ce57bf` |
| `docs/resume-bullets.md` | `11056e792c4e1cca816ec1325671a6ff431e92371e0c707ae9a630c4b6cd4a70` |
| `docs/sql-analysis.md` | `b61054f951265596c946eb52fe6124c2a8347a0e4e45993970a54a39c1b9ab82` |
| `docs/technical-case-study.md` | `2e8907281315295d78e8c4f6899278de45c1739e0faa4168e0dca98cf524d3f5` |
| `docs/uat-evidence.md` | `d6c1c7343277596b92ef5bf326acb3b1335891e39fe4427b59e08935393f784f` |
| `docs/web-brief.md` | `822783b8f9a7bbe7a7a6f05be3be5adbbec059b10a6431958775f24d558b51e8` |
| `docs/workbook.md` | `a4581811a579295313299d4845db92b97557ccc30a8c352c9b4fbf54b32049cb` |
| `requirements-artifacts.txt` | `06d28d69e958deafb09f0a44fcae9b548f15e4debc14ebc39aad5f0934856fbf` |
| `tests/test_artifacts.py` | `e08a5feedb7f1a68044674071a7b7c8ab7c26603cb02f7cb473f3508d926447f` |
<!-- END:checksums -->

## Verification status of this package (stated plainly)
* **Verified locally in this pass:** the reconciliation (393 rows, all equal, including a rebuild of the whole 2,400-account world), the workbook check cell (TRUE after LibreOffice recalculation, with three other model and what-if selections), the BI measures recomputed from the CSV files, the documents quoted from the stored results, the checksums, the independent reference check and the existing suite (see above).
* **Not verified:** Excel, Power BI Desktop and any DAX engine (no `.pbix`); any hosted run of `tests/test_artifacts.py`; the live site itself (the live check of `cf04a0e` is the ledger's run `40464668157`, copied not fetched); `npm run check` and `npm run e2e` by this pass (their results are the recorded runs in `uat-evidence.md`).
* **Binary artifacts** (the workbook) were generated in a sandbox, not on a GitHub-hosted runner, and are not attached to a GitHub release (P10-ART-xx-R06): a durable release asset needs a hosted workflow run, which this package did not start.
* **CI gate:** the workflow `retentionlab-ci.yml` installs LibreOffice Calc, creates `artifacts10_snapshot` and `artifacts10_golden`, fetches full history and the portfolio case study, and sets `ARTIFACTS_DATABASE_URL` and `ARTIFACTS_GOLDEN_DATABASE_URL`, so the tests that skip locally without them run there; the workflow does not itself fail on a skipped test (the TrustLedger no-skip junit gate is not in this workflow).
