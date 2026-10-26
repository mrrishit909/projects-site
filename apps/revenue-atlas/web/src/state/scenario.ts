// React-free scenario store. The published baseline is frozen and never written. A scenario is
// {id, discountDelta, shippingDelta}: signed decimal-string FRACTIONS ("-0.10" = 10 % less) applied
// to a COPY of the facts at compute time (contracts D-06). Everything lives in memory; reset()
// restores the published snapshot. Credits are not rescaled by a discount delta (assumption).
import * as D from "../domain/decimal";
import { NO_WINDOW, type Window, computeMetrics } from "../domain/metrics";
import type { PipelineResult } from "../domain/pipeline";
import type { Metrics, ShipmentLineFact } from "../domain/types";

export interface Scenario { id: string; discountDelta: string; shippingDelta: string }

export interface Baseline {
  readonly facts: readonly ShipmentLineFact[];
  readonly unallocatedFreight: D.Dec;
  readonly metrics: Metrics;
}
export interface ScenarioState { readonly baseline: Baseline; readonly scenarios: readonly Scenario[] }

/** Deep-freeze enough of a pipeline result to make accidental mutation throw in strict mode. */
export function freezeBaseline(r: PipelineResult): Baseline {
  for (const f of r.facts) Object.freeze(f);
  return Object.freeze({ facts: Object.freeze([...r.facts]), unallocatedFreight: r.unallocatedFreight, metrics: Object.freeze({ ...r.metrics }) });
}

const factor = (delta: string): D.Dec => D.add(D.ONE, D.parse(delta));

/** Copy of the facts with discount and freight scaled by (1 + delta). The input is untouched. */
export function applyScenario(facts: readonly ShipmentLineFact[], s: Scenario): ShipmentLineFact[] {
  const dk = factor(s.discountDelta);
  const sk = factor(s.shippingDelta);
  return facts.map((f) => ({ ...f, allocated_discount: D.mul(f.allocated_discount, dk), freight: D.mul(f.freight, sk) }));
}

/** Metrics of the baseline with the scenario applied to a copy. */
export function scenarioMetrics(baseline: Baseline, s: Scenario, window: Window = NO_WINDOW): Metrics {
  return computeMetrics(applyScenario(baseline.facts, s), window, { unallocatedFreight: D.mul(baseline.unallocatedFreight, factor(s.shippingDelta)) });
}

export interface ScenarioStore {
  getState(): ScenarioState;
  subscribe(listener: () => void): () => void;
  /** Add or replace (by id) a scenario. Deltas are validated as decimal strings. */
  upsert(s: Scenario): void;
  remove(id: string): void;
  /** Drop every scenario: the published snapshot is what remains. */
  reset(): void;
}

export function createScenarioStore(baseline: Baseline): ScenarioStore {
  let state: ScenarioState = { baseline, scenarios: [] };
  const listeners = new Set<() => void>();
  const set = (next: ScenarioState): void => {
    state = next;
    listeners.forEach((l) => l());
  };
  return {
    getState: () => state,
    subscribe(l) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
    upsert(s) {
      factor(s.discountDelta);
      factor(s.shippingDelta);
      const copy = Object.freeze({ ...s });
      const i = state.scenarios.findIndex((x) => x.id === s.id);
      const scenarios = i < 0 ? [...state.scenarios, copy] : state.scenarios.map((x, j) => (j === i ? copy : x));
      set({ baseline: state.baseline, scenarios });
    },
    remove(id) {
      set({ baseline: state.baseline, scenarios: state.scenarios.filter((x) => x.id !== id) });
    },
    reset() {
      set({ baseline: state.baseline, scenarios: [] });
    },
  };
}
