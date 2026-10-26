// App-level data context: loads the snapshot once, runs the pipeline over it (as published, with
// returns), and exposes the frozen baseline plus the in-memory scenario store to every view.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { loadSnapshot, type Snapshot } from "../data/load";
import { runPipeline, type PipelineResult } from "../domain/pipeline";
import { createScenarioStore, freezeBaseline, type ScenarioState, type ScenarioStore } from "./scenario";

export type AtlasState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; snapshot: Snapshot; result: PipelineResult; store: ScenarioStore };

interface Ctx { state: AtlasState; reload: () => void }
const AtlasContext = createContext<Ctx>({ state: { status: "loading" }, reload: () => {} });

export function AtlasProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AtlasState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    void loadSnapshot().then((res) => {
      if (!live) return;
      if (!res.ok) return setState({ status: "error", error: res.error });
      // Defer so the loading state paints before the (sub-second) recomputation.
      setTimeout(() => {
        if (!live) return;
        try {
          const result = runPipeline(res.snapshot.inputs, true);
          setState({ status: "ready", snapshot: res.snapshot, result, store: createScenarioStore(freezeBaseline(result)) });
        } catch (e) {
          setState({ status: "error", error: `Recomputation failed: ${e instanceof Error ? e.message : String(e)}` });
        }
      }, 0);
    });
    return () => { live = false; };
  }, [attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const value = useMemo(() => ({ state, reload }), [state, reload]);
  return <AtlasContext.Provider value={value}>{children}</AtlasContext.Provider>;
}

export const useAtlas = (): Ctx => useContext(AtlasContext);

/** Subscribe to the scenario store (scenarios list and baseline). */
export function useScenarioState(store: ScenarioStore): ScenarioState {
  return useSyncExternalStore(store.subscribe, store.getState);
}
