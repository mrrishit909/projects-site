// App-level data context: loads the snapshot once, runs the pipeline over it (as published), and exposes
// the result plus the browser-memory simulation to every view.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { loadSnapshot, type Snapshot } from "../data/load";
import { runPipeline, type PipelineResult } from "../domain/pipeline";
import { createSimulation, type SimState, type SimulationStore } from "./simulation";

export type StudioState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; snapshot: Snapshot; result: PipelineResult; simulation: SimulationStore };

interface Ctx { state: StudioState; reload: () => void }
const StudioContext = createContext<Ctx>({ state: { status: "loading" }, reload: () => {} });

export function StudioProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StudioState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    void loadSnapshot().then((res) => {
      if (!live) return;
      if (!res.ok) return setState({ status: "error", error: res.error });
      // Defer so the loading state paints before the recomputation.
      setTimeout(() => {
        if (!live) return;
        try {
          const cutoffs = res.snapshot.manifest.cutoffs ?? [];
          const result = runPipeline(res.snapshot.inputs, null, { cutoffs });
          setState({ status: "ready", snapshot: res.snapshot, result, simulation: createSimulation(result, null, cutoffs) });
        } catch (e) {
          setState({ status: "error", error: `Recomputation failed: ${e instanceof Error ? e.message : String(e)}` });
        }
      }, 0);
    });
    return () => { live = false; };
  }, [attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const value = useMemo(() => ({ state, reload }), [state, reload]);
  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export const useStudio = (): Ctx => useContext(StudioContext);

const NOOP_STORE: SimulationStore | null = null;
const EMPTY: SimState = { revision: 0, log: [] };
/** Subscribe to the simulation (revision and command log). Pass the store from a ready state. */
export function useSimulationState(store: SimulationStore | null = NOOP_STORE): SimState {
  return useSyncExternalStore(store ? store.subscribe : () => () => {}, store ? store.getState : () => EMPTY);
}
