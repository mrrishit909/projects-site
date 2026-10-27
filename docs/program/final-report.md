# Business Data Lab: final report (2026-10-27)

All ten projects are built, verified, published, integrated into the portfolio, independently reviewed with confirmed defects
fixed, and carry an analyst artifact package whose tests run on GitHub-hosted runners. Every site is live and was verified from a
GitHub Actions runner (run 40486882515: deploy wait on the published `code_sha`, route status codes, case-study links both
ways, a browser journey) at the close of the programme. Ledgers: `program-status.json`, `task-queue.json`,
`delegation-ledger.jsonl` (82 assignments), `verification-ledger.json` (142+ entries), `release-manifest.json`.

## Where things live

* Monorepo: branch `business-data-lab` of `mrrishit909/projects-site` (head 8b297bf at the time of this report), one app per
  project under `apps/<slug>/`, CI workflows under `.github/workflows/<slug>-ci.yml` and `live-check.yml`.
* Published sites: `labs/<slug>/` on branch `unified-portfolio` (GitHub Pages), with the case studies at
  `https://mrrishit909.github.io/projects-site/<slug>/` and the catalogue entries on the home and archive pages.
* A dedicated repository could not be created (BLK-001: the GitHub App lacks repository-creation permission); the orphan
  branch is the recorded substitute. `*.github.io` is unreachable from the cloud container (BLK-002), so every live check runs
  on a hosted runner.

## The ten sites

| # | Project | Live site | Release (unified-portfolio) | Source (business-data-lab) | Review | Artifacts CI |
|---|---|---|---|---|---|---|
| 01 | Revenue Atlas | https://mrrishit909.github.io/projects-site/labs/revenue-atlas/ | f2605bb | 50e72e1 | fixed | delivered |
| 02 | Onboard Studio | https://mrrishit909.github.io/projects-site/labs/onboard-studio/ | 239950e | 1a27a0e | fixed | delivered |
| 03 | SupplyScope | https://mrrishit909.github.io/projects-site/labs/supplyscope/ | 13af835 | ca3e626 | fixed | delivered |
| 04 | ServiceFlow | https://mrrishit909.github.io/projects-site/labs/serviceflow/ | fec6758 | 2a6578e | fixed | delivered |
| 05 | InvoiceBridge | https://mrrishit909.github.io/projects-site/labs/invoicebridge/ | 188e409 | 2dcc460 | fixed | delivered |
| 06 | ProductSignal | https://mrrishit909.github.io/projects-site/labs/productsignal/ | e360bf1 | fdf911a | fixed | run 40441332040 |
| 07 | TrustLedger | https://mrrishit909.github.io/projects-site/labs/trustledger/ | e205202 | 0b5d686 | 8 defects fixed | run 40454781567 |
| 08 | Pipeline Observatory | https://mrrishit909.github.io/projects-site/labs/pipeline-observatory/ | d58209f | b326690 | 8 defects fixed | run 40480929146 |
| 09 | ChangeWorks | https://mrrishit909.github.io/projects-site/labs/changeworks/ | 8b9bcd3 | 29948f9 | 14 defects fixed | run 40486164950 |
| 10 | RetentionLab | https://mrrishit909.github.io/projects-site/labs/retentionlab/ | cf04a0e | c17fa32 | 3 defects fixed | run 40476210083 |

Per-site details (rollback commits, dataset hashes, published tree digests, live-verification runs, previous releases) are in
`release-manifest.json`.

## What every project has

* A known-answer fixture written before the code, with a standard-library reference script that recomputes it from the records.
* A pure-Python domain (decimals and exact rationals for money), PostgreSQL migrations with database-level guards, a FastAPI
  command and read surface (idempotency keys, 401/403/409/422 contracts, server-stamped instants, header-asserted identity,
  no authentication, stated as such), and an independent SQL recomputation of the metrics.
* A deterministic synthetic world with a published injection manifest and designed relationships; every page carries demo-mode
  labels, and nothing live is fabricated.
* A TypeScript mirror of the domain and a static React site with per-route pages, golden and review checks against the
  Python domain, and Playwright evidence at 360, 768, 1280 and 1920 px plus 200 % zoom.
* CI on GitHub-hosted runners only: Mode A (reference check, tests against a transient PostgreSQL 16 service, artifact tests on
  `artifactsNN_*` scratch databases with LibreOffice recalculation, a junit no-skip gate) and Mode B (build, golden check,
  browser evidence).
* An independent disproof review (opus) whose confirmed defects were fixed in code and whose false case-study claims were
  corrected on the live page first, then followed by the "Found by review, then fixed" paragraph.
* An analyst artifact package: SQL investigations reconciled row by row against the domain, the fixture and the published
  files; a formula-driven workbook recalculated by LibreOffice; a BI package of CSV facts and dimensions; business case,
  requirements traceability, data dictionary, ERD, executive memo, technical case study, release package with checksums,
  résumé bullets and UAT evidence.

## Honesty notes

* Models: delegations requested `sonnet` (70), `opus` (11) and the coordinator's own model (1). The served model is not
  observable from the Agent tool; two completion notices (A-080, A-081) reported a switch to Opus 5.5 because the requested
  model could not be used, and the ledger says so.
* One worker at a time was the rule; overlaps happened and each is recorded as a deviation in the delegation ledger.
* Workbooks were built in CI on hosted compute for the tests but are not attached to GitHub releases; Excel and Power BI
  Desktop were never run and no `.pbix` exists; DAX in the BI documents is unexecuted.
* Three container restarts (BLK-003..005) lost workers mid-task; each was resumed and accepted.
* Two CI failures were caused by order-dependent assertions on random ids or locale collation and were fixed at the root
  (never by skipping or weakening a test); one Mode B re-run cleared a navigation-abort flake and the watcher was hardened in
  every app.
* Known gaps are stated on each case study under "Not built yet" (for example resource levelling in ChangeWorks, the
  randomised experiment in RetentionLab, delete events in the Pipeline Observatory reference SQL).
