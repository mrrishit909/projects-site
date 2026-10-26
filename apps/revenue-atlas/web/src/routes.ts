// Route table (web-brief). Paths are relative to BASE_URL; "" is the landing page.
export interface RouteDef { path: string; label: string; title: string }
export const ROUTES: readonly RouteDef[] = [
  { path: "", label: "Start", title: "Revenue Atlas" },
  { path: "overview", label: "Overview", title: "Executive overview" },
  { path: "bridge", label: "Bridge", title: "Margin bridge" },
  { path: "products", label: "Products", title: "Product matrix" },
  { path: "customers", label: "Customers", title: "Customer explorer" },
  { path: "regions", label: "Regions", title: "Regional review" },
  { path: "returns", label: "Returns", title: "Returns desk" },
  { path: "discounts", label: "Discounts", title: "Discount lab" },
  { path: "evidence", label: "Evidence", title: "Transaction evidence ledger" },
  { path: "scenarios", label: "Scenarios", title: "Scenario comparison" },
  { path: "case-study", label: "Case study", title: "Case study" },
];

/** Absolute URL path for a route path, honouring the injected base. */
export function hrefFor(path: string): string {
  return `${import.meta.env.BASE_URL}${path ? `${path}/` : ""}`;
}

/** Route path ("" for landing, else "overview", ...) for a location pathname; null when unknown. */
export function routeFromPathname(pathname: string): string | null {
  const base = import.meta.env.BASE_URL;
  let rest = pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\/+/, "");
  rest = rest.replace(/index\.html$/, "").replace(/\/+$/, "");
  return ROUTES.some((r) => r.path === rest) ? rest : null;
}
