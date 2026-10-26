"""Prepare the seeded snapshot for the analysis queries (P01-ART-04).

Usage:  DATABASE_URL=postgresql://... ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py

Steps (the operator path of docs/contracts.md D-03/D-04): reset + migrate, seed web/public/data
(INJ-01 orders are refused at seed), ingest the three INJ-01 order bundles through C01 so the
refusals land in rejected_records, then C02 (cost version + quarantine) and C04 (freight and
discount allocation) for every shipment. Writes nothing outside the target database.
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
from fastapi.testclient import TestClient  # noqa: E402

from api.app import PREFIX, create_app  # noqa: E402
from data import migrate, seed  # noqa: E402

SNAPSHOT = ROOT / "web" / "public" / "data"
HEADERS = {"X-Actor-Id": "analysis-prep", "X-Actor-Role": "steward"}
BAD_ORDERS = {"ord-002141", "ord-002021", "ord-001005"}      # INJ-01


def load_inputs() -> dict:
    data: dict = {"contract": "v1", "reporting_currency": "USD"}
    for f in SNAPSHOT.glob("*.json"):
        if f.stem in ("manifest", "injection-manifest", "quotas"):
            continue
        data[f.stem] = json.loads(f.read_text())["rows"]
    return data


def main() -> int:
    url = os.environ["DATABASE_URL"]
    inputs = load_inputs()
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
        out = seed.seed(conn, inputs)
    print("seed:", json.dumps({k: out[k] for k in ("dataset_version", "skipped")}),
          "inserted:", json.dumps(out["inserted"]))
    with TestClient(create_app()) as client:
        def post(name: str, input_: dict, key: str):
            r = client.post(f"{PREFIX}/commands/{name}", headers=HEADERS,
                            json={"request_id": "prep", "dataset_version": out["dataset_version"],
                                  "idempotency_key": key, "input": input_})
            assert r.status_code == 200, (name, key, r.status_code, r.text[:300])
            return r.json()

        # INJ-01 through C01: the malformed-currency orders and all dependants are rejected, raw rows kept.
        lines = {r["line_id"] for r in inputs["order_lines"] if r["order_id"] in BAD_ORDERS}
        shp = {r["shipment_id"] for r in inputs["shipments"] if r["order_id"] in BAD_ORDERS}
        sls = {r["shipment_line_id"] for r in inputs["shipment_lines"] if r["shipment_id"] in shp}
        batch = {"contract": "v1",
                 "orders": [r for r in inputs["orders"] if r["order_id"] in BAD_ORDERS],
                 "order_lines": [r for r in inputs["order_lines"] if r["line_id"] in lines],
                 "discounts": [r for r in inputs["discounts"] if r["line_id"] in lines],
                 "shipments": [r for r in inputs["shipments"] if r["shipment_id"] in shp],
                 "shipment_lines": [r for r in inputs["shipment_lines"] if r["shipment_line_id"] in sls],
                 "returns": [r for r in inputs["returns"] if r["shipment_line_id"] in sls]}
        c01 = post("ingest-sales", {"batch": batch}, "prep-inj01")
        print("C01 INJ-01 status:", c01["status"], "rejected:", len(c01["result"]["rejected_records"]))

        with psycopg.connect(url) as conn:
            ships = [r[0] for r in conn.execute("SELECT shipment_id FROM shipments ORDER BY 1").fetchall()]
        for i, sid in enumerate(ships):
            post("resolve-historical-cost", {"shipment_id": sid}, f"prep-c02-{sid}")
            post("allocate-freight", {"shipment_id": sid}, f"prep-c04-{sid}")
        print("C02 + C04 run for", len(ships), "shipments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
