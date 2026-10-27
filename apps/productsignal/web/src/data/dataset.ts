// A loaded dataset (the golden fixture or the published snapshot): the ingested population plus memoised computations per cutoff.
// Windows: the manifest's own at the dataset's cutoff, the defaults for the cutoff (README assumption 3) at any other.
import { canonicalise, type Canon } from "../domain/events";
import { compute, segmentAnalysis, type Computation, type SegmentOut } from "../domain/metrics";
import { defaultWindows, type AnalysisRun, type ExperimentVersion, type FunnelDef, type Plan, type Population, type Windows } from "../domain/models";
import { goldenOf, ingestInputs, type PipelineInputs } from "../domain/pipeline";
import type { IngestResult } from "../domain/ingest";
import { DAY, parseTs } from "../domain/time";
import { SEGMENT_FIELDS } from "../domain/contract";
import type { Manifest } from "./inputs";

export interface Dataset {
  id: "golden" | "snapshot"; manifest: Manifest; inputs: PipelineInputs; ingest: IngestResult; population: Population; plans: Map<string, Plan>;
  funnel: FunnelDef | null; windows: Windows; cutoff: number; asOf: number; runs: AnalysisRun[]; versions: ExperimentVersion[]; expected: unknown;
  canonAt(cutoff: number): Canon;
  at(cutoff: number, xv?: string | null, runId?: string | null): Computation;
  segments(cutoff: number, xv: string, by: string): SegmentOut;
  /** D-10 (R6-13): the same split corrected together with every split the segments page offers (plan, segment, timezone). */
  segmentsFamily(cutoff: number, xv: string, by: string): SegmentOut;
}

export function makeDataset(id: Dataset["id"], manifest: Manifest, inputs: PipelineInputs, expected: unknown = null): Dataset {
  const { ingest, population, plans, funnel, windows } = ingestInputs(inputs);
  if (!windows) throw new Error("the dataset carries no metric_windows");
  const cutoff = parseTs(manifest.cutoff, "cutoff");
  const canons = new Map<number, Canon>();
  const comps = new Map<string, Computation>();
  const segs = new Map<string, SegmentOut>();
  const canonAt = (c: number): Canon => { let x = canons.get(c); if (!x) { x = canonicalise(population, c); canons.set(c, x); } return x; };
  return {
    id, manifest, inputs, ingest, population, plans, funnel, windows, cutoff, asOf: parseTs(manifest.as_of, "as_of"), expected,
    runs: [...population.analysis_runs].sort((a, b) => a.cutoff_at - b.cutoff_at || (a.analysis_id < b.analysis_id ? -1 : 1)), versions: population.experiment_versions,
    canonAt,
    at(c, xv = null, runId = null) {
      const key = `${c}|${xv ?? ""}|${runId ?? ""}`;
      let r = comps.get(key);
      if (!r) {
        const asOf = c === cutoff;
        r = compute(population, c, asOf ? windows : defaultWindows(c), funnel, xv, runId, null, asOf || !funnel ? null : [c - 7 * DAY, c], canonAt(c));
        comps.set(key, r);
      }
      return r;
    },
    segments(c, xv, by) {
      const key = `${c}|${xv}|${by}`;
      let r = segs.get(key);
      if (!r) { r = segmentAnalysis(population, c, plans.get(xv)!, by, canonAt(c)); segs.set(key, r); }
      return r;
    },
    segmentsFamily(c, xv, by) {
      const key = `${c}|${xv}|${by}|family`;
      let r = segs.get(key);
      if (!r) {
        const k = SEGMENT_FIELDS.reduce((t, f) => t + segmentAnalysis(population, c, plans.get(xv)!, f, canonAt(c)).segments_tested, 0);
        r = segmentAnalysis(population, c, plans.get(xv)!, by, canonAt(c), k);
        segs.set(key, r);
      }
      return r;
    },
  };
}

/** The dataset's own cutoff computed the way the golden fixture is (default plan and run), in the shape of expected.json. */
export function goldenShape(ds: Dataset): Record<string, unknown> {
  const computation = ds.at(ds.cutoff);
  return goldenOf({ ingest: ds.ingest, computation, metrics: computation.metrics });
}
