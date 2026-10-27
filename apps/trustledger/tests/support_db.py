"""Shared helpers for the tests (imported, not auto-collected): fixtures, the DB fixtures, a small-world builder and the command driver.

Every database test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations`` recreates them. Tests
skip cleanly when DATABASE_URL is unset (the pure-domain tests never need it). The fixture's synthetic truth is loaded into the
verification layer's own table (``verification_truth``) by ``load`` and by nothing else.
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
TRUTH_SQL = (ROOT / "data" / "sql" / "verification_truth.sql").read_text()
# The actors are registered owners of the golden register and their role is the register's (D-10 R7-03): own-01 analyst (the proposer of every
# golden candidate), own-02 and own-03 stewards, own-04 admin, own-05 a steward who is inactive.
ANALYST = {"X-Actor-Id": "own-01", "X-Actor-Role": "analyst"}
STEWARD = {"X-Actor-Id": "own-02", "X-Actor-Role": "steward"}
STEWARD2 = {"X-Actor-Id": "own-03", "X-Actor-Role": "steward"}
ADMIN = {"X-Actor-Id": "own-04", "X-Actor-Role": "admin"}
INACTIVE = {"X-Actor-Id": "own-05", "X-Actor-Role": "steward"}
VARIANTS = ["", "variant-rejected", "variant-empty"]


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


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------------- small worlds
class World:
    """A small dataset builder for rule tests (the shape of inputs.json), with the two fixture weight versions and checklist cl-1."""

    def __init__(self, as_of: str = "2026-10-05T00:00:00Z") -> None:
        self.d: dict[str, Any] = {
            "contract_version": 1, "as_of": as_of, "whitespace_policy": {"name": "trim_empty_is_missing", "trim_characters": " \t\r\n"},
            "weight_version": "w2",
            "weight_versions": [
                {"weight_version": "w1", "valid_from": "2026-01-01T00:00:00Z",
                 "weights": {"completeness": "0.400000", "validity": "0.300000", "uniqueness": "0.200000", "relationship": "0.050000", "timeliness": "0.050000"}},
                {"weight_version": "w2", "valid_from": "2026-09-01T00:00:00Z",
                 "weights": {"completeness": "0.250000", "validity": "0.250000", "uniqueness": "0.250000", "relationship": "0.150000", "timeliness": "0.100000"}}],
            "checklist_version": "cl-1", "checklist_versions": [{"checklist_version": "cl-1", "items": ["definition", "grain", "source_fields", "owner", "refresh"]}],
            "probes": {"definition_at": "2026-08-01T00:00:00Z"},
            "owners": [], "datasets": [], "fields": [], "quality_rules": [], "rule_runs": [], "issues": [], "lineage_edges": [],
            "metric_versions": [], "definition_changes": [], "customer_records": [], "match_candidates": [], "merge_decisions": [],
            "dataset_rows": {}, "synthetic_truth": {"note": "verification only", "true_entity": {}}}
        self.n = 0

    def owner(self, oid: str, role: str = "steward", active: bool = True, deactivated_at: str | None = None) -> str:
        self.d["owners"].append({"owner_id": oid, "owner_name": f"Synthetic {oid}", "team": "Data", "role": role, "active": active, "deactivated_at": deactivated_at})
        return oid

    def dataset(self, dsid: str, owner: str, rows: list[dict[str, Any]] | None = None, monitored: bool = False, **kw: Any) -> str:
        sched = ({"refresh_timezone": "UTC", "refresh_local_time": "06:00", "refresh_grace_minutes": 60, "last_refreshed_at": "2026-10-04T06:10:00Z"}
                 if monitored else {"refresh_timezone": None, "refresh_local_time": None, "refresh_grace_minutes": None, "last_refreshed_at": None})
        self.d["datasets"].append({"dataset_id": dsid, "dataset_name": dsid, "source_system": "crm", "owner_id": owner, "classification": "internal",
                                   "registered_at": "2026-06-01T00:00:00Z", "monitored": monitored, **sched, **kw})
        if rows is not None:
            self.d["dataset_rows"][dsid] = rows
        return dsid

    def rule(self, rid: str, dsid: str, rtype: str, definition: dict[str, Any], severity: str = "medium", version: int = 1, **kw: Any) -> str:
        self.d["quality_rules"].append({"rule_id": rid, "dataset_id": dsid, "field_id": None, "rule_type": rtype, "severity": severity,
                                        "version_number": version, "status": "active", "disabled_at": None, "disabled_reason": None,
                                        "definition": definition, **kw})
        return rid

    def run(self, rid: str, rule: str, at: str, eligible: int, failures: int, version: int = 1, kind: str = "scheduled", for_issue: str | None = None) -> str:
        self.d["rule_runs"].append({"rule_run_id": rid, "rule_id": rule, "rule_version": version, "weight_version": "w2", "kind": kind, "run_at": at,
                                    "eligible_count": eligible, "failure_count": failures, "rerun_for_issue": for_issue})
        return rid

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self.d)


def rows_of(field: str, values: list[Any], key: str = "row_id") -> list[dict[str, Any]]:
    return [{key: f"r-{i + 1:04d}", field: v} for i, v in enumerate(values)]


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
        conn.execute(TRUTH_SQL)
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


def load(conn, inputs: dict[str, Any], truth: bool = True, **kw: Any) -> dict[str, Any]:
    """seed.seed in ONE transaction, then (``truth``) the fixture's synthetic truth into the verification layer's table. The seeder
    itself never loads the truth."""
    with conn.transaction():
        out = seed.seed(conn, inputs, **kw)
        if truth:
            for rec, ent in ((inputs.get("synthetic_truth") or {}).get("true_entity") or {}).items():
                conn.execute("INSERT INTO verification_truth VALUES (%s, %s) ON CONFLICT DO NOTHING", (rec, ent))
    return out


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


def command(client, name: str, input_: dict[str, Any], key: str | None = None, headers: dict[str, str] | None = None,
            request_id: str = "req-test", dataset_version: str | None = None):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: the steward)."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": dataset_version or current_dataset_version(), "idempotency_key": key, "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body, headers=STEWARD if headers is None else headers)


def publish_through_review(client, pub: dict[str, Any], reason: str = "reviewed and published", author=None, reviewer=None):
    """C02 in its three steps (draft, reviewed by someone else, published): returns the response of the last step. Defaults: own-02 drafts and
    publishes, own-03 reviews (D-10 R7-12)."""
    author, reviewer = author or STEWARD, reviewer or STEWARD2
    steps = [("draft", author), ("reviewed", reviewer), ("published", author)]
    out = None
    for status, who in steps:
        out = command(client, "publish-definition", {**pub, "status": status, "reason": reason}, headers=who)
        if out.status_code != 200:
            return out
    return out


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
