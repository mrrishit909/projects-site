// Route table (docs/web-brief.md). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string; plate: string; entry: boolean; blurb: string }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "ChangeWorks", plate: "Frontispiece", entry: false, blurb: "The decision, the snapshot and where to look." },
  { path: "portfolio", label: "Portfolio", title: "Portfolio overview", plate: "Plate I", entry: true, blurb: "Costs and benefits by class, confidence labels, the double-count residual." },
  { path: "baseline", label: "Baseline", title: "Baseline evidence", plate: "Plate II", entry: false, blurb: "Volumes, effort and errors; approved versions." },
  { path: "business-case", label: "Business case", title: "Business case", plate: "Plate III", entry: true, blurb: "The cash-flow model beside its assumption versions; NPV and both paybacks." },
  { path: "sensitivity", label: "Sensitivity", title: "Sensitivity lab", plate: "Plate IV", entry: false, blurb: "Rates, adoption ramp and cost scenarios, simulated in browser memory." },
  { path: "roadmap", label: "Roadmap", title: "Roadmap", plate: "Plate V", entry: true, blurb: "Initiatives on periods, dependencies, feasible starts, resource lanes." },
  { path: "impact", label: "Impact", title: "Change impact", plate: "Plate VI", entry: false, blurb: "Stakeholder groups and the operating changes they face." },
  { path: "readiness", label: "Readiness", title: "Readiness review", plate: "Plate VII", entry: false, blurb: "Five dimensions with labels: an assessment, not a probability." },
  { path: "benefits", label: "Benefits", title: "Benefits register", plate: "Plate VIII", entry: false, blurb: "Owners, observations and realisation within a benefit type." },
  { path: "forecast", label: "Forecast", title: "Forecast comparison", plate: "Plate IX", entry: false, blurb: "The original forecast, every revision, and what was observed." },
  { path: "evidence", label: "Evidence", title: "Evidence", plate: "Plate X", entry: false, blurb: "What was checked, by what, and what it cannot show." },
  { path: "case-study", label: "Case study", title: "Case study", plate: "Plate XI", entry: true, blurb: "Investment logic and the limits of attribution." },
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

/** Route path ("" for landing, else "portfolio", ...) for a location pathname; null when unknown. */
export function routeFromPathname(pathname: string): string | null {
  const base = import.meta.env.BASE_URL;
  let rest = pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\/+/, "");
  rest = rest.replace(/index\.html$/, "").replace(/\/+$/, "");
  return ROUTES.some((r) => r.path === rest) ? rest : null;
}
