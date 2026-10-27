// Route table (docs/web-brief.md). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string; entry: boolean }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "ProductSignal", entry: false },
  { path: "overview", label: "Journey overview", title: "Journey overview", entry: true },
  { path: "funnel", label: "Funnel", title: "Funnel explorer", entry: true },
  { path: "cohorts", label: "Cohorts", title: "Cohort laboratory", entry: true },
  { path: "tracking", label: "Tracking quality", title: "Tracking quality", entry: false },
  { path: "experiments", label: "Experiments", title: "Experiment registry", entry: false },
  { path: "result", label: "Result", title: "Experiment result", entry: true },
  { path: "population", label: "Population", title: "Assigned and exposed", entry: false },
  { path: "segments", label: "Segments", title: "Segment analysis", entry: false },
  { path: "decision", label: "Decision", title: "Decision memo", entry: true },
  { path: "evidence", label: "Evidence", title: "Evidence", entry: false },
  { path: "case-study", label: "Case study", title: "Case study", entry: true },
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

/** Route path ("" for landing, else "overview", ...) for a location pathname; null when unknown. */
export function routeFromPathname(pathname: string): string | null {
  const base = import.meta.env.BASE_URL;
  let rest = pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\/+/, "");
  rest = rest.replace(/index\.html$/, "").replace(/\/+$/, "");
  return ROUTES.some((r) => r.path === rest) ? rest : null;
}
