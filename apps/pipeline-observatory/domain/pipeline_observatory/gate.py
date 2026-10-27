"""Fail-closed quality gate and the atomic publication pointer (D-02, D-P8-08)."""
from __future__ import annotations

from typing import Any, Iterable

CRITICAL = "critical"
ALLOWED, BLOCKED = "allowed", "blocked"


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
