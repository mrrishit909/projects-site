import type { ReactNode } from "react";
import type { Dataset, DatasetId } from "../data/dataset";
import { useParam } from "../router";
import { useDataset, usePrimaryId } from "../state/data";

/** Renders children once the dataset is loaded and recomputed; otherwise an honest loading or error state. */
export function WithDataset({ id, children }: { id: DatasetId; children: (ds: Dataset) => ReactNode }) {
  const s = useDataset(id);
  if (s.status === "loading") return <p className="notice" role="status" data-testid="loading">Loading the published {id === "golden" ? "golden fixture" : "snapshot"} and recomputing every figure in the browser…</p>;
  if (s.status === "error") return <div className="notice notice--bad" role="alert" data-testid="load-error"><p>The data did not load: {s.error}. No figure is shown because none can be computed.</p><button type="button" onClick={s.reload}>Try again</button></div>;
  return <>{children(s.dataset)}</>;
}
/** The dataset the address asks for (snapshot, or `?dataset=golden`). */
export function WithData({ children }: { children: (ds: Dataset) => ReactNode }) {
  return <WithDataset id={usePrimaryId()}>{children}</WithDataset>;
}

export type ChipKind = "ok" | "note" | "crit" | "hatch" | "plain";
/** A status label; the colour is never the only signal (the word is always printed). The dry red (`crit`) is reserved for refusals and overallocation. */
export function Chip({ kind = "plain", children, k }: { kind?: ChipKind; children: ReactNode; k?: string }) {
  return <span className={`chip chip--${kind}`} {...(k ? { "data-chip": k } : {})}>{children}</span>;
}
/** A definition popover: a native disclosure, so it works with keyboard and without a script. */
export function Def({ term, children }: { term: string; children: ReactNode }) {
  return <details className="def"><summary><span>{term}</span><span className="def__q" aria-hidden="true">?</span></summary><span className="def__body">{children}</span></details>;
}
export function Scroll({ children, label }: { children: ReactNode; label: string }) {
  return <div className="scroll" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}
export function NotBuilt({ children }: { children: ReactNode }) {
  return <aside className="notbuilt" data-testid="not-built"><strong>Not built here.</strong> {children}</aside>;
}
/** A figure with a stable hook for the tests. */
export function Fig({ k, children }: { k: string; children: ReactNode }) {
  return <span className="fig" data-figure={k}>{children}</span>;
}
/** The opening of a view: a plate number, the h1 and an optional lede. */
export function PlateHead({ mark, title, children }: { mark: string; title: string; children?: ReactNode }) {
  return (
    <header className="plate">
      <p className="plate__no">{mark}</p>
      <h1>{title}</h1>
      {children}
    </header>
  );
}
/** The simulation notice shown wherever an action is only a browser-memory simulation. */
export function SimNote({ children }: { children?: ReactNode }) {
  return <p className="simnote" data-testid="sim-note"><strong>Simulation, browser memory only.</strong> {children ?? "Nothing is saved, proposed or funded; the published data and every published figure stay as they are, and the simulation is gone when you reload."}</p>;
}
/** One choice among a few, kept in the address. */
export function Choice({ name, legend, options, value, onChange, testid }: { name: string; legend: string; options: { value: string; label: string }[]; value: string; onChange: (v: string) => void; testid?: string }) {
  return (
    <fieldset className="picker" {...(testid ? { "data-testid": testid } : {})}>
      <legend>{legend}</legend>
      <div className="picker__row">
        {options.map((o) => (
          <label key={o.value} className={`picker__opt${o.value === value ? " is-on" : ""}`}>
            <input type="radio" name={name} value={o.value} checked={o.value === value} onChange={() => onChange(o.value)} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
/** A select kept in the address. */
export function ParamSelect({ name, label, options, dflt, testid }: { name: string; label: string; options: { value: string; label: string }[]; dflt: string; testid?: string }) {
  const [v, set] = useParam(name, dflt);
  const value = options.some((o) => o.value === v) ? v : dflt;
  return (
    <label>{label}
      <select value={value} onChange={(e) => set(e.target.value)} {...(testid ? { "data-testid": testid } : {})}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}
export function useParamChoice(name: string, options: readonly string[], dflt: string): [string, (v: string) => void] {
  const [v, set] = useParam(name, dflt);
  return [options.includes(v) ? v : dflt, set];
}
/** The empty state of a filtered list, with the way out. */
export function NoData({ what, onClear }: { what: string; onClear?: () => void }) {
  return <div className="notice" data-testid="no-data"><p>No {what} match the current filters.</p>{onClear && <button type="button" onClick={onClear}>Clear the filters</button>}</div>;
}
/** A CSV of exactly the rows on screen. */
export function ExportCsv({ name, csv, label }: { name: string; csv: string; label: string }) {
  return <a className="button button--quiet" download={name} href={`data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`} data-testid="export-csv" aria-label={label}>Download CSV ({name})</a>;
}
