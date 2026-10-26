// Route table (web-brief). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "Onboard Studio" },
  { path: "intake", label: "Intake", title: "Case intake" },
  { path: "queue", label: "Queue", title: "Work queue" },
  { path: "cases", label: "Cases", title: "Case timeline" },
  { path: "workflow", label: "Workflow", title: "Workflow canvas" },
  { path: "documents", label: "Documents", title: "Document review" },
  { path: "sla", label: "SLA", title: "SLA explorer" },
  { path: "bottlenecks", label: "Bottlenecks", title: "Bottlenecks" },
  { path: "versions", label: "Versions", title: "Version comparison" },
  { path: "simulation", label: "Simulation", title: "Simulation" },
  { path: "case-study", label: "Case study", title: "Case study" },
];

/** Absolute URL path for a route path, honouring the injected base. */
export function hrefFor(path: string): string {
  return `${import.meta.env.BASE_URL}${path ? `${path}/` : ""}`;
}

/** Route path ("" for landing, else "cases", ...) for a location pathname; null when unknown. */
export function routeFromPathname(pathname: string): string | null {
  const base = import.meta.env.BASE_URL;
  let rest = pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\/+/, "");
  rest = rest.replace(/index\.html$/, "").replace(/\/+$/, "");
  return ROUTES.some((r) => r.path === rest) ? rest : null;
}
