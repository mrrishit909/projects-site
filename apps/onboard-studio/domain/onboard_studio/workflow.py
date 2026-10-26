"""Workflow rules (D-02, D-03): publishing, step readiness, approval, pause and completion checks."""
from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any, Iterable, Mapping

from .contract import STEP_TRANSITIONS
from .errors import (DEPENDENCY_CYCLE, INVALID_TRANSITION, MISSING_REQUIRED_DOCUMENT, ORPHAN_REFERENCE,
                     PAUSE_REASON_NOT_CONFIGURED, ROLE_MISMATCH, SELF_APPROVAL, STEP_NOT_READY, DomainError)

Edge = tuple[str, str]  # (step, prerequisite)


def topological_order(step_ids: Iterable[str], edges: Iterable[Edge]) -> tuple[list[str], list[str]]:
    """Kahn's algorithm. Returns ``(order, leftover)``; ``leftover`` is non-empty iff there is a cycle.

    ``edges`` are ``(step, prerequisite)`` pairs. Ties are broken by step id so the order is stable.
    """
    ids = sorted(set(step_ids))
    indegree = {s: 0 for s in ids}
    followers: dict[str, list[str]] = {s: [] for s in ids}
    for step, prereq in sorted(set(edges)):
        indegree[step] += 1
        followers[prereq].append(step)
    queue = deque(s for s in ids if indegree[s] == 0)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for nxt in sorted(followers[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return order, sorted(s for s in ids if indegree[s] > 0)


def check_publishable(step_ids: Iterable[str], edges: Iterable[Edge]) -> list[str]:
    """P: reject a version whose dependencies contain a cycle (DEPENDENCY_CYCLE); returns the topological order."""
    ids, edge_list = set(step_ids), list(edges)
    for step, prereq in edge_list:
        if step not in ids or prereq not in ids:
            raise DomainError(ORPHAN_REFERENCE, "a dependency names a step that is not in the version",
                              details={"step": step, "prerequisite": prereq})
    order, leftover = topological_order(ids, edge_list)
    if leftover:
        raise DomainError(DEPENDENCY_CYCLE, "the workflow's dependencies contain a cycle",
                          path="input.dependencies", details={"steps": leftover})
    return order


def definition_hash(steps: Iterable[Mapping[str, Any]], dependencies: Iterable[Mapping[str, Any]]) -> str:
    """D-05: sha256 of compact sorted-key JSON of the ordered steps and the dependencies."""
    step_rows = sorted(steps, key=lambda s: s["sequence"])
    ids = {s["step_definition_id"] for s in step_rows}
    payload = {
        "steps": [[s["step_definition_id"], s["step_name"], s["required"], s["role_key"], s["sequence"]]
                  for s in step_rows],
        "dependencies": [[d["step_definition_id"], d["prerequisite_id"], d["dependency_type"]]
                         for d in sorted(dependencies, key=lambda d: d["dependency_id"])
                         if d["step_definition_id"] in ids],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def mandatory_prerequisites(step_definition_id: str, dependencies: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted(d["prerequisite_id"] for d in dependencies
                  if d["step_definition_id"] == step_definition_id and d["dependency_type"] == "mandatory")


def unapproved_prerequisites(step_definition_id: str, dependencies: Iterable[Mapping[str, Any]],
                             status_by_step: Mapping[str, str]) -> list[str]:
    """Mandatory prerequisites that are not ``approved`` (a prerequisite without an instance is not approved)."""
    return [p for p in mandatory_prerequisites(step_definition_id, dependencies)
            if status_by_step.get(p) != "approved"]


def step_is_ready(step_definition_id: str, dependencies: Iterable[Mapping[str, Any]],
                  status_by_step: Mapping[str, str]) -> bool:
    """D-03: a step is ready only when every mandatory prerequisite is approved."""
    return not unapproved_prerequisites(step_definition_id, dependencies, status_by_step)


def require_unlockable(step_definition_id: str, dependencies: Iterable[Mapping[str, Any]],
                       status_by_step: Mapping[str, str]) -> None:
    """C05: raise STEP_NOT_READY unless every mandatory prerequisite is approved."""
    missing = unapproved_prerequisites(step_definition_id, dependencies, status_by_step)
    if missing:
        raise DomainError(STEP_NOT_READY, "mandatory prerequisites are not approved",
                          path="input.step_instance_id", details={"unapproved": missing})


def require_transition(current: str, new: str) -> None:
    if new not in STEP_TRANSITIONS.get(current, frozenset()):
        raise DomainError(INVALID_TRANSITION, f"step cannot go from {current} to {new}",
                          details={"from": current, "to": new})


def check_approval(reviewer_id: str, reviewer_role: str, role_key: str, assignees: Iterable[str]) -> None:
    """C06 (D-03): the reviewer's role matches the step's role_key (admin may act for any role)
    and the reviewer was never an assignee of the step. Raises ROLE_MISMATCH or SELF_APPROVAL."""
    if reviewer_id in set(assignees):
        raise DomainError(SELF_APPROVAL, "a reviewer cannot approve work they were assigned",
                          path="input.step_instance_id", details={"reviewer_id": reviewer_id})
    if reviewer_role not in (role_key, "admin"):
        raise DomainError(ROLE_MISMATCH, f"the step needs role {role_key!r}", path="input.step_instance_id",
                          details={"role": reviewer_role, "role_key": role_key})


def check_pause_reason(reason_code: str, pause_policy: Iterable[str]) -> None:
    """C08 (D-01): only a reason configured in the SLA rule's pause_policy may pause."""
    if reason_code not in set(pause_policy):
        raise DomainError(PAUSE_REASON_NOT_CONFIGURED, f"{reason_code!r} is not a configured pause reason",
                          path="input.reason_code", details={"configured": sorted(pause_policy)})


def missing_for_completion(required_steps: Mapping[str, str], required_types: Iterable[str],
                           accepted_types: Iterable[str]) -> dict[str, list[str]]:
    """What stops a completion: required steps not approved and required document types not accepted.
    ``required_steps`` maps a required step definition to its instance status (``missing`` if none)."""
    accepted = set(accepted_types)
    return {"steps": sorted(s for s, st in required_steps.items() if st != "approved"),
            "document_types": sorted(t for t in set(required_types) if t not in accepted)}


def require_completable(required_steps: Mapping[str, str], required_types: Iterable[str],
                        accepted_types: Iterable[str]) -> None:
    """C09 (D-03): every required step approved and every required document type accepted."""
    missing = missing_for_completion(required_steps, required_types, accepted_types)
    if missing["steps"] or missing["document_types"]:
        raise DomainError(MISSING_REQUIRED_DOCUMENT,
                          "required steps or documents are missing for completion",
                          path="input.case_id", details=missing)


def accepted_types_latest(documents: Iterable[Any]) -> set[str]:
    """D-06 / Q-04: document types whose LATEST version (highest ``version_number``) has the effective status
    ``accepted``. A type accepted on v1 and rejected or still submitted on v2 is not accepted."""
    latest: dict[str, Any] = {}
    for d in documents:
        cur = latest.get(d.document_type)
        if cur is None or d.version_number > cur.version_number:
            latest[d.document_type] = d
    return {t for t, d in latest.items() if d.review_status == "accepted"}
