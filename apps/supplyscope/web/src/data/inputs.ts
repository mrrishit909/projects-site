// Builds a pipeline input batch from the published entity files (pure: no browser or Node APIs, so the Node golden check
// and the browser use the same code).
import { ENTITIES, EXTRA_ENTITIES } from "../domain/contract";
import type { EntityFile, Manifest, PipelineInputs } from "../domain/types";

/** Names of the files a manifest lists, validated against the entities the domain reads. */
export function listedFiles(manifest: Manifest): string[] {
  const names = Object.keys(manifest.row_counts);
  for (const e of [...ENTITIES, ...EXTRA_ENTITIES]) if (!names.includes(e)) throw new Error(`manifest.json does not list ${e}`);
  return names;
}

export function isManifest(m: unknown): m is Manifest {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" &&
    typeof x.generated_at === "string" && typeof x.contract_version === "string" &&
    !!x.row_counts && typeof x.row_counts === "object";
}

/** The as-of instant of the dataset: the golden fixture's `as_of`, else the generator's declared parameter. */
export function manifestAsOf(manifest: Manifest): string {
  const v = manifest.as_of ?? manifest.generator?.parameters?.as_of;
  if (typeof v !== "string") throw new Error("manifest.json declares no as_of");
  return v;
}
/** The first observed day as a UTC instant. */
export function manifestWindowStart(manifest: Manifest): string | undefined {
  const v = manifest.window_start ?? manifest.generator?.parameters?.window?.[0];
  return typeof v === "string" ? (v.length === 10 ? `${v}T00:00:00Z` : v) : undefined;
}

/** Validates each entity file against the manifest and assembles the batch. */
export function buildInputs(manifest: Manifest, files: ReadonlyMap<string, unknown>): PipelineInputs {
  const inputs: PipelineInputs = { contract_version: manifest.contract_version, as_of: manifestAsOf(manifest) };
  const start = manifestWindowStart(manifest);
  if (start) inputs.window_start = start;
  if (manifest.states) inputs.states = manifest.states;
  for (const name of listedFiles(manifest)) {
    const f = files.get(name) as Partial<EntityFile<unknown>> | undefined;
    if (!f || !Array.isArray(f.rows)) throw new Error(`${name}.json: "rows" is not an array`);
    if (f.dataset_version !== manifest.dataset_version) throw new Error(`${name}.json: dataset_version ${String(f.dataset_version)} differs from the manifest`);
    if (f.rows.length !== manifest.row_counts[name]) throw new Error(`${name}.json: ${f.rows.length} rows, manifest says ${manifest.row_counts[name]}`);
    inputs[name] = f.rows;
  }
  return inputs;
}
