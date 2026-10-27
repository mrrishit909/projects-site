"""Write artifacts/CHECKSUMS.txt: sha256 of every file produced for the artifact package (P06-ART-01..10).

Usage:  ../../.venv/bin/python artifacts/checksums.py [--table]       (run from apps/productsignal; `sha256sum -c` format)
        --table also rewrites the block between the checksums markers of docs/release-package.md with the same list as a Markdown
        table (that document is not listed: it carries the checksums, so it cannot contain its own).

Paths are relative to apps/productsignal. The list is every artifact (workbook, analysis results, BI CSV exports, scripts), every analysis SQL and Python
file, every document of docs/ except release-package.md, requirements-artifacts.txt and tests/test_artifacts.py. ``artifacts/CHECKSUMS.txt`` cannot list itself.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN, END = "<!-- BEGIN:checksums -->", "<!-- END:checksums -->"
SELF_REFERENTIAL = {"docs/release-package.md", "artifacts/CHECKSUMS.txt"}


def files() -> list[str]:
    out: list[str] = []
    for pattern in ("artifacts/*", "artifacts/bi/*", "data/sql/analysis/*.sql", "data/sql/analysis/*.py", "docs/*.md"):
        for p in sorted(ROOT.glob(pattern)):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and rel not in SELF_REFERENTIAL and "__pycache__" not in rel and not p.name.startswith(("~$", ".~lock")) and p.suffix != ".tmp":
                out.append(rel)
    out += ["requirements-artifacts.txt", "tests/test_artifacts.py"]
    return sorted(dict.fromkeys(out))


def main(argv: list[str]) -> None:
    lines, rows = [], []
    for rel in files():
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
        doc = ROOT / "docs" / "release-package.md"
        text = doc.read_text()
        new = re.sub(re.escape(BEGIN) + ".*?" + re.escape(END), lambda m: f"{BEGIN}\n{table}\n{END}", text, flags=re.S)
        doc.write_text(new)
        print("rewrote the checksums block of docs/release-package.md")


if __name__ == "__main__":
    main(sys.argv[1:])
