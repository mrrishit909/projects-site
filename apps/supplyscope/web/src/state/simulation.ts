// Browser-memory (s,S) simulation (P03-FLOW-08). It works on values copied out of the published population (scenarios, the
// product's MOQ and pack size, the supplier's quoted lead days, recent demand), draws from the published seed, and never
// writes back: reloading, or reset(), restores the published state. Nothing is persisted or sent anywhere.
import { commonSample, simulatePolicy, type PolicyResult } from "../domain/demand";
import { d6, ratio } from "../domain/money";
import { dayOf, parseTs } from "../domain/time";
import type { Population } from "../domain/types";

export interface SimSummary { scenario_id: string; name: string; unmet_policy: string; requested: number; fulfilled: number; fill_rate: string | null; mean_stockout_days: string; replications: number }
export interface SimRun {
  product_id: string; location_id: string; reorderPoint: number; target: number; days: number; seed: number; meanDemand: number;
  leadLow: number; leadHigh: number; results: SimSummary[];
}
export interface SimState { revision: number; log: string[]; last: SimRun | null }
export interface SimulationStore {
  subscribe: (l: () => void) => () => void;
  getState: () => SimState;
  run: (product: string, location: string, policy: { reorderPoint: number; target: number; days: number }) => SimRun;
  reset: () => void;
}
const EMPTY: SimState = { revision: 0, log: [], last: null };

/** `asOfIso` bounds the demand history the mean is taken from (the last 90 days). */
export function createSimulation(population: Population, asOfIso: string): SimulationStore {
  // a copy: the store never holds a reference it could mutate
  const scenarios = population.policy_scenarios.map((s) => ({ ...s }));
  const products = new Map(population.products.map((p) => [p.product_id, { ...p }]));
  const suppliers = new Map(population.suppliers.map((s) => [s.supplier_id, { ...s }]));
  const supplierOfProduct = new Map(population.replenishment_params.map((p) => [p.product_id, p.supplier_id] as const));
  const sales = population.sales.map((s) => ({ product_id: s.product_id, location_id: s.location_id, day: dayOf(s.sold_at), quantity: s.quantity }));
  const lastDay = dayOf(parseTs(asOfIso));
  let state: SimState = EMPTY;
  const listeners = new Set<() => void>();
  const set = (next: SimState): void => { state = next; listeners.forEach((l) => l()); };
  return {
    subscribe: (l) => { listeners.add(l); return () => void listeners.delete(l); },
    getState: () => state,
    run(product, location, policy) {
      const prod = products.get(product);
      if (!prod) throw new Error(`unknown product ${product}`);
      const quoted = suppliers.get(supplierOfProduct.get(product) ?? "")?.quoted_lead_days ?? 7;
      const leadLow = quoted, leadHigh = Math.ceil(quoted * 1.3);
      let units = 0;
      for (const s of sales) if (s.product_id === product && s.location_id === location && s.day > lastDay - 90 && s.day <= lastDay) units += s.quantity;
      const meanDemand = units / 90; // a float is fine here: it only parameterises a random draw
      const seed = scenarios[0]?.seed ?? 0;
      const reps = Math.max(1, ...scenarios.map((s) => s.replications));
      const per = new Map<string, PolicyResult[]>(scenarios.map((s) => [s.scenario_id, []]));
      for (let rep = 0; rep < reps; rep++) {
        const sample = commonSample(seed + rep, policy.days, meanDemand, leadLow, leadHigh); // one sample for every scenario
        for (const sc of scenarios) per.get(sc.scenario_id)!.push(simulatePolicy(sample, sc, policy.reorderPoint, policy.target, prod.minimum_order_quantity, prod.pack_size, policy.target));
      }
      const results = scenarios.map((sc): SimSummary => {
        const rs = per.get(sc.scenario_id)!;
        const requested = rs.reduce((a, r) => a + r.requested, 0), fulfilled = rs.reduce((a, r) => a + r.fulfilled, 0);
        return {
          scenario_id: sc.scenario_id, name: sc.scenario_name, unmet_policy: sc.unmet_policy, requested, fulfilled, fill_rate: d6(ratio(fulfilled, requested)),
          mean_stockout_days: (rs.reduce((a, r) => a + r.stockout_days, 0) / rs.length).toFixed(2), replications: rs.length,
        };
      });
      const run: SimRun = { product_id: product, location_id: location, reorderPoint: policy.reorderPoint, target: policy.target, days: policy.days, seed, meanDemand, leadLow, leadHigh, results };
      set({ revision: state.revision + 1, log: [...state.log, `run ${product}/${location} s=${policy.reorderPoint} S=${policy.target} ${policy.days} days, seed ${seed}`], last: run });
      return run;
    },
    reset() { set({ revision: state.revision + 1, log: [], last: null }); },
  };
}
