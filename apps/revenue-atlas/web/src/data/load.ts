// Loads the published snapshot: manifest.json then every entity file it lists, relative to
// BASE_URL + "data/". On any failure it returns an explicit error; nothing is ever invented.
import { ENTITIES, type EntityFile, type Manifest, type PipelineInputs, type QuotaRow } from "../domain/types";

export interface Snapshot {
  manifest: Manifest;
  /** Pipeline input batch built from the entity files' `rows`. */
  inputs: PipelineInputs;
  quotas: QuotaRow[];
}
export type LoadResult = { ok: true; snapshot: Snapshot } | { ok: false; error: string };

/** "golden" when the page was opened with ?dataset=golden (the hand-derived fixture, for the display check); else "". */
export function datasetId(): string {
  try {
    return new URLSearchParams(window.location.search).get("dataset") === "golden" ? "golden" : "";
  } catch {
    return "";
  }
}

export const dataUrl = (file: string): string => `${import.meta.env.BASE_URL}data/${datasetId() ? "golden/" : ""}${file}`;

async function getJson(file: string): Promise<unknown> {
  const res = await fetch(dataUrl(file), { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${file}: HTTP ${res.status}`);
  try {
    return await res.json();
  } catch {
    throw new Error(`${file}: response is not valid JSON`);
  }
}

function isManifest(m: unknown): m is Manifest {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" &&
    typeof x.generated_at === "string" && typeof x.contract_version === "string" &&
    !!x.row_counts && typeof x.row_counts === "object";
}

export async function loadSnapshot(): Promise<LoadResult> {
  try {
    const manifest = await getJson("manifest.json");
    if (!isManifest(manifest)) throw new Error("manifest.json: required fields are missing");
    const names = Object.keys(manifest.row_counts);
    for (const e of ENTITIES) if (!names.includes(e)) throw new Error(`manifest.json does not list ${e}`);
    const files = await Promise.all(names.map(async (n) => [n, await getJson(`${n}.json`)] as const));
    const inputs: Record<string, unknown> = { contract: manifest.contract_version };
    let quotas: QuotaRow[] = [];
    for (const [name, file] of files) {
      const f = file as Partial<EntityFile<unknown>>;
      if (!Array.isArray(f.rows)) throw new Error(`${name}.json: "rows" is not an array`);
      if (f.dataset_version !== manifest.dataset_version) {
        throw new Error(`${name}.json: dataset_version ${String(f.dataset_version)} differs from the manifest`);
      }
      if (f.rows.length !== manifest.row_counts[name]) {
        throw new Error(`${name}.json: ${f.rows.length} rows, manifest says ${manifest.row_counts[name]}`);
      }
      if (name === "quotas") quotas = f.rows as QuotaRow[];
      else inputs[name] = f.rows;
    }
    return { ok: true, snapshot: { manifest, inputs: inputs as PipelineInputs, quotas } };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
