// App-level data context: loads the snapshot once, runs the TypeScript pipeline over it in the browser and exposes the result.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { loadSnapshot, type Snapshot } from "../data/load";
import { runPipeline, type PipelineResult } from "../domain/pipeline";

export type AppState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; snapshot: Snapshot; result: PipelineResult };
export type Ready = Extract<AppState, { status: "ready" }>;
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
        try { setState({ status: "ready", snapshot: res.snapshot, result: runPipeline(res.snapshot.inputs, { stored: true }) }); }
        catch (e) { setState({ status: "error", error: `Recomputation failed: ${e instanceof Error ? e.message : String(e)}` }); }
      }, 0);
    });
    return () => { live = false; };
  }, [attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const value = useMemo(() => ({ state, reload }), [state, reload]);
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}
export const useStore = (): Ctx => useContext(StoreContext);
