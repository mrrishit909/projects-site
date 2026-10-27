"""Load a fixture ``inputs.json`` into the tables, idempotently (``ON CONFLICT DO NOTHING``).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json [--dataset-version NAME]

Rows go through the domain's ``validate_batch`` (the same rules as the API): a rejected record is kept in ``rejected_records`` with its raw row,
reason code and details, and is not loaded; its children are DEPENDENT_REJECTED. The whole load is one transaction (the initiatives' foreign key to
the approved baseline is checked at commit). An initiative whose ``baseline_version`` names a version with no accepted baseline row is loaded with a
null baseline_version and reported in ``warnings``. Each load records one ``dataset_versions`` row; ``dataset_version`` defaults to ``ds-<first 12
of the hash>`` and may be named by the caller so that commands prepared against a published dataset match the database's current one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

for _p in (Path(__file__).resolve().parents[1] / "domain",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from changeworks import CONTRACT_VERSION, validate_batch  # noqa: E402
from changeworks.contract import ENTITIES  # noqa: E402
from changeworks.timeutil import parse_ts  # noqa: E402


def canonical_json(obj: Any) -> str:
    """Canonical JSON used for every hash in the data layer."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Lexeme(float):
    """A JSON number read with its original text (R9-22): a float for every rule, the text for the rejected-record echo."""
    text: str

    def __new__(cls, text: str) -> "Lexeme":
        o = super().__new__(cls, text)
        o.text = text
        return o


def load_json(text: str) -> Any:
    """json.loads that keeps a fractional or exponent number's original lexeme (1.50 stays 1.50, 1e3 stays 1e3)."""
    return json.loads(text, parse_float=Lexeme)


def dump_raw(value: Any) -> str:
    """json.dumps for a raw row: a Lexeme is written as its original text, everything else as usual."""
    tag = "\u0000lexeme:"
    def walk(v: Any) -> Any:
        if isinstance(v, Lexeme):
            return tag + v.text
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v
    out = json.dumps(walk(value), separators=(",", ":"))
    return re.sub(r'"\\u0000lexeme:([^"]+)"', r"\1", out)


def insert_rejected(conn: psycopg.Connection, batch_id: str, rejected: list[Any]) -> None:
    """Keep every rejected raw row; two occurrences of one id get different ordinals."""
    seen: dict[tuple[str, str, str], int] = {}
    for rej in rejected:
        rid = str(rej.id)
        k = (rej.entity, rid, rej.reason_code)
        n = seen[k] = seen.get(k, -1) + 1
        conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, details, raw_row, ordinal) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                     "ON CONFLICT DO NOTHING", (batch_id, rej.entity, rid, rej.reason_code, Jsonb(rej.details), Jsonb(rej.raw_row, dumps=dump_raw), n))


#: entity -> (table, [(column, key of the row, conversion)], actor column, instant column). Conversions: ts (ISO Z -> datetime), json (list -> jsonb).
INSERTS: dict[str, tuple[str, list[tuple[str, str, str | None]], str | None, str | None]] = {
    "initiatives": ("initiatives", [(c, c, None) for c in ("initiative_id", "title", "sponsor_id", "status", "baseline_version", "requested_start_period", "duration_periods",
                                                          "deployment_period", "eligibility_rule_version")], "created_by", "created_at"),
    "process_baselines": ("process_baselines", [(c, c, None) for c in ("baseline_id", "initiative_id", "baseline_version", "volume", "minutes_per_case", "error_rate",
                                                                      "evidence_ref")] + [("measured_at", "measured_at", "ts"), ("reason", "reason", None)], "created_by", "created_at"),
    "assumption_versions": ("assumption_versions", [(c, c, None) for c in ("assumption_id", "initiative_id", "name", "version_number", "value")] + [("value_list", "values", "json")] +
                            [(c, c, None) for c in ("unit", "rationale", "author_id", "evidence_ref", "staffing_change_evidence_ref")] + [("created_at", "created_at", "ts")], None, None),
    "resources": ("resources", [(c, c, None) for c in ("resource_id", "name", "capacity_per_period", "unit")], None, None),
    "scenario_versions": ("scenario_versions", [(c, c, None) for c in ("scenario_id", "baseline_version", "discount_rate", "rate_basis", "rate_conversion_assumption_id",
                                                                      "horizon_periods", "status")] + [("created_at", "created_at", "ts"), ("initiatives_expected", "_n_initiatives", None),
                                                                                                       ("pins_expected", "_n_pins", None)], "created_by", None),
    "cost_items": ("cost_items", [(c, c, None) for c in ("cost_id", "initiative_id", "cost_key", "cost_type", "cost_basis", "amount", "period_index", "start_period",
                                                         "end_period", "baseline_version")] + [("recorded_at", "recorded_at", "ts?")], None, "recorded_at"),
    "benefit_items": ("benefit_items", [(c, c, None) for c in ("benefit_id", "initiative_id", "benefit_type", "amount", "period_index", "starts_period", "unit",
                                                               "cash_realisation", "evidence_ref", "benefit_source_key", "baseline_trend_per_period")] +
                      [("recorded_at", "recorded_at", "ts?")], None, "recorded_at"),
    "dependencies": ("dependencies", [(c, c, None) for c in ("dependency_id", "initiative_id", "prerequisite_id", "dependency_type", "lag_periods")], None, None),
    "stakeholder_groups": ("stakeholder_groups", [(c, c, None) for c in ("group_id", "group_name", "owner_id", "affected_count", "impact_level")], None, None),
    "impact_mappings": ("impact_mappings", [(c, c, None) for c in ("mapping_id", "initiative_id", "group_id", "operating_change", "impact_level")], None, None),
    "resource_allocations": ("resource_allocations", [(c, c, None) for c in ("allocation_id", "resource_id", "initiative_id", "period_index", "amount")], None, None),
    "readiness_assessments": ("readiness_assessments", [(c, c, None) for c in ("assessment_id", "group_id", "dimension", "score", "weight")] +
                              [("assessed_at", "assessed_at", "ts")], "assessed_by", None),
    "adoption_observations": ("adoption_observations", [(c, c, None) for c in ("observation_id", "initiative_id", "eligible_count", "adopted_count")] +
                              [("observed_at", "observed_at", "ts"), ("eligibility_rule_version", "eligibility_rule_version", None), ("recorded_at", "recorded_at", "ts?")],
                              "recorded_by", "recorded_at"),
    "training_completions": ("training_completions", [(c, c, None) for c in ("training_id", "initiative_id", "eligible_trainees", "completed")] +
                             [("recorded_at", "recorded_at", "ts"), ("eligibility_rule_version", "eligibility_rule_version", None), ("entered_at", "entered_at", "ts?")],
                             "recorded_by", "entered_at"),
    "benefit_observations": ("benefit_observations", [(c, c, None) for c in ("benefit_observation_id", "benefit_id", "measured_value", "evidence_ref")] +
                             [("observed_at", "observed_at", "ts"), ("recorded_at", "recorded_at", "ts?")], "recorded_by", "recorded_at"),
    "risk_items": ("risk_items", [(c, c, None) for c in ("risk_id", "initiative_id", "probability", "impact", "mitigation")], None, None),
    "forecast_versions": ("forecast_versions", [(c, c, None) for c in ("forecast_id", "initiative_id", "version_number", "period_index", "amount", "reason")] +
                          [("created_at", "created_at", "ts")], "created_by", None),
}


def insert_row(conn: psycopg.Connection, entity: str, r: dict[str, Any], by: str | None = None, at: Any = None) -> int:
    """INSERT one accepted domain row (the shape of inputs.json) into its table; returns the rows inserted (0 when it already exists). ``by`` / ``at``
    stamp the actor (and the creation instant where the table has one) of a row that came through the API."""
    table, cols, by_col, at_col = INSERTS[entity]
    if entity == "scenario_versions":          # the sizes the scenario is sealed at (R9-01): its sets cannot grow afterwards
        r = {**r, "_n_initiatives": len(set(r["initiative_ids"])), "_n_pins": len(set(r["pinned_assumption_ids"]))}
    names = [c for c, _, _ in cols]
    vals = [(parse_ts(r[k]) if conv == "ts" else (parse_ts(r[k]) if r.get(k) else None) if conv == "ts?" else None if conv == "json" and r[k] is None else
             Jsonb(r[k]) if conv == "json" else r[k]) for _, k, conv in cols]
    if at is not None and at_col and at_col in names:          # the server's instant replaces any the row carries (the API row carries the same one)
        vals[names.index(at_col)] = at
    elif at is not None and at_col:
        names.append(at_col)
        vals.append(at)
    if by is not None and by_col:
        names.append(by_col)
        vals.append(by)
    conflict = "" if by is not None else " ON CONFLICT DO NOTHING"        # the API never skips a row silently: a clash is a UniqueViolation (409)
    n = conn.execute(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))}){conflict}", vals).rowcount     # constants only
    if entity == "scenario_versions" and n:
        for iid in sorted(set(r["initiative_ids"])):
            conn.execute("INSERT INTO scenario_initiatives VALUES (%s,%s) ON CONFLICT DO NOTHING", (r["scenario_id"], iid))
        for aid in sorted(set(r["pinned_assumption_ids"])):
            conn.execute("INSERT INTO scenario_pins VALUES (%s,%s) ON CONFLICT DO NOTHING", (r["scenario_id"], aid))
    return n


def seed(conn: psycopg.Connection, inputs: dict[str, Any], dataset_version: str | None = None, dataset_hash: str | None = None) -> dict[str, Any]:
    """Seed one fixture; return ``{dataset_version, dataset_hash, inserted, skipped, warnings}``."""
    ing = validate_batch(inputs)
    pop = ing.population
    dataset_hash = dataset_hash or sha256_hex(canonical_json(inputs))
    version = dataset_version or f"ds-{dataset_hash[:12]}"
    n = {e: 0 for e in ENTITIES}
    warnings: list[dict[str, Any]] = []
    conn.execute("INSERT INTO dataset_config (id, period_basis, period_start, as_of) VALUES (1, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                 (inputs["period_basis"], inputs["period_start"], parse_ts(inputs["as_of"]) if inputs.get("as_of") else None))
    baselines = {(b["initiative_id"], b["baseline_version"]) for b in pop.acc["process_baselines"]}
    for e in ENTITIES:
        for r in pop.acc[e]:
            if e == "initiatives" and r["baseline_version"] is not None and (r["initiative_id"], r["baseline_version"]) not in baselines:
                warnings.append({"code": "BASELINE_NOT_LOADED", "path": f"initiatives.{r['initiative_id']}",
                                 "message": f"baseline {r['baseline_version']} has no accepted baseline row; the initiative is loaded without an approved baseline"})
                r = {**r, "baseline_version": None}
            n[e] += insert_row(conn, e, r)
        if e == "process_baselines":          # the approvals the initiatives name (deferred foreign key), after the baselines exist
            for i in pop.acc["initiatives"]:
                if i["baseline_version"] is not None and (i["initiative_id"], i["baseline_version"]) in baselines:
                    conn.execute("INSERT INTO baseline_approvals (approval_id, initiative_id, baseline_version, approved_by, approved_at, reason) "
                                 "VALUES (%s,%s,%s,'seed',%s,'loaded as approved') ON CONFLICT DO NOTHING",
                                 (f"appr-{i['initiative_id']}-{i['baseline_version']}", i["initiative_id"], i["baseline_version"],
                                  parse_ts(inputs["as_of"]) if inputs.get("as_of") else parse_ts("1970-01-01T00:00:00Z")))
    if ing.rejected:
        insert_rejected(conn, f"batch-seed-{dataset_hash[:16]}", ing.rejected)
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version, as_of) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                 (version, dataset_hash, str(CONTRACT_VERSION), parse_ts(inputs["as_of"]) if inputs.get("as_of") else None))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": n, "skipped": len(ing.rejected), "warnings": warnings}


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
    inputs = load_json(Path(args[0]).read_text())
    with psycopg.connect(url) as conn:
        print(json.dumps(seed(conn, inputs, dataset_version=version), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
