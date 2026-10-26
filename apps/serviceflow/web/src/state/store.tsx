// App-level data context: loads the snapshot once, runs the pipeline over it in the browser and exposes the result.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { manifestWindow } from "../data/inputs";
import { loadSnapshot, type Snapshot } from "../data/load";
import { runPipeline, type PipelineResult } from "../domain/pipeline";
import { parseTs } from "../domain/time";
import type { Window } from "../domain/types";

export type AppState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; snapshot: Snapshot; result: PipelineResult; windows: NamedWindows };
export type Ready = Extract<AppState, { status: "ready" }>;
export interface NamedWindows { full: Window; training: Window | null; holdout: Window | null }

/** The full declared window and, for the published snapshot, the training (weeks 1-8) and holdout (weeks 9-12) windows. */
export function namedWindows(snapshot: Snapshot): NamedWindows {
  const w = manifestWindow(snapshot.manifest);
  const full: Window = [parseTs(w.start), parseTs(w.end)];
  const weeks = snapshot.manifest.generator?.parameters?.training_weeks;
  if (!weeks) return { full, training: null, holdout: null };
  const cut = full[0] + weeks[1] * 7 * 86400;
  return { full, training: [full[0], cut], holdout: [cut, full[1]] };
}

interface Ctx { state: AppState; reload: () => void }
const StoreContext = createContext<Ctx>({ state: { status: "loading" }, reload: () => {} });

export function Store({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    void loadSnapshot().then((res) => {
      if (!live) return;
      if (!res.ok) return setState({ status: "error", error: res.error });
      setTimeout(() => { // let the loading state paint before the recomputation
        if (!live) return;
        try {
          const result = runPipeline(res.snapshot.inputs);
          setState({ status: "ready", snapshot: res.snapshot, result, windows: namedWindows(res.snapshot) });
        } catch (e) {
          setState({ status: "error", error: `Recomputation failed: ${e instanceof Error ? e.message : String(e)}` });
        }
      }, 0);
    });
    return () => { live = false; };
  }, [attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const value = useMemo(() => ({ state, reload }), [state, reload]);
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}
export const useStore = (): Ctx => useContext(StoreContext);
