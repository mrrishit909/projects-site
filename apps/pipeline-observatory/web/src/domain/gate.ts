// Fail-closed quality gate and the atomic publication pointer (D-02, D-P8-08).
import type { Row } from "./contract";
import { pyInt, sortedBy } from "./py";

export const CRITICAL = "critical", ALLOWED = "allowed", BLOCKED = "blocked";
/** A quality result passes iff its failure_count is 0 (D-P8-08). */
export const checkPassed = (r: Row): boolean => pyInt(r["failure_count"]) === 0;
export interface GateResult { severity: string; eligible: number; failures: number; passed: boolean }
export interface GateDecision { results: Record<string, GateResult>; critical_failures: number; noncritical_failures: number; decision: string }
/** The gate of one run from its quality results: `allowed` iff at least one critical result exists and none failed; with no critical result
 * the gate fails closed (`blocked`). The latest result per rule name counts. A failing non-critical check never blocks. */
export function decide(results: Iterable<Row>): GateDecision {
  const out: Record<string, GateResult> = {};
  for (const q of sortedBy(results, (q) => [q["quality_result_id"] as string])) {
    out[q["rule_name"] as string] = { severity: q["severity"] as string, eligible: pyInt(q["eligible_count"]), failures: pyInt(q["failure_count"]), passed: checkPassed(q) };
  }
  const vals = Object.values(out);
  const crit = vals.filter((v) => v.severity === CRITICAL);
  const critFail = crit.filter((v) => !v.passed).length;
  const nonFail = vals.filter((v) => v.severity !== CRITICAL && !v.passed).length;
  return { results: out, critical_failures: critFail, noncritical_failures: nonFail, decision: crit.length > 0 && critFail === 0 ? ALLOWED : BLOCKED };
}
/** The pointer moves to a run's publication only if the run succeeded, its gate is allowed and a publication exists (D-P8-08). */
export const mayPublish = (runStatus: string, decision: string, hasPublication: boolean): boolean => runStatus === "success" && decision === ALLOWED && hasPublication;
