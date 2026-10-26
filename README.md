# Business Data Lab

Ten synthetic business and data products built to the directive pack in
`mrrishit909/projects-site` branch `claude-business-data-directive-2026-10-26`
(`build-directives/business-data-lab/`, verified pack commit `fe5f7981`).

This branch (`business-data-lab`) is an orphan branch holding only the lab's
application source and program ledgers; the directive stays on its own branch
and the portfolio stays on `unified-portfolio`.

* `docs/program/` — program-status, task queue, delegation ledger,
  verification ledger, release manifest, source-pack record.
* `apps/<slug>/` — one directory per product: `domain/`, `api/`, `data/`,
  `tests/`, `web/`, `docs/`.

All data is synthetic. Public sites are static GitHub Pages demos whose
mutations are browser-memory simulations; backend and relational behaviour is
verified on GitHub-hosted Actions runners with a transient PostgreSQL service.
