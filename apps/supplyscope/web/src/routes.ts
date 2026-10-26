// Route table (web-brief). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "SupplyScope" },
  { path: "overview", label: "Overview", title: "Planning overview" },
  { path: "skus", label: "SKUs", title: "SKU trajectory" },
  { path: "locations", label: "Locations", title: "Locations" },
  { path: "suppliers", label: "Suppliers", title: "Suppliers" },
  { path: "forecast", label: "Forecast", title: "Forecast evaluation" },
  { path: "reorder", label: "Reorder", title: "Reorder workbench" },
  { path: "simulator", label: "Simulator", title: "Policy simulator" },
  { path: "capital", label: "Capital", title: "Working capital" },
  { path: "draft", label: "Draft", title: "Purchase draft export" },
  { path: "case-study", label: "Case study", title: "Case study" },
];

/** True when the address asks for the golden fixture; that choice follows the reader from view to view. */
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

/** Route path ("" for landing, else "reorder", ...) for a location pathname; null when unknown. */
export function routeFromPathname(pathname: string): string | null {
  const base = import.meta.env.BASE_URL;
  let rest = pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\/+/, "");
  rest = rest.replace(/index\.html$/, "").replace(/\/+$/, "");
  return ROUTES.some((r) => r.path === rest) ? rest : null;
}
