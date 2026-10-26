import { useSyncExternalStore } from "react";
import { routeFromPathname } from "./routes";

/** Fired after any change to the address (navigation or a query-only update) so subscribers re-read it. */
export const LOCATION_EVENT = "supplyscope:location";
const listeners = new Set<() => void>();
const notify = (): void => { listeners.forEach((l) => l()); window.dispatchEvent(new Event(LOCATION_EVENT)); };
if (typeof window !== "undefined") window.addEventListener("popstate", () => listeners.forEach((l) => l()));

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => void listeners.delete(l);
}
const snapshot = (): string => window.location.pathname;

/** Current route path: "" landing, a known route, or null for the not-found view. */
export function useRoute(): string | null {
  return routeFromPathname(useSyncExternalStore(subscribe, snapshot));
}

export function navigate(href: string): void {
  if (href !== `${window.location.pathname}${window.location.search}`) window.history.pushState(null, "", href);
  notify();
  window.scrollTo(0, 0);
}
