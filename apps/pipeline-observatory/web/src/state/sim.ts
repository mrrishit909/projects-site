// Browser-memory simulations: quarantine dispositions, backfill requests and fault injections live in module state, gone on reload. Nothing is sent
// anywhere and no published figure changes.
import { useSyncExternalStore } from "react";

export interface SimQuarantine { n: number; quarantine_id: string; action: "retry" | "park" | "discard"; outcome: string; reason: string | null; note: string }
export interface SimBackfill { n: number; backfill_id: string; source_id: string; start_at: string; end_at: string; accepted: boolean; code: string | null; message: string; partitions: string[]; verified: number }
export interface SimFault { n: number; run_id: string; forced: Record<string, number>; decision: string; pointer_after: string | null; note: string }

let quarantine: readonly SimQuarantine[] = [];
let backfills: readonly SimBackfill[] = [];
let faults: readonly SimFault[] = [];
const listeners = new Set<() => void>();
const emit = (): void => listeners.forEach((l) => l());
const sub = (l: () => void): (() => void) => { listeners.add(l); return () => void listeners.delete(l); };

export const useSimQuarantine = (): readonly SimQuarantine[] => useSyncExternalStore(sub, () => quarantine);
export const useSimBackfills = (): readonly SimBackfill[] => useSyncExternalStore(sub, () => backfills);
export const useSimFaults = (): readonly SimFault[] => useSyncExternalStore(sub, () => faults);
export function addSimQuarantine(d: Omit<SimQuarantine, "n">): void { quarantine = [...quarantine, { ...d, n: quarantine.length + 1 }]; emit(); }
export function addSimBackfill(d: Omit<SimBackfill, "n" | "verified">): void { backfills = [...backfills, { ...d, n: backfills.length + 1, verified: 0 }]; emit(); }
export function verifySimPartition(n: number): void { backfills = backfills.map((b) => (b.n === n && b.accepted && b.verified < b.partitions.length ? { ...b, verified: b.verified + 1 } : b)); emit(); }
export function addSimFault(d: Omit<SimFault, "n">): void { faults = [...faults, { ...d, n: faults.length + 1 }]; emit(); }
export function resetSim(which: "quarantine" | "backfill" | "fault"): void {
  if (which === "quarantine") quarantine = []; else if (which === "backfill") backfills = []; else faults = [];
  emit();
}
