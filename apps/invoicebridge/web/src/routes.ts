// Route table (docs/web-brief.md). Paths are relative to BASE_URL; "" is the landing page.
// Keep in step with scripts/postbuild-routes.mjs, which writes one index.html per route.
export interface RouteDef { path: string; label: string; title: string; entry: boolean }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "InvoiceBridge", entry: false },
  { path: "intake", label: "Intake", title: "Intake and duplicate detection", entry: true },
  { path: "invoices", label: "Invoice desk", title: "Invoice desk", entry: true },
  { path: "matching", label: "Matching", title: "Three-way matching", entry: true },
  { path: "duplicates", label: "Duplicates", title: "Duplicate groups", entry: false },
  { path: "exceptions", label: "Exceptions", title: "Exception queue", entry: true },
  { path: "approvals", label: "Approvals", title: "Approval desk", entry: false },
  { path: "vendors", label: "Vendors", title: "Vendors", entry: false },
  { path: "exports", label: "Exports", title: "Export review", entry: false },
  { path: "audit", label: "Audit", title: "Audit timeline", entry: false },
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

/** Route path ("" for landing, else "intake", ...) for a location pathname; null when unknown. */
export function routeFromPathname(pathname: string): string | null {
  const base = import.meta.env.BASE_URL;
  let rest = pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\/+/, "");
  rest = rest.replace(/index\.html$/, "").replace(/\/+$/, "");
  return ROUTES.some((r) => r.path === rest) ? rest : null;
}
