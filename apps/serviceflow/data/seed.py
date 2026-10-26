"""Load a fixture ``inputs.json`` into the tables (idempotent by primary key).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json

Rows are validated with the domain's ``validate_batch`` (the same rules as the API), so a fixture with rejected rows
loads the accepted rows, keeps the rejected raw rows in ``rejected_records`` and reports the count as ``skipped``.
Inserts use ``ON CONFLICT DO NOTHING``; running twice changes nothing. Each run records one ``dataset_versions`` row
whose ``dataset_hash`` is the sha256 of the canonical JSON. Every accepted simulation run is also simulated once and
its events stored in ``simulation_events`` (the golden case: se-001..se-006).
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
    import serviceflow  # noqa: F401
except ImportError:  # running as a script without PYTHONPATH=domain
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "domain"))
from serviceflow import CONTRACT_VERSION  # noqa: E402
from serviceflow.ingest import validate_batch  # noqa: E402
from serviceflow.simulation import simulate  # noqa: E402

#: Insert order respects foreign keys (0001_schema.sql).
INSERT_ORDER: tuple[str, ...] = ("customers", "queues", "agents", "skills", "agent_skills", "queue_skills", "shifts",
                                 "sla_policies", "tickets", "ticket_events", "surveys")

COLUMNS: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id", "segment", "timezone", "created_at", "synthetic"),
    "queues": ("queue_id", "queue_name", "priority_policy", "calendar_id", "active"),
    "agents": ("agent_id", "agent_name", "timezone", "employment_type", "active", "max_concurrent"),
    "skills": ("skill_id", "skill_name", "description", "active", "created_at"),
    "agent_skills": ("agent_skill_id", "agent_id", "skill_id", "proficiency", "effective_from"),
    "queue_skills": ("queue_id", "skill_id"),
    "shifts": ("shift_id", "agent_id", "starts_at", "ends_at", "break_minutes"),
    "sla_policies": ("sla_policy_id", "priority", "first_response_minutes", "resolution_minutes", "calendar_id"),
    "tickets": ("ticket_id", "customer_id", "queue_id", "priority", "created_at", "channel"),
    "ticket_events": ("event_id", "ticket_id", "event_type", "occurred_at", "actor_id", "queue_id", "agent_id"),
    "surveys": ("survey_id", "ticket_id", "response_at", "score", "invited_at"),
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


def insert_simulation(conn: psycopg.Connection, run: dict[str, Any], replications: int = 1) -> tuple[int, int]:
    """Store a run and the events of its first replication; returns (runs inserted, events inserted)."""
    sim = simulate(run["config"], run["seed"], run["warmup_minutes"], run["horizon_minutes"], run["simulation_id"])
    runs = conn.execute("INSERT INTO simulation_runs (simulation_id, seed, warmup_minutes, policy_version, "
                        "horizon_minutes, config, replications) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT DO NOTHING",
                        (run["simulation_id"], run["seed"], run["warmup_minutes"], run["policy_version"],
                         run["horizon_minutes"], Jsonb(run["config"]), replications)).rowcount
    warm = set(sim.warmup_ticket_ids)
    n = 0
    for e in sim.events:
        n += conn.execute("INSERT INTO simulation_events (simulation_id, simulation_event_id, ticket_id, event_type, "
                          "event_at, warmup) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                          (e["simulation_id"], e["simulation_event_id"], e["ticket_id"], e["event_type"], e["event_at"],
                           e["ticket_id"] in warm)).rowcount
    return runs, n


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
    inserted["simulation_runs"] = inserted["simulation_events"] = 0
    for run in ing.accepted_rows["simulation_runs"]:
        r, n = insert_simulation(conn, run)
        inserted["simulation_runs"] += r
        inserted["simulation_events"] += n
    if ing.rejected:
        batch_id = f"batch-seed-{dataset_hash[:16]}"
        conn.execute("INSERT INTO raw_batches (batch_id, idempotency_key, payload_hash, payload, status) "
                     "VALUES (%s, %s, %s, %s, 'partial') ON CONFLICT DO NOTHING",
                     (batch_id, f"seed-{dataset_hash[:32]}", dataset_hash, Jsonb(inputs)))
        insert_rejected(conn, batch_id, ing.rejected)
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version) "
                 "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (version, dataset_hash, str(CONTRACT_VERSION)))
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
