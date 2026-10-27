// Loads a published dataset: every file under BASE_URL + "data/" (the snapshot) or "golden/" (the hand-derived fixture, `?dataset=golden`).
// On any failure it returns an explicit error; nothing is ever invented.
import { buildGolden, buildSnapshot, SNAPSHOT_FILES, type Dataset, type DatasetId } from "./dataset";

export type LoadResult = { ok: true; dataset: Dataset } | { ok: false; error: string };

/** The dataset the address asks for: the snapshot, or the golden fixture with `?dataset=golden`. */
export function primaryId(): DatasetId {
  try { return new URLSearchParams(window.location.search).get("dataset") === "golden" ? "golden" : "snapshot"; } catch { return "snapshot"; }
}
export const fileUrl = (path: string): string => `${import.meta.env.BASE_URL}${path}`;

async function get(url: string, label: string, asText = false): Promise<unknown> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${label}: HTTP ${res.status}`);
  try { return asText ? await res.text() : await res.json(); } catch { throw new Error(`${label}: response is not valid JSON`); }
}

const cache = new Map<DatasetId, Promise<LoadResult>>();
/** Loaded once per page load and shared by every view (the golden fixture and the snapshot are independent loads). */
export function loadDataset(id: DatasetId): Promise<LoadResult> {
  let p = cache.get(id);
  if (!p) {
    p = (async (): Promise<LoadResult> => {
      try {
        if (id === "golden") {
          const [text, expected] = await Promise.all([get(fileUrl("golden/inputs.json"), "golden/inputs.json", true), get(fileUrl("golden/expected.json"), "golden/expected.json")]);
          return { ok: true, dataset: await buildGolden(text as string, expected as never) };
        }
        const entries = await Promise.all(SNAPSHOT_FILES.map(async (n) => [n, await get(fileUrl(`data/${n}.json`), `${n}.json`)] as const));
        return { ok: true, dataset: await buildSnapshot(new Map(entries)) };
      } catch (e) {
        cache.delete(id);
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    })();
    cache.set(id, p);
  }
  return p;
}
