"""Load a fixture ``inputs.json`` (or a directory of entity files) into the tables, idempotently (``ON CONFLICT DO NOTHING``).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json [--dataset-version NAME]
        DATABASE_URL=postgresql://... python data/seed.py <dir with owners.json, datasets.json, ... dataset_rows.json, config.json>

Rows go through the domain's ``validate_batch`` (the same rules as the API): a rejected record is kept in ``rejected_records`` with its
raw row and reason code and is not loaded; its children are DEPENDENT_REJECTED. The synthetic truth block of an inputs file is NEVER
loaded (precision is computed in the verification layer from a separate truth table that only a test loads, data/sql/verification_truth.sql).
Each load records one ``dataset_versions`` row; ``dataset_version`` defaults to ``ds-<first 12 of the hash>`` and may be named by the
caller so that commands prepared against a published dataset match the database's current one.
"""
from __future__ import annotations

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
from trustledger import CONTRACT_VERSION, validate_batch  # noqa: E402
from trustledger.contract import ENTITIES  # noqa: E402
from trustledger.numbers import rnd  # noqa: E402
from trustledger.timeutil import parse_ts  # noqa: E402

CONFIG_KEYS = ("contract_version", "as_of", "whitespace_policy", "weight_version", "weight_versions", "checklist_version",
               "checklist_versions", "probes")


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
    f = p / "dataset_rows.json"
    out["dataset_rows"] = json.loads(f.read_text()) if f.exists() else {}
    out.setdefault("contract_version", CONTRACT_VERSION)
    if out.get("as_of") is None:
        raise ValueError("config.json needs an as_of")
    return out


def insert_rejected(conn: psycopg.Connection, batch_id: str, rejected: list[Any]) -> None:
    """Keep every rejected raw row; two occurrences of one id get different ordinals."""
    seen: dict[tuple[str, str, str], int] = {}
    for rej in rejected:
        k = (rej.entity, rej.id, rej.reason_code)
        n = seen[k] = seen.get(k, -1) + 1
        conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row, ordinal) "
                     "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", (batch_id, rej.entity, rej.id, rej.reason_code, Jsonb(rej.raw_row), n))


def seed(conn: psycopg.Connection, inputs: dict[str, Any], dataset_version: str | None = None, dataset_hash: str | None = None) -> dict[str, Any]:
    """Seed one fixture; return ``{dataset_version, dataset_hash, inserted, skipped}``."""
    ing = validate_batch(inputs)
    pop = ing.population
    body = {k: v for k, v in inputs.items() if k != "synthetic_truth"}          # the truth is never part of the loaded dataset
    dataset_hash = dataset_hash or sha256_hex(canonical_json(body))
    version = dataset_version or f"ds-{dataset_hash[:12]}"
    n = {e: 0 for e in (*ENTITIES, "dataset_rows")}
    ex = conn.execute

    for o in pop.owners:
        n["owners"] += ex("INSERT INTO owners VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                          (o.owner_id, o.owner_name, o.team, o.role, o.active, o.deactivated_at)).rowcount
    for w in pop.weight_versions:
        ex("INSERT INTO rule_weight_versions VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
           (w.weight_version, w.valid_from, Jsonb({k: rnd(v, 6) for k, v in w.weights.items()})))
    for c in pop.checklist_versions:
        ex("INSERT INTO checklist_versions VALUES (%s,%s) ON CONFLICT DO NOTHING", (c["checklist_version"], Jsonb(c["items"])))
    ex("INSERT INTO ledger_config VALUES (1,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
       (Jsonb(inputs.get("whitespace_policy") or {"name": "trim_empty_is_missing", "trim_characters": pop.trim}), pop.checklist_version,
        Jsonb(inputs.get("probes") or {})))
    for d in pop.datasets:
        n["datasets"] += ex("INSERT INTO datasets (dataset_id, dataset_name, source_system, owner_id, classification, registered_at, monitored, "
                            "refresh_timezone, refresh_local_time, refresh_grace_minutes, last_refreshed_at, registered_by) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'seed') ON CONFLICT DO NOTHING",
                            (d.dataset_id, d.dataset_name, d.source_system, d.owner_id, d.classification, d.registered_at, d.monitored,
                             d.refresh_timezone, d.refresh_local_time, d.refresh_grace_minutes, d.last_refreshed_at)).rowcount
    for f in pop.fields:
        n["fields"] += ex("INSERT INTO fields VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                          (f.field_id, f.dataset_id, f.field_name, f.data_type, f.nullable)).rowcount
    for dsid, rows in pop.dataset_rows.items():
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO dataset_rows (dataset_id, ordinal, row_id, data) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            [(dsid, i, r["row_id"], Jsonb(r)) for i, r in enumerate(rows)])
            n["dataset_rows"] += max(cur.rowcount, 0)
    for r in pop.quality_rules:
        n["quality_rules"] += ex("INSERT INTO quality_rules VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                 (r.rule_id, r.dataset_id, r.field_id, r.rule_type, r.severity, r.version_number, r.status, r.disabled_at,
                                  r.disabled_reason, Jsonb(r.definition))).rowcount
    for r in pop.rule_runs:
        n["rule_runs"] += ex("INSERT INTO rule_runs (rule_run_id, rule_id, rule_version, weight_version, kind, run_at, eligible_count, "
                             "failure_count, rerun_for_issue, run_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'seed') ON CONFLICT DO NOTHING",
                             (r.rule_run_id, r.rule_id, r.rule_version, r.weight_version, r.kind, r.run_at, r.eligible_count,
                              r.failure_count, r.rerun_for_issue)).rowcount
    rules = {r.rule_id: r for r in pop.quality_rules}
    runs = {r.rule_run_id: r for r in pop.rule_runs}
    for i in pop.issues:
        got = ex("INSERT INTO issues (issue_id, rule_run_id, severity, owner_id, status, detected_at, due_at, closed_at, verification_run_id, "
                 "reopened_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                 (i.issue_id, i.rule_run_id, rules[runs[i.rule_run_id].rule_id].severity, i.owner_id, i.status, i.detected_at, i.due_at,
                  i.closed_at, i.verification_run_id, list(i.reopened_at))).rowcount
        n["issues"] += got
        if got:
            evs = [("detected", i.detected_at)]
            if i.closed_at:
                evs.append(("claimed", i.closed_at))
            if i.verification_run_id:
                evs.append(("verified", runs[i.verification_run_id].run_at))
            evs += [("reopened", t) for t in i.reopened_at]
            for k, (kind, at) in enumerate(evs):
                ex("INSERT INTO issue_events (event_id, issue_id, event_type, occurred_at, actor_id) VALUES (%s,%s,%s,%s,'seed') "
                   "ON CONFLICT DO NOTHING", (f"ie-{i.issue_id}-{k}", i.issue_id, kind, at))
    for e in pop.lineage_edges:
        n["lineage_edges"] += ex("INSERT INTO lineage_edges VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                 (e.edge_id, e.source_dataset_id, e.target_dataset_id, e.evidence_type, e.observed_at)).rowcount
    for m in sorted(pop.metric_versions, key=lambda m: (m.metric_id, m.version_number)):
        n["metric_versions"] += ex("INSERT INTO metric_versions (metric_version_id, metric_id, metric_name, version_number, definition, grain, "
                                   "source_fields, owner_id, refresh, valid_from, status, published_by) "
                                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'seed') ON CONFLICT DO NOTHING",
                                   (m.metric_version_id, m.metric_id, m.metric_name, m.version_number, m.definition, m.grain,
                                    None if m.source_fields is None else Jsonb(list(m.source_fields)), m.owner_id, m.refresh, m.valid_from,
                                    m.status)).rowcount
    for c in pop.definition_changes:
        n["definition_changes"] += ex("INSERT INTO definition_changes VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                      (c.change_id, c.metric_version_id, c.previous_metric_version_id, c.reason, c.approved_by,
                                       c.changed_at)).rowcount
    for c in pop.customer_records:
        n["customer_records"] += ex("INSERT INTO customer_records VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                    (c.record_id, c.source_system, c.source_customer_id, c.normalized_name, c.address_key)).rowcount
    for c in pop.match_candidates:
        n["match_candidates"] += ex("INSERT INTO match_candidates VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                    (c.candidate_id, c.left_record_id, c.right_record_id, rnd(c.score, 6),
                                     Jsonb(c.features), c.explanation, c.uncertainty, c.proposed_by, c.proposed_at)).rowcount
    for m in sorted(pop.merge_decisions, key=lambda m: (m.decided_at, m.merge_id)):
        n["merge_decisions"] += ex("INSERT INTO merge_decisions VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                   (m.merge_id, m.candidate_id, m.reviewer_id, m.decision, m.decided_at, m.reverses_merge_id, m.reason)).rowcount
    if ing.rejected:
        insert_rejected(conn, f"batch-seed-{dataset_hash[:16]}", ing.rejected)
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version, as_of) VALUES (%s, %s, %s, %s) "
                 "ON CONFLICT DO NOTHING", (version, dataset_hash, str(CONTRACT_VERSION), parse_ts(inputs["as_of"]) if inputs.get("as_of") else None))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": n, "skipped": len(ing.rejected)}


def main(argv: list[str]) -> int:
    url = os.environ.get("DATABASE_URL")
    args = [a for a in argv if not a.startswith("--")]
    version = None
    if "--dataset-version" in argv:
        version = argv[argv.index("--dataset-version") + 1]
        args = [a for a in args if a != version]
    if not url or len(args) != 1:
        print("usage: DATABASE_URL=... python data/seed.py <inputs.json | directory> [--dataset-version NAME]", file=sys.stderr)
        return 2
    inputs = load_inputs(args[0])
    with psycopg.connect(url) as conn:
        print(json.dumps(seed(conn, inputs, dataset_version=version), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
