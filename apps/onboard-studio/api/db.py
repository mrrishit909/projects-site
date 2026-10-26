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
from onboard_studio.models import Population
from onboard_studio.timeutil import iso_z
from psycopg.rows import dict_row

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
    """Row value to JSON: Decimal as a plain string, timestamps as UTC ISO-8601 with Z."""
    if isinstance(value, Decimal):
        n = value.normalize()
        return format(n.quantize(Decimal(1)) if n == n.to_integral_value() else n, "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def jsonable_row(row: Row) -> Row:
    return {k: jsonable(v) for k, v in row.items()}


_ROWS = {
    "organizations": "SELECT * FROM organizations ORDER BY organization_id",
    "cases": "SELECT case_id, organization_id, workflow_version_id, status, opened_at, completed_at "
             "FROM cases ORDER BY case_id",
    "workflow_versions": "SELECT * FROM workflow_versions ORDER BY workflow_version_id",
    "step_definitions": "SELECT * FROM step_definitions ORDER BY step_definition_id",
    "dependencies": "SELECT * FROM dependencies ORDER BY dependency_id",
    "step_instances": "SELECT * FROM step_instances ORDER BY step_instance_id",
    "assignments": "SELECT * FROM assignments ORDER BY assignment_id",
    # The effective review status is the latest review row, if any, else the status at insertion.
    "document_versions": (
        "SELECT dv.document_version_id, dv.case_id, dv.document_type, dv.version_number, dv.content_hash, "
        "COALESCE((SELECT r.decision FROM document_reviews r WHERE r.document_version_id = dv.document_version_id "
        "ORDER BY r.decided_at DESC, r.review_id DESC LIMIT 1), dv.review_status) AS review_status, "
        "dv.submitted_at, dv.reviewed_at FROM document_versions dv ORDER BY dv.document_version_id"),
    "approvals": "SELECT * FROM approvals ORDER BY approval_id",
    "sla_rules": "SELECT * FROM sla_rules ORDER BY sla_rule_id",
    "calendar_intervals": "SELECT * FROM calendar_intervals ORDER BY calendar_interval_id",
    "waiting_intervals": "SELECT * FROM waiting_intervals ORDER BY waiting_interval_id",
    "case_events": "SELECT * FROM case_events ORDER BY event_id",
}


def load_population(conn: psycopg.Connection[Row]) -> Population:
    """Assemble the domain's population from the tables (rows are trusted: no ingest rules are re-applied)."""
    rows = {ent: [dict(r) for r in conn.execute(sql).fetchall()] for ent, sql in _ROWS.items()}
    for r in rows["sla_rules"]:
        r["pause_policy"] = list(r["pause_policy"])
    requirements: dict[str, list[str]] = {}
    for r in conn.execute("SELECT workflow_version_id, document_type FROM workflow_requirements "
                          "ORDER BY workflow_version_id, document_type").fetchall():
        requirements.setdefault(r["workflow_version_id"], []).append(r["document_type"])
    return Population.from_rows(rows, {k: {"required_document_types": v} for k, v in requirements.items()})
