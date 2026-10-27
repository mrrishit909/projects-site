import { useState } from "react";
import { Link } from "../components/link";
import { Chip, Def, NotBuilt, Scroll, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { canonicalJson, planHash } from "../domain/models";
import { isoZ } from "../domain/time";
import { short } from "../lib/format";
import { isFinal } from "../lib/pick";
import { addDraft, useDrafts } from "../state/sim";

const SPLITS: Record<string, string> = { "0.500000": "0.500000", "0.600000": "0.400000", "0.700000": "0.300000" };
function Draft({ ds }: { ds: Dataset }) {
  const drafts = useDrafts();
  const [id, setId] = useState("xv-003");
  const [share, setShare] = useState("0.500000");
  const base = ds.plans.get(ds.versions[ds.versions.length - 1]!.experiment_version_id)!;
  const valid = /^[a-z][a-z0-9-]{2,31}$/.test(id);
  function freeze(): void {
    const treatment = SPLITS[share]!;
    const body = { ...base.body, experiment_version_id: id, allocation: { control: share, treatment }, frozen_at: "(simulated)" };
    addDraft({ experiment_version_id: id, control_share: share, config_hash: planHash(body), body: canonicalJson(body) });
  }
  return (
    <section className="block" data-testid="draft" aria-labelledby="draft-h">
      <h2 id="draft-h">Draft a plan <Chip v="simulated">simulated</Chip></h2>
      <p className="muted">Freezing a plan fixes its configuration before any outcome is read, and its <span className="mono">config_hash</span> is the sha-256 of the plan's key-sorted compact JSON. Here you can see the hash change with the plan. Nothing is stored or registered: the draft lives in this browser's memory only.</p>
      <div className="form">
        <label><span>Version id</span><input type="text" value={id} onChange={(e) => setId(e.target.value)} aria-invalid={!valid} /></label>
        <label><span>Control share (treatment gets the rest)</span>
          <select value={share} onChange={(e) => setShare(e.target.value)}>{Object.keys(SPLITS).map((k) => <option key={k} value={k}>{k}</option>)}</select></label>
        <button type="button" disabled={!valid} onClick={freeze}>Freeze this plan (simulated)</button>
      </div>
      {drafts.length > 0 && (
        <Scroll label="Simulated drafts">
          <table data-testid="drafts"><thead><tr><th scope="col">#</th><th scope="col">Version</th><th scope="col">Control share</th><th scope="col">config_hash (sha-256, computed here)</th></tr></thead>
            <tbody>{drafts.map((d) => <tr key={d.n}><td className="mono">{d.n}</td><td className="mono">{d.experiment_version_id}</td><td className="mono">{d.control_share}</td><td className="mono" title={d.body}>{short(d.config_hash, 24)}</td></tr>)}</tbody></table>
        </Scroll>
      )}
    </section>
  );
}

function Experiments({ ds }: { ds: Dataset }) {
  return (
    <>
      <ViewHead eyebrow="Experiment registry" title="Versions, frozen plans and every run">
        <p className="lede">Each experiment version has one plan, frozen before any outcome is read. Every analysis run is logged and cites the plan's hash; the count of prior runs is shown with every result, because looking early and often changes what a "significant" result means.</p>
      </ViewHead>
      <section className="block" data-testid="versions" aria-labelledby="v">
        <h2 id="v">Versions and plans</h2>
        <Scroll label="Versions">
          <table>
            <thead><tr><th scope="col">Version</th><th scope="col">Name</th><th scope="col">Unit</th><th scope="col">Primary metric</th><th scope="col">Allocation</th><th scope="col">Frozen</th><th scope="col">Planned end</th><th scope="col">config_hash</th><th scope="col">Hash recomputed</th></tr></thead>
            <tbody>{ds.versions.map((v) => { const p = ds.plans.get(v.experiment_version_id); return (
              <tr key={v.experiment_version_id} data-version={v.experiment_version_id}>
                <th scope="row" className="mono">{v.experiment_version_id}</th><td>{v.name}</td><td>{v.unit_type}</td><td className="mono">{v.primary_metric}</td>
                <td className="mono">{p ? p.variants.map((x) => `${x} ${p.allocation[x]}`).join(" / ") : "no plan"}</td><td className="mono">{p ? isoZ(p.frozen_at) : "not frozen"}</td><td className="mono">{isoZ(v.planned_end)}</td>
                <td className="mono" title={p?.config_hash}>{p ? short(p.config_hash, 16) : "n/a"}</td><td>{p ? (p.hash_valid ? <Chip v="OK">matches</Chip> : <Chip v="MISMATCH">differs</Chip>) : "n/a"}</td>
              </tr>); })}</tbody>
          </table>
        </Scroll>
        <p className="muted"><Def term="what a plan fixes">The primary outcome (activation within 7 days), the guardrail (product error rate, 7 days), the horizon (planned end), the allocation, the confidence (0.95, z = 1.959964), the sample ratio thresholds and the revenue window. A run before the freeze is refused; a plan is never edited.</Def></p>
      </section>
      <section className="block" data-testid="runs" aria-labelledby="r">
        <h2 id="r">Analysis runs</h2>
        <Scroll label="Analysis runs">
          <table>
            <thead><tr><th scope="col">Run</th><th scope="col">Version</th><th scope="col">Cutoff</th><th scope="col">Created</th><th scope="col">Label</th><th scope="col" className="num">Prior runs</th><th scope="col">Cites the plan's hash</th><th scope="col">Result</th></tr></thead>
            <tbody>{ds.runs.map((r) => { const ex = ds.at(r.cutoff_at, r.experiment_version_id, r.analysis_id).metrics.experiment!; return (
              <tr key={r.analysis_id} data-run={r.analysis_id}>
                <th scope="row" className="mono">{r.analysis_id}</th><td className="mono">{r.experiment_version_id}</td><td className="mono">{isoZ(r.cutoff_at)}</td><td className="mono">{isoZ(r.created_at)}</td>
                <td><Chip v={isFinal(ds, r) ? "final" : "interim"}>{isFinal(ds, r) ? "final" : "interim"}</Chip></td><td className="num mono" data-k="prior">{ex.run.prior_runs}</td>
                <td>{ex.run.config_hash_matches_plan ? <Chip v="OK">yes</Chip> : <Chip v="MISMATCH">no</Chip>}</td>
                <td><Link to={`result?run=${r.analysis_id}`}>{ex.srm.verdict === "MISMATCH" ? "SRM MISMATCH" : ex.primary.conclusive ? "conclusive" : "not conclusive"}</Link></td>
              </tr>); })}</tbody>
          </table>
        </Scroll>
        <p className="muted">Runs are created 5 minutes after their cutoff. In the snapshot, version 1 has three interim runs and a final one; an interim run can never support a ship decision.</p>
      </section>
      <Draft ds={ds} />
      <NotBuilt>Registering a real version, assigning accounts, logging a run, and the audit trail of the API (Mode A). The registry here is the published data, read-only, plus the in-memory plan draft above.</NotBuilt>
    </>
  );
}
export function ExperimentsView() { return <WithData>{(ds) => <Experiments ds={ds} />}</WithData>; }
