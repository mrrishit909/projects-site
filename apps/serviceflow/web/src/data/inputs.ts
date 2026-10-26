// Builds a pipeline input batch from the published entity files (pure: no browser or Node APIs, so the Node golden check
// and the browser use the same code).
import { ENTITIES, EXTRA_ENTITIES } from "../domain/contract";
import type { Manifest, PipelineInputs } from "../domain/types";

export interface EntityFile { entity: string; dataset_version: string; rows: unknown[] }

/** Names of the files a manifest lists, validated against the entities the domain reads. */
export function listedFiles(manifest: Manifest): string[] {
  const names = Object.keys(manifest.row_counts);
  for (const e of [...ENTITIES, ...EXTRA_ENTITIES]) if (!names.includes(e)) throw new Error(`manifest.json does not list ${e}`);
  return names;
}

export function isManifest(m: unknown): m is Manifest {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" && typeof x.generated_at === "string" &&
    typeof x.contract_version === "string" && !!x.row_counts && typeof x.row_counts === "object";
}

/** The declared window of a dataset as ISO instants: the golden fixture's own window, else the generator's day span
 * from 00:00:00Z of the first day to one second after `as_of` (the snapshot cut). */
export function manifestWindow(m: Manifest): { start: string; end: string } {
  if (m.window_start && m.window_end) return { start: m.window_start, end: m.window_end };
  const p = m.generator?.parameters;
  const w = p?.window, asOf = p?.as_of;
  if (!w || !asOf) throw new Error("manifest.json declares no window");
  const end = new Date(Date.parse(asOf) + 1000).toISOString().replace(/\.000Z$/, "Z");
  return { start: `${w[0]}T00:00:00Z`, end };
}

const abandonableOf = (m: Manifest): string[] => (m.generator?.parameters as { abandonable_channels?: string[] } | undefined)?.abandonable_channels ?? ["chat", "phone"];

/** Validates each entity file against the manifest and assembles the batch. */
export function buildInputs(manifest: Manifest, files: ReadonlyMap<string, unknown>): PipelineInputs {
  if (manifest.contract_version !== "v1") throw new Error(`manifest.json: contract_version ${manifest.contract_version} is not v1`);
  const w = manifestWindow(manifest);
  const inputs: PipelineInputs = { contract_version: 1, window_start: w.start, window_end: w.end, backlog_cutoffs: manifest.backlog_cutoffs ?? [w.end], abandonable_channels: manifest.abandonable_channels ?? abandonableOf(manifest) };
  for (const name of listedFiles(manifest)) {
    const f = files.get(name) as Partial<EntityFile> | undefined;
    if (!f || !Array.isArray(f.rows)) throw new Error(`${name}.json: "rows" is not an array`);
    if (f.dataset_version !== manifest.dataset_version) throw new Error(`${name}.json: dataset_version ${String(f.dataset_version)} differs from the manifest`);
    if (f.rows.length !== manifest.row_counts[name]) throw new Error(`${name}.json: ${f.rows.length} rows, manifest says ${manifest.row_counts[name]}`);
    inputs[name] = f.rows;
  }
  return inputs;
}
