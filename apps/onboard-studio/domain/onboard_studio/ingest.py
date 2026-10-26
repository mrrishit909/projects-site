"""Batch validation with dependent rejection (D-02, D-03, D-05). Pure: the same input gives an equal result.

A case that breaks a case-level rule is rejected together with every row that hangs off it (its step
instances, assignments, documents, approvals, waiting intervals and events), each carrying the case's
reason. Reasons, in priority order when several apply: WORKFLOW_VERSION_NOT_PUBLISHED, DEPENDENCY_CYCLE,
SELF_APPROVAL, STEP_NOT_READY, MISSING_REQUIRED_DOCUMENT, CASE_ALREADY_COMPLETE,
PAUSE_REASON_NOT_CONFIGURED, ORPHAN_REFERENCE. A version with a dependency cycle is rejected with its steps,
dependencies and SLA rules, and so are the cases bound to it. DECISION_CONFLICT rejects only the later
approval of a step version that already has a decision.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from . import workflow
from .contract import ACCEPTED_INPUT_CONTRACTS, CONTRACT_VERSION, ENTITIES
from .errors import (CASE_REASONS, CASE_ALREADY_COMPLETE, CONTRACT_MISMATCH, DECISION_CONFLICT,
                     DEPENDENCY_CYCLE, DUPLICATE_ID, MALFORMED_RECORD, MISSING_REQUIRED_DOCUMENT,
                     ORPHAN_REFERENCE, PAUSE_REASON_NOT_CONFIGURED, SELF_APPROVAL, STEP_NOT_READY,
                     WORKFLOW_VERSION_NOT_PUBLISHED, DomainError)
from .models import ID_FIELD, Population, RejectedRecord, normalise_requirements, parsers


@dataclass
class IngestResult:
    accepted: dict[str, list[Any]] = field(default_factory=dict)
    accepted_rows: dict[str, list[dict]] = field(default_factory=dict)
    rejected: list[RejectedRecord] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    requirements: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def population(self) -> Population:
        pop = Population(requirements=dict(self.requirements))
        for ent in ENTITIES:
            setattr(pop, ent, list(self.accepted.get(ent, [])))
        return pop

    def rejected_dicts(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.rejected]


def _case_reasons(raw_case: Any, ctx: dict[str, Any]) -> set[str]:
    """Every case-level rule the case breaks (a set; the caller picks by priority)."""
    c = raw_case
    out: set[str] = set()
    wv = ctx["versions"].get(c.workflow_version_id)
    if c.organization_id not in ctx["org_ids"] or wv is None:
        out.add(ORPHAN_REFERENCE)
    if wv is not None and (wv.published_at is None or wv.published_at > c.opened_at):
        out.add(WORKFLOW_VERSION_NOT_PUBLISHED)
    if c.workflow_version_id in ctx["cyclic_versions"]:
        out.add(DEPENDENCY_CYCLE)

    steps = {s.step_definition_id: s for s in ctx["steps_by_version"].get(c.workflow_version_id, [])}
    instances = ctx["instances_by_case"].get(c.case_id, [])
    inst_by_def = {i.step_definition_id: i for i in instances}
    if any(i.step_definition_id not in steps for i in instances):
        out.add(ORPHAN_REFERENCE)

    # SELF_APPROVAL: the reviewer is any assignee ever on the step instance.
    for a in ctx["approvals_by_case"].get(c.case_id, []):
        if a.reviewer_id in ctx["assignees"].get(a.step_instance_id, set()):
            out.add(SELF_APPROVAL)

    # STEP_NOT_READY: work began before every mandatory prerequisite was approved.
    deps = ctx["deps_by_version"].get(c.workflow_version_id, [])
    for i in instances:
        if i.status == "blocked" and i.ready_at is None and i.started_at is None:
            continue
        marks = [t for t in (i.ready_at, i.started_at) if t is not None]
        for prereq in workflow.mandatory_prerequisites(i.step_definition_id, deps_as_rows(deps)):
            pi = inst_by_def.get(prereq)
            if pi is None or pi.approved_at is None or any(pi.approved_at > t for t in marks):
                out.add(STEP_NOT_READY)

    done = c.status == "completed" or c.completed_at is not None
    if done:
        required_steps = {sid: (inst_by_def[sid].status if sid in inst_by_def else "missing")
                          for sid, s in steps.items() if s.required}
        accepted_types = workflow.accepted_types_latest(ctx["docs_by_case"].get(c.case_id, []))  # D-06: latest version
        required_types = ctx["requirements"].get(c.workflow_version_id, ())
        m = workflow.missing_for_completion(required_steps, required_types, accepted_types)
        if m["steps"] or m["document_types"]:
            out.add(MISSING_REQUIRED_DOCUMENT)

    # CASE_ALREADY_COMPLETE: a second completion, a reopening, or activity after the completion.
    events = ctx["events_by_case"].get(c.case_id, [])
    completions = [e for e in events if e.event_type == "case_completed"]
    if len(completions) > 1 or any(e.event_type == "case_reopened" for e in events) or (
            completions and any(e.occurred_at > completions[0].occurred_at for e in events)):
        out.add(CASE_ALREADY_COMPLETE)

    # PAUSE_REASON_NOT_CONFIGURED: an interval that asks to pause for a reason the SLA rule does not list.
    rule = ctx["sla_by_version"].get(c.workflow_version_id)
    for w in ctx["waiting_by_case"].get(c.case_id, []):
        if w.pause_requested and (rule is None or w.reason_code not in rule.pause_policy):
            out.add(PAUSE_REASON_NOT_CONFIGURED)
    return out


def deps_as_rows(deps: list[Any]) -> list[dict[str, str]]:
    return [{"step_definition_id": d.step_definition_id, "prerequisite_id": d.prerequisite_id,
             "dependency_type": d.dependency_type} for d in deps]


def _group(items: list[Any], key: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for x in items:
        out.setdefault(key(x), []).append(x)
    return out


def validate_batch(raw: dict[str, Any]) -> IngestResult:
    """Validate and parse a raw batch; raw rows of rejected records are kept as they arrived."""
    if raw.get("contract", CONTRACT_VERSION) not in ACCEPTED_INPUT_CONTRACTS:
        raise DomainError(CONTRACT_MISMATCH, f"expected contract {CONTRACT_VERSION}",
                          details={"got": raw.get("contract")})
    ps = parsers()
    parsed: dict[str, list[tuple[dict, Any]]] = {}
    rejected: dict[tuple[str, str], RejectedRecord] = {}
    bad_case_ids: dict[str, str] = {}
    dupes: list[RejectedRecord] = []  # a repeated id never displaces the first row carrying it

    def reject(entity: str, row: dict, code: str) -> None:
        rid = str(row.get(ID_FIELD[entity], "")) if isinstance(row, dict) else ""
        rejected.setdefault((entity, rid), RejectedRecord(entity, rid, code, copy.deepcopy(row)))

    for ent in ENTITIES:
        parsed[ent] = []
        seen: set[str] = set()
        for row in raw.get(ent) or []:
            try:
                obj = ps[ent](row)
            except (KeyError, ValueError, TypeError, AttributeError):
                reject(ent, row, MALFORMED_RECORD)
                if ent == "cases" and isinstance(row, dict) and isinstance(row.get("case_id"), str):
                    bad_case_ids[row["case_id"]] = MALFORMED_RECORD
                continue
            rid = getattr(obj, ID_FIELD[ent])
            if rid in seen:
                dupes.append(RejectedRecord(ent, rid, DUPLICATE_ID, copy.deepcopy(row)))
                continue
            seen.add(rid)
            parsed[ent].append((row, obj))

    objs = {ent: [o for _, o in parsed[ent]] for ent in ENTITIES}
    versions = {v.workflow_version_id: v for v in objs["workflow_versions"]}
    steps_by_version = _group(objs["step_definitions"], lambda s: s.workflow_version_id)
    step_version = {s.step_definition_id: s.workflow_version_id for s in objs["step_definitions"]}

    # Dependencies that name unknown steps are orphans; the rest feed Kahn's algorithm per version.
    deps_by_version: dict[str, list[Any]] = {}
    for row, d in parsed["dependencies"]:
        v1, v2 = step_version.get(d.step_definition_id), step_version.get(d.prerequisite_id)
        if v1 is None or v1 != v2:
            reject("dependencies", row, ORPHAN_REFERENCE)
        else:
            deps_by_version.setdefault(v1, []).append(d)
    cyclic: set[str] = set()
    for vid in versions:
        ids = [s.step_definition_id for s in steps_by_version.get(vid, [])]
        edges = [(d.step_definition_id, d.prerequisite_id) for d in deps_by_version.get(vid, [])]
        if workflow.topological_order(ids, edges)[1]:
            cyclic.add(vid)
    for ent, vkey in (("workflow_versions", lambda o: o.workflow_version_id),
                      ("step_definitions", lambda o: o.workflow_version_id),
                      ("sla_rules", lambda o: o.workflow_version_id)):
        for row, o in parsed[ent]:
            if vkey(o) in cyclic:
                reject(ent, row, DEPENDENCY_CYCLE)
    for row, d in parsed["dependencies"]:
        if step_version.get(d.step_definition_id) in cyclic:
            reject("dependencies", row, DEPENDENCY_CYCLE)

    step_case = {i.step_instance_id: i.case_id for i in objs["step_instances"]}
    ctx = {
        "versions": versions, "org_ids": {o.organization_id for o in objs["organizations"]},
        "cyclic_versions": cyclic, "steps_by_version": steps_by_version, "deps_by_version": deps_by_version,
        "instances_by_case": _group(objs["step_instances"], lambda i: i.case_id),
        "approvals_by_case": _group([a for a in objs["approvals"] if a.step_instance_id in step_case],
                                    lambda a: step_case[a.step_instance_id]),
        "assignees": {k: {a.assignee_id for a in v}
                      for k, v in _group(objs["assignments"], lambda a: a.step_instance_id).items()},
        "docs_by_case": _group(objs["document_versions"], lambda d: d.case_id),
        "events_by_case": _group(objs["case_events"], lambda e: e.case_id),
        "waiting_by_case": _group(objs["waiting_intervals"], lambda w: w.case_id),
        "sla_by_version": {r.workflow_version_id: r for r in objs["sla_rules"]},
        "requirements": normalise_requirements(raw.get("workflow_requirements")),
    }

    for row, c in parsed["cases"]:
        reasons = _case_reasons(c, ctx)
        if reasons:
            bad_case_ids[c.case_id] = next(r for r in CASE_REASONS if r in reasons)
    known_cases = {c.case_id for c in objs["cases"]}

    owner = {"cases": lambda r: r.case_id, "step_instances": lambda r: r.case_id,
             "assignments": lambda r: step_case.get(r.step_instance_id),
             "document_versions": lambda r: r.case_id,
             "approvals": lambda r: step_case.get(r.step_instance_id),
             "waiting_intervals": lambda r: r.case_id, "case_events": lambda r: r.case_id}
    for ent, of in owner.items():
        for row, o in parsed[ent]:
            cid = of(o)
            if cid in bad_case_ids:
                reject(ent, row, bad_case_ids[cid])
            elif cid is None or cid not in known_cases:
                reject(ent, row, ORPHAN_REFERENCE)

    # DECISION_CONFLICT: a second decision on the same step version (the earlier one stands).
    inst_version = {i.step_instance_id: i.version_number for i in objs["step_instances"]}
    first: dict[tuple[str, int], str] = {}
    for row, a in sorted(parsed["approvals"], key=lambda p: (p[1].decided_at, p[1].approval_id)):
        if ("approvals", a.approval_id) in rejected:
            continue
        key = (a.step_instance_id, a.version_number or inst_version.get(a.step_instance_id, 1))
        if key in first:
            reject("approvals", row, DECISION_CONFLICT)
        else:
            first[key] = a.approval_id

    result = IngestResult(requirements=ctx["requirements"])
    for ent in ENTITIES:
        result.accepted[ent], result.accepted_rows[ent] = [], []
        for row, obj in parsed[ent]:
            if (ent, getattr(obj, ID_FIELD[ent])) not in rejected:
                result.accepted[ent].append(obj)
                result.accepted_rows[ent].append(row)
    result.rejected = sorted([*rejected.values(), *dupes], key=lambda r: (r.entity, r.id))
    for ent in ENTITIES:
        result.counts[ent] = {"accepted": len(result.accepted[ent]),
                              "rejected": sum(1 for r in result.rejected if r.entity == ent)}
    return result
