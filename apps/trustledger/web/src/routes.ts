// Route table (docs/web-brief.md). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string; entry: boolean; blurb: string }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "TrustLedger", entry: false, blurb: "The decision, the snapshot and where to look." },
  { path: "catalog", label: "Catalog", title: "Catalog", entry: true, blurb: "Search datasets, fields and owners; who is accountable for what." },
  { path: "glossary", label: "Glossary", title: "Glossary", entry: true, blurb: "Metric definitions and their versions side by side." },
  { path: "scorecard", label: "Scorecard", title: "Quality scorecard", entry: true, blurb: "Five dimensions, kept apart; the weighted score; critical failures." },
  { path: "rules", label: "Rules", title: "Rule detail", entry: true, blurb: "The eligible population, failing examples, comparable runs." },
  { path: "issues", label: "Issues", title: "Issue workbench", entry: true, blurb: "Ownership, aging, claimed against resolved." },
  { path: "lineage", label: "Lineage", title: "Lineage explorer", entry: true, blurb: "Declared, observed and inferred edges, kept apart." },
  { path: "duplicates", label: "Duplicates", title: "Duplicate review", entry: false, blurb: "Candidate pairs side by side, with their uncertainty." },
  { path: "merges", label: "Merges", title: "Merge history", entry: false, blurb: "Reversible mappings and what they restore." },
  { path: "impact", label: "Impact", title: "Impact preview", entry: false, blurb: "What a definition change reaches downstream." },
  { path: "evidence", label: "Evidence", title: "Evidence", entry: false, blurb: "What was checked, by what, and what it cannot show." },
  { path: "case-study", label: "Case study", title: "Case study", entry: true, blurb: "The problem, the method, the findings and the limits." },
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

/** Route path ("" for landing, else "catalog", ...) for a location pathname; null when unknown. */
export function routeFromPathname(pathname: string): string | null {
  const base = import.meta.env.BASE_URL;
  let rest = pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\/+/, "");
  rest = rest.replace(/index\.html$/, "").replace(/\/+$/, "");
  return ROUTES.some((r) => r.path === rest) ? rest : null;
}
