"""Fail-closed quality gate and the atomic publication pointer (D-02, D-P8-08, D-09 R8-02)."""
from __future__ import annotations

from typing import Any, Iterable

from .timeutil import parse_ts

CRITICAL = "critical"
ALLOWED, BLOCKED = "allowed", "blocked"
#: The two critical checks D-09 adds (R8-02): a publication may not silently omit a batch that was committed before its run started, nor a late event.
SCOPE_COMPLETE = "scope_complete"
LATE_EVENTS_INCLUDED = "late_events_included"


def scope_complete(committed: Iterable[tuple[str, Any]], included: Iterable[str], scope_from: Any, until: Any) -> tuple[int, list[str]]:
    """``scope_complete``: every committed batch of the run's scope is in the candidate publication. ``committed`` is (batch_id, committed_at) of
    every committed batch; the scope is the batches committed in ``[scope_from, until)`` (``scope_from`` None = from the beginning, ``until`` = the
    instant the run started). Returns (eligible = batches in scope, the ids missing from ``included``)."""
    lo = parse_ts(scope_from) if scope_from is not None else None
    hi = parse_ts(until)
    scope = sorted(b for b, at in committed if (lo is None or parse_ts(at) >= lo) and parse_ts(at) < hi)
    have = set(included)
    return len(scope), [b for b in scope if b not in have]


def check_passed(result: dict[str, Any]) -> bool:
    """A quality result passes iff its failure_count is 0 (D-P8-08)."""
    return int(result["failure_count"]) == 0


def decide(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The gate of one run from its quality results. ``allowed`` iff at least one critical result exists and none failed; with no
    critical result the gate fails closed (``blocked``). A failing non-critical check never blocks."""
    out: dict[str, dict[str, Any]] = {}
    for q in sorted(results, key=lambda q: q["quality_result_id"]):
        out[q["rule_name"]] = {"severity": q["severity"], "eligible": int(q["eligible_count"]), "failures": int(q["failure_count"]),
                               "passed": check_passed(q)}
    crit = [v for v in out.values() if v["severity"] == CRITICAL]
    critical_failures = sum(1 for v in crit if not v["passed"])
    noncritical_failures = sum(1 for v in out.values() if v["severity"] != CRITICAL and not v["passed"])
    return {"results": out, "critical_failures": critical_failures, "noncritical_failures": noncritical_failures,
            "decision": ALLOWED if crit and critical_failures == 0 else BLOCKED}


def may_publish(run_status: str, decision: str, has_publication: bool) -> bool:
    """The pointer moves to a run's publication only if the run succeeded, its gate is allowed and a publication exists (D-P8-08)."""
    return run_status == "success" and decision == ALLOWED and has_publication
