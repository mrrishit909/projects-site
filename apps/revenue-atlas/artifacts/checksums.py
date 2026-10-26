"""Write artifacts/CHECKSUMS.txt: sha256 of every file produced for the artifact package (P01-ART-03..10).

Usage:  ../../.venv/bin/python artifacts/checksums.py       (run from apps/revenue-atlas; `sha256sum -c` format)
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "artifacts/revenue-atlas-analyst-workbook.xlsx", "artifacts/analysis-results.json",
    "artifacts/build_workbook.py", "artifacts/checksums.py", "requirements-artifacts.txt",
    "data/sql/analysis/00_line_facts.sql", "data/sql/analysis/01_margin_bridge_by_month.sql",
    "data/sql/analysis/02_contribution_by_region.sql", "data/sql/analysis/03_discount_rate_by_region_before_after_2026_03.sql",
    "data/sql/analysis/04_fixtures_cost_vs_price_by_month.sql", "data/sql/analysis/05_return_rate_by_segment_category.sql",
    "data/sql/analysis/06_top10_customers_contribution_decline.sql", "data/sql/analysis/07_quarantine_reasons.sql",
    "data/sql/analysis/08_allocation_residual_check.sql", "data/sql/analysis/09_stored_vs_contract_freight.sql",
    "data/sql/analysis/prepare_snapshot.py", "data/sql/analysis/run_all.py", "tests/test_artifacts.py",
    "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
    "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md",
]
# docs/release-package.md is not listed: it carries these checksums, so it cannot contain its own.


def main() -> None:
    lines = []
    for rel in FILES:
        p = ROOT / rel
        if p.exists():
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}")
    (ROOT / "artifacts" / "CHECKSUMS.txt").write_text("\n".join(lines) + "\n")
    print(f"wrote artifacts/CHECKSUMS.txt ({len(lines)} files)")


if __name__ == "__main__":
    main()
