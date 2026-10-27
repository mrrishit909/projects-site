# ChangeWorks: résumé bullets (P09-ART-10 support)

**Synthetic data only.** These bullets describe engineering on a generated portfolio (dataset `cw-20261026-20261026`, generator `dataset_hash` `6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9`, code revision `29948f9`); every number is a count of checks, tests or synthetic records from the ledgers and this package's run, and no bullet claims business impact on a real organisation.

* Built a transformation-portfolio decision tool (Python, PostgreSQL 16, FastAPI) under written contracts D-01..D-09 that keeps cash, revenue, avoided cost and capacity hours apart and computes NPV as an exact rational, verified by 454 Python tests on GitHub-hosted runners and a 3,156-check standard-library reference.
* Wrote an independent SQL model of the cash flows, paybacks (last crossing) and the double-count rule whose 48,476 leaves equal the reference SQL and the Python domain, and reconciled eleven investigations in 763 reconciliation rows, all equal, including the known answer NPV 5000/121 = 41.32.
* Showed in the synthetic portfolio that the plain sum of initiative NPVs (1,438,382.25) counted a shared capacity claim twice; the attributable figure is 1,243,149.05, and only 10 of 24 initiatives carry a cash case without depending on one that does not.
* Delivered a formula-driven analyst workbook (openpyxl, recalculated by LibreOffice headless with a self-check cell; Excel not run) and a BI star schema of 14 CSV tables with 486 measure rows, no `.pbix`, every empty value carrying its reason and scope.
* Acted on a 14-defect review (R9-01..R9-22) and documented the fixes, the data dictionary, the ERD and the release with checksums and a rollback commit.
