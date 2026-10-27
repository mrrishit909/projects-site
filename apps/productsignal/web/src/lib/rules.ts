// The decision rules of C10 (docs/contracts.md D-03, D-06), as a pure function of a run's evidence. The static site only simulates a
// decision; the rules are the API's.
import type { ExperimentOut, GuardrailReview } from "../domain/metrics";

export type Option = "ship" | "stop" | "inconclusive";
export interface Verdict { option: Option; allowed: boolean; blockers: string[]; warnings: string[] }
export const OPTIONS: readonly Option[] = ["ship", "stop", "inconclusive"];

export function decisionRules(ex: ExperimentOut, guard: GuardrailReview): Verdict[] {
  const common: string[] = [];
  if (!ex.run.plan_frozen) common.push("PLAN_NOT_FROZEN: the analysis plan was not frozen before the first run");
  const hasRun = ex.run.analysis_id !== null;
  if (!hasRun) common.push("NO_RUN: a decision cites one logged analysis run, and none is logged at this cutoff");
  const srm = ex.srm.verdict === "MISMATCH";
  return OPTIONS.map((option) => {
    const blockers = [...common], warnings: string[] = [];
    if (option === "ship") {
      if (ex.run.interim) blockers.push("INTERIM_RUN: the run is before planned_end and cannot support ship");
      if (srm) blockers.push("SRM_MISMATCH: the assignment counts do not match the allocation");
      if (guard.verdict === "HARMFUL") blockers.push("GUARDRAIL_HARMFUL: the whole interval of the error-rate difference is above 0");
      if (!ex.run.config_hash_matches_plan) blockers.push("CONFIG_HASH_MISMATCH: the run does not cite the plan's hash");
      if (!blockers.length && !ex.primary.conclusive) warnings.push("NOT_CONCLUSIVE: the interval includes 0; a ship on a non-conclusive final run is allowed but carries this warning");
    } else if (option === "stop") {
      if (srm) blockers.push("SRM_MISMATCH: the data cannot support either direction; only inconclusive is allowed (coordinator decision, D-06)");
    }
    return { option, allowed: blockers.length === 0, blockers, warnings };
  });
}
