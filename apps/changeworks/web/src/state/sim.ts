// Simulated actions: scenario proposals, the sensitivity settings and the roadmap edits live in browser memory only (module state, gone on reload).
// Nothing is sent anywhere and no published figure changes.
import { useSyncExternalStore } from "react";
import type { Row } from "../domain/contract";

export interface SimProposal { n: number; scenario_id: string; outcome: "proposed" | "refused"; code: string | null; note: string; residual: string }
export interface SensitivitySettings { initiative: string; scenario: string; rate: string; basis: "annual" | "monthly"; ramp: "planned" | "immediate" | "late2" | "slow75"; costPct: number; raw: boolean }
export interface RoadmapEdits { shifts: Record<string, number>; deps: Row[]; allocations: Row[]; log: { n: number; text: string; refused: boolean }[] }

let proposals: readonly SimProposal[] = [];
let sens: SensitivitySettings | null = null;
let edits: RoadmapEdits = { shifts: {}, deps: [], allocations: [], log: [] };
const listeners = new Set<() => void>();
const emit = (): void => listeners.forEach((l) => l());
const sub = (l: () => void): (() => void) => { listeners.add(l); return () => void listeners.delete(l); };

export const useProposals = (): readonly SimProposal[] => useSyncExternalStore(sub, () => proposals);
export function addProposal(p: Omit<SimProposal, "n">): void { proposals = [...proposals, { ...p, n: proposals.length + 1 }]; emit(); }
export const proposedIds = (): string[] => proposals.filter((p) => p.outcome === "proposed").map((p) => p.scenario_id);

export const useSensitivity = (): SensitivitySettings | null => useSyncExternalStore(sub, () => sens);
export function setSensitivity(s: SensitivitySettings | null): void { sens = s; emit(); }

export const useRoadmapEdits = (): RoadmapEdits => useSyncExternalStore(sub, () => edits);
export function updateRoadmap(f: (e: RoadmapEdits) => RoadmapEdits): void { edits = f(edits); emit(); }
export function logRoadmap(e: RoadmapEdits, text: string, refused: boolean): RoadmapEdits { return { ...e, log: [...e.log, { n: e.log.length + 1, text, refused }] }; }
export function resetRoadmap(): void { edits = { shifts: {}, deps: [], allocations: [], log: [] }; emit(); }
export function resetAll(): void { proposals = []; sens = null; edits = { shifts: {}, deps: [], allocations: [], log: [] }; emit(); }
