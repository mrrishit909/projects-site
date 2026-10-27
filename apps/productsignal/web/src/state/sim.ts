// Simulated actions: decisions and plan drafts live in browser memory only (module state, gone on reload). Nothing is sent anywhere.
import { useSyncExternalStore } from "react";

export interface SimDecision { n: number; run: string; xv: string; option: "ship" | "stop" | "inconclusive"; status: "recorded" | "refused"; reasons: string[]; warnings: string[]; note: string; at: string }
export interface SimDraft { n: number; experiment_version_id: string; control_share: string; config_hash: string; body: string }

let decisions: readonly SimDecision[] = [];
let drafts: readonly SimDraft[] = [];
const listeners = new Set<() => void>();
const emit = (): void => listeners.forEach((l) => l());
const sub = (l: () => void): (() => void) => { listeners.add(l); return () => void listeners.delete(l); };

export const useDecisions = (): readonly SimDecision[] => useSyncExternalStore(sub, () => decisions);
export const useDrafts = (): readonly SimDraft[] => useSyncExternalStore(sub, () => drafts);
export function addDecision(d: Omit<SimDecision, "n" | "at">): SimDecision {
  const row = { ...d, n: decisions.length + 1, at: new Date().toISOString().slice(0, 19) + "Z" };
  decisions = [...decisions, row];
  emit();
  return row;
}
export function addDraft(d: Omit<SimDraft, "n">): void { drafts = [...drafts, { ...d, n: drafts.length + 1 }]; emit(); }
