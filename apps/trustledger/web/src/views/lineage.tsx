import { Chip, Def, Fig, Scroll, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { cmp, type Row } from "../domain/models";
import { layout } from "../lib/graph";
import { dayTime } from "../lib/format";
import { useParam } from "../router";

const NW = 132, NH = 24, CW = 196, RH = 34, PAD = 18;
type Kind = "declared" | "observed" | "inferred";
const KINDS: Kind[] = ["declared", "observed", "inferred"];

interface Pair { source: string; target: string; declared: boolean; observed: boolean; inferred: boolean; observations: number; last: string | null }
function pairsOf(ds: Dataset): Pair[] {
  const map = new Map<string, Pair>();
  for (const e of ds.raw.lineage_edges) {
    const k = `${e["source_dataset_id"]}\u0000${e["target_dataset_id"]}`;
    const p = map.get(k) ?? { source: e["source_dataset_id"], target: e["target_dataset_id"], declared: false, observed: false, inferred: false, observations: 0, last: null };
    const t = e["evidence_type"] as Kind;
    p[t] = true;
    if (t === "observed") { p.observations++; if (e["observed_at"] && (!p.last || e["observed_at"] > p.last)) p.last = e["observed_at"]; }
    map.set(k, p);
  }
  return [...map.values()].sort((a, b) => cmp(a.source, b.source) || cmp(a.target, b.target));
}

function Graph({ ds, pairs, kinds, focus, setFocus }: { ds: Dataset; pairs: Pair[]; kinds: Set<Kind>; focus: string; setFocus: (v: string) => void }) {
  const ids = ds.raw.datasets.map((d) => d["dataset_id"] as string);
  const { placed, layers, rows } = layout(ids, pairs.map((p) => [p.source, p.target] as const));
  const W = PAD * 2 + layers * CW - (CW - NW), H = PAD * 2 + rows * RH;
  const xy = (id: string): [number, number] => { const p = placed.get(id)!; return [PAD + p.layer * CW, PAD + p.row * RH]; };
  const path = (a: string, b: string, dy = 0): { d: string; mx: number; my: number } => {
    const [xs, ys] = xy(a), [xt, yt] = xy(b);
    const x1 = xs + NW, y1 = ys + NH / 2 + dy, x2 = xt, y2 = yt + NH / 2 + dy;
    const dx = Math.max(40, Math.abs(x2 - x1) / 2);
    const forward = x2 > x1;
    const c1 = forward ? x1 + dx : x1 + 50, c2 = forward ? x2 - dx : x2 - 50;
    return { d: `M${x1},${y1} C${c1},${y1} ${c2},${y2} ${x2},${y2}`, mx: (x1 + x2) / 2 + (forward ? 0 : 0), my: (y1 + y2) / 2 };
  };
  const touches = (p: Pair): boolean => !focus || p.source === focus || p.target === focus;
  const undeclared = (p: Pair): boolean => p.observed && !p.declared;
  return (
    <div className="graph-box" role="region" aria-label="Lineage graph (a table of the same edges follows)" tabIndex={0} data-testid="graph-box">
      <svg className="graph" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Lineage of ${ids.length} datasets. Declared edges are thin solid lines, observed edges are thick lines, inferred edges are dashed lines labelled inferred.`} data-testid="graph">
        <g data-layer="declared">{kinds.has("declared") && pairs.filter((p) => p.declared).map((p) => <path key={`d${p.source}${p.target}`} className={`e-declared${touches(p) ? "" : " e-dim"}`} d={path(p.source, p.target).d} data-edge="declared" data-pair={`${p.source}>${p.target}`}><title>{`declared: ${p.source} to ${p.target}`}</title></path>)}</g>
        <g data-layer="observed">{kinds.has("observed") && pairs.filter((p) => p.observed).map((p) => <g key={`o${p.source}${p.target}`} className={touches(p) ? "" : "e-dim"}>
          <path className="e-observed" d={path(p.source, p.target).d} data-edge="observed" data-pair={`${p.source}>${p.target}`} data-undeclared={undeclared(p)}><title>{`observed${undeclared(p) ? ", no declared counterpart" : ""}: ${p.source} to ${p.target}, ${p.observations} observation${p.observations === 1 ? "" : "s"}`}</title></path>
          {p.declared && kinds.has("declared") && <path className="e-declared" d={path(p.source, p.target).d} style={{ stroke: "var(--paper)", strokeWidth: 1.4 }} />}
          {undeclared(p) && (() => { const m = path(p.source, p.target); return <rect className="e-marker" x={m.mx - 5} y={m.my - 5} width={10} height={10} transform={`rotate(45 ${m.mx} ${m.my})`} data-marker="undeclared" />; })()}
        </g>)}</g>
        <g data-layer="inferred">{kinds.has("inferred") && pairs.filter((p) => p.inferred).map((p) => { const m = path(p.source, p.target, 6); return (
          <g key={`i${p.source}${p.target}`} className={touches(p) ? "" : "e-dim"} data-edge="inferred" data-pair={`${p.source}>${p.target}`}>
            <path className="e-inferred" d={m.d}><title>{`inferred, not observed: ${p.source} to ${p.target}`}</title></path>
            <g className="e-label" transform={`translate(${m.mx - 25},${m.my - 8})`}><rect width={50} height={14} /><text x={25} y={10.5} textAnchor="middle">inferred</text></g>
          </g>); })}</g>
        <g>{ids.map((id) => { const [x, y] = xy(id); const on = id === focus; return (
          <g key={id} className={`g-node${on ? " is-focus" : ""}`} transform={`translate(${x},${y})`} tabIndex={0} role="button" aria-pressed={on} aria-label={`Dataset ${id}${on ? ", focused" : ""}`} data-node={id}
            onClick={() => setFocus(on ? "" : id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setFocus(on ? "" : id); } }}>
            <rect width={NW} height={NH} rx={2} /><text x={8} y={16}>{id}</text>
          </g>); })}</g>
      </svg>
    </div>
  );
}

function Legend() {
  return (
    <ul className="legend" data-testid="legend" aria-label="Edge styles">
      <li><svg viewBox="0 0 72 12" aria-hidden="true"><path d="M2 6h68" className="e-declared" /></svg><span><strong>Declared</strong>: a thin solid line. Stated in the register by an owner.</span></li>
      <li><svg viewBox="0 0 72 12" aria-hidden="true"><path d="M2 6h68" className="e-observed" /></svg><span><strong>Observed</strong>: a thick solid line. Seen in the data with an observation time. A diamond marks an observed edge with no declared counterpart.</span></li>
      <li><svg viewBox="0 0 72 12" aria-hidden="true"><path d="M2 6h68" className="e-inferred" /></svg><span><strong>Inferred</strong>: a dashed line, labelled “inferred”. A guess; never styled as observed and never counted as observed.</span></li>
    </ul>
  );
}

function Lineage({ ds }: { ds: Dataset }) {
  const pairs = pairsOf(ds);
  const [k, setK] = useParam("kinds", KINDS.join(","));
  const kinds = new Set(k.split(",").filter((x): x is Kind => (KINDS as string[]).includes(x)));
  const [focus, setFocus] = useParam("focus", "");
  const l = ds.now.metrics["lineage_coverage"] as Row;
  const toggle = (x: Kind): void => { const n = new Set(kinds); if (n.has(x)) n.delete(x); else n.add(x); setK(KINDS.filter((y) => n.has(y)).join(",") || "none"); };
  const fp = focus ? pairs.filter((p) => p.source === focus || p.target === focus) : [];
  const nm = (id: string): string => (ds.byId.datasets.get(id)?.["dataset_name"] as string | undefined) ?? id;
  const list = (title: string, items: Row[], note: string, id: string) => (
    <div className="block" data-testid={id}>
      <h3>{title} ({items.length})</h3>
      <p className="muted">{note}</p>
      {items.length > 0 && <Scroll label={title}><table><thead><tr><th scope="col">Source</th><th scope="col">Target</th><th scope="col">Evidence</th></tr></thead>
        <tbody>{items.map((e) => { const p = pairs.find((x) => x.source === e["source_dataset_id"] && x.target === e["target_dataset_id"])!; return (
          <tr key={`${e["source_dataset_id"]}${e["target_dataset_id"]}`}><td className="mono">{e["source_dataset_id"]}</td><td className="mono">{e["target_dataset_id"]}</td>
            <td>{[p.declared && "declared", p.observed && `observed ${p.observations}× (last ${p.last ? dayTime(p.last) : "?"})`, p.inferred && "inferred"].filter(Boolean).join("; ")}</td></tr>); })}</tbody></table></Scroll>}
    </div>
  );
  return (
    <>
      <section className="block" data-testid="coverage" aria-labelledby="cov">
        <h2 id="cov">Observed lineage coverage</h2>
        <div className="pair-fig">
          <div><span className="big"><Fig k="lineage-coverage">{l["value"]}</Fig></span><span className="cap">{l["observed_matching_declared"]} of {l["declared_edges"]} declared edges were observed, counted over <Def term="distinct pairs">Observed lineage counts distinct (source, target) pairs: repeat observations add nothing. An inferred edge is never part of the observed numerator.</Def></span></div>
          <div><span className="big"><Fig k="observed-distinct">{l["observed_distinct"]}</Fig></span><span className="cap">distinct observed pairs ({l["observed_rows"]} observation rows)</span></div>
          <div><span className="big"><Fig k="undeclared">{(l["undeclared_observed"] as unknown[]).length}</Fig></span><span className="cap">observed with no declared edge</span></div>
          <div><span className="big"><Fig k="inferred">{(l["inferred_edges"] as unknown[]).length}</Fig></span><span className="cap">inferred, kept apart</span></div>
        </div>
      </section>
      <section className="block" aria-labelledby="gr">
        <h2 id="gr">The graph</h2>
        <Legend />
        <fieldset className="picker" data-testid="kind-toggles"><legend>Show edges</legend>
          <div className="picker__row">{KINDS.map((x) => <label key={x} className={`picker__opt${kinds.has(x) ? " is-on" : ""}`}><input type="checkbox" checked={kinds.has(x)} onChange={() => toggle(x)} /><span>{x}</span></label>)}</div>
        </fieldset>
        <p className="muted">Datasets are placed left to right from sources to consumers. Select a dataset (click or Enter) to isolate its edges.</p>
        <Graph ds={ds} pairs={pairs} kinds={kinds} focus={focus} setFocus={setFocus} />
        {focus && <div className="callout" data-testid="focus-panel"><strong className="mono">{focus}</strong> ({nm(focus)}): {fp.filter((p) => p.target === focus).length} upstream and {fp.filter((p) => p.source === focus).length} downstream pairs.
          <ul>{fp.map((p) => <li key={`${p.source}${p.target}`}><span className="mono">{p.source} → {p.target}</span> {p.declared && <Chip kind="ok">declared</Chip>} {p.observed && <Chip kind="note">observed</Chip>} {p.inferred && <Chip kind="hatch">inferred</Chip>}</li>)}</ul></div>}
      </section>
      <section aria-labelledby="lists">
        <h2 id="lists">Where the three kinds disagree</h2>
        {list("Observed, not declared", l["undeclared_observed"], "Seen in the data but absent from the register: the register is missing a dependency, or the observation is wrong.", "undeclared")}
        {list("Declared, not observed", l["declared_not_observed"], "Stated in the register but never seen: unused, or not yet observable. These are the denominator that coverage misses.", "unobserved")}
        {list("Inferred", l["inferred_edges"], "Guessed from naming and shape, never observed. An inferred edge on a declared pair does not make that pair observed.", "inferred-list")}
      </section>
    </>
  );
}

export function LineageView() {
  return (
    <>
      <ViewHead mark="Shelfmark 06 · lineage" title="Lineage explorer">
        <p className="lede">Who feeds whom. Three kinds of evidence are drawn and counted separately because they mean different things: what the register says, what was seen, and what was only guessed.</p>
      </ViewHead>
      <WithData>{(ds) => <Lineage ds={ds} />}</WithData>
    </>
  );
}
