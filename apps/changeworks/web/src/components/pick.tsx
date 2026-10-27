import type { Dataset } from "../data/dataset";
import { useParam } from "../router";
import { defaultScenario } from "../lib/derive";
import { cmp } from "../domain/num";

export const scenarioIds = (ds: Dataset): string[] => Object.keys(ds.metrics["scenarios"]).sort(cmp);
/** The scenario in the address (`?scenario=`), the default when absent or unknown. */
export function useScenario(ds: Dataset): [string, (v: string) => void] {
  const dflt = defaultScenario(ds);
  const [v, set] = useParam("scenario", dflt);
  return [scenarioIds(ds).includes(v) ? v : dflt, set];
}
export const initiativeIds = (ds: Dataset): string[] => [...ds.byId.initiatives.keys()].sort(cmp);
/** An initiative of the chosen scenario (`?initiative=`), falling back to a preferred id (a designed relationship) or the first. */
export function useInitiative(ds: Dataset, sid: string, prefer?: string): [string, (v: string) => void] {
  const ids = Object.keys(ds.metrics["scenarios"][sid]?.["initiatives"] ?? {}).sort(cmp);
  const dflt = prefer && ids.includes(prefer) ? prefer : (ids[0] ?? "");
  const [v, set] = useParam("initiative", dflt);
  return [ids.includes(v) ? v : dflt, set];
}
