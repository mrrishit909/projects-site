# Release package (P04-ART-10)

ServiceFlow, business-data-lab project 04. **Synthetic data only**; nothing here is a claim about a real support team, real tickets, service levels or savings. Observed, simulated and hypothetical results are kept apart in every artifact: the site and the analysis show observed behaviour of a synthetic history; the memo's scenarios are simulated estimates; no hypothetical benefit is claimed.
Facts below are copied from `../../docs/program/release-manifest.json` (updated 2026-10-26T18:12:13Z) and `verification-ledger.json`; the release and rollback commits were also looked up read-only with `git log` / `git cat-file` in this worktree. This package did not fetch `github.io` and **committed and pushed nothing**:
the artifact files listed below are uncommitted files in the worktree (`CLAUDE.md`: work goes to the private repository's `unified-portfolio` branch only; the owner decides what reaches the public site).
How to read it without installing anything: the tables are the manifest; the commands are listed for anyone who wants to reproduce a figure.

## Where it lives
| Item | Value |
|---|---|
| Site URL | https://mrrishit909.github.io/projects-site/labs/serviceflow/ |
| Portfolio case study | https://mrrishit909.github.io/projects-site/serviceflow/ (`/serviceflow/project.json` on `unified-portfolio`) |
| Source | https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/serviceflow (branch `business-data-lab`; manifest `source_commit_business_data_lab` `43de7f8`, contract v1) |
| Dataset | `sf-20261026-20261026`, generator `dataset_hash` `944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4` (seed 20261026, 3 queues, 18 agents, 3,826 tickets published and 3,817 accepted, 12 weeks from 2026-07-06) |
| Published tree | 45 files under `labs/serviceflow/`, sha256 `b5a33b9681eb0319a9c092bfc83e29b37d333c4bc836e784815eaab7a614f445` (manifest) |
| Live verification | https://github.com/mrrishit909/projects-site/actions/runs/40367109366 (all jobs success, 2026-10-26T17:18:16Z) was for the **first** release (`e3bd4a4`, code `6a753e8`); for the republish the manifest's `live_verification.run_url` is `null` ("CI and live check pending") |
| Hosted CI | https://github.com/mrrishit909/projects-site/actions/runs/40364940392 (Mode A and Mode B success; 296 TypeScript golden checks and 65 Playwright tests; code `6a753e8`); none recorded yet for `43de7f8` |
| Status | built, published (republished after the reviewer fixes, `e44d15d`) and integrated; **live verification and a hosted run of the fixed code are pending**, so the verification of the current release is local only until they are recorded |

The four release fields are kept separate (P04-REL-20): **built** yes (`python3 build.py` at the portfolio root writes the case study and catalogue); **verified** locally at `43de7f8` (`uat-evidence.md`: `reference_check.py` ALL OK, 377 passed, 303 golden + 54 review checks, 70 e2e) and on hosted runners for `6a753e8` only; **published** commit `e44d15d` on `unified-portfolio`; **integrated** the portfolio case study and the site link to each other (verified both ways for `6a753e8`, run 40367109366; not re-verified for `e44d15d`).

## Release and rollback commits (branch `unified-portfolio`)
| Commit | What it is | Role |
|---|---|---|
| `e44d15d` | ServiceFlow: republish after the reviewer fixes; case study updated with the replication intervals and the fixed findings | **release commit** (manifest) |
| `60e8838` | ServiceFlow case study: correct the reference-check count and the wait, abandonment, SLA and simulation wording after the independent review | between the two (git history) |
| `e3bd4a4` | ServiceFlow: publish the site under `labs/serviceflow` and add its case study (cover, shift grid and SLA shots) | **rollback commit** (manifest): the previous release, live-verified by run 40367109366 |
| `13af835` | Archive rebuilt with the SupplyScope row | the last `unified-portfolio` state without ServiceFlow (the parent of `e3bd4a4`) |

Rollback manifest (copied from the release manifest; nothing was executed):
```json
{"slug": "serviceflow", "release_commit_unified_portfolio": "e44d15d", "rollback_commit_unified_portfolio": "e3bd4a4",
 "source_commit_business_data_lab": "43de7f8", "published_tree_sha256": "b5a33b9681eb0319a9c092bfc83e29b37d333c4bc836e784815eaab7a614f445",
 "files": 45, "dataset_version": "sf-20261026-20261026", "contract_version": "v1", "previous_run_url": "https://github.com/mrrishit909/projects-site/actions/runs/40367109366"}
```

## Rollback procedure (not executed; nothing was committed or pushed by this package)
Per `CLAUDE.md`, work goes to the private repository's `unified-portfolio` branch only (the worktree's single remote `origin` is `https://github.com/mrrishit909/projects-site`, the private repository `CLAUDE.md` calls `private`); never the public repository, never `main`.
1. `git switch unified-portfolio && git pull` (the private remote).
2. **Back to the previous release (the manifest's rollback):** `git revert --no-edit e44d15d 60e8838` (newest first; confirm each hash with `git log` first), then check `git diff e3bd4a4 -- serviceflow labs/serviceflow` is empty, then `python3 build.py` and confirm the home page, `all.html` and the case study show the first release.
3. **Remove ServiceFlow entirely:** additionally `git revert --no-edit e3bd4a4`; the tree should then equal `13af835` for `serviceflow/` and `labs/serviceflow/` (`git diff 13af835 -- serviceflow labs/serviceflow`), then `python3 build.py` and confirm the entry is gone from `index.html` and `all.html`.
4. Push to the private `unified-portfolio` only; verify with the live-check workflow after the owner publishes.
Use `git revert`, not a reset or force push, so history stays auditable.

## Main-portfolio metadata (from `/serviceflow/project.json`)
| Field | Value |
|---|---|
| Title | Which Staffing or Routing Change Meets Support Targets Under Uncertain Workload? |
| Slug / case study | `serviceflow` |
| Kind | Dashboard · Operations analytics · FastAPI · React (business data lab project 04, synthetic data) |
| Tagline | ServiceFlow: a support queue reconstructed from its event log; FIFO within priority, waits from the original arrival, breaks deducted from staffed time, SLA compliance with open overdue counted separately, P90 beside the mean, and a seeded queue simulator that reproduces the known answer before any random arrival |
| Tools | Python 3.11, PostgreSQL 16, FastAPI 0.162, SQL reference recomputation, TypeScript, React 18, Vite, Playwright 1.55, GitHub Actions; for the artifacts openpyxl 3.1.5 and LibreOffice (recalculation) |
| Evidence | 377 Python tests, 303 TypeScript golden checks, 54 review checks, 70 browser tests; hosted CI and live-check runs for the first release (above); this package: 185 reconciliation rows between eight SQL investigations, an independent SQL reference and the Python domain |
| Demo / repo | https://mrrishit909.github.io/projects-site/labs/serviceflow/ and https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/serviceflow |
| Disclosure | Synthetic data; designed-in relationships and nine injected defects published in `data/injection-manifest.json`; static demo (the simulator runs in the browser and nothing is persisted); simulated estimates labelled as estimates; C07 and C10 return 501 and three screens are stubs; the +20 % holdout is a chosen realisation; no realised staffing benefit claimed |

## What this artifact pass ran (2026-10-26, scratch databases `artifacts04_*`; never the shared `serviceflow` database for its own work)
| Command | Exit code | Result |
|---|---|---|
| `data/sql/analysis/prepare_snapshot.py` (snapshot) and `--golden`, into `artifacts04_snapshot` and `artifacts04_golden` | 0 and 0 | snapshot: 3,817 tickets, 21,893 events, 2,147 surveys, 70 rejected rows kept, 1,018 breaks loaded; golden: 3 tickets |
| `psql -v ON_ERROR_STOP=1 -f` `00_event_views.sql`, each of `01..08`, `bi_dimensions.sql`, `bi_fact_*.sql` (snapshot) and `00`, `09_golden_known_answer.sql` (golden) | 0 for each of the 15 runs | no error |
| `data/sql/analysis/run_all.py` (no environment: creates and drops `artifacts04_run_snapshot` and `artifacts04_run_golden`) | 0 | `RESULT: OK (185 reconciliation rows, 185 equal)` |
| `run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi`, run twice | 0 and 0 | `RESULT: OK` with 185 rows; the JSON and the 11 CSV files are byte-identical on the second run |
| `artifacts/render_sql_analysis.py` | 0 | `docs/sql-analysis.md` and `docs/bi-package.md` tables rendered from the stored results |
| `artifacts/build_workbook.py --recalc` (LibreOffice headless) | 0 | workbook built, recalculated, `fullCalcOnLoad` restored |
| `artifacts/checksums.py --table` and `sha256sum -c artifacts/CHECKSUMS.txt` | 0 and 0 | 51 files, all OK |
| `pytest -q tests/test_artifacts.py` with `ARTIFACTS_DATABASE_URL` and `ARTIFACTS_GOLDEN_DATABASE_URL` set (includes three LibreOffice recalculations of copies: as delivered, training, holdout) | 0 | 37 tests passed in about 70 s |
| `DATABASE_URL=... pytest -q` (the whole app suite, plus the two `ARTIFACTS_*` URLs) | 0 | **414 passed** in 179 s: the 377 of the existing suite plus 37 new |
| `python tests/reference_check.py` | 0 | `ALL OK` (hashes unchanged) |

Not run: Microsoft Excel (the workbook was recalculated by LibreOffice only), Power BI Desktop and any DAX engine (no `.pbix` exists), `npm run e2e` / `npm run check` / the hosted workflows (the browser and hosted evidence are the earlier recorded runs), and a hosted run of `tests/test_artifacts.py` (it is not part of `serviceflow-ci.yml`).

## Artifacts and checksums (sha256; also `artifacts/CHECKSUMS.txt`, verifiable with `sha256sum -c artifacts/CHECKSUMS.txt` from `apps/serviceflow`)
<!-- BEGIN:checksums -->
| File | sha256 |
|---|---|
| `artifacts/analysis-results.json` | `8cca586a04f5c737ffdf6495219161a36c83d456e56fd788a50461d274afcfee` |
| `artifacts/bi/dim_agent.csv` | `0ae026e0380134bcb34c3380d216efb51c52721815a339a21f953c7f982fa942` |
| `artifacts/bi/dim_channel.csv` | `9b7fd63b1eca54110cadba905dffd81fb01b2f0e00f734c0643f7fc1884636a3` |
| `artifacts/bi/dim_date.csv` | `67b05d2a8f0deaef1803cce376d7e76b348296ffd25d5a4201f0ce06cb26f139` |
| `artifacts/bi/dim_priority.csv` | `39b4ce7c441865610108bad419471b3d5c2bd408992abb5cb91785fde767f3eb` |
| `artifacts/bi/dim_queue.csv` | `1004471e9858e86603d921fc02633438bc7f65c62ad391daed403e0bc43784c0` |
| `artifacts/bi/dim_simulation_run.csv` | `fb508babb9dfa777857ed7a7d5280649844e8f32ab8d1e0ad73203a4e1bb646a` |
| `artifacts/bi/fact_service_interval.csv` | `b827aab01f3d65ad09a352d411ff8cb972aa3a0287d0b1c63a932c294642a327` |
| `artifacts/bi/fact_shift.csv` | `ef838fa04106b8d187d3076d13e061146b6cc5430e3eea7f56a8123c46790b90` |
| `artifacts/bi/fact_simulation_replication.csv` | `d5d43ca2177ebdb74373a9610e3292d6664625076fdb34ad80d997b577780edb` |
| `artifacts/bi/fact_survey.csv` | `98b9e49ebf3fe687fbf28ba0910df3e73fb58d63808431fe60212809dca9f30f` |
| `artifacts/bi/fact_ticket.csv` | `98673de62155203eddefe6342681e1cfd2c3e646cec98494bf0a38d33d36308a` |
| `artifacts/build_workbook.py` | `ad862adc77a6aef6c86ce91bf45a77bdb2a726ff371e9c441137e5d08cf29ff6` |
| `artifacts/checksums.py` | `5add1f6ddd67096bf1d712cca7c46a0b945aad902510111606367f26ed62bd11` |
| `artifacts/render_sql_analysis.py` | `a2fd0d544afc4d570b59d4f65f17a6438a5cb6af614fc3a9f5debe9958cdcedb` |
| `artifacts/serviceflow-analyst-workbook.xlsx` | `49281ab1d40523d472ead6858c8317b2494fa777b6f3c3f9db1cfef081977158` |
| `data/sql/analysis/00_event_views.sql` | `1dc30b233b0c3ec68aa05cc9ad71537e1161b04f28b4ea0c69fa258ac2897b93` |
| `data/sql/analysis/01_arrivals_by_hour_of_week.sql` | `9fd73805ccb1a8de117deaac3019fd1f996b5d099332d63356332d0d12ae1e4f` |
| `data/sql/analysis/02_wait_and_response_distributions.sql` | `1cbe7544cc957f7b5827c43c83ae15ffa7f7057d46871feb47ff72058e45aee7` |
| `data/sql/analysis/03_sla_compliance_and_open_overdue.sql` | `16a20351a997682ebb1c852ad4cdfd053bd5505e27b8a47dcbad4c6fdb1299ea` |
| `data/sql/analysis/04_occupancy_by_agent_and_shift.sql` | `d8de0a889e572bcf85e5ff5ec45363899392f37149a5330e59018364a8c0166c` |
| `data/sql/analysis/05_transfer_and_reopen_effects.sql` | `9fa75fa3d927092e84dc3535363d408e89ebd44092b1f4a8b587d05095a011ec` |
| `data/sql/analysis/06_abandonment_by_channel_and_patience.sql` | `43c28a9a7598ed0902100f0b360e833af935f43c6fe19e5d3c1f339c0d2329f6` |
| `data/sql/analysis/07_survey_response_skew.sql` | `8f85b0fa74c71507e8ea9b37d0d9e2a2567df7e729406a3086f5817b20250476` |
| `data/sql/analysis/08_rejections_and_defects_by_reason.sql` | `eac10d7838c3772ed87b11a8f2c0f0c39bbf5146a3c4a9a51f209a05543ec6b3` |
| `data/sql/analysis/09_golden_known_answer.sql` | `712732a76260197b47cd0218ffafba48f0479045444a2c9aa38ead435ec5161c` |
| `data/sql/analysis/bi_dimensions.sql` | `c2209f3eb07825958ee58208c857234d036f7b5cc3605873e499a02afea08a80` |
| `data/sql/analysis/bi_fact_service_interval.sql` | `eb2bfc1ca5338019aa4110b7d33b4a7e27ae51b8cdc1d43e576d27fa61348bf6` |
| `data/sql/analysis/bi_fact_shift.sql` | `d2f6829e97847eb02daa213e25f71453d1f23794921862af60711cec260e9d62` |
| `data/sql/analysis/bi_fact_survey.sql` | `d3e56c9f9fc6e45fba7df3b002be9bd48940af959830be0188bc8b3f58754779` |
| `data/sql/analysis/bi_fact_ticket.sql` | `2274493fc659978ee06774080e3b6c9893f13562fdce07429535d61d9aedadb7` |
| `data/sql/analysis/prepare_snapshot.py` | `89796b9ae9f596c96850467fcfecf97a23ddedb89b11401c2ce02d4861787398` |
| `data/sql/analysis/python_side.py` | `1a10447092248722c8b736d8ff41bdd0c8d951939185668824ba6561673c6a06` |
| `data/sql/analysis/run_all.py` | `917a50272b83cbb3bb59dcbf08365ad35ab67662a7aee53171df6c3cc9a6fcd6` |
| `docs/api-contract.md` | `dd60a6c7bb669900ada9f63b79a2e757f847206bb94926ab72f3266d91f16e74` |
| `docs/bi-package.md` | `2d772b3e56718c1f9ec8b564f087256ed57d4ae43ed0293e0195512f71514299` |
| `docs/business-case.md` | `95957029be178a83aab6fcec618a01d191280f4710c85ca53c82c64ec814a417` |
| `docs/contracts.md` | `bbff2ff1489b81e5e987830ae192c02baa2e38cb0ef44b9978b787a570124c75` |
| `docs/data-dictionary.md` | `38158bc5c1fd9398fc75c854dde663be310d85a03906efb748c352c74821ea67` |
| `docs/data-generator.md` | `9a8bc60a4fddcdb685b7598eb853f9fd690f3a9bb619bf451f9a0129f51f31fc` |
| `docs/erd.md` | `57058fec27b92a2fddfc97e49273097d70c6315f0b052c4fccae5fef338f1424` |
| `docs/executive-memo.md` | `ad757f1b1d1a6fa65d0099d2e6d9269945b8d95e623c1b7cda1001991dc39cb6` |
| `docs/requirements.md` | `dcb53805e75d9547e7e90fb1f75975d57590656a63f81067ee06c8efdf00cbe2` |
| `docs/resume-bullets.md` | `288af3acb0331756b6f387e1f79b3fe4e6982e25b27a1bd6abf99428172617ae` |
| `docs/sql-analysis.md` | `af28d3aea3e99087c8ad03b107cb70cf0d19b415470b60164633c405721dec1c` |
| `docs/technical-case-study.md` | `78c7d1146078d1ccb0036a748066177d73cac6b1d85b5726bab07f4bd18f4636` |
| `docs/uat-evidence.md` | `05582a9d1e8f8f966c63389e0e004c842be249749a7430e57c95359f9514c8c4` |
| `docs/web-brief.md` | `803ea343d39105e7af233c119422c78b2e02f420af0a3012c9c4cdce05830ce2` |
| `docs/workbook.md` | `fd59448fcb1a06df003da8e45303fd0d8909bc9d30e19d9c655b9cf7cf32f6e7` |
| `requirements-artifacts.txt` | `06d28d69e958deafb09f0a44fcae9b548f15e4debc14ebc39aad5f0934856fbf` |
| `tests/test_artifacts.py` | `7d2fd67040a379b0fa22d1434c61780817578113f00e6405cdc57d429d18e12d` |
<!-- END:checksums -->

`docs/release-package.md` is not listed: it carries these checksums, so it cannot contain its own. `artifacts/CHECKSUMS.txt` cannot list itself. The screenshots in `web/evidence/` are git-ignored (see `uat-evidence.md` section 1) and are not listed. Regenerate both with `../../.venv/bin/python artifacts/checksums.py --table` after any change to a listed file.

## Known limits of the package
* The workbook replays no events (per-ticket instants are typed from the domain's replay) and its `Domain reference` and `SQL results (pasted)` sheets are pastes; Excel was not run.
* The BI package is a design (DAX-like pseudocode, CSV exports); its expected values were computed in Python over the exports and reconciled to SQL and the domain; there is no `.pbix`.
* The analysis is one seed over a synthetic history; the simulation is a single-queue, dedicated-server model at the Monday bind intensity for twelve hours; its improvement is an estimate with a 95 % interval over 50 replications, not a realised benefit.
* `docs/data-dictionary.md` row counts are from the scratch snapshot database, not from a shared database; `dataset_versions` holds the seed's input hash (`d5d7a5e1b7df...`), which is not the generator's file hash.
* The republish `e44d15d` (code `43de7f8`) is verified: hosted CI run https://github.com/mrrishit909/projects-site/actions/runs/40375493599 (both modes green) and live check run https://github.com/mrrishit909/projects-site/actions/runs/40376659299 (live manifest carries the release commit; 11 routes; links both ways).
