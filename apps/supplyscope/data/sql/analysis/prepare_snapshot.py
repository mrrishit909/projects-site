"""Prepare databases for the analysis queries (P03-ART-04).

Usage:
  DATABASE_URL=postgresql://... ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py            # the generated snapshot
  DATABASE_URL=postgresql://... ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden   # the golden fixture

Resets the project's tables in the target database (never the whole schema), applies the migrations and seeds either
``web/public/data`` (the published synthetic snapshot) or ``tests/fixtures/golden/inputs.json``. Seeding goes through the
domain's ``validate_batch``, so the injected defects the contract rejects land in ``rejected_records`` as in production.
Use an empty scratch database (never the shared ``supplyscope`` one).
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
ENTITIES = ("backorders", "calendar_closures", "cost_versions", "forecast_points", "forecast_runs", "inventory_movements",
            "latent_demand", "locations", "lost_sales", "policy_scenarios", "products", "promotions", "purchase_order_lines",
            "purchase_orders", "receipts", "replenishment_params", "reservations", "sales", "suppliers")


def snapshot_inputs() -> dict:
    """The published rows plus the cut and window of the generator (as in tests/test_generator.py)."""
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text())
    data: dict = {"contract_version": 1, "as_of": manifest["generator"]["parameters"]["as_of"],
                  "window_start": "2025-04-01T00:00:00Z"}
    for name in ENTITIES:
        data[name] = json.loads((SNAPSHOT / f"{name}.json").read_text())["rows"]
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
