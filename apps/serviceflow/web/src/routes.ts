// Route table (web-brief). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string; entry: boolean; built: boolean }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "ServiceFlow", entry: false, built: true },
  { path: "overview", label: "Overview", title: "Service overview", entry: true, built: true },
  { path: "queues", label: "Queues", title: "Queues", entry: false, built: false },
  { path: "tickets", label: "Ticket timeline", title: "Queue timeline", entry: true, built: true },
  { path: "staffing", label: "Shift grid", title: "Shift grid", entry: true, built: true },
  { path: "sla", label: "SLA review", title: "SLA review", entry: true, built: true },
  { path: "simulation", label: "Simulation", title: "Simulation studio", entry: true, built: true },
  { path: "compare", label: "Compare", title: "Policy comparison", entry: false, built: false },
  { path: "surveys", label: "Surveys", title: "Surveys", entry: false, built: false },
  { path: "evidence", label: "Evidence", title: "Evidence", entry: false, built: true },
  { path: "case-study", label: "Case study", title: "Case study", entry: true, built: true },
];

const golden = (): boolean => {
  try { return new URLSearchParams(window.location.search).get("dataset") === "golden"; } catch { return false; }
};

/** Absolute URL for a route path (optionally "path?query"), honouring the injected base and the dataset choice. */
export function hrefFor(to: string): string {
  const [path = "", query = ""] = to.split("?");
  const params = new URLSearchParams(query);
  if (golden() && !params.has("dataset")) params.set("dataset", "golden");
  const qs = params.toString();
  return `${import.meta.env.BASE_URL}${path ? `${path}/` : ""}${qs ? `?${qs}` : ""}`;
}

/** Route path ("" for landing, else "tickets", ...) for a location pathname; null when unknown. */
export function routeFromPathname(pathname: string): string | null {
  const base = import.meta.env.BASE_URL;
  let rest = pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\/+/, "");
  rest = rest.replace(/index\.html$/, "").replace(/\/+$/, "");
  return ROUTES.some((r) => r.path === rest) ? rest : null;
}
