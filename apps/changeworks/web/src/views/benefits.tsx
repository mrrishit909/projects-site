import { Chip, Def, NoData, ParamSelect, PlateHead, Scroll, WithData, ExportCsv } from "../components/ui";
import { Link } from "../components/link";
import { scenarioIds, useScenario } from "../components/pick";
import type { Dataset } from "../data/dataset";
import { BENEFIT_TYPES, type Row } from "../domain/contract";
import { cmp, dec, div, money, p6, sumFr } from "../domain/num";
import { toCsv } from "../lib/csv";
import { partialTrend } from "../lib/derive";
import { group, n0 } from "../lib/format";
import { useParam } from "../router";
import { parseTs } from "../domain/time";

export function BenefitsView() { return <WithData>{(ds) => <Benefits ds={ds} />}</WithData>; }
const UNIT: Record<string, string> = { cash: "USD", avoided_cost: "USD", revenue: "USD", capacity: "hours" };
const LABEL: Record<string, string> = { cash: "Cash", avoided_cost: "Avoided cost", revenue: "Revenue", capacity: "Capacity" };

function Benefits({ ds }: { ds: Dataset }) {
  const [sid] = useScenario(ds);
  const [type] = useParam("type", "cash");
  const [oid, setOid] = useParam("initiative", "init-008");
  const T = (BENEFIT_TYPES as readonly string[]).includes(type) ? type : "cash";
  const acc = ds.result.population.acc;
  const sc = ds.metrics["scenarios"][sid] as Row;
  const iids = Object.keys(sc["initiatives"]).sort(cmp);
  const rows = iids.filter((i) => (sc["initiatives"][i]["benefit_realization"] as Row)[T]);
  const overview = BENEFIT_TYPES.map((t) => ({ t, rows: acc.benefit_items.filter((b) => b["benefit_type"] === t), total: sumFr(acc.benefit_items.filter((b) => b["benefit_type"] === t).map((b) => dec(b["amount"]))) }));
  const sel = iids.includes(oid) ? oid : (iids[0] ?? "");
  const items = acc.benefit_items.filter((b) => b["initiative_id"] === sel && b["benefit_type"] === T).sort((a, b) => a["period_index"] - b["period_index"] || cmp(a["benefit_id"], b["benefit_id"]));
  const obs = (b: Row): Row[] => acc.benefit_observations.filter((o) => o["benefit_id"] === b["benefit_id"]).sort((x, y) => (parseTs(x["observed_at"]) < parseTs(y["observed_at"]) ? -1 : 1));
  const csv = toCsv(["initiative", "owner", "type", "unit", "planned_comparable", "observed_comparable", "realization", "baseline_trend", "observed_above_trend", "attribution"],
    rows.map((i) => { const r = sc["initiatives"][i]["benefit_realization"][T] as Row; return [i, ds.byId.initiatives.get(i)!["sponsor_id"], T, UNIT[T], r["planned_comparable"], r["observed_comparable"], r["realization"], r["baseline_trend"], r["observed_above_trend"], r["attribution"]]; }));
  const truth = ds.manifest.synthetic_truth?.by_initiative_and_type;
  return (
    <>
      <PlateHead mark="Plate VIII" title="Benefits register">
        <p className="lede">What each initiative planned and what was observed, compared <strong>within one benefit type</strong> and only for matured periods. Cash, avoided cost, revenue and capacity are never added into one number.</p>
      </PlateHead>
      <div className="controls">
        <ParamSelect name="scenario" label="Scenario" dflt={sid} testid="scenario-picker" options={scenarioIds(ds).map((id) => ({ value: id, label: id }))} />
        <ParamSelect name="type" label="Benefit type" dflt="cash" testid="type-picker" options={BENEFIT_TYPES.map((t) => ({ value: t, label: `${LABEL[t]} (${UNIT[t]})` }))} />
      </div>
      <h2>Four classes, four units</h2>
      <Scroll label="Benefit classes">
        <table data-testid="class-overview">
          <caption>Planned benefit rows by class (each total is in its own unit and is never added to another)</caption>
          <thead><tr><th>Class</th><th>Unit</th><th className="num">Rows</th><th className="num">Planned amount, all rows</th></tr></thead>
          <tbody>{overview.map((o) => <tr key={o.t} data-class={o.t}><th scope="row">{LABEL[o.t]}</th><td>{UNIT[o.t]}</td><td className="num">{n0(o.rows.length)}</td><td className="num" data-k="total">{group(money(o.total))} {UNIT[o.t] === "hours" ? "h" : ""}</td></tr>)}</tbody>
        </table>
      </Scroll>
      <h2>Realisation within {LABEL[T].toLowerCase()} ({UNIT[T]})</h2>
      <p className="small muted" data-testid="attribution-caveat"><Chip kind="hatch">observed, not attributed</Chip> An observed improvement is shown beside the baseline trend recorded before deployment and the raw change, never in place of it. The share above the trend is not proof the rollout caused it. Unobserved matured rows are listed, not counted as zero.</p>
      {rows.length === 0 ? <NoData what="initiatives with matured observations of this type" /> : (
        <Scroll label="Realisation by initiative">
          <table data-testid="realization-table">
            <caption>Planned against observed, matured periods only, {UNIT[T]}, scenario {sid}</caption>
            <thead><tr><th>Initiative</th><th>Owner</th><th className="num">Rows compared</th><th className="num">Planned</th><th className="num">Observed (raw change)</th><th className="num">Realisation</th><th className="num">Baseline trend, beside</th><th className="num">Observed above trend</th><th className="num">Matured, unobserved</th><th>Label</th></tr></thead>
            <tbody>{rows.map((i) => {
              const r = sc["initiatives"][i]["benefit_realization"][T] as Row;
              return (
                <tr key={i} data-initiative={i} className={i === sel ? "is-on" : undefined}>
                  <th scope="row"><button type="button" className="button--quiet" onClick={() => setOid(i)} aria-label={`Show the observations of ${i}`}>{i}</button></th><td>{ds.byId.initiatives.get(i)!["sponsor_id"]}</td><td className="num">{r["comparable_items"].length}</td>
                  <td className="num" data-k="planned">{group(r["planned_comparable"])}</td><td className="num" data-k="observed">{group(r["observed_comparable"])}</td><td className="num" data-k="realization">{r["realization"] ?? "n/a"}</td>
                  <td className="num" data-k="trend">{group(r["baseline_trend"])}</td><td className="num" data-k="above">{partialTrend(ds, i, T, sid) ? "partial trend coverage" : group(r["observed_above_trend"])}</td>
                  <td className="num">{r["matured_unobserved_items"].length}</td><td><Chip kind="hatch">{r["attribution"]}</Chip></td>
                </tr>);
            })}</tbody>
          </table>
        </Scroll>
      )}
      <ExportCsv name={`realization-${sid}-${T}.csv`} csv={csv} label="Download the realisation table on screen as CSV" />
      <section aria-labelledby="h-obs">
        <h2 id="h-obs">Observation evidence: {sel}, {LABEL[T].toLowerCase()}</h2>
        {items.length === 0 ? <p className="notice">{sel} has no {LABEL[T].toLowerCase()} benefit rows. Choose another initiative from the table above.</p> : (
          <Scroll label="Benefit rows and their observations">
            <table data-testid="observations">
              <caption>Benefit rows of {sel} and every reading recorded (readings after the as-of date do not exist yet)</caption>
              <thead><tr><th>Benefit row</th><th className="num">Period</th><th className="num">Planned</th><th>Readings (date: value, evidence)</th></tr></thead>
              <tbody>{items.map((b) => (
                <tr key={b["benefit_id"]} data-benefit={b["benefit_id"]}><th scope="row" className="mono">{b["benefit_id"]}</th><td className="num">{b["period_index"]}</td><td className="num">{group(b["amount"])}</td>
                  <td className="wrapcell small">{obs(b).map((o) => `${String(o["observed_at"]).slice(0, 10)}: ${group(o["measured_value"])} (${o["evidence_ref"]})`).join("; ") || "no reading yet"}</td></tr>))}</tbody>
            </table>
          </Scroll>
        )}
      </section>
      <section aria-labelledby="h-disc" data-testid="disclosure">
        <h2 id="h-disc">Disclosure: the synthetic counterfactual</h2>
        <p className="small">In this synthetic world the generator knows how much of each observed improvement the rollout really caused. A real organisation never knows that, so the site never uses it: the table above is computed without it. It is shown here only so a reader can see how far "observed above trend" can sit from the truth.</p>
        <Def term="Attributable share by initiative (generator's truth, not an input)">
          {truth ? (
            <Scroll label="Disclosure of the attributable share">
              <table data-testid="truth-table"><caption>Generator's true attributable share for {LABEL[T].toLowerCase()}, beside what the site can see</caption>
                <thead><tr><th>Initiative</th><th className="num">True share (disclosure)</th><th className="num">Trend ÷ observed (what the site sees)</th></tr></thead>
                <tbody>{iids.filter((i) => truth[`${i}/${T}`]).map((i) => { const r = (sc["initiatives"][i]["benefit_realization"] as Row)[T] as Row | undefined; return <tr key={i} data-initiative={i}><th scope="row">{i}</th><td className="num" data-k="true-share">{truth[`${i}/${T}`]!.true_attributable_share}</td><td className="num">{r && r["baseline_trend"] && r["observed_comparable"] ? ratio6(r["baseline_trend"], r["observed_comparable"]) : "n/a"}</td></tr>; })}</tbody>
              </table>
            </Scroll>) : <span>Not available in this dataset.</span>}
        </Def>
        <p className="small muted">Owners are the sponsors of the initiatives. See also <Link to="evidence">the Evidence plate</Link> and <Link to="forecast">the forecast comparison</Link>.</p>
      </section>
    </>
  );
}
const ratio6 = (a: string, b: string): string => p6(div(dec(a), dec(b)))!;
