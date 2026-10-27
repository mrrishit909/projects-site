import type { ReactNode } from "react";
import type { Dataset, DatasetId } from "../data/dataset";
import { useParam } from "../router";
import { useDataset, usePrimaryId } from "../state/data";

/** Renders children once the dataset is loaded and recomputed; otherwise an honest loading or error state. */
export function WithDataset({ id, children }: { id: DatasetId; children: (ds: Dataset) => ReactNode }) {
  const s = useDataset(id);
  if (s.status === "loading") return <p className="notice" role="status" data-testid="loading">Loading the published {id === "golden" ? "golden fixture" : "snapshot"} and recomputing every figure in the browser…</p>;
  if (s.status === "error") return <div className="notice notice--bad" role="alert" data-testid="load-error"><p>The data did not load: {s.error}</p><button type="button" onClick={s.reload}>Try again</button></div>;
  return <>{children(s.dataset)}</>;
}
/** The dataset the address asks for (snapshot, or `?dataset=golden`). */
export function WithData({ children }: { children: (ds: Dataset) => ReactNode }) {
  return <WithDataset id={usePrimaryId()}>{children}</WithDataset>;
}

export type ChipKind = "ok" | "note" | "crit" | "hatch" | "plain";
/** A status label; the colour is never the only signal (the word is always printed). Vermilion (`crit`) is reserved for critical failures. */
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
/** A small honest label for what a view does not do. */
export function NotBuilt({ children }: { children: ReactNode }) {
  return <aside className="notbuilt" data-testid="not-built"><strong>Not built here.</strong> {children}</aside>;
}
/** A figure with a stable hook for the tests. */
export function Fig({ k, children }: { k: string; children: ReactNode }) {
  return <span className="fig" data-figure={k}>{children}</span>;
}
/** The opening of a view: a shelf mark, the h1 and an optional lede. */
export function ViewHead({ mark, title, children }: { mark: string; title: string; children?: ReactNode }) {
  return (
    <header className="view-head">
      <p className="shelfmark">{mark}</p>
      <h1>{title}</h1>
      {children}
    </header>
  );
}
/** The simulation notice shown wherever an action is only a browser-memory simulation. */
export function SimNote({ children }: { children?: ReactNode }) {
  return <p className="simnote" data-testid="sim-note"><strong>Simulation, browser memory only.</strong> {children ?? "Nothing is merged, closed, reopened or disabled; the published data and every figure above stay as they are, and the simulation is gone on reload."}</p>;
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
/** Pages of a long list, kept in the address. */
export function usePage(name: string, size: number, total: number): { page: number; pages: number; from: number; to: number; set: (p: number) => void } {
  const [v, set] = useParam(name, "1");
  const pages = Math.max(1, Math.ceil(total / size));
  const page = Math.min(pages, Math.max(1, Number.parseInt(v, 10) || 1));
  return { page, pages, from: (page - 1) * size, to: Math.min(total, page * size), set: (p) => set(String(p)) };
}
export function Pager({ page, pages, from, to, total, set, label }: { page: number; pages: number; from: number; to: number; total: number; set: (p: number) => void; label: string }) {
  return (
    <nav className="pager" aria-label={`${label} pages`}>
      <span data-testid="pager-range">{total === 0 ? "none" : `${from + 1} to ${to} of ${total}`}</span>
      <button type="button" className="button--quiet" disabled={page <= 1} onClick={() => set(page - 1)}>Previous</button>
      <button type="button" className="button--quiet" disabled={page >= pages} onClick={() => set(page + 1)}>Next</button>
    </nav>
  );
}
