import type { Dataset } from "../data/dataset";
import type { AnalysisRun } from "../domain/models";
import { isoZ } from "../domain/time";
import { useParam } from "../router";
import { day } from "./format";

/** The default run: the first final run (cutoff at or after planned_end) of the first version, i.e. v1's final run. */
export function defaultRun(ds: Dataset): AnalysisRun {
  const fin = ds.runs.filter((r) => { const p = ds.plans.get(r.experiment_version_id); return !!p && r.cutoff_at >= p.planned_end; });
  return (fin.length ? fin : ds.runs).slice().sort((a, b) => (a.experiment_version_id < b.experiment_version_id ? -1 : a.experiment_version_id > b.experiment_version_id ? 1 : a.cutoff_at - b.cutoff_at))[0]!;
}
/** The analysis run in the address (`?run=an-004`). */
export function useRun(ds: Dataset): [AnalysisRun, (v: string) => void] {
  const d = defaultRun(ds);
  const [v, set] = useParam("run", d.analysis_id);
  return [ds.runs.find((r) => r.analysis_id === v) ?? d, set];
}
export const isFinal = (ds: Dataset, r: AnalysisRun): boolean => r.cutoff_at >= ds.plans.get(r.experiment_version_id)!.planned_end;
export const runLabel = (ds: Dataset, r: AnalysisRun): string =>
  `${r.analysis_id} · ${r.experiment_version_id} · ${day(isoZ(r.cutoff_at))} · ${isFinal(ds, r) ? "final" : "interim"}`;
