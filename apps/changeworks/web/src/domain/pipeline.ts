// `runPipeline`: validate a dataset, compute the metrics, and shape the result exactly like expected.json.
import type { Window } from "./context";
import { CONTRACT_VERSION, type Row } from "./contract";
import { compute, type Computation } from "./metrics";
import { ingestCounts, parseAsOf, rejectedRecords, validateBatch, type Ingest, type Population } from "./ingest";
import { isoSeconds, parseTs, type Instant } from "./time";

export interface PipelineResult {
  ingest: Ingest; population: Population; asOf: Instant; computation: Computation; metrics: Row; warnings: Row[];
  emptyPopulation: boolean;
}

export function runPipeline(inputs: Row, asOf?: string | null, window?: Window | null, scenarioIds?: readonly string[] | null): PipelineResult {
  const ing = validateBatch(inputs);
  const when = parseTs(asOf ?? inputs["as_of"]);
  const computation = compute(ing.population, when, window, scenarioIds);
  return { ingest: ing, population: ing.population, asOf: when, computation, metrics: computation.metrics, warnings: computation.warnings, emptyPopulation: !ing.population.acc.initiatives.length };
}

/** The whole shape of expected.json. */
export function goldenOf(res: PipelineResult): Row {
  const cfg = res.population.config;
  const same = res.asOf === parseAsOf(cfg["as_of"]);
  return {
    contract_version: CONTRACT_VERSION, as_of: same ? cfg["as_of"] : isoSeconds(res.asOf), period_basis: cfg["period_basis"], empty_population: res.emptyPopulation,
    ingest: { counts: ingestCounts(res.ingest), rejected_records: rejectedRecords(res.ingest) }, metrics: res.metrics,
  };
}
