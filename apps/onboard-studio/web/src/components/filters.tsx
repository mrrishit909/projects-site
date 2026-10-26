import type { Filters, PauseMode, ViewState } from "../state/filters";
import { describeFilters } from "../state/filters";
import "../styles/screens.css";

export interface FilterOptions { segments: readonly string[]; regions: readonly string[]; versions: readonly { id: string; label: string }[] }

function Select({ id, label, value, options, onChange }: { id: string; label: string; value: string; options: readonly { value: string; label: string }[]; onChange: (v: string) => void }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

/** Filters kept in the URL query. Dates are UTC days; the window is half-open [from, to) on opened_at. */
export function FilterBar({ view, options, shown, total }: { view: ViewState; options: FilterOptions; shown: number; total: number }) {
  const f: Filters = view.filters;
  return (
    <section className="filters" aria-labelledby="filters-title">
      <h2 id="filters-title" className="filters__title">Filters</h2>
      <div className="filters__grid">
        <div className="field">
          <label htmlFor="f-from">Opened from (UTC day, inclusive)</label>
          <input id="f-from" type="date" value={f.from} onChange={(e) => view.set({ from: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="f-to">Opened to (UTC day, exclusive)</label>
          <input id="f-to" type="date" value={f.to} onChange={(e) => view.set({ to: e.target.value })} />
        </div>
        <Select id="f-segment" label="Segment" value={f.segment} options={options.segments.map((s) => ({ value: s, label: s }))} onChange={(v) => view.set({ segment: v })} />
        <Select id="f-region" label="Region" value={f.region} options={options.regions.map((s) => ({ value: s, label: s }))} onChange={(v) => view.set({ region: v })} />
        <Select id="f-wf" label="Workflow version" value={f.wf} options={options.versions.map((v) => ({ value: v.id, label: v.label }))} onChange={(v) => view.set({ wf: v })} />
        <div className="field field--action"><button type="button" className="btn" onClick={view.clear} data-testid="clear-filters">Clear filters</button></div>
      </div>
      <p className="filters__summary" role="status" data-testid="population-line">
        Population: <strong data-testid="population-shown">{shown}</strong> of {total} accepted cases. Filters: {describeFilters(f)}. The window is half-open, [from, to), on opened_at.
      </p>
      {view.window === null && <p className="notice notice--error" role="alert">The window start must be before its end, so no case matches. Change the dates or clear the filters.</p>}
    </section>
  );
}

/** The pause-policy toggle: a view setting, labelled as such. */
export function PauseToggle({ view, policy }: { view: ViewState; policy: string }) {
  const set = (m: PauseMode): void => view.set({ pause: m === "none" ? "none" : null });
  return (
    <fieldset className="pause-toggle">
      <legend>Pause policy (view setting, browser-memory simulation)</legend>
      <label className="radio"><input type="radio" name="pause" checked={view.pause === "configured"} onChange={() => set("configured")} /> Configured</label>
      <label className="radio"><input type="radio" name="pause" checked={view.pause === "none"} onChange={() => set("none")} /> None</label>
      <p className="small muted">{policy} This recomputes the figures on this page in your browser only; the dataset is not changed and a reload keeps only what the address carries.</p>
    </fieldset>
  );
}
