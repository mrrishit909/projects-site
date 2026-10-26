// End to end: ingest -> population -> metrics -> simulations (D-01..D-05). Mirrors domain/serviceflow/pipeline.py.
import { DEFAULT_ABANDONABLE } from "./contract";
import { calendarWarnings, cutoffWarnings, type DomainWarning } from "./diagnostics";
import { validateBatch } from "./ingest";
import { computeMetrics, histories } from "./metrics";
import { goldenShape, simulate, type SimulationResult } from "./simulation";
import { parseTs } from "./time";
import type { IngestResult, Metrics, PipelineInputs, Population, Window } from "./types";
import type { History } from "./events";

export interface PipelineResult {
  ingest: IngestResult; population: Population; window: Window; cutoffs: number[]; abandonable: readonly string[];
  histories: Map<string, History>; metrics: Metrics; simulations: SimulationResult[];
  /** D-09: calendars ignored, a cutoff at or after the window end. */
  warnings: DomainWarning[];
}

export function windowOf(inputs: PipelineInputs): Window { return [parseTs(inputs.window_start), parseTs(inputs.window_end)]; }

export function runPipeline(inputs: PipelineInputs, window?: Window): PipelineResult {
  const ingest = validateBatch(inputs);
  const population = ingest.accepted;
  const win = window ?? windowOf(inputs);
  const cutoffs = (inputs.backlog_cutoffs ?? []).map(parseTs);
  const abandonable = inputs.abandonable_channels ?? DEFAULT_ABANDONABLE;
  const hist = histories(population);
  const metrics = computeMetrics(population, win, cutoffs, abandonable, hist);
  const simulations = population.simulation_runs.map((r) => simulate(r.config, r.seed, r.warmup_minutes, r.horizon_minutes, r.simulation_id));
  return { ingest, population, window: win, cutoffs, abandonable, histories: hist, metrics, simulations, warnings: [...calendarWarnings(population), ...cutoffWarnings(population, win, cutoffs)] };
}

/** The shape of expected.json: contract_version, ingest, metrics, simulation (first run or null). */
export function goldenOf(r: PipelineResult): { contract_version: number; ingest: { counts: IngestResult["counts"]; rejected_records: unknown[] }; metrics: Metrics; simulation: ReturnType<typeof goldenShape> | null } {
  return { contract_version: 1, ingest: { counts: r.ingest.counts, rejected_records: r.ingest.rejected }, metrics: r.metrics, simulation: r.simulations[0] ? goldenShape(r.simulations[0]) : null };
}
