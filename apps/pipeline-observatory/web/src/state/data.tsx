// Dataset hooks: load once per page load (shared promise), compute in the browser, expose the result.
import { useCallback, useEffect, useState } from "react";
import type { Dataset } from "../data/analyse";
import { loadDataset, type DatasetId } from "../data/load";
import { useSearch } from "../router";

export type DsState = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; dataset: Dataset; bytes: Record<string, number> };

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
      void loadDataset(id).then((res) => { if (live) setState(res.ok ? { status: "ready", dataset: res.dataset, bytes: res.bytes } : { status: "error", error: res.error }); });
    }, 0);
    return () => { live = false; clearTimeout(t); };
  }, [id, attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, reload };
}
