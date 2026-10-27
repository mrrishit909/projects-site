import { useState } from "react";
import { Disclosures } from "../components/experiment";
import { Link } from "../components/link";
import { Chip, Choice, Def, Scroll, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { guardrailReview } from "../domain/metrics";
import { isoZ } from "../domain/time";
import { minus, pp } from "../lib/format";
import { runLabel, useRun } from "../lib/pick";
import { decisionRules, type Option } from "../lib/rules";
import { addDecision, useDecisions } from "../state/sim";

const MEANING: Record<Option, string> = {
  ship: "roll the change out to everyone",
  stop: "do not roll the change out",
  inconclusive: "the evidence cannot support ship or stop: investigate further (a longer run, a larger sample, a repaired assignment)",
};

function Decision({ ds }: { ds: Dataset }) {
  const [run, setRun] = useRun(ds);
  const [note, setNote] = useState("");
  const log = useDecisions();
  const xv = run.experiment_version_id;
  const plan = ds.plans.get(xv)!;
  const ex = ds.at(run.cutoff_at, xv, run.analysis_id).metrics.experiment!;
  const guard = guardrailReview(ex, plan);
  const verdicts = decisionRules(ex, guard);
  const withheld = ex.srm.verdict === "MISMATCH";
  const iv = ex.primary.interval;
  const evidence: { key: string; item: string; value: React.ReactNode; ok: boolean | null }[] = [
    { key: "plan", item: "Plan frozen before the first run", value: ex.run.plan_frozen ? `yes, ${isoZ(plan.frozen_at)}` : "no", ok: ex.run.plan_frozen },
    { key: "hash", item: "The run cites the plan's config_hash", value: ex.run.config_hash_matches_plan ? "yes, and the hash recomputes in this browser" : "no", ok: ex.run.config_hash_matches_plan },
    { key: "run", item: "Run", value: <>{ex.run.interim ? "interim" : "final"}; {ex.run.prior_runs} prior run{ex.run.prior_runs === 1 ? "" : "s"}; cutoff {isoZ(run.cutoff_at)}; planned end {isoZ(plan.planned_end)}</>, ok: !ex.run.interim },
    { key: "srm", item: "Sample ratio (before any lift)", value: <>{ex.srm.verdict}: chi-square {ex.srm.statistic ?? "n/a"}, p {ex.srm.p_value ?? "n/a"}</>, ok: ex.srm.verdict !== "MISMATCH" },
    { key: "lift", item: "Absolute effect on 7-day activation", value: withheld ? "withheld (SRM MISMATCH)" : iv ? <>{pp(ex.primary.absolute_lift_pp)}; Newcombe [{minus(iv.low)}, {minus(iv.high)}], {iv.includes_zero ? "includes 0" : "excludes 0"}</> : "n/a", ok: withheld ? false : iv ? !iv.includes_zero : null },
    { key: "conclusive", item: "Conclusive (interval excludes 0, final run, valid plan hash)", value: withheld ? "not assessed" : ex.primary.conclusive ? "yes" : "no", ok: withheld ? false : ex.primary.conclusive },
    { key: "guardrail", item: "Guardrail: error rate", value: <>{guard.verdict}{guard.difference_pp !== null && <>; difference {pp(guard.difference_pp)}</>}</>, ok: guard.verdict === "OK" },
    { key: "exposure", item: "Exposure rate (ITT counts the unexposed too)", value: ex.exposure.overall.rate ?? "n/a", ok: null },
    { key: "segments", item: "Segments", value: "not cited: exploratory, never a decision basis", ok: null },
  ];
  const done = log.find((d) => d.run === run.analysis_id && d.status === "recorded");
  function record(option: Option): void {
    const v = verdicts.find((x) => x.option === option)!;
    if (done) { addDecision({ run: run.analysis_id, xv, option, status: "refused", reasons: [`ONE_DECISION_PER_RUN: ${done.option} is already recorded for ${run.analysis_id}`], warnings: [], note }); return; }
    addDecision({ run: run.analysis_id, xv, option, status: v.allowed ? "recorded" : "refused", reasons: v.blockers, warnings: v.warnings, note });
    setNote("");
  }
  return (
    <>
      <ViewHead eyebrow="Decision memo" title="Ship, stop, or investigate further?">
        <p className="lede">The memo lists the evidence of one analysis run and what the contract allows. It does not recommend an option, and inconclusive is a legitimate outcome, not a failure to decide.</p>
      </ViewHead>
      <p className="callout callout--warn" data-testid="sim-label"><Chip v="simulated">simulated</Chip> Recording a decision here only writes a row in your browser's memory. Nothing is shipped, stopped or changed; no feature flag, release or product state exists to change; the log is gone when you reload.</p>
      <Choice name="run" legend="Analysis run cited" value={run.analysis_id} onChange={setRun} testid="run-picker" options={ds.runs.map((r) => ({ value: r.analysis_id, label: runLabel(ds, r) }))} />
      <section className="block" data-testid="evidence" aria-labelledby="ev">
        <h2 id="ev">Evidence from {run.analysis_id}</h2>
        <Scroll label="Evidence">
          <table>
            <thead><tr><th scope="col">Evidence</th><th scope="col">Finding</th><th scope="col">Supports</th></tr></thead>
            <tbody>{evidence.map((e) => <tr key={e.key} data-evidence={e.key}><th scope="row">{e.item}</th><td className="basis">{e.value}</td><td>{e.ok === null ? <span className="muted">context</span> : e.ok ? <Chip v="OK">supports</Chip> : <Chip v="MISMATCH">does not support</Chip>}</td></tr>)}</tbody>
          </table>
        </Scroll>
        <p className="muted"><Link to={`result?run=${run.analysis_id}`}>Full result for this run</Link> · <Link to={`population?run=${run.analysis_id}`}>assigned and exposed</Link>. <Def term="what a decision may cite">One analysis run and the guardrail review of that run, a frozen plan and a sample ratio that is not MISMATCH. Ship is also blocked by an interim run, a harmful guardrail, a pre-assignment exclusion (plan deviation) and a config-hash mismatch. A MISMATCH also blocks stop (the data cannot support either direction); only inconclusive remains.</Def></p>
      </section>
      <section aria-labelledby="opts">
        <h2 id="opts">The options</h2>
        <div className="options" data-testid="options">
          {verdicts.map((v) => (
            <article key={v.option} className={`option option--${v.allowed ? "ok" : "blocked"}`} data-option={v.option} data-allowed={v.allowed ? "true" : "false"}>
              <h3>{v.option} <Chip v={v.allowed ? "allowed" : "blocked"}>{v.allowed ? "allowed" : "blocked"}</Chip></h3>
              <p className="muted">{MEANING[v.option]}</p>
              {v.blockers.length > 0 && <ul className="reasons">{v.blockers.map((b) => <li key={b} data-reason={b.split(":")[0]}>{b}</li>)}</ul>}
              {v.warnings.length > 0 && <ul className="reasons reasons--warn">{v.warnings.map((b) => <li key={b} data-warning={b.split(":")[0]}>{b}</li>)}</ul>}
              <button type="button" onClick={() => record(v.option)} data-testid={`record-${v.option}`}>{v.allowed ? `Record ${v.option} (simulated)` : `Try ${v.option} (simulated, will be refused)`}</button>
            </article>
          ))}
        </div>
        <label className="note"><span>Note for the log (optional, stays in memory)</span><input type="text" value={note} maxLength={160} onChange={(e) => setNote(e.target.value)} /></label>
      </section>
      <section className="block" data-testid="sim-log" aria-labelledby="log">
        <h2 id="log">Simulated decision log</h2>
        {log.length === 0 ? <p className="muted" data-testid="sim-empty">Nothing recorded in this browser session.</p> : (
          <Scroll label="Simulated decisions">
            <table>
              <thead><tr><th scope="col">#</th><th scope="col">Run</th><th scope="col">Option</th><th scope="col">Result</th><th scope="col">Why</th><th scope="col">Note</th></tr></thead>
              <tbody>{log.map((d) => <tr key={d.n} data-decision={d.n} data-status={d.status}><td className="mono">{d.n}</td><td className="mono">{d.run}</td><td>{d.option}</td><td><Chip v={d.status}>{d.status === "refused" ? "refused (audit row)" : "recorded"}</Chip></td><td className="basis">{[...d.reasons, ...d.warnings].join("; ") || "no blocker"}</td><td className="basis">{d.note}</td></tr>)}</tbody>
            </table>
          </Scroll>
        )}
      </section>
      {ds.id === "snapshot" && <Disclosures ds={ds} />}
    </>
  );
}
export function DecisionView() { return <WithData>{(ds) => <Decision ds={ds} />}</WithData>; }
