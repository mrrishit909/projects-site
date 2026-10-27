// Dataset hooks: loads a dataset once per page load (shared promise), builds the population in the browser and exposes it.
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { Dataset, DatasetId } from "../data/dataset";
import { loadDataset } from "../data/load";
import { useSearch } from "../router";

export type DsState = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; dataset: Dataset };

/** The dataset the address asks for: the snapshot, or the golden fixture with `?dataset=golden`. */
export function usePrimaryId(): DatasetId {
  return new URLSearchParams(useSearch()).get("dataset") === "golden" ? "golden" : "snapshot";
}

// A retry on one view refreshes every view that shows the same failed load (the manifest strip as well as the page).
let epoch = 0;
const epochListeners = new Set<() => void>();
const bump = (): void => { epoch++; epochListeners.forEach((l) => l()); };
const watchEpoch = (l: () => void): (() => void) => { epochListeners.add(l); return () => void epochListeners.delete(l); };

export function useDataset(id: DatasetId): DsState & { reload: () => void } {
  const [state, setState] = useState<DsState>({ status: "loading" });
  const attempt = useSyncExternalStore(watchEpoch, () => epoch);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    // let the loading state paint before the recomputation blocks the thread
    const t = setTimeout(() => {
      void loadDataset(id).then((res) => { if (live) setState(res.ok ? { status: "ready", dataset: res.dataset } : { status: "error", error: res.error }); });
    }, 0);
    return () => { live = false; clearTimeout(t); };
  }, [id, attempt]);
  const reload = useCallback(() => bump(), []);
  return { ...state, reload };
}
