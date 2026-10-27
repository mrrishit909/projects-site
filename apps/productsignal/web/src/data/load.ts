// Loads a published dataset: manifest.json then every entity file, relative to BASE_URL + "data/". On any failure it returns an
// explicit error; nothing is ever invented. `?dataset=golden` reads data/golden/ (the hand-derived fixture) instead of the snapshot.
import { ENTITIES } from "../domain/contract";
import { makeDataset, type Dataset } from "./dataset";
import { buildInputs, isManifest } from "./inputs";

export type DatasetId = Dataset["id"];
export type LoadResult = { ok: true; dataset: Dataset } | { ok: false; error: string };

/** The dataset the address asks for: the snapshot, or the golden fixture with `?dataset=golden`. */
export function primaryId(): DatasetId {
  try { return new URLSearchParams(window.location.search).get("dataset") === "golden" ? "golden" : "snapshot"; } catch { return "snapshot"; }
}
export const dataUrl = (file: string, id: DatasetId): string => `${import.meta.env.BASE_URL}data/${id === "golden" ? "golden/" : ""}${file}`;

async function getJson(url: string, label: string): Promise<unknown> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${label}: HTTP ${res.status}`);
  try { return await res.json(); } catch { throw new Error(`${label}: response is not valid JSON`); }
}

const cache = new Map<DatasetId, Promise<LoadResult>>();
/** Loaded once per page load and shared by every view (the golden fixture and the snapshot are independent loads). */
export function loadDataset(id: DatasetId): Promise<LoadResult> {
  let p = cache.get(id);
  if (!p) {
    p = (async (): Promise<LoadResult> => {
      try {
        const manifest = await getJson(dataUrl("manifest.json", id), "manifest.json");
        if (!isManifest(manifest)) throw new Error("manifest.json: required fields are missing");
        const names = ENTITIES.map((e) => `${e}.json`);
        const [files, expected] = await Promise.all([
          Promise.all(ENTITIES.map(async (n, i) => [n, await getJson(dataUrl(names[i]!, id), names[i]!)] as const)),
          id === "golden" ? getJson(dataUrl("expected.json", id), "expected.json") : Promise.resolve(null),
        ]);
        const dataset = makeDataset(id, manifest, buildInputs(manifest, new Map(files)), expected);
        return { ok: true, dataset };
      } catch (e) {
        cache.delete(id);
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    })();
    cache.set(id, p);
  }
  return p;
}
