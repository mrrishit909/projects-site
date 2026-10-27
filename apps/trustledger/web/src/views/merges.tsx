import { useState } from "react";
import { Chip, Choice, Def, Fig, Pager, Scroll, SimNote, usePage, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/models";
import { dayTime } from "../lib/format";
import { useParam } from "../router";
import { addSimReversal, useSimReversals } from "../state/sim";

function Detail({ ds, h, decision }: { ds: Dataset; h: Row; decision: Row | undefined }) {
  const log = useSimReversals();
  const [reason, setReason] = useState("");
  const rev = ds.raw.merge_decisions.find((m) => m["merge_id"] === h["reversed_by"]);
  const name = (id: string): string => (ds.byId.owners.get(id)?.["owner_name"] as string | undefined) ?? id;
  const map = ds.now.matching["identity_map"] as Record<string, string>;
  const mine = log.filter((e) => e.merge_id === h["merge_id"]);
  const simOk = mine.some((e) => e.status === "recorded");
  const state: string = h["state"];
  const from = h["from_record_id"] as string, to = h["to_record_id"] as string;
  const submit = (): void => {
    const base = { merge_id: h["merge_id"] as string };
    if (state === "reversed" || simOk) addSimReversal({ ...base, status: "refused", code: "ALREADY_REVERSED", note: "A merge is reversed once; the reversal is already on record." });
    else if (!reason.trim()) addSimReversal({ ...base, status: "refused", code: "INVALID_REVERSAL", note: "A reversal needs a reason." });
    else addSimReversal({ ...base, status: "recorded", code: null, note: `Simulated reversal: ${from} and ${to} would each map to themselves again, and ${h["merge_id"]} would stay in the history as reversed. Nothing was changed.` });
  };
  const after = state === "reversed" || simOk;
  return (
    <section className="block" data-testid="merge-detail" data-merge={h["merge_id"]} aria-labelledby="md">
      <h2 id="md"><span className="mono">{h["merge_id"]}</span> {state === "active" && !simOk ? <Chip kind="ok">active</Chip> : <Chip kind="hatch">reversed{simOk && state !== "reversed" ? " (simulated)" : ""}</Chip>}</h2>
      <p>Candidate <span className="mono">{h["candidate_id"]}</span>: a merge maps the <strong>right</strong> record to the <strong>left</strong> one. {decision && <>Approved by {name(decision["reviewer_id"])} at <span className="mono">{dayTime(decision["decided_at"])}</span>.</>}</p>
      <Scroll label="Mapping before and after"><table data-testid="mapping">
        <thead><tr><th scope="col">Record</th><th scope="col">Identity map when approved</th><th scope="col">Identity map now</th></tr></thead>
        <tbody>
          <tr><th scope="row" className="mono">{from}</th><td className="mono">{from} → {to}</td><td className="mono" data-k="from-now">{after ? `${from} → ${from} (restored)` : `${from} → ${map[from]}`}</td></tr>
          <tr><th scope="row" className="mono">{to}</th><td className="mono">{to} → {to}</td><td className="mono" data-k="to-now">{to} → {to}</td></tr>
        </tbody>
      </table></Scroll>
      {state === "reversed" && rev && <p data-testid="reversal">Reversed by {name(rev["reviewer_id"])} at <span className="mono">{dayTime(rev["decided_at"])}</span> (<span className="mono">{rev["merge_id"]}</span>): “{rev["reason"]}”. Reversal restores both source identities and keeps the mapping history: the approval and the reversal both remain on record.</p>}
      {state === "active" && (<>
        <h3>Reverse this merge (simulated)</h3>
        <SimNote>Nothing is reversed or merged; this shows how the rules answer and what the identity map would read.</SimNote>
        <label className="field">Reason for the reversal<textarea value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason for the reversal" data-testid="reversal-reason" /></label>
        <div className="btn-row"><button type="button" onClick={submit} data-testid="simulate-reversal">Simulate reversal</button></div>
      </>)}
      {mine.length > 0 && <ul className="sim-log" data-testid="reversal-log">{mine.map((e) => <li key={e.n} data-status={e.status}><Chip kind={e.status === "recorded" ? "ok" : "note"}>{e.status}</Chip>{e.code ? <> <span className="mono">{e.code}</span></> : ""} {e.note}</li>)}</ul>}
    </section>
  );
}

function Merges({ ds }: { ds: Dataset }) {
  const mt = ds.now.matching;
  const hist = mt["mapping_history"] as Row[];
  const pr = ds.now.metrics["match_precision"];
  const [st, setSt] = useParam("state", "all");
  const dflt = (hist.find((h) => h["state"] === "reversed") ?? hist[0])?.["merge_id"] as string | undefined;
  const [sel, setSel] = useParam("merge", dflt ?? "");
  const cur = hist.find((h) => h["merge_id"] === sel) ?? hist.find((h) => h["merge_id"] === dflt);
  const list = hist.filter((h) => st === "all" || h["state"] === st);
  const pg = usePage("page", 10, list.length);
  const dec = new Map(ds.raw.merge_decisions.map((m) => [m["merge_id"] as string, m]));
  const reversals = ds.raw.merge_decisions.filter((m) => m["decision"] === "reverse");
  const n = (v: unknown): string => (v === null || v === undefined ? "unknown" : String(v));
  return (
    <>
      <section className="block" data-testid="merge-summary" aria-labelledby="ms">
        <h2 id="ms">Mappings and what they restore</h2>
        <div className="tiles">
          <div className="tile"><b data-figure="candidates">{mt["candidates"]}</b><span>candidates</span></div>
          <div className="tile"><b data-figure="reviewed">{mt["reviewed"]}</b><span>reviewed ({mt["approved"]} approved, {mt["rejected"]} rejected)</span></div>
          <div className="tile"><b data-figure="active">{mt["active_merges"]}</b><span>merges in force</span></div>
          <div className="tile"><b data-figure="reversed">{mt["merges_reversed"]}</b><span>merges reversed</span></div>
        </div>
        <p>A merge is a human decision with a reviewer, and it is reversible: a reversal restores both source identities and keeps the mapping history. {reversals.length} reversal decisions are stored beside {ds.raw.merge_decisions.length - reversals.length} approve and reject decisions.</p>
      </section>
      <section className="block" data-testid="verification" aria-labelledby="vf">
        <h2 id="vf">Match precision, from the verification layer</h2>
        <div className="pair-fig">
          <div><span className="big"><Fig k="precision">{pr["precision"] ?? "unknown"}</Fig></span><span className="cap">precision: {n(pr["approved_correct"])} of {pr["approved_decisions"]} approved decisions confirmed as one entity by the <Def term="synthetic truth">The generator knows which records are the same synthetic person and stores that only in the manifest’s verification block. The matcher, the candidates and the merge pages never read it; only this precision figure does, and a reversal does not remove the earlier approval from the ratio.</Def></span></div>
          <div><span className="big"><Fig k="reviewed-share">{pr["reviewed_correct_share"] ?? "unknown"}</Fig></span><span className="cap">reviewed_correct_share: {n(pr["reviewed_correct"])} of {pr["reviewed"]} reviewed pairs (approved and rejected). A different figure, labelled apart so nobody reads it as precision.</span></div>
        </div>
        <p className="muted">The figure comes from synthetic match truth held outside the matcher; it says nothing about real people.</p>
      </section>
      {cur && <Detail ds={ds} h={cur} decision={dec.get(cur["merge_id"])} />}
      <section className="block" aria-labelledby="hist" data-testid="merge-list">
        <h2 id="hist">Merge history ({list.length})</h2>
        <Choice name="state" legend="State" value={st} onChange={setSt} testid="merge-state" options={[{ value: "all", label: `All (${hist.length})` }, { value: "active", label: `Active (${hist.filter((h) => h["state"] === "active").length})` }, { value: "reversed", label: `Reversed (${hist.filter((h) => h["state"] === "reversed").length})` }]} />
        <Scroll label="Merge history"><table>
          <thead><tr><th scope="col">Merge</th><th scope="col">Candidate</th><th scope="col">Maps</th><th scope="col">State</th><th scope="col">Reversed by</th></tr></thead>
          <tbody>{list.slice(pg.from, pg.to).map((h) => { const id = h["merge_id"] as string; return (
            <tr key={id} data-merge={id} className={id === cur?.["merge_id"] ? "is-sel" : ""}>
              <th scope="row"><a className="mono" href={`?merge=${id}`} aria-current={id === cur?.["merge_id"] ? "true" : undefined} onClick={(e) => { e.preventDefault(); setSel(id); window.scrollTo(0, 0); }}>{id}</a></th>
              <td className="mono">{h["candidate_id"]}</td><td className="mono">{h["from_record_id"]} → {h["to_record_id"]}</td>
              <td>{h["state"] === "active" ? <Chip kind="ok">active</Chip> : <Chip kind="hatch">reversed</Chip>}</td><td className="mono">{h["reversed_by"] ?? "none"}</td>
            </tr>); })}</tbody>
        </table></Scroll>
        <Pager {...pg} total={list.length} label="Merges" />
      </section>
    </>
  );
}

export function MergesView() {
  return (
    <>
      <ViewHead mark="Shelfmark 08 · merges" title="Merge history">
        <p className="lede">Every approved merge is a mapping from the right record to the left, and every mapping can be undone. The history keeps both.</p>
      </ViewHead>
      <WithData>{(ds) => <Merges ds={ds} />}</WithData>
    </>
  );
}
