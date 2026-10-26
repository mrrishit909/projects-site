"""Load a fixture ``inputs.json`` into the tables (idempotent by primary key).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json

Rows are validated with the domain's ``validate_batch`` (the same rules as the API), so a fixture with rejected rows
loads the accepted rows, keeps the rejected raw rows in ``rejected_records`` and reports the count as ``skipped``.
Inserts use ``ON CONFLICT DO NOTHING``; running twice changes nothing. Each run records one ``dataset_versions`` row
whose ``dataset_hash`` is the sha256 of the canonical JSON. The fixture's named states go to ``fixture_states``.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

try:
    import supplyscope  # noqa: F401
except ImportError:  # running as a script without PYTHONPATH=domain
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "domain"))
from supplyscope import CONTRACT_VERSION  # noqa: E402
from supplyscope.ingest import validate_batch  # noqa: E402

#: Insert order respects foreign keys (0001_schema.sql).
INSERT_ORDER: tuple[str, ...] = (
    "suppliers", "products", "locations", "calendar_closures", "cost_versions", "policy_scenarios", "purchase_orders",
    "purchase_order_lines", "receipts", "inventory_movements", "sales", "promotions", "latent_demand", "forecast_runs",
    "forecast_points", "backorders", "lost_sales", "reservations", "replenishment_params")

COLUMNS: dict[str, tuple[str, ...]] = {
    "suppliers": ("supplier_id", "supplier_name", "calendar_id", "quoted_lead_days", "active"),
    "products": ("product_id", "sku", "unit_cost", "pack_size", "minimum_order_quantity", "abc_class", "supplier_id"),
    "locations": ("location_id", "location_name", "timezone", "storage_capacity", "active"),
    "calendar_closures": ("closure_id", "calendar_id", "closed_from", "closed_to"),
    "cost_versions": ("cost_version_id", "product_id", "unit_cost", "effective_from"),
    "policy_scenarios": ("scenario_id", "scenario_name", "service_target", "unmet_policy", "seed", "warmup_days",
                         "replications"),
    "purchase_orders": ("purchase_order_id", "supplier_id", "ordered_at", "status", "currency"),
    "purchase_order_lines": ("po_line_id", "purchase_order_id", "product_id", "ordered_quantity", "unit_cost"),
    "receipts": ("receipt_id", "po_line_id", "location_id", "received_quantity", "received_at"),
    "inventory_movements": ("movement_id", "product_id", "location_id", "quantity_delta", "event_at", "movement_type"),
    "sales": ("sale_id", "product_id", "location_id", "sold_at", "quantity"),
    "promotions": ("promotion_id", "product_id", "location_id", "starts_at", "ends_at", "planned_uplift",
                   "announced_at", "realised_uplift"),
    "latent_demand": ("product_id", "location_id", "demand_date", "latent_quantity"),
    "forecast_runs": ("forecast_run_id", "product_id", "location_id", "cutoff", "horizon_days", "selected_model"),
    "forecast_points": ("forecast_point_id", "forecast_run_id", "model", "target_date", "forecast_value"),
    "backorders": ("backorder_id", "product_id", "location_id", "quantity", "opened_at", "closed_at", "scenario_id"),
    "lost_sales": ("lost_sale_id", "product_id", "location_id", "quantity", "occurred_at", "scenario_id"),
    "reservations": ("reservation_id", "product_id", "location_id", "quantity", "reserved_at", "released_at"),
    "replenishment_params": ("product_id", "location_id", "reorder_point", "target_position", "supplier_id"),
}


def canonical_json(obj: Any) -> str:
    """Canonical JSON used for every hash in the data layer."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def insert_rejected(conn: psycopg.Connection, batch_id: str, rejected: list[Any]) -> None:
    """Keep every rejected raw row; two occurrences of one id get different ordinals."""
    seen: dict[tuple[str, str, str], int] = {}
    for rej in rejected:
        k = (rej.entity, rej.id, rej.reason_code)
        n = seen[k] = seen.get(k, -1) + 1
        conn.execute("INSERT INTO rejected_records (entity, id, reason_code, raw_row, batch_id, ordinal) "
                     "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (rej.entity, rej.id, rej.reason_code, Jsonb(rej.raw_row), batch_id, n))


def seed(conn: psycopg.Connection, inputs: dict[str, Any]) -> dict[str, Any]:
    """Seed one fixture; return ``{dataset_version, dataset_hash, inserted, skipped}``."""
    ing = validate_batch(inputs)
    dataset_hash = sha256_hex(canonical_json(inputs))
    version = f"ds-{dataset_hash[:12]}"
    inserted: dict[str, int] = {}
    for ent in INSERT_ORDER:
        cols = COLUMNS[ent]
        sql = (f"INSERT INTO {ent} ({', '.join(cols)}) "  # ent/cols are constants above
               f"VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING")
        n = 0
        for row in ing.accepted_rows[ent]:
            n += conn.execute(sql, [row.get(c) for c in cols]).rowcount
        inserted[ent] = n
    for name, spec in (inputs.get("states") or {}).items():
        conn.execute("INSERT INTO fixture_states (state_name, payload) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (name, Jsonb(spec)))
    if ing.rejected:
        batch_id = f"batch-seed-{dataset_hash[:16]}"
        conn.execute("INSERT INTO raw_batches (batch_id, idempotency_key, payload_hash, payload, status) "
                     "VALUES (%s, %s, %s, %s, 'partial') ON CONFLICT DO NOTHING",
                     (batch_id, f"seed-{dataset_hash[:32]}", dataset_hash, Jsonb(inputs)))
        insert_rejected(conn, batch_id, ing.rejected)
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version) "
                 "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (version, dataset_hash, CONTRACT_VERSION))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": inserted, "skipped": len(ing.rejected)}


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
