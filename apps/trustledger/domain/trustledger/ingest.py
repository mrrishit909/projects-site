"""Ingest: validate a batch of raw rows (D-06 / D-T7-10 rejection codes, dependent rejection).

Rejection is atomic per record: a record is accepted or rejected with ONE reason code and its raw row; a child of a rejected parent
is DEPENDENT_REJECTED (never silently dropped). The order of the checks follows ``tests/reference_check.py`` for the fixtures;
codes the fixtures do not use (MALFORMED_RECORD, DUPLICATE_ID, SCHEDULE_REQUIRED, INVALID_COUNTS, ALREADY_REVIEWED, INVALID_REVERSAL,
ALREADY_REVERSED) are this backend's assumptions and are listed in README.md. The synthetic truth block is never read here.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .contract import DEFAULT_CHECKLIST, DEFAULT_TRIM, ENTITIES, ID_KEYS
from .errors import (ALREADY_REVERSED, ALREADY_REVIEWED, CLASSIFICATION_REQUIRED, DEPENDENT_REJECTED, DUPLICATE_ID,
                     DUPLICATE_PAIR, INVALID_CANDIDATE, INVALID_REVERSAL, MALFORMED_RECORD, NON_CANONICAL_ORDER, OWNER_INACTIVE,
                     OWNER_REQUIRED, REVIEWER_IS_PROPOSER, ROLE_NOT_PERMITTED, SAME_RECORD, UNKNOWN_CANDIDATE, UNKNOWN_DATASET,
                     UNKNOWN_MERGE, UNKNOWN_METRIC_VERSION, UNKNOWN_OWNER, UNKNOWN_RECORD, UNKNOWN_RULE, UNKNOWN_RULE_RUN,
                     VERIFICATION_RUN_INVALID, DomainError)
from .issues import verification_problem
from .models import Population, WeightVersion, parse
from .timeutil import parse_ts

Row = dict[str, Any]


@dataclass(frozen=True)
class Rejection:
    entity: str
    id: str
    reason_code: str
    raw_row: Row
    message: str = ""

    def as_dict(self) -> Row:
        return {"entity": self.entity, "id": self.id, "status": "rejected", "reason_code": self.reason_code, "raw_row": self.raw_row}


@dataclass
class IngestResult:
    population: Population
    rejected: list[Rejection]
    counts: dict[str, dict[str, int]]

    def rejected_dicts(self) -> list[Row]:
        return [r.as_dict() for r in self.rejected]


def blank(v: Any, trim: str = DEFAULT_TRIM) -> bool:
    """Missing: null, or (after trimming ``trim``) empty text (D-06)."""
    return v is None or (isinstance(v, str) and v.strip(trim) == "")


def _rid(row: Any, key: str) -> str:
    v = row.get(key) if isinstance(row, dict) else None
    return v if isinstance(v, str) else ""


def row_problem(row: Any, seen_ids: set[str]) -> str | None:
    """Why a dataset row cannot be loaded (None = it can): a flat object with a non-blank text ``row_id`` unique in its dataset, whose
    values are text, integers, booleans or null (nested values and floats cannot be compared as exact text)."""
    rid = row.get("row_id") if isinstance(row, dict) else None
    if not isinstance(rid, str) or not rid.strip():
        return MALFORMED_RECORD
    if rid in seen_ids:
        return DUPLICATE_ID
    if any(isinstance(v, (dict, list, float)) or (not isinstance(v, (str, int, bool)) and v is not None) for v in row.values()):
        return MALFORMED_RECORD
    return None


def parse_config(raw: Row, pop: Population) -> None:
    """Whitespace policy, weight versions, checklist versions, probes: configuration, not records."""
    wp = raw.get("whitespace_policy") or {}
    pop.trim = wp.get("trim_characters", DEFAULT_TRIM) if isinstance(wp, dict) else DEFAULT_TRIM
    pop.weight_versions = [WeightVersion(w["weight_version"], parse_ts(w["valid_from"]),
                                         {k: Fraction(v) for k, v in w["weights"].items()}) for w in raw.get("weight_versions") or []]
    pop.checklist_versions = list(raw.get("checklist_versions") or [DEFAULT_CHECKLIST])
    pop.checklist_version = raw.get("checklist_version") or pop.checklist_versions[-1]["checklist_version"]
    probe = (raw.get("probes") or {}).get("definition_at")
    pop.probe_definition_at = parse_ts(probe) if probe else None
    pop.weight_version = raw.get("weight_version")


def validate_batch(raw: Row) -> IngestResult:
    """Validate an inputs object (the shape of ``tests/fixtures/golden/inputs.json``)."""
    pop = Population()
    parse_config(raw, pop)
    trim = pop.trim
    rej: list[Rejection] = []
    rejected_ids: dict[str, set[str]] = {e: set() for e in ENTITIES}
    seen: dict[str, set[str]] = {e: set() for e in ENTITIES}

    def reject(ent: str, row: Any, code: str, msg: str = "") -> None:
        rid = _rid(row, ID_KEYS[ent])
        if rid:
            rejected_ids[ent].add(rid)
        rej.append(Rejection(ent, rid, code, row if isinstance(row, dict) else {"value": repr(row)}, msg))

    def section(ent: str) -> list[Any]:
        v = raw.get(ent, [])
        return v if isinstance(v, list) else []

    def parsed(ent: str, row: Any) -> Any | None:
        try:
            obj = parse(ent, row)
        except DomainError as err:
            # a dataset without an owner is OWNER_REQUIRED even though the typed parse would also fail on other fields: parse keeps owner null
            reject(ent, row, err.code, err.message)
            return None
        rid = row[ID_KEYS[ent]]
        if rid in seen[ent]:
            reject(ent, row, DUPLICATE_ID, f"{ID_KEYS[ent]} already loaded")
            return None
        seen[ent].add(rid)
        return obj

    owners: dict[str, Any] = {}
    for r in section("owners"):
        if (o := parsed("owners", r)) is not None:
            pop.owners.append(o)
            owners[o.owner_id] = o

    ds_ok: dict[str, Any] = {}
    for r in section("datasets"):
        d = parsed("datasets", r)
        if d is None:
            continue
        o = owners.get(d.owner_id)
        if blank(d.owner_id, trim):
            reject("datasets", r, OWNER_REQUIRED)
        elif o is None:
            reject("datasets", r, UNKNOWN_OWNER)
        elif o.deactivated_at is not None and d.registered_at >= o.deactivated_at:
            reject("datasets", r, OWNER_INACTIVE)
        elif blank(d.classification, trim):
            reject("datasets", r, CLASSIFICATION_REQUIRED)
        else:
            pop.datasets.append(d)
            ds_ok[d.dataset_id] = d
    ds_bad = rejected_ids["datasets"]

    def child(ent: str, parent_ok: Any, parent_bad: set[str], parent_key: str, unknown: str) -> list[Any]:
        out = []
        for r in section(ent):
            obj = parsed(ent, r)
            if obj is None:
                continue
            p = getattr(obj, parent_key)
            if p in parent_ok:
                out.append(obj)
            elif p in parent_bad:
                reject(ent, r, DEPENDENT_REJECTED)
            else:
                reject(ent, r, unknown)
        return out

    pop.fields = child("fields", ds_ok, ds_bad, "dataset_id", UNKNOWN_DATASET)
    pop.quality_rules = child("quality_rules", ds_ok, ds_bad, "dataset_id", UNKNOWN_DATASET)
    rules = {r.rule_id: r for r in pop.quality_rules}
    pop.rule_runs = child("rule_runs", rules, rejected_ids["quality_rules"], "rule_id", UNKNOWN_RULE)
    runs = {r.rule_run_id: r for r in pop.rule_runs}
    pop.issues = []
    issue_rows = {r.get("issue_id"): r for r in section("issues") if isinstance(r, dict)}
    for i in child("issues", runs, rejected_ids["rule_runs"], "rule_run_id", UNKNOWN_RULE_RUN):
        row = issue_rows[i.issue_id]
        ver = runs.get(i.verification_run_id) if i.verification_run_id else None
        if i.owner_id not in owners:
            reject("issues", row, UNKNOWN_OWNER)
        elif i.verification_run_id and ver is None:
            reject("issues", row, DEPENDENT_REJECTED if i.verification_run_id in rejected_ids["rule_runs"] else UNKNOWN_RULE_RUN)
        elif ver is not None and verification_problem(i, runs[i.rule_run_id], ver) is not None:
            reject("issues", row, VERIFICATION_RUN_INVALID, verification_problem(i, runs[i.rule_run_id], ver) or "")
        else:
            pop.issues.append(i)

    for r in section("lineage_edges"):                    # an edge needs both of its ends
        e = parsed("lineage_edges", r)
        if e is None:
            continue
        ends = (e.source_dataset_id, e.target_dataset_id)
        if (e.evidence_type == "observed") != (e.observed_at is not None):   # D-08: observed edges carry an instant, others none
            reject("lineage_edges", r, MALFORMED_RECORD)
        elif all(x in ds_ok for x in ends):
            pop.lineage_edges.append(e)
        elif any(x in ds_bad for x in ends):
            reject("lineage_edges", r, DEPENDENT_REJECTED)
        else:
            reject("lineage_edges", r, UNKNOWN_DATASET)

    for r in section("metric_versions"):
        if (m := parsed("metric_versions", r)) is not None:
            pop.metric_versions.append(m)
    mv_ok = {m.metric_version_id for m in pop.metric_versions}
    for r in section("definition_changes"):
        c = parsed("definition_changes", r)
        if c is not None:
            if c.metric_version_id in mv_ok and (c.previous_metric_version_id is None or c.previous_metric_version_id in mv_ok):
                pop.definition_changes.append(c)
            else:
                reject("definition_changes", r, UNKNOWN_METRIC_VERSION)

    for r in section("customer_records"):
        if (c := parsed("customer_records", r)) is not None:
            pop.customer_records.append(c)
    rec_ok = {c.record_id for c in pop.customer_records}

    seen_pairs: set[tuple[str, str]] = set()           # a pair is stored once, in canonical order (D-04)
    for r in section("match_candidates"):
        c = parsed("match_candidates", r)
        if c is None:
            continue
        lo, hi = c.left_record_id, c.right_record_id
        if lo not in rec_ok or hi not in rec_ok:
            reject("match_candidates", r, UNKNOWN_RECORD)
        elif lo == hi:
            reject("match_candidates", r, SAME_RECORD)
        elif not (0 <= c.score <= 1) or blank(c.explanation, trim):
            reject("match_candidates", r, INVALID_CANDIDATE)
        elif (min(lo, hi), max(lo, hi)) in seen_pairs:
            reject("match_candidates", r, DUPLICATE_PAIR)
        elif lo > hi:
            reject("match_candidates", r, NON_CANONICAL_ORDER)
        else:
            seen_pairs.add((lo, hi))
            pop.match_candidates.append(c)
    cand = {c.candidate_id: c for c in pop.match_candidates}
    cand_bad = rejected_ids["match_candidates"]

    accepted: dict[str, Any] = {}
    reviewed: set[str] = set()
    reversed_ids: set[str] = set()
    typed: list[tuple[Any, Any]] = []
    for r in section("merge_decisions"):
        m = parsed("merge_decisions", r)
        if m is not None:
            typed.append((m, r))
    for m, r in sorted(typed, key=lambda t: (t[0].decided_at, t[0].merge_id)):
        c = cand.get(m.candidate_id)
        rev = owners.get(m.reviewer_id)
        tgt = accepted.get(m.reverses_merge_id) if m.decision == "reverse" else None
        if m.candidate_id in cand_bad:
            reject("merge_decisions", r, DEPENDENT_REJECTED)
        elif m.decision == "reverse" and tgt is None:
            reject("merge_decisions", r, DEPENDENT_REJECTED if m.reverses_merge_id in rejected_ids["merge_decisions"] else UNKNOWN_MERGE)
        elif c is None or rev is None:
            reject("merge_decisions", r, UNKNOWN_CANDIDATE)
        elif m.reviewer_id == c.proposed_by:
            reject("merge_decisions", r, REVIEWER_IS_PROPOSER)
        elif rev.role not in ("steward", "admin") or not rev.active:
            reject("merge_decisions", r, ROLE_NOT_PERMITTED)
        elif m.decision == "reverse" and (tgt.decision != "approve" or tgt.candidate_id != m.candidate_id or blank(m.reason, trim)):
            reject("merge_decisions", r, INVALID_REVERSAL)
        elif m.decision == "reverse" and m.reverses_merge_id in reversed_ids:
            reject("merge_decisions", r, ALREADY_REVERSED)
        elif m.decision != "reverse" and m.candidate_id in reviewed:
            reject("merge_decisions", r, ALREADY_REVIEWED)
        else:
            accepted[m.merge_id] = m
            if m.decision == "reverse":
                reversed_ids.add(m.reverses_merge_id)
            else:
                reviewed.add(m.candidate_id)
    pop.merge_decisions = sorted(accepted.values(), key=lambda m: m.merge_id)

    # dataset rows follow their dataset (a dataset's whole batch is one record); a bad row is rejected on its own
    raw_rows = raw.get("dataset_rows") or {}
    rows_rejected = 0
    for dsid, rows in (raw_rows.items() if isinstance(raw_rows, dict) else ()):
        if dsid in ds_ok:
            good, ids = [], set()
            for i, row in enumerate(rows if isinstance(rows, list) else []):
                rid = row.get("row_id") if isinstance(row, dict) else None
                code = row_problem(row, ids)
                if code:
                    rows_rejected += 1
                    rej.append(Rejection("dataset_rows", f"{dsid}/{rid if isinstance(rid, str) and rid else i}", code,
                                         {"dataset_id": dsid, "row": row}))
                else:
                    ids.add(rid)
                    good.append(row)
            pop.dataset_rows[dsid] = good
        else:
            rows_rejected += len(rows)
            code = DEPENDENT_REJECTED if dsid in ds_bad else UNKNOWN_DATASET
            rej.append(Rejection("dataset_rows", dsid, code, {"dataset_id": dsid, "rows": rows}))
    rej.sort(key=lambda x: (x.entity, x.id))
    counts = {e: {"accepted": len(getattr(pop, e)), "rejected": len(rejected_ids[e])} for e in ENTITIES}
    counts["dataset_rows"] = {"accepted": sum(len(v) for v in pop.dataset_rows.values()), "rejected": rows_rejected}
    return IngestResult(pop, rej, counts)
