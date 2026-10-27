// Loads a published dataset: manifest.json then every entity file, relative to BASE_URL + "data/". On any failure it returns an
// explicit error; nothing is ever invented. `?dataset=golden` reads data/golden/ (the hand-derived fixture) instead of the snapshot.
import { makeDataset, type Dataset, type DatasetId } from "./dataset";
import { FILES, isManifest, rawOf } from "./inputs";

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
        const names = FILES.map((e) => `${e}.json`);
        const [files, expected, injections] = await Promise.all([
          Promise.all(FILES.map(async (n, i) => [n, await getJson(dataUrl(names[i]!, id), names[i]!)] as const)),
          id === "golden" ? getJson(dataUrl("expected.json", id), "expected.json") : Promise.resolve(null),
          id === "snapshot" && manifest.injection_manifest ? getJson(dataUrl(manifest.injection_manifest, id), manifest.injection_manifest) : Promise.resolve(null),
        ]);
        const dataset = makeDataset(id, manifest, rawOf(new Map(files)), expected as Dataset["expected"], injections as Dataset["injections"]);
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
