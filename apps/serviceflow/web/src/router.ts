import { useCallback, useSyncExternalStore } from "react";
import { routeFromPathname } from "./routes";

const listeners = new Set<() => void>();
const notify = (): void => listeners.forEach((l) => l());
if (typeof window !== "undefined") window.addEventListener("popstate", notify);
function subscribe(l: () => void): () => void { listeners.add(l); return () => void listeners.delete(l); }

/** Current route path: "" landing, a known route, or null for the not-found view. */
export function useRoute(): string | null {
  return routeFromPathname(useSyncExternalStore(subscribe, () => window.location.pathname));
}
/** The query string as the address has it. */
export const useSearch = (): string => useSyncExternalStore(subscribe, () => window.location.search);

export function navigate(href: string): void {
  if (href !== `${window.location.pathname}${window.location.search}`) window.history.pushState(null, "", href);
  notify();
  window.scrollTo(0, 0);
}

/** A view setting kept in the address (`?name=value`, default omitted); changing it replaces the history entry. */
export function useParam(name: string, dflt: string): [string, (v: string) => void] {
  const search = useSearch();
  const value = new URLSearchParams(search).get(name) ?? dflt;
  const set = useCallback((v: string): void => {
    const p = new URLSearchParams(window.location.search);
    if (v === dflt) p.delete(name); else p.set(name, v);
    const qs = p.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
    notify();
  }, [name, dflt]);
  return [value, set];
}
