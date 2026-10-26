"""Shared helpers for the database-backed tests (imported, not auto-collected).

Every test gets a clean schema: ``migrate.reset`` drops the project's tables and
``apply_migrations`` recreates them. Tests skip cleanly when DATABASE_URL is unset.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import psycopg
import pytest
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from api.app import PREFIX, create_app  # noqa: E402
from data import migrate, seed  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden"
HEADERS = {"X-Actor-Id": "analyst-1", "X-Actor-Role": "analyst"}


def golden_inputs(returns: bool = False, costs: bool = False) -> dict[str, Any]:
    """Golden inputs; by default without returns and without pre-set cost_version_id."""
    data = copy.deepcopy(json.loads((GOLDEN / "inputs.json").read_text()))
    if not returns:
        data["returns"] = []
    if not costs:
        for sl in data["shipment_lines"]:
            sl.pop("cost_version_id", None)
    return data


def expected() -> dict[str, Any]:
    return json.loads((GOLDEN / "expected.json").read_text())


@pytest.fixture
def db_url() -> Iterator[str]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
    yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(db_url, row_factory=dict_row, autocommit=True) as c:
        yield c


@pytest.fixture
def client(db_url: str):
    from fastapi.testclient import TestClient
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


def seed_db(conn: psycopg.Connection[Any], inputs: dict[str, Any]) -> dict[str, Any]:
    out = seed.seed(conn, inputs)
    return out


def count(conn: psycopg.Connection[Any], table: str) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]  # table is a test constant


_seq = {"n": 0}


def command(client, name: str, input_: dict[str, Any], key: str | None = None,
            headers: dict[str, str] | None = None, request_id: str = "req-test"):
    """POST one command with a fresh idempotency key unless ``key`` is given."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": "ds-test", "idempotency_key": key,
            "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body,
                       headers=HEADERS if headers is None else headers)
