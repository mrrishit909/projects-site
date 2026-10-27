// End to end: ingest -> metrics (D-01..D-08). The pipeline's optional truth goes only to the verification layer.
import { CONTRACT_VERSION } from "./contract";
import { rejectedDicts, validateBatch, type IngestResult } from "./ingest";
import { compute, type Computation, type Window } from "./metrics";
import type { Population, Row } from "./models";
import { isoZ, parseTs, type Instant } from "./time";
import { truthMap, type Truth } from "./verification";

export type PipelineInputs = Row;
export interface PipelineResult {
  ingest: IngestResult; population: Population; metrics: Row; warnings: Computation["warnings"]; computation: Computation; asOf: Instant; truth: Truth | null;
}

/** Ingest `inputs` (the shape of tests/fixtures/golden/inputs.json) and compute the metrics at asOf (default: the inputs' own). `truth` (or the
 * inputs' own top-level `synthetic_truth` block) goes to the precision step only; without either, precision is null. */
export function runPipeline(inputs: PipelineInputs, asOf?: string | Instant | null, weightVersion?: string | null, window?: Window | null, truth?: Truth | null): PipelineResult {
  const when = typeof asOf === "bigint" ? asOf : parseTs(asOf ?? inputs["as_of"]);
  const ing = validateBatch(inputs);
  const tm = truth ?? truthMap(inputs["synthetic_truth"]);
  const comp = compute(ing.population, when, weightVersion, window, tm);
  return { ingest: ing, population: ing.population, metrics: comp.metrics, warnings: comp.warnings, computation: comp, asOf: when, truth: tm };
}

/** The shape of expected.json. */
export function goldenOf(r: PipelineResult): Row {
  const c = r.computation;
  const out: Row = {
    contract_version: CONTRACT_VERSION, as_of: isoZ(r.asOf), weight_version: c.weight_version, checklist_version: r.population.checklist_version, empty_population: c.empty_population,
    ingest: { counts: r.ingest.counts, rejected_records: rejectedDicts(r.ingest) }, rules: c.rules, metrics: r.metrics, definitions: c.definitions, matching: c.matching,
  };
  if (Object.keys(c.timeliness_probes).length) out["timeliness_probes"] = c.timeliness_probes; // present only where the inputs state timeliness probes (the golden fixture)
  return out;
}
