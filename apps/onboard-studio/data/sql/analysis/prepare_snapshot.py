"""Prepare databases for the analysis queries (P02-ART-04).

Usage:
  DATABASE_URL=postgresql://... ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py            # the generated snapshot
  DATABASE_URL=postgresql://... ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden   # the golden fixture

Resets the project's tables in the target database (never the whole schema), applies the migrations and seeds either
``web/public/data`` (the published synthetic snapshot, ``workflow_requirements`` folded back into the D-05 block) or
``tests/fixtures/golden/inputs.json``. Seeding goes through the domain's ``validate_batch``, so the injected defects that
the contract rejects land in ``rejected_records`` exactly as they would in production. Use an empty scratch database.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "domain", ROOT):
    sys.path.insert(0, str(p))

import psycopg  # noqa: E402

from data import migrate, seed  # noqa: E402

SNAPSHOT = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "inputs.json"
ENTITIES = ("organizations", "workflow_versions", "step_definitions", "dependencies", "sla_rules", "calendar_intervals",
            "cases", "step_instances", "assignments", "document_versions", "approvals", "waiting_intervals",
            "case_events")


def snapshot_inputs() -> dict:
    data: dict = {"contract": "v1"}
    for name in ENTITIES:
        data[name] = json.loads((SNAPSHOT / f"{name}.json").read_text())["rows"]
    reqs = json.loads((SNAPSHOT / "workflow_requirements.json").read_text())["rows"]
    data["workflow_requirements"] = {r["workflow_version_id"]: {"required_document_types": r["required_document_types"]}
                                     for r in reqs}
    return data


def main(argv: list[str]) -> int:
    url = os.environ["DATABASE_URL"]
    inputs = json.loads(GOLDEN.read_text()) if "--golden" in argv else snapshot_inputs()
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
        out = seed.seed(conn, inputs)
    print(json.dumps({"dataset_version": out["dataset_version"], "dataset_hash": out["dataset_hash"],
                      "rejected_rows_kept": out["skipped"], "inserted": out["inserted"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
