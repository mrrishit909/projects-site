# revenue_atlas domain (contract v1)

Standard-library Python implementing `docs/contracts.md` (D-01..D-06). Pure functions, Decimal money, no I/O.

Flow: `ingest.validate_batch` -> `pipeline.run_pipeline` (FX, cost version, region, discount and freight
allocation, returns) -> `metrics.compute_metrics` / `group_metrics`. Failures raise `errors.DomainError`
(`code`, `message`, `path`, `details`); pipeline lines/returns that fail are quarantined with that code.

Run tests from `apps/revenue-atlas`: `python -m pytest -q`.
