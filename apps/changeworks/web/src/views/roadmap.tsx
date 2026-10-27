import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Chip, PlateHead, Scroll, SimNote, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { DEPENDENCY_TYPES } from "../domain/contract";
import { cmp, dec, ge } from "../domain/num";
import { basisPoints } from "../lib/scale";
import { useParam } from "../router";
import { buildRoadmap, validatorWith, type RoadItem, type RoadModel } from "../lib/roadmap";
import { logRoadmap, resetRoadmap, updateRoadmap, useRoadmapEdits, type RoadmapEdits } from "../state/sim";

export function RoadmapView() { return <WithData>{(ds) => <Roadmap ds={ds} />}</WithData>; }

const PX = 22, ROW = 28, LEFT = 190, TOP = 34;

function Roadmap({ ds }: { ds: Dataset }) {
  const edits = useRoadmapEdits();
  const model = buildRoadmap(ds, edits);
  const [sel, setSel] = useParam("initiative", "");
  const selected = model.items.find((i) => i.iid === sel) ?? null;
  const [active, setActive] = useState(0);
  const refs = useRef<(SVGGElement | null)[]>([]);
  const focusNext = useRef(false);
  useEffect(() => { if (focusNext.current) { refs.current[active]?.focus(); focusNext.current = false; } }, [active]);
  const idx = new Map(model.items.map((i, k) => [i.iid, k]));
  const go = (k: number): void => { focusNext.current = true; setActive(Math.max(0, Math.min(model.items.length - 1, k))); };
  function onKey(e: KeyboardEvent, it: RoadItem, k: number): void {
    if (e.key === "ArrowDown") { e.preventDefault(); go(k + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); go(k - 1); }
    else if (e.key === "Home") { e.preventDefault(); go(0); }
    else if (e.key === "End") { e.preventDefault(); go(model.items.length - 1); }
    else if (e.key === "ArrowLeft") { const d = it.prereqs.find((x) => x["dependency_id"] === it.binding) ?? it.prereqs[0]; if (d) { e.preventDefault(); go(idx.get(d["prerequisite_id"])!); } }
    else if (e.key === "ArrowRight") { const d = it.dependents[0]; if (d) { e.preventDefault(); go(idx.get(d["initiative_id"])!); } }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(it.iid); }
  }
  const W = LEFT + model.periods * PX + 20, H = TOP + model.items.length * ROW + 10;
  const x = (p: number): number => LEFT + p * PX;
  const y = (k: number): number => TOP + k * ROW;
  const delayed = model.items.filter((i) => i.delay > 0);
  return (
    <>
      <PlateHead mark="Plate V" title="Roadmap">
        <p className="lede">Initiatives as bars on periods. A dashed outline is the start that was asked for; the solid bar is the earliest start the dependencies allow. Arrows run from what must happen first to what waits for it. Below, the shared resources by period against their capacity.</p>
      </PlateHead>
      <p className="small muted" data-testid="roadmap-help">Keyboard: Tab to the chart, then Up and Down move between initiatives, Left goes to the prerequisite that binds, Right to the first initiative that waits, Home and End to the ends, Enter selects. A table with the same figures follows the chart.</p>
      <dl className="facts" data-testid="roadmap-facts">
        <div><dt>Initiatives</dt><dd data-figure="initiatives">{model.items.length}</dd></div>
        <div><dt>Dependencies</dt><dd data-figure="dependencies">{model.deps.length}</dd></div>
        <div><dt>Delayed by a dependency</dt><dd data-figure="delayed">{delayed.length}</dd></div>
        <div><dt>Longest delay (periods)</dt><dd data-figure="max-delay">{Math.max(0, ...model.items.map((i) => i.delay))}</dd></div>
      </dl>
      <div className="legend" aria-hidden="true"><span><i className="sw sw--ben" />feasible window</span><span><i className="sw sw--beside" />requested start (dashed outline), drawn only when a dependency delays the initiative</span><span><i className="sw sw--cost" />bar delayed by a dependency</span></div>
      <Scroll label="Roadmap chart">
        <svg className="plate-svg" role="group" aria-label="Roadmap: initiatives on periods with dependency arrows" width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ width: W, maxWidth: "none" }} data-testid="roadmap-chart">
          <defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="#7d6236" /></marker></defs>
          {Array.from({ length: model.periods + 1 }, (_, p) => (
            <g key={p}><line className="grid" x1={x(p)} x2={x(p)} y1={TOP - 6} y2={H - 10} />{p < model.periods && p % 2 === 0 && <text x={x(p) + 2} y={TOP - 12} fontSize="10" className="mono">{p}</text>}</g>
          ))}
          <text x={4} y={14} fontSize="11" fontWeight="700">Period (index from 0)</text>
          {model.deps.map((d) => {
            const a = idx.get(d["prerequisite_id"]), b = idx.get(d["initiative_id"]);
            if (a === undefined || b === undefined) return null;
            const pre = model.items[a]!, suc = model.items[b]!;
            const x1 = d["dependency_type"] === "finish_to_start" ? x(pre.finish) : x(pre.feasible), y1 = y(a) + 9, x2 = x(suc.feasible), y2 = y(b) + 9;
            const xm = Math.max(x1 + 5, Math.min(x2 - 5, (x1 + x2) / 2));
            return <path key={d["dependency_id"]} className={`dep${d["dependency_type"] === "start_to_start" ? " dep--ss" : ""}`} d={`M${x1} ${y1} H${xm} V${y2} H${x2 - 1}`} markerEnd="url(#arr)" data-dep={d["dependency_id"]}><title>{`${d["dependency_id"]}: ${d["prerequisite_id"]} → ${d["initiative_id"]}, ${d["dependency_type"]}, lag ${d["lag_periods"]}`}</title></path>;
          })}
          {model.items.map((it, k) => (
            <g key={it.iid} ref={(el) => { refs.current[k] = el; }} role="button" tabIndex={k === active ? 0 : -1} data-initiative={it.iid} data-active={k === active ? "true" : "false"} aria-pressed={sel === it.iid}
              aria-label={`${it.iid} ${it.title}: requested start ${it.requested}, feasible start ${it.feasible}, delay ${it.delay} periods, duration ${it.duration}${it.binding ? `, bound by ${it.binding}` : ""}`}
              className={sel === it.iid ? "row-sel" : undefined} onKeyDown={(e) => onKey(e, it, k)} onClick={() => { setActive(k); setSel(it.iid); }} onFocus={() => setActive(k)} style={{ cursor: "pointer" }}>
              <rect className="focus-ring" x={2} y={y(k) - 2} width={W - 6} height={ROW - 2} rx={2} />
              <text x={6} y={y(k) + 14} fontSize="11"><tspan className="mono">{it.iid}</tspan> {it.title.length > 17 ? `${it.title.slice(0, 16)}…` : it.title}</text>
              {it.delay > 0 && <rect className="ghost" x={x(it.requested)} y={y(k) + 2} width={it.duration * PX} height={14} />}
              <rect className={`bar${it.delay > 0 ? " bar--delay" : ""}`} x={x(it.feasible)} y={y(k) + 2} width={it.duration * PX} height={14} rx={2} />
              {it.delay > 0 && <text x={x(it.feasible) + it.duration * PX + 4} y={y(k) + 14} fontSize="10" className="mono">+{it.delay}</text>}
            </g>
          ))}
        </svg>
      </Scroll>
      {selected && <Detail it={selected} model={model} />}
      <section aria-labelledby="h-lanes">
        <h2 id="h-lanes">Resource lanes</h2>
        <p className="small muted">Each lane is one shared resource: bars are what is allocated in a period, the dashed line is its capacity. A bar that reaches the line is at capacity (allowed); one request more would be refused and is marked with a cross. Allocation is checked at entry, so no stored allocation exceeds capacity.</p>
        <Lanes model={model} W={W} />
        <Scroll label="Resource conflicts">
          <table data-testid="resource-table">
            <caption>Resources: capacity, periods at capacity, refused requests</caption>
            <thead><tr><th>Resource</th><th className="num">Capacity</th><th>Unit</th><th>Periods at capacity</th><th>Stored over capacity</th><th>Refused requests</th></tr></thead>
            <tbody>{Object.entries(model.resources).map(([rid, r]) => {
              const rr = r as Row;
              const full = (rr["by_period"] as Row[]).filter((b) => b["headroom"] === "0.00").map((b) => b["period_index"]);
              const ref = model.refused.filter((q) => q.resource_id === rid);
              return <tr key={rid} data-resource={rid}><th scope="row">{rid} <span className="muted small">{ds.byId.resources.get(rid)?.["name"]}</span></th><td className="num">{rr["capacity_per_period"]}</td><td>{rr["unit"]}</td>
                <td data-k="full">{full.length ? full.join(", ") : "none"}</td><td data-k="over">{(rr["overallocated_periods"] as number[]).length ? <span className="refused">{(rr["overallocated_periods"] as number[]).join(", ")}</span> : "none"}</td>
                <td data-k="refused">{ref.length ? ref.map((q) => `period ${q.period} (${q.requested} requested, ${q.source})`).join("; ") : "none"}</td></tr>;
            })}</tbody>
          </table>
        </Scroll>
      </section>
      <section aria-labelledby="h-tab">
        <h2 id="h-tab">Feasible starts and delays</h2>
        <Scroll label="Feasible starts table">
          <table data-testid="roadmap-table">
            <caption>Requested and feasible starts, in periods</caption>
            <thead><tr><th>Initiative</th><th className="num">Requested</th><th className="num">Duration</th><th className="num">Feasible start</th><th className="num">Dependency delay</th><th>Binding dependency</th><th>Prerequisites</th><th className="num">Finish</th><th className="num">Resource delay</th></tr></thead>
            <tbody>{[...model.items].sort((a, b) => cmp(a.iid, b.iid)).map((it) => (
              <tr key={it.iid} data-initiative={it.iid} className={sel === it.iid ? "is-on" : undefined}>
                <th scope="row" className="wrapcell"><button type="button" className="button--quiet" onClick={() => setSel(it.iid)} aria-label={`Select ${it.iid}`}>{it.iid}</button> <span className="small muted">{it.title}</span></th>
                <td className="num">{it.requested}</td><td className="num">{it.duration}</td><td className="num" data-k="feasible">{it.feasible}</td><td className="num" data-k="delay">{it.delay}</td>
                <td data-k="binding">{it.binding ?? "none"}</td><td className="wrapcell small">{it.prereqs.map((d) => `${d["prerequisite_id"]} (${d["dependency_type"] === "finish_to_start" ? "FS" : "SS"}+${d["lag_periods"]})`).join(", ") || "none"}</td>
                <td className="num">{it.finish}</td><td className="num">0</td>
              </tr>))}</tbody>
          </table>
        </Scroll>
        <p className="small muted">Feasible start = the latest of the requested start and every prerequisite's constraint (finish-to-start: its feasible start + duration + lag; start-to-start: its feasible start + lag), propagated along the chain. Delay is never negative. Resource constraints are reported separately; resource levelling is not implemented, so the resource delay is 0 and an overallocation can only be refused. The roadmap does not re-time the cash flows.</p>
      </section>
      <Edits ds={ds} model={model} edits={edits} sel={selected?.iid ?? null} />
    </>
  );
}

function Detail({ it, model }: { it: RoadItem; model: RoadModel }) {
  const allocs = model.allocations.filter((a) => a["initiative_id"] === it.iid);
  return (
    <section className="callout" data-testid="roadmap-detail" aria-label={`Selected initiative ${it.iid}`}>
      <h3 style={{ marginTop: 0 }}>{it.iid} {it.title}</h3>
      <p>Requested start {it.requested}; feasible start <strong>{it.feasible}</strong>; dependency delay <strong>{it.delay}</strong> period{it.delay === 1 ? "" : "s"}{it.binding ? `, set by ${it.binding}` : ""}; finishes at {it.finish}.</p>
      <p className="small">Waits for: {it.prereqs.map((d) => `${d["prerequisite_id"]} (${d["dependency_type"]}, lag ${d["lag_periods"]})`).join("; ") || "nothing"}. Others wait for it: {it.dependents.map((d) => d["initiative_id"]).join(", ") || "nobody"}. Allocation rows: {allocs.length}.</p>
    </section>
  );
}

function Lanes({ model, W }: { model: RoadModel; W: number }) {
  const rids = Object.keys(model.resources);
  const LH = 44;
  const Hh = 22 + rids.length * LH;
  return (
    <Scroll label="Resource lanes chart">
      <svg className="plate-svg" role="img" aria-label={`Resource lanes: allocation by period against capacity for ${rids.length} resources`} width={W} height={Hh} viewBox={`0 0 ${W} ${Hh}`} style={{ width: W, maxWidth: "none" }} data-testid="lanes-chart">
        {Array.from({ length: model.periods + 1 }, (_, p) => <line key={p} className="grid" x1={LEFT + p * PX} x2={LEFT + p * PX} y1={14} y2={Hh - 4} />)}
        {rids.map((rid, k) => {
          const r = model.resources[rid] as Row;
          const cap = dec(r["capacity_per_period"]);
          const top = 20 + k * LH;
          return (
            <g key={rid} data-lane={rid}>
              <text x={6} y={top + 20} fontSize="11"><tspan className="mono">{rid}</tspan> cap {r["capacity_per_period"]}</text>
              <line className="cap" x1={LEFT} x2={LEFT + model.periods * PX} y1={top} y2={top} style={{ stroke: "#7d6236" }} />
              {(r["by_period"] as Row[]).map((b) => {
                const h = Math.max(1, Math.round((basisPoints(dec(b["allocated"]), cap) * 32) / 10000));
                const full = b["headroom"] === "0.00", over = !ge(cap, dec(b["allocated"]));
                return <rect key={b["period_index"]} x={LEFT + b["period_index"] * PX + 2} y={top + 34 - h} width={PX - 4} height={h} className={over ? "over" : "bar"} style={full && !over ? { fill: "#7d6236" } : undefined}><title>{`${rid} period ${b["period_index"]}: ${b["allocated"]} of ${r["capacity_per_period"]}${full ? " (at capacity)" : ""}`}</title></rect>;
              })}
              {model.refused.filter((q) => q.resource_id === rid).map((q) => <text key={q.period + q.requested} x={LEFT + q.period * PX + 4} y={top + 14} fontSize="13" fill="#9e3b2f" fontWeight="700">×<title>{`refused: ${q.requested} requested in period ${q.period}`}</title></text>)}
            </g>
          );
        })}
      </svg>
    </Scroll>
  );
}

function Edits({ ds, model, edits, sel }: { ds: Dataset; model: RoadModel; edits: RoadmapEdits; sel: string | null }) {
  const ids = model.items.map((i) => i.iid).sort(cmp);
  const [a, setA] = useState("init-001"), [b, setB] = useState("init-002"), [type, setType] = useState<string>("finish_to_start"), [lag, setLag] = useState("0");
  const [res, setRes] = useState(Object.keys(model.resources)[0] ?? ""), [ai, setAi] = useState(ids[0] ?? ""), [per, setPer] = useState("14"), [amt, setAmt] = useState("0.50");
  const shift = (d: number): void => { if (!sel) return; updateRoadmap((e) => logRoadmap({ ...e, shifts: { ...e.shifts, [sel]: (e.shifts[sel] ?? 0) + d } }, `requested start of ${sel} moved by ${d > 0 ? "+" : ""}${d} period`, false)); };
  function addDep(): void {
    const row = { dependency_id: `sim-d-${edits.deps.length + 1}`, initiative_id: a, prerequisite_id: b, dependency_type: type, lag_periods: Number(lag) };
    const rej = validatorWith(ds, edits).check("dependencies", row);
    updateRoadmap((e) => rej ? logRoadmap(e, `dependency ${a} after ${b} refused ${rej.reason_code}${rej.details["cycle"] ? `: ${(rej.details["cycle"] as string[]).join(" → ")}` : ""}`, true) : logRoadmap({ ...e, deps: [...e.deps, row] }, `dependency ${a} after ${b} (${type}, lag ${lag}) accepted`, false));
  }
  function addAlloc(): void {
    const row = { allocation_id: `sim-al-${edits.allocations.length + 1}`, resource_id: res, initiative_id: ai, period_index: Number(per), amount: amt };
    const rej = validatorWith(ds, edits).check("resource_allocations", row);
    updateRoadmap((e) => rej ? logRoadmap(e, `allocation of ${amt} ${res} to ${ai} in period ${per} refused ${rej.reason_code}${rej.details["capacity"] ? ` (${rej.details["allocated_before"]} of ${rej.details["capacity"]} already allocated)` : ""}`, true) : logRoadmap({ ...e, allocations: [...e.allocations, row] }, `allocation of ${amt} ${res} to ${ai} in period ${per} accepted`, false));
  }
  return (
    <section aria-labelledby="h-edit" data-testid="roadmap-edits">
      <h2 id="h-edit">Try an edit (simulation)</h2>
      <SimNote>These edits change the chart above and nothing else. Each is checked by the same validator the import uses, so a cycle or an overallocation is refused with its reason. Reload to return to the published roadmap.</SimNote>
      <div className="controls">
        <p style={{ margin: 0 }}>Selected: <strong>{sel ?? "none (select a bar or a row)"}</strong></p>
        <button type="button" disabled={!sel} onClick={() => shift(-1)} data-testid="shift-earlier">Request start 1 period earlier</button>
        <button type="button" disabled={!sel} onClick={() => shift(1)} data-testid="shift-later">Request start 1 period later</button>
      </div>
      <form className="controls" onSubmit={(e) => { e.preventDefault(); addDep(); }} aria-label="Add a dependency" data-testid="dep-form">
        <label>Initiative<select value={a} onChange={(e) => setA(e.target.value)} data-testid="dep-initiative">{ids.map((i) => <option key={i}>{i}</option>)}</select></label>
        <label>waits for<select value={b} onChange={(e) => setB(e.target.value)} data-testid="dep-prereq">{ids.map((i) => <option key={i}>{i}</option>)}</select></label>
        <label>Type<select value={type} onChange={(e) => setType(e.target.value)}>{DEPENDENCY_TYPES.map((t) => <option key={t}>{t}</option>)}</select></label>
        <label>Lag<input type="number" min={0} value={lag} onChange={(e) => setLag(e.target.value)} style={{ width: "5rem" }} /></label>
        <button type="submit" data-testid="dep-add">Add dependency</button>
      </form>
      <form className="controls" onSubmit={(e) => { e.preventDefault(); addAlloc(); }} aria-label="Request an allocation" data-testid="alloc-form">
        <label>Resource<select value={res} onChange={(e) => setRes(e.target.value)} data-testid="alloc-resource">{Object.keys(model.resources).map((r) => <option key={r}>{r}</option>)}</select></label>
        <label>Initiative<select value={ai} onChange={(e) => setAi(e.target.value)}>{ids.map((i) => <option key={i}>{i}</option>)}</select></label>
        <label>Period<input type="number" min={0} value={per} onChange={(e) => setPer(e.target.value)} style={{ width: "5rem" }} data-testid="alloc-period" /></label>
        <label>Amount<input type="text" value={amt} onChange={(e) => setAmt(e.target.value)} style={{ width: "5rem" }} data-testid="alloc-amount" /></label>
        <button type="submit" data-testid="alloc-add">Request allocation</button>
      </form>
      <button type="button" className="button--quiet" onClick={resetRoadmap} data-testid="roadmap-reset">Reset the edits</button>
      <ol data-testid="edit-log" aria-live="polite">{edits.log.length === 0 ? <li className="muted">No edits in this session.</li> : edits.log.map((l) => <li key={l.n}>{l.refused ? <Chip kind="crit">refused</Chip> : <Chip kind="ok">applied (simulated)</Chip>} {l.text}</li>)}</ol>
    </section>
  );
}
