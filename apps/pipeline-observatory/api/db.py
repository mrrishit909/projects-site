"""psycopg helpers: one connection and one transaction per request, and the domain's rows assembled from the tables.

``transaction()`` commits when the block exits normally and rolls back on any exception, so a command's effects and its audit event are atomic.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from pipeline_observatory.contract import ENTITIES
from pipeline_observatory.timeutil import iso_z
from psycopg.rows import dict_row

Row = dict[str, Any]
Conn = psycopg.Connection[Row]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect(autocommit: bool = False) -> Conn:
    # UTC session so TIMESTAMPTZ comparisons never depend on the server's zone.
    return psycopg.connect(database_url(), row_factory=dict_row, options="-c timezone=UTC", autocommit=autocommit)


@contextmanager
def transaction() -> Iterator[Conn]:
    """One transaction: commit on success, rollback on error, always close."""
    with _connect() as conn:
        yield conn


@contextmanager
def autocommit() -> Iterator[Conn]:
    """A separate connection whose statements commit at once: keeps a refusal in the audit trail when the command's own transaction is
    about to be rolled back."""
    with _connect(True) as conn:
        yield conn


def jsonable(value: Any) -> Any:
    """Row value to JSON: Decimal exactly as stored (a string), timestamps as UTC ISO-8601 with Z. Never a float."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    return value


def jsonable_row(row: Row) -> Row:
    return {k: jsonable(v) for k, v in row.items()}


def current_dataset_version(conn: Conn) -> str:
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row["dataset_version"] if row else "unversioned"


_SELECTS = {
    "source_contracts": "SELECT source_id, source_name, schema_version, expected_frequency, owner_id FROM source_contracts",
    "ingestion_batches": "SELECT batch_id, source_id, source_cursor, started_at, status, schema_version FROM ingestion_batches",
    "raw_records": "SELECT raw_record_id, batch_id, source_key, payload_hash, payload_json FROM raw_records",
    "quarantine_records": "SELECT quarantine_id, batch_id, source_key, reason_code, payload_hash FROM quarantine_records",
    "checkpoints": "SELECT checkpoint_id, source_id, batch_id, committed_cursor, committed_at, version_number FROM checkpoints",
    "model_definitions": "SELECT model_id, model_name, grain, version_number, definition, definition_hash FROM model_definitions",
    "pipeline_runs": "SELECT run_id, started_at, finished_at, status, code_sha, backfill_id, scope_from FROM pipeline_runs",
    "task_runs": "SELECT task_run_id, run_id, task_name, status, attempt FROM task_runs",
    "quality_results": "SELECT quality_result_id, task_run_id, rule_name, severity, eligible_count, failure_count FROM quality_results",
    "publications": "SELECT publication_id, run_id, dataset_name, published_at, watermark, source_ids, included_batch_ids, content_hash FROM publications",
    "incidents": "SELECT incident_id, run_id, severity, status, opened_at, closed_at, recovery_run_id FROM incidents",
    "backfill_requests": "SELECT backfill_id, source_id, start_at, end_at, status, partitions, requested_at, settled_at FROM backfill_requests",
}
_INSTANTS = ("started_at", "finished_at", "committed_at", "published_at", "watermark", "opened_at", "closed_at", "start_at", "end_at", "scope_from",
            "requested_at", "settled_at")


def load_rows(conn: Conn) -> dict[str, list[Row]]:
    """The domain's entity rows from the tables (the shape of inputs.json: instants as ISO strings, attempts as integers)."""
    acc: dict[str, list[Row]] = {}
    for ent in ENTITIES:
        key = {"source_contracts": "source_id", "ingestion_batches": "batch_id", "raw_records": "raw_record_id", "quarantine_records": "quarantine_id",
               "checkpoints": "checkpoint_id", "model_definitions": "model_id", "pipeline_runs": "run_id", "task_runs": "task_run_id",
               "quality_results": "quality_result_id", "publications": "publication_id", "incidents": "incident_id", "backfill_requests": "backfill_id"}[ent]
        rows = conn.execute(f'{_SELECTS[ent]} ORDER BY {key} COLLATE "C"').fetchall()      # table and key come from constants above
        out = []
        for r in rows:
            r = {k: (iso_z(v) if k in _INSTANTS and v is not None else v) for k, v in r.items()}
            out.append(r)
        acc[ent] = out
    return acc


def load_rejected(conn: Conn) -> list[Row]:
    rows = conn.execute("SELECT entity, id, reason_code, raw_row, ordinal, created_at FROM rejected_records").fetchall()
    order = {e: i for i, e in enumerate(ENTITIES)}
    rows.sort(key=lambda r: (order.get(r["entity"], 99), r["created_at"], r["id"], r["reason_code"], r["ordinal"]))
    return [{"entity": r["entity"], "id": r["id"], "status": "rejected", "reason_code": r["reason_code"], "raw_row": r["raw_row"]} for r in rows]


def load_params(conn: Conn, cutoff: str) -> Row:
    expectations = [{"source_id": r["source_id"], "partition": r["partition"], "expected_records": r["expected_records"]}
                    for r in conn.execute("SELECT * FROM source_expectations ORDER BY source_id COLLATE \"C\", partition").fetchall()]
    m = conn.execute("SELECT source_id, batch_id, measured_seconds, hardware, cache_state FROM processing_measurements "
                     "ORDER BY recorded_at DESC, measurement_id DESC LIMIT 1").fetchone()
    pm = None if m is None else {"source_id": m["source_id"], "batch_id": m["batch_id"], "measured_seconds": format(m["measured_seconds"], "f"),
                                 "hardware": m["hardware"], "cache_state": m["cache_state"]}
    totals = {r["publication_id"]: r["total"] for r in conn.execute(
        "SELECT p.publication_id, coalesce(sum(o.amount), 0) AS total FROM publications p JOIN model_outputs o ON o.run_id = p.run_id GROUP BY p.publication_id").fetchall()}
    return {"contract_version": 1, "as_of": cutoff, "cutoff": cutoff, "business_total_field": "amount", "source_expectations": expectations,
            "processing_measurement": pm, "published_totals": totals}      # the stored published table, where the API built one (seeded fixtures have none)
