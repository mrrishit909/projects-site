"""Load a fixture ``inputs.json`` into the tables (idempotent by primary key).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json

Rows are validated with the domain's ``validate_batch`` (the same rules as the API), so a fixture with a
rejected case loads the accepted rows, keeps the rejected raw rows in ``rejected_records`` and reports the
count as ``skipped``. Inserts use ``ON CONFLICT DO NOTHING``; running twice changes nothing. Workflow
versions are inserted as drafts, their steps, dependencies and required documents are added, and only then are
they published (the NULL -> published update is the one change the immutability trigger allows).
Each run records one ``dataset_versions`` row whose ``dataset_hash`` is the sha256 of the canonical JSON.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

try:
    import onboard_studio  # noqa: F401
except ImportError:  # running as a script without PYTHONPATH=domain
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "domain"))
from onboard_studio import CONTRACT_VERSION  # noqa: E402
from onboard_studio.ingest import validate_batch  # noqa: E402
from onboard_studio.workflow import definition_hash  # noqa: E402

#: Insert order respects foreign keys (0001_schema.sql).
INSERT_ORDER: tuple[str, ...] = (
    "organizations", "workflow_versions", "step_definitions", "dependencies", "sla_rules",
    "calendar_intervals", "cases", "step_instances", "assignments", "document_versions", "approvals",
    "waiting_intervals", "case_events")

COLUMNS: dict[str, tuple[str, ...]] = {
    "organizations": ("organization_id", "organization_name", "segment", "region", "created_at"),
    "workflow_versions": ("workflow_version_id", "template_id", "version_number"),
    "step_definitions": ("step_definition_id", "workflow_version_id", "step_name", "required", "role_key",
                         "sequence"),
    "dependencies": ("dependency_id", "step_definition_id", "prerequisite_id", "dependency_type", "created_at"),
    "sla_rules": ("sla_rule_id", "workflow_version_id", "business_minutes", "pause_policy", "calendar_id"),
    "calendar_intervals": ("calendar_interval_id", "calendar_id", "starts_at", "ends_at", "timezone", "kind"),
    "cases": ("case_id", "organization_id", "workflow_version_id", "status", "opened_at", "completed_at"),
    "step_instances": ("step_instance_id", "case_id", "step_definition_id", "status", "version_number",
                       "ready_at", "started_at", "approved_at"),
    "assignments": ("assignment_id", "step_instance_id", "assignee_id", "assigned_at", "ended_at"),
    "document_versions": ("document_version_id", "case_id", "document_type", "version_number", "content_hash",
                          "review_status", "submitted_at", "reviewed_at"),
    "approvals": ("approval_id", "step_instance_id", "reviewer_id", "decision", "decided_at", "reason",
                  "version_number"),
    "waiting_intervals": ("waiting_interval_id", "case_id", "reason_code", "starts_at", "ends_at"),
    "case_events": ("event_id", "case_id", "event_type", "actor_id", "occurred_at"),
}
DEFAULTS: dict[str, Any] = {"kind": "working", "dependency_type": "mandatory", "version_number": 1}
DEFINITION_TABLES = ("step_definitions", "dependencies")


def canonical_json(obj: Any) -> str:
    """Canonical JSON used for every hash in the data layer."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def seed(conn: psycopg.Connection, inputs: dict[str, Any]) -> dict[str, Any]:
    """Seed one fixture; return ``{dataset_version, dataset_hash, inserted, skipped}``."""
    ing = validate_batch(inputs)
    rows = ing.accepted_rows
    dataset_hash = sha256_hex(canonical_json(inputs))
    version = f"ds-{dataset_hash[:12]}"
    with conn.cursor(row_factory=tuple_row) as cur:  # independent of the caller's row factory
        published = {r[0] for r in cur.execute(
            "SELECT workflow_version_id FROM workflow_versions WHERE published_at IS NOT NULL").fetchall()}
    step_versions = {s["step_definition_id"]: s["workflow_version_id"] for s in rows["step_definitions"]}
    inst_version = {s["step_instance_id"]: s.get("version_number", 1) for s in rows["step_instances"]}
    inserted: dict[str, int] = {}
    for cid in sorted({r["calendar_id"] for ent in ("sla_rules", "calendar_intervals") for r in rows[ent]}):
        conn.execute("INSERT INTO calendars (calendar_id) VALUES (%s) ON CONFLICT DO NOTHING", (cid,))  # Q-05 (FK target)
    for ent in INSERT_ORDER:
        cols = COLUMNS[ent]
        sql = (f"INSERT INTO {ent} ({', '.join(cols)}) "  # ent/cols are constants above
               f"VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING")
        n = 0
        for row in rows[ent]:
            if ent == "step_definitions" and row["workflow_version_id"] in published:
                continue  # already published: its definition is immutable
            if ent == "dependencies" and step_versions.get(row["step_definition_id"]) in published:
                continue
            row = dict(row)
            if ent == "approvals" and row.get("version_number") is None:
                row["version_number"] = inst_version.get(row["step_instance_id"], 1)
            vals = [row.get(c, DEFAULTS.get(c)) for c in cols]
            vals = [Jsonb(v) if isinstance(v, dict) else v for v in vals]
            n += conn.execute(sql, vals).rowcount
        inserted[ent] = n
    # Required document types, then publish (the hash is the fixture's when given, else computed).
    n = 0
    for wfv, types in ing.requirements.items():
        if wfv in published or not any(v["workflow_version_id"] == wfv for v in rows["workflow_versions"]):
            continue
        for t in types:
            n += conn.execute("INSERT INTO workflow_requirements (workflow_version_id, document_type) "
                              "VALUES (%s, %s) ON CONFLICT DO NOTHING", (wfv, t)).rowcount
    inserted["workflow_requirements"] = n
    for v in rows["workflow_versions"]:
        if v.get("published_at") is None:
            continue
        steps = [s for s in rows["step_definitions"] if s["workflow_version_id"] == v["workflow_version_id"]]
        deps = [d for d in rows["dependencies"] if step_versions.get(d["step_definition_id"]) == v["workflow_version_id"]]
        dhash = v.get("definition_hash") or definition_hash(
            steps, [{"dependency_type": "mandatory", **d} for d in deps])
        conn.execute("UPDATE workflow_versions SET published_at = %s, definition_hash = %s "
                     "WHERE workflow_version_id = %s AND published_at IS NULL",
                     (v["published_at"], dhash, v["workflow_version_id"]))
    batch_id = f"batch-seed-{dataset_hash[:16]}"
    if ing.rejected:
        conn.execute("INSERT INTO raw_batches (batch_id, idempotency_key, payload_hash, payload, status) "
                     "VALUES (%s, %s, %s, %s, 'partial') ON CONFLICT DO NOTHING",
                     (batch_id, f"seed-{dataset_hash[:32]}", dataset_hash, Jsonb(inputs)))
        for rej in ing.rejected:
            conn.execute("INSERT INTO rejected_records (entity, id, reason_code, raw_row, batch_id) "
                         "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                         (rej.entity, rej.id, rej.reason_code, Jsonb(rej.raw_row), batch_id))
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version) "
                 "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (version, dataset_hash, CONTRACT_VERSION))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": inserted,
            "skipped": len(ing.rejected)}


def main(argv: list[str]) -> int:
    url = os.environ.get("DATABASE_URL")
    if not url or len(argv) != 1:
        print("usage: DATABASE_URL=... python data/seed.py <inputs.json>", file=sys.stderr)
        return 2
    inputs = json.loads(Path(argv[0]).read_text())
    with psycopg.connect(url) as conn:
        print(json.dumps(seed(conn, inputs), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
