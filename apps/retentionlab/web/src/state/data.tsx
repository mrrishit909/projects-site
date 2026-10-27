// Dataset hooks: load a dataset once per page load (shared promise), run the evaluation in the browser and expose it.
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { Dataset, DatasetId } from "../data/dataset";
import { loadDataset } from "../data/load";
import { useSearch } from "../router";

export type DsState = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; dataset: Dataset };

/** The dataset the address asks for: the snapshot, or the golden fixture with `?dataset=golden`. */
export function usePrimaryId(): DatasetId {
  return new URLSearchParams(useSearch()).get("dataset") === "golden" ? "golden" : "snapshot";
}

// a retry anywhere reloads every consumer (the manifest strip must recover with the view)
let epoch = 0;
const subs = new Set<() => void>();
const subscribe = (l: () => void): (() => void) => { subs.add(l); return () => void subs.delete(l); };
export function useDataset(id: DatasetId): DsState & { reload: () => void } {
  const [state, setState] = useState<DsState>({ status: "loading" });
  const attempt = useSyncExternalStore(subscribe, () => epoch);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    const t = setTimeout(() => { void loadDataset(id).then((res) => { if (live) setState(res.ok ? { status: "ready", dataset: res.dataset } : { status: "error", error: res.error }); }); }, 0);
    return () => { live = false; clearTimeout(t); };
  }, [id, attempt]);
  const reload = useCallback(() => { epoch += 1; subs.forEach((l) => l()); }, []);
  return { ...state, reload };
}
