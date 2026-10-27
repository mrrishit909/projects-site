"""Fill the result tables of docs/sql-analysis.md and docs/bi-package.md from artifacts/analysis-results.json (P07-ART-04, P07-ART-06).

Usage:  ../../.venv/bin/python artifacts/render_sql_analysis.py

Every block between ``<!-- BEGIN:key -->`` and ``<!-- END:key -->`` is replaced by the stored rows of that key, so no pasted figure in a table is typed by
hand. ``tests/test_artifacts.py`` re-renders in memory and fails on any drift.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "docs" / "sql-analysis.md", ROOT / "docs" / "bi-package.md"]
RES = ROOT / "artifacts" / "analysis-results.json"


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).replace("|", "/")


def table(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def render(text: str, results: dict) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        return f"<!-- BEGIN:{key} -->\n{table(results[key])}\n<!-- END:{key} -->"
    return re.sub(r"<!-- BEGIN:([\w]+) -->.*?<!-- END:\1 -->", sub, text, flags=re.S)


def main() -> int:
    results = json.loads(RES.read_text())
    for doc in DOCS:
        if doc.exists():
            doc.write_text(render(doc.read_text(), results))
            print(f"rendered {doc.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
