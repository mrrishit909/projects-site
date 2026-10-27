import { useMemo } from "react";
import { GoldenPanel } from "../components/golden-panel";
import { Link } from "../components/link";
import { Fig, Meaning, Panel, Scroll, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import type { Row } from "../domain/contract";
import { isoZ, parseTs, secondsBetween } from "../domain/time";
import { blockedRunIds, diagnosis, gateOf, intake, runLog, runsOf, timeLabel } from "../lib/derive";
import { dayTimeS, dur, n0 } from "../lib/format";
import { useParam } from "../router";

const TASKS = ["ingest", "transform", "quality_gate", "publish"];
function RunStrip({ ds, runs, sel, pick }: { ds: Dataset; runs: Row[]; sel: string; pick: (id: string) => void }) {
  const W = 1000, H = 44, n = runs.length;
  const w = W / n;
  const idx = runs.findIndex((r) => r["run_id"] === sel);
  return (
    <figure className="chart" data-testid="run-strip">
      <svg viewBox={`0 0 ${W} ${H + 18}`} className="chart__svg" role="img" aria-label={`Every run in time order, ${n} cells. Blocked or failed runs are tall amber marks. The failed runs are also listed as buttons below.`}
        onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); const i = Math.max(0, Math.min(n - 1, Math.floor(((e.clientX - r.left) / r.width) * n))); pick(runs[i]!["run_id"]); }}>
        {runs.map((r, i) => {
          const g = gateOf(ds, r["run_id"]);
          const bad = r["status"] !== "success" || g?.decision === "blocked";
          return <rect key={r["run_id"]} x={i * w} y={bad ? 2 : 22} width={Math.max(0.6, w - 0.2)} height={bad ? 38 : 18} className={bad ? "strip__bad" : "strip__ok"} />;
        })}
        {idx >= 0 && <g><line x1={idx * w + w / 2} x2={idx * w + w / 2} y1={0} y2={H} className="strip__sel" /><path d={`M${idx * w + w / 2 - 5} ${H + 12}l5 -8l5 8z`} className="strip__selg" /></g>}
        <text x={0} y={H + 14} className="chart__tick">{isoZ(runs[0]!["started_at"])!.slice(0, 10)}</text>
        <text x={W} y={H + 14} textAnchor="end" className="chart__tick">{isoZ(runs[n - 1]!["started_at"])!.slice(0, 10)}</text>
      </svg>
    </figure>
  );
}
function Timeline({ ds, runId }: { ds: Dataset; runId: string }) {
  const run = ds.acc["pipeline_runs"]!.find((r) => r["run_id"] === runId)!;
  const pub = ds.acc["publications"]!.find((p) => p["run_id"] === runId);
  const inc = ds.acc["incidents"]!.find((i) => i["run_id"] === runId);
  const ev: { at: bigint; kind: string; text: string }[] = [];
  for (const c of intake(ds, runId)) ev.push({ at: parseTs(c["committed_at"]), kind: "intake", text: `batch ${c["batch_id"]} committed (v${c["version_number"]})` });
  ev.push({ at: parseTs(run["started_at"]), kind: "start", text: `run ${runId} started` });
  if (run["finished_at"]) ev.push({ at: parseTs(run["finished_at"]), kind: "finish", text: `run ${run["status"]}` });
  if (pub) { ev.push({ at: parseTs(pub["published_at"]), kind: "publish", text: `${pub["publication_id"]} published` }); ev.push({ at: parseTs(pub["watermark"]), kind: "watermark", text: `watermark of ${pub["publication_id"]}` }); }
  if (inc) ev.push({ at: parseTs(inc["opened_at"]), kind: "incident", text: `${inc["incident_id"]} opened` });
  ev.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
  const t0 = ev[0]!.at, t1 = ev[ev.length - 1]!.at;
  const span = Number(t1 - t0) || 1;
  const W = 900, L = 24, R = 24;
  const x = (t: bigint): number => L + ((W - L - R) * Number(t - t0)) / span;
  const GL: Record<string, string> = { intake: "▮", start: "▶", finish: "■", publish: "◆", watermark: "▏", incident: "!" };
  return (
    <>
      <figure className="chart" data-testid="run-timeline">
        <svg viewBox={`0 0 ${W} 120`} className="chart__svg" role="img" aria-label={`Timeline of run ${runId}: ${ev.length} events from ${isoZ(t0)} to ${isoZ(t1)}; the same events are in the table below.`}>
          <line x1={L} x2={W - R} y1={56} y2={56} className="tl__axis" />
          {ev.map((e, i) => (
            <g key={`${e.kind}${i}`} data-event={e.kind}>
              <line x1={x(e.at)} x2={x(e.at)} y1={e.kind === "intake" ? 46 : 36} y2={e.kind === "intake" ? 66 : 76} className={`tl__mark tl__mark--${e.kind}`} />
              <text x={x(e.at)} y={e.kind === "intake" ? 40 : 30} textAnchor="middle" className={`tl__glyph tl__glyph--${e.kind}`}>{GL[e.kind]}</text>
              {e.kind !== "intake" && <text x={Math.min(W - 70, Math.max(70, x(e.at)))} y={92 + (i % 2) * 14} textAnchor="middle" className="chart__sub">{e.text}</text>}
            </g>
          ))}
          <text x={L} y={116} className="chart__tick">{dayTimeS(isoZ(t0)!)}</text>
          <text x={W - R} y={116} textAnchor="end" className="chart__tick">{dayTimeS(isoZ(t1)!)}</text>
        </svg>
      </figure>
      <Scroll label="Events of the run in time order">
        <table className="data" data-testid="run-events">
          <caption>Events of run {runId}, in time order. Task attempts carry no timestamps in the published data, so they appear as steps below, never placed on this axis.</caption>
          <thead><tr><th scope="col">Time (UTC)</th><th scope="col">Event</th></tr></thead>
          <tbody>{ev.map((e, i) => <tr key={i} data-event={e.kind}><td>{dayTimeS(isoZ(e.at)!)}</td><td>{e.text}</td></tr>)}</tbody>
        </table>
      </Scroll>
    </>
  );
}
function RunDetail({ ds, runId }: { ds: Dataset; runId: string }) {
  const run = ds.acc["pipeline_runs"]!.find((r) => r["run_id"] === runId);
  if (!run) return <div className="notice notice--bad" role="alert" data-testid="run-missing">No run named “{runId}” in this dataset.</div>;
  const gate = gateOf(ds, runId)!;
  const R = ds.g.metrics.runs.runs[runId];
  const pub = ds.acc["publications"]!.find((p) => p["run_id"] === runId);
  const hist = (ds.g.metrics.publications.pointer_history as Row[]);
  const hi = hist.findIndex((h) => h["run_id"] === runId);
  const inc = ds.incidents.incidents.find((i) => i.run_id === runId);
  const attempts = (name: string): Row[] => ds.acc["task_runs"]!.filter((t) => t["run_id"] === runId && t["task_name"] === name).sort((a, b) => Number(a["attempt"]) - Number(b["attempt"]));
  const log = runLog(ds, runId);
  const withheld = log.filter((l) => l.withheld).length;
  const dsec = run["finished_at"] ? secondsBetween(run["started_at"], run["finished_at"]) : null;
  return (
    <div data-testid="run-detail" data-run={runId}>
      <dl className="facts">
        <div><dt>Run</dt><dd data-k="run-id">{runId}</dd></div>
        <div><dt>Status</dt><dd data-k="status"><Status tone={run["status"] === "success" ? "ok" : "bad"}>{run["status"]}</Status></dd></div>
        <div><dt>Started</dt><dd>{run["started_at"]}</dd></div>
        <div><dt>Finished</dt><dd>{run["finished_at"] ?? "not recorded"}{dsec !== null ? ` (${dsec} s, ${dur(dsec)})` : ""}</dd></div>
        <div><dt>Code</dt><dd><code>{run["code_sha"]}</code>{run["backfill_id"] ? ` · carries backfill ${run["backfill_id"]}` : ""}</dd></div>
        <div><dt>Gate</dt><dd data-k="gate"><Status tone={gate.decision === "allowed" ? "ok" : "bad"}>{gate.decision}</Status> · <Link to={`gate?run=${runId}`}>open the gate</Link></dd></div>
      </dl>
      <h3>Steps and attempts</h3>
      <Scroll label="Tasks and attempts of the run">
        <table className="data" data-testid="run-steps">
          <caption>A task has attempts; the last attempt is its outcome. Task success rate counts tasks, not attempts: {R.tasks_successful} of {R.tasks_terminal} tasks succeeded ({R.task_success_rate ?? "n/a"}); {R.attempts_successful} of {R.attempts} attempts ({R.attempt_success_rate ?? "n/a"}).</caption>
          <thead><tr><th scope="col">Task</th><th scope="col">Attempts</th><th scope="col">Outcome</th></tr></thead>
          <tbody>
            {TASKS.map((name) => {
              const a = attempts(name);
              const final = a.length ? a[a.length - 1]!["status"] : null;
              return (
                <tr key={name} data-task={name}>
                  <th scope="row"><code>{name}</code></th>
                  <td data-k="attempts">{a.length ? a.map((t) => <span key={t["task_run_id"]} className={`attempt attempt--${t["status"]}`}><span aria-hidden="true">{t["status"] === "success" ? "✓" : "✕"}</span> #{t["attempt"]} {t["status"]}</span>) : <span className="sub">not run: no task row</span>}</td>
                  <td data-k="outcome">{final ? <Status tone={final === "success" ? "ok" : "bad"}>{final}</Status> : <Status tone="idle">absent</Status>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Scroll>
      <h3>Quality results</h3>
      <Scroll label="Quality results of the run">
        <table className="data" data-testid="run-quality">
          <caption>{Object.keys(gate.results).length === 0 ? "No quality result exists for this run: it failed before its gate ran, and a gate with no critical result is blocked (fail closed)." : `Latest result per rule counts. Critical failures: ${gate.critical_failures}; warnings failing: ${gate.noncritical_failures}.`}</caption>
          <thead><tr><th scope="col">Rule</th><th scope="col">Severity</th><th scope="col">Eligible</th><th scope="col">Failures</th><th scope="col">Result</th></tr></thead>
          <tbody>{Object.entries(gate.results as Record<string, Row>).map(([rule, r]) => <tr key={rule} data-rule={rule}><th scope="row"><code>{rule}</code></th><td>{r["severity"]}</td><td>{n0(r["eligible"])}</td><td>{n0(r["failures"])}</td><td><Status tone={r["passed"] ? "ok" : r["severity"] === "critical" ? "bad" : "warn"}>{r["passed"] ? "passed" : "failed"}</Status></td></tr>)}</tbody>
        </table>
      </Scroll>
      <p className="meaning" data-testid="run-outcome"><strong>Outcome.</strong> {pub ? `Published ${pub["publication_id"]} at ${pub["published_at"]} with watermark ${pub["watermark"]}; the pointer ${hi >= 0 && hist[hi]!["pointer_after"] === pub["publication_id"] ? "moved to it" : `stayed at ${hist[hi]?.["pointer_after"] ?? "its previous value"}`}.` : `No publication row exists for this run; the pointer ${hi >= 0 ? `stays at ${hist[hi]!["pointer_after"] ?? "none"}` : "does not move"}.${gate.decision === "blocked" ? " A failed run never replaces the publication." : ""}`}
        {inc ? <> Incident <Link to={`incidents?incident=${inc.incident_id}`}>{inc.incident_id}</Link> opened at {inc.opened_at}: {diagnosis(ds, runId)}; verified recovery by {inc.recovery_run_id ?? "none yet"}{inc.recovery_minutes ? ` after ${inc.recovery_minutes} min` : ""}.</> : null}</p>
      <h3>Evidence log</h3>
      <p className="meaning">Structured lines built only from published rows (batches, checkpoints, tasks, gate results, publication). Every line passes the secret-redaction check before it is shown: {n0(log.length)} lines, {n0(withheld)} withheld.</p>
      <Scroll label="Structured evidence log of the run">
        <table className="data log" data-testid="run-log">
          <thead><tr><th scope="col">Time (UTC)</th><th scope="col">Line</th></tr></thead>
          <tbody>{log.map((l, i) => <tr key={i}><td>{timeLabel(l.at)}</td><td><code>{l.text}</code></td></tr>)}</tbody>
        </table>
      </Scroll>
    </div>
  );
}
function Picker({ ds, runs, sel, set }: { ds: Dataset; runs: Row[]; sel: string; set: (id: string) => void }) {
  const ids = useMemo(() => runs.map((r) => r["run_id"] as string), [runs]);
  const i = ids.indexOf(sel);
  const blocked = blockedRunIds(ds);
  const failedList = runs.filter((r) => r["status"] !== "success");
  return (
    <>
      <div className="controls" data-testid="run-controls">
        <label>Run <select value={ids.includes(sel) ? sel : ""} data-testid="run-select" onChange={(e) => set(e.target.value)}>
          {!ids.includes(sel) && <option value="">(not in this dataset)</option>}
          {blocked.length > 0 && <optgroup label={`Blocked runs (${blocked.length})`}>{blocked.map((id) => <option key={`b${id}`} value={id}>{id}</option>)}</optgroup>}
          <optgroup label="Latest 24 runs">{ids.slice(-24).reverse().map((id) => <option key={`l${id}`} value={id}>{id}</option>)}</optgroup>
        </select></label>
        <label>Go to run id <input list="run-ids" data-testid="run-input" defaultValue="" placeholder={ids[ids.length - 1]} onChange={(e) => { if (ids.includes(e.target.value)) set(e.target.value); }} /></label>
        <datalist id="run-ids">{ids.map((id) => <option key={id} value={id} />)}</datalist>
        <button type="button" className="quiet" data-testid="run-prev" disabled={i <= 0} onClick={() => set(ids[i - 1]!)}>Previous run</button>
        <button type="button" className="quiet" data-testid="run-next" disabled={i < 0 || i >= ids.length - 1} onClick={() => set(ids[i + 1]!)}>Next run</button>
        <button type="button" className="quiet" data-testid="run-latest" onClick={() => set(ids[ids.length - 1]!)}>Latest run</button>
      </div>
      <RunStrip ds={ds} runs={runs} sel={sel} pick={set} />
      <Meaning>{n0(runs.length)} runs in time order; tall amber marks are failed or blocked runs ({failedList.length}). Click the strip, use the controls, or pick a failed run:</Meaning>
      <p className="chips" data-testid="failed-runs">{failedList.map((r) => <button key={r["run_id"]} type="button" className={`chip${r["run_id"] === sel ? " is-on" : ""}`} aria-pressed={r["run_id"] === sel} onClick={() => set(r["run_id"])}>{r["run_id"]}</button>)}{failedList.length === 0 && <span className="sub">no failed run</span>}</p>
    </>
  );
}
function Runs({ ds }: { ds: Dataset }) {
  const runs = useMemo(() => runsOf(ds), [ds]);
  const blocked = blockedRunIds(ds);
  const dflt = blocked.length ? blocked[blocked.length - 1]! : runs[runs.length - 1]?.["run_id"] ?? "";
  const [sel, set] = useParam("run", dflt);
  if (!runs.length) return <div className="notice notice--empty" data-testid="empty"><p>This dataset has no runs.</p></div>;
  return (
    <>
      <Panel id="pick" title="Choose a run" scope="complete"><Picker ds={ds} runs={runs} sel={sel} set={set} /></Panel>
      <Panel id="timeline" title={`Run evidence timeline: ${sel}`} scope="complete">
        {runs.some((r) => r["run_id"] === sel) ? <Timeline ds={ds} runId={sel} /> : null}
      </Panel>
      <Panel id="detail" title="Steps, attempts, quality results and logs" scope="complete"><RunDetail ds={ds} runId={sel} /></Panel>
    </>
  );
}
export function RunsView() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="04 · entry screen" title="Run detail">
            <p className="lede">What a run actually did: its steps and attempts, the quality results that decided it, the log it left and what it did to the publication. Below it, the golden batch: ten rows, a replay, and a crash.</p>
          </ViewHead>
          <Runs ds={ds} />
          <GoldenPanel />
          <p className="meaning">Runs here: <Fig k="run-count">{n0(ds.acc["pipeline_runs"]!.length)}</Fig>.</p>
        </>
      )}
    </WithData>
  );
}
