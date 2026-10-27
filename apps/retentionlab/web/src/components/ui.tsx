import { useState, type ReactNode } from "react";
import type { Dataset, DatasetId } from "../data/dataset";
import { useParam } from "../router";
import { ROUTES } from "../routes";
import { useDataset, usePrimaryId } from "../state/data";
import { csvText, downloadText, slug } from "../lib/format";
import { Link } from "./link";

/** Renders children once the dataset is loaded and recomputed; otherwise an honest loading or error state. Nothing is shown in place of data. */
export function WithDataset({ id, children }: { id: DatasetId; children: (ds: Dataset) => ReactNode }) {
  const s = useDataset(id);
  if (s.status === "loading") return <p className="notice" role="status" data-testid="loading">Loading the published {id === "golden" ? "golden fixture" : "snapshot"} and recomputing every figure in the browser…</p>;
  if (s.status === "error") return <div className="notice notice--bad" role="alert" data-testid="load-error"><p>The data did not load, so no figure is shown: {s.error}</p><button type="button" onClick={s.reload}>Try again</button></div>;
  return <>{children(s.dataset)}</>;
}
/** The dataset the address asks for (snapshot, or `?dataset=golden`). */
export function WithData({ children }: { children: (ds: Dataset) => ReactNode }) {
  return <WithDataset id={usePrimaryId()} >{children}</WithDataset>;
}

export type ChipKind = "ok" | "risk" | "hatch" | "note" | "plain";
/** A status label; colour is never the only signal (the word is always printed). */
export function Chip({ kind = "plain", children, k }: { kind?: ChipKind; children: ReactNode; k?: string }) {
  return <span className={`chip chip--${kind}`} {...(k ? { "data-chip": k } : {})}>{children}</span>;
}
/** A definition popover: a native disclosure, so it works with the keyboard and without a script. */
export function Def({ term, children }: { term: string; children: ReactNode }) {
  return <details className="def"><summary><span>{term}</span><span className="def__q" aria-hidden="true">?</span></summary><span className="def__body">{children}</span></details>;
}
export function Scroll({ children, label }: { children: ReactNode; label: string }) {
  return <div className="scroll" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}
/** A figure with a stable hook for the tests. */
export function Fig({ k, children, tone }: { k: string; children: ReactNode; tone?: "neg" | "pos" | undefined }) {
  return <span className={`fig${tone ? ` ${tone}` : ""}`} data-figure={k}>{children}</span>;
}
/** The opening of a view: a mark, the h1, a lede and the contracts it implements. */
export function ViewHead({ mark, title, contracts, children }: { mark: string; title: string; contracts: string; children?: ReactNode }) {
  return (
    <header className="view-head">
      <p className="shelfmark">{mark}</p>
      <h1>{title}</h1>
      {children}
      <p className="contracts" data-testid="contracts">Contracts: {contracts}</p>
    </header>
  );
}
/** The active window, population, filters and data version, always stated (P10-UI-*-R06). */
export function ScopeStrip({ ds, items }: { ds: Dataset; items: [string, ReactNode][] }) {
  return (
    <p className="scope" data-testid="scope">
      {items.map(([k, v]) => <span key={k}><b>{k}</b> {v}</span>)}
      <span><b>data</b> <span className="mono">{ds.strip.dataset_version}</span></span>
    </p>
  );
}
/** The simulation notice shown wherever an action is only a browser-memory simulation. */
export function SimNote({ children }: { children?: ReactNode }) {
  return <p className="simnote" data-testid="sim-note"><strong>Simulation, browser memory only.</strong> {children ?? "Nothing is sent to anyone and no published figure changes; the simulation is gone when you reload."}</p>;
}
/** The disclosure that the model's margin over the baselines was reached by construction (D-G02, D-07). */
export function ByConstruction({ compact = false }: { compact?: boolean }) {
  return (
    <aside className="note" data-testid="by-construction">
      <strong>Reached by construction.</strong>{" "}
      {compact
        ? "The logistic model beats the baselines because the generator's engagement signal was strengthened until the stated margins were met (disclosure D-G02)."
        : "The generator was run, the model was fitted, and the first margins were too small. The engagement signal was then strengthened (coefficient 1100 to 2200, plus a per-account offset) until the margins over the rule and the random baseline were met. The margin on this page is therefore a property of the synthetic world, not evidence that this kind of model beats a simple rule on real accounts."}{" "}
      <Link to="evidence">Read disclosure D-G02</Link>.
    </aside>
  );
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
/** A select that keeps its value in the address. */
export function ParamSelect({ name, label, dflt, options, testid }: { name: string; label: string; dflt: string; options: { value: string; label: string }[]; testid?: string }) {
  const [v, set] = useParam(name, dflt);
  const value = options.some((o) => o.value === v) ? v : dflt;
  return (
    <label className="field">{label}
      <select value={value} onChange={(e) => set(e.target.value)} {...(testid ? { "data-testid": testid } : {})}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}
/** Download exactly what the table above shows, with the contract version, scope, dataset hash and generated timestamp in the header (P10-UI-*-R20). */
export function ExportButton({ ds, name, scope, header, rows }: { ds: Dataset; name: string; scope: string; header: string[]; rows: (string | number | null)[][] }) {
  return (
    <button type="button" className="button--quiet" data-testid={`export-${slug(name)}`} onClick={() => downloadText(`retentionlab-${slug(name)}.csv`, csvText(
      [["contract_version", ds.strip.contract_version], ["dataset_version", ds.strip.dataset_version], ["dataset_hash", ds.strip.dataset_hash], ["generated_at", ds.strip.generated_at], ["as_of", ds.strip.as_of], ["scope", scope], ["rows", String(rows.length)], ["synthetic", "true; hypothetical where marked"]], header, rows))}>
      Download this table (CSV)
    </button>
  );
}
/** The empty state of a filtered view, with the way out. */
export function NoData({ what, onClear }: { what: string; onClear: () => void }) {
  return <div className="notice" role="status" data-testid="no-data"><p>No {what} match the current filters. Nothing is shown rather than a zero.</p><button type="button" onClick={onClear}>Clear the filters</button></div>;
}
/** Where to go next from a view: the evidence, the definitions (case study) and the neighbouring routes (P10-UI-*-R21). */
export function Related({ also = [] }: { also?: string[] }) {
  const links = [...also, "evidence", "case-study"];
  return (
    <nav className="related" aria-label="Related pages" data-testid="related">
      {links.map((p) => { const r = ROUTES.find((x) => x.path === p)!; return <Link key={p} to={p}>{r.title}</Link>; })}
    </nav>
  );
}
/** A toggle that reveals the data table behind a graphic. The table is in the page either way for assistive technology. */
export function TableFold({ summary, children, open = true }: { summary: string; children: ReactNode; open?: boolean }) {
  const [o, setO] = useState(open);
  return <details className="fold" open={o} onToggle={(e) => setO((e.target as HTMLDetailsElement).open)}><summary>{summary}</summary>{children}</details>;
}
