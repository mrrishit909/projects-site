// End to end: ingest -> population -> metrics (D-01..D-05). Mirrors domain/onboard_studio/pipeline.py.
import { populationOf, validateBatch, type IngestResult } from "./ingest";
import { computeWithFlags, NO_WINDOW, slaUnevaluatedCases } from "./metrics";
import type { Case, CaseFigures, Flag, Metrics, PausePolicyOverride, PipelineInputs, Population, RejectedRecord, Window } from "./types";

/** A state is a name in inputs.states, a policy list for every rule, a {rule: policy | {pause_policy}} map, or null. */
export type StateSpec = string | readonly string[] | Readonly<Record<string, readonly string[] | { pause_policy: readonly string[] }>> | null;

export interface PipelineResult {
  ingest: IngestResult;
  /** The accepted population (every accepted record, parsed). */
  population: Population;
  /** Accepted cases. */
  cases: Case[];
  rejected: RejectedRecord[];
  flags: Flag[];
  /** D-09: completed cases left out of the SLA denominator (their calendar has no working interval). */
  sla_unevaluated_cases: number;
  metrics: Metrics;
  /** Exact per-case figures behind the means (completed eligible cases). */
  perCase: CaseFigures[];
}

/** Resolve a state to a pause-policy override (null keeps each rule's configured policy). */
export function pauseOverride(inputs: PipelineInputs, state: StateSpec): PausePolicyOverride {
  if (state === null) return null;
  if (Array.isArray(state)) return state as readonly string[];
  if (typeof state === "string") {
    const spec = inputs.states?.[state];
    if (spec === undefined) throw new Error(`unknown state '${state}'`);
    const out: Record<string, readonly string[]> = {};
    for (const [rule, v] of Object.entries(spec)) out[rule] = v.pause_policy;
    return out;
  }
  const out: Record<string, readonly string[]> = {};
  for (const [k, v] of Object.entries(state as Record<string, readonly string[] | { pause_policy: readonly string[] }>)) {
    out[k] = Array.isArray(v) ? (v as readonly string[]) : (v as { pause_policy: readonly string[] }).pause_policy;
  }
  return out;
}

export interface PipelineOptions { cutoffs?: readonly string[]; window?: Window }

/** Ingest `inputs`, then compute the metrics of the accepted population in `state`. */
export function runPipeline(inputs: PipelineInputs, state: StateSpec = null, opts: PipelineOptions = {}): PipelineResult {
  const ingest = validateBatch(inputs);
  const population = populationOf(ingest);
  return runOnPopulation(ingest, population, pauseOverride(inputs, state), opts.cutoffs ?? inputs.cutoffs ?? [], opts.window ?? NO_WINDOW);
}

/** Metrics over an already-ingested population (used by the simulation to recompute after an action). */
export function runOnPopulation(ingest: IngestResult, population: Population, override: PausePolicyOverride, cutoffs: readonly string[] = [], window: Window = NO_WINDOW): PipelineResult {
  const { metrics, flags, perCase } = computeWithFlags(population, override, cutoffs, window);
  return { ingest, population, cases: population.cases, rejected: ingest.rejected, flags, sla_unevaluated_cases: slaUnevaluatedCases(flags), metrics, perCase };
}
