// Loads the published snapshot: manifest.json then every entity file, relative to BASE_URL + "data/". On any failure it returns an
// explicit error; nothing is ever invented. `?dataset=golden` reads data/golden/ (the hand-derived fixture) instead.
import type { Row } from "../domain/types";
import { ALL_FILES, buildInputs, isManifest, type Manifest } from "./inputs";
import type { PipelineInputs } from "../domain/types";

export interface Snapshot { manifest: Manifest; inputs: PipelineInputs; golden: boolean; batches: Row[] }
export type LoadResult = { ok: true; snapshot: Snapshot } | { ok: false; error: string };

export function datasetId(): string {
  try { return new URLSearchParams(window.location.search).get("dataset") === "golden" ? "golden" : ""; } catch { return ""; }
}
export const dataUrl = (file: string, dataset = datasetId()): string => `${import.meta.env.BASE_URL}data/${dataset ? `${dataset}/` : ""}${file}`;

async function getJson(url: string, label: string): Promise<unknown> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${label}: HTTP ${res.status}`);
  try { return await res.json(); } catch { throw new Error(`${label}: response is not valid JSON`); }
}

export async function loadSnapshot(dataset = datasetId()): Promise<LoadResult> {
  try {
    const manifest = await getJson(dataUrl("manifest.json", dataset), "manifest.json");
    if (!isManifest(manifest)) throw new Error("manifest.json: required fields are missing");
    const files = new Map(await Promise.all(ALL_FILES.map(async (n) => [n, await getJson(dataUrl(`${n}.json`, dataset), `${n}.json`)] as const)));
    const inputs = buildInputs(manifest, files);
    const batches = ((files.get("export_batches") as { rows?: Row[] } | undefined)?.rows) ?? [];
    return { ok: true, snapshot: { manifest, inputs, golden: dataset === "golden", batches } };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
