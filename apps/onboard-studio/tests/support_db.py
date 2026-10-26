"""Shared helpers for the database-backed tests (imported, not auto-collected).

Every test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations`` recreates
them. Tests skip cleanly when DATABASE_URL is unset.
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
OPS = {"X-Actor-Id": "ops-2", "X-Actor-Role": "ops"}
REVIEWER = {"X-Actor-Id": "rev-1", "X-Actor-Role": "reviewer"}
ADMIN = {"X-Actor-Id": "adm-1", "X-Actor-Role": "admin"}


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
    """The golden dataset loaded (workflow wfv-001 published, case-001 completed)."""
    seed.seed(conn, golden_inputs())
    return conn


def count(conn: psycopg.Connection[Any], table: str) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]  # table is a test constant


_seq = {"n": 0}


def command(client, name: str, input_: dict[str, Any], key: str | None = None,
            headers: dict[str, str] | None = None, request_id: str = "req-test"):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: ops-2, ops)."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": "ds-test", "idempotency_key": key, "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body, headers=OPS if headers is None else headers)


def rule_ids(response) -> list[str]:
    return [d["rule_id"] for d in response.json()["error"]["details"]]


def open_case(client, case_id: str = "case-100", at: str = "2026-03-10T09:00:00Z",
              assignments: dict[str, str] | None = None):
    """C01 on the golden workflow: sd-001 starts ready, sd-002 starts blocked."""
    return command(client, "create-case", {
        "case_id": case_id, "organization_id": "org-001", "workflow_version_id": "wfv-001", "occurred_at": at,
        "assignments": assignments if assignments is not None else {"sd-001": "ops-1", "sd-002": "ops-1"}})


def step_id(case_id: str, sd: str) -> str:
    return f"{case_id}:{sd}"


def drive_to_completion(client, case_id: str = "case-100", day: str = "2026-03-10") -> None:
    """open (09:00) -> submit+accept identity_proof -> approve sd-001 -> unlock + submit + approve sd-002 -> complete."""
    def at(hhmm: str) -> str:
        return f"{day}T{hhmm}:00Z"
    assert open_case(client, case_id, at("09:00")).status_code == 200
    s1, s2 = step_id(case_id, "sd-001"), step_id(case_id, "sd-002")
    steps = [
        ("submit-document", {"case_id": case_id, "document_type": "identity_proof", "step_instance_id": s1,
                             "occurred_at": at("09:05")}, OPS),
        ("accept-document", {"case_id": case_id, "document_type": "identity_proof", "occurred_at": at("09:10")}, REVIEWER),
        ("approve-step", {"step_instance_id": s1, "expected_version": 1, "occurred_at": at("09:20")}, OPS),
        ("unlock-dependent-step", {"step_instance_id": s2, "occurred_at": at("09:25")}, OPS),
        ("submit-document", {"case_id": case_id, "document_type": "approval_form", "step_instance_id": s2,
                             "occurred_at": at("09:30")}, OPS),
        ("approve-step", {"step_instance_id": s2, "expected_version": 1, "occurred_at": at("09:40")}, REVIEWER),
        ("complete-case", {"case_id": case_id, "occurred_at": at("09:45")}, REVIEWER),
    ]
    for name, body, headers in steps:
        r = command(client, name, body, headers=headers)
        assert r.status_code == 200, (name, r.status_code, r.text)
