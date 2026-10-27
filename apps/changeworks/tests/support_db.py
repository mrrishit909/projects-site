"""Shared helpers for the tests (imported, not auto-collected): fixtures, the DB fixtures, a small-world builder and the command driver.

Every database test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations`` recreates them. The database tests need
DATABASE_URL (CI provides postgres:16; locally ``postgresql://lab:lab@127.0.0.1:5432/changeworks``); without it they FAIL loudly rather than skip, so a
green run always means the database was exercised. The pure-domain tests never need it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from api.app import PREFIX, create_app  # noqa: E402
from data import migrate, seed  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden"
FIXTURES = ROOT / "tests" / "fixtures"
ANALYST = {"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "analyst"}
SPONSOR = {"X-Actor-Id": "usr-sponsor01", "X-Actor-Role": "sponsor"}
SPONSOR2 = {"X-Actor-Id": "usr-sponsor02", "X-Actor-Role": "sponsor"}
ADMIN = {"X-Actor-Id": "usr-adm01", "X-Actor-Role": "admin"}
VARIANTS = ["", "variant-rejected", "variant-empty"]


def golden_inputs(sub: str = "") -> dict[str, Any]:
    return copy.deepcopy(json.loads((GOLDEN / sub / "inputs.json").read_text()))


def golden_expected(sub: str = "") -> dict[str, Any]:
    return json.loads((GOLDEN / sub / "expected.json").read_text())


def fixture(name: str) -> dict[str, Any]:
    """A small fixture of tests/fixtures/ (the shape of inputs.json, or a patch document for the adversarial pairs)."""
    return copy.deepcopy(json.loads((FIXTURES / name).read_text()))


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


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------------- fixtures
def _url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL is not set: the database tests do not skip (postgresql://lab:lab@127.0.0.1:5432/changeworks)", pytrace=False)
    return url


@pytest.fixture
def db_url() -> Iterator[str]:
    import psycopg
    url = _url()
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
    """seed.seed in ONE transaction (the initiatives' foreign key to the approved baseline is checked at commit)."""
    with conn.transaction():
        return seed.seed(conn, inputs, **kw)


def count(conn, table: str, where: str = "true") -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table} WHERE {where}").fetchone()["n"]  # table and where are test constants


_seq = {"n": 0}


def current_dataset_version() -> str:
    """The dataset_version the database names now ("ds-test" when none): commands carry the current version, as a client that has just read the data would."""
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "ds-test"
    with psycopg.connect(url) as c:
        row = c.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row[0] if row else "ds-test"


def command(client, name: str, input_: dict[str, Any], key: str | None = None, headers: dict[str, str] | None = None,
            request_id: str = "req-test", dataset_version: str | None = None):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: the sponsor, who may run every command)."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": dataset_version or current_dataset_version(), "idempotency_key": key, "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body, headers=SPONSOR if headers is None else headers)


def rule_ids(response) -> list[str]:
    return [d["rule_id"] for d in response.json()["error"]["details"]]


def get(client, path: str, **params):
    return client.get(f"{PREFIX}{path}", params={k: v for k, v in params.items() if v is not None})


def metrics(client, **params):
    r = get(client, "/metrics", **params)
    assert r.status_code == 200, r.text
    return r.json()


def table_digest(conn, tables: list[str]) -> dict[str, str]:
    """A hash of every row of each table: proof that a command left a table untouched."""
    out = {}
    for t in tables:
        rows = conn.execute(f"SELECT to_jsonb(x) AS j FROM {t} x ORDER BY 1").fetchall()       # table names are test constants
        out[t] = sha(json.dumps([r["j"] for r in rows], sort_keys=True, default=str))
    return out
