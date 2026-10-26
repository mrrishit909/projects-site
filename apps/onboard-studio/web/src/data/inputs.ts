// Builds a pipeline input batch from the published entity files (pure: no browser or Node APIs).
import { ENTITIES } from "../domain/contract";
import type { EntityFile, Manifest, PipelineInputs } from "../domain/types";

/** Names of the files a manifest lists, validated against the entities the domain needs. */
export function listedFiles(manifest: Manifest): string[] {
  const names = Object.keys(manifest.row_counts);
  for (const e of [...ENTITIES, "workflow_requirements"]) if (!names.includes(e)) throw new Error(`manifest.json does not list ${e}`);
  return names;
}

export function isManifest(m: unknown): m is Manifest {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" &&
    typeof x.generated_at === "string" && typeof x.contract_version === "string" &&
    !!x.row_counts && typeof x.row_counts === "object";
}

/** Validates each entity file against the manifest and assembles the batch (workflow_requirements rows become the D-05 block). */
export function buildInputs(manifest: Manifest, files: ReadonlyMap<string, unknown>): PipelineInputs {
  const inputs: Record<string, unknown> = { contract: manifest.contract_version };
  for (const name of listedFiles(manifest)) {
    const f = files.get(name) as Partial<EntityFile<unknown>> | undefined;
    if (!f || !Array.isArray(f.rows)) throw new Error(`${name}.json: "rows" is not an array`);
    if (f.dataset_version !== manifest.dataset_version) throw new Error(`${name}.json: dataset_version ${String(f.dataset_version)} differs from the manifest`);
    if (f.rows.length !== manifest.row_counts[name]) throw new Error(`${name}.json: ${f.rows.length} rows, manifest says ${manifest.row_counts[name]}`);
    if (name === "workflow_requirements") {
      const block: Record<string, { required_document_types: string[] }> = {};
      for (const r of f.rows as { workflow_version_id: string; required_document_types: string[] }[]) {
        block[r.workflow_version_id] = { required_document_types: r.required_document_types };
      }
      inputs.workflow_requirements = block;
    } else inputs[name] = f.rows;
  }
  return inputs as PipelineInputs;
}
