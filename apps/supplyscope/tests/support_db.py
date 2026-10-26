"""Shared helpers for the database-backed tests (imported, not auto-collected).

Every test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations`` recreates them.
Tests skip cleanly when DATABASE_URL is unset.
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
PLANNER = {"X-Actor-Id": "plan-1", "X-Actor-Role": "planner"}
BUYER = {"X-Actor-Id": "buy-1", "X-Actor-Role": "buyer"}
ADMIN = {"X-Actor-Id": "adm-1", "X-Actor-Role": "admin"}
AS_OF = "2026-03-31T23:59:59Z"


def golden_inputs(sub: str = "") -> dict[str, Any]:
    return copy.deepcopy(json.loads((GOLDEN / sub / "inputs.json").read_text()))


def golden_expected(sub: str = "") -> dict[str, Any]:
    return json.loads((GOLDEN / sub / "expected.json").read_text())


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


@pytest.fixture
def seeded(conn):
    """The golden dataset loaded (one product, one location, one confirmed order of 30, ROP 70 / target 120)."""
    seed.seed(conn, golden_inputs())
    return conn


def count(conn: psycopg.Connection[Any], table: str) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]  # table is a test constant


_seq = {"n": 0}


def current_dataset_version() -> str:
    """The dataset_version a well-behaved client sends (D-07): the newest dataset_versions row, else 'ds-test'."""
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True) as c:
        row = c.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC "
                        "LIMIT 1").fetchone()
    return row["dataset_version"] if row else "ds-test"


def command(client, name: str, input_: dict[str, Any], key: str | None = None,
            headers: dict[str, str] | None = None, request_id: str = "req-test", dataset_version: str | None = None):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: plan-1, planner). The
    request carries the current dataset_version unless ``dataset_version`` says otherwise."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": dataset_version or current_dataset_version(),
            "idempotency_key": key, "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body, headers=PLANNER if headers is None else headers)


def rule_ids(response) -> list[str]:
    return [d["rule_id"] for d in response.json()["error"]["details"]]


def get(client, path: str, **params):
    return client.get(f"{PREFIX}{path}", params=params)


def add_scenario(conn, scenario_id: str = "sc-1", target: str = "0.95", policy: str = "backlog", seed_: int = 7,
                 replications: int = 2):
    conn.execute("INSERT INTO policy_scenarios VALUES (%s, %s, %s, %s, %s, 3, %s)",
                 (scenario_id, f"Scenario {scenario_id}", target, policy, seed_, replications))
