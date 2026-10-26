# Technical case study: Revenue Atlas (P01-ART-09)

A synthetic revenue-analytics product built to one question: which customer, product, region or discount policy explains declining contribution margin. All data is generated; no result here describes a real business.

## Architecture
```mermaid
flowchart LR
  G[generate.py seed 20261026] --> S[(web/public/data snapshot JSON)]
  S --> TS[Mode B: TypeScript domain in the browser]
  S --> SEED[data/seed.py]
  SEED --> PG[(PostgreSQL 16 plain SQL migrations)]
  API[FastAPI C01-C04 + reads] --> PG
  PY[Python domain: pipeline, metrics] --> API
  PG --> REF[reference_totals.sql independent SQL]
  TS --> PAGES[GitHub Pages static site]
```
* **Mode A (verified on hosted runners):** Python domain (`domain/revenue_atlas`), PostgreSQL migrations (`data/migrations`), FastAPI commands C01 ingest, C02 resolve cost, C03 partial return, C04 allocate freight, and reads (`/data/{entity}`, `/metrics`).
* **Mode B (public):** the same contract in TypeScript (`web/src/domain`) over the published snapshot; mutations stay in browser memory. Static hosting only; the backend is not deployed.
* One contract (`docs/contracts.md`, v1.1, decisions D-01..D-07) with a golden fixture whose answers are hand-derived (`tests/fixtures/golden/CALCULATION.md`).

## Tradeoffs
* **Three implementations of one contract** (Python pipeline, SQL reference, TypeScript). Cost: three places to change per rule (the v1.1 change touched all three). Benefit: they check each other. Observed on the whole snapshot (A-010 run): the SQL view, `reference_totals.sql` and the Python `run_pipeline` give identical gross, discounts, credits, net, COGS, gross profit, shipping and contribution (3,309,826.22), and the TypeScript golden check passes 175 checks. The SQL reference deliberately does not read the allocation tables and carries its own largest-remainder logic, so a shared bug is less likely.
* **Decimal strategy.** Money is `Decimal` in Python, `NUMERIC(20,6)` in PostgreSQL, decimal strings in JSON, a decimal type in TypeScript; never binary floats. Rounding to cents happens at two steps only: allocation and presentation (D-02). Cost: grouped sums can disagree by cents when each group rounds separately (review R-05); the ungrouped total is exact.
* **Allocation.** Discount and freight are split to the shipment line in integer cents by largest remainder, ties to the lowest `shipment_line_id` (D-04), so every dollar belongs to one line and margin attribution is exactly additive. Alternative (proportional float split) rejected: residuals. A zero-gross shipment falls back to quantity weights. The primary key on `freight_allocations.shipment_line_id` is the double-allocation guard.
* **Quarantine, not defaults.** A line with a missing FX rate or zero/several cost versions is excluded and counted, never filled with 1.0 or 0 (D-02, D-03). Cost: totals shrink by the quarantined lines (snapshot: 56 lines, 42,742.55 + 5,205.01 of gross at stake for the cost reasons); benefit: no silent wrong total. `quarantined_records` holds current state and clears on recovery.
* **Credits on credit date (D-01a).** A closed window stays closed when a late credit arrives; the price is cohort mixing in the return rate, disclosed on the returns view.

## Recovery behaviour (observed in tests)
| Situation | Behaviour | Test |
|---|---|---|
| Second freight allocation for a shipment | 409 `FREIGHT_ALREADY_ALLOCATED`, no partial write, no audit row; same key replays the first result with `Idempotent-Replay: true` | P01-TEST-01 |
| Return above remaining quantity / negative credit | 422 with `error.details[].rule_id` `RETURN_EXCEEDS_REMAINING` / `CREDIT_SIGN_REVERSED`; nothing written | P01-TEST-06, 10, INJ-06/07 |
| Same idempotency key, different payload | 409; same payload returns the stored result | C01 tests |
| Stale `expected_version` on a line | 409 `STALE_VERSION` (optimistic concurrency on `shipment_lines.version`) | test_api_commands |
| Hostile ingest payloads | 422, never 500, no rows written | P01-TEST-06 |
| Missing FX / cost version | line quarantined; ingesting the rate or fixing `valid_to` and rerunning C02 releases it | P01-TEST-03, 04 |
| Atomic audit | business write, audit event and stored command result commit in one transaction; independent review could not break atomic rollback or concurrent C03/C04 (exactly one success) | ledger review entry |

## Reproducible setup
```sh
cd apps/revenue-atlas
python -m venv ../../.venv && ../../.venv/bin/pip install -r requirements.txt -r requirements-artifacts.txt
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/revenue_atlas
python data/generate.py --seed 20261026 --out web/public/data     # optional: deterministic, same dataset_hash 40f541fc... (rewrites manifest generated_at)
python data/migrate.py --reset && python data/seed.py tests/fixtures/golden/inputs.json
python3 -I tests/reference_check.py                               # stdlib golden check, 187 checks
../../.venv/bin/python -m pytest -q                               # needs DATABASE_URL, resets this project's tables per test
(cd web && npm ci && npm run check && npm run e2e)                # tsc strict + 175 golden checks; 24 Playwright tests
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py && ../../.venv/bin/python data/sql/analysis/run_all.py   # SQL investigations + reconciliation
../../.venv/bin/python artifacts/build_workbook.py --recalc       # workbook (LibreOffice recalculation)
```

## Measured evidence
| Evidence | Result | Where |
|---|---|---|
| Full pytest, local PostgreSQL 16.15, this package included | 109 passed, 3 skipped (2 blocked TEST-08/12 recover cases, 1 CHECKSUMS skip before it was written), 95.5 s | A-010 run on its own database |
| Mode A on a hosted runner after contract v1.1 | success; reference check ALL OK; 100 tests | https://github.com/mrrishit909/projects-site/actions/runs/40313628128 |
| Mode A + Mode B at `fdd0789` | success; 175 TS golden checks, 24 Playwright tests, screenshots at 360/768/1280/1920 | https://github.com/mrrishit909/projects-site/actions/runs/40314532665 |
| Earlier Mode A at `57f01433` | success; 63 tests | https://github.com/mrrishit909/projects-site/actions/runs/40306213772 |
| Live deployment check | 200 on 7 URLs, served `dataset_hash` equals the manifest, 0 console errors | https://github.com/mrrishit909/projects-site/actions/runs/40310810960 |
| Portfolio link in both directions | verified | https://github.com/mrrishit909/projects-site/actions/runs/40313778038 |
| TypeScript pipeline timing | 377 ms for `runPipeline` over 6,649 shipment lines, `npm run golden` ALL OK (175 checks), re-run in this package; ledger recorded about 0.3 s | `web/scripts/golden-check.ts` |
| Golden fixture | independent reference: 187 checks, 7 fixture hashes verified; net 225.00, contribution 70.00, after return 40.00 | ledger P01-GOLD |
| Snapshot reconciliation | bridge 3,309,826.22 = `reference_totals.sql` = Python domain; residual 0.00 across 2,724 shipments | `sql-analysis.md` |
| Generator | two runs give identical `dataset_hash`; 16 generator tests | ledger P01-DATA |

## Defects found and fixed
* **G-01 (UAT, fixed in contract v1.1 / D-01a):** a late credit changed a closed month. Now shipment lines are windowed by `shipped_at` and credits by `credit_date` in Python, SQL and TypeScript; observed: closed March window net stays 225.00, the later window shows credit 90.00 and net -90.00.
* **DEFECT-1 (fixed):** `FX_RATE_MISSING` was reported in metrics but not persisted. C02 now evaluates FX first and writes the quarantine row; a later rate ingest clears it (gross 338.00, CM 93.60 after recovery in the test).

## Open gaps (not hidden)
* Independent review R-01..R-07 (ledger, fix task T-01-13 queued): shipped quantity above ordered accepted; `discount_allocations` drift when a line ships across several C04 calls; grouped metrics omit unallocated freight; web overview/bridge months count credits by shipment month; cent drift in grouped sums after FX; cross-order shipment line accepted; idempotency payload hashed as text.
* **New in this package (A-010):** C04 allocates freight over every line of a shipment, including lines C02 quarantined; the contract metrics re-split over in-population lines. Summing the stored table over population lines under-reports shipping by 287.78 (41 shipments). Metrics and the API are unaffected; direct consumers of `freight_allocations` are.
* Not implemented: C05..C10 (investigate, compare regions, scenarios, export, publish), quota attainment (P01-TEST-08), backend scenarios (P01-TEST-12 recover). The web date filter still selects facts by `shipped_at` only.
* BI: no `.pbix` exists (`bi-package.md` is a design). Workbook: recalculated by LibreOffice, not by Excel.
* The live site was checked from a hosted runner (this environment cannot reach `github.io`); this package did not re-check it.
