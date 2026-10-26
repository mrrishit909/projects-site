// Loads the published snapshot: manifest.json then every entity file it lists, relative to
// BASE_URL + "data/". On any failure it returns an explicit error; nothing is ever invented.
// `?dataset=golden` reads data/golden/ (the hand-derived fixture) instead.
import type { Manifest, PipelineInputs } from "../domain/types";
import { buildInputs, isManifest, listedFiles } from "./inputs";

export interface Snapshot {
  manifest: Manifest;
  /** Pipeline input batch built from the entity files' `rows`. */
  inputs: PipelineInputs;
  /** True when this is the golden fixture, not the published dataset. */
  golden: boolean;
}
export type LoadResult = { ok: true; snapshot: Snapshot } | { ok: false; error: string };

export function datasetId(): string {
  try {
    return new URLSearchParams(window.location.search).get("dataset") === "golden" ? "golden" : "";
  } catch {
    return "";
  }
}

export const dataUrl = (file: string, dataset = datasetId()): string =>
  `${import.meta.env.BASE_URL}data/${dataset ? `${dataset}/` : ""}${file}`;

async function getJson(file: string): Promise<unknown> {
  const res = await fetch(dataUrl(file), { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${file}: HTTP ${res.status}`);
  try {
    return await res.json();
  } catch {
    throw new Error(`${file}: response is not valid JSON`);
  }
}

export async function loadSnapshot(): Promise<LoadResult> {
  try {
    const manifest = await getJson("manifest.json");
    if (!isManifest(manifest)) throw new Error("manifest.json: required fields are missing");
    const names = listedFiles(manifest);
    const files = new Map(await Promise.all(names.map(async (n) => [n, await getJson(`${n}.json`)] as const)));
    return { ok: true, snapshot: { manifest, inputs: buildInputs(manifest, files), golden: datasetId() === "golden" } };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
