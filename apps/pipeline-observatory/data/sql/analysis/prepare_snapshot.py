"""Prepare scratch databases for the analysis queries (P08-ART-04).

Usage (from apps/pipeline-observatory):
  ARTIFACTS_DATABASE_URL=postgresql://.../artifacts08_snapshot ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py
  ARTIFACTS_GOLDEN_DATABASE_URL=postgresql://.../artifacts08_golden ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden

Resets the project's tables in the target database (``data/migrate.py``: never the whole schema), applies the three migrations and loads either the published
synthetic snapshot ``web/public/data`` or ``tests/fixtures/golden/inputs.json`` through ``data/seed.py`` (the domain's ``validate_import``, the same rules as the API).
The snapshot is loaded exactly as ``tests/test_generator.py`` loads it: the twelve domain entities and ``source_expectations`` of the published files with the manifest's
configuration; the dataset version and hash are the generator's (``po-20261026-20261026``, ``0a906877...``). The golden fixture loads with the seed's own version and hash.

SCOPE. The published ``raw_records`` is a 2,000-row SAMPLE of 62 whole batches (D-07): the seed loads only that. Everything else in the database (batches, checkpoints,
runs, tasks, quality results, publications, incidents, backfills, quarantine rows, expectations) is the COMPLETE world. The seeder does not load ``fetch_log``,
``model_output_totals``, ``batch_summaries`` or the recorded figures of the manifest. After the seed this script loads them: ``fetch_log`` into its own table (the schema
has it; explicit ids), and ``artifact_*`` tables (``artifact_tables.sql``, not a migration) for the batch summaries, the stored candidate totals and the recorded freshness
and residual. Only the investigations read the ``artifact_*`` tables; the application never does.

SAFETY. The target database name must start with ``artifacts08_`` (a scratch database made for this package); the script refuses anything else, so it can never reset the
shared ``pipeline_observatory`` development database. ``run_all.py`` creates and drops such databases itself when no ARTIFACTS_*_URL is given. Standard library, psycopg and
this app only.
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
from psycopg.types.json import Jsonb  # noqa: E402

from data import migrate, seed  # noqa: E402
from pipeline_observatory.contract import ENTITIES  # noqa: E402

SNAPSHOT = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "inputs.json"
TABLES_SQL = Path(__file__).resolve().parent / "artifact_tables.sql"
SCRATCH_PREFIX = "artifacts08_"
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


def wrapped(name: str) -> list[dict]:
    return json.loads((SNAPSHOT / f"{name}.json").read_text())["rows"]


def snapshot_inputs() -> tuple[dict, dict]:
    """The inputs ``seed.py`` loads (the shape of inputs.json, as tests/test_generator.py builds it) and the manifest."""
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text())
    inputs = {**manifest["config"], "source_expectations": wrapped("source_expectations")}
    for e in ENTITIES:
        inputs[e] = wrapped(e)
    return inputs, manifest


def load_artifact_tables(conn: psycopg.Connection, manifest: dict) -> dict[str, int]:
    """fetch_log and the artifact_* tables, loaded from the published files and the manifest's recorded figures."""
    conn.execute(TABLES_SQL.read_text())
    n: dict[str, int] = {}
    fl = wrapped("fetch_log")
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO fetch_log (fetch_id, source_id, cursor_value, session_id, status, next_cursor, retry_after_seconds, fetched_at, batch_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(r["fetch_id"], r["source_id"], r["cursor_value"], r["session_id"], r["status"], r["next_cursor"], r["retry_after_seconds"], r["fetched_at"], r["batch_id"])
                         for r in fl])
        n["fetch_log"] = len(fl)
        bs = wrapped("batch_summaries")
        cur.executemany("INSERT INTO artifact_batch_summaries VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(r["batch_id"], r["source_id"], r["kind"], r["status"], r["sampled"], r["written_rows"], r["received"], r["accepted_unique"], r["duplicate"],
                          r["quarantined"], r["deleted"], Jsonb(r["quarantine_by_reason"])) for r in bs])
        n["artifact_batch_summaries"] = len(bs)
        mt = wrapped("model_output_totals")
        cur.executemany("INSERT INTO artifact_model_output_totals VALUES (%s,%s,%s)", [(r["run_id"], r["output_rows"], r["total_amount"]) for r in mt])
        n["artifact_model_output_totals"] = len(mt)
        fr = manifest["stats"]["freshness_at_as_of"]
        cur.executemany("INSERT INTO artifact_recorded_freshness VALUES (%s,%s,%s,%s)",
                        [(s, v["latest_accepted_event_at"], v["freshness_seconds"], v["ingestion_age_seconds"]) for s, v in sorted(fr.items())])
        n["artifact_recorded_freshness"] = len(fr)
        dr5 = next(d for d in manifest["designed_relationships"] if d["id"] == "DR-05")["realised"]["candidates_with_nonzero_residual"]
        cur.executemany("INSERT INTO artifact_recorded_residual VALUES (%s,%s,%s,%s,%s,%s)",
                        [(c["run_id"], c["day"], c["source_total"], c["exclusions_total"], c["published_total"], c["residual"]) for c in dr5])
        n["artifact_recorded_residual"] = len(dr5)
    return n


def prepare(url: str, golden: bool) -> dict:
    assert_scratch(url)
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn:
        with conn.transaction():
            if golden:
                out = seed.seed(conn, json.loads(GOLDEN.read_text()))
            else:
                inputs, manifest = snapshot_inputs()
                out = seed.seed(conn, inputs, dataset_version=manifest["dataset_version"], dataset_hash=manifest["dataset_hash"])
                out["inserted"] = {**out["inserted"], **load_artifact_tables(conn, manifest)}
    return out


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
