# Release package (P01-ART-10)

Revenue Atlas, business-data-lab project 01. **Synthetic data only**; nothing here is a claim about a real company, revenue or savings. Facts below are copied from
`../../docs/program/release-manifest.json` (updated 2026-10-26T11:15:55Z) and `verification-ledger.json`, and checked against `git log` of `unified-portfolio` (read-only).

## Where it lives
| Item | Value |
|---|---|
| Site URL | https://mrrishit909.github.io/projects-site/labs/revenue-atlas/ |
| Portfolio case study URL | https://mrrishit909.github.io/projects-site/revenue-atlas/ |
| Source | https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/revenue-atlas (orphan branch `business-data-lab`; manifest `source_commit_business_data_lab` `a9d7d21c350a818320fe29dc5d3a313acceebbfa`, contract v1.1) |
| Dataset | `ra-20261026-20261026`, `dataset_hash` `40f541fcd8681eb056f408b40d03ad941e4ef797fc4ea5283e1412a02bc6f444` |
| Published tree | 38 files under `labs/revenue-atlas/`, sha256 `5e89722301518793abfa282556d0e0004edabeeb8d1f922d89029e6347999c76` (manifest) |
| Live verification | https://github.com/mrrishit909/projects-site/actions/runs/40310810960 (200 on 7 URLs, served hash equals manifest, 0 console errors, 2026-10-26T10:53:16Z); portfolio link both ways: https://github.com/mrrishit909/projects-site/actions/runs/40313778038 |
| Not re-checked here | This environment cannot reach `github.io` (program blocker BLK-002), so the URLs above were not fetched by this package; the ledger runs are the evidence. |

## Release and rollback commits (branch `unified-portfolio`, from the manifest, order confirmed by `git log`)
| Commit | What it is | Role |
|---|---|---|
| `92b9c66` | Republish Revenue Atlas (contract v1.1, static portfolio back-link): 15 files under `labs/revenue-atlas/` | **release commit** |
| `954f7fb51d2fb5253db2aa4f75f05961cbe46932` | Add Revenue Atlas case study, cover, motion tile; catalogue (`index.html`), archive (`all.html`) and two neighbouring project pages rebuilt | **rollback commit** (the state before the v1.1 republish) |
| `cdae3f271d81df8e42e98eefb2cfdd4ca5fc1fb1` | Publish Revenue Atlas static site at `labs/revenue-atlas` (38 files) | previous release |

## Rollback procedure (not executed; nothing was committed or pushed by this package)
Per `CLAUDE.md`, work goes to the private remote on `unified-portfolio` only; the owner decides what reaches the public site.
1. `git switch unified-portfolio && git pull private unified-portfolio`
2. Back to the previous release (undo the contract v1.1 republish): `git revert --no-edit 92b9c66`. The tree then equals `954f7fb`.
3. Remove the site entirely: also `git revert --no-edit 92b9c66 954f7fb cdae3f2` (newest first; the `labs/` tree goes with `cdae3f2`, the catalogue, archive and case study entries with `954f7fb`), then `python3 build.py` and check that `index.html` and `all.html` no longer list Revenue Atlas.
4. `git push private unified-portfolio` (never `origin`, never `main`). Verify with the live-check workflow after the owner publishes.
Use `git revert`, not a reset or force push, so history stays auditable.

## Main-portfolio metadata
| Field | Value |
|---|---|
| Title | Revenue Atlas |
| Slug / case study | `revenue-atlas`, https://mrrishit909.github.io/projects-site/revenue-atlas/ |
| Kind | Business data lab: decision-support analytics (synthetic data) |
| Tagline | Which customer, product, region or discount policy explains declining contribution margin? |
| Tools | Python, PostgreSQL 16, FastAPI, TypeScript, React, Vite, Playwright, GitHub Actions |
| Evidence | Golden fixture (net 225.00, contribution 70.00; 40.00 after return), snapshot reconciliation to the cent (3,309,826.22), 109 local tests, hosted CI runs in `technical-case-study.md` |
| Disclosure | Synthetic data; designed-in relationships (`data/injection-manifest.json`); static demo; no real savings claimed |

## Artifacts and checksums (sha256; also `artifacts/CHECKSUMS.txt`, verifiable with `cd apps/revenue-atlas && sha256sum -c artifacts/CHECKSUMS.txt`)
| File | sha256 |
|---|---|
| `artifacts/revenue-atlas-analyst-workbook.xlsx` | `4b9415c112f0bdeb3b4b00a20dc64fbc1cffb07b0cedc02efafb814b17d2fc1b` |
| `artifacts/analysis-results.json` | `2436b45e0291f6f1d06352ef14ac725123c0a3f7218786173ff24bec194a10bc` |
| `artifacts/build_workbook.py` | `9cec28aec00e7f9c34e3665ea5fb835c8a2c1e07d8ad89ba47e93d21e765ed70` |
| `artifacts/checksums.py` | `ed3d9600cb6032210e6ec8461467126a9738ccca552c3f54b6599155b3bfabb7` |
| `requirements-artifacts.txt` | `06d28d69e958deafb09f0a44fcae9b548f15e4debc14ebc39aad5f0934856fbf` |
| `data/sql/analysis/00_line_facts.sql` | `af7b2ea539ac4a08895f02a1000907003a977fada495bcc249559fddca233a07` |
| `data/sql/analysis/01_margin_bridge_by_month.sql` | `fbd651519459075f4ccd2a9649921499de5a36a38f1f3cced78996e35e4724d5` |
| `data/sql/analysis/02_contribution_by_region.sql` | `6a0676f688ccc182c86243a7ed69d5d16a883fb5605cb5f868f8e3fcabeb9ca8` |
| `data/sql/analysis/03_discount_rate_by_region_before_after_2026_03.sql` | `a9698f7a1d11519a0945dae622c235115e71de9a9662ddf2f3ce4d77474697e1` |
| `data/sql/analysis/04_fixtures_cost_vs_price_by_month.sql` | `d1bc5488c93352eb6e440960c3ba7bc6deea89381a14d30c264759309ecbffb6` |
| `data/sql/analysis/05_return_rate_by_segment_category.sql` | `665623c6a420a104488f1761177bd34a09bdbfc425c7fd74761803d9615a9408` |
| `data/sql/analysis/06_top10_customers_contribution_decline.sql` | `d6e0ae83413fb959ce116c5e92e0732ec990733ba0f1d0dff08de65a21cb3d44` |
| `data/sql/analysis/07_quarantine_reasons.sql` | `baeb894e57ef7e5737a78ee4435e10c867236d77a3260da5763798dd9cbe1649` |
| `data/sql/analysis/08_allocation_residual_check.sql` | `6905debd1ac3f0d0859cbcad92f6a4dc4b07fa2f7c87dc5e278204772436a4e3` |
| `data/sql/analysis/09_stored_vs_contract_freight.sql` | `3cb54db749b1a39431c96b96e80c0d4aa8b889d67a32749c4f5e7eada73e0243` |
| `data/sql/analysis/prepare_snapshot.py` | `c8cf27be12dd41ca3c171b36f0ebe4ca7a6a12f84f04d376b0f635d42e2559b0` |
| `data/sql/analysis/run_all.py` | `7a7a5b249610e587dd3ff2e85b918a6413be090910d6b8ee00caf2de7f1c2746` |
| `tests/test_artifacts.py` | `1fa5504de41b10709ea33abc5cbed373473dcf2e6571f7af1540db5795aa4e9b` |
| `docs/data-dictionary.md` | `c0aa0019c6822a5d863a7318b6ebcc8ac34a8de7bad618f44496cf304d38f9f6` |
| `docs/erd.md` | `183a4eae56633cc3117a0bc30c6295e15383c4a14f18d2108e60e5a0554feef7` |
| `docs/sql-analysis.md` | `8f5c5479afed2a84689b5b0749439d71fa617c1d7fcf83959aad55059554baf9` |
| `docs/workbook.md` | `853252f25c0cd871b6cbb3821eb26ac6b49b329860975174f8d1296efb927dc0` |
| `docs/bi-package.md` | `e05d992d8d8d2e63e0982b231872093612b4c03465ea93e344a98d7a768f75d0` |
| `docs/executive-memo.md` | `32cf414b975b088343dedeb807f4372bd10f3119ab1de6df86669501727b2e4c` |
| `docs/technical-case-study.md` | `d38713fe5ea6c80cd430395f5808b575896f38f7f2d873b720561690f5235811` |
| `docs/resume-bullets.md` | `a33221a2dbc7bd20e5644fbdab16e1a81f539a754932cb89756b38d6c31b6866` |

`docs/release-package.md` itself is not listed (it carries this table). Regenerate after any edit: `../../.venv/bin/python artifacts/checksums.py`; `tests/test_artifacts.py::test_checksums_file_matches_files` fails on a stale line.
The `.xlsx` hash is that of the LibreOffice-recalculated file (`workbook.md`). No `.pbix` exists, so none is listed (`bi-package.md`).
