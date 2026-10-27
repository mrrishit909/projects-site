"""Prepare scratch databases for the analysis queries (P05-ART-04).

Usage (from apps/invoicebridge):
  ARTIFACTS_DATABASE_URL=postgresql://.../artifacts05_snapshot ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py
  ARTIFACTS_GOLDEN_DATABASE_URL=postgresql://.../artifacts05_golden ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden

Resets the project's tables in the target database (``data/migrate.py``: never the whole schema), applies the three migrations and loads
either the published synthetic snapshot ``web/public/data`` or ``tests/fixtures/golden/inputs.json`` through ``data/seed.py`` (the domain's
``validate_batch``, the same rules as the API). ``seed.py`` derives the workflow state (match results, one open exception per derived
reason, export rows) at the inputs' as-of; it does not load the exception HISTORY the generator publishes (``exceptions.json`` with its
resolved rows and ``exception_assignments.json``), so for the snapshot this script replaces the derived exception rows with the published
ones, exactly as tests/test_generator.py does before it runs the SQL reference. The golden fixture has no history and needs none.
The dataset version is the generator's (``ib-20261026-20261026``), the one the replay events carry.

SAFETY. The target database name must start with ``artifacts05_`` (a scratch database made for this package); the script refuses anything
else, so it can never reset the shared ``invoicebridge`` development database. ``run_all.py`` creates and drops such databases itself when
no ARTIFACTS_*_URL is given. Only the standard library, psycopg and this app are used.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "domain", ROOT):
    sys.path.insert(0, str(p))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from data import migrate, seed  # noqa: E402

SNAPSHOT = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "inputs.json"
SCRATCH_PREFIX = "artifacts05_"
#: The local development login of the repository's CI workflow; override with ARTIFACTS_ADMIN_URL. No other credential exists.
DEFAULT_ADMIN_URL = "postgresql://lab:lab@127.0.0.1:5432/postgres"
INPUT_ENTITIES = ("vendors", "purchase_orders", "po_lines", "receipts", "invoices", "invoice_lines", "credit_notes", "approval_policies",
                  "approvals", "export_requests")


def db_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def with_db(url: str, name: str) -> str:
    return urlunparse(urlparse(url)._replace(path="/" + name))


def assert_scratch(url: str) -> None:
    if not db_name(url).startswith(SCRATCH_PREFIX):
        raise SystemExit(f"refusing to touch database {db_name(url)!r}: scratch databases must be named {SCRATCH_PREFIX}*")


def create_database(admin_url: str, name: str) -> None:
    if not name.startswith(SCRATCH_PREFIX):
        raise SystemExit(f"scratch database names start with {SCRATCH_PREFIX}")
    with psycopg.connect(admin_url, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{name}"')


def drop_database(admin_url: str, name: str) -> None:
    if not name.startswith(SCRATCH_PREFIX):
        raise SystemExit(f"scratch database names start with {SCRATCH_PREFIX}")
    with psycopg.connect(admin_url, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def snapshot_rows() -> dict[str, list[dict]]:
    return {e: json.loads((SNAPSHOT / f"{e}.json").read_text())["rows"] for e in INPUT_ENTITIES + ("exceptions", "exception_assignments")}


def snapshot_inputs() -> tuple[dict, str, dict]:
    """The inputs ``seed.py`` loads, the published dataset version, and the rows (with the exception history)."""
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text())
    rows = snapshot_rows()
    inputs = {"contract_version": 1, "as_of": manifest["as_of"], "snapshot_cutoffs": manifest["snapshot_cutoffs"], "tolerances": manifest["tolerances"],
              **{e: rows[e] for e in INPUT_ENTITIES}}
    return inputs, manifest["dataset_version"], rows


def prepare(url: str, golden: bool) -> dict:
    assert_scratch(url)
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn:
        if golden:
            out = seed.seed(conn, json.loads(GOLDEN.read_text()))
            out["exceptions_loaded"] = out["assignments_loaded"] = 0
            return out
        inputs, version, rows = snapshot_inputs()
        out = seed.seed(conn, inputs, dataset_version=version)
        conn.execute("DELETE FROM exceptions")
        for e in rows["exceptions"]:
            conn.execute("INSERT INTO exceptions (exception_id, invoice_id, exception_type, status, owner_id, created_at, resolved_at) "
                         "VALUES (%(exception_id)s, %(invoice_id)s, %(exception_type)s, %(status)s, %(owner_id)s, %(created_at)s, %(resolved_at)s)", e)
        for a in rows["exception_assignments"]:
            conn.execute("INSERT INTO exception_assignments (assignment_id, exception_id, owner_id, assigned_by, assigned_at, note) "
                         "VALUES (%(assignment_id)s, %(exception_id)s, %(owner_id)s, %(assigned_by)s, %(assigned_at)s, %(note)s)", a)
        conn.execute("SELECT setval('exception_seq', %s)", (len(rows["exceptions"]),))
        out["exceptions_loaded"] = len(rows["exceptions"])
        out["assignments_loaded"] = len(rows["exception_assignments"])
    return out


def main(argv: list[str]) -> int:
    golden = "--golden" in argv
    url = os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL" if golden else "ARTIFACTS_DATABASE_URL")
    if not url:
        print("set ARTIFACTS_DATABASE_URL (or ARTIFACTS_GOLDEN_DATABASE_URL with --golden) to a scratch database "
              f"named {SCRATCH_PREFIX}*", file=sys.stderr)
        return 2
    out = prepare(url, golden)
    print(json.dumps({"dataset_version": out["dataset_version"], "seed_input_hash": out["dataset_hash"], "rejected_rows_kept": out["skipped"],
                      "inserted": out["inserted"], "exceptions_loaded": out["exceptions_loaded"], "assignments_loaded": out["assignments_loaded"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
