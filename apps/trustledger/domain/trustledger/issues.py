"""Issues and remediation (D-03, D-06): resolved only after a successful rerun of the same rule version; a close without it is claimed.

  resolved  status closed AND the verification run is a rerun, for this issue, of the same rule and rule version as the run that
            opened it, with 0 failures, at or after detection (and not after ``as_of``). resolved_at = that rerun's run_at.
  claimed   status closed without such a rerun. Listed separately, never counted as resolved; disabling the rule is not repair.
  open      everything else (open, investigating, reopened); its age runs to ``as_of``. A reopened issue keeps its first detected_at.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from .models import Issue, Population, Rule, RuleRun
from .numbers import h4
from .timeutil import hours_between


def verification_problem(issue: Issue, base: RuleRun, ver: RuleRun | None, reopens: tuple[datetime, ...] = ()) -> str | None:
    """Why ``ver`` does not verify ``issue`` (None = it does). ``reopens`` are the reopen instants that count: a rerun older than the
    latest reopen verified an earlier closure, not the current one."""
    if ver is None:
        return "NO_RERUN"
    if ver.kind != "rerun" or ver.rerun_for_issue != issue.issue_id:
        return "NOT_A_RERUN_OF_THIS_ISSUE"
    if ver.rule_id != base.rule_id:
        return "DIFFERENT_RULE"
    if ver.rule_version != base.rule_version:
        return "RULE_VERSION_DIFFERS"
    if ver.failure_count != 0:
        return "RERUN_STILL_FAILING"
    if ver.run_at < issue.detected_at:
        return "RERUN_BEFORE_DETECTION"
    if reopens and ver.run_at < max(reopens):
        return "VERIFICATION_BEFORE_REOPEN"
    return None


@dataclass(frozen=True)
class IssueView:
    issue: Issue
    rule: Rule
    base: RuleRun
    cls: str                                  # resolved | claimed | open
    resolved_at: datetime | None
    cycles: int
    hours: Fraction | None                    # resolution hours (resolved), claimed age (claimed) or open age (open)

    @property
    def severity(self) -> str:
        return self.rule.severity


def classify(pop: Population, as_of: datetime) -> list[IssueView]:
    rules = {r.rule_id: r for r in pop.quality_rules}
    runs = {r.rule_run_id: r for r in pop.rule_runs}
    out = []
    for i in sorted(pop.issues, key=lambda x: x.issue_id):
        base = runs[i.rule_run_id]
        ver = runs.get(i.verification_run_id) if i.verification_run_id else None
        closed = i.status == "closed" and i.closed_at is not None and i.closed_at <= as_of
        reopens = tuple(t for t in i.reopened_at if t <= as_of)
        verified = ver is not None and ver.run_at <= as_of and verification_problem(i, base, ver, reopens) is None
        cycles = len(reopens)
        if closed and verified:
            out.append(IssueView(i, rules[base.rule_id], base, "resolved", ver.run_at, cycles, hours_between(i.detected_at, ver.run_at)))
        elif closed:
            out.append(IssueView(i, rules[base.rule_id], base, "claimed", None, cycles, hours_between(i.detected_at, i.closed_at)))
        else:
            out.append(IssueView(i, rules[base.rule_id], base, "open", None, cycles, hours_between(i.detected_at, as_of)))
    return out


def resolution_block(views: list[IssueView]) -> dict:
    resolved = [v.hours for v in views if v.cls == "resolved"]
    issues = {}
    for v in views:
        issues[v.issue.issue_id] = {
            "rule_id": v.rule.rule_id, "severity": v.severity, "class": v.cls,
            "resolution_hours": h4(v.hours) if v.cls == "resolved" else None,
            "claimed_hours": h4(v.hours) if v.cls == "claimed" else None,
            "age_hours": h4(v.hours) if v.cls == "open" else None,
            "reopen_cycles": v.cycles}
    return {"resolved_count": len(resolved), "claimed_count": sum(1 for v in views if v.cls == "claimed"),
            "open_count": sum(1 for v in views if v.cls == "open"),
            "reopened_count": sum(1 for v in views if v.cycles > 0),
            "reopen_cycles_total": sum(v.cycles for v in views),
            "mean_hours": h4(sum(resolved, Fraction(0)) / len(resolved) if resolved else None),
            "issues": issues}
