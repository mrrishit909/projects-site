"""Shared helpers for the tests (imported, not auto-collected): fixtures, the DB fixtures, the command driver and the golden-through-the-API player.

Every database test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations`` recreates them. The tests that
need PostgreSQL FAIL (never skip) when DATABASE_URL is unset: CI and the local lab both provide it. DATABASE_URL defaults to the lab database
``postgresql://lab:lab@127.0.0.1:5432/pipeline_observatory``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("DATABASE_URL", "postgresql://lab:lab@127.0.0.1:5432/pipeline_observatory")

from api import clock  # noqa: E402
from api.app import PREFIX, create_app  # noqa: E402
from data import migrate, seed  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden"
FIXTURES = ROOT / "tests" / "fixtures"
ENGINEER = {"X-Actor-Id": "usr-eng01", "X-Actor-Role": "engineer"}
OPERATOR = {"X-Actor-Id": "usr-op01", "X-Actor-Role": "operator"}
OPERATOR2 = {"X-Actor-Id": "usr-op02", "X-Actor-Role": "operator"}
ADMIN = {"X-Actor-Id": "usr-adm01", "X-Actor-Role": "admin"}
VARIANTS = ["", "variant-rejected", "variant-empty"]
CUTOFF = "2026-10-05T00:00:00Z"


def golden_inputs(sub: str = "") -> dict[str, Any]:
    return copy.deepcopy(json.loads((GOLDEN / sub / "inputs.json").read_text()))


def golden_expected(sub: str = "") -> dict[str, Any]:
    return json.loads((GOLDEN / sub / "expected.json").read_text())


def fixture_json(rel: str) -> Any:
    return json.loads((FIXTURES / rel).read_text())


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def flat(x: Any, path: str = "") -> dict[str, Any]:
    """Every leaf of a JSON value by path (empty list/object as one leaf)."""
    if isinstance(x, dict):
        if not x:
            return {path + "{}": "empty"}
        out: dict[str, Any] = {}
        for k, v in x.items():
            out.update(flat(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(x, list):
        if not x:
            return {path + "[]": "empty"}
        out = {}
        for i, v in enumerate(x):
            out.update(flat(v, f"{path}[{i}]"))
        return out
    return {path: x}


def diff(a: Any, b: Any) -> list[str]:
    fa, fb = flat(a), flat(b)
    return sorted(k for k in set(fa) | set(fb) if fa.get(k, "<missing>") != fb.get(k, "<missing>"))


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def at(s: str) -> None:
    """Freeze the API clock at an instant (every call returns it: a command's decisions share one instant)."""
    clock.freeze(ts(s), timedelta(0))


# ---------------------------------------------------------------------------------------------------------- fixtures
@pytest.fixture
def db_url() -> Iterator[str]:
    import psycopg
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
    yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(db_url, row_factory=dict_row, autocommit=True) as c:
        yield c


@pytest.fixture
def client(db_url: str):
    from fastapi.testclient import TestClient
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


def load(conn, inputs: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """seed.seed in ONE transaction."""
    with conn.transaction():
        return seed.seed(conn, inputs, **kw)


def world(sources: tuple[str, ...] = ("src-orders", "src-refunds"), version: str = "ds-api-1", **extra: Any) -> dict[str, Any]:
    """A small empty world for the API tests: sources, one expectation (9 records for src-orders on 2026-10-04) and nothing else."""
    d = {"contract_version": 1, "as_of": CUTOFF, "cutoff": CUTOFF, "business_total_field": "amount", "freshness_timestamp_field": "event_ts",
         "partition_rule": "UTC date of the freshness timestamp field",
         "source_expectations": [{"source_id": "src-orders", "partition": "2026-10-04", "expected_records": 9},
                                 {"source_id": "src-refunds", "partition": "2026-10-04", "expected_records": 1}],
         "processing_measurement": None,
         "source_contracts": [{"source_id": s, "source_name": f"Synthetic {s}", "schema_version": "1", "expected_frequency": "hourly", "owner_id": "own-01", **extra.get(s, {})}
                              for s in sources]}
    for e in ("ingestion_batches", "raw_records", "quarantine_records", "checkpoints", "model_definitions", "pipeline_runs", "task_runs", "quality_results",
              "publications", "incidents", "backfill_requests"):
        d[e] = []
    return d


def load_world(conn, **kw: Any) -> dict[str, Any]:
    w = world(**kw)
    load(conn, w, dataset_version="ds-api-1")
    return w


_seq = {"n": 0}


def current_dataset_version() -> str:
    import psycopg
    url = os.environ.get("DATABASE_URL")
    with psycopg.connect(url) as c:
        row = c.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row[0] if row else "ds-test"


def command(client, name: str, input_: dict[str, Any], key: str | None = None, headers: dict[str, str] | None = None,
            request_id: str = "req-test", dataset_version: str | None = None):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: the operator, who may run every command)."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": dataset_version or current_dataset_version(), "idempotency_key": key, "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body, headers=OPERATOR if headers is None else headers)


def rule_ids(response) -> list[str]:
    return [d["rule_id"] for d in response.json()["error"]["details"]]


def get(client, path: str, **params):
    return client.get(f"{PREFIX}{path}", params={k: v for k, v in params.items() if v is not None})


def metrics(client, **params):
    r = get(client, "/metrics", **params)
    assert r.status_code == 200, r.text
    return r.json()


def count(conn, table: str, where: str = "true") -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table} WHERE {where}").fetchone()["n"]  # table and where are test constants


def table_digest(conn, tables: list[str]) -> dict[str, str]:
    """A hash of every row of each table: proof that a command left a table untouched."""
    out = {}
    for t in tables:
        rows = conn.execute(f"SELECT to_jsonb(x) AS j FROM {t} x ORDER BY 1").fetchall()       # table names are test constants
        out[t] = sha(json.dumps([r["j"] for r in rows], sort_keys=True, default=str))
    return out


# ---------------------------------------------------------------------------------------------------------- pipeline helpers
def payloads(inputs: dict[str, Any], batch_id: str) -> list[dict[str, Any]]:
    """The payloads of one golden batch's raw rows, in raw_record_id order (what the source would deliver)."""
    return [{"payload": r["payload_json"]} for r in sorted(inputs["raw_records"], key=lambda r: r["raw_record_id"]) if r["batch_id"] == batch_id]


def ingest(client, source_id: str, batch_id: str, records: list[dict[str, Any]], cursor: str = "cur-000", next_cursor: str | None = "cur-010",
           commit: bool = True, headers: dict[str, str] | None = None, **page: Any) -> dict[str, Any]:
    """C01 + C02 (+ C03). Returns the three response bodies' results."""
    out: dict[str, Any] = {}
    r = command(client, "fetch-source-page", {"source_id": source_id, "cursor": cursor, "batch_id": batch_id,
                                              "page": {"records": records, "next_cursor": next_cursor, **page}}, headers=headers)
    assert r.status_code == 200, r.text
    out["fetch"] = r.json()["result"]
    r = command(client, "validate-contract", {"batch_id": batch_id}, headers=headers)
    assert r.status_code == 200, r.text
    out["validate"] = r.json()["result"]
    if commit:
        r = command(client, "commit-batch", {"batch_id": batch_id}, headers=headers)
        assert r.status_code == 200, r.text
        out["commit"] = r.json()["result"]
    return out


def run_pipeline_for(client, run_id: str, batch_ids: list[str], watermark: str, publish: bool = True) -> dict[str, Any]:
    """C04 + C05 (+ C06) for one run; returns the results (the gate's may be blocked)."""
    out: dict[str, Any] = {}
    r = command(client, "transform-models", {"run_id": run_id, "batch_ids": batch_ids})
    assert r.status_code == 200, r.text
    out["transform"] = r.json()["result"]
    r = command(client, "run-quality-gate", {"run_id": run_id})
    assert r.status_code == 200, r.text
    out["gate"] = r.json()["result"]
    if publish and out["gate"]["decision"] == "allowed":
        r = command(client, "publish-snapshot", {"run_id": run_id, "watermark": watermark})
        assert r.status_code == 200, r.text
        out["publish"] = r.json()["result"]
    return out
