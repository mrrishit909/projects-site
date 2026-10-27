// Assembles the pipeline inputs from the published entity files (manifest.json + <entity>.json, rows under "rows"). The synthetic truth stays in the
// manifest: it is never put into the inputs the domain reads, and no computation touches it (it is shown only as a disclosure).
import { ENTITIES, type Row } from "../domain/contract";

export interface Manifest {
  dataset_version: string; dataset_hash: string; generated_at: string; as_of: string; contract_version: string | number; config: Row;
  row_counts: Record<string, number>;
  designed_relationships?: { id: string; name: string; statement: string; realised: Row }[];
  generator?: { name: string; seed: number; parameters?: Record<string, string> };
  programmes?: { programme_id: string; name: string; sponsor_id: string; approved_baseline_version: string | null; initiative_ids: string[] }[];
  stats?: Row; injection_manifest?: string; fixture_id?: string;
  synthetic_truth?: { note?: string; by_initiative_and_type?: Record<string, { observed_comparable_cents: number; true_attributable_share: string; true_trend_cents: number }> };
}
export const isManifest = (m: unknown): m is Manifest => {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" && typeof x.generated_at === "string" && typeof x.as_of === "string"
    && !!x.config && typeof x.config === "object" && typeof x.row_counts === "object" && x.row_counts !== null;
};
export type RawRows = Record<(typeof ENTITIES)[number], Row[]>;
export function rawOf(files: ReadonlyMap<string, unknown>): RawRows {
  return Object.fromEntries(ENTITIES.map((n) => {
    const f = files.get(n) as { rows?: Row[] } | undefined;
    if (!f || !Array.isArray(f.rows)) throw new Error(`${n}.json: no rows array`);
    return [n, f.rows];
  })) as RawRows;
}
export function buildInputs(manifest: Manifest, raw: RawRows): Row {
  const inputs: Row = { ...manifest.config };
  for (const e of ENTITIES) inputs[e] = raw[e];
  return inputs;
}
