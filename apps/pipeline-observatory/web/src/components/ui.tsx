import type { ReactNode } from "react";
import type { Dataset } from "../data/analyse";
import type { Basis } from "../data/analyse";
import { useParam } from "../router";
import { useDataset, usePrimaryId } from "../state/data";

/** Renders children once the dataset is loaded and recomputed; otherwise an honest loading or error state. */
export function WithData({ children }: { children: (ds: Dataset, bytes: Record<string, number>) => ReactNode }) {
  const id = usePrimaryId();
  const s = useDataset(id);
  if (s.status === "loading") return <p className="notice" role="status" data-testid="loading">Loading the published {id === "golden" ? "golden fixture" : "snapshot"} and recomputing every figure in the browser…</p>;
  if (s.status === "error") return <div className="notice notice--bad" role="alert" data-testid="load-error"><p><strong>The data did not load.</strong> {s.error}. No figure is shown, because none was computed.</p><button type="button" onClick={s.reload}>Try again</button></div>;
  return <>{children(s.dataset, s.bytes)}</>;
}

export type Tone = "ok" | "bad" | "warn" | "idle" | "info";
const GLYPH: Record<Tone, string> = { ok: "✓", bad: "✕", warn: "!", idle: "○", info: "◆" };
/** A status label: the colour is never the only signal (a glyph and the word are always printed). */
export function Status({ tone, children, k }: { tone: Tone; children: ReactNode; k?: string }) {
  return <span className={`status status--${tone}`} {...(k ? { "data-status": k } : {})}><span aria-hidden="true" className="status__g">{GLYPH[tone]}</span>{children}</span>;
}
const SCOPE: Record<Basis, { label: string; title: string }> = {
  complete: { label: "Complete world", title: "Recomputed in this browser from files that are published in full." },
  sample: { label: "2,000-row sample", title: "Recomputed in this browser over the published raw_records sample; it describes the sample, not the whole world." },
  recorded: { label: "Recorded by the generator", title: "A statement in the manifest about the complete world, which the published files cannot reproduce." },
};
export function ScopeTag({ basis }: { basis: Basis }) {
  return <span className={`scope scope--${basis}`} title={SCOPE[basis].title} data-scope={basis}>{SCOPE[basis].label}</span>;
}
export function Scroll({ children, label }: { children: ReactNode; label: string }) {
  return <div className="scroll" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}
/** A figure with a stable hook for the tests. */
export function Fig({ k, children }: { k: string; children: ReactNode }) {
  return <span className="fig" data-figure={k}>{children}</span>;
}
/** A big readout: label, value, unit and the sentence that says what it means. */
export function Readout({ label, value, unit, note, k, scope }: { label: string; value: ReactNode; unit?: string | undefined; note?: ReactNode; k: string; scope?: Basis | undefined }) {
  return (
    <div className="readout" data-readout={k}>
      <dt>{label}{scope ? <> <ScopeTag basis={scope} /></> : null}</dt>
      <dd><span className="readout__v" data-figure={k}>{value}</span>{unit ? <span className="readout__u">{unit}</span> : null}</dd>
      {note ? <dd className="readout__n">{note}</dd> : null}
    </div>
  );
}
/** The opening of a view: a catalogue mark, the h1 and an optional lede. */
export function ViewHead({ mark, title, children }: { mark: string; title: string; children?: ReactNode }) {
  return (
    <header className="view-head">
      <p className="mark">{mark}</p>
      <h1>{title}</h1>
      {children}
    </header>
  );
}
export function Panel({ id, title, scope, children, aside }: { id?: string; title: string; scope?: Basis | undefined; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="panel" {...(id ? { id, "aria-labelledby": `${id}-h` } : {})}>
      <div className="panel__head"><h2 {...(id ? { id: `${id}-h` } : {})}>{title}</h2>{scope ? <ScopeTag basis={scope} /> : null}{aside}</div>
      {children}
    </section>
  );
}
/** The simulation notice shown wherever an action is only a browser-memory simulation. */
export function SimNote({ children }: { children?: ReactNode }) {
  return <p className="simnote" data-testid="sim-note"><strong>Simulation, browser memory only.</strong> {children ?? "Nothing is written, retried or published; the published data and every figure above stay as they are, and this is gone on reload."}</p>;
}
/** The meaning and unit of a figure, printed beside it. */
export function Meaning({ children }: { children: ReactNode }) { return <p className="meaning">{children}</p>; }
export function Empty({ children, onClear, clear }: { children: ReactNode; onClear?: () => void; clear?: string }) {
  return <div className="notice notice--empty" data-testid="empty" role="status"><p>{children}</p>{onClear ? <button type="button" onClick={onClear}>{clear ?? "Clear filters"}</button> : null}</div>;
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
      <button type="button" className="quiet" disabled={page <= 1} onClick={() => set(page - 1)}>Previous</button>
      <button type="button" className="quiet" disabled={page >= pages} onClick={() => set(page + 1)}>Next</button>
    </nav>
  );
}
