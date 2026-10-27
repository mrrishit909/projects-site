// Issues and remediation (D-03, D-06): resolved only after a successful rerun of the same rule version; a close without it is claimed.
//   resolved  status closed AND the verification run is a rerun, for this issue, of the same rule and rule version as the run that opened it,
//             with 0 failures, at or after detection (and not after as_of). resolved_at = that rerun's run_at.
//   claimed   status closed without such a rerun. Listed separately, never counted as resolved; disabling the rule is not repair.
//   open      everything else (open, investigating, reopened); its age runs to as_of. A reopened issue keeps its first detected_at.
import { fr, h4, sumFr, div, type Fr } from "./num";
import type { Issue, Population, Row, Rule, RuleRun } from "./models";
import { cmp } from "./models";
import { hoursBetween, type Instant } from "./time";

export function verificationProblem(issue: Issue, base: RuleRun, ver: RuleRun | null | undefined, reopens: readonly Instant[] = []): string | null {
  if (!ver) return "NO_RERUN";
  if (ver.kind !== "rerun" || ver.rerun_for_issue !== issue.issue_id) return "NOT_A_RERUN_OF_THIS_ISSUE";
  if (ver.rule_id !== base.rule_id) return "DIFFERENT_RULE";
  if (ver.rule_version !== base.rule_version) return "RULE_VERSION_DIFFERS";
  if (ver.failure_count !== 0) return "RERUN_STILL_FAILING";
  if (ver.run_at < issue.detected_at) return "RERUN_BEFORE_DETECTION";
  if (reopens.length && ver.run_at < reopens.reduce((a, b) => (b > a ? b : a))) return "VERIFICATION_BEFORE_REOPEN";
  return null;
}

export type IssueClass = "resolved" | "claimed" | "open";
export interface IssueView {
  issue: Issue; rule: Rule; base: RuleRun; cls: IssueClass; resolved_at: Instant | null; cycles: number;
  /** resolution hours (resolved), claimed age (claimed) or open age (open). */
  hours: Fr;
}

export function classify(pop: Population, asOf: Instant): IssueView[] {
  const rules = new Map(pop.quality_rules.map((r) => [r.rule_id, r]));
  const runs = new Map(pop.rule_runs.map((r) => [r.rule_run_id, r]));
  const out: IssueView[] = [];
  for (const i of [...pop.issues].sort((a, b) => cmp(a.issue_id, b.issue_id))) {
    const base = runs.get(i.rule_run_id)!;
    const ver = i.verification_run_id ? runs.get(i.verification_run_id) : undefined;
    const closed = i.status === "closed" && i.closed_at !== null && i.closed_at <= asOf;
    const reopens = i.reopened_at.filter((t) => t <= asOf);
    const verified = ver !== undefined && ver.run_at <= asOf && verificationProblem(i, base, ver, reopens) === null;
    const rule = rules.get(base.rule_id)!;
    const cycles = reopens.length;
    if (closed && verified) out.push({ issue: i, rule, base, cls: "resolved", resolved_at: ver!.run_at, cycles, hours: hoursBetween(i.detected_at, ver!.run_at) });
    else if (closed) out.push({ issue: i, rule, base, cls: "claimed", resolved_at: null, cycles, hours: hoursBetween(i.detected_at, i.closed_at!) });
    else out.push({ issue: i, rule, base, cls: "open", resolved_at: null, cycles, hours: hoursBetween(i.detected_at, asOf) });
  }
  return out;
}

export function resolutionBlock(views: IssueView[]): Row {
  const resolved = views.filter((v) => v.cls === "resolved").map((v) => v.hours);
  const issues: Row = {};
  for (const v of views) {
    issues[v.issue.issue_id] = {
      rule_id: v.rule.rule_id, severity: v.rule.severity, class: v.cls,
      resolution_hours: v.cls === "resolved" ? h4(v.hours) : null, claimed_hours: v.cls === "claimed" ? h4(v.hours) : null,
      age_hours: v.cls === "open" ? h4(v.hours) : null, reopen_cycles: v.cycles,
    };
  }
  return {
    resolved_count: resolved.length, claimed_count: views.filter((v) => v.cls === "claimed").length, open_count: views.filter((v) => v.cls === "open").length,
    reopened_count: views.filter((v) => v.cycles > 0).length, reopen_cycles_total: views.reduce((a, v) => a + v.cycles, 0),
    mean_hours: resolved.length ? h4(div(sumFr(resolved), fr(resolved.length))) : null, issues,
  };
}
