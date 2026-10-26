// App-level data context: loads the snapshot once, runs the pipeline over it (as published), and exposes the result plus
// the browser-memory simulation to every view.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { manifestAsOf } from "../data/inputs";
import { loadSnapshot, type Snapshot } from "../data/load";
import { runPipeline, type PipelineResult } from "../domain/pipeline";
import { createSimulation, type SimState, type SimulationStore } from "./simulation";

export type AtlasState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; snapshot: Snapshot; result: PipelineResult; simulation: SimulationStore };
export type Ready = Extract<AtlasState, { status: "ready" }>;

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
      setTimeout(() => { // let the loading state paint before the recomputation
        if (!live) return;
        try {
          const result = runPipeline(res.snapshot.inputs, null);
          setState({ status: "ready", snapshot: res.snapshot, result, simulation: createSimulation(result.population, manifestAsOf(res.snapshot.manifest)) });
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

const EMPTY: SimState = { revision: 0, log: [], last: null };
const NO_SUBSCRIBE = (): (() => void) => () => {};
/** Subscribe to the simulation store of a ready state. */
export function useSimulationState(store: SimulationStore | null): SimState {
  return useSyncExternalStore(store ? store.subscribe : NO_SUBSCRIBE, store ? store.getState : () => EMPTY);
}
