// A loaded dataset: the inputs for display, the pipeline run over them in this browser, and memoised recomputation at other as-of instants
// and windows. Nothing is fetched from a server beyond the published files and nothing is invented: every figure comes from the pipeline.
import { type Row } from "../domain/contract";
import type { Window } from "../domain/context";
import { compute, type Computation } from "../domain/metrics";
import { goldenOf, runPipeline, type PipelineResult } from "../domain/pipeline";
import type { Instant } from "../domain/time";
import type { Manifest } from "./inputs";

export type DatasetId = "snapshot" | "golden";
export interface Dataset {
  id: DatasetId; manifest: Manifest; inputs: Row; expected: Row | null; injections: Row | null;
  asOf: Instant; result: PipelineResult; comp: Computation; metrics: Row;
  /** the metrics at another as-of or window, memoised */
  at(asOf: Instant, window?: Window | null): Computation;
  /** accepted rows by entity and id, for lookups */
  byId: { initiatives: Map<string, Row>; resources: Map<string, Row>; groups: Map<string, Row>; benefits: Map<string, Row>; assumptions: Map<string, Row>; scenarios: Map<string, Row> };
  goldenShape(): Row;
}
const index = (rows: Row[], key: string): Map<string, Row> => new Map(rows.map((r) => [r[key] as string, r]));

export function makeDataset(id: DatasetId, manifest: Manifest, inputs: Row, expected: Row | null, injections: Row | null): Dataset {
  const result = runPipeline(inputs);
  const memo = new Map<string, Computation>();
  const at = (t: Instant, w?: Window | null): Computation => {
    const k = `${t}|${w ? `${w[0] ?? ""}~${w[1] ?? ""}` : ""}`;
    let c = memo.get(k);
    if (!c) { c = compute(result.population, t, w ?? null); memo.set(k, c); }
    return c;
  };
  memo.set(`${result.asOf}|`, result.computation);
  const acc = result.population.acc;
  return {
    id, manifest, inputs, expected, injections, asOf: result.asOf, result, comp: result.computation, metrics: result.metrics, at,
    byId: { initiatives: index(acc.initiatives, "initiative_id"), resources: index(acc.resources, "resource_id"), groups: index(acc.stakeholder_groups, "group_id"),
      benefits: index(acc.benefit_items, "benefit_id"), assumptions: index(acc.assumption_versions, "assumption_id"), scenarios: index(acc.scenario_versions, "scenario_id") },
    goldenShape: () => goldenOf(result),
  };
}
