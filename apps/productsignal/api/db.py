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
from productsignal.metrics import select_funnel  # noqa: F401  (re-exported for the read side)
from productsignal.models import FunnelDef, Plan, Population, Windows, default_windows, parse_funnel, parse_plan, parse_windows
from productsignal.timeutil import iso_z
from psycopg.rows import dict_row

Row = dict[str, Any]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect(autocommit: bool = False) -> psycopg.Connection[Row]:
    # UTC session so TIMESTAMPTZ comparisons and local-date arithmetic never depend on the server's zone.
    return psycopg.connect(database_url(), row_factory=dict_row, options="-c timezone=UTC", autocommit=autocommit)


@contextmanager
def transaction() -> Iterator[psycopg.Connection[Row]]:
    """One transaction: commit on success, rollback on error, always close."""
    with _connect() as conn:
        yield conn


@contextmanager
def autocommit() -> Iterator[psycopg.Connection[Row]]:
    """A separate connection whose statements commit at once: used to keep a refusal or a rejected record when the
    command's own transaction is about to be rolled back."""
    with _connect(True) as conn:
        yield conn


def jsonable(value: Any) -> Any:
    """Row value to JSON: Decimal exactly as stored, timestamps as UTC ISO-8601 with Z."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def jsonable_row(row: Row) -> Row:
    return {k: jsonable(v) for k, v in row.items()}


_ROWS = {
    "accounts": "SELECT * FROM accounts ORDER BY account_id",
    "users": "SELECT * FROM users ORDER BY user_id",
    "identity_links": "SELECT * FROM identity_links ORDER BY identity_link_id",
    "sessions": "SELECT * FROM sessions ORDER BY session_id",
    "events": "SELECT event_id, user_id, anonymous_id, event_name, event_at, received_at FROM events ORDER BY event_id",
    "event_properties": "SELECT * FROM event_properties ORDER BY property_id",
    "subscriptions": "SELECT * FROM subscriptions ORDER BY subscription_id",
    "experiment_versions": "SELECT * FROM experiment_versions ORDER BY experiment_version_id",
    "assignments": "SELECT * FROM assignments ORDER BY assignment_id",
    "exposures": "SELECT * FROM exposures ORDER BY exposure_id",
    "metric_observations": "SELECT * FROM metric_observations ORDER BY observation_id",
    "analysis_runs": "SELECT * FROM analysis_runs ORDER BY analysis_id",
}


def load_plans(conn: psycopg.Connection[Row]) -> list[Plan]:
    return [parse_plan(r["plan"], r["config_hash"]) for r in
            conn.execute("SELECT experiment_version_id, plan, config_hash FROM analysis_plans ORDER BY experiment_version_id").fetchall()]


def load_funnels(conn: psycopg.Connection[Row]) -> list[FunnelDef]:
    return [parse_funnel({"definition_id": r["definition_id"], "version": r["version"], "steps": list(r["steps"]),
                          "max_gap_hours": r["max_gap_hours"], "from": r["window_from"], "to": r["window_to"]}, r["created_at"])
            for r in conn.execute("SELECT * FROM funnel_definitions ORDER BY definition_id, version").fetchall()]


def load_windows(conn: psycopg.Connection[Row], cutoff: datetime) -> Windows:
    row = conn.execute("SELECT windows FROM metric_config WHERE id = 1").fetchone()
    return parse_windows(row["windows"]) if row else default_windows(cutoff)


def load_population(conn: psycopg.Connection[Row]) -> Population:
    """Assemble the domain's population from the tables (rows are trusted; the same parsers as ingest run over them)."""
    rows = {ent: [dict(r) for r in conn.execute(sql).fetchall()] for ent, sql in _ROWS.items()}
    return Population.from_rows(rows, load_plans(conn), load_funnels(conn))
