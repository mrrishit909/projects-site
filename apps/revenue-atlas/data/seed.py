"""Load a fixture ``inputs.json`` into the tables (idempotent by primary key).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json

Rows are validated with the domain's ``validate_batch`` (same rule as command C01), so a
fixture with a bad currency loads its good rows and reports the rest as ``skipped``.
Inserts use ``ON CONFLICT DO NOTHING``; running twice changes nothing. Each run records
one ``dataset_versions`` row whose ``dataset_hash`` is the sha256 of the canonical JSON.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

try:
    import revenue_atlas  # noqa: F401
except ImportError:  # running as a script without PYTHONPATH=domain
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "domain"))
from revenue_atlas import CONTRACT_VERSION  # noqa: E402
from revenue_atlas.ingest import validate_batch  # noqa: E402

#: Insert order respects foreign keys (0002_constraints.sql).
INSERT_ORDER: tuple[str, ...] = (
    "customers", "products", "cost_versions", "exchange_rates", "orders", "order_lines",
    "discounts", "shipments", "shipment_lines", "returns")

COLUMNS: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id", "customer_name", "region_id", "segment", "effective_from"),
    "products": ("product_id", "sku", "category_id", "unit_of_measure", "active"),
    "orders": ("order_id", "customer_id", "order_date", "currency", "status"),
    "order_lines": ("line_id", "order_id", "product_id", "quantity", "unit_price"),
    "discounts": ("discount_id", "line_id", "discount_amount", "reason_code", "approved_by"),
    "shipments": ("shipment_id", "order_id", "shipped_at", "shipping_cost", "currency"),
    "shipment_lines": ("shipment_line_id", "shipment_id", "line_id", "shipped_quantity",
                       "cost_version_id"),
    "returns": ("return_id", "shipment_line_id", "returned_quantity", "credit_amount",
                "credit_date"),
    "cost_versions": ("cost_version_id", "product_id", "unit_cost", "valid_from", "valid_to"),
    "exchange_rates": ("rate_id", "currency", "reporting_currency", "rate_date", "rate"),
}


def canonical_json(obj: Any) -> str:
    """Canonical JSON used for every hash in the data layer."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def row_from_record(record: Any) -> dict[str, Any]:
    """Domain dataclass to a JSON-shaped row (Decimal and datetime as strings)."""
    out: dict[str, Any] = {}
    for key, val in dataclasses.asdict(record).items():
        if isinstance(val, datetime):
            out[key] = val.isoformat()
        elif isinstance(val, Decimal):
            out[key] = format(val, "f")
        else:
            out[key] = val
    return out


def insert_rows(conn: psycopg.Connection, rows: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Insert JSON-shaped rows per entity; return rows actually inserted per entity."""
    inserted: dict[str, int] = {}
    for entity in INSERT_ORDER:
        cols = COLUMNS[entity]
        sql = (f"INSERT INTO {entity} ({', '.join(cols)}) "  # entity/cols are constants above
               f"VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING")
        count = 0
        for row in rows.get(entity, []):
            cur = conn.execute(sql, tuple(row.get(c) for c in cols))
            count += cur.rowcount
        inserted[entity] = count
    return inserted


def seed(conn: psycopg.Connection, inputs: dict[str, Any]) -> dict[str, Any]:
    """Seed one fixture; return ``{dataset_version, dataset_hash, inserted, skipped}``."""
    ing = validate_batch(inputs)
    rows = {ent: [row_from_record(r) for r in recs] for ent, recs in ing.accepted.items()}
    inserted = insert_rows(conn, rows)
    dataset_hash = sha256_hex(canonical_json(inputs))
    version = f"ds-{dataset_hash[:12]}"
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version) "
                 "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                 (version, dataset_hash, CONTRACT_VERSION))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": inserted,
            "skipped": len(ing.rejected)}


def main(argv: list[str]) -> int:
    url = os.environ.get("DATABASE_URL")
    if not url or len(argv) != 1:
        print("usage: DATABASE_URL=... python data/seed.py <inputs.json>", file=sys.stderr)
        return 2
    inputs = json.loads(Path(argv[0]).read_text())
    with psycopg.connect(url) as conn:
        print(json.dumps(seed(conn, inputs), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
