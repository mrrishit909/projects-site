import { Chip, Fig, NotBuilt, Scroll, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { cmp, type Row } from "../domain/models";
import { p6 } from "../domain/num";
import { downstream, scoreRows } from "../lib/derive";
import { dayTime, minus } from "../lib/format";
import { useParam } from "../router";

const ITEMS: [string, string][] = [["definition", "Definition"], ["grain", "Grain"], ["source_fields", "Source fields"], ["owner_id", "Owner"], ["refresh", "Refresh"]];
const text = (v: unknown): string => (v === null || v === undefined || v === "" ? "(blank)" : Array.isArray(v) ? (v.length ? v.join(", ") : "(none)") : String(v));
/** The dataset a source field reads: `orders.amount` reads `ds-orders`. The register has no other link between a metric and a dataset. */
const sourceDatasets = (ds: Dataset, v: Row | undefined): { id: string; known: boolean }[] =>
  [...new Set(((v?.["source_fields"] ?? []) as string[]).map((f) => `ds-${f.split(".")[0]}`))].sort(cmp).map((id) => ({ id, known: ds.byId.datasets.has(id) }));

function Impact({ ds }: { ds: Dataset }) {
  const changes = [...ds.raw.definition_changes].sort((a, b) => cmp(b["changed_at"], a["changed_at"]) || cmp(a["change_id"], b["change_id"]));
  const [id, setId] = useParam("change", changes[0]!["change_id"]);
  const ch = changes.find((c) => c["change_id"] === id) ?? changes[0]!;
  const byVersion = new Map(ds.raw.metric_versions.map((v) => [v["metric_version_id"] as string, v]));
  const after = byVersion.get(ch["metric_version_id"])!, before = ch["previous_metric_version_id"] ? byVersion.get(ch["previous_metric_version_id"]) : undefined;
  const srcAfter = sourceDatasets(ds, after), srcBefore = sourceDatasets(ds, before);
  const affected = [...new Set([...srcAfter, ...srcBefore].map((s) => s.id))].filter((x) => ds.byId.datasets.has(x)).sort(cmp);
  const declared = ds.raw.lineage_edges.filter((e) => e["evidence_type"] === "declared").map((e) => [e["source_dataset_id"], e["target_dataset_id"]] as [string, string]);
  const down = downstream(declared, affected);
  const eff = ds.now.definitions["effective_at_as_of"] as Record<string, string | null>;
  const metrics = Object.entries(eff).filter(([mid, vid]) => mid !== after["metric_id"] && vid && byVersion.get(vid)!["status"] === "published").map(([mid, vid]) => ({ mid, v: byVersion.get(vid!)! }));
  const rows = metrics.map(({ mid, v }) => {
    const src = sourceDatasets(ds, v).map((s) => s.id);
    const direct = src.filter((s) => affected.includes(s));
    const viaDown = src.filter((s) => down.has(s));
    return { mid, v, direct, viaDown, path: viaDown[0] ? down.get(viaDown[0])! : [] };
  }).filter((r) => r.direct.length || r.viaDown.length).sort((a, b) => Number(!!b.direct.length) - Number(!!a.direct.length) || cmp(a.mid, b.mid));
  const name = (oid: string | null): string => (oid ? (ds.byId.owners.get(oid)?.["owner_name"] as string | undefined) ?? oid : "none");
  const movers = scoreRows(ds).filter((r) => r.delta !== null && r.delta.n !== 0n).sort((a, b) => { const x = a.delta!, y = b.delta!; const ax = x.n < 0n ? -x.n : x.n, ay = y.n < 0n ? -y.n : y.n; return ay * x.d > ax * y.d ? 1 : ay * x.d < ax * y.d ? -1 : cmp(a.dataset_id, b.dataset_id); }).slice(0, 8);
  return (
    <>
      <section className="block" aria-labelledby="pick">
        <h2 id="pick">A definition change</h2>
        <label className="field">Change record ({changes.length}, newest first)
          <select value={ch["change_id"]} onChange={(e) => setId(e.target.value)} aria-label="Change record" data-testid="change-picker">
            {changes.map((c) => <option key={c["change_id"]} value={c["change_id"]}>{c["change_id"]} · {byVersion.get(c["metric_version_id"])!["metric_name"]} · {(c["changed_at"] as string).slice(0, 10)}</option>)}
          </select>
        </label>
        <p data-testid="change-summary"><strong>{after["metric_name"]}</strong> changed from v{before ? before["version_number"] : "none"} to v{after["version_number"]} at <span className="mono">{dayTime(ch["changed_at"])}</span>, approved by {name(ch["approved_by"])}: “{ch["reason"]}”. The earlier version stays readable; nothing was rewritten in place.</p>
        <Scroll label="What changed between the versions"><table data-testid="diff">
          <thead><tr><th scope="col">Item</th><th scope="col">Before</th><th scope="col">After</th><th scope="col">Changed</th></tr></thead>
          <tbody>{ITEMS.map(([k, label]) => { const a = before?.[k], b = after[k]; const diff = JSON.stringify(a ?? null) !== JSON.stringify(b ?? null); const show = (v: unknown): string => (k === "owner_id" ? name(v as string | null) : text(v)); return (
            <tr key={k} data-item={k}><th scope="row">{label}</th><td>{before ? show(a) : "(no earlier version)"}</td><td>{show(b)}</td><td data-k="changed">{diff ? <Chip kind="ok">changed</Chip> : <span className="muted">same</span>}</td></tr>); })}</tbody>
        </table></Scroll>
      </section>

      <section className="block" aria-labelledby="reach" data-testid="reach">
        <h2 id="reach">What the change reaches</h2>
        <p>The new definition reads: {srcAfter.map((s, i) => <span key={s.id}>{i ? ", " : ""}<span className="mono">{s.id}</span>{!s.known && " (not in the register)"}</span>)}. Following <strong>declared</strong> lineage downstream from {affected.length === 1 ? "it" : "them"} reaches <Fig k="downstream">{down.size}</Fig> {down.size === 1 ? "dataset" : "datasets"}.</p>
        {down.size > 0 && <Scroll label="Downstream datasets"><table data-testid="downstream">
          <thead><tr><th scope="col">Dataset</th><th scope="col" className="num">Hops</th><th scope="col">Declared path</th></tr></thead>
          <tbody>{[...down.entries()].sort((a, b) => a[1].length - b[1].length || cmp(a[0], b[0])).map(([d, p]) => <tr key={d}><th scope="row" className="mono">{d}</th><td className="num mono">{p.length - 1}</td><td className="mono">{p.join(" → ")}</td></tr>)}</tbody>
        </table></Scroll>}
      </section>

      <section className="block" aria-labelledby="metrics" data-testid="downstream-metrics">
        <h2 id="metrics">Published metrics that read the affected data ({rows.length})</h2>
        <p>Other published metrics whose source fields read an affected dataset, or a dataset downstream of it over declared lineage. Their owners are the people to tell before the change goes out.</p>
        {rows.length === 0 ? <p>No other published metric reads the affected data.</p> : <Scroll label="Downstream metrics"><table>
          <thead><tr><th scope="col">Metric</th><th scope="col">Effective version</th><th scope="col">Owner</th><th scope="col">Reached by</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.mid} data-metric={r.mid}><th scope="row">{r.v["metric_name"]}<br /><span className="mono muted">{r.mid}</span></th><td className="mono">v{r.v["version_number"]}</td>
            <td>{name(r.v["owner_id"])} {r.v["owner_id"] && ds.byId.owners.get(r.v["owner_id"])?.["active"] === false && <Chip kind="hatch">inactive</Chip>}</td>
            <td>{r.direct.length ? <><Chip kind="ok">same data</Chip> reads <span className="mono">{r.direct.join(", ")}</span></> : <><Chip kind="note">downstream</Chip> reads <span className="mono">{r.viaDown[0]}</span> via <span className="mono">{r.path.join(" → ")}</span></>}</td></tr>)}</tbody>
        </table></Scroll>}
        <NotBuilt>The data holds no metric-to-metric dependency and no recomputed metric values. This page lists what a definition change <em>reaches</em> through the source fields and declared lineage; it does not predict whether or by how much any number would move, and it ignores observed and inferred edges.</NotBuilt>
      </section>

      <section className="block" aria-labelledby="wchg" data-testid="weight-change">
        <h2 id="wchg">A change that needs no rule to change: the weight version</h2>
        <p>Re-weighting the five dimensions is also a definition change: the same rows and rules score differently. Largest movers between {ds.weightVersions[0]} and {ds.weightVersions[ds.weightVersions.length - 1]}:</p>
        {movers.length === 0 ? <p>No dataset’s score differs between the weight versions.</p> : <Scroll label="Largest score shifts between weight versions"><table>
          <thead><tr><th scope="col">Dataset</th>{ds.weightVersions.map((v) => <th key={v} scope="col" className="num">{v}</th>)}<th scope="col" className="num">Shift</th></tr></thead>
          <tbody>{movers.map((r) => <tr key={r.dataset_id} data-dataset={r.dataset_id}><th scope="row" className="mono">{r.dataset_id}</th>{ds.weightVersions.map((v) => <td key={v} className="num mono">{r.scores[v] ? p6(r.scores[v]!) : "n/a"}</td>)}<td className="num mono">{minus(p6(r.delta!)!)}</td></tr>)}</tbody>
        </table></Scroll>}
      </section>
    </>
  );
}

export function ImpactView() {
  return (
    <>
      <ViewHead mark="Shelfmark 09 · impact" title="Impact preview">
        <p className="lede">Before a definition changes, see what it touches: which datasets feed it, what sits downstream of them and which other published metrics read the same data.</p>
      </ViewHead>
      <WithData>{(ds) => <Impact ds={ds} />}</WithData>
    </>
  );
}
