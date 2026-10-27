// Dataset hooks: loads a dataset once per page load (shared promise), builds the population in the browser and exposes it.
import { useCallback, useEffect, useState } from "react";
import type { Dataset } from "../data/dataset";
import { loadDataset, type DatasetId } from "../data/load";
import { useSearch } from "../router";

export type DsState = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; dataset: Dataset };

/** The dataset the address asks for: the snapshot, or the golden fixture with `?dataset=golden`. */
export function usePrimaryId(): DatasetId {
  return new URLSearchParams(useSearch()).get("dataset") === "golden" ? "golden" : "snapshot";
}

export function useDataset(id: DatasetId): DsState & { reload: () => void } {
  const [state, setState] = useState<DsState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    // let the loading state paint before the recomputation blocks the thread
    const t = setTimeout(() => {
      void loadDataset(id).then((res) => { if (live) setState(res.ok ? { status: "ready", dataset: res.dataset } : { status: "error", error: res.error }); });
    }, 0);
    return () => { live = false; clearTimeout(t); };
  }, [id, attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, reload };
}
