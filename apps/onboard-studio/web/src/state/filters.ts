// URL-synced view state. Filters and view settings live in the query string so a view can be shared, reloaded
// and restored with the back button. Nothing here touches the dataset: these are view settings only.
import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { Window } from "../domain/types";

export interface Filters { from: string; to: string; segment: string; region: string; wf: string }
export const NO_FILTERS: Filters = { from: "", to: "", segment: "", region: "", wf: "" };
export type PauseMode = "configured" | "none";

const FILTER_KEYS = ["from", "to", "segment", "region", "wf"] as const;
const EVENT = "onboard-studio:query";
const subscribe = (l: () => void): (() => void) => {
  window.addEventListener("popstate", l);
  window.addEventListener(EVENT, l);
  return () => { window.removeEventListener("popstate", l); window.removeEventListener(EVENT, l); };
};
const snapshot = (): string => window.location.search;

/** Replace query parameters in place (no new history entry); null or "" removes a key; other keys are kept. */
export function setParams(patch: Readonly<Record<string, string | null>>): void {
  const p = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(patch)) { if (v === null || v === "") p.delete(k); else p.set(k, v); }
  const qs = p.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`);
  window.dispatchEvent(new Event(EVENT));
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
/** A YYYY-MM-DD value as UTC midnight; null for empty or malformed input. */
export function dayToMs(s: string): number | null {
  if (!DAY.test(s)) return null;
  const ms = Date.parse(`${s}T00:00:00Z`);
  return Number.isFinite(ms) ? ms : null;
}

export const describeFilters = (f: Filters): string => {
  const parts = [
    f.from ? `opened_at >= ${f.from}T00:00:00Z` : "", f.to ? `opened_at < ${f.to}T00:00:00Z` : "",
    f.segment ? `segment = ${f.segment}` : "", f.region ? `region = ${f.region}` : "", f.wf ? `workflow_version = ${f.wf}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join("; ") : "none";
};

export interface ViewState {
  filters: Filters;
  /** The opened_at window [from, to) in UTC ms, or null when the two bounds are out of order. */
  window: Window | null;
  pause: PauseMode;
  caseId: string;
  /** Selected workflow version number on the canvas ("" = first). */
  version: string;
  active: boolean;
  set: (patch: Readonly<Record<string, string | null>>) => void;
  clear: () => void;
}

export function useViewState(): ViewState {
  const search = useSyncExternalStore(subscribe, snapshot, () => "");
  const value = useMemo(() => {
    const p = new URLSearchParams(search);
    const filters = { ...NO_FILTERS };
    for (const k of FILTER_KEYS) filters[k] = p.get(k) ?? "";
    const lo = dayToMs(filters.from), hi = dayToMs(filters.to);
    const window: Window | null = lo !== null && hi !== null && lo >= hi ? null : [lo, hi];
    const pause: PauseMode = p.get("pause") === "none" ? "none" : "configured";
    return { filters, window, pause, caseId: p.get("case") ?? "", version: p.get("v") ?? "", active: FILTER_KEYS.some((k) => filters[k] !== "") };
  }, [search]);
  const clear = useCallback(() => setParams(Object.fromEntries(FILTER_KEYS.map((k) => [k, null]))), []);
  return { ...value, set: setParams, clear };
}
