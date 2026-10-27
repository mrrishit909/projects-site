// Assembles the pipeline inputs from the published entity files (manifest.json + <entity>.json, rows under "rows").
import { ENTITIES } from "../domain/contract";
import type { PipelineInputs } from "../domain/pipeline";
import type { Row } from "../domain/models";

export interface Manifest {
  dataset_version: string; dataset_hash: string; generated_at: string; as_of: string; cutoff: string; contract_version: string;
  analysis_plan: Row; analysis_plans?: Record<string, Row>; metric_windows: Row; row_counts: Record<string, number>;
  designed_relationships?: { id: string; name: string; statement: string; realised: Record<string, unknown> }[];
  generator?: { name: string; seed: number; parameters?: { disclosures?: string[]; outcome_selection?: string; true_activation_effect_pp?: string; [k: string]: unknown } };
  stats?: Record<string, unknown>; code_sha?: string; seed?: number;
}
export const isManifest = (m: unknown): m is Manifest => {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" && typeof x.generated_at === "string" && typeof x.as_of === "string"
    && typeof x.cutoff === "string" && !!x.analysis_plan && typeof x.analysis_plan === "object" && !!x.metric_windows && typeof x.row_counts === "object" && x.row_counts !== null;
};
const rowsOf = (files: ReadonlyMap<string, unknown>, name: string): Row[] => {
  const f = files.get(name) as { rows?: Row[] } | undefined;
  if (!f || !Array.isArray(f.rows)) throw new Error(`${name}.json: no rows array`);
  return f.rows;
};
export function buildInputs(manifest: Manifest, files: ReadonlyMap<string, unknown>): PipelineInputs {
  const inputs: PipelineInputs = { contract_version: 1, as_of: manifest.as_of, cutoff: manifest.cutoff, analysis_plan: manifest.analysis_plan, metric_windows: manifest.metric_windows };
  if (manifest.analysis_plans) inputs["analysis_plans"] = manifest.analysis_plans;
  for (const e of ENTITIES) inputs[e] = rowsOf(files, e);
  return inputs;
}
