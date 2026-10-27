// Assembles the pipeline inputs from the published entity files (manifest.json + <entity>.json, rows under "rows").
// The config (whitespace policy, weight and checklist versions, probe) lives in the manifest; `dataset_rows` is a flat list that carries
// its dataset_id on every row and is regrouped here (tests/test_generator.py::make_inputs does the same). The synthetic truth stays in the
// manifest and is handed only to the verification step: it is never put into the inputs the matcher reads.
import { ENTITIES } from "../domain/contract";
import type { Row } from "../domain/models";
import type { PipelineInputs } from "../domain/pipeline";

export interface Manifest {
  dataset_version: string; dataset_hash: string; generated_at: string; as_of: string; contract_version: string; config: Row;
  row_counts: Record<string, number>;
  designed_relationships?: { id: string; name: string; statement: string; realised: Record<string, unknown> }[];
  generator?: { name: string; seed: number; parameters?: Record<string, string> };
  stats?: Row; code_sha?: string; seed?: number; window_start?: string; window_end?: string; injection_manifest?: string; fixture_id?: string;
  synthetic_truth?: { note?: string; entities?: number; precision?: Row; true_entity?: Record<string, string> };
}
export const FILES = [...ENTITIES, "dataset_rows", "quality_rule_versions", "weight_versions"] as const;
export type FileName = (typeof FILES)[number];

export const isManifest = (m: unknown): m is Manifest => {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" && typeof x.generated_at === "string" && typeof x.as_of === "string"
    && !!x.config && typeof x.config === "object" && typeof x.row_counts === "object" && x.row_counts !== null;
};
const rowsOf = (files: ReadonlyMap<string, unknown>, name: string): Row[] => {
  const f = files.get(name) as { rows?: Row[] } | undefined;
  if (!f || !Array.isArray(f.rows)) throw new Error(`${name}.json: no rows array`);
  return f.rows;
};
export type RawRows = Record<FileName, Row[]>;
export function rawOf(files: ReadonlyMap<string, unknown>): RawRows {
  return Object.fromEntries(FILES.map((n) => [n, rowsOf(files, n)])) as RawRows;
}
export function buildInputs(manifest: Manifest, raw: RawRows): PipelineInputs {
  const inputs: PipelineInputs = { ...manifest.config };
  for (const e of ENTITIES) inputs[e] = raw[e];
  const grouped: Record<string, Row[]> = {};
  for (const r of raw.dataset_rows) {
    const { dataset_id, ...cells } = r;
    (grouped[dataset_id as string] ??= []).push(cells);
  }
  inputs["dataset_rows"] = grouped;
  inputs["weight_versions"] = raw.weight_versions;
  return inputs;
}
