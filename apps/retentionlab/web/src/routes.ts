// Route table (docs/web-brief.md). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string; entry: boolean; blurb: string; contracts: string }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "RetentionLab", entry: false, blurb: "The decision, the snapshot and where to look.", contracts: "P10-GOAL-01" },
  { path: "overview", label: "Overview", title: "Retention overview", entry: true, blurb: "Mature cohorts, the churn definition and the censored tail.", contracts: "P10-MET-01, P10-FLOW-02, D-01" },
  { path: "cohorts", label: "Cohorts", title: "Cohort explorer", entry: false, blurb: "Plan, region and tenure: who churns and what the model expected.", contracts: "P10-MET-01, P10-MET-06, D-03" },
  { path: "features", label: "Features", title: "Feature evidence", entry: false, blurb: "Point-in-time lineage, availability and what arrived late.", contracts: "P10-FLOW-01, P10-TEST-01, P10-TEST-02, D-01" },
  { path: "models", label: "Models", title: "Model comparison", entry: true, blurb: "Random, rule and logistic on the held-out test, with the golden case recomputed.", contracts: "P10-MET-04, P10-MET-05, P10-FLOW-05, D-03" },
  { path: "calibration", label: "Calibration", title: "Calibration lab", entry: true, blurb: "The reliability curve with the number of rows behind each point.", contracts: "P10-MET-05, P10-MET-06, P10-FLOW-06, D-03" },
  { path: "capacity", label: "Capacity", title: "Capacity planner", entry: true, blurb: "Precision and recall at K, risk lift and the contact budget (simulated).", contracts: "P10-MET-02, P10-MET-03, P10-MET-07, P10-MET-08, P10-MET-09, D-03" },
  { path: "account", label: "Account", title: "Account explanation", entry: false, blurb: "Risk factors for one account, with no causal claim.", contracts: "P10-FLOW-07, P10-FLOW-08, P10-TEST-09" },
  { path: "queue", label: "Queue", title: "Outreach queue", entry: false, blurb: "Synthetic draft actions, capacity-limited, simulated and never sent.", contracts: "P10-FLOW-08, P10-FLOW-09, P10-TEST-09, P10-TEST-10" },
  { path: "monitoring", label: "Monitoring", title: "Monitoring", entry: false, blurb: "Drift by region, maturity and scoring freshness.", contracts: "P10-MET-10, P10-MET-11, P10-MET-12, P10-FLOW-10" },
  { path: "evidence", label: "Evidence", title: "Evidence", entry: false, blurb: "What was checked, by what, and what it cannot show.", contracts: "P10-TEST-01..12, D-07" },
  { path: "case-study", label: "Case study", title: "Case study", entry: true, blurb: "Model card, evaluation and the limits of the intervention.", contracts: "P10-DOMAIN-05, P10-DOMAIN-06, D-07" },
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
