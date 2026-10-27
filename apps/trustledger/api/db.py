"""psycopg helpers: one connection and one transaction per request, and the domain's population assembled from the tables.

``transaction()`` commits when the block exits normally and rolls back on any exception, so a command's effects and its audit event
are atomic.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from trustledger.contract import DEFAULT_CHECKLIST, DEFAULT_TRIM, ENTITIES
from trustledger.models import Population, WeightVersion, parse
from trustledger.timeutil import iso_z, parse_ts

Row = dict[str, Any]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect(autocommit: bool = False) -> psycopg.Connection[Row]:
    # UTC session so TIMESTAMPTZ comparisons never depend on the server's zone.
    return psycopg.connect(database_url(), row_factory=dict_row, options="-c timezone=UTC", autocommit=autocommit)


@contextmanager
def transaction() -> Iterator[psycopg.Connection[Row]]:
    """One transaction: commit on success, rollback on error, always close."""
    with _connect() as conn:
        yield conn


@contextmanager
def autocommit() -> Iterator[psycopg.Connection[Row]]:
    """A separate connection whose statements commit at once: keeps a refusal in the audit trail when the command's own transaction
    is about to be rolled back."""
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
    "owners": "SELECT * FROM owners ORDER BY owner_id",
    "datasets": "SELECT * FROM datasets ORDER BY dataset_id",
    "fields": "SELECT * FROM fields ORDER BY field_id",
    "quality_rules": "SELECT * FROM quality_rules ORDER BY rule_id",
    "rule_runs": "SELECT rule_run_id, rule_id, rule_version, weight_version, kind, run_at, eligible_count, failure_count, rerun_for_issue "
                 "FROM rule_runs ORDER BY rule_run_id",
    "issues": "SELECT issue_id, rule_run_id, owner_id, status, detected_at, due_at, closed_at, verification_run_id, reopened_at FROM issues ORDER BY issue_id",
    "lineage_edges": "SELECT * FROM lineage_edges ORDER BY edge_id",
    "metric_versions": "SELECT * FROM metric_versions ORDER BY metric_version_id",
    "definition_changes": "SELECT * FROM definition_changes ORDER BY change_id",
    "customer_records": "SELECT * FROM customer_records ORDER BY record_id",
    "match_candidates": "SELECT * FROM match_candidates ORDER BY candidate_id",
    "merge_decisions": "SELECT * FROM merge_decisions ORDER BY merge_id",
}


#: The rows of a dataset as the measurement reads them: the latest version of each record recorded by ``as_of`` (NULL = the latest of all),
#: in the position of its first version. Corrections append versions (C11); nothing is edited (D-10 R7-07).
CURRENT_ROWS_SQL = (
    "SELECT dataset_id, data FROM ("
    " SELECT DISTINCT ON (dataset_id, row_id) dataset_id, row_id, data, min(ordinal) OVER (PARTITION BY dataset_id, row_id) AS pos"
    " FROM dataset_rows WHERE (%(as_of)s::timestamptz IS NULL OR recorded_at IS NULL OR recorded_at <= %(as_of)s::timestamptz)"
    " AND (%(ids)s::text[] IS NULL OR dataset_id = ANY(%(ids)s::text[]))"
    " ORDER BY dataset_id, row_id, row_version DESC) x ORDER BY dataset_id COLLATE \"C\", pos")

#: The latest recorded refresh of each dataset not after ``as_of``: the value loaded with the dataset or a later C12 record-refresh.
LAST_REFRESH_SQL = (
    "SELECT dataset_id, max(t) AS last_refreshed_at FROM ("
    " SELECT dataset_id, last_refreshed_at AS t FROM datasets UNION ALL SELECT dataset_id, refreshed_at FROM dataset_refreshes) x"
    " WHERE t IS NOT NULL AND (%(as_of)s::timestamptz IS NULL OR t <= %(as_of)s::timestamptz) GROUP BY dataset_id")


def current_rows(conn: psycopg.Connection[Row], as_of: datetime | None, dataset_ids: list[str] | None = None) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {}
    for r in conn.execute(CURRENT_ROWS_SQL, {"as_of": as_of, "ids": dataset_ids}).fetchall():
        out.setdefault(r["dataset_id"], []).append(r["data"])
    return out


def last_refreshes(conn: psycopg.Connection[Row], as_of: datetime | None) -> dict[str, datetime]:
    return {r["dataset_id"]: r["last_refreshed_at"] for r in conn.execute(LAST_REFRESH_SQL, {"as_of": as_of}).fetchall()}


def load_population(conn: psycopg.Connection[Row], as_of: datetime | None = None) -> Population:
    """The domain's population from the tables (rows are trusted; the same parsers as ingest run over them). With ``as_of`` the dataset rows
    are the latest versions recorded by then and each dataset's last refresh is the latest not after it."""
    pop = Population()
    refreshed = last_refreshes(conn, as_of)
    for ent in ENTITIES:
        rows = conn.execute(_ROWS[ent]).fetchall()
        for r in rows:
            if ent == "match_candidates":
                r = {**r, "score": format(r["score"], "f")}
            if ent == "issues":
                r = {**r, "reopened_at": list(r["reopened_at"])}
            if ent == "datasets":
                r = {**r, "last_refreshed_at": refreshed.get(r["dataset_id"])}
            getattr(pop, ent).append(parse(ent, r))
    pop.dataset_rows = current_rows(conn, as_of)
    pop.weight_versions = [WeightVersion(r["weight_version"], r["valid_from"], {k: Fraction(v) for k, v in r["weights"].items()})
                           for r in conn.execute("SELECT * FROM rule_weight_versions ORDER BY weight_version").fetchall()]
    pop.checklist_versions = [{"checklist_version": r["checklist_version"], "items": list(r["items"])}
                              for r in conn.execute("SELECT * FROM checklist_versions ORDER BY checklist_version").fetchall()] or [DEFAULT_CHECKLIST]
    cfg = conn.execute("SELECT * FROM ledger_config WHERE id = 1").fetchone()
    if cfg:
        pop.trim = (cfg["whitespace_policy"] or {}).get("trim_characters", DEFAULT_TRIM)
        pop.checklist_version = cfg["checklist_version"]
        probe = (cfg["probes"] or {}).get("definition_at")
        pop.probe_definition_at = parse_ts(probe) if probe else None
    else:
        pop.checklist_version = pop.checklist_versions[-1]["checklist_version"]
    return pop


def load_truth(conn: psycopg.Connection[Row]) -> dict[str, str] | None:
    """The verification layer's truth, if a test (or reviewer) loaded the ``verification_truth`` table; otherwise None, and match
    precision is unknown (null). Nothing else in the API reads it."""
    if conn.execute("SELECT to_regclass('verification_truth') AS t").fetchone()["t"] is None:
        return None
    rows = conn.execute("SELECT record_id, true_entity FROM verification_truth").fetchall()
    return {r["record_id"]: r["true_entity"] for r in rows} or None


def current_dataset_version(conn: psycopg.Connection[Row]) -> str:
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row["dataset_version"] if row else "unversioned"
