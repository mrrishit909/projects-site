// Route table (docs/web-brief.md). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string; entry: boolean; blurb: string }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Observatory", title: "Pipeline Observatory", entry: false, blurb: "The decision, the snapshot and where to look." },
  { path: "overview", label: "Overview", title: "Platform overview", entry: true, blurb: "Freshness beside ingestion age, independent of green jobs." },
  { path: "dag", label: "Graph", title: "Dependency graph", entry: true, blurb: "Sources, models and the publication, freshness drawn on every node." },
  { path: "runs", label: "Runs", title: "Run detail", entry: true, blurb: "Steps, attempts, quality results and evidence of one run; the golden batch and its replay." },
  { path: "sources", label: "Sources", title: "Source contract", entry: false, blurb: "Schema, version comparison and the checkpoint of each source." },
  { path: "quarantine", label: "Quarantine", title: "Quarantine desk", entry: true, blurb: "Invalid rows and their retry disposition, simulated in browser memory." },
  { path: "gate", label: "Gate", title: "Quality gate", entry: true, blurb: "Critical checks and the publication decision; a failed run never replaces the publication." },
  { path: "backfill", label: "Backfill", title: "Backfill console", entry: false, blurb: "Partitions, overlaps and progress; requests simulated in browser memory." },
  { path: "incidents", label: "Incidents", title: "Incident timeline", entry: false, blurb: "Detection, diagnosis and verified recovery." },
  { path: "benchmark", label: "Benchmark", title: "Benchmark evidence", entry: false, blurb: "Measured hardware, size and duration, with what each number can and cannot say." },
  { path: "evidence", label: "Evidence", title: "Evidence", entry: false, blurb: "Hashes recomputed here, designed relationships, injected defects." },
  { path: "case-study", label: "Case study", title: "Case study", entry: true, blurb: "Delivery guarantees and failure experiments." },
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
