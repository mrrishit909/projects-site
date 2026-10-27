// Simulations live in browser memory only (module state, gone on reload): the capacity planner's scenario and the outreach queue's review marks.
// Nothing is sent anywhere, nothing is written to browser storage, and no published figure changes.
import { useSyncExternalStore } from "react";

export interface Scenario { k: string; contact_cost: string; assumed_effect: string; margin_value: string }
export interface QueueMark { account_id: number | string; scenario_id: string; mark: "reviewed" | "held" | "dropped"; n: number }

let scenario: Scenario | null = null;
let marks: readonly QueueMark[] = [];
let basisTried: { basis: string; code: string | null; n: number }[] = [];
const listeners = new Set<() => void>();
const emit = (): void => listeners.forEach((l) => l());
const sub = (l: () => void): (() => void) => { listeners.add(l); return () => void listeners.delete(l); };

/** The simulated scenario, or null while the planner still shows the published defaults. */
export const useSimScenario = (): Scenario | null => useSyncExternalStore(sub, () => scenario);
export function setSimScenario(s: Scenario | null): void { scenario = s; emit(); }
export const useQueueMarks = (): readonly QueueMark[] => useSyncExternalStore(sub, () => marks);
export function markQueue(account_id: QueueMark["account_id"], scenario_id: string, mark: QueueMark["mark"]): void {
  marks = [...marks.filter((m) => !(m.account_id === account_id && m.scenario_id === scenario_id)), { account_id, scenario_id, mark, n: marks.length + 1 }];
  emit();
}
export const useBasisTries = (): typeof basisTried => useSyncExternalStore(sub, () => basisTried);
export function tryBasis(basis: string, code: string | null): void { basisTried = [...basisTried, { basis, code, n: basisTried.length + 1 }]; emit(); }
/** Every simulation back to the published state. */
export function resetSimulations(): void { scenario = null; marks = []; basisTried = []; emit(); }
