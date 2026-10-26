"""psycopg helpers: one connection and one transaction per request.

``transaction()`` commits when the block exits normally and rolls back on any exception, so a command's
effects and its audit event are atomic.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from serviceflow.models import Population
from serviceflow.timeutil import iso_z

Row = dict[str, Any]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect() -> psycopg.Connection[Row]:
    # UTC session so TIMESTAMPTZ comparisons never depend on the server's zone.
    return psycopg.connect(database_url(), row_factory=dict_row, options="-c timezone=UTC")


@contextmanager
def transaction() -> Iterator[psycopg.Connection[Row]]:
    """One transaction: commit on success, rollback on error, always close."""
    with _connect() as conn:
        yield conn


def jsonable(value: Any) -> Any:
    """Row value to JSON: Decimal exactly as stored (NUMERIC(14,4) minutes keep their 4 decimals), timestamps as UTC
    ISO-8601 with Z."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def jsonable_row(row: Row) -> Row:
    return {k: jsonable(v) for k, v in row.items()}


_ROWS = {
    "customers": "SELECT * FROM customers ORDER BY customer_id",
    "queues": "SELECT * FROM queues ORDER BY queue_id",
    "tickets": "SELECT * FROM tickets ORDER BY ticket_id",
    "ticket_events": ("SELECT event_id, ticket_id, event_type, occurred_at, actor_id, queue_id, agent_id "
                      "FROM ticket_events ORDER BY event_seq"),
    "agents": "SELECT * FROM agents ORDER BY agent_id",
    "skills": "SELECT * FROM skills ORDER BY skill_id",
    "agent_skills": "SELECT * FROM agent_skills ORDER BY agent_skill_id",
    "queue_skills": "SELECT * FROM queue_skills ORDER BY queue_id, skill_id",
    "shifts": "SELECT * FROM shifts ORDER BY shift_id",
    "sla_policies": "SELECT * FROM sla_policies ORDER BY sla_policy_id",
    "surveys": "SELECT * FROM surveys ORDER BY survey_id",
}


def load_population(conn: psycopg.Connection[Row]) -> Population:
    """Assemble the domain's population from the tables (rows are trusted: no ingest rules are re-applied)."""
    return Population.from_rows({ent: [dict(r) for r in conn.execute(sql).fetchall()] for ent, sql in _ROWS.items()})
