import { useState } from "react";
import { Chip, Choice, Def, Pager, Scroll, SimNote, usePage, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/models";
import { candidateStates, type CandidateState } from "../lib/derive";
import { dayTime } from "../lib/format";
import { useParam } from "../router";
import { addSimReview, useSimReviews } from "../state/sim";

const stateChip = (s: CandidateState) => s === "approved" ? <Chip kind="ok">approved</Chip> : s === "rejected" ? <Chip kind="note">rejected</Chip> : s === "reversed" ? <Chip kind="hatch">approved, then reversed</Chip> : <Chip kind="plain">unreviewed</Chip>;
const FIELDS: [string, string][] = [["record_id", "Record"], ["source_system", "Source system"], ["source_customer_id", "Source customer id"], ["normalized_name", "Normalised name"], ["address_key", "Address key"]];

function Detail({ ds, cand }: { ds: Dataset; cand: Row }) {
  const states = candidateStates(ds);
  const st = states.get(cand["candidate_id"])!;
  const log = useSimReviews();
  const [reviewer, setReviewer] = useState("");
  const [decision, setDecision] = useState<"approve" | "reject">("approve");
  const left = ds.byId.records.get(cand["left_record_id"])!, right = ds.byId.records.get(cand["right_record_id"])!;
  const owners = ds.raw.owners;
  const name = (id: string): string => (ds.byId.owners.get(id)?.["owner_name"] as string | undefined) ?? id;
  const mine = log.filter((e) => e.candidate_id === cand["candidate_id"]);
  const features = Object.entries(cand["features"] as Record<string, string>);
  const submit = (): void => {
    const rid = reviewer || (owners[0]!["owner_id"] as string);
    const rev = ds.byId.owners.get(rid)!;
    const base = { candidate_id: cand["candidate_id"] as string, reviewer_id: rid, decision };
    const reviewedBefore = st.state !== "unreviewed" || mine.some((e) => e.status === "recorded");
    if (rid === cand["proposed_by"]) addSimReview({ ...base, status: "refused", code: "REVIEWER_IS_PROPOSER", note: "A merge needs an independent human decision: the reviewer cannot be the proposer of the pair." });
    else if (!(rev["role"] === "steward" || rev["role"] === "admin") || !rev["active"]) addSimReview({ ...base, status: "refused", code: "ROLE_NOT_PERMITTED", note: `${rev["owner_name"]} is ${rev["active"] ? "" : "inactive and "}a${/^[aeiou]/.test(rev["role"]) ? "n" : ""} ${rev["role"]}; only an active steward or admin can review a pair.` });
    else if (reviewedBefore) addSimReview({ ...base, status: "refused", code: "ALREADY_REVIEWED", note: "This pair already has a decision; one decision per candidate (a reversal is a separate step on the merge history)." });
    else addSimReview({ ...base, status: "recorded", code: null, note: decision === "approve" ? `Recorded as a simulated approval. Nothing was merged: if it were real, ${cand["right_record_id"]} would map to ${cand["left_record_id"]}, reversibly, and the identity map shown on the merge history is unchanged.` : "Recorded as a simulated rejection. Nothing changed." });
  };
  return (
    <section className="block" data-testid="candidate-detail" data-candidate={cand["candidate_id"]} aria-labelledby="cd">
      <h2 id="cd"><span className="mono">{cand["candidate_id"]}</span> {stateChip(st.state)}</h2>
      <p>Proposed with score <span className="mono" data-testid="score">{cand["score"]}</span>: {cand["explanation"]}. Proposed by {name(cand["proposed_by"])} at <span className="mono">{dayTime(cand["proposed_at"])}</span>.</p>
      {cand["uncertainty"] && (
        <div className="uncertainty" data-testid="uncertainty" role="note">
          <strong>Uncertainty: {cand["uncertainty"]}.</strong> Two different people can share a name and an address (a household). The records alone cannot tell, so this pair is a candidate with explicit uncertainty and is <strong>never merged automatically</strong>; a person decides.
        </div>
      )}
      <h3>The two records, side by side</h3>
      <Scroll label="Records side by side"><table className="sbs" data-testid="side-by-side">
        <thead><tr><th scope="col">Field</th><th scope="col">Left (kept)</th><th scope="col">Right (would map to left)</th><th scope="col">Compare</th></tr></thead>
        <tbody>{FIELDS.map(([k, label]) => { const eq = left[k] === right[k]; return (
          <tr key={k} data-field={k}><th scope="row">{label}</th><td className={`mono ${eq ? "same" : "differs"}`}>{left[k]}</td><td className={`mono ${eq ? "same" : "differs"}`}>{right[k]}</td><td data-k="compare">{eq ? "same" : "differs"}</td></tr>); })}</tbody>
      </table></Scroll>
      <h3>Evidence behind the score</h3>
      <ul data-testid="features">{features.map(([k, v]) => <li key={k}><span className="mono">{k}</span>: <span className="mono">{v}</span></li>)}</ul>
      <h3>What has been decided</h3>
      <ul data-testid="decisions">
        {!st.approve && !st.reject && <li>No decision yet. Unreviewed candidates are never merged.</li>}
        {st.approve && <li>Approved by {name(st.approve["reviewer_id"])} at <span className="mono">{dayTime(st.approve["decided_at"])}</span> (<span className="mono">{st.approve["merge_id"]}</span>).</li>}
        {st.reject && <li>Rejected by {name(st.reject["reviewer_id"])} at <span className="mono">{dayTime(st.reject["decided_at"])}</span> (<span className="mono">{st.reject["merge_id"]}</span>).</li>}
        {st.reversal && <li>Reversed by {name(st.reversal["reviewer_id"])} at <span className="mono">{dayTime(st.reversal["decided_at"])}</span> (<span className="mono">{st.reversal["merge_id"]}</span>): “{st.reversal["reason"]}”. Both identities were restored and the history kept.</li>}
      </ul>
      <h3>Review this pair (simulated)</h3>
      <SimNote>There is no button on this site that merges anything. This form only shows how the rules would answer: a recorded review changes nothing in the data, the identity map or any figure.</SimNote>
      <div className="form-row">
        <label className="field">Reviewer
          <select value={reviewer || (owners[0]!["owner_id"] as string)} onChange={(e) => setReviewer(e.target.value)} aria-label="Reviewer" data-testid="reviewer">
            {owners.map((o) => <option key={o["owner_id"]} value={o["owner_id"]}>{o["owner_name"]} · {o["role"]}{o["active"] ? "" : " (inactive)"}{o["owner_id"] === cand["proposed_by"] ? " · proposer" : ""}</option>)}
          </select>
        </label>
        <Choice name="decision" legend="Decision" value={decision} onChange={(v) => setDecision(v === "reject" ? "reject" : "approve")} testid="decision-choice" options={[{ value: "approve", label: "Approve as the same person" }, { value: "reject", label: "Reject" }]} />
      </div>
      <div className="btn-row"><button type="button" onClick={submit} data-testid="record-review">Record simulated review</button></div>
      {mine.length > 0 && <ul className="sim-log" data-testid="review-log">{mine.map((e) => <li key={e.n} data-status={e.status}><Chip kind={e.status === "recorded" ? "ok" : "note"}>{e.status}</Chip> {name(e.reviewer_id)} · {e.decision}{e.code ? <> · <span className="mono">{e.code}</span></> : ""}: {e.note}</li>)}</ul>}
    </section>
  );
}

function Duplicates({ ds }: { ds: Dataset }) {
  const states = candidateStates(ds);
  const [st, setSt] = useParam("state", "all");
  const [unc, setUnc] = useParam("unc", "0");
  const cands = ds.raw.match_candidates;
  const dflt = (cands.find((c) => c["uncertainty"]) ?? cands[0])!["candidate_id"] as string;
  const [sel, setSel] = useParam("c", dflt);
  const cand = ds.byId.candidates.get(sel) ?? ds.byId.candidates.get(dflt)!;
  const list = cands.filter((c) => (st === "all" || states.get(c["candidate_id"])!.state === st) && (unc !== "1" || c["uncertainty"]));
  const pg = usePage("page", 10, list.length);
  const count = (s: CandidateState): number => cands.filter((c) => states.get(c["candidate_id"])!.state === s).length;
  const withUnc = cands.filter((c) => c["uncertainty"]).length;
  return (
    <>
      <section className="block" aria-labelledby="not-auto" data-testid="no-auto-merge">
        <h2 id="not-auto">Nothing is merged automatically</h2>
        <p>{cands.length} candidate pairs were proposed from distinct source records. {withUnc} of them carry an explicit uncertainty note because they share a name and an address. <Def term="why">Identity is a decision, not a calculation. A shared name and address can be one person or two members of a household, so a candidate is only ever proposed; a person reviews it, and a merge is reversible.</Def></p>
        <div className="tiles">
          <div className="tile"><b data-figure="unreviewed">{count("unreviewed")}</b><span>unreviewed</span></div>
          <div className="tile"><b data-figure="approved">{count("approved")}</b><span>approved, in force</span></div>
          <div className="tile"><b data-figure="reversed">{count("reversed")}</b><span>approved, then reversed</span></div>
          <div className="tile"><b data-figure="rejected">{count("rejected")}</b><span>rejected</span></div>
        </div>
      </section>
      <Detail ds={ds} cand={cand} />
      <section className="block" aria-labelledby="lst" data-testid="candidate-list">
        <h2 id="lst">Candidates</h2>
        <div className="controls">
          <Choice name="state" legend="State" value={st} onChange={setSt} testid="state-filter" options={[{ value: "all", label: "All" }, { value: "unreviewed", label: "Unreviewed" }, { value: "approved", label: "Approved" }, { value: "rejected", label: "Rejected" }, { value: "reversed", label: "Reversed" }]} />
          <Choice name="unc" legend="Uncertainty note" value={unc} onChange={setUnc} testid="unc-filter" options={[{ value: "0", label: "Any" }, { value: "1", label: `Shared name and address (${withUnc})` }]} />
        </div>
        <Scroll label="Candidate pairs"><table>
          <thead><tr><th scope="col">Candidate</th><th scope="col">Pair</th><th scope="col" className="num">Score</th><th scope="col">Uncertainty</th><th scope="col">State</th></tr></thead>
          <tbody>{list.slice(pg.from, pg.to).map((c) => { const id = c["candidate_id"] as string; return (
            <tr key={id} data-candidate={id} className={id === cand["candidate_id"] ? "is-sel" : ""}>
              <th scope="row"><a className="mono" href={`?c=${id}`} aria-current={id === cand["candidate_id"] ? "true" : undefined} onClick={(e) => { e.preventDefault(); setSel(id); window.scrollTo(0, 0); }}>{id}</a></th>
              <td className="mono">{c["left_record_id"]} · {c["right_record_id"]}</td><td className="num mono">{c["score"]}</td><td>{c["uncertainty"] ? <Chip kind="hatch">shared name and address</Chip> : <span className="muted">none recorded</span>}</td><td>{stateChip(states.get(id)!.state)}</td>
            </tr>); })}</tbody>
        </table></Scroll>
        <Pager {...pg} total={list.length} label="Candidates" />
      </section>
    </>
  );
}

export function DuplicatesView() {
  return (
    <>
      <ViewHead mark="Shelfmark 07 · duplicates" title="Duplicate review">
        <p className="lede">Two customer records that look alike are laid side by side with the evidence and the doubt. A pair is stored once, in canonical order, and a decision belongs to a person other than the one who proposed it.</p>
      </ViewHead>
      <WithData>{(ds) => <Duplicates ds={ds} />}</WithData>
    </>
  );
}
