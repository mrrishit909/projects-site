"""Apply SQL migrations in order and record them in ``schema_migrations``.

Usage:  DATABASE_URL=postgresql://... python data/migrate.py [--reset]

* Safe on an empty database and on a second run (applied versions are skipped, and each migration file is itself
  idempotent). A migration file that changed after it was applied is refused.
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

#: Every table the migrations create, children first (used by ``reset``).
OWNED_TABLES = (
    "command_results", "audit_events", "rejected_records", "raw_batches", "dataset_versions", "simulation_events",
    "simulation_runs", "surveys", "ticket_events", "tickets", "sla_policies", "shift_breaks", "shifts",
    "queue_skills", "agent_skills", "skills", "agents", "queues", "customers", "schema_migrations",
)
OWNED_FUNCTIONS = ("sf_forbid_mutation", "sf_arrival_fixed")


def reset(conn: psycopg.Connection) -> None:
    """Drop the project's tables and functions (test and dev use)."""
    for table in OWNED_TABLES:
        conn.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')  # names are constants above
    for fn in OWNED_FUNCTIONS:
        conn.execute(f"DROP FUNCTION IF EXISTS {fn}() CASCADE")


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations; return the versions applied by this call."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                 "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
                 "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('serviceflow_migrate', 0))")
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
