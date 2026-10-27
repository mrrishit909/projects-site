// Loads a dataset: the published snapshot (manifest.json, injection-manifest.json and the 16 entity files, relative to BASE_URL + "data/") or the golden
// fixture (bundled). On any failure it returns an explicit error; nothing is ever invented.
import { checkInstants } from "../domain/ingest";
import { sha256Hex } from "../domain/sha256";
import { analyseGolden, analyseSnapshot, type Dataset } from "./analyse";
import { buildInputs, ENTITY_FILES, isManifest, rawOf } from "./files";
import { loadGolden } from "./golden";

export type DatasetId = "snapshot" | "golden";
export type LoadResult = { ok: true; dataset: Dataset; bytes: Record<string, number> } | { ok: false; error: string };
export const dataUrl = (file: string): string => `${import.meta.env.BASE_URL}data/${file}`;

async function getText(url: string, label: string): Promise<string> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${label}: HTTP ${res.status}`);
  return res.text();
}
const parse = (text: string, label: string): unknown => { try { return JSON.parse(text); } catch { throw new Error(`${label}: response is not valid JSON`); } };

const cache = new Map<DatasetId, Promise<LoadResult>>();
/** Loaded once per page load and shared by every view (the golden fixture and the snapshot are independent loads). */
export function loadDataset(id: DatasetId): Promise<LoadResult> {
  let p = cache.get(id);
  if (!p) {
    p = (async (): Promise<LoadResult> => {
      try {
        if (id === "golden") {
          const g = await loadGolden();
          checkInstants(g.inputs);
          return { ok: true, dataset: analyseGolden(g.inputs, g.inputsText, sha256Hex), bytes: Object.fromEntries(Object.entries(g.texts).map(([k, v]) => [k, new TextEncoder().encode(v).length])) };
        }
        const manifestText = await getText(dataUrl("manifest.json"), "manifest.json");
        const manifest = parse(manifestText, "manifest.json");
        if (!isManifest(manifest)) throw new Error("manifest.json: required fields are missing");
        const names = ENTITY_FILES.map((e) => `${e}.json`);
        const injName = manifest.injection_manifest ?? "injection-manifest.json";
        const [texts, injText] = await Promise.all([Promise.all(names.map(async (n) => [n, await getText(dataUrl(n), n)] as const)), getText(dataUrl(injName), injName)]);
        const bytes: Record<string, number> = { "manifest.json": new TextEncoder().encode(manifestText).length, [injName]: new TextEncoder().encode(injText).length };
        const files = new Map<string, unknown>();
        texts.forEach(([n, t]) => { bytes[n] = new TextEncoder().encode(t).length; files.set(n.replace(/\.json$/, ""), parse(t, n)); });
        const raw = rawOf(files);
        const { data } = buildInputs(manifest, raw);
        checkInstants(data);
        return { ok: true, dataset: analyseSnapshot(manifest, raw, parse(injText, injName) as Record<string, unknown>), bytes };
      } catch (e) {
        cache.delete(id);
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    })();
    cache.set(id, p);
  }
  return p;
}
