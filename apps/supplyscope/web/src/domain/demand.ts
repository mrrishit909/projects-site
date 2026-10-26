// Demand, unmet demand and common random numbers (D-03, D-04, D-05, D-06).
// Requested = immediately fulfilled sales + unmet demand opened in the window; unmet is a backorder (backlog policy) or a
// lost sale (lost_sale policy), never both. A stockout day is a date on which unmet demand opened.
import { UNMET_POLICIES } from "./contract";
import { DomainError, POLICY_SEED_MISMATCH, UNKNOWN_POLICY } from "./errors";
import { ratio, type Rat } from "./money";
import { packRoundUp } from "./replenishment";
import { dayOf, parseDay } from "./time";
import type { Backorder, Latent, LostSale, Sale, Scenario } from "./types";

/** start <= t < end, and never after the information cutoff `asOf` (an absent end means "up to asOf"). */
export const inWindow = (t: number, start: number | null, end: number | null, asOf: number): boolean =>
  t <= asOf && (start === null || t >= start) && (end === null || t < end);
/** The last UTC day observed: asOf, or just before the window end, whichever is earlier. */
export const lastObservedDay = (end: number | null, asOf: number): number => dayOf(end === null ? asOf : Math.min(asOf, end - 1));
export const observedDays = (start: number, end: number | null, asOf: number): number => Math.max(lastObservedDay(end, asOf) - dayOf(start) + 1, 0);

export interface DemandSummary { requested: number; fulfilled: number; unmet: number; stockoutDates: Set<number>; observedDays: number }
export const fillRate = (s: DemandSummary): Rat | null => ratio(s.fulfilled, s.requested);
export const stockoutDayRatio = (s: DemandSummary): Rat | null => ratio(s.stockoutDates.size, s.observedDays);

export function summarise(sales: Iterable<Sale>, backorders: Iterable<Backorder>, lostSales: Iterable<LostSale>,
  start: number, end: number | null, asOf: number): DemandSummary {
  let fulfilled = 0, unmet = 0;
  const dates = new Set<number>();
  for (const s of sales) if (inWindow(s.sold_at, start, end, asOf)) fulfilled += s.quantity;
  for (const b of backorders) if (inWindow(b.opened_at, start, end, asOf)) { unmet += b.quantity; dates.add(dayOf(b.opened_at)); }
  for (const l of lostSales) if (inWindow(l.occurred_at, start, end, asOf)) { unmet += l.quantity; dates.add(dayOf(l.occurred_at)); }
  return { requested: fulfilled + unmet, fulfilled, unmet, stockoutDates: dates, observedDays: observedDays(start, end, asOf) };
}

/** Exactly one of backorder / lost sale takes the shortfall (P03-TEST-08). */
export function applyUnmetPolicy(policy: string, unmet: number): { backorder: number; lost_sale: number } {
  if (!(UNMET_POLICIES as readonly string[]).includes(policy)) throw new DomainError(UNKNOWN_POLICY, `unmet policy must be one of ${UNMET_POLICIES.join(", ")}`);
  if (unmet < 0) throw new Error("unmet quantity cannot be negative");
  return policy === "backlog" ? { backorder: unmet, lost_sale: 0 } : { backorder: 0, lost_sale: unmet };
}

export interface CensoredVsLatent {
  days: number[]; observed: number[]; latent: (number | null)[]; censoredDays: number[];
  observedTotal: number; latentTotal: number | null; hasLatent: boolean; shown: string;
}
/** Observed (censored) sales and the published latent demand, reported separately (P03-TEST-01). A day with unmet demand
 * is censored: its observed sales are a floor on demand, not demand. */
export function censoredVsLatent(sales: Iterable<Sale>, backorders: Iterable<Backorder>, lostSales: Iterable<LostSale>,
  latent: Iterable<Latent>, productId: string, locationId: string, first: number, last: number, asOf: number): CensoredVsLatent {
  const n = Math.max(last - first + 1, 0);
  const days = Array.from({ length: n }, (_, i) => first + i);
  const obs = new Array<number>(n).fill(0);
  for (const s of sales) {
    const d = dayOf(s.sold_at);
    if (s.product_id === productId && s.location_id === locationId && s.sold_at <= asOf && d >= first && d <= last) obs[d - first]! += s.quantity;
  }
  const censored = new Set<number>();
  for (const b of backorders) if (b.product_id === productId && b.location_id === locationId && b.opened_at <= asOf) censored.add(dayOf(b.opened_at));
  for (const l of lostSales) if (l.product_id === productId && l.location_id === locationId && l.occurred_at <= asOf) censored.add(dayOf(l.occurred_at));
  const lat = new Map<number, number>();
  for (const x of latent) if (x.product_id === productId && x.location_id === locationId) lat.set(parseDay(x.demand_date), x.latent_quantity);
  const latentSeries = days.map((d) => lat.get(d) ?? null);
  const hasLatent = days.some((d) => lat.has(d));
  return {
    days, observed: obs, latent: latentSeries, censoredDays: days.filter((d) => censored.has(d)), observedTotal: obs.reduce((a, b) => a + b, 0),
    latentTotal: hasLatent ? latentSeries.reduce<number>((a, b) => a + (b ?? 0), 0) : null, hasLatent,
    shown: "observed (censored during stockouts); latent demand is the generator's published truth",
  };
}

// ---- common random numbers (D-05, P03-FLOW-08) --------------------------------------------------------------------
// The browser draws from a seeded 32-bit generator (mulberry32). The seed contract is the same as the Python side
// (one seed drives demand and lead times for every policy) but the streams are not Python's random.Random streams,
// so a browser run is reproducible against itself, never numerically equal to a Python run.
function hashSeed(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
export function rng(text: string): () => number {
  let a = hashSeed(text);
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function poisson(rand: () => number, mean: number): number {
  const limit = Math.exp(-mean);
  let k = 0, p = 1;
  for (;;) { p *= rand(); if (p <= limit) return k; k += 1; }
}
export interface Sample { demand: number[]; lead_times: number[] }
/** One draw of demand and lead times from `seed`: every policy compared in one run shares this sample. */
export function commonSample(seed: number, days: number, meanDemand: number, leadLow: number, leadHigh: number): Sample {
  const d = rng(`demand:${seed}`), l = rng(`lead:${seed}`);
  return {
    demand: Array.from({ length: days }, () => poisson(d, meanDemand)),
    lead_times: Array.from({ length: days }, () => leadLow + Math.floor(l() * (leadHigh - leadLow + 1))),
  };
}
export interface PolicyResult { scenario_id: string; requested: number; fulfilled: number; fill_rate: Rat | null; stockout_days: number; scored_days: number }
/** Daily loop in D-01 order: receipts, then demand, then review. Warm-up days are not scored. */
export function simulatePolicy(sample: Sample, scenario: Scenario, reorderPoint: number, target: number, moq: number, packSize: number, initialStock: number): PolicyResult {
  let stock = initialStock, backlog = 0;
  const pipeline: [number, number][] = []; // [arrival day, quantity]
  let requested = 0, fulfilled = 0, stockout = 0, scored = 0;
  sample.demand.forEach((demand, day) => {
    for (let i = pipeline.length - 1; i >= 0; i--) if (pipeline[i]![0] === day) { stock += pipeline[i]![1]; pipeline.splice(i, 1); }
    if (backlog && stock) { const served = Math.min(stock, backlog); stock -= served; backlog -= served; } // arrivals serve the backlog first
    const sold = Math.min(stock, demand);
    stock -= sold;
    const short = demand - sold;
    if (scenario.unmet_policy === "backlog") backlog += short;
    if (day >= scenario.warmup_days) { scored += 1; requested += demand; fulfilled += sold; stockout += short ? 1 : 0; }
    const position = stock + pipeline.reduce((a, p) => a + p[1], 0) - backlog;
    if (position < reorderPoint) pipeline.push([day + sample.lead_times[day]!, packRoundUp(Math.max(target - position, moq), packSize)]);
  });
  return { scenario_id: scenario.scenario_id, requested, fulfilled, fill_rate: ratio(fulfilled, requested), stockout_days: stockout, scored_days: scored };
}
/** Every scenario is run on the SAME sample (same seed); scenarios with different seeds are refused. */
export function comparePolicies(scenarios: readonly Scenario[], days: number, meanDemand: number, leadLow: number, leadHigh: number,
  reorderPoint: number, target: number, moq: number, packSize: number, initialStock: number): { seed: number; replications: number; results: Record<string, PolicyResult[]> } {
  const seeds = [...new Set(scenarios.map((s) => s.seed))].sort((a, b) => a - b);
  if (seeds.length !== 1) throw new DomainError(POLICY_SEED_MISMATCH, "policies are compared on common random numbers: every scenario must declare the same seed", null, { seeds });
  const seed = seeds[0]!;
  const reps = Math.max(...scenarios.map((s) => s.replications));
  const results: Record<string, PolicyResult[]> = Object.fromEntries(scenarios.map((s) => [s.scenario_id, [] as PolicyResult[]]));
  for (let rep = 0; rep < reps; rep++) {
    const sample = commonSample(seed + rep, days, meanDemand, leadLow, leadHigh);
    for (const s of scenarios) results[s.scenario_id]!.push(simulatePolicy(sample, s, reorderPoint, target, moq, packSize, initialStock));
  }
  return { seed, replications: reps, results };
}
