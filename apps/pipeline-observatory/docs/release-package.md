# Release package (P08-ART-10)

Dataset `po-20261026-20261026` (generator `dataset_hash` `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`), contract v1, code revision **`ed7eb5a8b403db8dcb158c6a3399ee126dc29450`** (`ed7eb5a`, the review-R8 fixes; the published source `b326690a791ca440e6c616dea361383cb8f7e665` adds ledger files only: the app content equals `ed7eb5a`). **Synthetic data only.** This package **committed and pushed nothing**; every id below marked "ledger" is copied from the committed ledgers (`docs/program/release-manifest.json`, `verification-ledger.json`, `delegation-ledger.jsonl`, `task-queue.json`, `program-status.json`) and was **not fetched** by this pass.
The decision it supports: **is this dataset safe, complete, and fresh enough to publish?** (`executive-memo.md`: publish `pub-1343` with a stated exception for `src-refunds`).

**How to read it without installing anything:** where everything lives, the release and rollback commits copied from the ledgers, the rollback procedure (not executed), the portfolio metadata and the case-study claims checked against the reconciliation, what this pass ran, and the checksums.

## Where it lives
| What | Where |
|---|---|
| Individual site (static, Mode B) | https://mrrishit909.github.io/projects-site/labs/pipeline-observatory/ (`labs/pipeline-observatory/` on `unified-portfolio`, 41 files, published tree sha256 `12f59fe2f3a5533b27dcd3e9189ab034c5bf9d6d42fa62e8dc66343d60a95370`); not fetched by this pass |
| Source | `apps/pipeline-observatory/` on branch `business-data-lab` of https://github.com/mrrishit909/projects-site (the `repo` field of the portfolio record: https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/pipeline-observatory) |
| Contracts and decisions | `docs/contracts.md` D-01..D-09, `README.md`, `docs/api-contract.md`, `docs/web-brief.md`, `docs/data-generator.md` |
| Golden fixture and hashes | `tests/fixtures/golden/` (`HASHES.json`, `CALCULATION.md`), `tests/reference_check.py` |
| Published data and manifests | `web/public/data/` (`manifest.json`, `injection-manifest.json`, sixteen entity files; `raw_records.json` is a 2,000-row sample) |
| Analysis | `data/sql/analysis/` (ten numbered investigations, the golden known answer, BI queries, `prepare_snapshot.py`, `python_side.py`, `run_all.py`), `artifacts/analysis-results.json` |
| Workbook | `artifacts/pipeline-observatory-analyst-workbook.xlsx` (`workbook.md`) |
| BI package | `artifacts/bi/*.csv` (`bi-package.md`) |
| Documents | `docs/{business-case,requirements,data-dictionary,erd,sql-analysis,workbook,bi-package,executive-memo,uat-evidence,technical-case-study,release-package,resume-bullets}.md` |
| Checksums | `artifacts/CHECKSUMS.txt` (`sha256sum -c artifacts/CHECKSUMS.txt` from `apps/pipeline-observatory`), and the table below |
| CI workflow | `.github/workflows/pipeline-observatory-ci.yml` (job `reference-and-domain`: LibreOffice Calc, scratch databases `artifacts08_snapshot` and `artifacts08_golden`, full history, the portfolio case study; job `web`) |
| Evidence area of the site | the site's `/evidence/` route (hashes recomputed in the browser, designed relationships, injected defects, scope tags) is source code of the published site and was **not changed** by this package; linking these documents from it (P08-ART-xx-R14) is left to the coordinator: the documents are safe to link (synthetic, no credentials) |

## Release and rollback commits (branch `unified-portfolio`)
| Release | Portfolio commit | Source (`business-data-lab`) | Hosted verification (ledger) | Rollback target |
|---|---|---|---|---|
| First publication | `83b6a60` | `a2ef4f4130e04f5d70795ba8d83b97f02d962583` | web CI `40455458608` green in both modes; live-check run `40456053215` (all eight sites success; pipeline-observatory live code `a2ef4f4130e04f5d70795ba8d83b97f02d962583`) | the commit before `83b6a60` (not recorded in the manifest) |
| Case-study wording corrected after review R8 | `3558f84` (R8-07, R8-09, R8-10, R8-11, R8-14, R8-16 fixed live by the coordinator, ledger A-073) | unchanged | covered by the portfolio build | `83b6a60` |
| **Republish after the review-R8 fixes (current)** | **`d58209f`** (published 2026-10-27T07:51:33Z) | **`b326690a791ca440e6c616dea361383cb8f7e665`** (code fixes `ed7eb5a`, ledger commit on top) | CI **`40468689563`** green in both modes on `b326690` (release manifest `publication_status`); **live check: pending at dispatch** of this package (A-080 was dispatched at 07:51:33Z, the instant of publication); recorded afterwards as run **`40469671918`**, success for all ten sites, pipeline-observatory live code sha `b326690a791ca440e6c616dea361383cb8f7e665`, verified 2026-10-27T07:53:13Z | **`cf04a0e`** (release manifest `rollback_commit_unified_portfolio`) |
`program-status.json` records `published: {release d58209f, rollback cf04a0e, source b326690, at 2026-10-27T07:51:33Z, note: republish after review fixes}`, `verified: {live_check_run 40469671918, at 2026-10-27T07:53:13Z, release d58209f}`, `integrated: true`. A source commit is not labelled a verified live release by itself: `d58209f` is **built, published and integrated, and live-verified by the recorded run `40469671918`** (copied from the ledger, **not fetched** by this package; the check matched the live code sha to `b326690`).

## Rollback procedure (not executed; nothing was committed or pushed by this package)
1. On `unified-portfolio`, find the release commit: `git log --oneline -- labs/pipeline-observatory pipeline-observatory` shows `d58209f` (and `3558f84`, `83b6a60` before it).
2. Revert the republish rather than rewrite history: `git revert d58209f` (this restores `labs/pipeline-observatory/` and `pipeline-observatory/project.json` to the state at `cf04a0e`, the release manifest's rollback target). If only the case-study text must go back, `git revert` leaves the site files and the record in step.
3. Push to the **private** repository only (`git push private unified-portfolio`); do not push to `origin` or merge into `main` (the owner decides when the public site is updated).
4. Re-run the live check for the reverted commit before calling it verified; record the new run in the ledger.
Rollback of this package's documents is deletion of the new files (they change no application code, no migration and no fixture).

## Main-portfolio metadata (from `/pipeline-observatory/project.json` on `unified-portfolio`)
| Field | Value |
|---|---|
| title | Is This Dataset Safe, Complete and Fresh Enough to Publish? |
| kind | Dashboard · Data engineering · Reliability · FastAPI · React |
| order | 307 |
| date | 2026-10 |
| repo | https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/pipeline-observatory |
| demo | https://mrrishit909.github.io/projects-site/labs/pipeline-observatory/ (label "Open Pipeline Observatory") |
| cover | `cover.jpg` (with `loop.mp4`, `loop.webm` and `shots/` in the same directory) |
| tech | Python 3.11; PostgreSQL 16; FastAPI 0.162; SQL reference recomputation; TypeScript + React 18 + Vite; Playwright 1.55; GitHub Actions; "529 Python tests, 1,180 TypeScript golden and snapshot checks plus 255 review checks over 51 worlds, 90 browser tests" |
The record was read, not changed. **No claim of it is contradicted by the reconciliation**; two points need a coordinator's attention (below).

### Claims of the public case study checked against this package's reconciliation
| Claim (`project.json`) | This package | Result |
|---|---|---|
| six sources, 1,311 batches, 40,191 raw rows, 1,343 runs, 25 incidents, 15 backfills | `manifest.json` `row_counts`, `run_all.py` family B | equal |
| 39,901 rows in committed batches: 37,248 accepted, 2,101 duplicates, 429 quarantined (rejection 0.010752, duplicate 0.052655), plus 123 delete events | investigation 01 | equal (complete world) |
| the 17 rows of the one batch quarantined whole are listed separately and in no rate | investigation 01 | equal: 429 + 17 = 446 quarantine rows |
| 1,343 runs, 1,328 reached the gate, 1,318 allowed, 10 blocked (five freshness, four relationships, one residual), 15 failed before it | investigation 02 | equal |
| task success 0.995311, attempt success 0.971622; pointer on `pub-1343` | investigations 03 and 05 | equal |
| refunds: freshness 262,378 s against an ingestion age of 17,363 s, all 72 runs green, completeness 0.000000 on its last three days, 7-day target | investigation 04 | equal (freshness and the three empty days are **recorded**; the sample's latest refunds event coincides with the record) |
| `run-1187` blocked, pointer stays on `pub-1186`, recovery 67.8833 minutes; all 25 incidents closed, mean 60.6827 | investigations 05 and 06 | equal |
| shipments rate-limited 49 times, every retry honoured retry-after | investigation 08 | equal |
| 757 late events, none lost; every publication reconciles to 0.00; one residual -141.46 on 2026-09-09; 141 late events recomputable over the sample | investigation 06 and `run_all.py` family B | equal (757 and the 0.00 are recorded; -141.46 recomputed from its parts; 141 = reference SQL = domain over the sample) |
| eleven of fifteen partitions of thirteen accepted backfills verified (0.733333); two further requests refused | investigation 07 | equal |
| 9,296 quality results instead of 6,640; the two refused backfills overlap requests that were running | `manifest.json`, investigation 07 | equal |
| known answer: 10 / 8 / 1 / 1; 52,200 s against 42,900 s; 8 of 9; 1.000000 against 0.800000; -30.00 and 29.97; 475.0000; 2 of 3; "all 742 checks" | investigation 09; `tests/reference_check.py` | equal (742 checks re-run in this pass) |
| "529 Python tests" | the tests directory before this package | **will read N after `tests/test_artifacts.py` lands**: the claim is true of the suite the coordinator ran; adding this file raises the count. Reported to the coordinator; the file lives on `unified-portfolio` and was not touched |
| "the other 15 failed in a task before the gate ran" | investigation 02 | equal; note that the domain's `pointer_history` labels all 25 failed runs `blocked`, which is why the funnel separates the stages (not a contradiction) |

## What this artifact pass ran (2026-10-27, scratch databases `artifacts08_*`; never the shared `pipeline_observatory` database)
Commands, from `apps/pipeline-observatory`, with `../../.venv/bin/python`; `<creds>` stands for the local development login of the CI workflow's throwaway `postgres:16` service (127.0.0.1:5432), which is not written in any document. Scratch databases created for this pass: `artifacts08_run_snapshot` and `artifacts08_run_golden` (created, loaded and dropped by `run_all.py` itself), and `artifacts08_snapshot`, `artifacts08_golden`, `artifacts08_pytest` (created with `createdb`, all dropped when the pass ended). The shared `pipeline_observatory` database was neither read nor written.
| Command | Result (last line) |
|---|---|
| `python -I tests/reference_check.py` | `ALL OK (742 checks)`, exit 0; 7 lines `OK hash.` (the fixture hashes) |
| `ARTIFACTS_DATABASE_URL=<scratch> python data/sql/analysis/prepare_snapshot.py` and `ARTIFACTS_GOLDEN_DATABASE_URL=<scratch> ... --golden` | snapshot `po-20261026-20261026`, hash `0a906877...`, 2 rejected rows kept (bf-006, bf-012), 2,000 raw rows, 1,361 fetch rows, 1,311 batch summaries; golden hash `08049a5cd683...` |
| `python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi` | `RESULT: OK (204 reconciliation rows, 204 equal; 64 result sets, 303 rows)`, exit 0; `wrote 14 CSV files to artifacts/bi`; `wrote artifacts/analysis-results.json` (about 2 min 40 s) |
| mutation check: the attempt-success rate of `03_task_vs_attempt_success.sql` rounded to 5 places instead of 6 (restored afterwards) | the SQL-against-`python_side.py` comparison (family C) reported `DIFF 03_task_vs_attempt_success__overall`; restored: 0 differences |
| `python artifacts/render_sql_analysis.py` | `rendered docs/sql-analysis.md`, `rendered docs/bi-package.md` |
| `python artifacts/build_workbook.py --recalc` | `wrote artifacts/pipeline-observatory-analyst-workbook.xlsx`; `recalculated with LibreOffice headless; cached values written`; `Checks!B2` TRUE; `Publish decision!B10` = "PUBLISH WITH A STATED EXCEPTION: 1 source is silent while the jobs stay green, the first is src-refunds" (and TRUE with the switches flipped, by the tests) |
| `python artifacts/checksums.py --table` and `sha256sum -c artifacts/CHECKSUMS.txt` | `wrote artifacts/CHECKSUMS.txt (59 files)`; every file `OK` |
| `DATABASE_URL=<scratch> ARTIFACTS_DATABASE_URL=<scratch> ARTIFACTS_GOLDEN_DATABASE_URL=<scratch> PIPELINE_ENVIRONMENT=sandbox python -m pytest -q -ra tests/test_artifacts.py` | `39 passed in 92.70s (0:01:32)` |
| the same without the two `ARTIFACTS_*` URLs | `38 passed, 1 skipped in 45.55s`; `SKIPPED [1] tests/test_artifacts.py:271: ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (scratch databases named artifacts08_*; the test prepares them with data/sql/analysis/prepare_snapshot.py) are not set` |
| `DATABASE_URL=<scratch> ARTIFACTS_DATABASE_URL=<scratch> ARTIFACTS_GOLDEN_DATABASE_URL=<scratch> PIPELINE_ENVIRONMENT=sandbox python -m pytest -q -ra` (the whole suite) | `568 passed, 1 warning in 644.96s (0:10:44)` (the 529 existing tests plus the 39 of this package; no existing test changed; the warning is Starlette's `httpx` deprecation notice). Two wording edits to `sql-analysis.md` and `technical-case-study.md` followed; `tests/test_artifacts.py` was re-run after them (the 39 passed above) |
| `git diff --stat ed7eb5a -- domain api data/sql/migrations data/seed.py data/migrate.py data/generate.py data/sql/reference_metrics.sql web/public web/src web/e2e web/scripts tests ':(exclude)tests/test_artifacts.py' docs/contracts.md README.md ...` | empty (`test_provenance_the_analysed_code_and_data_equal_revision_ed7eb5a`) |
No existing domain, API, migration, loader, reference-SQL, web, fixture, generator, test or contract file was modified; `git status` shows only new files (`artifacts/`, `data/sql/analysis/`, `docs/*.md` of this package, `requirements-artifacts.txt`, `tests/test_artifacts.py`). `npm run check` and `npm run e2e` were not run by this pass.

## Artifacts and checksums (sha256; also `artifacts/CHECKSUMS.txt`, verifiable with `sha256sum -c artifacts/CHECKSUMS.txt` from `apps/pipeline-observatory`)
<!-- BEGIN:checksums -->
| File | sha256 |
|---|---|
| `artifacts/analysis-results.json` | `72401879ad2c9306a599319ed674d109a9feec371b8f685c5e84bc2ef40ff0e9` |
| `artifacts/bi/dim_check.csv` | `59bc616f1fb67ecba229b899db15017191a4b49d0ff7fd7216ad988c6911ebaf` |
| `artifacts/bi/dim_date.csv` | `1fe61b92ac2f10ae1df185eac0d5bfc1d1bb39dd23905548adee5b042f0a22b3` |
| `artifacts/bi/dim_failure_kind.csv` | `9d7a65c8cb10f4f127a19e2f95f9a18cd942d47af75ded9391cd4afac867e6ca` |
| `artifacts/bi/dim_measure.csv` | `adc7890f087808d806fa03c23e49ddecef33f00fca91e62ea6c5f9bed738bce2` |
| `artifacts/bi/dim_scope.csv` | `29fe51520538499a6d460a539a15bfc10f78b5a112843d8d3cbdca1f9d2a347b` |
| `artifacts/bi/dim_source.csv` | `06b266fb4389892d917807a7c915b5aced8a7a684c19e05f3dc93ea4191caabe` |
| `artifacts/bi/fact_backfill_partition.csv` | `73c5d1052afe5dd76cf1c1ab4f90eda9aa8a8b3302e3d2194b3b6661c5a68206` |
| `artifacts/bi/fact_batch.csv` | `e1a25934f3e5ea77c35ed5840fc3a7b7196fb5a52e022c85f341ff4e7fb6cf4c` |
| `artifacts/bi/fact_fetch.csv` | `c6f359921987e9f78349d6b192781a8ae42819b1790fd7cee9afb8b2406ee81f` |
| `artifacts/bi/fact_freshness.csv` | `18eb1c7e09075b497b9f729a908c45f37857d6e394abbf5642bf7cd4c1aee68e` |
| `artifacts/bi/fact_gate_check.csv` | `2fdf4e8383a2a2d66545631a706a7d9216fc462e1ccf252b46ed590adaaaeb64` |
| `artifacts/bi/fact_incident.csv` | `968af8f7c905ac218dbc0ad8b639ab2b663e76536b685c0a7aa66fe5f2ae5d3c` |
| `artifacts/bi/fact_run.csv` | `06cd65395215cdb911392303ec87153d462fef6eac4aa4e09869a7877f5d11b6` |
| `artifacts/bi/measures_recomputed.csv` | `b4c5501bbda29ff63df7ea85a0ffe9724fe196488ab34c856380b608ab328768` |
| `artifacts/build_workbook.py` | `673ec3383407f617536b184b3db313c1449437dc77b0b187aa59e1ab6282bf86` |
| `artifacts/checksums.py` | `8cc250dc42d0c55206f357114eda1bdc4ed4322d7950e6b5788958a8418bb7ba` |
| `artifacts/pipeline-observatory-analyst-workbook.xlsx` | `46dad3f8a86c022875b89e9570128d91cfb0d71568da2d1062f8d6f03bc79cd7` |
| `artifacts/render_sql_analysis.py` | `d9a16650e99517c391bd52cbbbcb40f69ff09aff780847279c4dd67d9a6e54d1` |
| `data/sql/analysis/00_definitions.sql` | `dd2e0cd29e577702f3fd73aa8fdf2d6414974a27f25c05bf71ae180febf567ba` |
| `data/sql/analysis/01_ingestion_by_source.sql` | `d30fff331ebf74320b14fec11b662f8f1311c04b723c1819100f05d576903339` |
| `data/sql/analysis/02_run_funnel_by_failure_kind.sql` | `2e7da85d3b2259bbd5bab044e6e68ff166a4419559e16b4d27ae730d86deeef0` |
| `data/sql/analysis/03_task_vs_attempt_success.sql` | `11d891f565e93a1319c5eeec0e3c72bfdf5c4b085c9f90e5997347c995175b19` |
| `data/sql/analysis/04_freshness_vs_ingestion_age.sql` | `13f39f2b6437bc1d63e8d6fffdb36ddbdf0e2409729d7ebb127a0ad0f145e8e7` |
| `data/sql/analysis/05_publication_pointer_and_blocked_runs.sql` | `60cdf6b0c602a0beb56cad265cdddb163c8c061df52d2eccf10f1e8f75d1d64c` |
| `data/sql/analysis/06_incidents_and_verified_recovery.sql` | `2af35cb29af436a3bbaa724a216899462bf819037f406ac75b6abedb5ef48cf7` |
| `data/sql/analysis/07_backfill_coverage_and_refused_overlaps.sql` | `27e720191bfe03b3fa22fe8982b32bd545a0c7648bfb0af851790f07e6315ab2` |
| `data/sql/analysis/08_fetch_log_retry_after.sql` | `d11c5aeb29bb5786b9b9bea0e8f471f61dfef80e504dd30763b87fbd1f5ecb32` |
| `data/sql/analysis/09_golden_known_answer.sql` | `8ab6c2d590daf7a4f70bdad05a6bceee95c94e4a1f36713e4c1607489d0dd4b5` |
| `data/sql/analysis/10_sample_scope_reconciliation.sql` | `2611a9028142379600d60abf3474a7c9c0eeedb3e92f0807fafe5a6ce80693e5` |
| `data/sql/analysis/artifact_tables.sql` | `ec3070f75d65de2ae906a05969fff95d0aa258fd51e83d3a5a93da7a8febf8fa` |
| `data/sql/analysis/bi_dimensions.sql` | `0683ed358a4d4b62021e7588bc3076135ea9b08ced35ea256012eeea18af299d` |
| `data/sql/analysis/bi_fact_backfill_partition.sql` | `2bdd5d4218fd87a87def98eebd3deb7c31f23a3bc67b3373752449a5c4ff736b` |
| `data/sql/analysis/bi_fact_batch.sql` | `4f4266dbd68854239fce21a130ce8c968042dbb04680453fffe8d0b9c4894356` |
| `data/sql/analysis/bi_fact_fetch.sql` | `da1b74b03c0f66d1c29d4bca080387e01a9e49f6873a23669845871e4c62a1e0` |
| `data/sql/analysis/bi_fact_freshness.sql` | `b61e956517d759b933bc4a6f5ef46dcfd4870501c782b9e3d9b0e169e7f4784e` |
| `data/sql/analysis/bi_fact_gate_check.sql` | `21e231da850cd72496bce1657734f343e62730e4083d1757328f6edd9edfe9e3` |
| `data/sql/analysis/bi_fact_incident.sql` | `ecffc7715d38fe08986efdcc27a0a132bcdd6e399d9742aecf7b6750eb5f2f9b` |
| `data/sql/analysis/bi_fact_run.sql` | `f750ca7d8437df435d4c2fc23fabad154270a33cf5718a0ff65a5a1e3691ed0f` |
| `data/sql/analysis/prepare_snapshot.py` | `0da845ed58b0d28ca606172437f2bc2770eb96536ede49f8866e466b3d4ad938` |
| `data/sql/analysis/python_side.py` | `5347dab7853ad6facb66472640f969d1f14a2b55049417a7bcb641c23d9d526b` |
| `data/sql/analysis/run_all.py` | `d1066a6f61c60bb4a7529aeb02630fe51af9dc1da4f34b837d742730c9c5babc` |
| `docs/api-contract.md` | `0da3beaca84798b79f86bbb42fb94da526f3ae549da9a80e93b7fc66d0920353` |
| `docs/bi-package.md` | `262f72837f9a8f4c1cd92c71f8d90404d4604ad659048fbab0a2e6f617e63389` |
| `docs/business-case.md` | `1908d2727e7958a87043fe188b3db27f383921c9d4524b68b4e7ee163da11b5d` |
| `docs/contracts.md` | `ddd04a09f89a111dc96a2d1313f567323a2a42fb76dbf52baefa88986da4ff5f` |
| `docs/data-dictionary.md` | `05a56d41926c26f5c567d88256df2656f5e43cdfdeca0dcb10e80124ebd0023c` |
| `docs/data-generator.md` | `4edd63e4c64a35615cf5ae87d0b586b2e48b86b725782d4b7d0d6f51ef0acc0e` |
| `docs/erd.md` | `ae67f54f28c8940f5a77dd9e85cfb1b37b4665133fc50b2fe980ad97d931c043` |
| `docs/executive-memo.md` | `1a5b0a72a6097ddec5f1a096a39e301aec3bcd65e19d99bc32a1c9ca6f884dc4` |
| `docs/requirements.md` | `37ad9feaeceb3579e7a8ed1e96eb5fe49fac40373f48f180d758a35f9960adb7` |
| `docs/resume-bullets.md` | `802193b92d19d30c5708937127e3e1d61556f312991bc8a1807eee327f7f70cb` |
| `docs/sql-analysis.md` | `34631fac582c49892233d0a8a5bc50f5c7dc656b68b97f82fcad05bfe121f850` |
| `docs/technical-case-study.md` | `30301bf9793f1fbf83237a8887996bb689c591f726ce3ef649b43fb7f13350b4` |
| `docs/uat-evidence.md` | `67706a97edf33b134d60588c055646d5301d3ee619483abd86dbd26b14e51c99` |
| `docs/web-brief.md` | `bd4b4026e5f3618f7c1a8ba4e6dec7282898cd42a4c181e244850f2775b4253d` |
| `docs/workbook.md` | `31689483045b0d30cacc07a14fb43ff358b4a6b169a848c6dc262c50b499f2d6` |
| `requirements-artifacts.txt` | `06d28d69e958deafb09f0a44fcae9b548f15e4debc14ebc39aad5f0934856fbf` |
| `tests/test_artifacts.py` | `62035d99ac52e32210d36a2085ace6133502024a510dfa9632bed1878837c540` |
<!-- END:checksums -->

## Verification status of this package (stated plainly)
* **Verified locally in this pass:** the reconciliation (204 rows, all equal), the workbook check cell (TRUE after LibreOffice recalculation, under the default and the flipped switches), the BI measures recomputed from the CSV files, the documents quoted from the stored results, the checksums, the independent oracle and the existing suite (see above).
* **Not verified:** Excel, Power BI Desktop and any DAX engine (no `.pbix`); any hosted run of `tests/test_artifacts.py`; the live site itself (the live check of `d58209f` is the ledger's run `40469671918`, copied not fetched); `npm run check` and `npm run e2e` by this pass (their results are the recorded runs in `uat-evidence.md`).
* **Binary artifacts** (the workbook) were generated in the session's cloud container, not on a GitHub-hosted runner, and are not attached to a GitHub release (P08-ART-xx-R06): a durable release asset needs a hosted workflow run, which this package did not start.
* **CI gate:** the next push of `apps/pipeline-observatory/**` runs `pytest -q -ra` with LibreOffice Calc, the two scratch databases, full history and the portfolio case study provisioned, so `tests/test_artifacts.py` is meant to run there without skipping; without any of them its LibreOffice, scratch-database, provenance and case-study tests skip with a printed reason, which a no-skip gate would count.
