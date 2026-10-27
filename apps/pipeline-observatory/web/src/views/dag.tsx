import { useMemo, useRef, type KeyboardEvent } from "react";
import { Meaning, Panel, Scroll, ScopeTag, Status, ViewHead, WithData } from "../components/ui";
import { Link } from "../components/link";
import type { Dataset } from "../data/analyse";
import type { GNode } from "../domain/graph";
import { cmpFr, fr, ratio } from "../domain/num";
import type { FreshnessRow } from "../domain/world";
import { runsOf } from "../lib/derive";
import { dur } from "../lib/format";
import { useParam } from "../router";

const NW = 158, NH = 62, GX = 56, GY = 16, PADX = 14, PADY = 14;
const LAYER_LABEL: Record<string, string> = { source: "Sources", staging: "Staging", intermediate: "Intermediate", marts: "Marts", publication: "Publication" };
interface NodeInfo { node: GNode; fresh: FreshnessRow | null; viaSource: string | null; job: { tone: "ok" | "bad" | "idle"; text: string }; ratioText: string | null; fill: number }

function describe(ds: Dataset): Map<string, NodeInfo> {
  const g = ds.graph;
  const runs = runsOf(ds);
  const last = runs[runs.length - 1];
  const taskFinal = (name: string): { status: string; attempts: number } | null => {
    if (!last) return null;
    const mine = ds.acc["task_runs"]!.filter((t) => t["run_id"] === last["run_id"] && t["task_name"] === name).sort((a, b) => Number(a["attempt"]) - Number(b["attempt"]));
    return mine.length ? { status: mine[mine.length - 1]!["status"], attempts: mine.length } : null;
  };
  const bySource = new Map(ds.freshness.map((f) => [f.source_id, f]));
  const out = new Map<string, NodeInfo>();
  for (const n of g.nodes) {
    let fresh: FreshnessRow | null = null, via: string | null = null;
    if (n.kind === "source") { fresh = bySource.get(n.id) ?? null; via = n.id; }
    else {
      for (const u of g.upstream(n.id)) { const f = bySource.get(u); if (f && f.freshness_seconds !== null && (fresh === null || f.freshness_seconds > (fresh.freshness_seconds ?? -1))) { fresh = f; via = u; } }
    }
    let job: NodeInfo["job"];
    if (n.kind === "source") job = fresh?.last_batch ? { tone: fresh.last_batch.status === "committed" ? "ok" : "bad", text: `last batch ${fresh.last_batch.status}` } : { tone: "idle", text: "no batch" };
    else {
      const t = taskFinal(n.kind === "publication" ? "publish" : "transform");
      job = t ? { tone: t.status === "success" ? "ok" : "bad", text: `${n.kind === "publication" ? "publish" : "transform"} ${t.status} in ${last!["run_id"]}` } : { tone: "idle", text: "no task recorded" };
    }
    // the bar is the share of the node's own target used up (a model or publication shows its stalest source's share); capped at the full width
    let ratioText: string | null = null, fill = 0;
    if (fresh && fresh.freshness_seconds !== null && fresh.target_seconds) {
      const r = ratio(fresh.freshness_seconds, fresh.target_seconds)!;
      ratioText = `${fresh.freshness_seconds} of ${fresh.target_seconds} s`;
      fill = cmpFr(r, fr(1)) >= 0 ? 1 : Number(r.n * 1000n / r.d) / 1000;
    } else if (fresh && fresh.freshness_seconds !== null && fresh.cadence_seconds) {
      const r = ratio(fresh.freshness_seconds, fresh.cadence_seconds * 4)!;
      fill = cmpFr(r, fr(1)) >= 0 ? 1 : Number(r.n * 1000n / r.d) / 1000;
    }
    out.set(n.id, { node: n, fresh, viaSource: via, job, ratioText, fill });
  }
  return out;
}
const pos = (n: GNode): { x: number; y: number } => ({ x: PADX + n.column * (NW + GX), y: PADY + 22 + n.row * (NH + GY) });

function Graph({ ds }: { ds: Dataset }) {
  const g = ds.graph;
  const info = useMemo(() => describe(ds), [ds]);
  const [sel, setSel] = useParam("node", "");
  const svg = useRef<SVGSVGElement>(null);
  const cols = Math.max(...g.nodes.map((n) => n.column)) + 1, rows = Math.max(...g.nodes.map((n) => n.row)) + 1;
  const W = PADX * 2 + cols * NW + (cols - 1) * GX, H = PADY * 2 + 22 + rows * NH + (rows - 1) * GY;
  const closure = sel && g.nodes.some((n) => n.id === sel) ? g.closure(sel) : null;
  const move = (e: KeyboardEvent<SVGGElement>, n: GNode): void => {
    const pick = (dc: number, dr: number): GNode | undefined => {
      const inCol = g.nodes.filter((x) => x.column === n.column + dc);
      if (dc !== 0) return inCol.sort((a, b) => Math.abs(a.row - n.row) - Math.abs(b.row - n.row))[0];
      return g.nodes.find((x) => x.column === n.column && x.row === n.row + dr);
    };
    const key = e.key;
    if (key === "Enter" || key === " ") { e.preventDefault(); setSel(sel === n.id ? "" : n.id); return; }
    if (key === "Escape") { setSel(""); return; }
    const target = key === "ArrowRight" ? pick(1, 0) : key === "ArrowLeft" ? pick(-1, 0) : key === "ArrowDown" ? pick(0, 1) : key === "ArrowUp" ? pick(0, -1) : undefined;
    if (target) { e.preventDefault(); svg.current?.querySelector<SVGGElement>(`[data-node="${CSS.escape(target.id)}"]`)?.focus(); }
  };
  const dim = (id: string): boolean => closure !== null && !closure.has(id);
  const ni = sel ? info.get(sel) : undefined;
  return (
    <>
      <Panel id="graph" title="Sources, models and the publication" scope={ds.id === "snapshot" ? "recorded" : "complete"}>
        <Meaning>
          <strong>Two channels, kept apart.</strong> The bar inside a node is <em>freshness</em>: how much of the node&apos;s freshness target the newest accepted event has used (a model or the publication shows its stalest source). The mark in the corner is the <em>job</em>: the latest batch of a source, or the latest run&apos;s transform / publish task. A node can have a green job and a full amber bar.
          {ds.id === "snapshot" ? " The newest-event instants are the generator's recorded values for the complete world (the raw rows are a sample); ingestion ages are recomputed from checkpoints." : ""}
        </Meaning>
        <p className="graph-help" id="graph-help">Tab to a node; arrow keys move between nodes; Enter or Space isolates it and everything upstream and downstream of it; Escape clears.</p>
        <Scroll label="Dependency graph, scrollable">
          <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="dag" style={{ minWidth: Math.min(W, 760) }} role="group" aria-label="Dependency graph" aria-describedby="graph-help" data-testid="dag">
            <defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" className="dag__arrow" /></marker></defs>
            {Array.from({ length: cols }, (_, c) => {
              const kind = g.nodes.find((n) => n.column === c)?.kind ?? "source";
              return <text key={c} x={PADX + c * (NW + GX)} y={PADY + 8} className="dag__col">{LAYER_LABEL[kind]}</text>;
            })}
            {g.edges.map((e) => {
              const a = g.nodes.find((n) => n.id === e.from)!, b = g.nodes.find((n) => n.id === e.to)!;
              const pa = pos(a), pb = pos(b);
              const x1 = pa.x + NW, y1 = pa.y + NH / 2, x2 = pb.x, y2 = pb.y + NH / 2, mx = (x1 + x2) / 2;
              const on = closure !== null && closure.has(e.from) && closure.has(e.to);
              return <path key={`${e.from}>${e.to}`} d={`M${x1} ${y1}C${mx} ${y1} ${mx} ${y2} ${x2 - 2} ${y2}`} className={`dag__edge${closure === null ? "" : on ? " is-on" : " is-dim"}`} markerEnd="url(#arrow)" data-edge={`${e.from}>${e.to}`} />;
            })}
            {g.nodes.map((n) => {
              const i = info.get(n.id)!, p = pos(n);
              const stale = i.fresh?.silent || i.fresh?.past_target;
              const state = sel === n.id ? "selected" : dim(n.id) ? "dimmed" : closure ? "related" : "normal";
              const label = `${n.label}, ${n.kind}${i.fresh ? `; freshness ${dur(i.fresh.freshness_seconds)}${i.viaSource && i.viaSource !== n.id ? ` inherited from ${i.viaSource}` : ""}${stale ? ", silent" : ""}` : ""}; job: ${i.job.text}`;
              return (
                <g key={n.id} role="button" tabIndex={0} aria-pressed={sel === n.id} aria-label={label} data-node={n.id} data-kind={n.kind} data-state={state} data-stale={stale ? "true" : "false"} data-testid="dag-node"
                  className={`dag__node dag__node--${n.kind} is-${state}`} transform={`translate(${p.x} ${p.y})`} onClick={() => setSel(sel === n.id ? "" : n.id)} onKeyDown={(e) => move(e, n)}>
                  <rect width={NW} height={NH} rx={3} className="dag__box" />
                  <text x={10} y={19} className="dag__name">{n.label.length > 19 ? `${n.label.slice(0, 18)}…` : n.label}</text>
                  <text x={10} y={33} className="dag__kind">{n.kind}{i.viaSource && i.viaSource !== n.id ? ` · via ${i.viaSource.replace("src-", "")}` : ""}</text>
                  <rect x={10} y={42} width={NW - 20} height={8} className="dag__track" />
                  <rect x={10} y={42} width={Math.max(i.fresh ? 2 : 0, (NW - 20) * i.fill)} height={8} className={`dag__fill${stale ? " is-stale" : ""}`} data-fill="freshness" />
                  <text x={NW - 10} y={19} textAnchor="end" className={`dag__job dag__job--${i.job.tone}`}>{i.job.tone === "ok" ? "✓" : i.job.tone === "bad" ? "✕" : "○"}</text>
                </g>
              );
            })}
          </svg>
        </Scroll>
        <div className="legend">
          <span><i className="sw sw--f" />freshness bar, within target</span><span><i className="sw sw--h" />silent or past target</span>
          <span><span className="dag__job dag__job--ok" aria-hidden="true">✓</span> job succeeded</span><span><span className="dag__job dag__job--bad" aria-hidden="true">✕</span> job failed</span>
        </div>
      </Panel>

      <Panel id="detail" title={ni ? `Isolated: ${ni.node.label}` : "Select a node to isolate it"}>
        {ni ? (
          <div data-testid="dag-detail">
            <dl className="facts">
              <div><dt>Layer</dt><dd>{ni.node.kind}</dd></div>
              <div><dt>Upstream ({g.upstream(ni.node.id).length})</dt><dd data-k="upstream">{g.upstream(ni.node.id).join(", ") || "none: this is a source"}</dd></div>
              <div><dt>Downstream ({g.downstream(ni.node.id).length})</dt><dd data-k="downstream">{g.downstream(ni.node.id).join(", ") || "none: nothing reads it"}</dd></div>
              <div><dt>Freshness</dt><dd data-k="freshness">{ni.fresh ? `${dur(ni.fresh.freshness_seconds)} (${ni.fresh.freshness_seconds} s)${ni.viaSource !== ni.node.id ? `, inherited from the stalest upstream source ${ni.viaSource}` : ""}${ni.ratioText ? `; ${ni.ratioText} of its target` : ""}` : "not defined for this node"}</dd></div>
              <div><dt>Job</dt><dd data-k="job"><Status tone={ni.job.tone === "ok" ? "ok" : ni.job.tone === "bad" ? "bad" : "idle"}>{ni.job.text}</Status></dd></div>
            </dl>
            <p><button type="button" className="quiet" data-testid="dag-clear" onClick={() => setSel("")}>Clear isolation</button> {ni.node.kind === "source" ? <Link to="sources">Open the source contract</Link> : null}</p>
          </div>
        ) : <p>Nothing is isolated; all {g.nodes.length} nodes and {g.edges.length} edges are shown.</p>}
      </Panel>

      <Panel id="nodes" title="The same graph as a table">
        <Scroll label="Nodes, edges, freshness and job status">
          <table className="data" data-testid="dag-table">
            <caption>{g.nodes.length} nodes, {g.edges.length} edges. Freshness is in whole seconds.</caption>
            <thead><tr><th scope="col">Node</th><th scope="col">Layer</th><th scope="col">Reads from</th><th scope="col">Read by</th><th scope="col">Freshness</th><th scope="col">Job</th></tr></thead>
            <tbody>
              {g.nodes.map((n) => {
                const i = info.get(n.id)!;
                return (
                  <tr key={n.id} data-table-node={n.id}>
                    <th scope="row"><code>{n.label}</code></th><td>{n.kind}</td><td>{g.edges.filter((e) => e.to === n.id).map((e) => e.from).join(", ") || "—"}</td><td>{g.edges.filter((e) => e.from === n.id).map((e) => e.to).join(", ") || "—"}</td>
                    <td>{i.fresh?.freshness_seconds ?? "n/a"}{i.fresh?.freshness_seconds != null ? ` s (${dur(i.fresh.freshness_seconds)})` : ""}{i.viaSource && i.viaSource !== n.id ? ` via ${i.viaSource}` : ""}</td>
                    <td><Status tone={i.job.tone === "ok" ? "ok" : i.job.tone === "bad" ? "bad" : "idle"}>{i.job.text}</Status></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Scroll>
      </Panel>
    </>
  );
}
export function DagView() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="03 · entry screen" title="Dependency graph">
            <p className="lede">Which data feeds which model, and how current each node is. Freshness is drawn on the node itself, so a green job cannot hide a stale source.</p>
          </ViewHead>
          <Graph ds={ds} />
          <p className="meaning">Edges are read from <code>model_definitions</code>: <code>depends_on</code> between models, the <code>source_id</code> named in each staging definition, and the mart that shares the publication&apos;s name. <ScopeTag basis="complete" /> for the structure.</p>
        </>
      )}
    </WithData>
  );
}
