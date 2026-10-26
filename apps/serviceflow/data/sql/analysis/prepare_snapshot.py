"""Prepare scratch databases for the analysis queries (P04-ART-04).

Usage (from apps/serviceflow):
  ARTIFACTS_DATABASE_URL=postgresql://.../artifacts04_snapshot ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py
  ARTIFACTS_DATABASE_URL=postgresql://.../artifacts04_golden   ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden

Resets the project's tables in the target database (``data/migrate.py``: never the whole schema), applies the two migrations
and seeds either the published synthetic snapshot ``web/public/data`` or ``tests/fixtures/golden/inputs.json`` through
``data/seed.py`` (the domain's ``validate_batch``, so the injected defects the contract rejects land in ``rejected_records``
exactly as in production). ``seed.py`` has no loader for ``shift_breaks`` (D-07), so the snapshot's 1,018 recorded break
intervals are inserted here from ``web/public/data/shift_breaks.json``; the occupancy investigation needs them.

SAFETY. The target database name must start with ``artifacts04_`` (a scratch database made for this package); the script
refuses anything else, so it can never reset the shared ``serviceflow`` development database. ``run_all.py`` creates and
drops such databases itself when no ARTIFACTS_*_URL is given. Only the standard library, psycopg and this app are used.
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

from data import migrate, seed  # noqa: E402
from serviceflow.contract import ENTITIES  # noqa: E402

SNAPSHOT = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "inputs.json"
SCRATCH_PREFIX = "artifacts04_"
#: The local development login of the repository's CI workflow; override with ARTIFACTS_ADMIN_URL. No other credential exists.
DEFAULT_ADMIN_URL = "postgresql://lab:lab@127.0.0.1:5432/postgres"


def db_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def with_db(url: str, name: str) -> str:
    u = urlparse(url)
    return urlunparse(u._replace(path="/" + name))


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


def snapshot_inputs() -> dict:
    """The published rows plus the window, the backlog cutoff and the abandonable channels the generator declares."""
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text())
    params = manifest["generator"]["parameters"]
    data: dict = {"contract_version": 1, "window_start": "2026-07-06T00:00:00Z", "window_end": "2026-09-28T00:00:00Z",
                  "backlog_cutoffs": [params["as_of"]], "abandonable_channels": params["abandonable_channels"]}
    for name in ENTITIES:
        data[name] = json.loads((SNAPSHOT / f"{name}.json").read_text())["rows"]
    return data


def prepare(url: str, golden: bool) -> dict:
    assert_scratch(url)
    inputs = json.loads(GOLDEN.read_text()) if golden else snapshot_inputs()
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
        out = seed.seed(conn, inputs)
        breaks = 0
        if not golden:
            for b in json.loads((SNAPSHOT / "shift_breaks.json").read_text())["rows"]:
                breaks += conn.execute(
                    "INSERT INTO shift_breaks (break_id, shift_id, agent_id, starts_at, ends_at) VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING", [b[c] for c in ("break_id", "shift_id", "agent_id", "starts_at", "ends_at")]).rowcount
        out["shift_breaks_loaded"] = breaks
    return out


def main(argv: list[str]) -> int:
    golden = "--golden" in argv
    url = os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL" if golden else "ARTIFACTS_DATABASE_URL")
    if not url:
        print("set ARTIFACTS_DATABASE_URL (or ARTIFACTS_GOLDEN_DATABASE_URL with --golden) to a scratch database "
              f"named {SCRATCH_PREFIX}*", file=sys.stderr)
        return 2
    out = prepare(url, golden)
    print(json.dumps({"dataset_version": out["dataset_version"], "seed_hash": out["dataset_hash"], "rejected_rows_kept": out["skipped"],
                      "inserted": out["inserted"], "shift_breaks_loaded": out["shift_breaks_loaded"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
