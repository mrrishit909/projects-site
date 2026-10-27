import { Chip, NoData, PlateHead, Scroll, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { cmp, dec, fr, maxFr, rnd, type Fr } from "../domain/num";
import { useParam } from "../router";
import { group, day } from "../lib/format";
import { basisPoints } from "../lib/scale";

export function ForecastView() { return <WithData>{(ds) => <Forecast ds={ds} />}</WithData>; }
const STROKE = ["#17382b", "#b08d57", "#7d6236", "#24503d"];
const DASH = ["", "6 3", "2 3", "10 3 2 3"];

function Forecast({ ds }: { ds: Dataset }) {
  const inits = Object.keys(ds.metrics["initiatives"]).filter((i) => ds.metrics["initiatives"][i]["forecast"]).sort(cmp);
  const [pick, setPick] = useParam("initiative", inits.includes("init-003") ? "init-003" : (inits[0] ?? ""));
  const iid = inits.includes(pick) ? pick : (inits[0] ?? "");
  if (!inits.length) return <><PlateHead mark="Plate IX" title="Forecast comparison" /><NoData what="forecasts" /></>;
  const fc = ds.metrics["initiatives"][iid]["forecast"] as Row;
  const versions = fc["versions"] as Row[];
  const observed = (fc["observed"] as Row[]);
  // the latest reading per period (by reading date, then id order), matured or not
  const latest = new Map<number, Row>();
  for (const o of observed) { const cur = latest.get(o["period_index"]); if (!cur || cmp(o["observed_at"], cur["observed_at"]) >= 0) latest.set(o["period_index"], o); }
  const periods = [...new Set([...versions.flatMap((v) => (v["by_period"] as Row[]).map((r) => r["period_index"] as number)), ...latest.keys()])].sort((a, b) => a - b);
  const all: Fr[] = [...versions.flatMap((v) => (v["by_period"] as Row[]).map((r) => dec(r["amount"]))), ...[...latest.values()].map((o) => dec(o["measured_value"]))];
  const ymax = all.length ? maxFr(all) : fr(1);
  const W = 720, H = 300, L = 70, B = 36, T = 16, R = 16;
  const px = (p: number): number => L + ((periods.indexOf(p) + 0.5) * (W - L - R)) / periods.length;
  const py = (v: Fr): number => T + (H - T - B) * (1 - basisPoints(v, ymax) / 10000);
  const vmap = versions.map((v) => new Map<number, string>((v["by_period"] as Row[]).map((r) => [r["period_index"], r["amount"]])));
  return (
    <>
      <PlateHead mark="Plate IX" title="Forecast comparison">
        <p className="lede">The approved forecast, every revision and what was actually observed, with their dates. A revision never overwrites the original: version 1 stays exactly as approved.</p>
      </PlateHead>
      <div className="controls"><label>Initiative<select value={iid} onChange={(e) => setPick(e.target.value)} data-testid="forecast-picker">{inits.map((i) => <option key={i} value={i}>{i} {ds.byId.initiatives.get(i)!["title"]}</option>)}</select></label></div>
      <dl className="facts" data-testid="forecast-facts">
        <div><dt>Versions</dt><dd data-figure="versions">{versions.length}</dd></div>
        <div><dt>Original kept</dt><dd data-figure="preserved">{fc["original_preserved"] ? `yes, version ${fc["original_version"]}` : "no"}</dd></div>
        <div><dt>Latest minus original (USD, total)</dt><dd data-figure="latest-minus-original">{group(fc["latest_minus_original"])}</dd></div>
        {versions.map((v) => <div key={v["version_number"]}><dt>Version {v["version_number"]} total ({day(v["created_at"])})</dt><dd data-figure={`total-${v["version_number"]}`}>{group(v["total"])}</dd></div>)}
      </dl>
      <div className="legend" aria-hidden="true">{versions.map((v, k) => <span key={v["version_number"]}><svg width="26" height="8" aria-hidden="true"><line x1="0" x2="26" y1="4" y2="4" stroke={STROKE[k % 4]} strokeWidth="2" strokeDasharray={DASH[k % 4]} /></svg> version {v["version_number"]}</span>)}<span>● observed (filled: matured period, hollow: not matured)</span></div>
      <svg className="plate-svg" role="img" aria-label={`Forecast versions and observed values of ${iid} by period; the table below has the same figures`} viewBox={`0 0 ${W} ${H}`} data-testid="forecast-chart">
        {[0, 1, 2, 3, 4].map((k) => <g key={k}><line className="grid" x1={L} x2={W - R} y1={T + ((H - T - B) * k) / 4} y2={T + ((H - T - B) * k) / 4} /></g>)}
        <line className="axis" x1={L} x2={L} y1={T} y2={H - B} /><line className="axis" x1={L} x2={W - R} y1={H - B} y2={H - B} />
        <text x={4} y={T + 10} fontSize="10" className="mono">{group(rnd(ymax, 2))}</text><text x={4} y={H - B} fontSize="10" className="mono">0</text>
        {periods.map((p) => <text key={p} x={px(p)} y={H - 18} fontSize="10" textAnchor="middle" className="mono">{p}</text>)}
        <text x={L} y={H - 4} fontSize="10">period index; USD per period</text>
        {versions.map((v, k) => <polyline key={v["version_number"]} fill="none" stroke={STROKE[k % 4]} strokeWidth="2" strokeDasharray={DASH[k % 4]} points={(v["by_period"] as Row[]).map((r) => `${px(r["period_index"])},${py(dec(r["amount"]))}`).join(" ")} />)}
        {[...latest.values()].map((o) => <circle key={o["period_index"]} cx={px(o["period_index"])} cy={py(dec(o["measured_value"]))} r={4.5} fill={o["period_matured"] ? "#9e3b2f" : "#f9f3e4"} stroke="#9e3b2f" strokeWidth="2"><title>{`period ${o["period_index"]}: ${o["measured_value"]} observed ${day(o["observed_at"])}`}</title></circle>)}
      </svg>
      <h2>The same figures as a table</h2>
      <Scroll label="Forecast by version and observed value">
        <table data-testid="forecast-table">
          <caption>{iid}: forecast by version and the latest observed reading, USD per period</caption>
          <thead><tr><th className="num">Period</th>{versions.map((v) => <th key={v["version_number"]} className="num">Version {v["version_number"]}<br /><span className="muted">{day(v["created_at"])}</span></th>)}<th className="num">Observed (latest reading)</th><th>Reading date</th><th>Matured</th></tr></thead>
          <tbody>{periods.map((p) => {
            const o = latest.get(p);
            return <tr key={p} data-period={p}><td className="num">{p}</td>{vmap.map((m, k) => <td key={k} className="num" data-k={`v${versions[k]!["version_number"]}`}>{group(m.get(p) ?? null, "")}</td>)}<td className="num" data-k="observed">{o ? group(o["measured_value"]) : ""}</td><td className="small">{o ? day(o["observed_at"]) : ""}</td><td>{o ? (o["period_matured"] ? "yes" : "not yet") : ""}</td></tr>;
          })}</tbody>
          <tfoot><tr><th scope="row">Total</th>{versions.map((v) => <td key={v["version_number"]} className="num">{group(v["total"])}</td>)}<td colSpan={3} /></tr></tfoot>
        </table>
      </Scroll>
      <h2>Why each revision was made</h2>
      <ol data-testid="revisions">{versions.map((v) => <li key={v["version_number"]}><strong>Version {v["version_number"]}</strong>, {day(v["created_at"])}: {v["reason"]}. {v["version_number"] > versions[0]!["version_number"] ? <Chip kind="note">revision, original kept</Chip> : <Chip kind="ok">approved original</Chip>}</li>)}</ol>
      <p className="small muted">Observed values are readings of the cash benefit of this initiative; several readings of one period are listed in the benefits register, and a reading after the as-of date does not exist yet. A forecast total is the sum of its period amounts and says nothing about periods outside the forecast. Revising a forecast is a sponsor command in the backend; this static site only reads the versions.</p>
    </>
  );
}
