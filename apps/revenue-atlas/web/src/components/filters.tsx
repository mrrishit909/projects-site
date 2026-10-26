// Filter controls, the visible population/basis summary and the links that carry filters between screens.
import type { AnchorHTMLAttributes, ReactNode } from "react";
import "../styles/screens.css";
import { datasetId } from "../data/load";
import { navigate } from "../router";
import { hrefFor } from "../routes";
import { carriedParams, hasFilters, queryFor, useFilters, useSearch, type Filters as F, type FilterOptions, type Population } from "../state/filters";
import { fmtInt } from "./format";

type Ready = Extract<Population, { status: "ready" }>;

export function describeFilters(f: F): string {
  const parts: string[] = [];
  if (f.from || f.to) parts.push(`shipped in [${f.from || "start"}, ${f.to || "end"})`);
  if (f.region) parts.push(`region ${f.region}`);
  if (f.segment) parts.push(`segment ${f.segment}`);
  if (f.category) parts.push(`category ${f.category}`);
  return parts.length ? parts.join("; ") : "none (all shipments in the snapshot)";
}

export function Filters({ options }: { options: FilterOptions }) {
  const { filters, set, clear } = useFilters();
  const sel = (id: keyof F, label: string, values: string[]) => (
    <div className="field">
      <label htmlFor={`f-${id}`}>{label}</label>
      <select id={`f-${id}`} value={filters[id]} onChange={(e) => set({ [id]: e.target.value })}>
        <option value="">All</option>
        {values.map((v) => <option key={v} value={v}>{v}</option>)}
      </select>
    </div>
  );
  return (
    <form className="filters" aria-label="Filters" onSubmit={(e) => e.preventDefault()}>
      <p className="filters__title" id="filters-title">Filters</p>
      <div className="filters__grid" role="group" aria-labelledby="filters-title">
        <div className="field">
          <label htmlFor="f-from">Shipped from (inclusive)</label>
          <input id="f-from" type="date" value={filters.from} onChange={(e) => set({ from: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="f-to">Shipped to (exclusive)</label>
          <input id="f-to" type="date" value={filters.to} onChange={(e) => set({ to: e.target.value })} />
        </div>
        {sel("region", "Region", options.regions)}
        {sel("segment", "Segment", options.segments)}
        {sel("category", "Category", options.categories)}
        <div className="field"><button type="button" className="btn" onClick={clear}>Clear filters</button></div>
      </div>
      <p className="filters__note" data-testid="window-label">
        Window <strong>[from, to)</strong>: half-open, UTC dates. A line shipped on the "to" date is not included.
      </p>
    </form>
  );
}

/** Date basis, active filters, dataset and exclusion counts: the denominators, always visible. */
export function PopulationSummary({ pop }: { pop: Ready }) {
  const q = pop.result.quarantined;
  const qLines = q.filter((r) => r.entity === "shipment_lines").length;
  const qReturns = q.filter((r) => r.entity === "returns").length;
  const rejected = pop.result.ingest.rejected.length;
  return (
    <dl className="basis" data-testid="population-summary">
      <div><dt>Date basis</dt><dd>Shipment date, UTC; months as [start, next start)</dd></div>
      <div><dt>Active window</dt><dd data-testid="active-window">[{pop.filters.from || "first shipment"}, {pop.filters.to || "no end"})</dd></div>
      <div><dt>Active filters</dt><dd data-testid="active-filters">{describeFilters(pop.filters)}</dd></div>
      <div><dt>Population</dt><dd><span data-testid="population-count">{fmtInt(pop.facts.length)}</span> shipment lines · {fmtInt(pop.metrics.eligible_orders)} orders</dd></div>
      <div><dt>Data version</dt><dd>{pop.snapshot.manifest.dataset_version} (synthetic)</dd></div>
      <div><dt>Excluded from the whole snapshot</dt><dd data-testid="exclusions">{fmtInt(qLines)} quarantined shipment lines · {fmtInt(qReturns)} quarantined returns · {fmtInt(pop.result.excluded.length)} lines excluded by order status · {fmtInt(rejected)} rejected records</dd></div>
    </dl>
  );
}

export function DatasetBanner() {
  if (datasetId() !== "golden") return null;
  return (
    <p className="banner" role="note" data-testid="golden-banner">
      Golden fixture dataset (?dataset=golden): a hand-derived three-unit order used to check this display against
      tests/fixtures/golden/expected.json. Not the demo data.
    </p>
  );
}

/** Internal link that may carry filters and other params; client-side on plain click. */
export function QueryLink({ to, filters, extra, children, ...rest }: { to: string; filters?: Partial<F>; extra?: Record<string, string>; children: ReactNode } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const search = useSearch();
  const href = `${hrefFor(to)}${queryFor(filters ?? {}, { ...carriedParams(search), ...extra })}`;
  return (
    <a
      {...rest}
      href={href}
      onClick={(e) => {
        rest.onClick?.(e);
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigate(href);
      }}
    >{children}</a>
  );
}

export function EmptyPopulation({ windowError }: { windowError: string | null }) {
  const { clear } = useFilters();
  return (
    <div className="status status--empty" role="status" data-testid="empty-state">
      <p className="status__title">No shipment lines match these filters</p>
      <p className="status__body">{windowError ?? "The filtered population is empty, so no totals are shown (none are invented)."}</p>
      <button type="button" className="btn" onClick={clear}>Clear filters</button>
    </div>
  );
}

export { hasFilters };
