// URL-synced view state. Filters and view settings live in the query string so a view can be shared, reloaded and restored
// with the back button. Nothing here touches the dataset: these are view settings only.
import { useCallback, useMemo, useSyncExternalStore } from "react";
import { LOCATION_EVENT } from "../router";

export interface Filters { loc: string; sup: string; trig: string; q: string }
export const NO_FILTERS: Filters = { loc: "", sup: "", trig: "", q: "" };
const FILTER_KEYS = ["loc", "sup", "trig", "q"] as const;

const subscribe = (l: () => void): (() => void) => {
  window.addEventListener("popstate", l);
  window.addEventListener(LOCATION_EVENT, l);
  return () => { window.removeEventListener("popstate", l); window.removeEventListener(LOCATION_EVENT, l); };
};
const snapshot = (): string => window.location.search;

/** Replace query parameters in place (no new history entry); null or "" removes a key; other keys are kept. */
export function setParams(patch: Readonly<Record<string, string | null>>): void {
  const p = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(patch)) { if (v === null || v === "") p.delete(k); else p.set(k, v); }
  const qs = p.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`);
  window.dispatchEvent(new Event(LOCATION_EVENT));
}

export function describeFilters(f: Filters): string {
  const parts = [
    f.loc ? `location = ${f.loc}` : "", f.sup ? `supplier = ${f.sup}` : "",
    f.trig === "yes" ? "triggered = yes" : f.trig === "no" ? "triggered = no" : "", f.q ? `search = ${f.q}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join("; ") : "none";
}

export interface ViewState {
  filters: Filters;
  /** ?as_of=YYYY-MM-DD, "" when absent. */
  asOf: string;
  /** ?state=<fixture state name>, "" when absent. */
  state: string;
  sku: string;
  cutoff: string;
  active: boolean;
  set: (patch: Readonly<Record<string, string | null>>) => void;
  /** Remove the reorder filters (the as-of date and the selected SKU are kept). */
  clear: () => void;
}

export function useViewState(): ViewState {
  const search = useSyncExternalStore(subscribe, snapshot, () => "");
  const value = useMemo(() => {
    const p = new URLSearchParams(search);
    const filters = { ...NO_FILTERS };
    for (const k of FILTER_KEYS) filters[k] = p.get(k) ?? "";
    return { filters, asOf: p.get("as_of") ?? "", state: p.get("state") ?? "", sku: p.get("sku") ?? "", cutoff: p.get("cutoff") ?? "", active: FILTER_KEYS.some((k) => filters[k] !== "") };
  }, [search]);
  const clear = useCallback(() => setParams(Object.fromEntries(FILTER_KEYS.map((k) => [k, null]))), []);
  return { ...value, set: setParams, clear };
}
