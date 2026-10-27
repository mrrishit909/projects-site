"""Load a fixture ``inputs.json`` into the tables, idempotently (``ON CONFLICT DO NOTHING``).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json [--dataset-version NAME]

Rows go through the domain's ``validate_import`` (the same rules as the API): a rejected record is kept in ``rejected_records`` with its raw
row and reason code and is not loaded; its dependants are DEPENDENT_REJECTED. Committed batches are classified by the domain (``derive``) so
that ``raw_records.disposition``, ``accepted_records`` (the idempotency boundary) and the delete markers agree with what the API would have
written; the SQL reference never reads those columns. The publication pointer is set to the domain's ``current_publication_id``. Each load
records one ``dataset_versions`` row; ``dataset_version`` defaults to ``ds-<first 12 of the hash>`` and may be named by the caller.
One transaction: the whole fixture loads or nothing does.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

for _p in (Path(__file__).resolve().parents[1] / "domain",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from pipeline_observatory import CONTRACT_VERSION  # noqa: E402
from pipeline_observatory.classify import ACCEPTED, DELETED  # noqa: E402
from pipeline_observatory.contract import ENTITIES  # noqa: E402
from pipeline_observatory.hashing import canonical_json, sha256_hex  # noqa: E402
from pipeline_observatory.metrics import compute, derive, params_of  # noqa: E402
from pipeline_observatory.ingest import validate_import  # noqa: E402

__all__ = ["seed", "canonical_json", "sha256_hex", "insert_rejected"]


def insert_rejected(conn: psycopg.Connection, batch_id: str, rejected: list[dict[str, Any]]) -> None:
    """Keep every rejected raw row; two occurrences of one id get different ordinals."""
    seen: dict[tuple[str, str, str], int] = {}
    for rej in rejected:
        k = (rej["entity"], str(rej["id"]), rej["reason_code"])
        n = seen[k] = seen.get(k, -1) + 1
        conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row, ordinal) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (batch_id, rej["entity"], str(rej["id"]), rej["reason_code"], Jsonb(rej["raw_row"]), n))


def _ins(conn: psycopg.Connection, sql: str, params: tuple[Any, ...]) -> int:
    return conn.execute(sql + " ON CONFLICT DO NOTHING", params).rowcount


def seed(conn: psycopg.Connection, inputs: dict[str, Any], dataset_version: str | None = None, dataset_hash: str | None = None) -> dict[str, Any]:
    """Seed one fixture inside the caller's transaction; return ``{dataset_version, dataset_hash, inserted, skipped}``."""
    imp = validate_import(inputs)
    acc = imp.accepted
    dataset_hash = dataset_hash or sha256_hex(canonical_json(inputs))
    version = dataset_version or f"ds-{dataset_hash[:12]}"
    n = {e: 0 for e in (*ENTITIES, "source_expectations", "accepted_records")}
    facts = derive(acc, cutoff=inputs.get("cutoff"))
    cp_by_batch = {c["batch_id"]: c for c in acc["checkpoints"]}

    for r in acc["source_contracts"]:
        n["source_contracts"] += _ins(conn, "INSERT INTO source_contracts (source_id, source_name, schema_version, expected_frequency, owner_id, freshness_target_seconds) VALUES (%s,%s,%s,%s,%s,%s)",
                                      (r["source_id"], r["source_name"], r["schema_version"], r["expected_frequency"], r["owner_id"], r.get("freshness_target_seconds")))
    for x in inputs.get("source_expectations", []):
        if x["source_id"] in {s["source_id"] for s in acc["source_contracts"]}:
            n["source_expectations"] += _ins(conn, "INSERT INTO source_expectations (source_id, partition, expected_records) VALUES (%s,%s,%s)",
                                             (x["source_id"], x["partition"], x["expected_records"]))
    for r in acc["backfill_requests"]:
        n["backfill_requests"] += _ins(conn, "INSERT INTO backfill_requests (backfill_id, source_id, start_at, end_at, status, partitions, requested_by, requested_at, settled_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                       (r["backfill_id"], r["source_id"], r["start_at"], r["end_at"], r["status"], Jsonb(r["partitions"]), "seed",
                                        r.get("requested_at"), r.get("settled_at")))
    for r in acc["ingestion_batches"]:
        n["ingestion_batches"] += _ins(conn, "INSERT INTO ingestion_batches (batch_id, source_id, source_cursor, started_at, status, next_cursor, schema_version) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                       (r["batch_id"], r["source_id"], r["source_cursor"], r["started_at"], r["status"],
                                        cp_by_batch[r["batch_id"]]["committed_cursor"] if r["batch_id"] in cp_by_batch else None, r.get("schema_version")))
    batch_source = {b["batch_id"]: b["source_id"] for b in acc["ingestion_batches"]}
    for r in acc["raw_records"]:
        d = facts.disposition.get(r["raw_record_id"])
        n["raw_records"] += _ins(conn, "INSERT INTO raw_records (raw_record_id, batch_id, source_key, payload_hash, payload_json, disposition, reason_code) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                 (r["raw_record_id"], r["batch_id"], r.get("source_key"), r["payload_hash"], Jsonb(r["payload_json"]),
                                  d.kind if d else None, d.reason if d else None))
    for a in facts.accepted:
        n["accepted_records"] += _ins(conn, "INSERT INTO accepted_records (source_id, source_key, raw_record_id, batch_id, accepted_at, deleted_in_batch) VALUES (%s,%s,%s,%s,%s,%s)",
                                      (a.source_id, a.key, a.raw_record_id, a.batch_id, a.arrival or inputs["as_of"], a.deleted_in))
    for r in acc["quarantine_records"]:
        n["quarantine_records"] += _ins(conn, "INSERT INTO quarantine_records (quarantine_id, batch_id, source_key, reason_code, payload_hash) VALUES (%s,%s,%s,%s,%s)",
                                        (r["quarantine_id"], r["batch_id"], r.get("source_key"), r["reason_code"], r["payload_hash"]))
    for r in sorted(acc["checkpoints"], key=lambda c: (c["source_id"], c["version_number"])):      # the guard wants previous + 1 in order
        n["checkpoints"] += conn.execute(       # the guard trigger fires before ON CONFLICT, so a reload skips what exists
            "INSERT INTO checkpoints (checkpoint_id, source_id, batch_id, committed_cursor, committed_at, version_number) "
            "SELECT %s,%s,%s,%s,%s,%s WHERE NOT EXISTS (SELECT 1 FROM checkpoints WHERE checkpoint_id = %s)",
            (r["checkpoint_id"], r["source_id"], r["batch_id"], r["committed_cursor"], r["committed_at"], r["version_number"], r["checkpoint_id"])).rowcount
    for r in acc["model_definitions"]:
        n["model_definitions"] += _ins(conn, "INSERT INTO model_definitions (model_id, model_name, grain, version_number, definition, definition_hash) VALUES (%s,%s,%s,%s,%s,%s)",
                                       (r["model_id"], r["model_name"], r["grain"], r["version_number"], r["definition"], r["definition_hash"]))
    for r in acc["pipeline_runs"]:
        n["pipeline_runs"] += _ins(conn, "INSERT INTO pipeline_runs (run_id, started_at, finished_at, status, code_sha, backfill_id, included_batch_ids, scope_from) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                   (r["run_id"], r["started_at"], r.get("finished_at"), r["status"], r["code_sha"], r.get("backfill_id"),
                                    next((p["included_batch_ids"] for p in acc["publications"] if p["run_id"] == r["run_id"]), []), r.get("scope_from")))
    for r in acc["task_runs"]:
        n["task_runs"] += _ins(conn, "INSERT INTO task_runs (task_run_id, run_id, task_name, status, attempt) VALUES (%s,%s,%s,%s,%s)",
                               (r["task_run_id"], r["run_id"], r["task_name"], r["status"], int(r["attempt"])))
    for r in acc["quality_results"]:
        n["quality_results"] += _ins(conn, "INSERT INTO quality_results (quality_result_id, task_run_id, rule_name, severity, eligible_count, failure_count) VALUES (%s,%s,%s,%s,%s,%s)",
                                     (r["quality_result_id"], r["task_run_id"], r["rule_name"], r["severity"], r["eligible_count"], r["failure_count"]))
    for r in acc["publications"]:
        n["publications"] += _ins(conn, "INSERT INTO publications (publication_id, run_id, dataset_name, published_at, watermark, source_ids, included_batch_ids, content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                  (r["publication_id"], r["run_id"], r["dataset_name"], r["published_at"], r["watermark"], r["source_ids"], r["included_batch_ids"], r["content_hash"]))
    for r in acc["incidents"]:
        n["incidents"] += _ins(conn, "INSERT INTO incidents (incident_id, run_id, severity, status, opened_at, closed_at, recovery_run_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                               (r["incident_id"], r["run_id"], r["severity"], r["status"], r["opened_at"], r.get("closed_at"), r.get("recovery_run_id")))
    pm = inputs.get("processing_measurement")
    if pm and pm["batch_id"] in batch_source:
        conn.execute("INSERT INTO processing_measurements (source_id, batch_id, measured_seconds, hardware, cache_state, recorded_at) "
                     "SELECT %s, %s, %s, %s, %s, %s WHERE NOT EXISTS (SELECT 1 FROM processing_measurements WHERE batch_id = %s)",
                     (pm["source_id"], pm["batch_id"], pm["measured_seconds"], pm["hardware"], pm["cache_state"], inputs["as_of"], pm["batch_id"]))
    current = compute(acc, imp.rejected, params_of(inputs))["metrics"]["publications"]["current_publication_id"]
    if current is not None:
        conn.execute("INSERT INTO publication_pointer (id, publication_id, updated_at) VALUES (1, %s, %s) ON CONFLICT DO NOTHING", (current, inputs["as_of"]))
    insert_rejected(conn, "seed", imp.rejected)
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version, as_of) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                 (version, dataset_hash, str(inputs.get("contract_version", CONTRACT_VERSION)), inputs["as_of"]))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": n, "skipped": len(imp.rejected)}


def main(argv: list[str]) -> int:
    import json
    import os
    if not argv or not os.environ.get("DATABASE_URL"):
        print("usage: DATABASE_URL=... python data/seed.py inputs.json [--dataset-version NAME]", file=sys.stderr)
        return 2
    version = argv[argv.index("--dataset-version") + 1] if "--dataset-version" in argv else None
    inputs = json.loads(Path(argv[0]).read_text())
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        out = seed(conn, inputs, version)
    print(json.dumps({k: v for k, v in out.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
