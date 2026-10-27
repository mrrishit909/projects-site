"""Load a fixture ``inputs.json`` into the tables, idempotently (``ON CONFLICT DO NOTHING``).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json [--dataset-version NAME]

Rows go through the domain's ``validate`` (the same rules as the API, D-P10-15): a rejected record is kept in ``rejected_records`` with
its raw row and reason code and is not loaded; its dependents are DEPENDENT_REJECTED. ``scope`` and ``requests`` of a fixture are
test inputs and are never loaded. Each load records one ``dataset_versions`` row; ``dataset_version`` defaults to ``ds-<first 12 of
the hash>`` and may be named by the caller so that commands prepared against it match the database's current one.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

for _p in (Path(__file__).resolve().parents[1] / "domain", Path(__file__).resolve().parents[1]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from data.artefacts import write_artefacts  # noqa: E402
from retentionlab import CONTRACT_VERSION, validate  # noqa: E402
from retentionlab.contract import ENTITIES  # noqa: E402
from retentionlab.numbers import canon, sha256_hex  # noqa: E402
from retentionlab.timeutil import parse_ts  # noqa: E402

TEST_ONLY_KEYS = ("scope", "requests")


def canonical_json(obj: Any) -> str:
    return canon(obj)


def insert_rejected(conn: psycopg.Connection, batch_id: str, rejected: list[dict[str, Any]], raw: dict[tuple[str, Any], list[dict[str, Any]]]) -> None:
    """Keep every rejected raw row; two occurrences of one id get different ordinals."""
    seen: dict[tuple[str, str, str], int] = {}
    for rej in rejected:
        key = (rej["entity"], str(rej["id"]), rej["reason_code"])
        n = seen[key] = seen.get(key, -1) + 1
        rows = raw.get((rej["entity"], rej["id"]), [{}])
        row = rows[min(n + 1, len(rows) - 1)] if rej["reason_code"] == "DUPLICATE_ID" else rows[min(n, len(rows) - 1)]   # the first row of an id is the accepted one
        conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row, ordinal) VALUES (%s,%s,%s,%s,%s,%s) "
                     "ON CONFLICT DO NOTHING", (batch_id, rej["entity"], str(rej["id"]), rej["reason_code"], Jsonb(row), n))


def _raw_by_key(inputs: dict[str, Any]) -> dict[tuple[str, Any], list[dict[str, Any]]]:
    from retentionlab.contract import ID
    out: dict[tuple[str, Any], list[dict[str, Any]]] = {}
    for e in ENTITIES:
        for row in inputs.get(e, []):
            out.setdefault((e, row.get(ID[e])), []).append(row)
    return out


def seed(conn: psycopg.Connection, inputs: dict[str, Any], dataset_version: str | None = None, dataset_hash: str | None = None) -> dict[str, Any]:
    """Seed one fixture; return ``{dataset_version, dataset_hash, inserted, skipped}``."""
    ing = validate(inputs)
    acc = ing.accepted
    body = {k: v for k, v in inputs.items() if k not in TEST_ONLY_KEYS}
    dataset_hash = dataset_hash or sha256_hex(canonical_json(body))
    version = dataset_version or f"ds-{dataset_hash[:12]}"
    n = {e: 0 for e in ENTITIES}
    ex = conn.execute
    t = parse_ts

    lv, fv = inputs.get("label_version"), inputs.get("feature_version_spec")
    if lv:
        ex("INSERT INTO label_versions VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (lv["label_version_id"], lv["horizon_days"], lv["grace_days"]))
    if fv:
        ex("INSERT INTO feature_versions VALUES (%s,%s) ON CONFLICT DO NOTHING", (fv["feature_version"], fv["observation_days"]))
    for r in acc["feature_registry"]:
        n["feature_registry"] += ex("INSERT INTO feature_registry VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                    (r["feature_name"], r["feature_version"], r["source_entity"], r.get("window_days"), r["post_outcome"],
                                     r["latent"], r["id_derived"], r["lineage"])).rowcount
    for a in acc["accounts"]:
        n["accounts"] += ex("INSERT INTO accounts VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (a["account_id"], t(a["created_at"]), a["segment"], a["region"], a["synthetic"])).rowcount
    for table, key, extra in (("subscription_events", "subscription_event_id", "event_type"), ("billing_events", "billing_event_id", "amount"),
                              ("usage_events", "usage_event_id", "event_name"), ("support_events", "support_event_id", "severity")):
        for e in acc[table]:
            n[table] += ex(f"INSERT INTO {table} VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",       # table names are constants above
                           (e[key], e["account_id"], e[extra], t(e["event_at"]), t(e["available_at"]))).rowcount
    for c in acc["prediction_cutoffs"]:
        n["prediction_cutoffs"] += ex("INSERT INTO prediction_cutoffs VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                      (c["cutoff_id"], c["account_id"], t(c["prediction_at"]), t(c["horizon_end"]), t(c["observation_start"]))).rowcount
    for f in acc["feature_rows"]:
        n["feature_rows"] += ex("INSERT INTO feature_rows VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                (f["feature_row_id"], f["cutoff_id"], f["feature_version"], Jsonb(f["features_json"]),
                                 t(f["max_available_at"]) if f["max_available_at"] else None)).rowcount
    for l in acc["labels"]:
        n["labels"] += ex("INSERT INTO labels VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                          (l["label_id"], l["cutoff_id"], l["churned"], t(l["label_end"]), l["mature"])).rowcount
    for r in acc["training_runs"]:
        got = ex("INSERT INTO training_runs (training_run_id, train_end, validation_end, test_end, config, config_hash) VALUES (%s,%s,%s,%s,%s,%s) "
                 "ON CONFLICT DO NOTHING", (r["training_run_id"], t(r["train_end"]), t(r["validation_end"]), t(r["test_end"]), Jsonb(r["config"]),
                                            r["config_hash"])).rowcount
        n["training_runs"] += got
        if got:
            write_artefacts(conn, r["training_run_id"], r["config"])
    for s in acc["split_assignments"]:
        n["split_assignments"] += ex("INSERT INTO split_assignments VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                     (s["assignment_id"], s["training_run_id"], s["cutoff_id"], s["split"], s["status"], s["drop_reason"])).rowcount
    for p in acc["predictions"]:
        n["predictions"] += ex("INSERT INTO predictions (prediction_id, training_run_id, cutoff_id, model_name, probability, scored_at, config_hash, "
                               "feature_version, label_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                               (p["prediction_id"], p["training_run_id"], p["cutoff_id"], p.get("model_name", "logistic_regression"), p["probability"],
                                t(p["scored_at"]), p["config_hash"], p["feature_version"], p["label_version"])).rowcount
    for p in acc["scoring_publications"]:
        n["scoring_publications"] += ex("INSERT INTO scoring_publications (publication_id, training_run_id, model_name, prediction_at, published_at, status) "
                                        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                        (p["publication_id"], p["training_run_id"], p.get("model_name", "logistic_regression"), t(p["prediction_at"]),
                                         t(p["published_at"]), p["status"])).rowcount
    for s in acc["intervention_scenarios"]:
        n["intervention_scenarios"] += ex("INSERT INTO intervention_scenarios (scenario_id, capacity, contact_cost, assumed_effect, margin_value) "
                                          "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                          (s["scenario_id"], s["capacity"], s["contact_cost"], s["assumed_effect"], s["margin_value"])).rowcount
    for o in acc["outreach_events"]:
        n["outreach_events"] += ex("INSERT INTO outreach_events (outreach_event_id, account_id, scenario_id, action, status) VALUES (%s,%s,%s,%s,%s) "
                                   "ON CONFLICT DO NOTHING", (o["outreach_event_id"], o["account_id"], o["scenario_id"], o["action"], o["status"])).rowcount
    if ing.rejected:
        insert_rejected(conn, f"batch-seed-{dataset_hash[:16]}", ing.rejected, _raw_by_key(inputs))
    ex("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version, as_of) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
       (version, dataset_hash, str(CONTRACT_VERSION), t(inputs["as_of"]) if inputs.get("as_of") else None))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": n, "skipped": len(ing.rejected)}


def main(argv: list[str]) -> int:
    url = os.environ.get("DATABASE_URL")
    args = [a for a in argv if not a.startswith("--")]
    version = None
    if "--dataset-version" in argv:
        version = argv[argv.index("--dataset-version") + 1]
        args = [a for a in args if a != version]
    if not url or len(args) != 1:
        print("usage: DATABASE_URL=... python data/seed.py <inputs.json> [--dataset-version NAME]", file=sys.stderr)
        return 2
    inputs = json.loads(Path(args[0]).read_text())
    with psycopg.connect(url) as conn:
        print(json.dumps(seed(conn, inputs, dataset_version=version), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
