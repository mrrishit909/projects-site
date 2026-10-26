# Release package (P02-ART-10)

Onboard Studio, business-data-lab project 02. **Synthetic data only**; nothing here is a claim about a real company, onboarding time or savings. Facts below are copied from `../../docs/program/release-manifest.json` (updated 2026-10-26T13:19:43Z) and
`verification-ledger.json`, and the commit order was read from `git log` of `unified-portfolio` (read-only). This package committed and pushed nothing: the artifact files listed below are uncommitted files in the worktree.

## Where it lives
| Item | Value |
|---|---|
| Site URL | https://mrrishit909.github.io/projects-site/labs/onboard-studio/ |
| Portfolio case study | https://mrrishit909.github.io/projects-site/onboard-studio/ (path `onboard-studio/` added in `unified-portfolio` `b642b24`; the manifest records no case-study URL, so this follows the site's layout) |
| Source | https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/onboard-studio (branch `business-data-lab`; manifest `source_commit_business_data_lab` `eac63b911dd73e98f1e5afa43e7a68298f10ba57`, contract v1) |
| Dataset | `os-20261026-20261026`, generator `dataset_hash` `3c20d296bcf178065e9178cae04f763994b4d7197026af2c021ab55b4cc2bc6a` (seed 20261026, 740 cases) |
| Published tree | 45 files under `labs/onboard-studio/`, sha256 `8b7bfab0e61562eff771364e355aa19fc5879cbcf2a1e7227d998aae1d28f47e` (manifest) |
| Live verification | https://github.com/mrrishit909/projects-site/actions/runs/40329082960 (200 on every route in `routes.json` and `data/manifest.json`; first two routes at 360 and 1280 with 0 console errors; 2026-10-26T13:18:08Z); portfolio link both ways: https://github.com/mrrishit909/projects-site/actions/runs/40329407956 |
| Not re-checked here | This package did not fetch `github.io`; the ledger runs above are the evidence. |

## Release and rollback commits (branch `unified-portfolio`)
| Commit | What it is | Role |
|---|---|---|
| `a614136` | Publish Onboard Studio static site at `labs/onboard-studio` (45 files) | **release commit** (manifest) |
| `b642b24` | Add Onboard Studio case study, cover, shots; catalogue and archive rebuilt | integration commit |
| `a9d6b1d` | Case study text corrected after the reviewer pass (same-window figures, completed-case handoff denominators, pause-deduction share, reviewer findings) | latest case-study text |
| `ced8384` | Onboard Studio motion tile (scene and loop clips) ahead of its case study | precedes the release |
| `f03b26f` | Revenue Atlas case study: reviewer findings and fixes | **rollback commit** (manifest): the last state without Onboard Studio |

## Rollback procedure (not executed; nothing was committed or pushed by this package)
Per `CLAUDE.md`, work goes to the private remote on `unified-portfolio` only; the owner decides what reaches the public site.
1. `git switch unified-portfolio && git pull private unified-portfolio`
2. Revert the case-study text correction only: `git revert --no-edit a9d6b1d`.
3. Remove Onboard Studio entirely, newest first: `git revert --no-edit a9d6b1d b642b24 a614136 ced8384`; the tree should then equal `f03b26f` for these paths (check with `git diff f03b26f -- onboard-studio labs/onboard-studio`), then `python3 build.py` and confirm `index.html` and `all.html` no longer list it.
4. `git push private unified-portfolio` (never `origin`, never `main`). Verify with the live-check workflow after the owner publishes.
Use `git revert`, not a reset or force push, so history stays auditable.

## Main-portfolio metadata
| Field | Value |
|---|---|
| Title | Onboard Studio |
| Slug / case study | `onboard-studio` |
| Kind | Business data lab: decision-support analytics (synthetic data) |
| Tagline | Which onboarding workflow should be adopted, and how should exceptions be handled? |
| Tools | Python, PostgreSQL 16, FastAPI, TypeScript, React, Vite, Playwright, GitHub Actions, LibreOffice (workbook recalculation) |
| Evidence | Golden fixture (calendar 66 h, business 2 h, paused 65 h, active 1 h or 2 h), three-source reconciliation of business hours, 712 completed cases checked one by one between SQL and the Python domain, 279 local tests, 150 TypeScript golden checks, 35 Playwright tests, hosted CI runs in `technical-case-study.md` |
| Disclosure | Synthetic data; designed-in relationships (`data/injection-manifest.json`); static demo (case actions are browser simulations); open reviewer findings Q-01..Q-07; no real savings claimed |

## Artifacts and checksums (sha256; also `artifacts/CHECKSUMS.txt`, verifiable with `sha256sum -c artifacts/CHECKSUMS.txt` from `apps/onboard-studio`)
| File | sha256 |
|---|---|
| `artifacts/onboard-studio-analyst-workbook.xlsx` | `ee8c2946274080d980a85a7a544ce7f1d09d7309d1eaf451dc96dc06f2ef3a17` |
| `artifacts/analysis-results.json` | `c79dd3f99543b0da2a6eacf6118aab73ade934a35f6852d5866f2f0c1e43e102` |
| `artifacts/build_workbook.py` | `71275ff36cf22108e4894916a7a6c5d8506181770f0fadd997c709d84764be4a` |
| `artifacts/checksums.py` | `05a39c990932da6ab2d221917c4a29e2c1b178a21ee3db7f6db5f358a8fa7788` |
| `requirements-artifacts.txt` | `06d28d69e958deafb09f0a44fcae9b548f15e4debc14ebc39aad5f0934856fbf` |
| `data/sql/analysis/00_case_facts.sql` | `60e736b3faa76195393a3b31e1416d08dd430727032aa2e81f60fa1e00c5770a` |
| `data/sql/analysis/01_cycle_time_by_opening_month.sql` | `708f51b395b9c59413a9cf28eae015ba9d4fed7631e2bee9fc6022da53660515` |
| `data/sql/analysis/02_version_comparison_comparable_window.sql` | `28d4ae5f040194727052b5916044a2c8f31b2c23eb45137d6d14b76c4e5eefbc` |
| `data/sql/analysis/03_sla_by_segment_region.sql` | `322357754cab39140d5f0e2bc2ae8569262904adff0ca90781ac669bc6fbc22d` |
| `data/sql/analysis/04_step_waiting_by_step_assignee.sql` | `5c970a21395e03c2b4e40ec488f976312520ba69f21fd5539bdaded5b9834aee` |
| `data/sql/analysis/05_rework_first_pass_by_segment.sql` | `5671456caf87e8f9fdadc1e2e922757fd2d75deeb51368232155442f8c233e8c` |
| `data/sql/analysis/06_paused_time_by_reason_region.sql` | `752af00bdbda23c8c82306776c631242a3400f487f5c689c5fe295f250d0d159` |
| `data/sql/analysis/07_backlog_month_ends.sql` | `b45daa297585b2754ae90e2104f8534ced271f4af595cf1e1538689b24768367` |
| `data/sql/analysis/08_flags_and_rejections_by_reason.sql` | `b8326359f4421a767affe13ae3d129e844673fff7f9467097e45a3e3c2306573` |
| `data/sql/analysis/09_golden_case_business_hours.sql` | `e8c73b59f70cae61b267ee987eb44813ac2def0d5a07cb97fe98fb295cc2b149` |
| `data/sql/analysis/bi_fact_case.sql` | `54e44c346d9b202e38f9f3348d5271f75169a5e61c46e442357b1a3f18f217e3` |
| `data/sql/analysis/bi_fact_step_instance.sql` | `394d540ee1b4b03b4a290a6601b74798b71b990d63479f298b62c17a826ecd04` |
| `data/sql/analysis/prepare_snapshot.py` | `7b76172e2e382d764778d3dde60ed5e64ee6ffdec3bda7f46d39fd791bb724f9` |
| `data/sql/analysis/run_all.py` | `f5d32b2ae1f8f712fd4e952adc9879603889a96991f5e1a12393f9308826132f` |
| `tests/test_artifacts.py` | `724dc0cc371a3c22476617a12952774ec4813cb7994b84636fec6af00014b4a0` |
| `docs/data-dictionary.md` | `67508cc8ca1ec0312ae22ac12dc47416a5d45a3a39a3fd19518f45babf58c9bd` |
| `docs/erd.md` | `b0ecbecec826360ba606dc06f59a5b5026bfd145ac96d40b5dc7d21dcfe1b676` |
| `docs/sql-analysis.md` | `a6eb7c95f8f923469383e180db2d6f26d8ab2b36db1fe69889d8785b34662085` |
| `docs/workbook.md` | `f43e9b7dadc084ac0411b92991064fb5dea3cbb5867094e6010ee2442c2acd0f` |
| `docs/bi-package.md` | `a1aac2e6e7eee5b4c68c68593f99a2a45cb8d2cae411906ebd2ac764dafbeb69` |
| `docs/executive-memo.md` | `ac8e5f8f40cb407e190bb1b9e0f0035e3ebe31c2b6fba9bdfa7b12d3dc8e599a` |
| `docs/technical-case-study.md` | `525e6bda3b51a1666664c4d3da42e6f77d18eccda35dd5eec4fcaadeffdbe363` |
| `docs/resume-bullets.md` | `54d4e4a531a1c850d7ad51b5fa7f71f0269c9d75a24921383d1311459866fd30` |

`docs/release-package.md` is not listed: it carries these checksums, so it cannot contain its own. `artifacts/CHECKSUMS.txt` cannot list itself. `tests/test_artifacts.py` checks every line of `CHECKSUMS.txt` against the file and that this table contains the same digests.

## What each artifact is, and what was run
| Artifact | Requirement | What was run | Not run |
|---|---|---|---|
| `docs/data-dictionary.md`, `docs/erd.md` | P02-ART-03 | a test parses the 21 tables and every column of `0001_schema.sql` and checks each is in the dictionary and in the Mermaid diagram | the Mermaid diagram was not rendered in a viewer |
| `data/sql/analysis/*.sql`, `docs/sql-analysis.md`, `artifacts/analysis-results.json` | P02-ART-04 | all ten files with `psql -v ON_ERROR_STOP=1` (exit 0) and `run_all.py` (exit 0, 37 reconciliation rows equal); golden business hours 2.0000 from the analysis SQL, `reference_metrics.sql` and the Python domain | other databases or seeds |
| `artifacts/onboard-studio-analyst-workbook.xlsx`, `docs/workbook.md` | P02-ART-05 | formulas checked in `tests/test_artifacts.py`; recalculated by LibreOffice 24.2.7.2 headless, as delivered and with the pause switch flipped; chain re-derived in Python | **Microsoft Excel** |
| `docs/bi-package.md`, `data/sql/analysis/bi_fact_*.sql` | P02-ART-06 | the two export queries (733 and 3,665 rows); expected measure values computed from the exports | **Power BI Desktop; no `.pbix` produced, opened or tested; no DAX or M executed** |
| `docs/executive-memo.md` | P02-ART-07 | the headline figures of the comparison table are checked against `analysis-results.json` by a test | review by a real stakeholder |
| `docs/technical-case-study.md` | P02-ART-09 | the existing suite (279 passed), `reference_check.py` (ALL OK), `npm run check` (150 checks) | `npm run e2e` (Playwright) was not re-run; its result is the ledger's |
| `docs/resume-bullets.md`, this file, `CHECKSUMS.txt` | P02-ART-10 | bullet count and wording checked by a test | |

## Reproduce
```sh
cd apps/onboard-studio
../../.venv/bin/pip install -r requirements.txt -r requirements-artifacts.txt
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<empty snapshot db> GOLDEN_DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<empty golden db>
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py && DATABASE_URL=$GOLDEN_DATABASE_URL ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json
../../.venv/bin/python artifacts/build_workbook.py --recalc
ARTIFACTS_DATABASE_URL=$DATABASE_URL ../../.venv/bin/python -m pytest -q tests/test_artifacts.py
../../.venv/bin/python artifacts/checksums.py
```
`run_all.py` and `prepare_snapshot.py` reset the project's tables in the database they are given: use scratch databases, not one that holds other work.
