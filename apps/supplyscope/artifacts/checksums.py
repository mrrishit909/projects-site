"""Write artifacts/CHECKSUMS.txt: sha256 of every file produced for the artifact package (P03-ART-03..10).

Usage:  ../../.venv/bin/python artifacts/checksums.py [--table]       (run from apps/supplyscope; `sha256sum -c` format)
        --table also prints the same list as a Markdown table, and rewrites the block between the checksums markers
        of docs/release-package.md (that document is not listed: it carries the checksums, so it cannot contain its own).
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "artifacts/supplyscope-analyst-workbook.xlsx", "artifacts/analysis-results.json",
    "artifacts/build_workbook.py", "artifacts/render_sql_analysis.py", "artifacts/checksums.py", "requirements-artifacts.txt",
    "data/sql/analysis/00_ledger_views.sql", "data/sql/analysis/01_stock_position_month_end_by_location.sql",
    "data/sql/analysis/02_draft_orders_arithmetic.sql", "data/sql/analysis/03_fill_rate_stockout_by_location_abc.sql",
    "data/sql/analysis/04_supplier_on_time_by_month.sql", "data/sql/analysis/05_censored_vs_latent_class_a.sql",
    "data/sql/analysis/06_working_capital_by_location.sql", "data/sql/analysis/07_forecast_wape_by_sku.sql",
    "data/sql/analysis/08_rejections_and_defects_by_reason.sql", "data/sql/analysis/09_golden_position_and_order.sql",
    "data/sql/analysis/bi_fact_movement_day.sql", "data/sql/analysis/bi_fact_draft_order.sql",
    "data/sql/analysis/prepare_snapshot.py", "data/sql/analysis/run_all.py", "data/sql/analysis/options.py",
    "tests/test_artifacts.py",
    "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
    "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md",
]
BEGIN, END = "<!-- BEGIN:checksums -->", "<!-- END:checksums -->"


def main(argv: list[str]) -> None:
    lines, rows = [], []
    for rel in FILES:
        p = ROOT / rel
        if not p.exists():
            raise SystemExit(f"missing artifact: {rel}")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}")
        rows.append(f"| `{rel}` | `{digest}` |")
    (ROOT / "artifacts" / "CHECKSUMS.txt").write_text("\n".join(lines) + "\n")
    print(f"wrote artifacts/CHECKSUMS.txt ({len(lines)} files)")
    table = "| File | sha256 |\n|---|---|\n" + "\n".join(rows)
    if "--table" in argv:
        print(table)
        doc = ROOT / "docs" / "release-package.md"
        text = doc.read_text()
        new = re.sub(re.escape(BEGIN) + ".*?" + re.escape(END), lambda m: f"{BEGIN}\n{table}\n{END}", text, flags=re.S)
        doc.write_text(new)
        print("rewrote the checksums block of docs/release-package.md")


if __name__ == "__main__":
    main(sys.argv[1:])
