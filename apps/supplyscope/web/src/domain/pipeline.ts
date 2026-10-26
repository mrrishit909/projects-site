// End to end: ingest -> population -> metrics (D-01..D-06). Returns the same keys as domain/supplyscope/pipeline.py.
import { DomainError, UNKNOWN_STATE } from "./errors";
import { populationOf, validateBatch } from "./ingest";
import { availabilityFlags, computeMetricsFull, negativeStockFlags, type Window } from "./metrics";
import { parseTs } from "./time";
import { METRIC_KEYS } from "./contract";
import type { ExtraMetrics, IngestResult, Metrics, PipelineInputs, Population, RejectedRecord, StateSpec } from "./types";

export interface PipelineResult {
  ingest: IngestResult;
  population: Population;
  /** Exactly the keys of expected.json. */
  metrics: Metrics;
  /** The metrics added after the fixture (R3-01), next to `metrics`. */
  extraMetrics: ExtraMetrics;
  asOf: number;
  window: Window;
  /** NEGATIVE_STOCK flags, then NEGATIVE_AVAILABLE flags (R3-07). */
  flags: { flag: string; product_id: string; location_id: string; [k: string]: unknown }[];
  counts: IngestResult["counts"];
  rejected: RejectedRecord[];
}

/** `null` keeps the accepted population; a name looks up `inputs.states[name]` (`add_purchase_order_lines`); an object is used as is. */
export function resolveState(inputs: PipelineInputs, state: string | StateSpec | null): StateSpec | null {
  if (state === null || typeof state === "object") return state;
  const spec = inputs.states?.[state];
  if (spec === undefined) throw new DomainError(UNKNOWN_STATE, `unknown state ${JSON.stringify(state)}`, null, { known: Object.keys(inputs.states ?? {}).sort() });
  return spec;
}

/** Ingest `inputs`, then compute the metrics of the accepted population in `state` at `asOf` (default `inputs.as_of`) over
 * `window` (default [inputs.window_start, asOf]). */
export function runPipeline(inputs: PipelineInputs, state: string | StateSpec | null = null, asOf: string | number | null = null, window: Window | null = null): PipelineResult {
  const ingest = validateBatch(inputs);
  const population = populationOf(ingest);
  const cut = asOf === null ? parseTs(inputs.as_of) : typeof asOf === "number" ? asOf : parseTs(asOf);
  const win: Window = window ?? [inputs.window_start ? parseTs(inputs.window_start) : null, null];
  const full = computeMetricsFull(population, cut, win, resolveState(inputs, state));
  const metrics = Object.fromEntries(METRIC_KEYS.map((k) => [k, full[k]])) as Metrics;
  const extraMetrics: ExtraMetrics = { stockout_calendar_days_share: full.stockout_calendar_days_share, observed_sku_days: full.observed_sku_days };
  return { ingest, population, metrics, extraMetrics, asOf: cut, window: win, flags: [...negativeStockFlags(population, cut), ...availabilityFlags(population, cut)], counts: ingest.counts, rejected: ingest.rejected };
}
