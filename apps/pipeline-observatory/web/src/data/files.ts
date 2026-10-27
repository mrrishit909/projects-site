// The published snapshot: manifest.json, injection-manifest.json and the 16 entity files (rows under "rows"), and how they become the inputs of
// the domain. Pure functions: the browser loader (load.ts) and the node scripts (golden-check, review-check) call the same code.
import { ENTITIES, type Row } from "../domain/contract";
import { canonicalJson, cmpCodePoints } from "../domain/hashing";
import { decFr, type Fr } from "../domain/num";
import { sha256Hex } from "../domain/sha256";

export const EXTRA_FILES = ["source_expectations", "model_output_totals", "batch_summaries", "fetch_log"] as const;
/** The 16 published entity files, in the order the dataset hash walks them (sorted by name). */
export const ENTITY_FILES = [...ENTITIES, ...EXTRA_FILES].sort(cmpCodePoints);
export type EntityFile = (typeof ENTITIES)[number] | (typeof EXTRA_FILES)[number];
export type RawFiles = Record<EntityFile, Row[]>;

export interface Manifest {
  dataset_version: string; dataset_hash: string; generated_at: string; as_of: string; contract_version: number; config: Row; row_counts: Record<string, number>;
  designed_relationships?: Row[]; generator?: Row; stats?: Row; sample?: Row; full_world?: Row; code_sha?: string; seed?: number; window_start?: string; window_end?: string;
  injection_manifest?: string; fixture_id?: string;
}
export const isManifest = (m: unknown): m is Manifest => {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" && typeof x.generated_at === "string" && typeof x.as_of === "string"
    && !!x.config && typeof x.config === "object" && typeof x.row_counts === "object" && x.row_counts !== null;
};
export function rawOf(files: ReadonlyMap<string, unknown>): RawFiles {
  const out: Partial<RawFiles> = {};
  for (const n of ENTITY_FILES) {
    const f = files.get(n) as { rows?: Row[] } | undefined;
    if (!f || !Array.isArray(f.rows)) throw new Error(`${n}.json: no rows array`);
    out[n as EntityFile] = f.rows;
  }
  return out as RawFiles;
}
/** sha256 over the canonical JSON of each entity file's rows, concatenated in file-name order: the manifest's dataset_hash. */
export const datasetHash = (raw: RawFiles): string => sha256Hex(ENTITY_FILES.map((n) => canonicalJson(raw[n as EntityFile])).join(""));

/** The inputs.json-shaped object the domain runs over, plus the stored candidate totals (model_output_totals) keyed by publication. */
export function buildInputs(manifest: Manifest, raw: RawFiles): { data: Record<string, unknown>; publishedTotals: Record<string, Fr> } {
  const data: Record<string, unknown> = { ...manifest.config };
  for (const e of ENTITIES) data[e] = raw[e];
  data["source_expectations"] = raw.source_expectations;
  const totalOfRun = new Map<string, string>(raw.model_output_totals.map((t) => [t["run_id"], t["total_amount"]]));
  const publishedTotals: Record<string, Fr> = {};
  for (const p of raw.publications) { const t = totalOfRun.get(p["run_id"]); if (t !== undefined) publishedTotals[p["publication_id"]] = decFr(t); }
  return { data, publishedTotals };
}
