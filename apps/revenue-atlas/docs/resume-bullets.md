# Résumé bullets: Revenue Atlas (P01)

Based on what was built and verified (ledger, UAT evidence, A-010 runs). The project uses **synthetic data only**; no bullet claims business impact, revenue, savings or users.
Professional facts outside this project belong to the résumé, not to this file.

* Specified a shipment-line-grain contribution-margin contract (seven written decisions on grain, FX, historical cost, allocation, credits and scenarios) with a hand-derived golden fixture, and implemented it independently in Python, SQL and TypeScript; the three agree to the cent on a 6,588-line synthetic snapshot (contribution 3,309,826.22) and on the fixture (250.00 gross to 70.00 contribution; 40.00 after a return).
* Designed an 18-table PostgreSQL 16 schema in two plain-SQL migrations (type-2 customers, append-only returns and audit tables, largest-remainder allocation keyed by line) and FastAPI commands with idempotent replay, 409 conflicts, 422 rule errors and atomic audit; verified by a 109-test local suite and GitHub-hosted CI runs.
* Wrote and ran adversarial tests for 12 business failure cases (double freight allocation, late returns, missing FX, overlapping costs, UNASSIGNED regions and others); found and fixed two defects (credit windowing on credit date, persisted FX quarantine), and documented the open ones from an independent review.
* Produced eight executable SQL investigations on a seeded snapshot with a reconciliation to an independent reference query, and surfaced an inconsistency between stored freight allocations and the contract population (287.78 across 41 shipments) that the aggregate metrics do not show.
* Built a formula-driven analyst workbook (integer-cent largest-remainder allocation in live formulas, a margin bridge and an expected-value check sheet) and validated it by LibreOffice recalculation plus a separate Python evaluation of the same chain; stated plainly that Excel was not run.
* Packaged the work for review: data dictionary and ER diagram, a Power BI model design (no `.pbix` produced), an executive memo that frames findings as what synthetic data supports, a technical case study, and checksummed release artifacts.
