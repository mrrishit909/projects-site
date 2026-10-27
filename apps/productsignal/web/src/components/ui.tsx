import type { ReactNode } from "react";
import type { Dataset } from "../data/dataset";
import type { DatasetId } from "../data/load";
import { isoZ } from "../domain/time";
import { useParam } from "../router";
import { usePrimaryId, useDataset } from "../state/data";
import { day } from "../lib/format";

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

const KIND: Record<string, string> = {
  OK: "ok", conclusive: "ok", final: "ok", HARMFUL: "bad", MISMATCH: "bad", INSUFFICIENT: "warn", interim: "warn", "not conclusive": "warn", exploratory: "warn",
  blank: "plain", withheld: "bad", simulated: "warn", allowed: "ok", blocked: "bad", recorded: "ok", refused: "bad",
};
/** A status label; the colour is never the only signal (the word is always printed). */
export function Chip({ v, children }: { v: string; children?: ReactNode }) {
  return <span className={`chip chip--${KIND[v] ?? "plain"}`} data-chip={v}>{children ?? v}</span>;
}

/** A definition popover: a native disclosure, so it works with keyboard and without a script. */
export function Def({ term, children }: { term: string; children: ReactNode }) {
  return <details className="def"><summary><span>{term}</span><span className="def__q" aria-hidden="true">?</span></summary><div className="def__body">{children}</div></details>;
}
export function Scroll({ children, label }: { children: ReactNode; label?: string }) {
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

/** The opening of a view: an eyebrow, the h1 and an optional lede. */
export function ViewHead({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <header className="view-head">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {children}
    </header>
  );
}

export interface CutoffOption { value: string; at: number; label: string }
/** The cutoffs worth looking at: the as-of and the cutoff of every logged analysis run (the interim ones make the D-08 rule visible). */
export function cutoffOptions(ds: Dataset): CutoffOption[] {
  const out = new Map<number, string[]>();
  const put = (t: number, l: string): void => { out.set(t, [...(out.get(t) ?? []), l]); };
  put(ds.cutoff, "as-of");
  for (const r of ds.runs) {
    const plan = ds.plans.get(r.experiment_version_id);
    put(r.cutoff_at, `${r.analysis_id} ${r.experiment_version_id} ${plan && r.cutoff_at < plan.planned_end ? "interim" : "final"}`);
  }
  return [...out.entries()].sort((a, b) => a[0] - b[0]).map(([at, labels]) => ({ value: isoZ(at), at, label: `${day(isoZ(at))} (${labels.join(", ")})` }));
}
/** The cutoff in the address (`?cutoff=`), default the dataset's as-of. */
export function useCutoff(ds: Dataset): [CutoffOption, CutoffOption[], (v: string) => void] {
  const opts = cutoffOptions(ds);
  const dflt = isoZ(ds.cutoff);
  const [v, set] = useParam("cutoff", dflt);
  return [opts.find((o) => o.value === v) ?? opts.find((o) => o.value === dflt)!, opts, set];
}
export function CutoffPicker({ options, value, onChange, label = "Analysis cutoff" }: { options: CutoffOption[]; value: string; onChange: (v: string) => void; label?: string }) {
  return (
    <fieldset className="picker" data-testid="cutoff-picker">
      <legend>{label}</legend>
      <div className="picker__row">
        {options.map((o) => (
          <label key={o.value} className={`picker__opt${o.value === value ? " is-on" : ""}`}>
            <input type="radio" name="cutoff" value={o.value} checked={o.value === value} onChange={() => onChange(o.value)} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
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
