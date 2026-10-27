import { useState } from "react";
import { Chip, ExportButton, Fig, ParamSelect, Related, Scroll, ScopeStrip, SimNote, ViewHead, WithData } from "../components/ui";
import { Link } from "../components/link";
import type { Dataset } from "../data/dataset";
import { DomainError } from "../domain/errors";
import { checkBasis } from "../domain/rules";
import { queueAt } from "../lib/account";
import { n0, usd } from "../lib/format";
import { useParam } from "../router";
import { markQueue, resetSimulations, tryBasis, useBasisTries, useQueueMarks } from "../state/sim";

export function QueueView() {
  return <WithData>{(ds) => <Queue ds={ds} />}</WithData>;
}

function Queue({ ds }: { ds: Dataset }) {
  const w = ds.primary.world;
  const qat = queueAt(ds);
  const [sid] = useParam("scenario", String(ds.scenarios[0]?.["scenario_id"] ?? ""));
  const scenario = ds.scenarios.find((s) => s["scenario_id"] === sid) ?? ds.scenarios[0];
  const marks = useQueueMarks();
  const tries = useBasisTries();
  const [basis, setBasis] = useState("risk_ranking");
  if (!scenario) return <><ViewHead mark="09 · Queue" title="Outreach queue" contracts="P10-FLOW-08"><p className="notice" data-testid="no-scenario">This dataset has no intervention scenario, so no queue can be drafted.</p></ViewHead><Related /></>;
  const m = ds.setAt(qat, ds.primaryModel, scenario["scenario_id"]);
  const q = m["outreach_queue"] as { account_ids: (string | number)[]; population: number; status: string } | null;
  const eco = m["economics"];
  const stored = w.acc.outreach_events.filter((o) => o["scenario_id"] === scenario["scenario_id"]).sort((a, b) => (a["queue_rank"] ?? 0) - (b["queue_rank"] ?? 0));
  const ranking = ds.primary.world.setRows(qat);
  const prob = new Map(ranking.map((r) => [r.account_id as string | number, w.pred(ds.runId, r.cutoff_id)?.["probability"] as string | undefined]));
  const markOf = (id: string | number): string | undefined => marks.find((x) => x.account_id === id && x.scenario_id === scenario["scenario_id"])?.mark;
  const same = q ? JSON.stringify([...stored.map((s) => String(s["account_id"]))]) === JSON.stringify(q.account_ids.map(String)) : false;
  const mine = marks.filter((x) => x.scenario_id === scenario["scenario_id"]);
  const check = (): void => {
    let code: string | null = null;
    try { checkBasis(basis); } catch (e) { if (!(e instanceof DomainError)) throw e; code = e.code; }
    tryBasis(basis, code);
  };
  const rows = (q?.account_ids ?? []).map((id, i) => ({ rank: i + 1, id, p: prob.get(id) ?? null, a: w.accounts.get(id) }));
  return (
    <>
      <ViewHead mark="09 · Queue" title="Outreach queue" contracts="P10-FLOW-08, P10-FLOW-09, P10-TEST-09, P10-TEST-10, D-03, D-05">
        <p className="lede">The queue is the top K accounts by risk, limited by capacity. Every action is a <strong>draft</strong>: a proposal to look at an account. Nothing is sent, scheduled or promised.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["scenario", String(scenario["scenario_id"])], ["population", `${n0(q?.population ?? 0)} scored eligible accounts at ${qat.slice(0, 10)}, outcomes unknown`], ["status", "draft only, sent: 0"]]} />
      <SimNote>The review marks below are simulated in browser memory and are gone on reload. The published queue does not change, no message exists, and reviewing an account does not mean it would respond to anything.</SimNote>
      <div className="controls">
        <ParamSelect name="scenario" label="Scenario" dflt={String(ds.scenarios[0]!["scenario_id"])} options={ds.scenarios.map((s) => ({ value: s["scenario_id"], label: `${s["scenario_id"]} · K ${s["capacity"]}` }))} testid="scenario-select" />
        <button type="button" className="button--quiet" onClick={resetSimulations} data-testid="reset-marks">Reset the simulation</button>
      </div>
      <div className="grid" data-testid="queue-figures">
        <div className="card"><div className="big"><Fig k="queue-k">{q?.account_ids.length ?? 0}</Fig><small>draft actions of K = {scenario["capacity"]}</small></div></div>
        <div className="card"><div className="big"><Fig k="queue-sent">0</Fig><small>sent: nothing is ever sent</small></div></div>
        {eco && <div className="card"><div className="big"><Fig k="queue-budget">{usd(eco.contact_budget)}</Fig><small>contact budget</small></div></div>}
        {eco && <div className="card"><div className="big"><Fig k="queue-ev" tone={eco.expected_value.startsWith("-") ? "neg" : "pos"}>{usd(eco.expected_value)}</Fig><small>expected value, hypothetical (assumed effect {scenario["assumed_effect"]}), on the {n0(q?.population ?? 0)} scored accounts of the published cohort; no treatment effect is estimated</small></div></div>}
      </div>
      <section aria-labelledby="q-h">
        <h2 id="q-h">Draft queue</h2>
        {q === null ? <p className="notice" data-testid="queue-refused">The capacity {scenario["capacity"]} exceeds the scored population, so no queue is drafted (CAPACITY_EXCEEDS_POPULATION).</p> : (
          <Scroll label="Draft outreach queue">
            <table data-testid="queue-table">
              <caption>Ranked by risk descending, ties by account id. Action: propose_contact, status draft. Marks are the simulation. {same ? <Chip kind="ok">equals the {stored.length} published draft rows</Chip> : <Chip kind="risk">differs from the published draft rows</Chip>}</caption>
              <thead><tr><th scope="col">Rank</th><th scope="col">Account</th><th scope="col">Risk</th><th scope="col">Plan · region</th><th scope="col">Action</th><th scope="col">Status</th><th scope="col">Review (simulated)</th></tr></thead>
              <tbody>{rows.map((r) => { const mk = markOf(r.id); return (
                <tr key={String(r.id)} data-account={String(r.id)} data-mark={mk ?? ""}>
                  <td className="l">{r.rank}</td><td><Link to={`account?account=${r.id}`}>{String(r.id)}</Link></td><td data-k="risk">{r.p ?? "—"}</td><td className="t">{r.a ? `${r.a["segment"]} · ${r.a["region"]}` : "—"}</td><td className="t">propose_contact</td><td className="t"><Chip kind="plain">draft</Chip></td>
                  <td className="t">
                    {mk ? <Chip kind="note">{mk}</Chip> : null}{" "}
                    {(["reviewed", "held", "dropped"] as const).map((x) => <button key={x} type="button" className="button--quiet" style={{ minHeight: 32, padding: ".15rem .5rem", marginRight: 4 }} aria-label={`Mark account ${r.id} ${x} (simulated)`} aria-pressed={mk === x} onClick={() => markQueue(r.id, String(scenario["scenario_id"]), x)}>{x}</button>)}
                  </td>
                </tr>); })}</tbody>
            </table>
          </Scroll>
        )}
        <p data-testid="marks-summary">Simulated marks on this queue: {mine.length === 0 ? "none" : (["reviewed", "held", "dropped"] as const).map((x) => `${mine.filter((y) => y.mark === x).length} ${x}`).join(", ")}. Still draft: {(q?.account_ids.length ?? 0)}; sent: 0.</p>
        <p><ExportButton ds={ds} name={`queue-${scenario["scenario_id"]}`} scope={`scenario=${scenario["scenario_id"]}; draft only; simulated marks excluded`} header={["rank", "account_id", "risk", "action", "status"]} rows={rows.map((r) => [r.rank, String(r.id), r.p, "propose_contact", "draft"])} /></p>
      </section>
      <section className="panel" data-testid="basis" aria-labelledby="basis-h">
        <h2 id="basis-h">What the queue is based on</h2>
        <p>The only accepted basis is the <strong>risk ranking</strong>. A queue that claimed to rank by who would respond to an offer (responsiveness, uplift) is refused <code>RISK_NOT_RESPONSIVENESS</code>: a churn risk says who is likely to leave, and says nothing about who an offer would keep. Try it; this runs the domain's rule in your browser.</p>
        <div className="controls">
          <label className="field">Basis claimed
            <select value={basis} onChange={(e) => setBasis(e.target.value)} data-testid="basis-select">
              <option value="risk_ranking">risk_ranking</option><option value="responsiveness">responsiveness</option><option value="uplift">uplift</option>
            </select>
          </label>
          <button type="button" onClick={check} data-testid="basis-check">Draft a queue on this basis</button>
        </div>
        <ol className="steps" data-testid="basis-log" aria-live="polite">{tries.map((t) => <li key={t.n}>{t.basis}: {t.code ? <Chip kind="risk">refused {t.code}</Chip> : <Chip kind="ok">accepted as a draft; nothing sent</Chip>}</li>)}</ol>
        {tries.length === 0 && <p className="mono">No request yet.</p>}
      </section>
      <Related also={["capacity", "account"]} />
    </>
  );
}
