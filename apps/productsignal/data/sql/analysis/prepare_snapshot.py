"""Prepare scratch databases for the analysis queries (P06-ART-04).

Usage (from apps/productsignal):
  ARTIFACTS_DATABASE_URL=postgresql://.../artifacts06_snapshot ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py
  ARTIFACTS_GOLDEN_DATABASE_URL=postgresql://.../artifacts06_golden ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden

Resets the project's tables in the target database (``data/migrate.py``: never the whole schema), applies the two migrations and loads either
the published synthetic snapshot ``web/public/data`` or ``tests/fixtures/golden/inputs.json`` through ``data/seed.py`` (the domain's
``validate_batch``, the same rules as the API). The snapshot is loaded exactly as ``tests/test_generator.py`` loads it: the inputs are the
entity files plus the manifest's metric windows, v1's plan as the plan of record and BOTH plans (v1 and v2) from the manifest's
``analysis_plans``; the dataset version and hash are the generator's (``ps-20261026-20261026``, ``12672f9c...``). The golden fixture
loads with the seed's own version and hash.

SAFETY. The target database name must start with ``artifacts06_`` (a scratch database made for this package); the script refuses anything
else, so it can never reset the shared ``productsignal`` development database. ``run_all.py`` creates and drops such databases itself when no
ARTIFACTS_*_URL is given. A schema cannot stand in for a database: ``0002_constraints.sql`` looks constraint names up globally
(``pg_constraint``), so two schemas of one database would see each other's constraints. Only the standard library, psycopg and this app are used.
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
from productsignal.contract import ENTITIES  # noqa: E402

SNAPSHOT = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "inputs.json"
SCRATCH_PREFIX = "artifacts06_"
#: The local development login of the repository's CI workflow (a throwaway postgres:16 service); override with ARTIFACTS_ADMIN_URL.
DEFAULT_ADMIN_URL = "postgresql://lab:lab@127.0.0.1:5432/postgres"


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


def snapshot_inputs() -> tuple[dict, dict]:
    """The inputs ``seed.py`` loads (the shape of inputs.json) and the manifest."""
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text())
    rows = {e: json.loads((SNAPSHOT / f"{e}.json").read_text())["rows"] for e in ENTITIES}
    inputs = {"contract_version": 1, "as_of": manifest["as_of"], "cutoff": manifest["cutoff"], "analysis_plan": manifest["analysis_plans"]["xv-001"],
              "analysis_plans": manifest["analysis_plans"], "metric_windows": manifest["metric_windows"], **rows}
    return inputs, manifest


def prepare(url: str, golden: bool) -> dict:
    assert_scratch(url)
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn:
        if golden:
            with conn.transaction():
                return seed.seed(conn, json.loads(GOLDEN.read_text()))
        inputs, manifest = snapshot_inputs()
        with conn.transaction():
            return seed.seed(conn, inputs, dataset_version=manifest["dataset_version"], dataset_hash=manifest["dataset_hash"])


def main(argv: list[str]) -> int:
    golden = "--golden" in argv
    url = os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL" if golden else "ARTIFACTS_DATABASE_URL")
    if not url:
        print("set ARTIFACTS_DATABASE_URL (or ARTIFACTS_GOLDEN_DATABASE_URL with --golden) to a scratch database "
              f"named {SCRATCH_PREFIX}*", file=sys.stderr)
        return 2
    out = prepare(url, golden)
    print(json.dumps({"dataset_version": out["dataset_version"], "dataset_hash": out["dataset_hash"], "rejected_rows_kept": out["skipped"],
                      "inserted": out["inserted"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
