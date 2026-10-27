"""Apply SQL migrations in order and record them in ``schema_migrations``.

Usage:  DATABASE_URL=postgresql://... python data/migrate.py [--reset]

* Safe on an empty database and on a second run (applied versions are skipped, and each migration file is itself idempotent). A
  migration file that changed after it was applied is refused.
* ``--reset`` first drops only the tables and functions this project owns (never the whole schema).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import tuple_row

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

#: Every table the migrations (and the verification loader) create, children first (used by ``reset``).
OWNED_TABLES = (
    "verification_truth", "command_results", "audit_events", "rejected_records", "dataset_versions", "merge_decisions",
    "match_candidates", "customer_records", "definition_changes", "metric_versions", "lineage_edges", "issue_events", "issues",
    "rule_runs", "ledger_config", "checklist_versions", "rule_weight_versions", "quality_rules", "dataset_rows", "fields",
    "datasets", "owners", "tl_timezones", "schema_migrations",
)
OWNED_FUNCTION_SIGNATURES = ("tl_forbid_mutation()", "tl_rule_guard()", "tl_rule_no_delete()", "tl_issue_guard()", "tl_decision_guard()",
                             "tl_valid_tz(text)", "tl_cell(jsonb)", "tl_iso(timestamptz)", "tl_valid_weights(jsonb)")


def reset(conn: psycopg.Connection) -> None:
    """Drop the project's tables and functions (test and dev use)."""
    for table in OWNED_TABLES:
        conn.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')  # names are constants above
    for sig in OWNED_FUNCTION_SIGNATURES:
        conn.execute(f"DROP FUNCTION IF EXISTS {sig} CASCADE")


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations; return the versions applied by this call."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                 "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('trustledger_migrate', 0))")
    with conn.cursor(row_factory=tuple_row) as cur:  # independent of the caller's row factory
        done = dict(cur.execute("SELECT version, checksum FROM schema_migrations").fetchall())
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text()
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        if path.name in done:
            if done[path.name] != checksum:
                raise RuntimeError(f"migration {path.name} changed after it was applied")
            continue
        conn.execute(sql)
        conn.execute("INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)", (path.name, checksum))
        applied.append(path.name)
    return applied


def main(argv: list[str]) -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    with psycopg.connect(url) as conn:  # commits on success, rolls back on error
        if "--reset" in argv:
            reset(conn)
        applied = apply_migrations(conn)
    print("applied: " + (", ".join(applied) if applied else "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
