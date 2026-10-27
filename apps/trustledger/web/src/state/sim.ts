// Simulated actions: issue closes, reruns and reopens, duplicate reviews and merge reversals live in browser memory only (module state,
// gone on reload). Nothing is sent anywhere and no published figure changes.
import { useSyncExternalStore } from "react";

export interface SimIssue { n: number; issue_id: string; action: "claim" | "rerun" | "reopen"; outcome: "claimed" | "resolved" | "open" | "refused"; code: string | null; note: string }
export interface SimReview { n: number; candidate_id: string; reviewer_id: string; decision: "approve" | "reject"; status: "recorded" | "refused"; code: string | null; note: string }
export interface SimReversal { n: number; merge_id: string; status: "recorded" | "refused"; code: string | null; note: string }

let issues: readonly SimIssue[] = [];
let reviews: readonly SimReview[] = [];
let reversals: readonly SimReversal[] = [];
const listeners = new Set<() => void>();
const emit = (): void => listeners.forEach((l) => l());
const sub = (l: () => void): (() => void) => { listeners.add(l); return () => void listeners.delete(l); };

export const useSimIssues = (): readonly SimIssue[] => useSyncExternalStore(sub, () => issues);
export const useSimReviews = (): readonly SimReview[] => useSyncExternalStore(sub, () => reviews);
export const useSimReversals = (): readonly SimReversal[] => useSyncExternalStore(sub, () => reversals);
export function addSimIssue(d: Omit<SimIssue, "n">): void { issues = [...issues, { ...d, n: issues.length + 1 }]; emit(); }
export function addSimReview(d: Omit<SimReview, "n">): void { reviews = [...reviews, { ...d, n: reviews.length + 1 }]; emit(); }
export function addSimReversal(d: Omit<SimReversal, "n">): void { reversals = [...reversals, { ...d, n: reversals.length + 1 }]; emit(); }
/** The class an issue would have after the simulated actions so far (last recorded outcome wins; refused actions change nothing). */
export function simClassOf(log: readonly SimIssue[], issueId: string, real: "resolved" | "claimed" | "open"): "resolved" | "claimed" | "open" {
  let cls = real;
  for (const e of log) if (e.issue_id === issueId && e.outcome !== "refused") cls = e.outcome === "claimed" ? "claimed" : e.outcome === "resolved" ? "resolved" : "open";
  return cls;
}
