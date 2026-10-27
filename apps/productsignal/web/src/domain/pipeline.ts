// End to end: ingest -> canonical events -> metrics (D-01..D-05). Mirror of domain/productsignal/pipeline.py.
import { CONTRACT_VERSION, ENTITIES, METRIC_KEYS, type Entity } from "./contract";
import { compute, type Computation, type Metrics } from "./metrics";
import { validateBatch, type IngestResult } from "./ingest";
import { defaultWindows, parseFunnel, parsePlan, parseWindows, type FunnelDef, type Plan, type Population, type Row, type Windows } from "./models";
import { parseTs } from "./time";

export interface PipelineInputs { [k: string]: unknown }

export interface PipelineResult {
  ingest: IngestResult; population: Population; metrics: Metrics; computation: Computation; cutoff: number; windows: Windows; funnel: FunnelDef | null; plans: Map<string, Plan>;
}

/** The plans an inputs object carries: `analysis_plans` (by version) when present, else the single `analysis_plan`. */
export function plansOf(inputs: PipelineInputs): Map<string, Plan> {
  const out = new Map<string, Plan>();
  const many = inputs["analysis_plans"];
  if (many && typeof many === "object") for (const raw of Object.values(many as Row)) { const p = parsePlan(raw); out.set(p.experiment_version_id, p); }
  else if (inputs["analysis_plan"] != null) { const p = parsePlan(inputs["analysis_plan"]); out.set(p.experiment_version_id, p); }
  return out;
}

/** Validate the batch once; the population does not depend on the cutoff. */
export function ingestInputs(inputs: PipelineInputs): { ingest: IngestResult; population: Population; plans: Map<string, Plan>; funnel: FunnelDef | null; windows: Windows | null } {
  const plans = plansOf(inputs);
  const ingest = validateBatch(inputs, plans);
  const mw = inputs["metric_windows"] as Row | undefined;
  const funnel = mw && mw["funnel"] ? parseFunnel(mw["funnel"] as Row) : null;
  const windows = mw ? parseWindows(mw) : null;
  const typed = Object.fromEntries(ENTITIES.map((e: Entity) => [e, [...ingest.accepted[e]]])) as unknown as Population;
  return { ingest, population: { ...typed, plans, funnels: funnel ? [funnel] : [] }, plans, funnel, windows };
}

/** Ingest `inputs` and compute the metrics at `cutoff` (default: the inputs' own cutoff). A run at an earlier cutoff sees only events
 *  received by then (D-01). Windows are the inputs' own (parse_windows) or, when none are stored, the defaults for the cutoff. */
export function runPipeline(inputs: PipelineInputs, cutoff?: string | number | null, experimentVersionId: string | null = null, runId: string | null = null): PipelineResult {
  const when = typeof cutoff === "number" ? cutoff : parseTs(cutoff ?? inputs["cutoff"], "cutoff");
  const { ingest, population, plans, funnel, windows } = ingestInputs(inputs);
  const w = windows ?? defaultWindows(when);
  const comp = compute(population, when, w, funnel, experimentVersionId, runId);
  if (JSON.stringify(Object.keys(comp.metrics)) !== JSON.stringify(METRIC_KEYS)) throw new Error("metric keys out of order");
  return { ingest, population, metrics: comp.metrics, computation: comp, cutoff: when, windows: w, funnel, plans };
}

/** Ingest counts as the API reports them: events are the canonical log of this run (accepted = canonical, merged = duplicates dropped
 *  plus idempotent repeats; rows received after the cutoff are in neither: they are in tracking_quality). */
export function countsOf(r: Pick<PipelineResult, "ingest" | "computation">): Record<Entity, { accepted: number; rejected: number; merged: number }> {
  const c = Object.fromEntries(ENTITIES.map((e) => [e, { ...r.ingest.counts[e] }])) as Record<Entity, { accepted: number; rejected: number; merged: number }>;
  const tq = r.computation.tracking_quality;
  c.events = { accepted: tq.canonical, rejected: c.events.rejected, merged: tq.duplicates_dropped + c.events.merged };
  return c;
}

/** The shape of expected.json. */
export function goldenOf(r: Pick<PipelineResult, "ingest" | "computation" | "metrics">): Record<string, unknown> {
  return {
    contract_version: CONTRACT_VERSION, empty_population: r.computation.empty_population,
    ingest: { counts: countsOf(r), rejected_records: r.ingest.rejected.map((x) => ({ entity: x.entity, id: x.id, status: "rejected", reason_code: x.reason_code, raw_row: x.raw_row })) },
    tracking_quality: r.computation.tracking_quality, identity: r.computation.identity, metrics: r.metrics,
  };
}
