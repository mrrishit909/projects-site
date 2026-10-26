"""Load a fixture ``inputs.json`` (or a directory of entity files) into the tables, idempotently (``ON CONFLICT DO NOTHING``).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json [--reference-only]
        DATABASE_URL=postgresql://... python data/seed.py <dir with accounts.json, users.json, ... and config.json>

Rows go through the domain's ``validate_batch`` (the same rules as the API): rejected rows are kept in ``rejected_records`` with
the raw row; the event log keeps every well-formed row (duplicates and late events included: the log is immutable and the
cutoff decides per run). The plan, the metric windows and the funnel definition of the inputs are stored beside the facts.
``--reference-only`` loads only the reference data (accounts, users, sessions, subscriptions, experiment versions, the metric
windows, the dataset version) so the API commands can drive the rest. Each load records one ``dataset_versions`` row whose
``dataset_hash`` is the sha256 of the canonical JSON of the inputs. The Student t table is loaded from ``sql/t_quantiles.csv``.

A directory holds one ``<entity>.json`` per entity (a JSON list, as in inputs.json) and an optional ``config.json`` with
``contract_version``, ``cutoff``, ``as_of``, ``analysis_plan`` and ``metric_windows``.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

for _p in (Path(__file__).resolve().parents[1] / "domain",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from productsignal import CONTRACT_VERSION, run_pipeline  # noqa: E402
from productsignal.contract import ENTITIES  # noqa: E402
from productsignal.models import Plan  # noqa: E402

REFERENCE_ENTITIES = ("accounts", "users", "sessions", "subscriptions", "experiment_versions")
T_TABLE = Path(__file__).parent / "sql" / "t_quantiles.csv"


def canonical_json(obj: Any) -> str:
    """Canonical JSON used for every hash in the data layer."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_inputs(path: str | Path) -> dict[str, Any]:
    """An inputs.json file, or a directory of entity files with an optional config.json."""
    p = Path(path)
    if p.is_file():
        return json.loads(p.read_text())
    out: dict[str, Any] = json.loads((p / "config.json").read_text()) if (p / "config.json").exists() else {}
    for ent in ENTITIES:
        f = p / f"{ent}.json"
        out[ent] = json.loads(f.read_text()) if f.exists() else []
    out.setdefault("contract_version", CONTRACT_VERSION)
    out.setdefault("cutoff", out.get("as_of"))
    if out["cutoff"] is None:
        raise ValueError("config.json needs a cutoff (or as_of)")
    return out


def insert_rejected(conn: psycopg.Connection, batch_id: str, rejected: list[Any]) -> None:
    """Keep every rejected raw row; two occurrences of one id get different ordinals."""
    seen: dict[tuple[str, str, str], int] = {}
    for rej in rejected:
        k = (rej.entity, rej.id, rej.reason_code)
        n = seen[k] = seen.get(k, -1) + 1
        conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row, ordinal) "
                     "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (batch_id, rej.entity, rej.id, rej.reason_code, Jsonb(rej.raw_row), n))


def insert_plan(conn: psycopg.Connection, plan: Plan, frozen_by: str | None = None) -> int:
    return conn.execute(
        "INSERT INTO analysis_plans (experiment_version_id, plan, config_hash, frozen_at, frozen_by) VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT DO NOTHING", (plan.experiment_version_id, Jsonb(plan.body), plan.config_hash, plan.frozen_at, frozen_by)).rowcount


def load_t_table(conn: psycopg.Connection) -> int:
    """The Python-generated Student t table (see data/sql/generate_t_quantiles.py); idempotent, one statement."""
    if not T_TABLE.exists():
        return 0
    rows = [r for r in csv.reader(T_TABLE.read_text().splitlines()[1:])]
    have = conn.execute("SELECT count(*) FROM t_critical_975").fetchone()
    if (have[0] if not isinstance(have, dict) else have["count"]) == len(rows):
        return 0
    conn.execute("INSERT INTO t_critical_975 (df, t) SELECT * FROM unnest(%s::int[], %s::numeric[]) ON CONFLICT DO NOTHING",
                 ([int(r[0]) for r in rows], [r[1] for r in rows]))
    return len(rows)


def seed(conn: psycopg.Connection, inputs: dict[str, Any], reference_only: bool = False) -> dict[str, Any]:
    """Seed one fixture; return ``{dataset_version, dataset_hash, inserted, skipped}``."""
    res = run_pipeline(inputs)
    pop, ing = res.population, res.ingest
    dataset_hash = sha256_hex(canonical_json(inputs))
    version = f"ds-{dataset_hash[:12]}"
    load_t_table(conn)
    ents = REFERENCE_ENTITIES if reference_only else ENTITIES
    inserted = {e: 0 for e in ENTITIES}

    def rows(ent: str) -> list[Any]:
        return getattr(pop, ent) if ent in ents else []

    for a in rows("accounts"):
        inserted["accounts"] += conn.execute("INSERT INTO accounts VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                             (a.account_id, a.plan, a.segment, a.created_at, a.internal, a.timezone)).rowcount
    for u in rows("users"):
        inserted["users"] += conn.execute("INSERT INTO users VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                          (u.user_id, u.account_id, u.created_at, u.timezone, u.bot_flag)).rowcount
    for l in rows("identity_links"):
        inserted["identity_links"] += conn.execute(
            "INSERT INTO identity_links (identity_link_id, anonymous_id, user_id, linked_at, rule_version) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING", (l.identity_link_id, l.anonymous_id, l.user_id, l.linked_at, l.rule_version)).rowcount
    for s in rows("sessions"):
        inserted["sessions"] += conn.execute("INSERT INTO sessions VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                             (s.session_id, s.user_id, s.started_at, s.ended_at, s.device_type)).rowcount
    for e in rows("events"):
        inserted["events"] += conn.execute(
            "INSERT INTO events (event_id, user_id, anonymous_id, event_name, event_at, received_at) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING", (e.event_id, e.user_id, e.anonymous_id, e.event_name, e.event_at, e.received_at)).rowcount
    for p in rows("event_properties"):
        inserted["event_properties"] += conn.execute(
            "INSERT INTO event_properties VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (p.property_id, p.event_id, p.property_key, p.property_value, p.value_type)).rowcount
    for s in rows("subscriptions"):
        inserted["subscriptions"] += conn.execute("INSERT INTO subscriptions VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                                  (s.subscription_id, s.account_id, s.starts_at, s.ends_at, s.status, s.amount_usd)).rowcount
    for v in rows("experiment_versions"):
        inserted["experiment_versions"] += conn.execute("INSERT INTO experiment_versions VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                                        (v.experiment_version_id, v.name, v.unit_type, v.primary_metric, v.planned_end)).rowcount
    if not reference_only:
        for plan in pop.plans.values():
            insert_plan(conn, plan, "seed")
        for a in rows("assignments"):
            inserted["assignments"] += conn.execute(
                "INSERT INTO assignments (assignment_id, experiment_version_id, unit_id, variant, assigned_at) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING", (a.assignment_id, a.experiment_version_id, a.unit_id, a.variant, a.assigned_at)).rowcount
        for x in rows("exposures"):
            inserted["exposures"] += conn.execute(
                "INSERT INTO exposures (exposure_id, assignment_id, exposed_at, surface, event_id) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING", (x.exposure_id, x.assignment_id, x.exposed_at, x.surface, x.event_id)).rowcount
        for o in rows("metric_observations"):
            inserted["metric_observations"] += conn.execute(
                "INSERT INTO metric_observations VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (o.observation_id, o.assignment_id, o.metric_name, o.value, o.window_end)).rowcount
        for r in rows("analysis_runs"):
            inserted["analysis_runs"] += conn.execute(
                "INSERT INTO analysis_runs (analysis_id, experiment_version_id, cutoff_at, config_hash, created_at, created_by) "
                "VALUES (%s,%s,%s,%s,%s,'seed') ON CONFLICT DO NOTHING",
                (r.analysis_id, r.experiment_version_id, r.cutoff_at, r.config_hash, r.created_at)).rowcount
        for f in pop.funnels:
            conn.execute("INSERT INTO funnel_definitions (definition_id, version, steps, max_gap_hours, window_from, window_to, created_by) "
                         "VALUES (%s,%s,%s,%s,%s,%s,'seed') ON CONFLICT DO NOTHING",
                         (f.definition_id, f.version, list(f.steps), f.max_gap_hours, f.window_from, f.window_to))
    mw = inputs.get("metric_windows")
    if mw:
        conn.execute("INSERT INTO metric_config (id, windows) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET windows = EXCLUDED.windows",
                     (Jsonb({k: v for k, v in mw.items() if k != "funnel"}),))
    wanted = [r for r in ing.rejected if not reference_only or r.entity in REFERENCE_ENTITIES]
    if wanted:
        insert_rejected(conn, f"batch-seed-{dataset_hash[:16]}", wanted)
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version) "
                 "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (version, dataset_hash, str(CONTRACT_VERSION)))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": inserted, "skipped": len(wanted)}


def main(argv: list[str]) -> int:
    url = os.environ.get("DATABASE_URL")
    args = [a for a in argv if not a.startswith("--")]
    if not url or len(args) != 1:
        print("usage: DATABASE_URL=... python data/seed.py <inputs.json | directory> [--reference-only]", file=sys.stderr)
        return 2
    inputs = load_inputs(args[0])
    with psycopg.connect(url) as conn:
        print(json.dumps(seed(conn, inputs, "--reference-only" in argv), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
