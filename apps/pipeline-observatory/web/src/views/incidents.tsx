import { Link } from "../components/link";
import { Panel, Readout, Scroll, ScopeTag, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import { isoZ, parseTs } from "../domain/time";
import type { IncidentView } from "../domain/world";
import { dayTime, dur, n0, pct } from "../lib/format";
import { useParam } from "../router";

const W = 900, L = 120, R = 24, LANE = 30, TOP = 22;
function Axis({ ds, sel, pick }: { ds: Dataset; sel: string; pick: (id: string) => void }) {
  const items = ds.incidents.incidents;
  const classes = Object.keys(ds.incidents.by_class);
  const t0 = parseTs(ds.manifest?.window_start ?? ds.acc["pipeline_runs"]![0]!["started_at"]), t1 = parseTs(ds.g.as_of);
  const span = Number(t1 - t0) || 1;
  const x = (iso: string): number => L + ((W - L - R) * Number(parseTs(iso) - t0)) / span;
  const H = TOP + classes.length * LANE + 26;
  const days = Math.max(1, Math.round(span / 86_400_000_000));
  const ticks = Array.from({ length: Math.floor(days / 7) + 1 }, (_, i) => t0 + BigInt(i) * 7n * 86_400_000_000n);
  return (
    <figure className="chart" data-testid="incident-axis">
      <svg viewBox={`0 0 ${W} ${H}`} className="chart__svg" role="group" aria-label={`Incidents on a time axis from ${ds.manifest?.window_start ?? "the first run"} to the as-of instant, one lane per diagnosis class. Each is also a row in the table below.`}>
        {ticks.map((t) => { const iso = isoZ(t)!.slice(0, 10); const xx = L + ((W - L - R) * Number(t - t0)) / span; return <g key={iso}><line x1={xx} x2={xx} y1={TOP - 8} y2={H - 22} className="chart__grid" /><text x={xx} y={H - 6} textAnchor="middle" className="chart__tick">{iso.slice(5)}</text></g>; })}
        {classes.map((c, i) => <text key={c} x={L - 8} y={TOP + i * LANE + 14} textAnchor="end" className="chart__label">{c}</text>)}
        {items.map((it) => {
          const lane = classes.indexOf(it.diagnosis_class);
          const x0 = x(it.opened_at), x1 = it.verified_at ? x(it.verified_at) : x0;
          const y = TOP + lane * LANE;
          const on = it.incident_id === sel;
          return (
            <g key={it.incident_id} role="button" tabIndex={0} aria-pressed={on} aria-label={`${it.incident_id}, ${it.severity}, ${it.diagnosis_class}, detected ${it.opened_at}${it.recovery_minutes ? `, recovered after ${it.recovery_minutes} minutes` : ", not recovered"}`}
              data-incident={it.incident_id} data-testid="incident-mark" className={`inc inc--${it.severity}${on ? " is-on" : ""}`} onClick={() => pick(it.incident_id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(it.incident_id); } }}>
              <rect x={x0} y={y + 4} width={Math.max(5, x1 - x0)} height={14} rx={2} className="inc__span" />
              <text x={x0 + 1} y={y + 15} className="inc__g" aria-hidden="true">{it.severity === "critical" ? "◆" : it.severity === "high" ? "▲" : "●"}</text>
            </g>
          );
        })}
      </svg>
      <figcaption className="legend"><span>◆ critical</span><span>▲ high</span><span>● medium</span><span>bar: detection to verified recovery</span></figcaption>
    </figure>
  );
}
function Detail({ ds, it }: { ds: Dataset; it: IncidentView }) {
  const run = ds.acc["pipeline_runs"]!.find((r) => r["run_id"] === it.run_id);
  return (
    <Panel id="detail" title={`${it.incident_id}: detection, diagnosis, recovery`} scope="complete">
      <ol className="steps" data-testid="incident-detail" data-incident={it.incident_id}>
        <li><h3>Detection</h3><p data-k="detection">Opened <strong>{it.opened_at}</strong> when run <Link to={`runs?run=${it.run_id}`}>{it.run_id}</Link> {run?.["status"] === "failed" ? "failed" : "was blocked"}{run?.["finished_at"] ? ` (finished ${run["finished_at"]})` : ""}. Severity {it.severity}.</p></li>
        <li><h3>Diagnosis</h3><p data-k="diagnosis">Class <strong>{it.diagnosis_class}</strong>. {it.failed_checks.length ? `Failed check${it.failed_checks.length === 1 ? "" : "s"}: ${it.failed_checks.map((c) => `${c.rule} (${c.failures} of ${c.eligible}, ${c.severity})`).join("; ")}.` : ""}{it.failed_tasks.length ? ` Failed task${it.failed_tasks.length === 1 ? "" : "s"}: ${it.failed_tasks.map((t) => `${t.task} after ${t.attempts} attempt${t.attempts === 1 ? "" : "s"}`).join("; ")}.` : ""}{!it.failed_checks.length && !it.failed_tasks.length ? " No failed check or task is recorded." : ""} <Link to={`gate?run=${it.run_id}`}>Open the gate of this run</Link>.</p></li>
        <li><h3>Verified recovery</h3><p data-k="recovery">{it.verified ? <>Run <Link to={`runs?run=${it.recovery_run_id}`}>{it.recovery_run_id}</Link> succeeded, passed its gate, published and reconciled; its publication went out at <strong>{it.verified_at}</strong>. Recovery time <strong data-figure="recovery-minutes">{it.recovery_minutes}</strong> min ({it.recovery_seconds} s, {dur(it.recovery_seconds)}), detection to verified recovery, never process restart.</> : "No later run has yet succeeded, passed its gate, published and reconciled: the incident stays open."}</p>
          <p className="meaning">The record says {it.status}{it.closed_at ? ` at ${it.closed_at}` : ""}{it.recorded_recovery_run_id ? ` by ${it.recorded_recovery_run_id}` : ""}: <Status tone={it.closure_consistent ? "ok" : "bad"}>{it.closure_consistent ? "consistent with the verified recovery" : "does NOT agree with the verified recovery"}</Status></p></li>
      </ol>
    </Panel>
  );
}
function Incidents({ ds }: { ds: Dataset }) {
  const I = ds.incidents;
  const dr = ds.manifest?.designed_relationships?.find((d) => d["id"] === "DR-02")?.["realised"]?.["incident_id"] as string | undefined;
  const [sel, setSel] = useParam("incident", dr && I.incidents.some((i) => i.incident_id === dr) ? dr : (I.incidents[0]?.incident_id ?? ""));
  const it = I.incidents.find((i) => i.incident_id === sel) ?? null;
  const M = ds.g.metrics.incidents;
  if (I.total === 0) return <p className="notice notice--empty" data-testid="empty">No incident in this dataset.</p>;
  return (
    <>
      <Panel id="summary" title="Detection to verified recovery" scope="complete">
        <dl className="readouts">
          <Readout k="incidents-total" label="Incidents" value={n0(I.total)} note={`${I.open} open, ${I.closed} closed`} />
          <Readout k="incidents-verified" label="Verified recoveries" value={n0(I.verified)} note="a later run succeeded, passed its gate, published and reconciled to 0.00" />
          <Readout k="mean-recovery" label="Mean verified recovery" value={I.mean_recovery_minutes ?? "n/a"} unit="min" note="detection (incident opened) to the recovery publication, never a process restart" />
          <Readout k="closures-consistent" label="Closures consistent" value={I.all_closures_consistent ? "all" : "not all"} note="each closed incident names the run and instant the rule finds" />
        </dl>
        {ds.residualAssumed && <p className="meaning" data-testid="residual-note"><ScopeTag basis="recorded" /> The reconciliation residual of a publication needs raw rows, which are published as a sample, so verified recovery here relies on the generator&apos;s recorded statement that every publication reconciles to 0.00. Over the 2,000-row sample alone the rule verifies {M.verified} of {M.total} (no residual can be evaluated), which is why the sample view cannot show recovery.</p>}
        <Scroll label="Incidents by diagnosis class">
          <table className="data" data-testid="class-table"><caption>Diagnosis class: the first failed gate check of the run, else its failed task.</caption>
            <thead><tr><th scope="col">Class</th><th scope="col">Incidents</th><th scope="col" /></tr></thead>
            <tbody>{Object.entries(I.by_class).map(([c, n]) => <tr key={c} data-class={c}><th scope="row">{c}</th><td data-k="count">{n}</td><td><span className="bar"><span className="bar__f" style={{ width: pct(n, I.total) }} /></span></td></tr>)}</tbody></table>
        </Scroll>
      </Panel>
      <Panel id="axis" title="Incident timeline" scope="complete"><Axis ds={ds} sel={sel} pick={setSel} /></Panel>
      {it ? <Detail ds={ds} it={it} /> : <p className="meaning">Select an incident on the timeline or in the table.</p>}
      <Panel id="all" title="All incidents" scope="complete">
        <Scroll label="All incidents">
          <table className="data" data-testid="incident-table">
            <caption>{I.total} incidents in time order.</caption>
            <thead><tr><th scope="col">Incident</th><th scope="col">Severity</th><th scope="col">Detected</th><th scope="col">Class</th><th scope="col">Recovery run</th><th scope="col">Verified at</th><th scope="col">Minutes</th><th scope="col">Closure</th></tr></thead>
            <tbody>{I.incidents.map((i) => (
              <tr key={i.incident_id} data-incident={i.incident_id} className={i.incident_id === sel ? "is-sel" : ""}>
                <th scope="row"><button type="button" className="link" onClick={() => setSel(i.incident_id)} aria-label={`Select ${i.incident_id}`}>{i.incident_id}</button></th><td>{i.severity}</td><td>{dayTime(i.opened_at)}</td><td>{i.diagnosis_class}</td>
                <td>{i.recovery_run_id ?? "—"}</td><td>{i.verified_at ? dayTime(i.verified_at) : "—"}</td><td data-k="minutes">{i.recovery_minutes ?? "—"}</td><td><Status tone={i.closure_consistent ? "ok" : "bad"}>{i.closure_consistent ? "consistent" : "inconsistent"}</Status></td>
              </tr>))}</tbody>
          </table>
        </Scroll>
      </Panel>
    </>
  );
}
export function IncidentsView() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="09" title="Incident timeline">
            <p className="lede">An incident opens when a run fails or a gate blocks, and closes only after a verified recovery: a later run that passes the gate, publishes and reconciles.</p>
          </ViewHead>
          <Incidents ds={ds} />
        </>
      )}
    </WithData>
  );
}
