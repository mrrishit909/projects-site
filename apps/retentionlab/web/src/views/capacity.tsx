import { useMemo } from "react";
import { Legend, PrCapacityChart } from "../components/charts";
import { Chip, Def, ExportButton, Fig, ParamSelect, Related, Scroll, ScopeStrip, SimNote, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { cumulativeHits } from "../domain/metrics";
import type { Row } from "../domain/models";
import { cmpFr, p6, parseFraction, ratio } from "../domain/num";
import { queueAt } from "../lib/account";
import { ecoAt, kAt, REFUSAL_K, seriesOf } from "../lib/derive";
import { n0, orDash, usd } from "../lib/format";
import { resetSimulations, setSimScenario, useSimScenario, type Scenario } from "../state/sim";
import { useParam } from "../router";

export function CapacityView() {
  return <WithData>{(ds) => <Capacity ds={ds} />}</WithData>;
}

const DEC = /^\d+(\.\d+)?$/;
const toScenario = (r: Row): Scenario => ({ k: String(r["capacity"]), contact_cost: r["contact_cost"], assumed_effect: r["assumed_effect"], margin_value: r["margin_value"] });

function Capacity({ ds }: { ds: Dataset }) {
  const [pid] = useParam("pop", ds.populations[0]!.id);
  const pop = ds.populations.find((p) => p.id === pid) ?? ds.populations[0]!;
  const pub = toScenario(ds.scenarios[0]!);
  const sim = useSimScenario();
  const sc = sim ?? pub;
  const items = useMemo(() => seriesOf(pop, ds.primarySeries), [pop, ds.primarySeries]);
  const hits = useMemo(() => cumulativeHits(items), [items]);
  const n = items.length, positives = hits.length ? hits[n - 1]! : 0;
  const set = (patch: Partial<Scenario>): void => setSimScenario({ ...sc, ...patch });
  const kNum = /^\d+$/.test(sc.k.trim()) ? Number(sc.k.trim()) : NaN;
  const kRes = Number.isNaN(kNum) ? null : kAt(items, kNum);
  const effectOk = DEC.test(sc.assumed_effect) && cmpFr(parseFraction(sc.assumed_effect, false), parseFraction("1")) <= 0;
  const moneyOk = DEC.test(sc.contact_cost) && DEC.test(sc.margin_value);
  const eco = kRes && kRes !== REFUSAL_K && effectOk && moneyOk ? ecoAt(items, kNum, { contact_cost: sc.contact_cost, assumed_effect: sc.assumed_effect, margin_value: sc.margin_value }) : null;
  const pts = useMemo(() => [...new Set([1, 2, 5, 10, 20, 50, 100, 200, 500, ...(Number.isNaN(kNum) ? [] : [kNum])])].filter((k) => k >= 1 && k <= n).sort((a, b) => a - b), [kNum, n]);
  const rowsAt = pts.map((k) => ({ k, r: kAt(items, k) as Exclude<ReturnType<typeof kAt>, string>, e: effectOk && moneyOk ? ecoAt(items, k, { contact_cost: sc.contact_cost, assumed_effect: sc.assumed_effect, margin_value: sc.margin_value }) : null }));
  const qat = queueAt(ds);
  const claims = ds.manifest?.["published_cohort"]?.["economics"] as Record<string, Row> | undefined;
  const fullWorld = ds.aggregates?.["economics_full_world"] as Row | undefined;                      // D-09 (R10-04): the same scenarios on the whole 2,400-account world
  const fw = (id: string): Row | undefined => (fullWorld?.["scenarios"] as Record<string, Row> | undefined)?.[id];
  const queueRows = ds.scenarios.map((r) => ({ r, m: ds.setAt(qat, ds.primaryModel, r["scenario_id"]) })).filter((x) => x.m["economics"]);
  const markers = ds.scenarios.map((r) => r["capacity"] as number);
  const exportRows = rowsAt.map(({ k, r, e }) => [k, r.hits, r.precision, r.recall, r.lift, r.tie_split ? "yes" : "no", e && e !== REFUSAL_K ? e.contact_budget : null, e && e !== REFUSAL_K ? e.expected_value : null]);
  return (
    <>
      <ViewHead mark="06 · Capacity" title="Capacity planner" contracts="P10-MET-02, P10-MET-03, P10-MET-07, P10-MET-08, P10-MET-09, P10-FLOW-09, P10-TEST-06, P10-TEST-10, D-03, D-05 (D-P10-03/04/13)">
        <p className="lede">A team can contact K accounts, not all of them. Rank the accounts by risk, take the top K, and ask how many of them really churn (precision), how many of all the churners that catches (recall), and what the contacts cost.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["population", pop.detail], ["ranking", "risk descending, ties by account id ascending"], ["K chosen on", "validation in the product (K is fixed before any outcome here); the test set is read once"]]} />
      <SimNote>The planner is a simulation: changing K, the cost, the assumed effect or the margin recomputes the figures below in this page only. Nothing is sent to any customer, no queue is created, and a reload restores the published scenario.</SimNote>
      <section className="panel" aria-labelledby="sc-h">
        <h2 id="sc-h">Scenario</h2>
        <div className="controls">
          <ParamSelect name="pop" label="Evaluation population" dflt={ds.populations[0]!.id} options={ds.populations.map((p) => ({ value: p.id, label: p.label }))} testid="pop-select" />
          <label className="field">Capacity K (accounts to contact)
            <input type="number" inputMode="numeric" min={1} step={1} value={sc.k} onChange={(e) => set({ k: e.target.value })} data-testid="k-input" aria-describedby="k-msg" />
          </label>
          <label className="field">Contact cost (USD each)
            <input type="text" inputMode="decimal" value={sc.contact_cost} onChange={(e) => set({ contact_cost: e.target.value })} data-testid="cost-input" />
          </label>
          <label className="field">Assumed effect (0 to 1)
            <input type="text" inputMode="decimal" value={sc.assumed_effect} onChange={(e) => set({ assumed_effect: e.target.value })} data-testid="effect-input" />
          </label>
          <label className="field">Margin per retained account (USD)
            <input type="text" inputMode="decimal" value={sc.margin_value} onChange={(e) => set({ margin_value: e.target.value })} data-testid="margin-input" />
          </label>
        </div>
        <div className="controls">
          {ds.scenarios.map((r) => <button key={r["scenario_id"]} type="button" className="button--quiet" onClick={() => setSimScenario(toScenario(r))} data-testid={`preset-${r["scenario_id"]}`}>Use {r["scenario_id"]} (K {r["capacity"]})</button>)}
          <button type="button" onClick={resetSimulations} data-testid="reset-sim">Reset to the published scenario</button>
          <span data-testid="sim-state"><Chip kind={sim ? "note" : "plain"}>{sim ? "simulated, not published" : "published scenario"}</Chip></span>
        </div>
        <p id="k-msg" role="status" data-testid="k-message">
          {Number.isNaN(kNum) ? <><Chip kind="risk">K must be a whole number from 1</Chip></> : kRes === REFUSAL_K ? <><Chip kind="risk">CAPACITY_EXCEEDS_POPULATION</Chip> K = {n0(kNum)} is outside 1 to {n0(n)}, the rows of this population; no metric is shown for it.</> : <>K = {n0(kNum)} of {n0(n)} rows.</>}
          {!effectOk && <> <Chip kind="risk">ASSUMED_EFFECT_OUT_OF_RANGE</Chip> the assumed effect must be a number from 0 to 1.</>}
          {!moneyOk && <> <Chip kind="risk">enter the cost and the margin as plain numbers</Chip></>}
        </p>
        <p><Def term="Assumed effect">The assumed share of an account's churn risk that an intervention removes, so the retained probability is risk × effect. It is an assumption, not an estimate: nothing here measures whether an offer works.</Def></p>
      </section>
      {kRes && kRes !== REFUSAL_K ? (
        <section aria-labelledby="pr-h">
          <h2 id="pr-h">Precision and recall at capacity K = <Fig k="k">{n0(kNum)}</Fig></h2>
          <div className="two">
            <figure className="figure">
              <PrCapacityChart n={n} hits={hits} k={kNum} markers={markers} prevalence={p6(ratio(positives, n))} caption={`Precision and recall at K for K from 1 to ${n} in ${pop.label}`} />
              <figcaption>Coral: precision at K (churners in the top K ÷ K). Teal: recall at K (churners in the top K ÷ all {n0(positives)} churners). Log scale in K; gold ticks are the published capacities. The dashed line is the churn rate of the whole population, what a random contact list would score.</figcaption>
              <Legend items={[{ label: "precision at K", color: "#ef7a6a" }, { label: "recall at K", color: "#7fc8b8" }]} />
            </figure>
            <div data-testid="k-results">
              <div className="card"><div className="big"><Fig k="precision">{kRes.precision}</Fig><small>precision at K: {kRes.hits} true churners among the top {n0(kNum)}</small></div></div>
              <div className="card" style={{ marginTop: ".6rem" }}><div className="big"><Fig k="recall">{orDash(kRes.recall, "no churners")}</Fig><small>recall at K: {kRes.hits} of {n0(positives)} churners reached</small></div></div>
              <div className="card" style={{ marginTop: ".6rem" }}><div className="big"><Fig k="lift">{orDash(kRes.lift, "no churners")}</Fig><small>risk lift: top-K churn rate ÷ overall churn rate. A ranking statistic, not treatment uplift.</small></div></div>
              {kRes.tie_split && <p className="note" data-testid="tie-note"><strong>Tie across rank K.</strong> Several accounts share the probability at rank {n0(kNum)} and the list cuts through them; the documented rule takes the lower account id first, so precision at K depends on that rule.</p>}
            </div>
          </div>
          <div className="card" data-testid="budget" aria-labelledby="budget-h">
            <h3 id="budget-h">Contact budget beside it <Chip kind="note">simulated</Chip></h3>
            {eco && eco !== REFUSAL_K ? (
              <>
                <p className="big"><Fig k="budget">{usd(eco.contact_budget)}</Fig><small>contact budget = K × contact cost = {n0(kNum)} × {usd(sc.contact_cost)}</small></p>
                <p className="big"><Fig k="ev" tone={eco.expected_value.startsWith("-") ? "neg" : "pos"}>{usd(eco.expected_value)}</Fig><small>expected intervention value, <strong>hypothetical</strong>: the sum over the top {n0(kNum)} of risk × {sc.assumed_effect} × {usd(sc.margin_value)} − {usd(sc.contact_cost)}, rounded once. Not a forecast; it rests on the assumed effect.</small></p>
              </>
            ) : <p>Enter a valid K, cost, effect and margin to see the budget and the hypothetical value.</p>}
          </div>
        </section>
      ) : (
        <p className="notice" role="status" data-testid="no-k-result">{kRes === REFUSAL_K ? "K is outside the population, so no precision, recall or lift is shown. Lower K or pick a larger population." : "Enter a whole number for K."}</p>
      )}
      <section aria-labelledby="tbl-h">
        <h2 id="tbl-h">The same curve as a table</h2>
        <Scroll label="Precision and recall at K">
          <table data-testid="k-table">
            <caption>Selected capacities of {pop.label}. Budget and value use the scenario above; the value is hypothetical.</caption>
            <thead><tr><th scope="col">K</th><th scope="col">Churners in top K</th><th scope="col">Precision</th><th scope="col">Recall</th><th scope="col">Lift</th><th scope="col">Tie at K</th><th scope="col">Budget (USD)</th><th scope="col">Expected value (USD, hypothetical)</th></tr></thead>
            <tbody>{rowsAt.map(({ k, r, e }) => (
              <tr key={k} data-k-row={k} className={k === kNum ? "is-active" : ""}><td className="l">{n0(k)}</td><td>{r.hits}</td><td>{r.precision}</td><td>{orDash(r.recall, "no churners")}</td><td>{orDash(r.lift, "no churners")}</td><td className="t">{r.tie_split ? <Chip kind="note">tie</Chip> : "no"}</td>
                <td>{e && e !== REFUSAL_K ? e.contact_budget : "—"}</td><td className={e && e !== REFUSAL_K && e.expected_value.startsWith("-") ? "neg" : ""}>{e && e !== REFUSAL_K ? e.expected_value : "—"}</td></tr>
            ))}</tbody>
          </table>
        </Scroll>
        <p><ExportButton ds={ds} name="capacity" scope={`${pop.id}; K=${sc.k}; cost=${sc.contact_cost}; effect=${sc.assumed_effect}; margin=${sc.margin_value} (simulated, hypothetical)`} header={["k", "hits", "precision", "recall", "lift", "tie_at_k", "contact_budget", "expected_value_hypothetical"]} rows={exportRows} /></p>
      </section>
      <section className="paper" data-testid="published-economics" aria-labelledby="pub-h">
        <h2 id="pub-h">The published scenarios on the draft queue</h2>
        <p>The queue is the top K by risk among the <Fig k="cohort-scored">{queueRows[0] ? n0(queueRows[0].m["outreach_queue"].population) : "—"}</Fig> scored accounts of the <strong>published cohort</strong> at {qat.slice(0, 10)}. Their outcomes are not known yet (the window is open), so only the budget and the hypothetical value exist. Recomputed here, with the manifest's figures beside them.
          {fullWorld && fw("sc-001") && <> The same three scenarios on the <strong>whole 2,400-account world</strong> ({n0(fw("sc-001")!["scored_accounts"])} scored accounts) are worth {ds.scenarios.map((r) => `${fw(r["scenario_id"])?.["expected_value"]} at K ${r["capacity"]}`).join(", ")} (USD, hypothetical, by the domain, published in <code>cutoff_aggregates.json</code>); the two populations differ, so the two sets of figures differ.</>}</p>
        <Scroll label="Published scenarios">
          <table data-testid="published-table">
            <caption>Each scenario was fixed before any outcome was looked at; the assumptions were changed once after the first run (disclosure D-G02 item 7).</caption>
            <thead><tr><th scope="col">Scenario</th><th scope="col">K</th><th scope="col">Cost</th><th scope="col">Effect</th><th scope="col">Margin</th><th scope="col">Budget</th><th scope="col">Expected value, published cohort ({queueRows[0] ? n0(queueRows[0].m["outreach_queue"].population) : "—"} scored accounts; hypothetical)</th><th scope="col">Manifest</th>{fullWorld && <th scope="col">Expected value, full world ({n0(fw("sc-001")?.["scored_accounts"] ?? 0)} scored accounts; hypothetical)</th>}</tr></thead>
            <tbody>{queueRows.map(({ r, m }) => { const e = m["economics"]; const c = claims?.[r["scenario_id"]]; return (
              <tr key={r["scenario_id"]} data-scenario={r["scenario_id"]}><td className="l">{r["scenario_id"]}</td><td>{r["capacity"]}</td><td>{r["contact_cost"]}</td><td>{r["assumed_effect"]}</td><td>{r["margin_value"]}</td>
                <td data-k="budget">{e.contact_budget}</td><td data-k="ev" className={e.expected_value.startsWith("-") ? "neg" : ""}>{e.expected_value}</td>
                <td className="t">{c ? (c["expected_value"] === e.expected_value && c["contact_budget"] === e.contact_budget ? <Chip kind="ok">equal</Chip> : <Chip kind="risk">differs</Chip>) : "—"}</td>
                {fullWorld && <td data-k="ev-full" className={String(fw(r["scenario_id"])?.["expected_value"]).startsWith("-") ? "neg" : ""}>{fw(r["scenario_id"])?.["expected_value"] ?? "—"}</td>}</tr>); })}</tbody>
          </table>
        </Scroll>
        <p>The value turns negative as K grows: each extra contact has a lower risk and the same cost. That is the shape of the decision, and it depends entirely on the assumed effect.</p>
      </section>
      <Related also={["queue", "models"]} />
    </>
  );
}
