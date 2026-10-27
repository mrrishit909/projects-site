// Loads a published dataset. The snapshot: manifest.json, then every entity file, relative to BASE_URL + "data/". The golden fixture (?dataset=golden):
// golden/inputs.json and golden/expected.json, the hand-derived case served beside the snapshot. On any failure it returns an explicit error;
// nothing is ever invented.
import { ENTITIES } from "../domain/contract";
import { makeDataset, type Dataset, type DatasetId } from "./dataset";
import { buildInputs, isManifest, rawOf, type Manifest } from "./inputs";

export type LoadResult = { ok: true; dataset: Dataset } | { ok: false; error: string };

export const GOLDEN_HASH = "e69d2a6af260354ab5e97841e656b442d6f3296973546f49cd255b7959264ae3"; // sha-256 of tests/fixtures/golden/inputs.json (HASHES.json)
const goldenManifest = (inputs: Record<string, unknown>): Manifest => ({
  dataset_version: "golden-fixture-v1", dataset_hash: GOLDEN_HASH, generated_at: String(inputs["as_of"]), as_of: String(inputs["as_of"]), contract_version: 1,
  config: { contract_version: 1, period_basis: inputs["period_basis"], period_start: inputs["period_start"], as_of: inputs["as_of"] },
  row_counts: Object.fromEntries(ENTITIES.map((e) => [e, (inputs[e] as unknown[]).length])),
  fixture_id: "golden",
});

/** The dataset the address asks for: the snapshot, or the golden fixture with `?dataset=golden`. */
export function primaryId(): DatasetId {
  try { return new URLSearchParams(window.location.search).get("dataset") === "golden" ? "golden" : "snapshot"; } catch { return "snapshot"; }
}
export const dataUrl = (file: string, id: DatasetId): string => `${import.meta.env.BASE_URL}${id === "golden" ? "golden/" : "data/"}${file}`;

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
        if (id === "golden") {
          const [inputs, expected] = await Promise.all([getJson(dataUrl("inputs.json", id), "inputs.json"), getJson(dataUrl("expected.json", id), "expected.json")]);
          if (!inputs || typeof inputs !== "object" || !ENTITIES.every((e) => Array.isArray((inputs as Record<string, unknown>)[e]))) throw new Error("inputs.json: entity arrays are missing");
          return { ok: true, dataset: makeDataset(id, goldenManifest(inputs as Record<string, unknown>), inputs as Record<string, never>, expected as Record<string, never>, null) };
        }
        const manifest = await getJson(dataUrl("manifest.json", id), "manifest.json");
        if (!isManifest(manifest)) throw new Error("manifest.json: required fields are missing");
        const names = ENTITIES.map((e) => `${e}.json`);
        const [files, injections] = await Promise.all([
          Promise.all(ENTITIES.map(async (n, i) => [n, await getJson(dataUrl(names[i]!, id), names[i]!)] as const)),
          manifest.injection_manifest ? getJson(dataUrl(manifest.injection_manifest, id), manifest.injection_manifest) : Promise.resolve(null),
        ]);
        const raw = rawOf(new Map(files));
        return { ok: true, dataset: makeDataset(id, manifest, buildInputs(manifest, raw), null, injections as Record<string, never> | null) };
      } catch (e) {
        cache.delete(id);
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    })();
    cache.set(id, p);
  }
  return p;
}
