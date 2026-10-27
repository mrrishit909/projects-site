"""Prepare scratch databases for the analysis queries (P10-ART-04).

Usage (from apps/retentionlab):
  ARTIFACTS_DATABASE_URL=postgresql://.../artifacts10_snapshot ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py
  ARTIFACTS_GOLDEN_DATABASE_URL=postgresql://.../artifacts10_golden ../../.venv/bin/python data/sql/analysis/prepare_snapshot.py --golden

Resets the project's tables in the target database (``data/migrate.py``: never the whole schema), applies the three migrations and loads either the published synthetic
snapshot ``web/public/data`` or ``tests/fixtures/golden/inputs.json`` through ``data/seed.py`` (the domain's ``validate``, the same rules as the API). The snapshot is
loaded exactly as ``tests/test_generator.py`` loads it: the entity files of the 200-account cohort plus the manifest's as-of, label version and feature version; the dataset
version and hash are the generator's (``rl-20261026-20261026``, ``9ebaaada...``). The golden fixture loads with the seed's own version and hash.

The verification layer. ``data/sql/verification_layer.sql`` is NOT a migration: the matcher, the API and the seeder never read or load it. After the seed this script creates it
(snapshot database only) and loads the published full-world files into it: the 1,513-row test table (``test_cohort.json``), the per-cutoff counts and the drift series
(``cutoff_aggregates.json``), the full-world economics, the split counts of the whole population and the manifest's published figures. Those rows are the "test table" and the
"published aggregates" the investigations read; the figures they carry are never re-derived from themselves: ``run_all.py`` reconciles every result with an independent source.

SAFETY. The target database name must start with ``artifacts10_`` (a scratch database made for this package); the script refuses anything else, so it can never reset the
shared ``retentionlab`` development database. ``run_all.py`` creates and drops such databases itself when no ARTIFACTS_*_URL is given. Only the standard library, psycopg and
this app are used.
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
from retentionlab.contract import ENTITIES  # noqa: E402

SNAPSHOT = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "inputs.json"
LAYER_SQL = ROOT / "data" / "sql" / "verification_layer.sql"
SCRATCH_PREFIX = "artifacts10_"
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


def read(name: str) -> dict:
    return json.loads((SNAPSHOT / f"{name}.json").read_text())


def snapshot_inputs() -> tuple[dict, dict]:
    """The inputs ``seed.py`` loads (the shape of inputs.json, as tests/test_generator.py ``inputs`` builds it) and the manifest."""
    manifest = read("manifest")
    cfg = manifest["config"]
    inputs = {"contract_version": 1, "as_of": manifest["as_of"], "label_version": cfg["label_version"], "feature_version_spec": cfg["feature_version_spec"]}
    inputs.update({e: read(e)["rows"] for e in ENTITIES})
    return inputs, manifest


def load_layer(conn) -> dict[str, int]:
    """Create the verification layer and fill it from the published files; returns the row counts."""
    conn.execute(LAYER_SQL.read_text())
    manifest, agg, split = read("manifest"), read("cutoff_aggregates"), read("split_summary")
    table = read("test_cohort")
    head_cutoffs = table["head"]["cutoffs"]
    cols = table["head"]["columns"]
    with conn.cursor() as cur:
        rows = []
        for n, r in enumerate(table["rows"], 1):
            d = dict(zip(cols, r))
            rows.append((n, d["account_id"], d["cutoff_index"], head_cutoffs[d["cutoff_index"]], d["segment"], d["region"], d["usage_events_30d"], d["days_since_last_usage"],
                         d["high_severity_support_90d"], d["billing_total_90d"], d["churned"], d["p_random_baseline"], d["p_business_rule"], d["p_logistic_uncalibrated"],
                         d["p_logistic_calibrated"], d["p_prevalence_baseline"]))
        cur.executemany("INSERT INTO art_test_table VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        for c in agg["cutoffs"]:
            p, le = c["population"], c["late_events"]
            cur.execute("INSERT INTO art_cutoff_aggregate VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (c["prediction_at"], c["range"], p["cutoff_rows"], p["eligible"], p["mature"], p["censored"], p["churned"], p["scored"], p["evaluated"], c["churn_rate"],
                         le["total"], le["usage_events"], le["billing_events"], le["support_events"], le["subscription_events"]))
        for d in agg["drift"]["by_cutoff"]:
            for g in ("all_accounts", "apac", "other_regions"):
                x = d[g]
                cur.execute("INSERT INTO art_drift_published VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (d["prediction_at"], g, x["psi"], x["current_rows"], x["reference_rows"], x.get("floored_bins"), x["exceeds_threshold"]))
        for sid, e in sorted(agg["economics_full_world"]["scenarios"].items()):
            a = e["assumptions"]
            cur.execute("INSERT INTO art_economics_full_world VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (sid, e["capacity"], e["scored_accounts"], a["contact_cost"], a["assumed_effect"], a["margin_value"], e["contact_budget"], e["expected_value"], e["label"]))
        for rng, s in sorted(split["population"].items()):
            cur.execute("INSERT INTO art_split_population VALUES (%s,%s,%s,%s,%s,%s)", (rng, s["total"], s["retained"], s["label_window"], s["group_test"], s["group_validation"]))
        dr = {d["id"]: d["realised"] for d in manifest["designed_relationships"]}
        pop = manifest["population"]
        claims = {
            ("dataset_hash", "manifest"): manifest["dataset_hash"],
            ("dataset_version", "manifest"): manifest["dataset_version"],
            ("eligible_rows", "full world"): str(pop["feature_rows"]),
            ("censored_rows", "full world"): str(dr["DR-05"]["censored_rows"]),
            ("censored_share", "full world"): dr["DR-05"]["censored_share"],
            ("mature_churn_rate", "full world"): dr["DR-05"]["mature_churn_rate"],
            ("test_rows", "full world"): str(pop["by_range"]["test"]["eligible"]),
            ("test_prevalence", "full world"): pop["by_range"]["test"]["churn_rate"],
            ("late_share_usage", "full world"): dr["DR-04"]["realised"]["usage_events"]["share"],
            ("late_share_billing", "full world"): dr["DR-04"]["realised"]["billing_events"]["share"],
            ("late_share_support", "full world"): dr["DR-04"]["realised"]["support_events"]["share"],
            ("late_share_subscription", "full world"): dr["DR-04"]["realised"]["subscription_events"]["share"],
            **{(f"naive_rate_if_censored_were_non_churn_{k[:10]}", "full world"): v for k, v in dr["DR-05"]["churn_rate_if_censored_were_non_churn"].items()},
            ("test_rows_features_change_if_ignored", "full world"): str(dr["DR-04"]["test_rows_features_change_if_ignored"]),
            ("share_of_test_rows_changed", "full world"): dr["DR-04"]["share_of_test_rows_changed"],
            ("test_rows_with_a_late_event", "full world"): str(dr["DR-04"]["test_rows_with_a_late_event"]),
        }
        cur.executemany("INSERT INTO art_published_claim VALUES (%s,%s,%s)", [(k[0], k[1], v) for k, v in sorted(claims.items())])
    return {"art_test_table": len(rows), "art_cutoff_aggregate": len(agg["cutoffs"]), "art_drift_published": 3 * len(agg["drift"]["by_cutoff"]),
            "art_economics_full_world": 3, "art_split_population": len(split["population"]), "art_published_claim": len(claims)}


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
                out["verification_layer"] = load_layer(conn)          # the verification layer (see the module docstring): created and loaded here and nowhere else
        conn.execute("ANALYZE")                                       # a freshly loaded scratch database has no statistics yet; without them the reference SQL plans badly (about 0.6 s a call)
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
                      "inserted": out["inserted"], "verification_layer": out.get("verification_layer")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
