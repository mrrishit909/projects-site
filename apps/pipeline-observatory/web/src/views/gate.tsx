import { useMemo, useState } from "react";
import { Link } from "../components/link";
import { Panel, Scroll, SimNote, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import type { Row } from "../domain/contract";
import { gateWhatIf } from "../domain/sim";
import { blockedRunIds, diagnosis, gateOf, runsOf } from "../lib/derive";
import { n0 } from "../lib/format";
import { useParam } from "../router";
import { addSimFault, resetSim, useSimFaults } from "../state/sim";

const RULE_TEXT: Record<string, string> = {
  keys_unique: "No source key appears twice in the candidate table.",
  relationships_intact: "Every output row refers to a row that exists upstream.",
  reconciliation_residual_zero: "Source total minus published total minus the explained exclusions (quarantined, duplicates, deletes) is exactly 0.00.",
  freshness_within_target: "Every source with a declared freshness target is within it.",
  completeness_vs_expectation: "Accepted records against the declared expectation per partition. A warning: reported, never blocks.",
};
function defaultRun(ds: Dataset): string {
  const dr = ds.manifest?.designed_relationships?.find((d) => d["id"] === "DR-02")?.["realised"]?.["run_id"] as string | undefined;
  const blocked = blockedRunIds(ds);
  if (dr && ds.acc["pipeline_runs"]!.some((r) => r["run_id"] === dr)) return dr;
  return blocked.length ? blocked[blocked.length - 1]! : runsOf(ds).slice(-1)[0]?.["run_id"] ?? "";
}
function Lab({ ds, runId }: { ds: Dataset; runId: string }) {
  const results = useMemo(() => {
    const tr = new Set(ds.acc["task_runs"]!.filter((t) => t["run_id"] === runId).map((t) => t["task_run_id"]));
    return ds.acc["quality_results"]!.filter((q) => tr.has(q["task_run_id"]));
  }, [ds, runId]);
  const hist = ds.g.metrics.publications.pointer_history as Row[];
  const hi = hist.findIndex((h) => h["run_id"] === runId);
  const before = hi > 0 ? (hist[hi - 1]!["pointer_after"] as string | null) : null;
  const pub = ds.pubOfRun[runId] ?? null;
  const rules = Object.keys(gateOf(ds, runId)?.results ?? {});
  const [force, setForce] = useState<Record<string, "fail" | "pass">>({});
  const faults = useSimFaults();
  const forced: Record<string, number> = {};
  for (const [rule, v] of Object.entries(force)) forced[rule] = v === "fail" ? 1 : 0;
  const candidate = pub ?? `candidate of ${runId}`;
  const w = gateWhatIf(results, forced, pub !== null, before, candidate);
  const recorded = gateOf(ds, runId)!;
  return (
    <Panel id="lab" title="Fault injection (synthetic sandbox)">
      <SimNote>Force a check to fail or pass and see what the gate and the pointer would do. The published gate result above does not change, and nothing is written.</SimNote>
      <fieldset className="picker" data-testid="fault-controls">
        <legend>Force the checks of {runId}</legend>
        {rules.map((rule) => (
          <label key={rule} className="picker__opt">
            <span><code>{rule}</code> </span>
            <select value={force[rule] ?? ""} data-testid={`fault-${rule}`} onChange={(e) => { const v = e.target.value; setForce((f) => { const n = { ...f }; if (v === "") delete n[rule]; else n[rule] = v as "fail" | "pass"; return n; }); }}>
              <option value="">as recorded</option><option value="fail">force to fail</option><option value="pass">force to pass</option>
            </select>
          </label>
        ))}
      </fieldset>
      <div className="whatif" data-testid="whatif" aria-live="polite">
        <p><strong>Decision with these faults:</strong> <span data-testid="whatif-decision"><Status tone={w.gate.decision === "allowed" ? "ok" : "bad"}>{w.gate.decision}</Status></span> (recorded: {recorded.decision}). Run would be <strong data-testid="whatif-run">{w.run_status}</strong>. Critical failures {w.gate.critical_failures}, warnings failing {w.gate.noncritical_failures}.</p>
        <p><strong>Pointer:</strong> <span data-testid="whatif-pointer">{w.pointer_after ?? "none"}</span> {w.publishes ? <>moves to {pub ? "this run's publication" : "a candidate (this run has no publication row: hypothetical)"}</> : <>stays where it was ({before ?? "none"}): a run replaces the publication only if it succeeded, its gate allowed and a publication exists</>}.</p>
      </div>
      <p className="actions">
        <button type="button" data-testid="fault-record" disabled={Object.keys(force).length === 0} onClick={() => addSimFault({ run_id: runId, forced, decision: w.gate.decision, pointer_after: w.pointer_after, note: Object.entries(force).map(([r, v]) => `${r}: ${v}`).join("; ") })}>Record this injection</button>
        <button type="button" className="quiet" onClick={() => setForce({})}>Clear the faults</button>
      </p>
      {faults.length > 0 && (
        <Scroll label="Injections recorded this session">
          <table className="data" data-testid="fault-log"><caption>Recorded in browser memory (P08-FLOW-07: a fault is allowed only in the synthetic sandbox and is always recorded).</caption>
            <thead><tr><th scope="col">#</th><th scope="col">Run</th><th scope="col">Forced</th><th scope="col">Decision</th><th scope="col">Pointer</th></tr></thead>
            <tbody>{faults.map((f) => <tr key={f.n}><td>{f.n}</td><th scope="row"><code>{f.run_id}</code></th><td>{f.note}</td><td>{f.decision}</td><td>{f.pointer_after ?? "none"}</td></tr>)}</tbody></table>
          <p><button type="button" className="quiet" onClick={() => resetSim("fault")}>Reset the log</button></p>
        </Scroll>
      )}
    </Panel>
  );
}
function GateOne({ ds, runId, set }: { ds: Dataset; runId: string; set: (id: string) => void }) {
  const runs = runsOf(ds);
  const run = runs.find((r) => r["run_id"] === runId);
  const gate = gateOf(ds, runId);
  const blocked = blockedRunIds(ds);
  const hist = ds.g.metrics.publications.pointer_history as Row[];
  const hi = hist.findIndex((h) => h["run_id"] === runId);
  const before = hi > 0 ? (hist[hi - 1]!["pointer_after"] as string | null) : null;
  const after = hi >= 0 ? (hist[hi]!["pointer_after"] as string | null) : null;
  const pub = ds.pubOfRun[runId] ?? null;
  const ids = runs.map((r) => r["run_id"] as string);
  if (!run || !gate) return <div className="notice notice--bad" role="alert" data-testid="gate-missing">No run named “{runId}” in this dataset. <button type="button" onClick={() => set(defaultRun(ds))}>Go to the default run</button></div>;
  const fails = ds.failedChecks[runId] ?? [];
  return (
    <>
      <Panel id="decision" title={`Gate of ${runId}`} scope="complete">
        <div className="controls">
          <label>Run <select value={runId} onChange={(e) => set(e.target.value)} data-testid="gate-run">
            {blocked.length > 0 && <optgroup label={`Blocked runs (${blocked.length})`}>{blocked.map((id) => <option key={`b${id}`} value={id}>{id}</option>)}</optgroup>}
            <optgroup label="Latest 24 runs">{ids.slice(-24).reverse().map((id) => <option key={`l${id}`} value={id}>{id}</option>)}</optgroup>
          </select></label>
          <Link to={`runs?run=${runId}`}>Open the run</Link>
        </div>
        <div className={`decision decision--${gate.decision}`} data-testid="gate-decision" data-decision={gate.decision}>
          <p className="decision__word"><Status tone={gate.decision === "allowed" ? "ok" : "bad"}>{gate.decision.toUpperCase()}</Status></p>
          <p>{gate.decision === "blocked" ? (fails.some((f) => f.severity === "critical") ? `Blocked: ${fails.filter((f) => f.severity === "critical").map((f) => `${f.rule} failed (${f.failures} of ${f.eligible})`).join("; ")}.` : "Blocked: no critical result exists or the run did not finish its gate (fail closed).") : `Allowed: ${gate.critical_failures} critical failures${gate.noncritical_failures ? `; ${gate.noncritical_failures} warning${gate.noncritical_failures === 1 ? "" : "s"} failing, which never block` : ""}.`}</p>
        </div>
        <Scroll label="Checks of the gate">
          <table className="data" data-testid="gate-checks">
            <caption>Critical checks decide; the gate fails closed. Latest result per rule counts.</caption>
            <thead><tr><th scope="col">Check</th><th scope="col">Severity</th><th scope="col">Eligible</th><th scope="col">Failures</th><th scope="col">Result</th><th scope="col">Meaning</th></tr></thead>
            <tbody>{Object.entries(gate.results as Record<string, Row>).map(([rule, r]) => (
              <tr key={rule} data-rule={rule} data-passed={r["passed"] ? "true" : "false"}>
                <th scope="row"><code>{rule}</code></th><td data-k="severity">{r["severity"]}</td><td data-k="eligible">{n0(r["eligible"])}</td><td data-k="failures">{n0(r["failures"])}</td>
                <td data-k="result"><Status tone={r["passed"] ? "ok" : r["severity"] === "critical" ? "bad" : "warn"}>{r["passed"] ? "passed" : "failed"}</Status></td><td>{RULE_TEXT[rule] ?? ""}</td>
              </tr>))}</tbody>
          </table>
        </Scroll>
        <div className="outcome" data-testid="gate-outcome">
          <p><strong>Publication decision.</strong> Run status <code>{run["status"]}</code>; publication row {pub ? <code>{pub}</code> : <strong>none</strong>}. The pointer was <code data-k="pointer-before">{before ?? "none"}</code> and is <code data-k="pointer-after">{after ?? "none"}</code>{pub && after === pub ? " (moved)" : " (unchanged)"}.</p>
          <p className="meaning">{gate.decision === "blocked" ? "A blocked run fails, opens an incident and publishes nothing: the publication pointer moves only to a candidate that passed, atomically. A failed run never replaces the publication." : "An allowed run succeeds and publishes; the pointer then moves to its publication. A failing warning is reported but never blocks."}{" "}Diagnosis from the published rows: {diagnosis(ds, runId)}.</p>
        </div>
      </Panel>
      <Lab key={runId} ds={ds} runId={runId} />
    </>
  );
}
function Blocked({ ds, set }: { ds: Dataset; set: (id: string) => void }) {
  const ids = blockedRunIds(ds);
  const gates = Object.values<{ decision: string }>(ds.g.metrics.quality_gate);
  return (
    <Panel id="blocked" title="Every blocked run" scope="complete">
      <p className="meaning" data-testid="gate-totals"><span data-figure="gate-allowed">{n0(gates.filter((g) => g.decision === "allowed").length)}</span> runs allowed, <span data-figure="gate-blocked">{n0(ids.length)}</span> blocked. Each blocked run opened an incident; none published.</p>
      {ids.length === 0 ? <p className="notice notice--empty" data-testid="empty">No run was blocked in this dataset.</p> : (
        <Scroll label="Blocked runs">
          <table className="data" data-testid="blocked-table">
            <thead><tr><th scope="col">Run</th><th scope="col">Failed check</th><th scope="col">Incident</th><th scope="col">Verified recovery</th><th scope="col" /></tr></thead>
            <tbody>{ids.map((id) => {
              const inc = ds.incidents.incidents.find((i) => i.run_id === id);
              return (
                <tr key={id} data-run={id}>
                  <th scope="row"><code>{id}</code></th><td>{diagnosis(ds, id)}</td><td>{inc ? <Link to={`incidents?incident=${inc.incident_id}`}>{inc.incident_id}</Link> : "—"}</td>
                  <td>{inc?.recovery_minutes ? `${inc.recovery_run_id}, ${inc.recovery_minutes} min` : "not yet"}</td><td><button type="button" className="quiet" onClick={() => set(id)}>Show</button></td>
                </tr>);
            })}</tbody>
          </table>
        </Scroll>
      )}
    </Panel>
  );
}
export function GateView() {
  return (
    <WithData>
      {(ds) => <Gate ds={ds} />}
    </WithData>
  );
}
function Gate({ ds }: { ds: Dataset }) {
  const dflt = defaultRun(ds);
  const [runId, set] = useParam("run", dflt);
  return (
    <>
      <ViewHead mark="07 · entry screen" title="Quality gate">
        <p className="lede">May this candidate replace the published dataset? Four critical checks decide; a failed run never replaces the publication.</p>
      </ViewHead>
      <GateOne ds={ds} runId={runId} set={set} />
      <Blocked ds={ds} set={set} />
    </>
  );
}
