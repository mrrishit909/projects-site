// A loaded dataset: the raw rows for display, the pipeline run over them in this browser, and memoised recomputation at other as-of
// instants and weight versions. Nothing here is fetched from a server and nothing is invented: every figure comes from the pipeline.
import type { Computation } from "../domain/metrics";
import { compute } from "../domain/metrics";
import type { Row } from "../domain/models";
import { goldenOf, runPipeline, type PipelineInputs, type PipelineResult } from "../domain/pipeline";
import type { Instant } from "../domain/time";
import { isoZ } from "../domain/time";
import type { Truth } from "../domain/verification";
import { buildInputs, type Manifest, type RawRows } from "./inputs";

export type DatasetId = "snapshot" | "golden";
export interface Dataset {
  id: DatasetId; manifest: Manifest; raw: RawRows; inputs: PipelineInputs; expected: Row | null; injections: Row | null;
  asOf: Instant; result: PipelineResult; truth: Truth | null;
  /** The metrics at `asOf` under `weightVersion` (default: the version in force). Memoised. */
  at(asOf: Instant, weightVersion?: string | null): Computation;
  /** The default computation at the dataset's own as-of. */
  now: Computation;
  weightVersions: string[];
  byId: { owners: Map<string, Row>; datasets: Map<string, Row>; rules: Map<string, Row>; runs: Map<string, Row>; records: Map<string, Row>; candidates: Map<string, Row> };
  goldenShape(): Row;
}

const index = (rows: Row[], key: string): Map<string, Row> => new Map(rows.map((r) => [r[key] as string, r]));

export function makeDataset(id: DatasetId, manifest: Manifest, raw: RawRows, expected: Row | null, injections: Row | null): Dataset {
  const inputs = buildInputs(manifest, raw);
  const truth = manifest.synthetic_truth?.true_entity ?? null;
  const result = runPipeline(inputs, undefined, undefined, undefined, truth);
  const memo = new Map<string, Computation>();
  const at = (t: Instant, wv?: string | null): Computation => {
    const k = `${t}|${wv ?? ""}`;
    let c = memo.get(k);
    if (!c) { c = compute(result.population, t, wv ?? null, null, truth); memo.set(k, c); }
    return c;
  };
  memo.set(`${result.asOf}|`, result.computation);
  return {
    id, manifest, raw, inputs, expected, injections, asOf: result.asOf, result, truth, at, now: result.computation,
    weightVersions: result.population.weight_versions.map((w) => w.weight_version).sort(),
    byId: { owners: index(raw.owners, "owner_id"), datasets: index(raw.datasets, "dataset_id"), rules: index(raw.quality_rules, "rule_id"), runs: index(raw.rule_runs, "rule_run_id"),
      records: index(raw.customer_records, "record_id"), candidates: index(raw.match_candidates, "candidate_id") },
    goldenShape: () => goldenOf(result),
  };
}
export const asOfIso = (ds: Dataset): string => isoZ(ds.asOf)!;
