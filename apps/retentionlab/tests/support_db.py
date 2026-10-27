"""Shared helpers for the tests (imported, not auto-collected): fixtures, the DB fixtures and the command driver.

Every database test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations`` recreates them. Tests
skip cleanly ONLY when DATABASE_URL is unset (the pure-domain tests never need it); CI and the local runs set it, so nothing is skipped.
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

from api.app import PREFIX, create_app  # noqa: E402
from data import migrate, seed  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden"
SCIENTIST = {"X-Actor-Id": "usr-scientist01", "X-Actor-Role": "scientist"}
SCIENTIST2 = {"X-Actor-Id": "usr-scientist02", "X-Actor-Role": "scientist"}
ANALYST = {"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "analyst"}
ADMIN = {"X-Actor-Id": "usr-adm01", "X-Actor-Role": "admin"}
VARIANTS = ["", "variant-rejected", "variant-empty"]
JAN, FEB = "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"


def golden_inputs(sub: str = "") -> dict[str, Any]:
    return copy.deepcopy(json.loads((GOLDEN / sub / "inputs.json").read_text()))


def golden_expected(sub: str = "") -> dict[str, Any]:
    return json.loads((GOLDEN / sub / "expected.json").read_text())


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


def has_float(x: Any) -> bool:
    if isinstance(x, float):
        return True
    if isinstance(x, dict):
        return any(has_float(v) for v in x.values())
    if isinstance(x, list):
        return any(has_float(v) for v in x)
    return False


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------------- fixtures
@pytest.fixture
def db_url() -> Iterator[str]:
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
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


def count(conn, table: str, where: str = "true") -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table} WHERE {where}").fetchone()["n"]  # table and where are test constants


_seq = {"n": 0}


def current_dataset_version() -> str:
    """The dataset_version the database names now ("ds-test" when none): commands carry the current version, as a client that has
    just read the data would (a stale version is 409)."""
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "ds-test"
    with psycopg.connect(url) as c:
        row = c.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row[0] if row else "ds-test"


def no_float(response) -> None:
    """No API body ever carries a JSON float (D-04): every number is an integer, every decimal a string."""
    json.loads(response.text, parse_float=lambda lit: (_ for _ in ()).throw(AssertionError(f"float {lit} in {response.request.url}")))


def command(client, name: str, input_: dict[str, Any], key: str | None = None, headers: dict[str, str] | None = None,
            request_id: str = "req-test", dataset_version: str | None = None):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: the scientist)."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": dataset_version or current_dataset_version(), "idempotency_key": key, "input": input_}
    r = client.post(f"{PREFIX}/commands/{name}", json=body, headers=SCIENTIST if headers is None else headers)
    no_float(r)
    return r


def rule_ids(response) -> list[str]:
    return [d["rule_id"] for d in response.json()["error"]["details"]]


def offending(response) -> list[dict[str, str]]:
    return [o for d in response.json()["error"]["details"] for o in d.get("context", {}).get("offending", [])]


def get(client, path: str, _server_clock: bool = False, **params):
    """GET one route. A report read at ``as_of`` is a read made AFTER that instant (D-09, R10-01: an as_of later than the server clock is refused
    AS_OF_IN_FUTURE), so the frozen clock is moved to an hour after the as_of for the duration of the call and then put back, unless
    ``_server_clock`` asks for the clock as it is (the tests of the refusal)."""
    from api import clock
    moved = None
    if path == "/metrics" and params.get("as_of") and not _server_clock and clock._next is not None:
        try:
            later = ts(params["as_of"]) + timedelta(hours=1)
        except ValueError:                                  # an invalid as_of is the test's point: leave the clock alone
            later = None
        if later is not None:
            moved = (clock._next, clock._step)
            clock.freeze(later, moved[1])
    try:
        r = client.get(f"{PREFIX}{path}", params={k: v for k, v in params.items() if v is not None})
    finally:
        if moved is not None:
            clock.freeze(*moved)
    no_float(r)
    return r


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


BUSINESS_TABLES = ["accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels",
                   "training_runs", "predictions", "intervention_scenarios", "outreach_events", "split_assignments", "scoring_publications",
                   "model_preprocessing", "model_coefficients", "calibration_maps"]
