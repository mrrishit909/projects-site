"""Shared helpers for the tests (imported, not auto-collected): fixtures, the DB fixtures and a small world builder.

Every database test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations``
recreates them. Tests skip cleanly when DATABASE_URL is unset (the pure-domain tests never need it).
"""
from __future__ import annotations

import copy
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
SUPERVISOR = {"X-Actor-Id": "sup-1", "X-Actor-Role": "supervisor"}
ANALYST = {"X-Actor-Id": "ana-1", "X-Actor-Role": "analyst"}
ADMIN = {"X-Actor-Id": "adm-1", "X-Actor-Role": "admin"}
DAY = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)   # minute 0 of the builder's clock


def golden_inputs(sub: str = "") -> dict[str, Any]:
    return copy.deepcopy(json.loads((GOLDEN / sub / "inputs.json").read_text()))


def golden_expected(sub: str = "") -> dict[str, Any]:
    return json.loads((GOLDEN / sub / "expected.json").read_text())


def at(minute: float, base: datetime = DAY) -> str:
    """ISO instant ``minute`` minutes after 2026-07-06T09:00:00Z (seconds resolution)."""
    return (base + timedelta(seconds=round(minute * 60))).strftime("%Y-%m-%dT%H:%M:%SZ")


class World:
    """A tiny dataset: queues q-1 and q-2 (both need skill s-1), agents a-1 and a-2 (skilled, shift 09:00-17:00 with a
    30 minute break), SLA targets per priority, and the tickets and events a test adds with ``ticket`` and ``ev``."""

    def __init__(self, window: tuple[float, float] = (0, 180), cutoffs: list[float] | None = None,
                 agents: tuple[str, ...] = ("a-1", "a-2"), max_concurrent: int = 1, prefix: str = "e") -> None:
        self.n = 0
        self.prefix = prefix
        self.d: dict[str, Any] = {
            "contract_version": 1, "window_start": at(window[0]), "window_end": at(window[1]),
            "backlog_cutoffs": [at(c) for c in (cutoffs if cutoffs is not None else [window[1]])],
            "abandonable_channels": ["chat", "phone"],
            "customers": [{"customer_id": f"c-{i}", "segment": "smb", "timezone": "America/New_York",
                           "created_at": "2026-01-01T00:00:00Z", "synthetic": True} for i in range(1, 13)],
            "queues": [{"queue_id": q, "queue_name": q, "priority_policy": "fifo_within_priority",
                        "calendar_id": "cal-1", "active": True} for q in ("q-1", "q-2")],
            "tickets": [], "ticket_events": [],
            "agents": [{"agent_id": a, "agent_name": a, "timezone": "UTC", "employment_type": "full_time",
                        "active": True, "max_concurrent": max_concurrent} for a in agents],
            "skills": [{"skill_id": "s-1", "skill_name": "General", "description": None, "active": True,
                        "created_at": "2026-01-01T00:00:00Z"}],
            "agent_skills": [{"agent_skill_id": f"as-{a}", "agent_id": a, "skill_id": "s-1", "proficiency": 4,
                              "effective_from": "2026-01-01T00:00:00Z"} for a in agents],
            "queue_skills": [{"queue_id": q, "skill_id": "s-1"} for q in ("q-1", "q-2")],
            "shifts": [{"shift_id": f"sh-{a}", "agent_id": a, "starts_at": at(0), "ends_at": at(480),
                        "break_minutes": 30} for a in agents],
            "sla_policies": [{"sla_policy_id": f"sla-{p}", "priority": p, "first_response_minutes": f,
                              "resolution_minutes": r, "calendar_id": "cal-1"}
                             for p, f, r in (("P1", 5, 30), ("P2", 15, 60), ("P3", 30, 120))],
            "surveys": [], "simulation_runs": [],
        }

    def ticket(self, tid: str, minute: float = 0, priority: str = "P2", queue: str = "q-1", channel: str = "email",
               customer: str | None = None, created: str | None = None) -> str:
        self.n += 1
        self.d["tickets"].append({"ticket_id": tid, "customer_id": customer or f"c-{(self.n % 12) + 1}",
                                  "queue_id": queue, "priority": priority, "created_at": created or at(minute),
                                  "channel": channel})
        self.ev(tid, "created", minute if created is None else 0, queue=queue)
        return tid

    def ev(self, tid: str, etype: str, minute: float, actor: str | None = "auto", agent: str | None = None,
           queue: str | None = None, when: str | None = None) -> dict[str, Any]:
        if actor == "auto":
            actor = agent
        row = {"event_id": f"{self.prefix}-{len(self.d['ticket_events']) + 1:04d}", "ticket_id": tid, "event_type": etype,
               "occurred_at": when or at(minute), "actor_id": actor, "queue_id": queue, "agent_id": agent}
        self.d["ticket_events"].append(row)
        return row

    def serve(self, tid: str, start: float, end: float | None, agent: str = "a-1", reply: bool = True,
              queue: str = "q-1") -> None:
        self.ev(tid, "service_started", start, agent=agent, queue=queue)
        if reply:
            self.ev(tid, "replied_human", start, agent=agent, queue=queue)
        if end is not None:
            self.ev(tid, "resolved", end, agent=agent, queue=queue)

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self.d)


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


@pytest.fixture
def seeded(conn):
    """The golden dataset loaded (3 resolved tickets, one agent, one queue, sim-001 and its 6 events)."""
    seed.seed(conn, golden_inputs())
    return conn


def load(conn, world: World) -> dict[str, Any]:
    """Seed a World through the validating seed (the same rules as the API)."""
    return seed.seed(conn, world.data())


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]  # table is a test constant


_seq = {"n": 0}


def command(client, name: str, input_: dict[str, Any], key: str | None = None,
            headers: dict[str, str] | None = None, request_id: str = "req-test"):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: sup-1, supervisor)."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": "ds-test", "idempotency_key": key, "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body, headers=SUPERVISOR if headers is None else headers)


def rule_ids(response) -> list[str]:
    return [d["rule_id"] for d in response.json()["error"]["details"]]


def get(client, path: str, **params):
    return client.get(f"{PREFIX}{path}", params=params)


def events_of(conn, tid: str) -> list[tuple[str, str]]:
    return [(r["event_type"], r["occurred_at"].strftime("%H:%M")) for r in conn.execute(
        "SELECT event_type, occurred_at FROM ticket_events WHERE ticket_id = %s ORDER BY event_seq", (tid,)).fetchall()]
