// URL-synced filter state (?from=&to=&region=&segment=&category=) and the filtered population every
// analytic screen reads. The query string is the single source of truth, so deep links work and a reload
// restores the same view. Other params (dataset, hl) are preserved untouched.
import { useCallback, useMemo, useSyncExternalStore } from "react";
import { NO_WINDOW, computeMetrics, regionKey, utcMidnight, windowLedger, type OutsideCredit, type Window } from "../domain/metrics";
import type { PipelineResult } from "../domain/pipeline";
import type { Metrics, ShipmentLineFact } from "../domain/types";
import type { Snapshot } from "../data/load";
import { UNASSIGNED_REGION } from "../domain/contract";
import { useAtlas } from "./atlas";

export interface Filters { from: string; to: string; region: string; segment: string; category: string }
export const EMPTY_FILTERS: Filters = { from: "", to: "", region: "", segment: "", category: "" };
const KEYS = ["from", "to", "region", "segment", "category"] as const;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const validDate = (s: string): boolean => DATE_RE.test(s) && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;

export function parseFilters(search: string): Filters {
  const p = new URLSearchParams(search);
  const f = { ...EMPTY_FILTERS };
  for (const k of KEYS) f[k] = p.get(k) ?? "";
  return f;
}
export const hasFilters = (f: Filters): boolean => KEYS.some((k) => f[k] !== "");

/** Query string ("?a=b" or "") for a filter set plus extra params (dataset, hl). */
export function queryFor(f: Partial<Filters>, extra: Record<string, string> = {}): string {
  const p = new URLSearchParams();
  for (const k of KEYS) if (f[k]) p.set(k, f[k]!);
  for (const [k, v] of Object.entries(extra)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
}
/** Params that must survive navigation between screens. */
export function carriedParams(search: string): Record<string, string> {
  const p = new URLSearchParams(search);
  const out: Record<string, string> = {};
  if (p.get("dataset")) out.dataset = p.get("dataset")!;
  return out;
}

// ---- location.search as an external store --------------------------------------------------------
const EVENT = "ra:query";
const subscribe = (cb: () => void): (() => void) => {
  window.addEventListener("popstate", cb);
  window.addEventListener(EVENT, cb);
  return () => { window.removeEventListener("popstate", cb); window.removeEventListener(EVENT, cb); };
};
const getSearch = (): string => window.location.search;

export function useSearch(): string {
  return useSyncExternalStore(subscribe, getSearch, () => "");
}
/** Merge params into the current query (null/"" removes) without adding a history entry. */
export function patchQuery(patch: Record<string, string | null>): void {
  const p = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(patch)) { if (v) p.set(k, v); else p.delete(k); }
  const s = p.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${s ? `?${s}` : ""}${window.location.hash}`);
  window.dispatchEvent(new Event(EVENT));
}

export function useFilters(): { filters: Filters; set: (patch: Partial<Filters>) => void; clear: () => void } {
  const search = useSearch();
  const filters = useMemo(() => parseFilters(search), [search]);
  const set = useCallback((patch: Partial<Filters>) => patchQuery({ ...patch }), []);
  const clear = useCallback(() => patchQuery({ from: null, to: null, region: null, segment: null, category: null }), []);
  return { filters, set, clear };
}

// ---- the filtered population -----------------------------------------------------------------------
interface Lookups {
  segmentOf: (customerId: string, shippedDate: string) => string;
  categoryOf: (productId: string) => string;
  customerName: (customerId: string) => string;
  sku: (productId: string) => string;
}
export function buildLookups(snapshot: Snapshot): Lookups {
  const versions = new Map<string, { effective_from: string; segment: string; customer_name: string }[]>();
  for (const c of snapshot.inputs.customers ?? []) {
    const g = versions.get(c.customer_id);
    if (g) g.push(c); else versions.set(c.customer_id, [c]);
  }
  const products = new Map((snapshot.inputs.products ?? []).map((p) => [p.product_id, p]));
  return {
    segmentOf: (id, day) => {
      let best: { effective_from: string; segment: string } | null = null;
      for (const c of versions.get(id) ?? []) if (c.effective_from <= day && (best === null || c.effective_from > best.effective_from)) best = c;
      return best?.segment ?? "";
    },
    categoryOf: (id) => products.get(id)?.category_id ?? "",
    customerName: (id) => {
      const g = versions.get(id) ?? [];
      return g.reduce((a, c) => (a === null || c.effective_from > a.effective_from ? c : a), null as (typeof g)[number] | null)?.customer_name ?? id;
    },
    sku: (id) => products.get(id)?.sku ?? id,
  };
}

export interface FilterOptions { regions: string[]; segments: string[]; categories: string[] }

export type Population =
  | { status: "loading" }
  | { status: "error"; error: string; retry: () => void }
  | {
      status: "ready";
      snapshot: Snapshot;
      result: PipelineResult;
      lookups: Lookups;
      filters: Filters;
      /** Message when the date window is unusable (bad date or from >= to); the population is then empty. */
      windowError: string | null;
      /** Shipment lines shipped in the window; their credit columns hold only credits dated in the window (D-01a, D-09). */
      facts: ShipmentLineFact[];
      /** Facts that pass the region/segment/category filters but not the window: what credits and monthly series read. */
      dimFacts: ShipmentLineFact[];
      /** Credits dated in the window for lines shipped outside it (D-09); empty without a window. */
      outside: OutsideCredit[];
      window: Window;
      metrics: Metrics;
      options: FilterOptions;
      active: boolean;
    };

export function windowOf(f: Filters): { window: Window; error: string | null } {
  if (f.from && !validDate(f.from)) return { window: NO_WINDOW, error: `"from" is not a valid date (YYYY-MM-DD): ${f.from}` };
  if (f.to && !validDate(f.to)) return { window: NO_WINDOW, error: `"to" is not a valid date (YYYY-MM-DD): ${f.to}` };
  if (f.from && f.to && f.from >= f.to) return { window: NO_WINDOW, error: "The window start must be before its end: [from, to) is empty." };
  return { window: { from: f.from ? utcMidnight(f.from) : null, to: f.to ? utcMidnight(f.to) : null }, error: null };
}

export function usePopulation(): Population {
  const { state, reload } = useAtlas();
  const search = useSearch();
  const filters = useMemo(() => parseFilters(search), [search]);
  const ready = state.status === "ready" ? state : null;
  const lookups = useMemo(() => (ready ? buildLookups(ready.snapshot) : null), [ready]);
  const options = useMemo<FilterOptions | null>(() => {
    if (!ready || !lookups) return null;
    const regions = new Set<string>([UNASSIGNED_REGION]);
    const segments = new Set<string>();
    const categories = new Set<string>();
    for (const f of ready.result.facts) {
      regions.add(regionKey(f));
      const s = lookups.segmentOf(f.customer_id, f.shipped_date);
      if (s) segments.add(s);
      const c = lookups.categoryOf(f.product_id);
      if (c) categories.add(c);
    }
    const sorted = (x: Set<string>): string[] => [...x].sort();
    return { regions: sorted(regions), segments: sorted(segments), categories: sorted(categories) };
  }, [ready, lookups]);
  const pop = useMemo(() => {
    if (!ready || !lookups) return null;
    const { window, error } = windowOf(filters);
    const dimFacts = error ? [] : ready.result.facts.filter((f) =>
      (!filters.region || regionKey(f) === filters.region) &&
      (!filters.segment || lookups.segmentOf(f.customer_id, f.shipped_date) === filters.segment) &&
      (!filters.category || lookups.categoryOf(f.product_id) === filters.category));
    // D-01a / D-09: lines are selected by shipped_at, credits by credit_date (R-04). Without a window the two coincide.
    const { lines: facts, outside } = windowLedger(dimFacts, ready.result.returns, window);
    // Freight that no line could carry counts in contribution (D-04); it cannot be attributed to a
    // region/segment/category or a partial window, so it is added only for the unfiltered population.
    const active = hasFilters(filters);
    const metrics = computeMetrics(dimFacts, window, { returns: ready.result.returns, ...(active ? {} : { unallocatedFreight: ready.result.unallocatedFreight }) });
    return { facts, dimFacts, outside, window, metrics, windowError: error, active };
  }, [ready, lookups, filters]);
  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") return { status: "error", error: state.error, retry: reload };
  return { status: "ready", snapshot: state.snapshot, result: state.result, lookups: lookups!, filters, options: options!, ...pop! };
}
