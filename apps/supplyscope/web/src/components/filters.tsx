import type { PairRow } from "../domain/metrics";
import type { Population } from "../domain/types";
import type { Scenario } from "../state/scenario";
import { describeFilters, type Filters, type ViewState } from "../state/filters";

function Select({ id, label, value, options, onChange, all = "All" }: { id: string; label: string; value: string; options: readonly { value: string; label: string }[]; onChange: (v: string) => void; all?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{all}</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}
export { Select };

/** As-of date (and, for the golden fixture, the fixture state): view settings kept in the address. */
export function ScenarioBar({ view, sc }: { view: ViewState; sc: Scenario }) {
  return (
    <section className="filters" aria-label="As-of date">
      <div className="filters__grid">
        <div className="field">
          <label htmlFor="as-of">As of (UTC day, whole day included)</label>
          <input id="as-of" type="date" min={sc.min} max={sc.max} value={sc.text} onChange={(e) => view.set({ as_of: e.target.value && e.target.value !== sc.max ? e.target.value : null })} />
        </div>
        {sc.stateNames.length > 0 && (
          <Select id="fixture-state" label="Fixture state" value={sc.stateName} all="Accepted population" options={sc.stateNames.map((n) => ({ value: n, label: n }))} onChange={(v) => view.set({ state: v || null })} />
        )}
      </div>
      <p className="small muted" data-testid="as-of-line">Every figure is recomputed in your browser at {sc.text} 23:59:59 UTC from movements posted by then; nothing later is read.</p>
      {sc.notices.map((n) => <p key={n} className="notice notice--error" role="alert">{n}</p>)}
    </section>
  );
}

/** Reorder filters kept in the URL query. */
export function FilterBar({ view, pop, rows, shown, total }: { view: ViewState; pop: Population; rows: readonly PairRow[]; shown: number; total: number }) {
  const f: Filters = view.filters;
  const locations = pop.locations.map((l) => ({ value: l.location_id, label: `${l.location_id} · ${l.location_name}` }));
  const suppliers = [...new Set(rows.map((r) => r.supplier_id))].sort().map((s) => ({ value: s, label: pop.suppliers.find((x) => x.supplier_id === s)?.supplier_name ? `${s} · ${pop.suppliers.find((x) => x.supplier_id === s)!.supplier_name}` : s }));
  return (
    <section className="filters" aria-labelledby="filters-title">
      <h2 id="filters-title" className="filters__title">Filters</h2>
      <div className="filters__grid">
        <Select id="f-loc" label="Location" value={f.loc} options={locations} onChange={(v) => view.set({ loc: v })} />
        <Select id="f-sup" label="Supplier" value={f.sup} options={suppliers} onChange={(v) => view.set({ sup: v })} />
        <Select id="f-trig" label="Reorder triggered" value={f.trig} options={[{ value: "yes", label: "Triggered (position below ROP)" }, { value: "no", label: "Not triggered" }]} onChange={(v) => view.set({ trig: v })} />
        <div className="field">
          <label htmlFor="f-q">Search SKU</label>
          <input id="f-q" type="search" value={f.q} placeholder="SKU-001 or prod-001" onChange={(e) => view.set({ q: e.target.value })} />
        </div>
        <div className="field field--action"><button type="button" className="btn" onClick={view.clear} data-testid="clear-filters">Clear filters</button></div>
      </div>
      <p className="filters__summary" role="status" data-testid="population-line">
        Rows: <strong data-testid="population-shown">{shown}</strong> of {total} SKU x location rows. Filters: {describeFilters(f)}.
      </p>
    </section>
  );
}
