import { Chip, Def, ExportCsv, ParamSelect, PlateHead, Scroll, WithData, WithDataset } from "../components/ui";
import { Link } from "../components/link";
import { scenarioIds, useInitiative, useScenario } from "../components/pick";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { cmp } from "../domain/num";
import { toCsv } from "../lib/csv";
import { benefitWindow, exactOf, scenariosWith } from "../lib/derive";
import { group, month } from "../lib/format";
import { assumptionTrail } from "../lib/trail";

export function BusinessCaseView() {
  return <WithData>{(ds) => <><Case ds={ds} /><GoldenRecomputed /></>}</WithData>;
}

const REASON: Record<string, string> = { NO_INVESTMENT: "no investment: the cumulative flow is never negative", NOT_RECOVERED: "the cumulative flow ends below zero", NO_FLOWS: "no flows" };
const pb = (p: Row): string => (p["period"] === null ? `never within the horizon (null${p["reason"] ? `: ${REASON[p["reason"]] ?? p["reason"]}` : ""})` : `period ${p["period"]}, interpolated ${p["interpolated"]}`);

function Case({ ds }: { ds: Dataset }) {
  const [sid] = useScenario(ds);
  const [iid] = useInitiative(ds, sid, ds.id === "golden" ? "init-001" : "init-003");
  const blk = ds.metrics["scenarios"][sid]["initiatives"][iid] as Row;
  const sc = ds.metrics["scenarios"][sid] as Row;
  const cf = blk["cash_flow"] as Row[];
  const { trail, rate, target } = assumptionTrail(ds, sid, iid);
  const ex1 = exactOf(ds, sid, iid);
  const win = benefitWindow(ds, iid);
  const asm = ds.result.population.acc.assumption_versions.filter((a) => a["initiative_id"] === iid).sort((a, b) => cmp(a["name"], b["name"]) || a["version_number"] - b["version_number"]);
  const pinned = new Set<string>(ds.byId.scenarios.get(sid)!["pinned_assumption_ids"]);
  const ex_ = blk["excluded_from_cash_flow"] as Row;
  const warn = ((ds.metrics["initiatives"][iid] as Row)["roadmap"]["warnings"] as Row[])[0] ?? null;
  const csv = toCsv(["period", "period_start", "costs", "cash", "revenue", "avoided_cost_realised", "capacity_converted", "net_cash_flow", "cumulative", "discount_factor", "discount_factor_exact", "discounted_cash_flow", "cumulative_discounted", "assumptions"],
    cf.map((r, i) => [r["period_index"], r["period_start"], r["costs"], r["benefits_by_class"]["cash"], r["benefits_by_class"]["revenue"], r["benefits_by_class"]["avoided_cost_realised"], r["benefits_by_class"]["capacity_converted"], r["net_cash_flow"], r["cumulative"], r["discount_factor"], r["discount_factor_exact"], r["discounted_cash_flow"], r["cumulative_discounted"], trail[i]!.items.map((x) => x.text).join(" | ")]));
  void ex1;
  return (
    <>
      <PlateHead mark="Plate III" title="Business case">
        <p className="lede">The cash-flow model of one initiative in one scenario, row by row, each row beside the assumption versions that produced it; then NPV and the two paybacks, each labelled separately.</p>
      </PlateHead>
      <div className="controls">
        <ParamSelect name="scenario" label="Scenario" dflt={sid} testid="scenario-picker" options={scenarioIds(ds).map((id) => ({ value: id, label: id }))} />
        <ParamSelect name="initiative" label="Initiative" dflt={iid} testid="initiative-picker" options={Object.keys(sc["initiatives"]).sort(cmp).map((id) => ({ value: id, label: `${id} ${ds.byId.initiatives.get(id)!["title"]}` }))} />
      </div>
      <p className="muted small">{ds.byId.initiatives.get(iid)!["title"]}. Also in scenarios {scenariosWith(ds, iid).filter((s) => s !== sid).slice(0, 6).map((s) => <span key={s}><Link to={`business-case?scenario=${s}&initiative=${iid}`}>{s}</Link> </span>)}{scenariosWith(ds, iid).length > 7 ? "…" : ""}</p>
      <section aria-labelledby="h-fig" data-testid="measures">
        <h2 id="h-fig">NPV and payback <Chip kind="note">estimate</Chip></h2>
        <dl className="facts" data-testid="scenario-npv">
          <div><dt>Scenario NPV total, attributable (USD)</dt><dd data-figure="npv-attributable">{group(sc["npv_total"]["value"])}</dd></div>
          <div><dt>Sum of the initiative NPVs, beside (USD)</dt><dd data-figure="npv-sum">{group(sc["npv_total"]["sum_of_initiatives"])}</dd></div>
          <div><dt>Counted twice, present value, beside (USD)</dt><dd data-figure="double-counted-pv">{group(sc["double_count"]["double_counted_pv"])}</dd></div>
        </dl>
        {warn && <p className="notice" data-testid="deployment-warning"><Chip kind="note">deployment before feasible start</Chip> Deployment is planned in period {warn["deployment_period"]}, {warn["periods_early"]} periods before the dependency-feasible start (period {warn["dependency_feasible_start"]}). The cash flow below is the plan as recorded and is not re-timed.</p>}
        <dl className="facts">
          <div><dt>This initiative's NPV (USD, 2 places), before shared claims are removed</dt><dd data-figure="npv">{group(blk["npv"]["value"])}</dd></div>
          <div><dt>NPV, exact rational</dt><dd data-figure="npv-exact">{blk["npv"]["exact"] ?? "n/a"}</dd></div>
          <div><dt>Simple payback (undiscounted)</dt><dd data-figure="simple-payback">{pb(blk["payback"]["simple"])}</dd></div>
          <div><dt>Discounted payback</dt><dd data-figure="discounted-payback">{pb(blk["payback"]["discounted"])}</dd></div>
          <div><dt>Capacity released (hours per period)</dt><dd data-figure="capacity-released">{blk["capacity_released"]["hours"] ?? `n/a (${blk["capacity_released"]["reason"]})`}</dd></div>
          <div><dt>Rate used</dt><dd data-figure="rate" className="wrapcell">{rate.text}</dd></div>
        </dl>
        <p className="small muted">NPV = Σ CF<sub>t</sub> ÷ (1 + r)<sup>t</sup> over {sc["horizon_periods"]} periods with r = {sc["effective_period_rate_exact"]} per {String(ds.result.population.config["period_basis"]).replace("ly", "")}. {win ? `This initiative's benefit rows fall in periods ${win.from} to ${win.to - 1} (${win.rows} rows): ` : ""}the snapshot recognises benefits within a <strong>twelve-period benefit window</strong> per stream (some streams are shorter), so this is not a multi-year forecast. A payback is the period of the last crossing from below zero; it is null, not zero, when the flow never recovers, never goes negative or has no flows, and the reason is named.</p>
        {target && <p className="small muted">Target assumption {target["assumption_id"]} v{target["version_number"]}: {target["value"]} minutes per case, from the approved baseline {blk["capacity_released"]["baseline_version"] ?? "(none)"}; hours are never a payroll saving by themselves.</p>}
      </section>
      <section aria-labelledby="h-cf">
        <h2 id="h-cf">The cash-flow table</h2>
        <Scroll label="Cash-flow model with assumption versions">
          <table data-testid="cashflow-table">
            <caption>Cash flow of {iid} in {sid}, USD, period by period</caption>
            <thead><tr><th className="num">t</th><th>Month</th><th className="num">Costs</th><th className="num">Cash</th><th className="num">Revenue</th><th className="num">Avoided cost (evidenced)</th><th className="num">Capacity converted</th>
              <th className="num">Net cash flow</th><th className="num">Cumulative</th><th className="num">Discount factor</th><th className="num">Discounted flow</th><th className="num">Cumulative discounted</th><th>Assumption versions applied</th></tr></thead>
            <tbody>
              {cf.map((r, i) => (
                <tr key={r["period_index"]} data-period={r["period_index"]}>
                  <td className="num" data-k="t">{r["period_index"]}</td><td>{month(r["period_start"])}</td>
                  <td className="num" data-k="costs">{group(r["costs"])}</td>
                  <td className="num" data-k="cash">{group(r["benefits_by_class"]["cash"])}</td><td className="num" data-k="revenue">{group(r["benefits_by_class"]["revenue"])}</td>
                  <td className="num" data-k="avoided">{group(r["benefits_by_class"]["avoided_cost_realised"])}</td><td className="num" data-k="capacity-usd">{group(r["benefits_by_class"]["capacity_converted"])}</td>
                  <td className="num" data-k="net">{group(r["net_cash_flow"])}</td><td className="num" data-k="cumulative">{group(r["cumulative"])}</td>
                  <td className="num" data-k="df" title={`exact ${r["discount_factor_exact"]}`}>{r["discount_factor"]}</td>
                  <td className="num" data-k="discounted" title={`exact ${r["discounted_exact"]}`}>{group(r["discounted_cash_flow"])}</td><td className="num" data-k="cum-discounted">{group(r["cumulative_discounted"])}</td>
                  <td className="wrapcell small" data-k="assumptions"><span className="muted">rate: {i === 0 ? rate.text : "as above"}</span>{trail[i]!.items.map((x) => <span key={x.text}><br />{x.text}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
        <p className="small muted">Discount factors are exact rationals (hover for n/d), shown to 6 places; rows are rounded once, at display. Exact values: NPV {blk["npv"]["exact"] ?? "n/a"}.</p>
        <ExportCsv name={`cashflow-${sid}-${iid}.csv`} csv={csv} label="Download the cash-flow table on screen as CSV" />
      </section>
      <section aria-labelledby="h-beside" data-testid="beside">
        <h2 id="h-beside">Beside the cash flow, not in it</h2>
        <ul>
          <li data-k="capacity-excluded"><strong>Capacity hours not converted:</strong> {ex_["capacity_hours_not_converted"] ? `${group(ex_["capacity_hours_not_converted"])} h over ${(ex_["capacity_not_converted"] as Row[]).length} rows (no conversion assumption with staffing-change evidence)` : "none"}.</li>
          <li data-k="capacity-converted"><strong>Capacity converted to cash:</strong> {(blk["converted_capacity"] as Row[]).length ? `${(blk["converted_capacity"] as Row[]).length} derived items citing ${(blk["converted_capacity"] as Row[])[0]!["conversion_assumption_id"]} and ${(blk["converted_capacity"] as Row[])[0]!["staffing_change_evidence_ref"]}` : "none"}.</li>
          <li data-k="avoided-beside"><strong>Avoided cost without a removed budget line:</strong> {ex_["avoided_cost_beside_total"] ? `${group(ex_["avoided_cost_beside_total"])} USD over ${(ex_["avoided_cost_beside"] as Row[]).length} rows (${[...new Set((ex_["avoided_cost_beside"] as Row[]).map((x) => x["reason"]))].join(", ")})` : "none"}.</li>
          <li data-k="beyond"><strong>Benefit rows beyond the horizon:</strong> {(ex_["beyond_horizon"] as string[]).length}.</li>
          <li data-k="ramp"><strong>Adoption ramp:</strong> {blk["ramp"] ? `${blk["ramp"]["assumption_id"]}: ${(blk["ramp"]["values"] as string[]).join(", ")}; planned (unramped) net cash flow stays visible: ${(blk["unramped_net_cash_flow"] as string[]).slice(0, 14).map((x) => group(x)).join(", ")}${(blk["unramped_net_cash_flow"] as string[]).length > 14 ? ", …" : ""}` : "none; benefits are recognised as planned"}.</li>
          <li data-k="planned"><strong>Planned money benefits:</strong> ramped {group(blk["planned_money_benefits"]["ramped"])}, unramped {group(blk["planned_money_benefits"]["unramped"])} USD.</li>
        </ul>
      </section>
      <section aria-labelledby="h-asm">
        <h2 id="h-asm">Assumption versions of {iid}</h2>
        <Scroll label="Assumption versions">
          <table data-testid="assumptions">
            <caption>Assumptions (separate from evidence), every version; those the scenario pins are marked</caption>
            <thead><tr><th>Assumption</th><th className="num">Version</th><th>Value</th><th>Author</th><th>Created</th><th>Rationale</th><th>In {sid}</th></tr></thead>
            <tbody>
              {asm.map((a) => (
                <tr key={a["assumption_id"]} data-assumption={a["assumption_id"]}>
                  <td className="mono">{a["name"]}<br /><span className="muted">{a["assumption_id"]}</span></td><td className="num">{a["version_number"]}</td>
                  <td className="wrapcell mono">{a["value"] ?? (a["values"] as string[]).join(", ")} <span className="muted">{a["unit"] ?? ""}</span></td><td>{a["author_id"]}</td><td>{String(a["created_at"]).slice(0, 10)}</td>
                  <td className="wrapcell small">{a["rationale"]}</td><td>{pinned.has(a["assumption_id"]) ? <Chip kind="ok">pinned</Chip> : <Chip kind="plain">not pinned</Chip>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
        <p className="small muted">A scenario uses the version it pins, otherwise the latest. <Def term="Why evidence and assumptions are kept apart">Baselines are measured evidence with a source and a date; assumptions carry a version number, an author and a rationale. Changing an assumption never rewrites evidence.</Def> The monthly-rate conversion, where there is one, is itself an assumption version.</p>
      </section>
    </>
  );
}

/** The golden case, recomputed here whatever dataset the page is on. */
function GoldenRecomputed() {
  return (
    <WithDataset id="golden">{(g) => {
      const blk = g.metrics["scenarios"]["scn-001"]["initiatives"]["init-001"] as Row;
      const dc = g.metrics["scenarios"]["scn-001"]["double_count"] as Row;
      const roadmap = g.metrics["initiatives"] as Row;
      return (
        <section aria-labelledby="h-golden" data-testid="golden-case">
          <h2 id="h-golden">The golden case, recomputed in your browser</h2>
          <p>A hand-derived case: cost 1000.00 at t = 0, net inflows of 600.00 at t = 1 and t = 2, a 10 % annual rate on annual periods. The expected answer was written independently of this code (NPV = −1000 + 600/1.1 + 600/1.1² = 5000/121).</p>
          <dl className="facts">
            <div><dt>NPV</dt><dd data-g="npv">{group(blk["npv"]["value"])} = {blk["npv"]["exact"]}</dd></div>
            <div><dt>Simple payback</dt><dd data-g="simple">period {blk["payback"]["simple"]["period"]}, interpolated {blk["payback"]["simple"]["interpolated"]}</dd></div>
            <div><dt>Discounted payback</dt><dd data-g="discounted">period {blk["payback"]["discounted"]["period"]}, interpolated {blk["payback"]["discounted"]["interpolated"]}</dd></div>
            <div><dt>Capacity hours excluded from cash flow</dt><dd data-g="excluded">{blk["excluded_from_cash_flow"]["capacity_hours_not_converted"]} h</dd></div>
            <div><dt>Capacity released per period</dt><dd data-g="released">{blk["capacity_released"]["hours"]} h</dd></div>
            <div><dt>Double-count residual</dt><dd data-g="residual">{dc["residual"]} ({(dc["overlaps"] as Row[])[0]!["benefit_source_key"]})</dd></div>
            <div><dt>Dependency delays</dt><dd data-g="delays">init-002: {roadmap["init-002"]["roadmap"]["dependency_delay"]} periods; init-003: {roadmap["init-003"]["roadmap"]["dependency_delay"]} periods</dd></div>
          </dl>
          <p className="small">Every one of the 643 leaves of the expected answer is compared on the <Link to="evidence">Evidence plate</Link>. Open the whole site on it: <a href={`${import.meta.env.BASE_URL}business-case/?dataset=golden`}>?dataset=golden</a>.</p>
        </section>
      );
    }}</WithDataset>
  );
}
