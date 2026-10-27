import { useState } from "react";
import { Chip, Def, ExportCsv, NoData, ParamSelect, PlateHead, Scroll, SimNote, WithData } from "../components/ui";
import { Link } from "../components/link";
import { scenarioIds, useScenario } from "../components/pick";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { add, cmp, ge, lt, money as moneyFr, type Fr } from "../domain/num";
import { useParam } from "../router";
import { toCsv } from "../lib/csv";
import { confidence, initiativeFigures, scenarioTotals, type InitiativeFigures } from "../lib/derive";
import { bp, group, minus } from "../lib/format";
import { basisPoints } from "../lib/scale";
import { addProposal, useProposals } from "../state/sim";

const label = (c: ReturnType<typeof confidence>): string => `evidence ${c.label} (${c.score}/4)`;
const chipKind = (l: string): "ok" | "note" | "hatch" => (l === "strong" ? "ok" : l === "partial" ? "note" : "hatch");

export function PortfolioView() {
  return <WithData>{(ds) => <Portfolio ds={ds} />}</WithData>;
}

function Portfolio({ ds }: { ds: Dataset }) {
  const [sid] = useScenario(ds);
  const [prog, setProg] = useParam("programme", "all");
  const [conf, setConf] = useParam("evidence", "all");
  const [sort] = useParam("sort", "id");
  const sc = ds.metrics["scenarios"][sid] as Row;
  const totals = scenarioTotals(ds);
  const t = totals.find((x) => x.id === sid)!;
  const all = Object.keys(sc["initiatives"]).sort(cmp).map((iid) => ({ f: initiativeFigures(ds, sid, iid), c: confidence(ds, sid, iid) }));
  const programmes = ds.manifest.programmes ?? [];
  const rows = all.filter(({ f, c }) => (prog === "all" || programmes.find((p) => p.programme_id === prog)?.initiative_ids.includes(f.iid)) && (conf === "all" || c.label === conf))
    .sort((a, b) => {
      if (sort === "npv") return (a.f.npvExact === null ? 1 : b.f.npvExact === null ? -1 : cmpExact(a.f.npvExact, b.f.npvExact)) || cmp(a.f.iid, b.f.iid);
      if (sort === "costs") return -cmpFr2(a.f.costs, b.f.costs) || cmp(a.f.iid, b.f.iid);
      return cmp(a.f.iid, b.f.iid);
    });
  const clear = (): void => { setProg("all"); setConf("all"); };
  const maxBar = rows.reduce<Fr>((m, { f }) => { const ben = benefitsInFlow(f); const x = lt(m, f.costs) ? f.costs : m; return lt(x, ben) ? ben : x; }, { n: 1n, d: 1n });
  const dc = sc["double_count"] as Row;
  const csv = toCsv(["initiative", "title", "programme", "costs_usd", "cash_usd", "revenue_usd", "avoided_cost_realised_usd", "capacity_converted_usd", "avoided_cost_beside_usd", "capacity_hours_not_converted", "npv_usd", "simple_payback", "discounted_payback", "evidence"],
    rows.map(({ f, c }) => [f.iid, f.title, f.programme, money(f.costs), money(f.cash), money(f.revenue), money(f.avoided), money(f.capacityUsd), f.avoidedBeside, f.capacityHours, f.npv, f.simple["period"], f.discounted["period"], label(c)]));
  return (
    <>
      <PlateHead mark="Plate I" title="Portfolio overview">
        <p className="lede">Costs and benefits for every initiative of a scenario, the four benefit classes in separate columns, a confidence label that says how much has been measured, and the benefits two initiatives both claim, counted once. Totals are attributable: a claim that two initiatives make on one source is removed from the total and shown beside it.</p>
      </PlateHead>
      <div className="controls">
        <ParamSelect name="scenario" label="Scenario" dflt={sid} testid="scenario-picker" options={scenarioIds(ds).map((id) => ({ value: id, label: `${id}${hasResidual(ds.metrics["scenarios"][id] as Row) ? " (residual)" : ""}` }))} />
        <ParamSelect name="programme" label="Programme" dflt="all" testid="programme-filter" options={[{ value: "all", label: "All programmes" }, ...programmes.map((p) => ({ value: p.programme_id, label: p.name }))]} />
        <ParamSelect name="evidence" label="Confidence" dflt="all" testid="evidence-filter" options={[{ value: "all", label: "All labels" }, { value: "strong", label: "Evidence strong" }, { value: "partial", label: "Evidence partial" }, { value: "thin", label: "Evidence thin" }]} />
        <ParamSelect name="sort" label="Order" dflt="id" testid="sort" options={[{ value: "id", label: "Initiative id" }, { value: "npv", label: "NPV, lowest first" }, { value: "costs", label: "Costs, largest first" }]} />
      </div>
      <dl className="facts" data-testid="attributable-facts" aria-label="Attributable total">
        <div><dt>NPV total, attributable (USD)</dt><dd data-figure="npv-attributable">{group(t.npv)}</dd></div>
        <div><dt>Sum of the initiative NPVs (USD), beside</dt><dd data-figure="npv-sum">{group(t.npvSum)}</dd></div>
        <div><dt>Counted twice, present value (USD), beside</dt><dd data-figure="double-counted-pv">{group(t.doubledPv)}</dd></div>
        <div><dt>Counted twice, money (USD, ramped), beside</dt><dd data-figure="double-counted-amount">{group(t.doubledAmount)}</dd></div>
      </dl>
      <dl className="facts" data-testid="scenario-facts" aria-label="Scenario">
        <div><dt>Scenario</dt><dd data-k="scenario">{sid} · {t.status}</dd></div>
        <div><dt>Horizon</dt><dd data-k="horizon">{t.horizon} {String(ds.result.population.config["period_basis"])} periods</dd></div>
        <div><dt>Declared rate</dt><dd data-k="declared">{t.declared} ({t.rateBasis})</dd></div>
        <div><dt>Effective per-period rate</dt><dd data-k="effective">{t.effective}</dd></div>
        <div><dt>Rate source</dt><dd data-k="rate-source">{t.rateSource}</dd></div>
        <div><dt>Baseline version</dt><dd data-k="baseline">{t.baselineVersion}</dd></div>
      </dl>
      <p className="muted small" data-testid="units">Money is USD, exact then rounded once to 2 places (ROUND_HALF_UP). NPV is an estimate over the scenario horizon. Capacity is hours and never enters a dollar column without a conversion. Totals add only within a column.</p>
      <section aria-labelledby="h-init">
        <h2 id="h-init">Initiatives in {sid}</h2>
        <div className="legend" aria-hidden="true"><span><i className="sw sw--cost" />costs</span><span><i className="sw sw--ben" />benefits entering the cash flow (cash and revenue; avoided cost only with evidence; capacity only converted)</span></div>
        {rows.length === 0 ? <NoData what="initiatives" onClear={clear} /> : (
          <Scroll label="Initiatives, costs and benefits by class">
            <table data-testid="initiatives-table">
              <caption>Costs and benefits by class, USD, scenario {sid}</caption>
              <thead><tr>
                <th>Initiative</th><th>Programme</th><th className="num">Costs</th><th>Costs against flow benefits</th><th className="num">Cash</th><th className="num">Revenue</th>
                <th className="num">Avoided cost (evidenced)</th><th className="num">Capacity converted</th><th className="num">Avoided cost beside</th><th className="num">Capacity hours not converted</th>
                <th className="num">NPV</th><th className="num">Simple payback</th><th className="num">Discounted payback</th><th>Confidence</th>
              </tr></thead>
              <tbody>
                {rows.map(({ f, c }) => (
                  <tr key={f.iid} data-initiative={f.iid}>
                    <th scope="row" className="wrapcell"><Link to={`business-case?scenario=${sid}&initiative=${f.iid}`}>{f.iid}</Link><br /><span className="muted small">{f.title}</span>{f.deploymentWarning && <><br /><Chip kind="note" title={`Deployment period ${f.deploymentWarning["deployment_period"]} is ${f.deploymentWarning["periods_early"]} periods before the dependency-feasible start ${f.deploymentWarning["dependency_feasible_start"]}; the cash flow is not re-timed`}>deployment before feasible start</Chip></>}</th>
                    <td className="wrapcell small">{f.programme ?? "n/a"}</td>
                    <td className="num" data-k="costs">{group(money(f.costs))}</td>
                    <td><span className="pair" aria-hidden="true"><i className="c" style={{ width: bp(basisPoints(f.costs, maxBar)) }} /><i className="b" style={{ width: bp(basisPoints(benefitsInFlow(f), maxBar)) }} /></span></td>
                    <td className="num" data-k="cash">{group(money(f.cash))}</td>
                    <td className="num" data-k="revenue">{group(money(f.revenue))}</td>
                    <td className="num" data-k="avoided">{group(money(f.avoided))}</td>
                    <td className="num" data-k="capacity-usd">{group(money(f.capacityUsd))}</td>
                    <td className="num" data-k="avoided-beside">{group(f.avoidedBeside, "none")}</td>
                    <td className="num" data-k="capacity-hours">{f.capacityHours === null ? "none" : `${group(f.capacityHours)} h`}</td>
                    <td className={`num${f.npv?.startsWith("-") ? " neg" : ""}`} data-k="npv">{group(f.npv)}</td>
                    <td className="num" data-k="simple">{pay(f.simple)}</td>
                    <td className="num" data-k="discounted">{pay(f.discounted)}</td>
                    <td data-k="confidence"><Chip kind={chipKind(c.label)}>{label(c)}</Chip></td>
                  </tr>
                ))}
              </tbody>
              {rows.length === all.length && (
                <tfoot>
                  <tr data-total="all">
                    <th scope="row">All {rows.length}, attributable, by column</th><td />
                    <td className="num" data-k="costs">{group(t.costs)}</td><td />
                    <td className="num" data-k="cash">{group(t.cash)}</td><td className="num" data-k="revenue">{group(t.revenue)}</td><td className="num" data-k="avoided">{group(t.avoided)}</td>
                    <td className="num" data-k="capacity-usd">{group(t.capacityUsd)}</td><td className="num" data-k="avoided-beside">{group(t.avoidedBeside)}</td><td className="num" data-k="capacity-hours">{group(t.capacityHours)} h</td>
                    <td className="num" data-k="npv">{group(t.npv)}</td><td className="num" colSpan={2}>{t.neverSimple} never pay back</td><td />
                  </tr>
                  <tr data-total="listed">
                    <th scope="row">As listed row by row (plain sums)</th><td /><td /><td />
                    <td className="num" data-k="cash">{group(t.listed.cash)}</td><td className="num" data-k="revenue">{group(t.listed.revenue)}</td><td className="num" data-k="avoided">{group(t.listed.avoided)}</td>
                    <td className="num" data-k="capacity-usd">{group(t.listed.capacityUsd)}</td><td className="num" data-k="avoided-beside">{group(t.listed.avoidedBeside)}</td><td />
                    <td className="num" data-k="npv">{group(t.npvSum)}</td><td colSpan={2} /><td />
                  </tr>
                  <tr data-total="removed">
                    <th scope="row">Counted twice, removed</th><td /><td /><td />
                    <td className="num" data-k="cash">{group(t.removed.cash)}</td><td className="num" data-k="revenue">{group(t.removed.revenue)}</td><td className="num" data-k="avoided">{group(t.removed.avoided)}</td>
                    <td className="num" data-k="capacity-usd">{group(t.removed.capacityUsd)}</td><td className="num" data-k="avoided-beside">{group(t.removed.avoidedBeside)}</td><td />
                    <td className="num" data-k="npv">{group(t.doubledPv)}</td><td colSpan={2} /><td />
                  </tr>
                </tfoot>
              )}
            </table>
          </Scroll>
        )}
        <p className="small muted">"Avoided cost beside" is avoided future cost without a removed budget line, reported next to the cash flow and not in it. "Capacity hours not converted" never become dollars unless a conversion assumption with staffing-change evidence exists. A payback is the period of the last crossing of the cumulative flow from below zero to zero or above and, in brackets, the linear interpolation; "never" means null: the flow never recovers within the horizon, never goes negative (no investment) or has no flows.{" "}
          <Def term="How the confidence label is read">Four yes/no points: an approved baseline; matured benefit rows with an observation; an adoption rate with its denominator; actual cost reported against the approved baseline cost. Four or three points read strong, two partial, fewer thin. It is an assessment of how much has been measured, not a probability of success.</Def></p>
        <ExportCsv name={`portfolio-${sid}.csv`} csv={csv} label="Download the initiatives table on screen as CSV" />
      </section>
      <section aria-labelledby="h-dc" data-testid="double-count">
        <h2 id="h-dc">The double-count residual</h2>
        <p>Benefits that two initiatives claim from the same source in the same period count once, at the largest claim (D-01), in money and in hours alike. Planned money benefits less the attributable total is the residual, and the hours claimed twice are the hours residual; a residual other than 0.00 in either must be explained before a scenario can be proposed (at least 20 characters).</p>
        <dl className="facts">
          <div><dt>Planned benefits (USD, ramped)</dt><dd data-figure="planned">{group(dc["planned_benefits"])}</dd></div>
          <div><dt>Attributable benefits (USD)</dt><dd data-figure="attributable">{group(dc["attributable_benefits"])}</dd></div>
          <div><dt>Residual (USD)</dt><dd data-figure="residual">{group(dc["residual"])}</dd></div>
          <div><dt>Counted twice, present value (USD)</dt><dd data-figure="pv-doubled">{group(dc["double_counted_pv"])}</dd></div>
          <div><dt>Planned capacity hours</dt><dd data-figure="hours-planned">{group(dc["planned_hours"])}</dd></div>
          <div><dt>Attributable capacity hours</dt><dd data-figure="hours-attributable">{group(dc["attributable_hours"])}</dd></div>
          <div><dt>Hours residual</dt><dd data-figure="hours-residual">{group(dc["hours_residual"])}</dd></div>
          <div><dt>Explanation required</dt><dd data-figure="explanation">{dc["explanation_required"] ? `yes (${(dc["explanation_required_for"] as string[]).join(" and ")})` : "no"}</dd></div>
        </dl>
        {(dc["overlaps"] as Row[]).length === 0 ? <p className="notice" data-testid="no-overlap">No money benefit is claimed by two initiatives in {sid}: the money residual is 0.00.</p> : (
          <Scroll label="Shared benefit keys and the claims on them">
            <table data-testid="overlaps">
              <caption>Overlaps: one shared key, one period, two or more claims</caption>
              <thead><tr><th>Shared key</th><th className="num">Period</th><th>Claims (initiative, benefit, USD)</th><th className="num">Counted once</th><th className="num">Overlap</th></tr></thead>
              <tbody>
                {(dc["overlaps"] as Row[]).map((o) => (
                  <tr key={`${o["benefit_source_key"]}-${o["period_index"]}`} data-key={o["benefit_source_key"]} data-period={o["period_index"]}>
                    <td className="mono wrapcell">{o["benefit_source_key"]}</td><td className="num">{o["period_index"]}</td>
                    <td className="wrapcell small">{(o["claims"] as Row[]).map((c) => `${c["initiative_id"]} · ${c["benefit_id"]} · ${group(c["amount"])}`).join("; ")}</td>
                    <td className="num">{group(o["counted_once"])}</td><td className="num">{group(o["overlap"])}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><th scope="row" colSpan={4}>Residual over {(dc["overlaps"] as Row[]).length} overlapping periods</th><td className="num">{group(dc["residual"])}</td></tr></tfoot>
            </table>
          </Scroll>
        )}
        {(dc["hours_overlaps"] as Row[]).length === 0 ? <p className="notice" data-testid="no-hours-overlap">No capacity hours are claimed by two initiatives in {sid}: the hours residual is 0.00.</p> : (
          <Scroll label="Shared capacity keys and the hours claimed on them">
            <table data-testid="hours-overlaps">
              <caption>Hours overlaps: one shared capacity key, one period, two or more claims</caption>
              <thead><tr><th>Shared key</th><th className="num">Period</th><th>Claims (initiative, benefit, hours)</th><th className="num">Counted once</th><th className="num">Hours overlap</th></tr></thead>
              <tbody>
                {(dc["hours_overlaps"] as Row[]).map((o) => (
                  <tr key={`${o["benefit_source_key"]}-${o["period_index"]}`} data-key={o["benefit_source_key"]} data-period={o["period_index"]}>
                    <td className="mono wrapcell">{o["benefit_source_key"]}</td><td className="num">{o["period_index"]}</td>
                    <td className="wrapcell small">{(o["claims"] as Row[]).map((c) => `${c["initiative_id"]} · ${c["benefit_id"]} · ${group(c["hours"])} h`).join("; ")}</td>
                    <td className="num">{group(o["counted_once"])}</td><td className="num">{group(o["hours_residual"])}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><th scope="row" colSpan={4}>Hours residual over {(dc["hours_overlaps"] as Row[]).length} overlapping periods</th><td className="num">{group(dc["hours_residual"])}</td></tr></tfoot>
            </table>
          </Scroll>
        )}
      </section>
      <section aria-labelledby="h-compare">
        <h2 id="h-compare">All scenarios</h2>
        <p className="small muted">Thirty draft scenarios, each an immutable estimate. Open one to make it the scenario above.</p>
        <Scroll label="Scenario comparison">
          <table data-testid="scenario-compare">
            <caption>Scenario comparison, USD</caption>
            <thead><tr><th>Scenario</th><th className="num">Horizon</th><th>Rate</th><th className="num">Initiatives</th><th className="num">Costs</th><th className="num">NPV total (attributable)</th><th className="num">Sum of initiative NPVs</th><th className="num">Residual</th><th className="num">Hours residual</th><th className="num">No simple payback</th></tr></thead>
            <tbody>
              {totals.map((s) => (
                <tr key={s.id} data-scenario={s.id} className={s.id === sid ? "is-on" : undefined}>
                  <th scope="row"><Link to={`portfolio?scenario=${s.id}`} aria-current={s.id === sid ? "true" : undefined}>{s.id}</Link> <span className="muted small">{s.status}</span></th>
                  <td className="num">{s.horizon}</td><td className="small">{s.declared} {s.rateBasis}</td><td className="num">{s.initiatives}</td>
                  <td className="num" data-k="costs">{group(s.costs)}</td><td className="num" data-k="npv">{group(s.npv)}</td><td className="num" data-k="npv-sum">{group(s.npvSum)}</td>
                  <td className={`num${s.residual !== "0.00" ? " neg" : ""}`} data-k="residual">{group(s.residual)}</td><td className={`num${s.hoursResidual !== "0.00" ? " neg" : ""}`} data-k="hours-residual">{group(s.hoursResidual)}</td><td className="num" data-k="never">{s.neverSimple}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      </section>
      <Propose ds={ds} sid={sid} />
    </>
  );
}

const REASON: Record<string, string> = { NO_INVESTMENT: "no investment", NOT_RECOVERED: "not recovered", NO_FLOWS: "no flows" };
const pay = (p: Row): string => (p["period"] === null ? (p["reason"] ? `never (${REASON[p["reason"]] ?? p["reason"]})` : "never") : `${p["period"]} (${p["interpolated"]})`);
const hasResidual = (sc: Row): boolean => sc["double_count"]["residual"] !== "0.00" || sc["double_count"]["hours_residual"] !== "0.00";
const benefitsInFlow = (f: InitiativeFigures): Fr => add(add(f.cash, f.revenue), add(f.avoided, f.capacityUsd));
const money = (x: Fr): string => moneyFr(x);

const cmpFr2 = (a: Fr, b: Fr): number => (ge(a, b) ? (ge(b, a) ? 0 : 1) : -1);
const cmpExact = (a: string, b: string): number => {
  const p = (s: string): Fr => { const [n, d] = s.split("/"); return { n: BigInt(n!), d: BigInt(d ?? 1) }; };
  const x = p(a), y = p(b); const l = x.n * y.d, r = y.n * x.d; return l < r ? -1 : l > r ? 1 : 0;
};

const MIN_EXPLANATION = 20;
function Propose({ ds, sid }: { ds: Dataset; sid: string }) {
  const log = useProposals();
  const [why, setWhy] = useState("");
  const dc = ds.metrics["scenarios"][sid]["double_count"] as Row;
  const already = log.some((p) => p.scenario_id === sid && p.outcome === "proposed");
  function propose(): void {
    if (already) { addProposal({ scenario_id: sid, outcome: "refused", code: "ALREADY_PROPOSED", note: "a proposal is final in this simulation; reload to start again", residual: dc["residual"] }); return; }
    const keys = [...new Set([...(dc["overlaps"] as Row[]), ...(dc["hours_overlaps"] as Row[])].map((o) => o["benefit_source_key"]))].join(", ");
    const what = `residual ${dc["residual"]} USD, hours residual ${dc["hours_residual"]} h (${keys})`;
    if (dc["explanation_required"] && !why.trim()) {
      addProposal({ scenario_id: sid, outcome: "refused", code: "DOUBLE_COUNT_UNEXPLAINED", residual: dc["residual"], note: `${what}; write an explanation first` });
      return;
    }
    if (dc["explanation_required"] && why.trim().length < MIN_EXPLANATION) {
      addProposal({ scenario_id: sid, outcome: "refused", code: "EXPLANATION_TOO_SHORT", residual: dc["residual"], note: `${what}; an explanation needs at least ${MIN_EXPLANATION} characters, this has ${why.trim().length}` });
      return;
    }
    addProposal({ scenario_id: sid, outcome: "proposed", code: null, residual: dc["residual"], note: dc["explanation_required"] ? `explanation recorded: "${why.trim()}"` : "no overlap to explain" });
  }
  return (
    <section aria-labelledby="h-propose" data-testid="propose">
      <h2 id="h-propose">Propose a scenario (simulation)</h2>
      <SimNote>A selected scenario is only a <strong>proposal</strong>: the product has no funded status and never funds anything. This replays the select-scenario rule in your browser: a money or hours residual other than 0.00 needs a written explanation of at least 20 characters first.</SimNote>
      <div className="controls">
        <p style={{ margin: 0 }}>Scenario <strong>{sid}</strong>, residual <span className="mono">{dc["residual"]}</span>, hours residual <span className="mono">{dc["hours_residual"]}</span>{dc["explanation_required"] ? " (explanation required)" : ""}</p>
        <label>Explanation of the residual<textarea rows={2} value={why} onChange={(e) => setWhy(e.target.value)} data-testid="explanation" aria-describedby="explain-help" /></label>
        <span id="explain-help" className="muted small">Required when either residual is not 0.00, at least 20 characters.</span>
        <button type="button" onClick={propose} data-testid="propose-button">Propose {sid} (simulation)</button>
      </div>
      <ol className="log" data-testid="proposal-log" aria-live="polite">
        {log.length === 0 ? <li className="muted">No proposals in this session.</li> : log.map((p) => (
          <li key={p.n} data-outcome={p.outcome}>{p.outcome === "proposed" ? <Chip kind="ok">proposed (simulated)</Chip> : <Chip kind="crit">refused {p.code}</Chip>} <span className="mono">{p.scenario_id}</span> {minus(p.note)}</li>
        ))}
      </ol>
      <p className="small muted">Not offered, because it does not exist: a funded status. {Object.keys(ds.metrics["scenarios"]).length} scenarios, all draft.</p>
    </section>
  );
}
