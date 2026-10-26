"""Write artifacts/CHECKSUMS.txt: sha256 of every file produced for the artifact package (P02-ART-03..10).

Usage:  ../../.venv/bin/python artifacts/checksums.py [--table]       (run from apps/onboard-studio; `sha256sum -c` format)
        --table also prints the same list as a Markdown table (the one in docs/release-package.md)
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "artifacts/onboard-studio-analyst-workbook.xlsx", "artifacts/analysis-results.json",
    "artifacts/build_workbook.py", "artifacts/checksums.py", "requirements-artifacts.txt",
    "data/sql/analysis/00_case_facts.sql", "data/sql/analysis/01_cycle_time_by_opening_month.sql",
    "data/sql/analysis/02_version_comparison_comparable_window.sql", "data/sql/analysis/03_sla_by_segment_region.sql",
    "data/sql/analysis/04_step_waiting_by_step_assignee.sql", "data/sql/analysis/05_rework_first_pass_by_segment.sql",
    "data/sql/analysis/06_paused_time_by_reason_region.sql", "data/sql/analysis/07_backlog_month_ends.sql",
    "data/sql/analysis/08_flags_and_rejections_by_reason.sql", "data/sql/analysis/09_golden_case_business_hours.sql",
    "data/sql/analysis/bi_fact_case.sql", "data/sql/analysis/bi_fact_step_instance.sql",
    "data/sql/analysis/prepare_snapshot.py", "data/sql/analysis/run_all.py", "tests/test_artifacts.py",
    "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
    "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md",
]
# docs/release-package.md is not listed: it carries these checksums, so it cannot contain its own. CHECKSUMS.txt cannot list itself.


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
    if "--table" in argv:
        print("| File | sha256 |\n|---|---|\n" + "\n".join(rows))


if __name__ == "__main__":
    main(sys.argv[1:])
